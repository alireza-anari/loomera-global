"""Phase 7.12 offline restart/failover evidence and live-auth no-wiring checks."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_restart_evidence_policy import (
    SyntheticRestartDecision,
    SyntheticRestartEvidence,
    assess_synthetic_restart,
)
from loomera.globalization import otp_restart_marker_rehearsal as redis_model

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_12_EXIT_MATRIX.json"
GOOD = SyntheticRestartEvidence(
    redis_health="healthy", reference_marker="verified",
    volatile_marker="verified", expected_generation=3,
    reference_generation=3, volatile_generation=3,
    reference_mode="observing", volatile_mode="observing",
    fingerprint_matches=True, topology="standalone",
    topology_independently_verified=True, session_ledger="settled",
    owner_inventory_complete=True, legacy_writers_frozen=True,
    reset_grants_drained=True, owner_signoff_claimed=True,
)


class Phase712RestartEvidenceTests(SimpleTestCase):
    def review(self, **changes):
        return assess_synthetic_restart(replace(GOOD, **changes))

    def test_all_claimed_green_remains_manual_only(self):
        decision = self.review()
        self.assertEqual(decision, SyntheticRestartDecision("manual_review_only"))
        self.assertTrue(decision.human_reconciliation_required)
        for attr in (
            "can_authenticate", "can_reissue_otp", "can_resume_issuance",
            "can_recreate_missing_marker", "can_retry_session_write",
            "legacy_fallback_authorized", "production_cutover_authorized",
        ):
            self.assertIs(getattr(decision, attr), False, attr)

    def test_redis_outage_timeout_and_unknown_never_reopen(self):
        for value in ("timeout", "unavailable", "unknown"):
            with self.subTest(value=value):
                self.assertEqual(self.review(redis_health=value).status, "redis_untrusted")

    def test_reference_marker_all_failure_modes(self):
        for value in ("missing", "stale", "corrupt", "unreadable"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.review(reference_marker=value).status, "reference_untrusted",
                )

    def test_volatile_marker_all_failure_modes(self):
        for value in ("missing", "stale", "corrupt", "unreadable"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.review(volatile_marker=value).status, "volatile_untrusted",
                )

    def test_fingerprint_conflict_denies(self):
        self.assertEqual(
            self.review(fingerprint_matches=False).status, "fingerprint_mismatch",
        )

    def test_promoted_replica_epoch_regression_denies(self):
        self.assertEqual(
            self.review(volatile_generation=2).status, "generation_regressed",
        )

    def test_reference_lag_or_uncommitted_future_epoch_denies(self):
        self.assertEqual(
            self.review(volatile_generation=4).status, "generation_ahead_untrusted",
        )

    def test_caller_expected_generation_mismatch_denies(self):
        self.assertEqual(
            self.review(expected_generation=2).status, "expected_generation_mismatch",
        )

    def test_reference_and_volatile_mode_conflict_denies(self):
        self.assertEqual(
            self.review(volatile_mode="quarantined").status, "mode_conflict",
        )

    def test_unknown_mode_denies(self):
        self.assertEqual(
            self.review(reference_mode="unknown", volatile_mode="unknown").status,
            "mode_unknown",
        )

    def test_terminal_halt_not_restartable(self):
        result = self.review(reference_mode="halted", volatile_mode="halted")
        self.assertEqual(result.status, "terminal_halt")
        self.assertFalse(result.can_resume_issuance)

    def test_quarantine_not_restartable(self):
        result = self.review(
            reference_mode="quarantined", volatile_mode="quarantined",
        )
        self.assertEqual(result.status, "quarantined")
        self.assertFalse(result.can_reissue_otp)

    def test_unknown_promoted_split_brain_topology_denies(self):
        for value in ("promoted", "unknown", "split_brain"):
            with self.subTest(value=value):
                self.assertEqual(self.review(topology=value).status, "topology_untrusted")

    def test_standalone_topology_requires_independent_verification(self):
        self.assertEqual(
            self.review(topology_independently_verified=False).status,
            "topology_untrusted",
        )

    def test_session_ledger_timeout_or_pending_denies(self):
        for value in ("pending", "ambiguous", "unavailable"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.review(session_ledger=value).status, "session_ledger_untrusted",
                )
                self.assertFalse(self.review(session_ledger=value).can_retry_session_write)

    def test_missing_inventory_evidence_denies(self):
        self.assertEqual(
            self.review(owner_inventory_complete=False).status, "inventory_untrusted",
        )

    def test_unfrozen_legacy_writer_denies(self):
        self.assertEqual(
            self.review(legacy_writers_frozen=False).status, "writers_not_frozen",
        )

    def test_password_reset_grant_not_drained_denies(self):
        self.assertEqual(
            self.review(reset_grants_drained=False).status, "reset_grants_pending",
        )

    def test_missing_owner_signoff_denies(self):
        self.assertEqual(
            self.review(owner_signoff_claimed=False).status, "owner_signoff_missing",
        )

    def test_wrong_evidence_type_rejected_not_coerced(self):
        with self.assertRaises(TypeError):
            assess_synthetic_restart({
                "phone_number": "09123456789",
                "otp": "123456",
            })

    def test_unknown_enum_values_rejected(self):
        for field in (
            "redis_health", "reference_marker", "volatile_marker",
            "reference_mode", "volatile_mode", "topology", "session_ledger",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.review(**{field: "unrecognized"})

    def test_truthy_non_boolean_values_rejected(self):
        for field in (
            "fingerprint_matches", "topology_independently_verified",
            "owner_inventory_complete", "legacy_writers_frozen",
            "reset_grants_drained", "owner_signoff_claimed",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.review(**{field: 1})

    def test_invalid_generation_and_boolean_as_int_rejected(self):
        for field in (
            "expected_generation", "reference_generation", "volatile_generation",
        ):
            for value in (0, -1, 1_000_000_001, True, "3", None):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.review(**{field: value})

    def test_no_live_api_web_or_session_wiring(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            source = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("otp_restart_evidence_policy", source)
                self.assertNotIn("otp_restart_marker_rehearsal", source)

    def test_two_key_scripts_fixtures_only(self):
        for script in (redis_model.INITIALIZE_SCRIPT, redis_model.FENCE_SCRIPT):
            self.assertIn("KEYS[1]", script)
            self.assertIn("KEYS[2]", script)
            self.assertNotIn("KEYS[3]", script)
            for command in ("FLUSHALL", "FLUSHDB", "SCAN", "KEYS *"):
                self.assertNotIn(command, script)
        src = inspect.getsource(redis_model)
        self.assertIn("LOOMERA_PHASE712_TEST_REDIS", src)
        self.assertIn("db != 15", src)
        for disallowed in (
            "django.contrib.auth", "apps.accounts.models", "apps.api.v1",
            "login(request", ".objects.", "request.session",
        ):
            self.assertNotIn(disallowed, src)

    def test_live_legacy_replay_gap_remains_unfixed(self):
        src = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        verifier = src[src.index("def verify_api_otp_code("):]
        self.assertIn("record = _cache_get(key)", verifier)
        self.assertIn("secrets.compare_digest", verifier)
        self.assertIn('context="verified"', verifier)

    def test_release_matrix_remains_explicitly_blocked(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.12")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "b491b3c0bdf895475c8e191248ed908375695205",
        )
        for flag in (
            "real_redis_restart_tested", "real_redis_failover_tested",
            "independent_durable_anchor_verified", "live_auth_wired",
            "real_sessions_accessed", "real_accounts_accessed",
            "production_cutover_authorized", "legacy_replay_race_fixed",
            "legacy_fallback_authorized", "deployed",
        ):
            self.assertIs(matrix[flag], False, flag)
        self.assertTrue(matrix["release_gate"].startswith("BLOCKED"))
