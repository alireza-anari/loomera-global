"""Phase 7.11 synthetic cross-store OTP recovery policy / release guards."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_cross_store_recovery_policy import (
    SyntheticCrossStoreEvidence,
    SyntheticRecoveryDecision,
    assess_synthetic_cross_store_recovery,
)
from loomera.globalization import otp_recovery_quarantine_rehearsal as rehearsal


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_11_EXIT_MATRIX.json"
GOOD = SyntheticCrossStoreEvidence(
    redis_read="healthy", marker="pinned",
    expected_generation=2, observed_generation=2,
    challenge="consumed", consume_acknowledged=True,
    account="active", authoritative_account_snapshot=True,
    session_write="claimed", authoritative_session_snapshot=True,
    reset_grants_drained=True, inventory_trusted=True,
    quarantine_acknowledged=True, operator_halted=False,
)


class Phase711CrossStoreRecoveryTests(SimpleTestCase):
    def review(self, **kwargs):
        return assess_synthetic_cross_store_recovery(replace(GOOD, **kwargs))

    def test_every_green_claim_is_observation_only(self):
        self.assertEqual(self.review(), SyntheticRecoveryDecision("manual_review_only"))
        self.assertFalse(self.review().authenticated)
        self.assertFalse(self.review().session_created)
        self.assertFalse(self.review().safe_to_retry_otp)
        self.assertFalse(self.review().safe_to_retry_session_write)
        self.assertFalse(self.review().production_recovery_authorized)
        self.assertFalse(self.review().legacy_fallback_authorized)
        self.assertTrue(self.review().manual_reconciliation_required)

    def test_emergency_halt_overrides_other_claims(self):
        self.assertEqual(
            self.review(operator_halted=True, redis_read="timeout").status, "halted",
        )

    def test_cache_unavailable_or_ambiguous_blocks(self):
        for case in ("unavailable", "timeout", "ambiguous"):
            with self.subTest(case=case):
                self.assertEqual(self.review(redis_read=case).status, "redis_untrusted")

    def test_missing_corrupt_or_stale_version_blocks(self):
        for case in ("missing", "stale", "corrupt"):
            with self.subTest(case=case):
                self.assertEqual(
                    self.review(marker=case).status, "version_marker_untrusted",
                )

    def test_generation_mismatch_blocks(self):
        self.assertEqual(
            self.review(observed_generation=1).status, "generation_mismatch",
        )

    def test_unconfirmed_quarantine_blocks(self):
        self.assertEqual(
            self.review(quarantine_acknowledged=False).status,
            "quarantine_unconfirmed",
        )

    def test_untrusted_inventory_blocks(self):
        self.assertEqual(
            self.review(inventory_trusted=False).status, "inventory_untrusted",
        )

    def test_untrusted_account_snapshot_blocks(self):
        self.assertEqual(
            self.review(authoritative_account_snapshot=False).status,
            "account_snapshot_untrusted",
        )

    def test_untrusted_session_snapshot_blocks(self):
        self.assertEqual(
            self.review(authoritative_session_snapshot=False).status,
            "session_snapshot_untrusted",
        )

    def test_inactive_deleting_missing_or_ambiguous_account_blocks(self):
        for case in ("inactive", "deleting", "missing", "ambiguous"):
            with self.subTest(case=case):
                self.assertEqual(self.review(account=case).status, "account_not_active")

    def test_legacy_password_reset_grant_blocks(self):
        self.assertEqual(
            self.review(reset_grants_drained=False).status, "reset_grant_pending",
        )

    def test_no_proven_consumed_challenge_blocks(self):
        for case in ("unissued", "issued", "expired", "unknown"):
            with self.subTest(case=case):
                self.assertEqual(
                    self.review(challenge=case).status, "challenge_not_consumed",
                )

    def test_lost_redis_consume_ack_does_not_promote_to_login(self):
        self.assertEqual(
            self.review(consume_acknowledged=False).status,
            "consume_ack_ambiguous",
        )

    def test_session_timeout_unconfirmed_duplicate_rejected_or_not_started_blocks(self):
        for case in ("timeout", "unconfirmed", "duplicate", "rejected", "not_started"):
            with self.subTest(case=case):
                self.assertEqual(
                    self.review(session_write=case).status, "session_outcome_untrusted",
                )
                self.assertFalse(self.review(session_write=case).safe_to_retry_session_write)

    def test_unexpected_pii_and_extra_fields_cannot_be_supplied(self):
        with self.assertRaises(TypeError):
            assess_synthetic_cross_store_recovery({
                "phone": "09123456789", "otp": "123456",
            })
        with self.assertRaises(TypeError):
            replace(GOOD, phone="09123456789")

    def test_invalid_enums_fail_validation(self):
        for field in ("redis_read", "marker", "challenge", "account", "session_write"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.review(**{field: "unrecognized"})

    def test_non_boolean_evidence_rejected(self):
        for field in (
            "consume_acknowledged", "authoritative_account_snapshot",
            "authoritative_session_snapshot", "reset_grants_drained",
            "inventory_trusted", "quarantine_acknowledged", "operator_halted",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.review(**{field: 1})

    def test_invalid_generation_rejected(self):
        for value in (0, -1, 1_000_000_001, True, "2", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.review(expected_generation=value)

    def test_live_api_web_and_session_store_not_wired(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            with self.subTest(path=path):
                src = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("otp_cross_store_recovery_policy", src)
                self.assertNotIn("otp_recovery_quarantine_rehearsal", src)

    def test_rehearsal_is_single_key_fixture_only_without_real_user_access(self):
        for script in (
            rehearsal.SEED, rehearsal.RECORD_CONSUMED,
            rehearsal.QUARANTINE, rehearsal.HALT, rehearsal.AUDIT,
        ):
            self.assertIn("KEYS[1]", script)
            self.assertNotIn("KEYS[2]", script)
            for unsafe in ("FLUSHDB", "FLUSHALL", "SCAN", "KEYS *"):
                self.assertNotIn(unsafe, script)
        source = inspect.getsource(rehearsal)
        self.assertIn("LOOMERA_PHASE711_TEST_REDIS", source)
        self.assertIn("db != 15", source)
        for unsafe in ("django.contrib.auth", "apps.accounts.models",
                       "apps.api.v1", "login(request", ".objects."):
            self.assertNotIn(unsafe, source)

    def test_live_legacy_replay_gap_still_documented_not_fixed(self):
        source = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        verify = source[source.index("def verify_api_otp_code("):]
        self.assertIn("record = _cache_get(key)", verify)
        self.assertIn("secrets.compare_digest", verify)
        self.assertIn('context="verified"', verify)
        helper = source[source.index("def _cache_delete("):source.index("def _increment_hour_rate(")]
        self.assertIn("cache.delete(key)", helper)

    def test_exit_matrix_requires_separate_live_approval(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.11")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "919f6a5a8f50592543cc961587662f50da3e3ea3",
        )
        for key in (
            "live_auth_wired", "real_session_created", "real_account_accessed",
            "cross_store_atomicity_proven", "redis_failover_verified",
            "legacy_replay_race_fixed", "production_recovery_authorized",
            "legacy_fallback_authorized", "deployed",
        ):
            self.assertIs(matrix[key], False, key)
        self.assertTrue(matrix["release_gate"].startswith("BLOCKED"))
