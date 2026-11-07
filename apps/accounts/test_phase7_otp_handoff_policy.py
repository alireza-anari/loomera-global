"""Phase 7.10 synthetic-only session and API-compatibility release barriers."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_v2_session_policy import (
    SyntheticSessionEvidence,
    SyntheticSessionReview,
    review_synthetic_session_handoff,
)
from loomera.globalization import otp_v2_atomic_handoff_rehearsal as model

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_10_EXIT_MATRIX.json"
VALID = SyntheticSessionEvidence(
    atomic_consume_confirmed=True, generation_fenced=True,
    purpose_bound=True, legacy_identity_unchanged=True,
    exactly_one_active_account=True, account_not_deleting=True,
    no_outstanding_password_reset_grant=True, cache_healthy=True,
    session_store_healthy=True, session_not_previously_admitted=True,
    receipt_within_deadline=True, not_halted=True,
)


class Phase710SyntheticSessionTests(SimpleTestCase):
    def review(self, **changes):
        return review_synthetic_session_handoff(replace(VALID, **changes))

    def test_all_claimed_evidence_remains_simulation_only(self):
        self.assertEqual(
            self.review(), SyntheticSessionReview("simulation_candidate"),
        )
        self.assertFalse(self.review().authenticated)
        self.assertFalse(self.review().session_created)
        self.assertFalse(self.review().production_authorized)
        self.assertFalse(self.review().rollback_to_legacy_authorized)

    def test_stopped_generation_fails_closed(self):
        self.assertEqual(self.review(not_halted=False).status, "halted")

    def test_uncertain_backend_and_session_store_block(self):
        self.assertEqual(
            self.review(cache_healthy=False).status, "cache_unavailable",
        )
        self.assertEqual(
            self.review(session_store_healthy=False).status,
            "session_store_unavailable",
        )

    def test_generation_mismatch_denies_handoff(self):
        self.assertEqual(
            self.review(generation_fenced=False).status, "stale_generation",
        )

    def test_wrong_purpose_denies_handoff(self):
        self.assertEqual(self.review(purpose_bound=False).status, "wrong_purpose")

    def test_unconfirmed_consume_denies_login(self):
        self.assertEqual(
            self.review(atomic_consume_confirmed=False).status,
            "unconfirmed_consume",
        )

    def test_expired_receipt_denies_handoff(self):
        self.assertEqual(
            self.review(receipt_within_deadline=False).status,
            "receipt_expired",
        )

    def test_legacy_mobile_identity_change_denies(self):
        self.assertEqual(
            self.review(legacy_identity_unchanged=False).status,
            "identity_changed",
        )

    def test_inactive_or_ambiguous_account_denies(self):
        self.assertEqual(
            self.review(exactly_one_active_account=False).status,
            "active_account_not_unique",
        )

    def test_account_deletion_or_deactivation_race_denies(self):
        self.assertEqual(
            self.review(account_not_deleting=False).status,
            "account_deactivation_pending",
        )

    def test_password_reset_grant_must_not_bridge(self):
        self.assertEqual(
            self.review(no_outstanding_password_reset_grant=False).status,
            "reset_grant_pending",
        )

    def test_previous_session_grant_never_reused(self):
        self.assertEqual(
            self.review(session_not_previously_admitted=False).status,
            "already_admitted",
        )

    def test_wrong_evidence_shape_is_rejected(self):
        with self.assertRaises(TypeError):
            review_synthetic_session_handoff({"legacy_mobile": "09123456789"})

    def test_truthy_non_boolean_values_are_not_accepted(self):
        for value in (1, "true", None, [True]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.review(atomic_consume_confirmed=value)

    def test_live_api_and_historical_web_auth_remain_unwired(self):
        for path in (
            "apps/api/v1/auth_otp.py",
            "apps/api/v1/auth_views.py",
            "apps/accounts/views.py",
            "apps/accounts/models.py",
        ):
            with self.subTest(path=path):
                source = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("otp_v2_session_policy", source)
                self.assertNotIn("otp_v2_atomic_handoff_rehearsal", source)
                self.assertNotIn("SyntheticOtpV2HandoffRehearsal", source)

    def test_experimental_scripts_do_not_address_second_key(self):
        for script in (
            model.BOOT_SCRIPT, model.ACTIVATE_SCRIPT, model.ISSUE_SCRIPT,
            model.VERIFY_SCRIPT, model.ADMIT_SCRIPT, model.HALT_SCRIPT,
        ):
            self.assertIn("KEYS[1]", script)
            self.assertNotIn("KEYS[2]", script)
            for unsafe in ("FLUSHDB", "FLUSHALL", "SCAN", "EVALSHA"):
                self.assertNotIn(unsafe, script)
        src = inspect.getsource(model)
        self.assertIn("LOOMERA_PHASE710_TEST_REDIS", src)
        self.assertIn("db != 15", src)
        for unsafe in (
            "django.contrib.auth", "apps.accounts.models", "apps.api.v1",
            "login(request", "request.session", ".objects.",
        ):
            self.assertNotIn(unsafe, src)

    def test_live_api_still_has_known_legacy_replay_gap(self):
        # Explicit visibility: Phase 7.10 does NOT claim this issue is fixed.
        source = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        verify = source[source.index("def verify_api_otp_code("):]
        self.assertIn("record = _cache_get(key)", verify)
        self.assertIn("secrets.compare_digest", verify)
        self.assertIn('context="verified"', verify)
        helper = source[source.index("def _cache_delete("):source.index("def _increment_hour_rate(")]
        self.assertIn("cache.delete(key)", helper)
        self.assertIn("return True", helper)

    def test_exit_matrix_requires_real_approval(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.10")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "62a4dc26ca96949afd0f82e86ccaa18bdd2c23c9",
        )
        for key in (
            "live_api_otp_modified", "live_session_created",
            "real_otp_verified", "real_account_accessed",
            "legacy_replay_race_fixed", "prod_version_gate_durable",
            "production_cutover_authorized", "deployed",
        ):
            self.assertIs(matrix[key], False, key)
        self.assertTrue(matrix["release_gate"].startswith("BLOCKED"))
