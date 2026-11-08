"""Phase 7.27 offline ingress completeness, no-PII and fail-closed gates."""
from __future__ import annotations

from dataclasses import fields, replace
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_ingress_boundary_policy as policy

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_27_EXIT_MATRIX.json"


def inventory(*, bypass=True):
    return tuple(policy.SyntheticIngressRoute(name, index == 0,
                 bypass and index in (1, 2, 3, 4))
                 for index, name in enumerate(policy.ROUTES))


class Phase727IngressBoundaryOfflineGuards(SimpleTestCase):
    @staticmethod
    def fake_redis(**updates):
        kwargs = {"host": "127.0.0.1", "port": 6427, "db": 15}
        kwargs.update(updates)
        return SimpleNamespace(connection_pool=SimpleNamespace(
            connection_kwargs=kwargs
        ))

    @staticmethod
    def grant():
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "phase727-fast",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE727_TEST_REDIS": "1",
        })

    def test_exact_loopback_db_and_random_fixture_are_required(self):
        with self.grant():
            self.assertEqual(
                policy.validate_disposable_redis(self.fake_redis(), "a" * 32),
                policy.PREFIX + "a" * 32 + ":",
            )
            for kwargs in (
                {"host": "localhost"}, {"host": "10.0.0.1"},
                {"port": 6379}, {"port": 6428}, {"db": 0},
                {"db": 14}, {"db": True}, {"port": True},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                    policy.validate_disposable_redis(
                        self.fake_redis(**kwargs), "a" * 32
                    )
            for fixture in ("A" * 32, "b" * 31, "b" * 33, None, True):
                with self.subTest(fixture=str(fixture)), self.assertRaises(ValueError):
                    policy.validate_disposable_redis(self.fake_redis(), fixture)

    def test_explicit_ci_authority_is_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                policy.validate_disposable_redis(self.fake_redis(), "a" * 32)
        for key in (
            "GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
            "LOOMERA_PHASE727_TEST_REDIS",
        ):
            with self.grant():
                os.environ.pop(key)
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    policy.validate_disposable_redis(self.fake_redis(), "a" * 32)

    def test_wrong_client_object_rejected_before_io(self):
        with self.grant():
            for client in (object(), SimpleNamespace(connection_pool=None),
                           SimpleNamespace(connection_pool=SimpleNamespace(
                               connection_kwargs=[]))):
                with self.assertRaises(RuntimeError):
                    policy.validate_disposable_redis(client, "a" * 32)

    def test_ungated_raw_route_blocks_release_even_with_pg_and_acl_claims(self):
        value = policy.review_synthetic_ingress(
            inventory(), pg_stale_claim_rejected=True,
            local_stale_acl_revoked=True,
        )
        self.assertEqual(value.status, "ungated_raw_redis_writer_observed")
        self.assertTrue(value.operator_review_required)
        for field in fields(policy.SyntheticIngressReview):
            if field.name.endswith(("proven", "allowed", "created", "authorized")):
                self.assertIs(getattr(value, field.name), False, field.name)

    def test_even_all_local_denials_prove_no_global_permission(self):
        value = policy.review_synthetic_ingress(
            inventory(bypass=False), pg_stale_claim_rejected=True,
            local_stale_acl_revoked=True,
        )
        self.assertEqual(value.status, "bounded_local_denial_evidence_only")
        self.assertFalse(value.actual_global_writer_fencing_proven)
        self.assertFalse(value.all_ingress_routes_closed)
        self.assertFalse(value.production_release_authorized)

    def test_unverified_pg_or_acl_never_grants(self):
        value = policy.review_synthetic_ingress(
            inventory(bypass=False), pg_stale_claim_rejected=False,
            local_stale_acl_revoked=True,
        )
        self.assertEqual(value.status, "pg_stale_writer_denial_missing")
        value = policy.review_synthetic_ingress(
            inventory(bypass=False), pg_stale_claim_rejected=True,
            local_stale_acl_revoked=False,
        )
        self.assertEqual(value.status, "local_credential_revocation_unverified")

    def test_missing_pg_check_is_explicitly_denied(self):
        rows = list(inventory(bypass=False))
        rows[0] = replace(rows[0], authority_checked=False)
        self.assertEqual(
            policy.review_synthetic_ingress(
                tuple(rows), pg_stale_claim_rejected=True,
                local_stale_acl_revoked=True,
            ).status, "pg_authority_not_observed",
        )

    def test_all_missing_extra_reordered_and_wrong_typed_inventory_denied(self):
        good = inventory()
        for bad in (None, [], (), good[:3], good + good[:1],
                    tuple(reversed(good)), (object(),) + good[1:]):
            with self.subTest(value=str(type(bad))), self.assertRaises(ValueError):
                policy.review_synthetic_ingress(
                    bad, pg_stale_claim_rejected=True,
                    local_stale_acl_revoked=True,
                )

    def test_route_names_and_bool_type_must_be_exact(self):
        for args in (
            ("production", True, False),
            ("old_host_raw", 1, False),
            ("old_host_raw", False, 0),
            ("old_host_raw", False, None),
        ):
            with self.subTest(args=str(args)), self.assertRaises((TypeError, ValueError)):
                policy.SyntheticIngressRoute(*args)
        for kwargs in (
            {"pg_stale_claim_rejected": 1, "local_stale_acl_revoked": True},
            {"pg_stale_claim_rejected": True, "local_stale_acl_revoked": 1},
        ):
            with self.assertRaises(TypeError):
                policy.review_synthetic_ingress(inventory(), **kwargs)

    def test_no_live_api_auth_account_sms_session_or_settings_wiring(self):
        source = inspect.getsource(policy)
        for forbidden in (
            "apps.accounts.models", "apps.api.v1", "request.session",
            "login(request", "FLUSHDB", "FLUSHALL",
            "SMSIR", "sms_ir", "real_otp_code", ".objects.",
        ):
            self.assertNotIn(forbidden, source)
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            live = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_ingress_boundary_policy", live)
            self.assertNotIn("test_phase7_postgis_redis_ingress", live)

    def test_runner_uses_exact_docker_resources_and_postgis_only(self):
        shell = (ROOT / "tests/phase7_postgis_redis_ingress_ci.sh").read_text(
            encoding="utf-8"
        )
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        for marker in (
            "GITHUB_ACTIONS", "LOOMERA_PHASE727_TEST_REDIS",
            "LOOMERA_PHASE726_TEST_POSTGIS", "6427",
            "trap cleanup EXIT", "--publish 127.0.0.1:",
            "docker volume rm", "loomera.phase727",
        ):
            self.assertIn(marker, shell)
        self.assertIn("bash tests/phase7_postgis_redis_ingress_ci.sh",
                      workflow)
        ingress = (ROOT / "apps/accounts/test_phase7_postgis_redis_ingress.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"CLIENT", "KILL", "USER", "phase727_stale"', ingress)
        self.assertIn("existing-socket-survives-acl-off", ingress)
        self.assertNotIn("FLUSHALL", shell)
        self.assertNotIn("FLUSHDB", shell)

    def test_machine_release_matrix_blocked(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "7.27")
        self.assertEqual(
            data["baseline_main_sha"],
            "6e4afcb685ce5d9398c57c1761f4acbc9294dcd7",
        )
        for field in (
            "production_auth_changed", "raw_old_master_globally_fenced",
            "all_writer_ingress_authority_enforced", "postgres_redis_atomicity",
            "external_sms_exactly_once", "live_account_or_session_atomicity",
            "real_customer_data_accessed", "security_owner_signoff",
            "production_deployment_authorized", "deployed",
        ):
            self.assertIs(data[field], False, field)
        self.assertTrue(data["release_gate"].startswith("BLOCKED"))
