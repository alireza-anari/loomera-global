"""Phase 7.18 offline ACL evidence, no-live wiring and blocked release gates."""
from dataclasses import replace
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_acl_partition_evidence_policy import (
    AclNodeObservation, AclPartitionReview, review_acl_partition,
)

ROOT = Path(__file__).resolve().parents[2]
OLD = AclNodeObservation("old", "master", True, True, True)
NEW = AclNodeObservation("promoted", "master", True, False, False)


class Phase718AclReviewTests(SimpleTestCase):
    def assess(self, old=OLD, new=NEW, reached=False):
        return review_acl_partition((old, new), old_admin_reachable=reached)

    def test_partitioned_old_master_remains_writable(self):
        self.assertEqual(self.assess(), AclPartitionReview("stale_old_raw_writer_bypass"))

    def test_explicit_old_acl_change_is_local_only(self):
        old = replace(OLD, stale_user_enabled=False, stale_raw_write_accepted=False)
        value = self.assess(old, reached=True)
        self.assertEqual(value.status, "local_old_acl_revocation_observed_only")
        self.assertTrue(value.operator_review_required)
        for field in ("authentication_allowed", "otp_consume_allowed",
                      "session_created", "production_write_allowed",
                      "global_fencing_proven", "external_revocation_proven",
                      "consensus_proven", "fallback_allowed"):
            self.assertFalse(getattr(value, field), field)

    def test_unreachable_old_admin_does_not_prove_revocation(self):
        old = replace(OLD, stale_user_enabled=False, stale_raw_write_accepted=False)
        self.assertEqual(self.assess(old).status, "old_control_plane_unverified")

    def test_enabled_old_credential_is_unresolved(self):
        old = replace(OLD, stale_raw_write_accepted=False)
        self.assertEqual(self.assess(old, reached=True).status,
                         "old_stale_user_still_enabled")

    def test_promoted_credential_still_enabled_is_denied(self):
        self.assertEqual(self.assess(new=replace(NEW, stale_user_enabled=True)).status,
                         "promoted_stale_user_not_revoked")

    def test_promoted_raw_write_is_denied(self):
        self.assertEqual(self.assess(new=replace(NEW, stale_raw_write_accepted=True)).status,
                         "promoted_stale_user_not_revoked")

    def test_anonymous_users_are_denied(self):
        self.assertEqual(self.assess(old=replace(OLD, default_disabled=False)).status,
                         "anonymous_default_user_open")
        self.assertEqual(self.assess(new=replace(NEW, default_disabled=False)).status,
                         "anonymous_default_user_open")

    def test_wrong_role_is_not_two_masters(self):
        self.assertEqual(self.assess(new=replace(NEW, role="slave")).status,
                         "topology_not_two_masters")

    def test_wrong_observation_counts_and_order_rejected(self):
        for payload in ([], None, (), (OLD,), (NEW, OLD), (OLD, NEW, NEW)):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                review_acl_partition(payload, old_admin_reachable=False)

    def test_untyped_observation_is_rejected(self):
        with self.assertRaises(TypeError):
            self.assess(old={"node": "old"})

    def test_no_truthy_integer_boolean_accepted(self):
        for field in ("default_disabled", "stale_user_enabled",
                      "stale_raw_write_accepted"):
            with self.subTest(field=field), self.assertRaises(TypeError):
                self.assess(old=replace(OLD, **{field: 1}))
        with self.assertRaises(TypeError):
            self.assess(reached=1)

    def test_no_live_auth_imports_rehearsal(self):
        for path in ("apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
                     "apps/accounts/views.py", "apps/accounts/models.py"):
            code = (ROOT/path).read_text(encoding="utf-8")
            self.assertNotIn("otp_acl_partition_evidence_policy", code)
            self.assertNotIn("phase7_acl_partition_drill", code)

    def test_ci_and_fixed_isolated_port_guards(self):
        driver = (ROOT/"tests/phase7_acl_partition_drill.py").read_text(encoding="utf-8")
        shell = (ROOT/"tests/phase7_redis_acl_partition_ci.sh").read_text(encoding="utf-8")
        for marker in ("GITHUB_ACTIONS", "GITHUB_RUN_ID", "LOOMERA_PHASE718_TEST_REDIS",
                       "6408", "6409"):
            self.assertIn(marker, driver + shell)
        for marker in ("trap cleanup EXIT", "--publish 127.0.0.1:",
                       "docker network disconnect", "docker volume rm"):
            self.assertIn(marker, shell)
        self.assertNotIn("--publish 6379:", shell)
        self.assertNotIn("FLUSHALL", driver)
        self.assertNotIn("FLUSHDB", driver)

    def test_release_gate_is_blocked(self):
        p = ROOT/"docs/globalization/PHASE7_18_EXIT_MATRIX.json"
        matrix = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.18")
        self.assertEqual(matrix["baseline_main_sha"],
                         "83a3b36cceb53a61b9f78dbe553fef4f0c8f5c5c")
        for k in ("durable_multihost_consensus", "global_stale_writer_fencing",
                  "remote_old_node_revocation_proven", "production_auth_changed",
                  "real_user_data_accessed", "legacy_otp_replay_race_fixed",
                  "deployment_authorized", "deployed"):
            self.assertIs(matrix[k], False, k)
        self.assertTrue(matrix["release_gate"].startswith("BLOCKED"))
