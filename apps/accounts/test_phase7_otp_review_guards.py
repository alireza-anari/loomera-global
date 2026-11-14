"""Phase 7.30 offline review-policy and no-live-wiring regression gates."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_outbox_review_rehearsal as review

ROOT = Path(__file__).resolve().parents[2]


class Phase730OfflineReviewGuards(SimpleTestCase):
    @staticmethod
    def reader(**changes):
        config = {
            "host": "127.0.0.1", "port": 6428, "db": 15,
            "username": "phase728_legacy",
        }
        config.update(changes)
        return SimpleNamespace(connection_pool=SimpleNamespace(
            connection_kwargs=config,
        ))

    @staticmethod
    def grants():
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "730",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE726_TEST_POSTGIS": "1",
            "LOOMERA_PHASE728_TEST_REDIS": "1",
            "LOOMERA_PHASE729_TEST_OUTBOX": "1",
            "LOOMERA_PHASE730_TEST_REVIEW": "1",
        })

    def test_requires_exact_readonly_role_fixture_host_db_port(self):
        with self.grants():
            self.assertEqual(
                review.validate_review_scope(self.reader(), "a" * 32),
                review.PREFIX + "a" * 32 + ":",
            )
            for changes in (
                {"host": "localhost"}, {"host": "10.0.0.2"},
                {"port": 6379}, {"port": True}, {"port": 6427},
                {"db": 0}, {"db": 14}, {"db": True},
                {"username": "phase728_gateway"},
                {"username": "phase728_admin"}, {"username": None},
            ):
                with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                    review.validate_review_scope(
                        self.reader(**changes), "a" * 32,
                    )

    def test_invalid_fixture_or_unstructured_client_is_denied(self):
        with self.grants():
            for ident in ("x" * 32, "A" * 32, "b" * 31,
                          "c" * 33, "", None, 1, True):
                with self.subTest(ident=str(ident)), self.assertRaises(ValueError):
                    review.validate_review_scope(self.reader(), ident)
            for bad in (
                object(), SimpleNamespace(connection_pool=None),
                SimpleNamespace(connection_pool=SimpleNamespace(
                    connection_kwargs=[],
                )),
            ):
                with self.assertRaises(RuntimeError):
                    review.validate_review_scope(bad, "a" * 32)

    def test_every_ci_grant_is_required_before_any_io(self):
        fields_to_revoke = (
            "GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
            "LOOMERA_PHASE726_TEST_POSTGIS",
            "LOOMERA_PHASE728_TEST_REDIS",
            "LOOMERA_PHASE729_TEST_OUTBOX",
            "LOOMERA_PHASE730_TEST_REVIEW",
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                review.validate_review_scope(self.reader(), "a" * 32)
        for key in fields_to_revoke:
            with self.grants():
                os.environ.pop(key)
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    review.validate_review_scope(self.reader(), "a" * 32)

    def test_all_classifications_deny_recovery_and_production(self):
        for status in (
            "pending_marker_absent", "inflight_marker_absent",
            "inflight_marker_matches_untrusted",
            "observed_marker_matches_untrusted",
            "observed_marker_absent", "quarantined_foreign_marker",
            "untracked_redis_marker", "orphan_intent_without_ledger",
            "orphan_ledger_without_intent", "conflicting_sql_identity",
            "authority_halted", "owner_epoch_stale",
            "redis_changed_during_review",
        ):
            evidence = review.SyntheticReviewEvidence(
                status, marker_present=True, redis_reads_stable=True,
            )
            self.assertTrue(evidence.requires_manual_review)
            for flag in (
                "auto_replay_allowed", "redis_marker_repair_allowed",
                "real_otp_authentication_allowed", "real_session_created",
                "external_sms_delivery_proven", "all_redis_ingress_fenced",
                "cross_store_atomic_snapshot_proven",
                "production_release_authorized",
            ):
                self.assertIs(getattr(evidence, flag), False, flag)
        self.assertEqual(
            {f.name for f in fields(review.SyntheticReviewEvidence)}
            & {"operation_id", "fingerprint", "password", "otp_code"},
            set(),
        )

    def test_source_only_reads_exact_key_and_one_sql_snapshot(self):
        source = inspect.getsource(review)
        for required in (
            "LOOMERA_PHASE730_TEST_REVIEW", "verify_ci_test_scope",
            'READER_USER = "phase728_legacy"',
            "FULL OUTER JOIN", "self.reader.get(key)",
            "redis_changed_during_review", "hmac.compare_digest",
            "requires_manual_review: bool = True",
            "production_release_authorized: bool = False",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "self.reader.set(", "self.reader.eval(", "self.reader.delete(",
            "cur.execute('UPDATE", "cur.execute('INSERT", "cur.execute('DELETE",
            "FLUSHDB", "FLUSHALL", "apps.api.v1", "apps.accounts.models",
            "sms_ir", "SMSIR", "cache.delete(",
        ):
            self.assertNotIn(forbidden, source)

    def test_existing_live_auth_and_production_settings_do_not_import_review(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
            "loomera/settings.py", "loomera/settings/production.py",
        ):
            target = ROOT / path
            if target.exists():
                self.assertNotIn(
                    "otp_outbox_review_rehearsal",
                    target.read_text(encoding="utf-8"),
                )

    def test_real_runner_and_ci_require_four_scoped_grants(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        shell = (ROOT / "tests/phase7_postgis_restricted_writer_ci.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_review_guards",
            workflow,
        )
        for grant in (
            "LOOMERA_PHASE726_TEST_POSTGIS",
            "LOOMERA_PHASE728_TEST_REDIS",
            "LOOMERA_PHASE729_TEST_OUTBOX",
            "LOOMERA_PHASE730_TEST_REVIEW",
        ):
            self.assertIn(grant, workflow)
            self.assertIn(grant, shell)
        self.assertIn(
            "apps.accounts.test_phase7_postgis_mandatory_ingress", shell,
        )
        for forbidden in ("FLUSHDB", "FLUSHALL", "docker system prune"):
            self.assertNotIn(forbidden, shell)

    def test_real_tests_cover_ambiguity_and_privileged_bypass(self):
        tests = (ROOT / "apps/accounts/test_phase7_postgis_mandatory_ingress.py").read_text(
            encoding="utf-8"
        )
        for method in (
            "test_phase730_pending_intent_never_implies_delivery",
            "test_phase730_inflight_with_marker_after_real_lost_ack",
            "test_phase730_inflight_without_marker_is_also_not_replay_grant",
            "test_phase730_admin_raw_bypass_visible_but_not_fenced",
            "test_phase730_sql_orphan_ledger_and_intent_are_distinguished",
            "test_phase730_two_reads_detect_interposed_physical_raw_write",
            "test_phase730_readonly_actor_denied_writes_and_acl_verified",
            "test_phase730_revoked_legacy_reader_fails_closed_without_repair",
        ):
            self.assertIn(method, tests)

    def test_exit_matrix_lists_known_bypasses_and_denies_release(self):
        data = json.loads((
            ROOT / "docs/globalization/PHASE7_30_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "7.30")
        self.assertEqual(
            data["baseline_main_sha"],
            "63b92c748881072b951016645caac910cc793cec",
        )
        self.assertEqual(
            data["known_ingress_routes"]["fixture_admin"],
            "PRIVILEGED_RAW_WRITE_BYPASS_OPEN",
        )
        self.assertEqual(
            data["known_ingress_routes"]["unknown_redis_nodes"],
            "UNVERIFIED_NOT_GLOBALLY_FENCED",
        )
        for field in (
            "live_auth_code_changed", "automatic_outbox_recovery_approved",
            "redis_global_ingress_fenced", "cross_store_atomic_snapshot",
            "external_sms_receipt_proven", "security_owner_approval",
            "production_deployment_authorized", "deployed",
        ):
            self.assertIs(data[field], False, field)
        self.assertTrue(data["release_gate"].startswith("BLOCKED"))
