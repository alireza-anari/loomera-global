"""Phase 7.14 isolated Redis promotion evidence and release-blocked safeguards."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_replica_promotion_policy import (
    SyntheticPromotionEvidence, SyntheticPromotionReview,
    review_synthetic_replica_promotion,
)
from loomera.globalization import otp_replica_promotion_rehearsal as model

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_14_EXIT_MATRIX.json"
GOOD = SyntheticPromotionEvidence(
    topology="promoted_standalone", proposed_leader="promoted",
    original_primary_status="replica_readonly",
    marker_replication="matched", marker_after_promotion="matched",
    generation_before=2, generation_after=2,
    mode_before="quarantined", mode_after="quarantined",
    cause_unchanged=True, fingerprint_unchanged=True,
    old_writer_guard_active=True, replica_sync_observed=True,
    source_write_ack="acknowledged", session_ledger_settled=True,
    real_account_data_absent=True, independent_durable_lease=True,
    owner_signoff_claimed=True,
)


class Phase714ReplicaPromotionPolicyTests(SimpleTestCase):
    def decide(self, **changes):
        return review_synthetic_replica_promotion(replace(GOOD, **changes))

    def test_even_all_claims_true_are_manual_only(self):
        result = self.decide()
        self.assertEqual(result, SyntheticPromotionReview("manual_review_only"))
        self.assertTrue(result.operator_review_required)
        for field in (
            "authenticated", "otp_reissue_allowed", "session_created",
            "session_retry_allowed", "cutover_allowed", "legacy_fallback_allowed",
            "real_failover_safety_proven", "old_leader_fenced_proven",
        ):
            self.assertFalse(getattr(result, field), field)

    def test_synthetic_rejoined_replica_still_not_live_proof(self):
        self.assertEqual(
            self.decide(topology="rejoined_replica").status,
            "manual_review_only",
        )

    def test_real_account_data_is_forbidden(self):
        self.assertEqual(
            self.decide(real_account_data_absent=False).status,
            "unsafe_fixture_scope",
        )

    def test_split_brain_or_unknown_topology_fails_closed(self):
        for topology in ("split_brain", "unknown"):
            with self.subTest(topology=topology):
                self.assertEqual(
                    self.decide(topology=topology).status, "topology_ambiguous",
                )

    def test_unpromoted_replica_does_not_claim_promotion(self):
        self.assertEqual(
            self.decide(topology="linked_replica").status,
            "promotion_unverified",
        )

    def test_wrong_leader_or_unknown_leader_denied(self):
        for value in ("original", "missing", "ambiguous"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.decide(proposed_leader=value).status,
                    "leader_not_promoted",
                )

    def test_missing_wait_replica_ack_denied(self):
        self.assertEqual(
            self.decide(replica_sync_observed=False).status,
            "replica_sync_unproven",
        )

    def test_marker_not_matched_on_replica_denied(self):
        for value in ("missing", "stale", "future", "corrupt"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.decide(marker_replication=value).status,
                    "replication_marker_untrusted",
                )

    def test_marker_not_matched_after_promotion_denied(self):
        for value in ("missing", "stale", "future", "corrupt"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.decide(marker_after_promotion=value).status,
                    "promoted_marker_untrusted",
                )

    def test_generation_regressed_denied(self):
        self.assertEqual(
            self.decide(generation_after=1).status, "generation_regressed",
        )

    def test_unknown_future_generation_denied(self):
        self.assertEqual(
            self.decide(generation_after=3).status,
            "generation_ahead_untrusted",
        )

    def test_mode_changed_during_promotion_denied(self):
        self.assertEqual(
            self.decide(mode_after="halted").status, "mode_changed",
        )

    def test_unknown_mode_denied(self):
        self.assertEqual(
            self.decide(mode_before="unknown", mode_after="unknown").status,
            "mode_unknown",
        )

    def test_fingerprint_changed_denied(self):
        self.assertEqual(
            self.decide(fingerprint_unchanged=False).status,
            "fingerprint_mismatch",
        )

    def test_quarantine_cause_changed_denied(self):
        self.assertEqual(
            self.decide(cause_unchanged=False).status, "cause_mismatch",
        )

    def test_ambiguous_original_write_ack_denied(self):
        for ack in ("timeout", "unknown", "not_attempted"):
            with self.subTest(ack=ack):
                self.assertEqual(
                    self.decide(source_write_ack=ack).status, "commit_ambiguous",
                )

    def test_old_primary_writable_is_explicitly_unsafe(self):
        self.assertEqual(
            self.decide(original_primary_status="master_writable").status,
            "old_primary_still_writable",
        )

    def test_old_primary_unknown_denied(self):
        self.assertEqual(
            self.decide(original_primary_status="unknown").status,
            "old_primary_untrusted",
        )

    def test_old_primary_offline_also_never_grants_login(self):
        result = self.decide(original_primary_status="offline")
        self.assertFalse(result.authenticated)
        self.assertFalse(result.old_leader_fenced_proven)

    def test_old_writer_guard_claim_required(self):
        self.assertEqual(
            self.decide(old_writer_guard_active=False).status,
            "old_writer_guard_missing",
        )

    def test_session_ledger_still_not_a_redis_atomic_proof(self):
        self.assertEqual(
            self.decide(session_ledger_settled=False).status,
            "session_ledger_untrusted",
        )

    def test_owner_claim_does_not_replace_signoff(self):
        self.assertEqual(
            self.decide(owner_signoff_claimed=False).status,
            "owner_signoff_unverified",
        )

    def test_no_external_durable_lease_denied(self):
        self.assertEqual(
            self.decide(independent_durable_lease=False).status,
            "durable_lease_missing",
        )

    def test_unknown_enum_rejected(self):
        for field in (
            "topology", "proposed_leader", "original_primary_status",
            "marker_replication", "marker_after_promotion",
            "mode_before", "mode_after", "source_write_ack",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.decide(**{field: "something_else"})

    def test_truthy_nonbool_rejected(self):
        for field in (
            "cause_unchanged", "fingerprint_unchanged", "old_writer_guard_active",
            "replica_sync_observed", "session_ledger_settled",
            "real_account_data_absent", "independent_durable_lease",
            "owner_signoff_claimed",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.decide(**{field: 1})

    def test_invalid_generations_rejected(self):
        for field in ("generation_before", "generation_after"):
            for value in (0, -1, 1_000_000_001, True, "2", None):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.decide(**{field: value})

    def test_untyped_context_and_pii_not_allowed(self):
        with self.assertRaises(TypeError):
            review_synthetic_replica_promotion({
                "otp": "123456", "mobile": "09123456789",
            })

    def test_runtime_fixtures_strictly_loopback_two_ports(self):
        source = inspect.getsource(model)
        for anchor in (
            "LOOMERA_PHASE714_TEST_REDIS",
            "LOOMERA_PHASE714_ACTIVE_LEADER",
            "LOOMERA_PHASE714_ALLOW_TEST_SEED",
            "6393", "6394", "db != 15",
        ):
            self.assertIn(anchor, source)
        for forbidden in (
            "FLUSHDB", "FLUSHALL", "SCAN", "django.contrib.auth",
            "apps.accounts.models", "request.session", "login(request", ".objects.",
        ):
            self.assertNotIn(forbidden, source)

    def test_live_api_and_historical_login_not_wired(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            with self.subTest(path=path):
                src = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("otp_replica_promotion_policy", src)
                self.assertNotIn("otp_replica_promotion_rehearsal", src)

    def test_legacy_race_still_not_repaired(self):
        src = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        verify = src[src.index("def verify_api_otp_code("):]
        self.assertIn("record = _cache_get(key)", verify)
        self.assertIn("secrets.compare_digest", verify)
        self.assertIn('context="verified"', verify)

    def test_exit_matrix_blocks_real_release(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.14")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "a57022631afe8e3034d9688eec784e6910a0ad2b",
        )
        for key in (
            "independent_durable_leader_lease_verified",
            "live_auth_wired", "real_accounts_accessed",
            "real_sessions_created", "old_primary_fenced_by_consensus",
            "real_sentinel_cluster_failover_tested",
            "legacy_replay_race_fixed", "production_recovery_authorized",
            "deployed",
        ):
            self.assertIs(matrix[key], False, key)
        self.assertTrue(matrix["release_gate"].startswith("BLOCKED"))
