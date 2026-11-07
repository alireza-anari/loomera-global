"""Phase 7.13 AOF restart evidence policy, scope and release-barrier tests."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_aof_restart_policy import (
    SyntheticAofRestartEvidence, SyntheticAofRestartReview,
    review_synthetic_aof_restart,
)
from loomera.globalization import otp_aof_process_restart_rehearsal as runtime

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_13_EXIT_MATRIX.json"
VALID = SyntheticAofRestartEvidence(
    shutdown="graceful", persistence="aof", appendfsync="always",
    docker_isolated=True, fresh_process=True, same_test_volume=True,
    reference_marker="verified", volatile_marker="verified",
    expected_generation=2, observed_generation=2,
    mode_before="observing", mode_after="observing",
    fingerprint_matches=True, reason_matches=True,
    last_write_ack="confirmed", no_real_data=True,
    session_store_untouched=True, legacy_path_untouched=True,
)


class Phase713AofRestartSafetyTests(SimpleTestCase):
    def review(self, **changes):
        return review_synthetic_aof_restart(replace(VALID, **changes))

    def test_all_green_is_never_production_authorization(self):
        result = self.review()
        self.assertEqual(
            result, SyntheticAofRestartReview("isolated_restart_observed_only"),
        )
        self.assertTrue(result.security_review_required)
        for name in (
            "real_failover_proven", "independently_durable_marker_proven",
            "authenticated", "otp_reissue_allowed", "resume_allowed",
            "missing_marker_reseed_allowed", "session_retry_allowed",
            "legacy_fallback_allowed", "production_recovery_authorized",
        ):
            self.assertIs(getattr(result, name), False, name)

    def test_sigkill_case_can_only_be_synthetic_observation(self):
        self.assertEqual(
            self.review(shutdown="sigkill").status,
            "isolated_restart_observed_only",
        )

    def test_unexecuted_restart_denied(self):
        self.assertEqual(
            self.review(shutdown="not_executed").status, "restart_not_proven",
        )

    def test_process_restarted_flag_required(self):
        self.assertEqual(
            self.review(fresh_process=False).status, "restart_not_proven",
        )

    def test_nonisolated_docker_denied(self):
        self.assertEqual(
            self.review(docker_isolated=False).status, "unsafe_test_scope",
        )

    def test_real_data_scope_denied(self):
        self.assertEqual(
            self.review(no_real_data=False).status, "unsafe_test_scope",
        )

    def test_rdb_only_and_disabled_persistence_denied(self):
        for value in ("rdb_only", "disabled", "unknown"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.review(persistence=value).status, "aof_not_verified",
                )

    def test_non_always_fsync_denied(self):
        for value in ("everysec", "no", "unknown"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.review(appendfsync=value).status, "aof_not_verified",
                )

    def test_missing_or_new_volume_denied(self):
        self.assertEqual(
            self.review(same_test_volume=False).status, "volume_untrusted",
        )

    def test_reference_lost_or_corrupt_denied(self):
        for value in ("missing", "corrupt", "unreadable"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.review(reference_marker=value).status,
                    "reference_untrusted",
                )

    def test_volatile_lost_or_corrupt_denied(self):
        for value in ("missing", "corrupt", "unreadable"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.review(volatile_marker=value).status,
                    "volatile_untrusted",
                )

    def test_regressed_generation_denied(self):
        self.assertEqual(
            self.review(observed_generation=1).status, "generation_regressed",
        )

    def test_future_generation_denied(self):
        self.assertEqual(
            self.review(observed_generation=3).status,
            "future_generation_untrusted",
        )

    def test_fingerprint_mismatch_denied(self):
        self.assertEqual(
            self.review(fingerprint_matches=False).status,
            "fingerprint_mismatch",
        )

    def test_quarantine_cause_mismatch_denied(self):
        self.assertEqual(
            self.review(reason_matches=False).status,
            "quarantine_reason_mismatch",
        )

    def test_mode_transition_during_restart_denied(self):
        self.assertEqual(
            self.review(mode_after="halted").status,
            "mode_changed_during_restart",
        )

    def test_unknown_mode_denied(self):
        self.assertEqual(
            self.review(mode_before="unknown", mode_after="unknown").status,
            "mode_unknown",
        )

    def test_lost_write_ack_denied(self):
        for value in ("timeout", "unknown"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.review(last_write_ack=value).status,
                    "write_outcome_ambiguous",
                )

    def test_session_store_untouched_required(self):
        self.assertEqual(
            self.review(session_store_untouched=False).status,
            "live_path_boundary_violation",
        )

    def test_legacy_path_untouched_required(self):
        self.assertEqual(
            self.review(legacy_path_untouched=False).status,
            "live_path_boundary_violation",
        )

    def test_halt_persists_without_reopening(self):
        result = self.review(mode_before="halted", mode_after="halted")
        self.assertEqual(result.status, "halted_marker_observed")
        self.assertFalse(result.resume_allowed)

    def test_quarantine_persists_without_reopening(self):
        result = self.review(
            mode_before="quarantined", mode_after="quarantined",
        )
        self.assertEqual(result.status, "quarantined_marker_observed")
        self.assertFalse(result.otp_reissue_allowed)

    def test_invalid_evidence_container_rejected(self):
        with self.assertRaises(TypeError):
            review_synthetic_aof_restart({"user": "a", "otp": "123456"})

    def test_invalid_enumeration_rejected(self):
        for field in (
            "shutdown", "persistence", "appendfsync",
            "reference_marker", "volatile_marker", "mode_before",
            "mode_after", "last_write_ack",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.review(**{field: "invalid"})

    def test_boolean_coercion_rejected(self):
        for field in (
            "docker_isolated", "fresh_process", "same_test_volume",
            "fingerprint_matches", "reason_matches", "no_real_data",
            "session_store_untouched", "legacy_path_untouched",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.review(**{field: 1})

    def test_invalid_and_bool_generations_rejected(self):
        for field in ("expected_generation", "observed_generation"):
            for value in (0, -1, 1_000_000_001, True, "2", None):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.review(**{field: value})

    def test_no_live_otp_or_session_import(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            with self.subTest(path=path):
                source = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("otp_aof_process_restart_rehearsal", source)
                self.assertNotIn("otp_aof_restart_policy", source)

    def test_dedicated_port_6392_and_two_owned_keys_only(self):
        source = inspect.getsource(runtime)
        self.assertIn('LOOMERA_PHASE713_TEST_REDIS', source)
        self.assertIn('LOOMERA_PHASE713_ALLOW_TEST_SEED', source)
        self.assertIn("port != 6392", source)
        self.assertIn("db != 15", source)
        self.assertIn("otp_restart_marker_rehearsal import", source)
        for fragment in (
            "django.contrib.auth", "apps.accounts.models",
            "apps.api.v1", "request.session", "login(request", ".objects.",
            "FLUSHDB", "FLUSHALL", "SCAN",
        ):
            self.assertNotIn(fragment, source)

    def test_live_verifier_replay_gap_still_unfixed(self):
        src = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        verification = src[src.index("def verify_api_otp_code("):]
        self.assertIn("record = _cache_get(key)", verification)
        self.assertIn("secrets.compare_digest", verification)
        self.assertIn('context="verified"', verification)

    def test_release_matrix_remains_blocked(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.13")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "753966d8984ac003a379f4e07c639c8a4435e31c",
        )
        for flag in (
            "real_redis_failover_tested", "replica_promotion_tested",
            "independent_durable_anchor_verified",
            "live_auth_wired", "real_account_accessed",
            "real_session_created", "legacy_replay_race_fixed",
            "production_recovery_authorized", "deployed",
        ):
            self.assertIs(matrix[flag], False, flag)
        self.assertTrue(matrix["release_gate"].startswith("BLOCKED"))
