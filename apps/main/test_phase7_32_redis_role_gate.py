"""Phase 7.32 offline Redis role-configuration gate contracts (no live I/O)."""
from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from apps.main.cache_preflight import assess_redis_role_isolation


GENERAL = "rediss://general_user:secret-general@redis.example.net:6380/1"
OTP = "rediss://otp_user:secret-otp@redis.example.net:6380/2"
BROKER = "rediss://broker_user:secret-broker@redis.example.net:6380/3"
RESULT = "rediss://result_user:secret-result@redis.example.net:6380/4"


def config(
    *, general=GENERAL, otp=OTP, alias="otp", celery=False,
    broker=BROKER, result=RESULT,
):
    return SimpleNamespace(
        CACHES={
            "default": {"BACKEND": "django_redis.cache.RedisCache", "LOCATION": general},
            "otp": {"BACKEND": "django_redis.cache.RedisCache", "LOCATION": otp},
        },
        LOOMERA_API_AUTH_OTP_CACHE_ALIAS=alias,
        LOOMERA_API_AUTH_OTP_CACHE_LOCATION=otp,
        LOOMERA_ENVIRONMENT="staging",
        LOOMERA_ENABLE_CELERY=celery,
        CELERY_BROKER_URL=broker,
        CELERY_RESULT_BACKEND=result,
    )


class Phase732RedisRoleGateTests(SimpleTestCase):
    def test_independent_named_tls_principals_pass_static_gate_but_never_authorize_release(self):
        report = assess_redis_role_isolation(config(celery=True))
        self.assertEqual(report["configuration_gate"], "PASS")
        self.assertEqual(report["blocking_reasons"], [])
        self.assertEqual(
            report["required_roles"],
            ["general_cache", "api_otp", "celery_broker", "celery_result"],
        )
        for key in (
            "redis_connections_opened",
            "database_connections_opened",
            "server_side_acl_verified",
            "network_ingress_verified",
            "redis_cluster_or_dns_aliases_verified",
            "live_otp_atomicity_verified",
            "production_release_authorized",
        ):
            self.assertIs(report[key], False)
        for secret in ("redis.example.net", "secret-general", "secret-otp"):
            self.assertNotIn(secret, repr(report))

    def test_default_alias_blocks_even_when_dedicated_url_is_present(self):
        report = assess_redis_role_isolation(config(alias="default"))
        self.assertEqual(report["configuration_gate"], "FAIL")
        self.assertIn("dedicated_api_otp_alias_required", report["blocking_reasons"])
        self.assertIn("api_otp_shares_general_cache_principal", report["blocking_reasons"])

    def test_plaintext_or_default_acl_or_unauthenticated_roles_fail(self):
        cases = (
            (dict(general=GENERAL.replace("rediss://", "redis://")),
             "general_cache_tls_required"),
            (dict(general=GENERAL.replace("general_user", "default")),
             "general_cache_named_acl_user_required"),
            (dict(otp="rediss://otp_user@redis.example.net:6380/2"),
             "api_otp_invalid_redis_url"),
            (dict(otp="rediss://otp_user:secret-otp@redis.example.net:6380/2"
                      "?ssl_cert_reqs=none"),
             "api_otp_invalid_redis_url"),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                report = assess_redis_role_isolation(config(**overrides))
                self.assertEqual(report["configuration_gate"], "FAIL")
                self.assertIn(reason, report["blocking_reasons"])
                self.assertNotIn("secret-otp", repr(report))

    def test_celery_requires_distinct_roles_and_rejects_logical_db_as_boundary(self):
        report = assess_redis_role_isolation(
            config(
                celery=True,
                broker="rediss://general_user:new-secret@redis.example.net:6380/5",
                result="rediss://general_user:another-secret@redis.example.net:6380/6",
            )
        )
        self.assertEqual(report["configuration_gate"], "FAIL")
        self.assertIn(
            "celery_broker_shares_general_cache_principal",
            report["blocking_reasons"],
        )
        self.assertIn(
            "celery_result_shares_general_cache_principal",
            report["blocking_reasons"],
        )

    def test_disabled_celery_does_not_require_celery_credentials(self):
        report = assess_redis_role_isolation(
            config(celery=False, broker="", result="")
        )
        self.assertEqual(report["configuration_gate"], "PASS")
        self.assertEqual(report["required_roles"], ["general_cache", "api_otp"])

    def test_enabled_celery_rejects_non_redis_result_backend(self):
        report = assess_redis_role_isolation(
            config(celery=True, result="rpc://")
        )
        self.assertEqual(report["configuration_gate"], "FAIL")
        self.assertIn("celery_result_not_configured", report["blocking_reasons"])

    def test_audit_command_preserves_legacy_json_and_blocks_bad_gate(self):
        settings = config(alias="default")
        with override_settings(**vars(settings)):
            legacy_out = io.StringIO()
            call_command("audit_phase7_otp_redis_roles", json=True, stdout=legacy_out)
            self.assertNotIn("configuration_assessment", json.loads(legacy_out.getvalue()))

            gated_out = io.StringIO()
            with self.assertRaises(SystemExit) as caught:
                call_command(
                    "audit_phase7_otp_redis_roles",
                    json=True,
                    require_isolation=True,
                    stdout=gated_out,
                )
            self.assertEqual(caught.exception.code, 1)
            result = json.loads(gated_out.getvalue())
            self.assertEqual(
                result["configuration_assessment"]["configuration_gate"], "FAIL"
            )
            self.assertIs(result["production_release_authorized"], False)
            for secret in ("redis.example.net", "secret-general", "secret-otp"):
                self.assertNotIn(secret, gated_out.getvalue())

    def test_audit_command_accepts_safe_static_gate_but_never_attests_runtime(self):
        settings = config(celery=True)
        with (
            override_settings(**vars(settings)),
            patch(
                "apps.main.cache_preflight.probe_cache_backend",
                side_effect=AssertionError("configuration audit must not probe Redis"),
            ),
        ):
            output = io.StringIO()
            call_command(
                "audit_phase7_otp_redis_roles",
                json=True,
                require_isolation=True,
                stdout=output,
            )
        result = json.loads(output.getvalue())
        self.assertEqual(
            result["configuration_assessment"]["configuration_gate"], "PASS"
        )
        self.assertFalse(result["production_release_authorized"])
        self.assertFalse(result["configuration_assessment"]["server_side_acl_verified"])
