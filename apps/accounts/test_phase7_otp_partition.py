"""Phase 7.15 offline partition evidence and safety/release guards."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_partition_evidence_policy import (
    SyntheticPartitionEvidence, SyntheticPartitionDecision,
    assess_synthetic_partition,
)
from loomera.globalization import otp_partition_redis_rehearsal as redis_model
from loomera.globalization import otp_partition_witness_rehearsal as witness_model

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_15_EXIT_MATRIX.json"
GREEN = SyntheticPartitionEvidence(
    replication_link="linked",
    original_role="replica_readonly",
    promoted_role="master",
    independent_witness="verified",
    witness_mode="observing",
    witness_generation=2,
    client_expected_generation=2,
    original_marker="matched",
    promoted_marker="matched",
    original_generation=2,
    promoted_generation=2,
    original_write_ack="acknowledged",
    promoted_write_ack="acknowledged",
    post_partition_inventory_complete=True,
    old_writer_fenced_by_consensus=True,
    durable_multi_host_quorum=True,
    real_data_absent=True,
    owner_authorized=True,
)


class Phase715PartitionSafetyTests(SimpleTestCase):
    def check(self, **changes):
        return assess_synthetic_partition(replace(GREEN, **changes))

    def test_all_green_claims_never_authenticate(self):
        decision = self.check()
        self.assertEqual(decision, SyntheticPartitionDecision("manual_review_only"))
        self.assertTrue(decision.manual_reconciliation_required)
        for name in (
            "login_allowed", "otp_consume_allowed", "otp_reissue_allowed",
            "write_on_either_master_allowed", "marker_reseed_allowed",
            "session_retry_allowed", "legacy_fallback_allowed",
            "production_cutover_allowed", "old_primary_fenced_proven",
            "real_quorum_proven",
        ):
            self.assertIs(getattr(decision, name), False, name)

    def test_real_data_inputs_forbidden(self):
        self.assertEqual(
            self.check(real_data_absent=False).status, "unsafe_real_data_scope",
        )

    def test_two_masters_even_if_link_claims_up_are_split_brain(self):
        self.assertEqual(
            self.check(original_role="master").status, "dual_master_split_brain",
        )

    def test_network_partition_denies(self):
        for link in ("partitioned", "restoring", "unknown"):
            with self.subTest(link=link):
                self.assertEqual(
                    self.check(replication_link=link).status, "replication_untrusted",
                )

    def test_old_master_writable_denies(self):
        self.assertEqual(
            self.check(original_role="master", replication_link="partitioned").status,
            "dual_master_split_brain",
        )

    def test_roles_unknown_down_or_readonly_deny(self):
        for original, promoted in (
            ("down", "master"), ("unknown", "master"),
            ("replica_readonly", "unknown"),
            ("replica_readonly", "replica_readonly"),
        ):
            with self.subTest(original=original, promoted=promoted):
                self.assertEqual(
                    self.check(original_role=original, promoted_role=promoted).status,
                    "roles_untrusted",
                )

    def test_missing_stale_corrupt_unavailable_witness_denies(self):
        for witness in ("missing", "stale", "corrupt", "unavailable"):
            with self.subTest(witness=witness):
                self.assertEqual(
                    self.check(independent_witness=witness).status,
                    "witness_untrusted",
                )

    def test_halted_witness_never_reopens(self):
        result = self.check(witness_mode="halted")
        self.assertEqual(result.status, "terminal_witness_halt")
        self.assertFalse(result.otp_consume_allowed)

    def test_unknown_witness_mode_denies(self):
        self.assertEqual(
            self.check(witness_mode="unknown").status, "witness_mode_untrusted",
        )

    def test_caller_stale_witness_generation_denies(self):
        self.assertEqual(
            self.check(client_expected_generation=1).status, "witness_epoch_mismatch",
        )

    def test_missing_divergent_corrupt_marker_on_original_denies(self):
        for marker in ("divergent", "missing", "corrupt", "unreadable"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    self.check(original_marker=marker).status, "markers_untrusted",
                )

    def test_missing_divergent_corrupt_marker_on_promoted_denies(self):
        for marker in ("divergent", "missing", "corrupt", "unreadable"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    self.check(promoted_marker=marker).status, "markers_untrusted",
                )

    def test_generation_regressed_either_node_denies(self):
        for name in ("original_generation", "promoted_generation"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.check(**{name: 1}).status, "marker_regressed",
                )

    def test_future_generation_either_node_denies(self):
        for name in ("original_generation", "promoted_generation"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.check(**{name: 3}).status, "marker_ahead_untrusted",
                )

    def test_lost_ack_from_old_primary_denies(self):
        for ack in ("unknown", "timeout", "not_attempted"):
            with self.subTest(ack=ack):
                self.assertEqual(
                    self.check(original_write_ack=ack).status,
                    "write_commit_ambiguous",
                )

    def test_lost_ack_from_promoted_primary_denies(self):
        for ack in ("unknown", "timeout", "not_attempted"):
            with self.subTest(ack=ack):
                self.assertEqual(
                    self.check(promoted_write_ack=ack).status,
                    "write_commit_ambiguous",
                )

    def test_postpartition_inventory_missing_denies(self):
        self.assertEqual(
            self.check(post_partition_inventory_complete=False).status,
            "inventory_untrusted",
        )

    def test_no_consensus_fence_denies(self):
        self.assertEqual(
            self.check(old_writer_fenced_by_consensus=False).status,
            "old_writer_not_fenced",
        )

    def test_local_sqlite_not_a_multihost_quorum(self):
        self.assertEqual(
            self.check(durable_multi_host_quorum=False).status,
            "quorum_unproven",
        )

    def test_no_owner_signoff_denies(self):
        self.assertEqual(
            self.check(owner_authorized=False).status, "owner_signoff_missing",
        )

    def test_invalid_evidence_type_rejected(self):
        with self.assertRaises(TypeError):
            assess_synthetic_partition({"otp": "123456"})

    def test_unknown_enums_rejected_without_coercion(self):
        for field in (
            "replication_link", "original_role", "promoted_role",
            "independent_witness", "witness_mode",
            "original_marker", "promoted_marker",
            "original_write_ack", "promoted_write_ack",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(**{field: "unrecognized"})

    def test_truthy_nonboolean_rejected(self):
        for field in (
            "post_partition_inventory_complete", "old_writer_fenced_by_consensus",
            "durable_multi_host_quorum", "real_data_absent", "owner_authorized",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(**{field: 1})

    def test_bad_and_boolean_epochs_rejected(self):
        for field in (
            "witness_generation", "client_expected_generation",
            "original_generation", "promoted_generation",
        ):
            for bad in (0, -1, 1_000_000_001, True, None, "2"):
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    self.check(**{field: bad})

    def test_no_live_auth_or_session_wiring(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            with self.subTest(path=path):
                src = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("otp_partition_redis_rehearsal", src)
                self.assertNotIn("otp_partition_witness_rehearsal", src)
                self.assertNotIn("otp_partition_evidence_policy", src)

    def test_witness_file_and_redis_endpoint_guards(self):
        source = inspect.getsource(redis_model)
        self.assertIn("LOOMERA_PHASE715_TEST_REDIS", source)
        self.assertIn("6395", source)
        self.assertIn("6396", source)
        self.assertIn("db != 15", source)
        witness_source = inspect.getsource(witness_model)
        self.assertIn("LOOMERA_PHASE715_WITNESS_TEST", witness_source)
        self.assertIn("LOOMERA_PHASE715_ALLOW_TEST_SEED", witness_source)
        for forbidden in (
            "FLUSHALL", "FLUSHDB", "SCAN", "request.session", "login(request",
            "apps.accounts.models", ".objects.",
        ):
            self.assertNotIn(forbidden, source + witness_source)

    def test_legacy_live_replay_race_is_not_fixed_here(self):
        src = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        verify = src[src.index("def verify_api_otp_code("):]
        self.assertIn("record = _cache_get(key)", verify)
        self.assertIn("secrets.compare_digest", verify)
        self.assertIn('context="verified"', verify)

    def test_release_matrix_explicitly_blocked(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.15")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "76b1f66af61f318add4fb940beb9a072de757f63",
        )
        for key in (
            "external_consensus_leader_verified", "independent_multihost_quorum",
            "raw_redis_writes_fenced", "automatic_failover_safe",
            "live_auth_wired", "real_users_accessed", "real_sessions_created",
            "legacy_replay_race_fixed", "production_cutover_authorized", "deployed",
        ):
            self.assertIs(matrix[key], False, key)
        self.assertTrue(matrix["release_gate"].startswith("BLOCKED"))
