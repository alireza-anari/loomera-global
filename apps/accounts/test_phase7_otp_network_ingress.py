"""Phase 7.19 pure ingress policy, no-live-wiring and release gate checks."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_network_ingress_evidence_policy import (
    IngressNodeObservation, IngressFenceReview, review_ingress_partition,
)

ROOT = Path(__file__).resolve().parents[2]
OLD = IngressNodeObservation("old", "master", False, False, True)
NEW = IngressNodeObservation("promoted", "master", True, True, True)


class Phase719NetworkIngressTests(SimpleTestCase):
    def review(self, old=OLD, new=NEW, partitioned=True):
        return review_ingress_partition(
            (old, new), replication_partition_verified=partitioned,
        )

    def test_real_client_bridge_fence_does_not_fence_host_bypass(self):
        self.assertEqual(
            self.review(), IngressFenceReview("bridge_fenced_but_host_bypass_open"),
        )

    def test_all_permission_flags_stay_false(self):
        for review in (self.review(), self.review(
            replace(OLD, host_raw_write_accepted=False))):
            self.assertTrue(review.operator_review_required)
            for name in ("authentication_allowed", "otp_consume_allowed",
                         "otp_issue_allowed", "real_session_created",
                         "production_write_allowed", "old_master_globally_fenced",
                         "alternate_ingress_eliminated", "distributed_consensus_proven",
                         "recovery_authorized", "legacy_fallback_allowed"):
                self.assertFalse(getattr(review, name), name)

    def test_two_paths_supposedly_closed_still_cannot_grant(self):
        self.assertEqual(
            self.review(replace(OLD, host_raw_write_accepted=False)).status,
            "two_local_ingress_paths_observed_only",
        )

    def test_unverified_replication_denied(self):
        self.assertEqual(
            self.review(partitioned=False).status, "replication_partition_unverified",
        )

    def test_old_bridge_never_detached_denied(self):
        self.assertEqual(
            self.review(replace(OLD, client_bridge_attached=True)).status,
            "old_client_bridge_still_attached",
        )

    def test_old_bridge_still_accepts_raw_writes_denied(self):
        self.assertEqual(
            self.review(replace(OLD, bridge_raw_write_accepted=True)).status,
            "old_client_bridge_still_writable",
        )

    def test_promoted_bridge_missing_denied(self):
        self.assertEqual(
            self.review(new=replace(NEW, client_bridge_attached=False)).status,
            "promoted_client_route_unverified",
        )

    def test_promoted_raw_write_missing_denied(self):
        self.assertEqual(
            self.review(new=replace(NEW, bridge_raw_write_accepted=False)).status,
            "promoted_client_route_unverified",
        )

    def test_not_two_masters_denied(self):
        self.assertEqual(
            self.review(new=replace(NEW, role="slave")).status,
            "not_two_writable_masters",
        )

    def test_exact_order_identity_and_count_required(self):
        for payload in (None, [], (), (OLD,), (NEW, OLD), (OLD, NEW, NEW)):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                review_ingress_partition(
                    payload, replication_partition_verified=True,
                )

    def test_untyped_observation_denied(self):
        with self.assertRaises(TypeError):
            self.review(old={"node": "old"})

    def test_boolean_int_confusion_denied(self):
        for field in ("client_bridge_attached", "bridge_raw_write_accepted",
                      "host_raw_write_accepted"):
            with self.subTest(field=field), self.assertRaises(TypeError):
                self.review(old=replace(OLD, **{field: 1}))
        with self.assertRaises(TypeError):
            self.review(partitioned=1)

    def test_wrong_node_identity_denied(self):
        with self.assertRaises(ValueError):
            self.review(old=replace(OLD, node="promoted"))

    def test_live_auth_not_changed_or_importing_synthetic_policy(self):
        for path in ("apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
                     "apps/accounts/views.py", "apps/accounts/models.py"):
            content = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_network_ingress_evidence_policy", content)
            self.assertNotIn("phase7_network_ingress_drill", content)

    def test_ci_script_uses_dedicated_bridges_and_ports(self):
        ci = (ROOT / "tests/phase7_redis_network_ingress_ci.sh").read_text(
            encoding="utf-8"
        )
        driver = (ROOT / "tests/phase7_network_ingress_drill.py").read_text(
            encoding="utf-8"
        )
        for anchor in ("GITHUB_ACTIONS", "LOOMERA_PHASE719_TEST_REDIS",
                       "6410", "6411"):
            self.assertIn(anchor, ci + driver)
        for anchor in ("trap cleanup EXIT", "--publish 127.0.0.1:",
                       "docker network disconnect", "client_net", "bypass_net",
                       "repl_net", "docker volume rm"):
            self.assertIn(anchor, ci)
        for forbidden in ("FLUSHALL", "FLUSHDB", "apps.accounts.models",
                          "request.session"):
            self.assertNotIn(forbidden, driver)

    def test_release_matrix_remains_blocked(self):
        data = json.loads((ROOT / "docs/globalization/PHASE7_19_EXIT_MATRIX.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "7.19")
        self.assertEqual(data["baseline_main_sha"],
                         "e721094a72416e167de45ec4ec088147045fa0fc")
        for field in ("globally_fenced_old_master", "all_ingress_paths_closed",
                      "durable_multihost_consensus", "real_user_data_accessed",
                      "production_auth_changed", "legacy_otp_replay_race_fixed",
                      "production_deployment_authorized", "deployed"):
            self.assertIs(data[field], False, field)
        self.assertTrue(data["release_gate"].startswith("BLOCKED"))
