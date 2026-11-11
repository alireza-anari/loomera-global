"""Phase 7.28 Fast/offline immutable release and fake-client boundary checks."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_restricted_writer_gateway_rehearsal as gate

ROOT = Path(__file__).resolve().parents[2]


class Phase728OfflineRestrictedGatewayGuards(SimpleTestCase):
    @staticmethod
    def client(**overrides):
        scope = {
            "host": "127.0.0.1", "port": 6428, "db": 15,
            "username": "phase728_gateway",
        }
        scope.update(overrides)
        return SimpleNamespace(connection_pool=SimpleNamespace(
            connection_kwargs=scope,
        ))

    @staticmethod
    def grant():
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase728-fast",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE728_TEST_REDIS": "1",
            "LOOMERA_PHASE726_TEST_POSTGIS": "1",
        })

    def test_restricted_scope_accepts_exact_test_target_only(self):
        with self.grant():
            self.assertEqual(
                gate.validate_gateway_scope(self.client(), "a" * 32),
                gate.PREFIX + "a" * 32 + ":",
            )
            for update in (
                {"host": "localhost"}, {"host": "10.0.0.1"},
                {"port": 6379}, {"port": 6427}, {"port": True},
                {"db": 0}, {"db": 14}, {"db": True},
                {"username": "phase728_admin"},
                {"username": "phase728_legacy"}, {"username": None},
            ):
                with self.subTest(update=update), self.assertRaises(RuntimeError):
                    gate.validate_gateway_scope(self.client(**update), "a" * 32)

    def test_reject_invalid_fixture_and_unstructured_clients(self):
        with self.grant():
            for ident in ("b" * 31, "B" * 32, "c" * 33, None, True, 12):
                with self.subTest(ident=str(ident)), self.assertRaises(ValueError):
                    gate.validate_gateway_scope(self.client(), ident)
            for bad in (
                object(), SimpleNamespace(connection_pool=None),
                SimpleNamespace(connection_pool=SimpleNamespace(
                    connection_kwargs=[],
                )),
            ):
                with self.assertRaises(RuntimeError):
                    gate.validate_gateway_scope(bad, "b" * 32)

    def test_every_ci_grant_is_indispensable(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                gate.validate_gateway_scope(self.client(), "a" * 32)
        for key in (
            "GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
            "LOOMERA_PHASE728_TEST_REDIS",
            "LOOMERA_PHASE726_TEST_POSTGIS",
        ):
            with self.grant():
                os.environ.pop(key)
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    gate.validate_gateway_scope(self.client(), "a" * 32)

    def test_truthy_values_cannot_authorize_production(self):
        for status in (
            "synthetic_redis_marker_observed", "same_operation_observed",
            "global_operation_conflict", "terminal_halt", "stale_writer",
            "missing_authority",
        ):
            review = gate.SyntheticGatewayObservation(
                status,
                synthetic_redis_marker_written=(
                    status == "synthetic_redis_marker_observed"
                ),
            )
            for flag in (
                "real_authentication_allowed", "real_otp_issue_or_consume_allowed",
                "real_session_created", "real_sms_sent",
                "all_redis_ingress_fenced", "cross_store_atomicity_proven",
                "production_release_authorized",
            ):
                self.assertIs(getattr(review, flag), False, flag)
        self.assertIn("production_release_authorized",
                      {field.name for field in fields(
                          gate.SyntheticGatewayObservation
                      )})

    def test_gateway_uses_pg_claim_in_transaction_plus_set_nx(self):
        source = inspect.getsource(gate)
        for required in (
            "SyntheticPostGISWriterAuthority", "verify_ci_test_scope",
            "transaction.atomic", "self.authority.claim",
            'self.client.set(key, fingerprint, nx=True)',
            "phase728_ambiguous_redis_marker_collision",
            "claim.status != \"synthetic_committed\"",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "FLUSHDB", "FLUSHALL", "apps.accounts.models", "apps.api.v1",
            "request.session", "login(request", "sms_ir",
            "SMSIR", "cache.delete(", "redis://127.0.0.1:6379",
        ):
            self.assertNotIn(forbidden, source)

    def test_no_live_wiring_or_migration_setting_modification(self):
        for path in (
            "apps/api/v1/auth_otp.py",
            "apps/api/v1/auth_views.py", "apps/accounts/views.py",
            "apps/accounts/models.py",
        ):
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_restricted_writer_gateway_rehearsal", source)
        # Never bind the synthetic gateway to production app settings.
        for path in ("loomera/settings.py", "loomera/settings/production.py"):
            if (ROOT / path).exists():
                self.assertNotIn(
                    "otp_restricted_writer_gateway_rehearsal",
                    (ROOT / path).read_text(encoding="utf-8"),
                )

    def test_physical_job_must_have_isolated_docker_and_both_db_grants(self):
        shell = (ROOT / "tests/phase7_postgis_restricted_writer_ci.sh").read_text(
            encoding="utf-8"
        )
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        for anchor in (
            "GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
            "LOOMERA_PHASE728_TEST_REDIS",
            "LOOMERA_PHASE726_TEST_POSTGIS",
            "--publish 127.0.0.1:6428:6379",
            "redis:7.4-alpine", "trap cleanup EXIT", "docker volume rm",
            "loomera.phase728", "phase7_postgis_mandatory_ingress",
        ):
            self.assertIn(anchor, shell)
        self.assertNotIn("FLUSHALL", shell)
        self.assertNotIn("FLUSHDB", shell)
        self.assertNotIn("docker system prune", shell)
        self.assertIn(
            "bash tests/phase7_postgis_restricted_writer_ci.sh", workflow
        )
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_restricted_writer_guards",
            workflow,
        )

    def test_real_job_checks_acls_and_ambiguity_with_real_databases(self):
        code = (ROOT / "apps/accounts/test_phase7_postgis_mandatory_ingress.py").read_text(
            encoding="utf-8"
        )
        for anchor in (
            'CLIENT", "KILL", "USER", "phase728_revoke',
            "synthetic_redis_marker_observed",
            "phase728_ambiguous_redis_marker_collision",
            "transaction.atomic",
            "old_socket_survives_acl_off",
            "test_admin_can_always_raw_write_fixture_key",
            "test_failed_ack_after_redis_write_is_not_auto_retried",
        ):
            self.assertIn(anchor, code)

    def test_release_matrix_blocks_false_global_fencing_claims(self):
        data = json.loads((
            ROOT / "docs/globalization/PHASE7_28_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "7.28")
        self.assertEqual(
            data["baseline_main_sha"],
            "6dd5b13cbe4b9db41b72430091431a98f46b1861",
        )
        for k in (
            "real_auth_code_changed", "production_auth_atomicity",
            "all_ingress_routes_closed", "prior_sockets_globally_revoked",
            "admin_raw_bypass_fenced", "postgis_redis_atomicity",
            "external_sms_exactly_once", "real_account_session_migrated",
            "real_customer_data_accessed", "security_owner_approval",
            "production_deployment_authorized", "deployed",
        ):
            self.assertIs(data[k], False, k)
        self.assertTrue(data["release_gate"].startswith("BLOCKED"))
