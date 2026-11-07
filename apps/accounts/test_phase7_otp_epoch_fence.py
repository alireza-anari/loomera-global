"""Phase 7.16 strict offline epoch-token policy and live-wiring blockers."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_epoch_fence_policy import (
    SyntheticEpochFenceEvidence, SyntheticEpochFenceAssessment,
    assess_synthetic_epoch_fence,
)
from loomera.globalization import otp_epoch_redis_rehearsal as adapter
from loomera.globalization import otp_epoch_witness_rehearsal as witness

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_16_EXIT_MATRIX.json"
A = "0" * 32
B = "1" * 32
GREEN = SyntheticEpochFenceEvidence(
    witness_status="verified", witness_owner="promoted",
    candidate_owner="promoted", witness_epoch=2, candidate_epoch=2,
    redis_epoch=2, witness_token=B, candidate_token=B, redis_token=B,
    redis_marker_status="matched", redis_master_role=True,
    dual_master_possible=False, old_primary_readonly=True,
    write_acknowledgement="confirmed",
    witness_read_atomic_with_redis_write=True, multi_host_quorum_attested=True,
    no_real_users_or_sessions=True,
)


class Phase716EpochFencePolicyTests(SimpleTestCase):
    def assess(self, **kw):
        return assess_synthetic_epoch_fence(replace(GREEN, **kw))

    def test_even_all_green_is_only_synthetic_fixture_evidence(self):
        r = self.assess()
        self.assertEqual(r, SyntheticEpochFenceAssessment(
            "synthetic_fixture_only_manual_review",
            fixture_write_observation_possible=True,
        ))
        self.assertTrue(r.manual_reconciliation_required)
        for field in (
            "authenticated", "otp_consume_allowed", "otp_reissue_allowed",
            "session_created", "session_retry_allowed",
            "legacy_fallback_allowed", "production_cutover_allowed",
            "real_consensus_proven",
        ):
            self.assertFalse(getattr(r, field), field)

    def test_scope_denies_real_user_or_session(self):
        self.assertEqual(
            self.assess(no_real_users_or_sessions=False).status,
            "unsafe_real_data_scope",
        )

    def test_halted_witness_is_terminal(self):
        self.assertEqual(self.assess(witness_status="halted").status, "witness_halted")

    def test_witness_missing_corrupt_unavailable_denied(self):
        for status in ("missing", "corrupt", "unavailable"):
            with self.subTest(status=status):
                self.assertEqual(
                    self.assess(witness_status=status).status, "witness_untrusted",
                )

    def test_unknown_witness_owner_denied(self):
        self.assertEqual(self.assess(witness_owner="unknown").status, "owner_untrusted")

    def test_unknown_candidate_owner_denied(self):
        self.assertEqual(self.assess(candidate_owner="unknown").status, "owner_untrusted")

    def test_wrong_owner_denied(self):
        self.assertEqual(self.assess(candidate_owner="original").status, "wrong_owner")

    def test_stale_candidate_epoch_denied(self):
        self.assertEqual(
            self.assess(candidate_epoch=1).status, "stale_or_future_candidate_epoch",
        )

    def test_future_candidate_epoch_denied(self):
        self.assertEqual(
            self.assess(candidate_epoch=3).status, "stale_or_future_candidate_epoch",
        )

    def test_stale_or_forged_token_denied(self):
        self.assertEqual(
            self.assess(candidate_token=A).status, "stale_or_forged_candidate_token",
        )

    def test_missing_stale_future_corrupt_redis_marker_denied(self):
        for marker in ("missing", "stale", "future", "corrupt"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    self.assess(redis_marker_status=marker).status,
                    "redis_marker_untrusted",
                )

    def test_redis_epoch_regressed_denied(self):
        self.assertEqual(self.assess(redis_epoch=1).status, "redis_epoch_diverged")

    def test_redis_epoch_ahead_denied(self):
        self.assertEqual(self.assess(redis_epoch=3).status, "redis_epoch_diverged")

    def test_redis_token_diverged_denied(self):
        self.assertEqual(self.assess(redis_token=A).status, "redis_token_diverged")

    def test_redis_replica_denied(self):
        self.assertEqual(self.assess(redis_master_role=False).status, "not_redis_master")

    def test_dual_master_denied(self):
        self.assertEqual(
            self.assess(dual_master_possible=True).status, "dual_master_not_fenced",
        )

    def test_old_primary_still_writable_denied(self):
        self.assertEqual(
            self.assess(old_primary_readonly=False).status,
            "old_primary_still_writable",
        )

    def test_ambiguous_previous_write_denied(self):
        for ack in ("lost", "unknown"):
            with self.subTest(ack=ack):
                self.assertEqual(
                    self.assess(write_acknowledgement=ack).status,
                    "uncertain_prior_write",
                )

    def test_separate_sqlite_read_and_redis_eval_is_not_atomic(self):
        self.assertEqual(
            self.assess(witness_read_atomic_with_redis_write=False).status,
            "cross_store_fence_not_atomic",
        )

    def test_single_host_witness_has_no_distributed_quorum(self):
        self.assertEqual(
            self.assess(multi_host_quorum_attested=False).status,
            "independent_quorum_missing",
        )

    def test_no_generic_dict_or_user_otp_accepted(self):
        with self.assertRaises(TypeError):
            assess_synthetic_epoch_fence({"otp": "123456"})

    def test_every_enum_is_exact(self):
        for field in (
            "witness_status", "witness_owner", "candidate_owner",
            "redis_marker_status", "write_acknowledgement",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.assess(**{field: "bad"})

    def test_truthy_bool_is_not_boolean(self):
        for field in (
            "redis_master_role", "dual_master_possible", "old_primary_readonly",
            "witness_read_atomic_with_redis_write",
            "multi_host_quorum_attested", "no_real_users_or_sessions",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.assess(**{field: 1})

    def test_invalid_epoch_and_boolean_rejected(self):
        for field in ("witness_epoch", "candidate_epoch", "redis_epoch"):
            for invalid in (0, -1, 1_000_000_001, True, None, "2"):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    self.assess(**{field: invalid})

    def test_invalid_tokens_rejected(self):
        for field in ("witness_token", "candidate_token", "redis_token"):
            for invalid in ("A"*32, "123", "x"*32, True, None):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    self.assess(**{field: invalid})

    def test_no_live_auth_wiring(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            with self.subTest(path=path):
                source = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("otp_epoch_fence_policy", source)
                self.assertNotIn("otp_epoch_witness_rehearsal", source)
                self.assertNotIn("otp_epoch_redis_rehearsal", source)

    def test_strict_disposable_endpoint_and_witness_grants(self):
        source = inspect.getsource(adapter)
        witness_source = inspect.getsource(witness)
        for s in ("6397", "6398", "db", "LOOMERA_PHASE716_TEST_REDIS",
                  "LOOMERA_PHASE716_ACTIVE_LEADER", "LOOMERA_PHASE716_ALLOW_TEST_ADOPT"):
            self.assertIn(s, source)
        for s in ("LOOMERA_PHASE716_TEST_WITNESS",
                  "LOOMERA_PHASE716_ALLOW_SEED", "BEGIN IMMEDIATE"):
            self.assertIn(s, witness_source)
        for forbidden in ("FLUSHALL", "FLUSHDB", "request.session", "login(request",
                          "apps.accounts.models", ".objects."):
            self.assertNotIn(forbidden, source + witness_source)

    def test_live_api_replay_gap_remains_blocked(self):
        source = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        verify = source[source.index("def verify_api_otp_code("):]
        self.assertIn("record = _cache_get(key)", verify)
        self.assertIn("secrets.compare_digest", verify)
        self.assertIn('context="verified"', verify)

    def test_release_matrix_is_explicitly_blocked(self):
        m = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(m["phase"], "7.16")
        self.assertEqual(
            m["baseline_main_sha"],
            "9263d8057dba1c3296dd031c68cfeecc2fb74676",
        )
        for field in (
            "multi_host_consensus_fencing_verified",
            "cross_store_atomic_fencing_verified",
            "old_primary_raw_writes_blocked",
            "live_auth_wired", "real_user_data_accessed",
            "real_session_created", "legacy_replay_race_fixed",
            "production_cutover_authorized", "deployed",
        ):
            self.assertIs(m[field], False, field)
        self.assertTrue(m["release_gate"].startswith("BLOCKED"))
