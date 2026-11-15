"""Phase 7.31 runtime Redis-role audit, configuration and safety regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from apps.main.management.commands.infrastructure_preflight_check import (
    Command as InfrastructurePreflightCommand,
)
from loomera.globalization.otp_redis_runtime_role_policy import (
    audit_runtime_redis_roles,
)

ROOT = Path(__file__).resolve().parents[2]


def _settings(**updates):
    values = {
        "LOOMERA_ENVIRONMENT": "production",
        "CACHES": {
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": "redis://cache-user:cache-secret@cache.internal:6379/1",
            },
        },
        "LOOMERA_API_AUTH_OTP_CACHE_ALIAS": "default",
        "LOOMERA_ENABLE_CELERY": True,
        "CELERY_BROKER_URL": "redis://cache-user:cache-secret@cache.internal:6379/5",
        "CELERY_RESULT_BACKEND": "redis://cache-user:cache-secret@cache.internal:6379/7",
    }
    values.update(updates)
    return SimpleNamespace(**values)


class Phase731RedisRuntimeRolePolicyTests(SimpleTestCase):
    def test_current_shared_default_cache_and_celery_defaults_are_detected(self):
        report = audit_runtime_redis_roles(_settings())
        self.assertEqual(report["phase"], "7.31")
        self.assertEqual(report["release_gate"], "BLOCKED")
        self.assertIn("OTP_SHARES_DEFAULT_DJANGO_CACHE_ALIAS", report["findings"])
        self.assertIn("OTP_HAS_NO_DEDICATED_REDIS_PRINCIPAL_BOUNDARY",
                      report["findings"])
        self.assertIn("CELERY_BROKER_REUSES_GENERAL_CACHE_REDIS_PRINCIPAL",
                      report["findings"])
        self.assertIn("CELERY_RESULT_REUSES_BROKER_REDIS_PRINCIPAL",
                      report["findings"])
        roles = {role["name"]: role for role in report["roles"]}
        self.assertEqual(
            roles["django_cache_default"]["principal_group"],
            roles["celery_broker"]["principal_group"],
        )
        self.assertEqual(
            roles["celery_broker"]["principal_group"],
            roles["celery_result"]["principal_group"],
        )
        self.assertFalse(report["production_release_authorized"])

    def test_separate_named_users_on_same_server_are_distinct_principals(self):
        report = audit_runtime_redis_roles(_settings(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://cache-user:cache-secret@redis.internal:6380/1",
                },
                "otp": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://otp-user:otp-secret@redis.internal:6380/2",
                },
            },
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
            CELERY_BROKER_URL=(
                "rediss://broker-user:broker-secret@redis.internal:6380/3"
            ),
            CELERY_RESULT_BACKEND=(
                "rediss://result-user:result-secret@redis.internal:6380/4"
            ),
        ))
        roles = {role["name"]: role for role in report["roles"]}
        self.assertEqual(
            roles["django_cache_default"]["endpoint_group"],
            roles["api_otp"]["endpoint_group"],
        )
        self.assertNotEqual(
            roles["django_cache_default"]["principal_group"],
            roles["api_otp"]["principal_group"],
        )
        self.assertNotEqual(
            roles["celery_broker"]["principal_group"],
            roles["celery_result"]["principal_group"],
        )
        self.assertNotIn("OTP_SHARES_DEFAULT_DJANGO_CACHE_ALIAS",
                         report["findings"])
        self.assertNotIn("OTP_AND_GENERAL_CACHE_REUSE_REDIS_PRINCIPAL",
                         report["findings"])
        # Configuration separation is necessary but cannot prove server ACLs.
        self.assertIn("REDIS_SERVER_ACL_RULES_NOT_READ_OR_VERIFIED",
                      report["findings"])
        self.assertEqual(report["release_gate"], "BLOCKED")

    def test_logical_database_number_does_not_create_a_security_boundary(self):
        report = audit_runtime_redis_roles(_settings(
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://shared-user:secret-a@redis.internal:6380/1",
                },
                "otp": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://shared-user:secret-b@redis.internal:6380/9",
                },
            },
            LOOMERA_ENABLE_CELERY=False,
        ))
        self.assertIn("OTP_AND_GENERAL_CACHE_REUSE_REDIS_PRINCIPAL",
                      report["findings"])
        roles = {role["name"]: role for role in report["roles"]}
        self.assertEqual(
            roles["django_cache_default"]["principal_group"],
            roles["api_otp"]["principal_group"],
        )

    def test_deployed_plaintext_default_user_and_local_targets_are_blockers(self):
        report = audit_runtime_redis_roles(_settings(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "redis://default:plain-secret@127.0.0.1:6379/1",
                },
            },
            LOOMERA_ENABLE_CELERY=False,
        ))
        self.assertIn("DJANGO_CACHE_DEFAULT_REDIS_TLS_REQUIRED",
                      report["findings"])
        self.assertIn("DJANGO_CACHE_DEFAULT_NAMED_REDIS_ACL_USER_REQUIRED",
                      report["findings"])
        self.assertIn("DJANGO_CACHE_DEFAULT_LOCAL_REDIS_ENDPOINT_FORBIDDEN",
                      report["findings"])

    def test_invalid_and_missing_targets_are_reported_without_echoing_input(self):
        secret = "never-print-this-password"
        report = audit_runtime_redis_roles(_settings(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": f"redis://user:{secret}@",
                },
            },
            LOOMERA_ENABLE_CELERY=False,
            CELERY_BROKER_URL="",
            CELERY_RESULT_BACKEND="",
        ))
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("redis://", rendered)
        roles = {role["name"]: role for role in report["roles"]}
        self.assertIn(roles["django_cache_default"]["status"], {"invalid", "missing"})
        self.assertEqual(roles["celery_broker"]["status"], "missing")

    def test_unused_dedicated_otp_location_is_not_mistaken_for_active_isolation(self):
        report = audit_runtime_redis_roles(_settings(
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default",
            LOOMERA_API_AUTH_OTP_CACHE_LOCATION=(
                "rediss://otp-user:otp-secret@otp.internal:6380/2"
            ),
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://cache-user:cache-secret@cache.internal:6380/1",
                },
                "otp": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://otp-user:otp-secret@otp.internal:6380/2",
                },
            },
            LOOMERA_ENABLE_CELERY=False,
        ))
        self.assertIn(
            "DEDICATED_OTP_REDIS_LOCATION_CONFIGURED_BUT_NOT_SELECTED",
            report["findings"],
        )
        self.assertIn("OTP_SHARES_DEFAULT_DJANGO_CACHE_ALIAS", report["findings"])

    def test_audit_never_emits_host_username_or_password(self):
        report = audit_runtime_redis_roles(_settings(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": (
                        "rediss://private-cache-user:private-cache-secret@"
                        "private-cache.internal:6380/1"
                    ),
                },
                "otp": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": (
                        "rediss://private-otp-user:private-otp-secret@"
                        "private-otp.internal:6380/2"
                    ),
                },
            },
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
            LOOMERA_ENABLE_CELERY=False,
        ))
        rendered = json.dumps(report, sort_keys=True)
        for secret in (
            "private-cache-user", "private-cache-secret",
            "private-otp-user", "private-otp-secret",
            "private-cache.internal", "private-otp.internal",
        ):
            self.assertNotIn(secret, rendered)

    def test_invalid_redis_port_is_rejected_without_exposing_target(self):
        report = audit_runtime_redis_roles(_settings(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://user:secret@redis.internal:70000/1",
                },
            },
            LOOMERA_ENABLE_CELERY=False,
        ))
        roles = {role["name"]: role for role in report["roles"]}
        self.assertEqual(roles["django_cache_default"]["status"], "invalid")
        self.assertNotIn("redis.internal", json.dumps(report))
        self.assertNotIn("secret", json.dumps(report))

    def test_disabled_celery_roles_are_not_counted_as_active_writers(self):
        report = audit_runtime_redis_roles(_settings(LOOMA_ENABLE_CELERY=False))
        roles = {role["name"]: role for role in report["roles"]}
        self.assertFalse(roles["celery_broker"]["active"])
        self.assertFalse(roles["celery_result"]["active"])

    def test_audit_command_emits_json_without_network_or_secret_access(self):
        output = StringIO()
        with patch(
            "apps.main.management.commands.audit_phase7_otp_redis_roles."
            "audit_runtime_redis_roles",
            return_value=audit_runtime_redis_roles(_settings()),
        ):
            call_command(
                "audit_phase7_otp_redis_roles", as_json=True, stdout=output,
            )
        report = json.loads(output.getvalue())
        self.assertEqual(report["phase"], "7.31")
        self.assertEqual(report["release_gate"], "BLOCKED")
        self.assertFalse(report["redis_connections_opened"])
        self.assertFalse(report["database_connections_opened"])
        self.assertFalse(report["secrets_emitted"])

    def test_otp_dedicated_preflight_checks_only_the_selected_alias(self):
        command = InfrastructurePreflightCommand()
        command.failed = False
        output = StringIO()
        command.stdout = output
        fake_cache = Mock()
        fake_cache.get.side_effect = lambda key: marker
        handler = MagicMock()
        handler.__getitem__.return_value = fake_cache
        marker = "synthetic-preflight-marker"
        with override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp"):
            with patch(
                "apps.main.management.commands.infrastructure_preflight_check.caches",
                handler,
            ):
                command._check_otp_cache()
        handler.__getitem__.assert_called_once_with("otp")
        fake_cache.set.assert_called_once()
        fake_cache.get.assert_called_once()
        fake_cache.delete.assert_called_once()
        self.assertFalse(command.failed)
        self.assertNotIn(marker, output.getvalue())

    def test_default_alias_preflight_does_not_duplicate_cache_writes(self):
        command = InfrastructurePreflightCommand()
        command.failed = False
        with override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default"):
            with patch(
                "apps.main.management.commands.infrastructure_preflight_check.caches",
                side_effect=AssertionError("unexpected cache lookup"),
            ):
                command._check_otp_cache()
        self.assertFalse(command.failed)

    def test_settings_opt_in_creates_otp_alias_without_printing_url(self):
        env = os.environ.copy()
        for key in (
            "LOOMERA_API_AUTH_OTP_CACHE_LOCATION",
            "LOOMERA_API_AUTH_OTP_CACHE_ALIAS",
        ):
            env.pop(key, None)
        env.update({
            "SECRET_KEY": "phase731-settings-test",
            "DATABASE_URL": "sqlite:///phase731-settings-test.sqlite3",
            "DEBUG": "False",
            "ALLOWED_HOSTS": "localhost,127.0.0.1",
            "CSRF_TRUSTED_ORIGINS": "http://localhost,http://127.0.0.1",
            "ONLINE_PAYMENT_ENABLED": "False",
            "PAYMENT_MODE": "mock",
            "LOOMERA_API_AUTH_OTP_CACHE_LOCATION":
                "rediss://otp-user:secret-value@otp.internal:6380/2",
        })
        script = (
            "import json; from loomera.settings import base; "
            "print(json.dumps({'alias': base.LOOMERA_API_AUTH_OTP_CACHE_ALIAS, "
            "'configured': 'otp' in base.CACHES, "
            "'backend': base.CACHES['otp']['BACKEND']}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=settings.BASE_DIR,
            env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertNotIn("secret-value", result.stdout)
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1]),
            {
                "alias": "otp",
                "configured": True,
                "backend": "django_redis.cache.RedisCache",
            },
        )

    def test_settings_rejects_missing_or_unknown_otp_alias(self):
        base_env = os.environ.copy()
        for key in (
            "LOOMERA_API_AUTH_OTP_CACHE_LOCATION",
            "LOOMERA_API_AUTH_OTP_CACHE_ALIAS",
        ):
            base_env.pop(key, None)
        base_env.update({
            "SECRET_KEY": "phase731-settings-test",
            "DATABASE_URL": "sqlite:///phase731-settings-test.sqlite3",
            "DEBUG": "False",
            "ALLOWED_HOSTS": "localhost,127.0.0.1",
            "CSRF_TRUSTED_ORIGINS": "http://localhost,http://127.0.0.1",
            "ONLINE_PAYMENT_ENABLED": "False",
            "PAYMENT_MODE": "mock",
        })
        script = "from loomera.settings import base; print('SETTINGS_OK')"
        for overrides in (
            {"LOOMERA_API_AUTH_OTP_CACHE_ALIAS": "otp"},
            {"LOOMERA_API_AUTH_OTP_CACHE_ALIAS": "missing"},
            {"LOOMERA_API_AUTH_OTP_CACHE_LOCATION": "http://not-redis"},
        ):
            env = base_env.copy()
            env.update(overrides)
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=settings.BASE_DIR,
                env=env, capture_output=True, text=True, check=False,
            )
            with self.subTest(overrides=overrides):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)

    def test_live_otp_uses_alias_but_default_proxy_compatibility_is_retained(self):
        source = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        self.assertIn("from django.core.cache import cache, caches", source)
        self.assertIn(
            'return cache if alias == "default" else caches[alias]', source,
        )
        for forbidden in (
            "redis.Redis(", "redis.from_url(", "otp_outbox_review_rehearsal",
            "otp_restricted_writer_gateway_rehearsal",
        ):
            self.assertNotIn(forbidden, source)

    def test_runtime_audit_and_synthetic_rehearsals_are_not_live_wired(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
            "loomera/settings/production.py",
        ):
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_redis_runtime_role_policy", source)
            self.assertNotIn("otp_outbox_review_rehearsal", source)
        policy_source = (
            ROOT / "loomera/globalization/otp_redis_runtime_role_policy.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "redis.Redis(", "redis.from_url(", "connection.cursor(",
            "cache.set(", "cache.delete(",
        ):
            self.assertNotIn(forbidden, policy_source)

    def test_preflight_tests_only_the_opted_in_alias_and_never_logs_credentials(self):
        source = (
            ROOT / "apps/main/management/commands/infrastructure_preflight_check.py"
        ).read_text(encoding="utf-8")
        self.assertIn("LOOMERA_API_AUTH_OTP_CACHE_ALIAS", source)
        self.assertIn("caches[alias]", source)
        self.assertIn("otp_cache.delete(key)", source)
        self.assertNotIn("LOOMERA_API_AUTH_OTP_CACHE_LOCATION", source)

    def test_exit_matrix_preserves_all_release_blockers(self):
        matrix = json.loads((
            ROOT / "docs/globalization/PHASE7_31_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.31")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "ff8ec57bd595f4133c2502bbf8bd1da853caa253",
        )
        for field in (
            "live_otp_atomic_consume_proven",
            "redis_server_acl_verified",
            "global_redis_ingress_fenced",
            "privileged_writer_revocation_proven",
            "stale_socket_revocation_proven",
            "outbox_connected_to_live_otp",
            "production_release_authorized",
            "deployed",
        ):
            self.assertIs(matrix[field], False, field)
        self.assertEqual(matrix["release_gate"], "BLOCKED")
