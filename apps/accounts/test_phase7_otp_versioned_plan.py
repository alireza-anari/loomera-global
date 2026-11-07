"""Phase 7.9 offline OTP drain and no-live-wiring security guards."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_transition_plan import (
    OfflineOtpDrainEvidence,
    OfflineOtpTransitionDecision,
    assess_offline_otp_drain,
)
from loomera.globalization import otp_versioned_gate_rehearsal as gate

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_9_EXIT_MATRIX.json"
AUTH_PATHS = (
    "apps/api/v1/auth_otp.py",
    "apps/api/v1/auth_views.py",
    "apps/accounts/views.py",
    "apps/accounts/models.py",
)
VALID = OfflineOtpDrainEvidence(
    inventory_complete=True,
    legacy_writers_frozen=True,
    cache_backend_healthy=True,
    session_scope_complete=True,
    api_legacy_pending=0, web_signup_pending=0,
    password_reset_pending=0, unknown_format_pending=0,
    last_legacy_issue_ts=1000, longest_legacy_ttl_seconds=120,
    now_ts=1150,
)


class Phase79OtpOfflinePlanTests(SimpleTestCase):
    def evaluate(self, **values):
        return assess_offline_otp_drain(replace(VALID, **values))

    def test_full_synthetic_drain_only_allows_simulation(self):
        self.assertEqual(self.evaluate(), OfflineOtpTransitionDecision("simulation_ready"))
        self.assertFalse(self.evaluate().production_cutover_authorized)
        self.assertFalse(self.evaluate().rollback_to_legacy_authorized)
        self.assertFalse(self.evaluate().authenticated)

    def test_inventory_must_cover_all_cache_and_session_scopes(self):
        for field in ("inventory_complete", "session_scope_complete"):
            with self.subTest(field=field):
                self.assertEqual(
                    self.evaluate(**{field: False}).status, "inventory_untrusted",
                )

    def test_failed_backend_blocks_even_empty_snapshot(self):
        self.assertEqual(
            self.evaluate(cache_backend_healthy=False).status,
            "backend_unavailable",
        )

    def test_writers_must_freeze_before_drain_approval(self):
        self.assertEqual(
            self.evaluate(legacy_writers_frozen=False).status,
            "writers_not_frozen",
        )

    def test_each_historical_consumer_independently_blocks(self):
        statuses = {
            "api_legacy_pending": "api_legacy_pending",
            "web_signup_pending": "web_signup_pending",
            "password_reset_pending": "password_reset_pending",
            "unknown_format_pending": "unknown_legacy_formats",
        }
        for field, expected in statuses.items():
            with self.subTest(field=field):
                self.assertEqual(self.evaluate(**{field: 1}).status, expected)

    def test_explicit_ttl_and_clock_margin_wait_before_simulation(self):
        decision = self.evaluate(now_ts=1110)
        self.assertEqual(decision.status, "drain_window_active")
        self.assertEqual(decision.seconds_until_rehearsal, 40)
        self.assertFalse(decision.production_cutover_authorized)
        self.assertEqual(self.evaluate(now_ts=1150).status, "simulation_ready")

    def test_inconsistent_clock_blocks_even_when_cache_empty(self):
        self.assertEqual(
            self.evaluate(now_ts=999).status, "clock_inconsistent",
        )

    def test_unknown_or_invalid_counts_are_rejected_without_coercion(self):
        for value in (-1, True, 1.5, None, "0", 1_000_001):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.evaluate(api_legacy_pending=value)

    def test_unbounded_or_ambiguous_time_values_are_rejected(self):
        for field, value in (
            ("now_ts", True), ("last_legacy_issue_ts", -1),
            ("longest_legacy_ttl_seconds", 0),
            ("longest_legacy_ttl_seconds", 86401),
            ("clock_margin_seconds", 0),
            ("clock_margin_seconds", 3601),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    self.evaluate(**{field: value})

    def test_boolean_evidence_must_be_exact_boolean(self):
        for invalid in (0, 1, None, "true"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.evaluate(inventory_complete=invalid)

    def test_only_metadata_evidence_objects_are_accepted(self):
        with self.assertRaises(TypeError):
            assess_offline_otp_drain({"mobile_number": "09123456789"})

    def test_rehearsal_has_no_live_auth_or_session_import(self):
        for path in AUTH_PATHS:
            code = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("otp_transition_plan", code)
                self.assertNotIn("otp_versioned_gate_rehearsal", code)
                self.assertNotIn("SyntheticOtpVersionGate", code)

    def test_isolated_gate_uses_one_key_and_never_authenticates(self):
        src = inspect.getsource(gate)
        self.assertIn('LOOMERA_PHASE79_TEST_REDIS', src)
        self.assertIn('db != 15', src)
        for script in (
            gate.SEED_SCRIPT, gate.RECONCILE_SCRIPT, gate.ACTIVATE_SCRIPT,
            gate.WOULD_ISSUE_SCRIPT, gate.HALT_SCRIPT,
        ):
            self.assertIn("KEYS[1]", script)
            self.assertNotIn("KEYS[2]", script)
            for disallowed in ("FLUSHDB", "FLUSHALL", "EVALSHA", "SCAN", "KEYS *"):
                self.assertNotIn(disallowed, script)
        for disallowed in (
            "django.contrib.auth", "login(request", "request.session",
            "apps.accounts.models", "apps.api.v1", ".objects.",
        ):
            self.assertNotIn(disallowed, src)

    def test_phase79_release_matrix_does_not_grant_cutover(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.9")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "6fcbcd1cdd6d63ebc54153b0a9e288ffd3069cac",
        )
        for name in (
            "live_otp_consumer_wired", "real_session_store_accessed",
            "real_accounts_accessed", "real_challenges_migrated",
            "production_atomic_otp_race_fixed", "production_cutover_authorized",
            "rollback_to_legacy_authorized", "deployed",
        ):
            self.assertFalse(matrix[name], name)
        self.assertIn("BLOCKED", matrix["release_gate"])
