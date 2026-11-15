"""Phase 7.31 guards for deployed Redis configuration and safe cache probes."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.main.cache_preflight import (
    CacheProbeError,
    assess_cache_configuration,
    assess_redis_url,
    build_redis_role_inventory,
    probe_cache_backend,
)

ROOT = Path(__file__).resolve().parents[2]


class FakeCache:
    def __init__(self, *, add_result=True, observed=None):
        self.add_result = add_result
        self.observed = observed
        self.add_calls = []
        self.get_calls = []
        self.set_calls = []
        self.delete_calls = []

    def add(self, key, value, timeout=None):
        self.add_calls.append((key, value, timeout))
        return self.add_result

    def get(self, key):
        self.get_calls.append(key)
        return self.observed

    def set(self, *args, **kwargs):
        self.set_calls.append((args, kwargs))
        raise AssertionError("cache preflight must not overwrite a key")

    def delete(self, *args, **kwargs):
        self.delete_calls.append((args, kwargs))
        raise AssertionError("cache preflight must not delete a shared key")


class Phase731CachePreflightTests(SimpleTestCase):
    def cache_config(self, location, backend="django_redis.cache.RedisCache"):
        return {"BACKEND": backend, "LOCATION": location}

    def test_authenticated_tls_redis_url_passes_without_disclosing_credentials(self):
        secret = "never-print-this-redis-password"
        assessment = assess_cache_configuration(
            self.cache_config(
                f"rediss://loomera_cache:{secret}@redis.example.net:6380/0"
            ),
            deployed=True,
            debug=False,
        )
        self.assertEqual(assessment.errors, ())
        self.assertEqual(assessment.warnings, ())
        self.assertNotIn(secret, repr(assessment))

    def test_deployed_cache_requires_redis_backend_remote_host_and_password(self):
        cases = (
            (
                self.cache_config("rediss://cache_user:secret@redis.example/0",
                                  backend="django.core.cache.backends.locmem.LocMemCache"),
                "deployed_cache_backend_must_be_django_redis",
            ),
            (
                self.cache_config("rediss://cache_user:secret@localhost/0"),
                "deployed_redis_url_must_not_use_localhost",
            ),
            (
                self.cache_config("rediss://cache_user@redis.example/0"),
                "deployed_redis_password_required",
            ),
            (
                self.cache_config("redis://cache_user:secret@redis.example/0"),
                None,
            ),
            (
                self.cache_config("memcached://cache_user:secret@redis.example/0"),
                "redis_url_scheme_must_be_redis_or_rediss",
            ),
        )
        for config, expected in cases:
            with self.subTest(config=config):
                result = assess_cache_configuration(
                    config, deployed=True, debug=False,
                )
                if expected is None:
                    self.assertEqual(result.errors, ())
                    self.assertIn("redis_transport_tls_not_enabled", result.warnings)
                else:
                    self.assertIn(expected, result.errors)

    def test_invalid_redis_url_shapes_fail_closed(self):
        for value, expected in (
            ("", "redis_url_required"),
            ("redis://", "redis_url_host_required"),
            ("redis://cache_user:secret@redis.example:notaport/0",
             "redis_url_invalid"),
            ("rediss://cache_user:secret@redis.example:0/0",
             "redis_url_port_invalid"),
            ("rediss://cache_user:secret@0.0.0.0:6380/0",
             "deployed_redis_url_must_not_use_localhost"),
            ("rediss://cache_user:secret@redis.example/not-a-db",
             "redis_url_database_invalid"),
            ("rediss://cache_user:secret@redis.example:6380/0?ssl_cert_reqs=none",
             "redis_tls_certificate_verification_not_required"),
        ):
            with self.subTest(value=value):
                result = assess_redis_url(value)
                self.assertIn(expected, result.errors)
                self.assertNotIn("secret", repr(result))

    def test_default_or_missing_acl_username_is_reported_as_warning(self):
        missing = assess_redis_url("rediss://:secret@redis.example/0")
        default = assess_redis_url("rediss://default:secret@redis.example/0")
        self.assertIn("redis_named_acl_username_not_configured", missing.warnings)
        self.assertIn("redis_default_acl_username_in_use", default.warnings)
        self.assertEqual(missing.errors, ())
        self.assertEqual(default.errors, ())

    def test_non_debug_local_memory_cache_is_rejected(self):
        result = assess_cache_configuration(
            self.cache_config(
                "local-only",
                backend="django.core.cache.backends.locmem.LocMemCache",
            ),
            deployed=False,
            debug=False,
        )
        self.assertIn("non_debug_cache_must_not_use_locmem", result.errors)

    def test_cache_probe_uses_unique_add_only_key_and_short_ttl(self):
        fake = FakeCache(observed="b" * 64)
        with (
            patch("apps.main.cache_preflight.caches", {"default": fake}),
            patch(
                "apps.main.cache_preflight.secrets.token_hex",
                side_effect=["a" * 32, "b" * 64],
            ),
        ):
            probe_cache_backend(scope="infrastructure")
        self.assertEqual(len(fake.add_calls), 1)
        key, marker, timeout = fake.add_calls[0]
        self.assertEqual(key, "loomera:preflight:infrastructure:" + "a" * 32)
        self.assertEqual(marker, "b" * 64)
        self.assertEqual(timeout, 30)
        self.assertEqual(fake.get_calls, [key])
        self.assertEqual(fake.set_calls, [])
        self.assertEqual(fake.delete_calls, [])

    def test_dedicated_otp_cache_probe_uses_only_the_otp_alias(self):
        default = FakeCache()
        otp = FakeCache(observed="e" * 64)
        with (
            patch(
                "apps.main.cache_preflight.caches",
                {"default": default, "otp": otp},
            ),
            patch(
                "apps.main.cache_preflight.secrets.token_hex",
                side_effect=["f" * 32, "e" * 64],
            ),
        ):
            probe_cache_backend(scope="otp", alias="otp")
        self.assertEqual(len(otp.add_calls), 1)
        self.assertEqual(len(otp.get_calls), 1)
        self.assertEqual(default.add_calls, [])
        self.assertEqual(default.get_calls, [])

    def test_cache_probe_never_reads_or_deletes_when_add_not_confirmed(self):
        fake = FakeCache(add_result=False)
        with (
            patch("apps.main.cache_preflight.caches", {"default": fake}),
            patch(
                "apps.main.cache_preflight.secrets.token_hex",
                side_effect=["c" * 32, "d" * 64],
            ),
        ):
            with self.assertRaisesRegex(
                CacheProbeError, "cache_probe_add_not_confirmed",
            ):
                probe_cache_backend(scope="pre_beta")
        self.assertEqual(len(fake.add_calls), 1)
        self.assertEqual(fake.get_calls, [])
        self.assertEqual(fake.set_calls, [])
        self.assertEqual(fake.delete_calls, [])

    def test_cache_probe_rejects_unknown_scope_before_cache_access(self):
        fake = FakeCache()
        with patch("apps.main.cache_preflight.caches", {"default": fake}):
            with self.assertRaisesRegex(ValueError, "unsupported_cache_probe_scope"):
                probe_cache_backend(scope="customer")
        self.assertEqual(fake.add_calls, [])

    def test_production_settings_default_to_production_identity(self):
        environment = os.environ.copy()
        environment.pop("LOOMERA_ENVIRONMENT", None)
        environment.pop("DJANGO_SETTINGS_MODULE", None)
        environment.pop("LOOMERA_API_AUTH_OTP_CACHE_ALIAS", None)
        environment.pop("LOOMERA_API_AUTH_OTP_CACHE_LOCATION", None)
        environment["SECRET_KEY"] = "phase731-test-only-secret-key-not-runtime"
        environment["DATABASE_URL"] = "sqlite:///phase731-settings-check.sqlite3"
        environment["DEBUG"] = "False"
        environment["PYTHONPATH"] = str(ROOT)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import loomera.settings.production as s; "
                "print(s.LOOMERA_ENVIRONMENT)",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertEqual(result.stdout.strip().splitlines()[-1], "production")

    def test_ci_and_liara_workflows_set_explicit_environment_identity(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        staging = (ROOT / ".github/workflows/liara-staging.yml").read_text(
            encoding="utf-8"
        )
        production = (
            ROOT / ".github/workflows/liara-production.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("LOOMERA_ENVIRONMENT: ci", ci)
        self.assertIn('"LOOMERA_ENVIRONMENT=staging"', staging)
        self.assertIn('"LOOMERA_ENVIRONMENT=production"', production)

    def test_both_readiness_commands_use_the_shared_non_destructive_probe(self):
        infrastructure = (
            ROOT / "apps/main/management/commands/infrastructure_preflight_check.py"
        ).read_text(encoding="utf-8")
        pre_beta = (
            ROOT / "apps/main/management/commands/pre_beta_check.py"
        ).read_text(encoding="utf-8")
        for source, scope in (
            (infrastructure, 'scope="infrastructure"'),
            (pre_beta, 'scope="pre_beta"'),
        ):
            self.assertIn("assess_cache_configuration", source)
            self.assertIn("probe_cache_backend", source)
            self.assertIn(scope, source)
            self.assertNotIn('cache.set("loomera:', source)
            self.assertNotIn('cache.delete("loomera:', source)

    def _settings_subprocess(self, extra_env):
        environment = os.environ.copy()
        for key in (
            "LOOMERA_ENVIRONMENT",
            "LOOMERA_API_AUTH_OTP_CACHE_ALIAS",
            "LOOMERA_API_AUTH_OTP_CACHE_LOCATION",
            "CACHE_LOCATION",
        ):
            environment.pop(key, None)
        environment.update(
            {
                "SECRET_KEY": "phase731-test-only-secret-key-not-runtime",
                "DATABASE_URL": "sqlite:///phase731-settings-check.sqlite3",
                "DEBUG": "False",
                "PYTHONPATH": str(ROOT),
                **extra_env,
            }
        )
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import loomera.settings.production as s; "
                "print(s.LOOMERA_API_AUTH_OTP_CACHE_ALIAS); "
                "print(s.CACHES.get('otp', {}).get('BACKEND', 'absent')); "
                "print(s.CACHES.get('otp', {}).get('KEY_PREFIX', 'absent'))",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_dedicated_otp_alias_is_opt_in_and_uses_its_own_cache(self):
        secret = "phase731-synthetic-otp-secret"
        result = self._settings_subprocess(
            {
                "CACHE_LOCATION": "rediss://general_user:general-secret@cache.example:6380/1",
                "LOOMERA_API_AUTH_OTP_CACHE_LOCATION":
                    f"rediss://otp_user:{secret}@otp-cache.example:6380/0",
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertEqual(
            result.stdout.strip().splitlines()[-3:],
            [
                "otp",
                "django_redis.cache.RedisCache",
                "loomera:api-auth-otp-cache",
            ],
        )
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_dedicated_otp_alias_requires_location_and_named_tls_principal(self):
        missing = self._settings_subprocess(
            {"LOOMERA_API_AUTH_OTP_CACHE_ALIAS": "otp"}
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertNotIn("secret", missing.stderr.lower())

        for location in (
            "redis://otp_user:phase731-secret@otp-cache.example:6379/0",
            "rediss://default:phase731-secret@otp-cache.example:6380/0",
            "rediss://%64efault:phase731-secret@otp-cache.example:6380/0",
            "rediss://otp_user:phase731-secret@0.0.0.0:6380/0",
            (
                "rediss://otp_user:phase731-secret@otp-cache.example:6380/0"
                "?ssl_cert_reqs=none"
            ),
        ):
            with self.subTest(location=location):
                result = self._settings_subprocess(
                    {"LOOMERA_API_AUTH_OTP_CACHE_LOCATION": location}
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("phase731-secret", result.stdout + result.stderr)

    def test_dedicated_otp_alias_rejects_same_acl_principal_even_on_other_db(self):
        cases = (
            (
                "rediss://shared_user:shared-secret@redis.example:6380/1",
                "rediss://shared_user:shared-secret@redis.example:6380/9",
            ),
            (
                "rediss://shared_user:old-password@redis.example:6380/1",
                "rediss://shared_user:new-password@redis.example:6380/2",
            ),
        )
        for general, otp in cases:
            with self.subTest(general=general, otp=otp):
                result = self._settings_subprocess(
                    {
                        "CACHE_LOCATION": general,
                        "LOOMERA_API_AUTH_OTP_CACHE_LOCATION": otp,
                    }
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("shared-secret", result.stdout + result.stderr)
                self.assertNotIn("old-password", result.stdout + result.stderr)
                self.assertNotIn("new-password", result.stdout + result.stderr)

    def test_role_inventory_groups_principals_without_disclosing_identity(self):
        general = "rediss://general_user:general-secret@redis.example:6380/1"
        otp = "rediss://otp_user:otp-secret@redis.example:6380/9"
        config = SimpleNamespace(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": general,
                },
                "otp": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": otp,
                },
            },
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
            LOOMERA_ENVIRONMENT="staging",
            LOOMERA_ENABLE_CELERY=True,
            CELERY_BROKER_URL=general.replace("/1", "/2"),
            CELERY_RESULT_BACKEND=general.replace("/1", "/3"),
        )
        report = build_redis_role_inventory(config)
        roles = report["roles"]
        self.assertEqual(
            roles["general_cache"]["principal_group"],
            roles["celery_broker"]["principal_group"],
        )
        self.assertEqual(
            roles["celery_broker"]["principal_group"],
            roles["celery_result"]["principal_group"],
        )
        self.assertNotEqual(
            roles["general_cache"]["principal_group"],
            roles["api_otp"]["principal_group"],
        )
        self.assertEqual(
            roles["general_cache"]["endpoint_group"],
            roles["api_otp"]["endpoint_group"],
        )
        self.assertNotEqual(
            roles["general_cache"]["database_index"],
            roles["celery_broker"]["database_index"],
        )
        rendered = repr(report)
        for secret in (
            "redis.example", "general_user", "general-secret",
            "otp_user", "otp-secret",
        ):
            self.assertNotIn(secret, rendered)
        self.assertIn("celery_broker_shares_general_cache_principal",
                      report["warnings"])

    def test_role_inventory_treats_password_rotation_as_same_acl_principal(self):
        config = SimpleNamespace(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": (
                        "rediss://shared_user:old-password@redis.example:6380/1"
                    ),
                },
                "otp": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": (
                        "rediss://shared_user:new-password@redis.example:6380/9"
                    ),
                },
            },
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
            LOOMERA_ENVIRONMENT="staging",
            LOOMERA_ENABLE_CELERY=False,
        )
        report = build_redis_role_inventory(config)
        roles = report["roles"]
        self.assertEqual(
            roles["general_cache"]["principal_group"],
            roles["api_otp"]["principal_group"],
        )
        rendered = repr(report)
        self.assertNotIn("old-password", rendered)
        self.assertNotIn("new-password", rendered)

    def test_role_inventory_normalizes_percent_encoded_default_acl_username(self):
        config = SimpleNamespace(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://default:general-secret@redis.example:6380/1",
                },
                "otp": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": "rediss://%64efault:otp-secret@redis.example:6380/9",
                },
            },
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
            LOOMERA_ENVIRONMENT="staging",
            LOOMERA_ENABLE_CELERY=False,
        )
        report = build_redis_role_inventory(config)
        roles = report["roles"]
        self.assertEqual(
            roles["general_cache"]["principal_group"],
            roles["api_otp"]["principal_group"],
        )
        self.assertFalse(roles["api_otp"]["named_acl_user"])
        self.assertNotIn("general-secret", repr(report))
        self.assertNotIn("otp-secret", repr(report))

    def test_role_inventory_rejects_zero_port_and_invalid_database_path(self):
        for location in (
            "rediss://cache_user:secret@redis.example:0/1",
            "rediss://cache_user:secret@redis.example:6380/1/not-a-db",
        ):
            with self.subTest(location=location):
                config = SimpleNamespace(
                    CACHES={
                        "default": {
                            "BACKEND": "django_redis.cache.RedisCache",
                            "LOCATION": location,
                        }
                    },
                    LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default",
                    LOOMERA_ENVIRONMENT="staging",
                    LOOMERA_ENABLE_CELERY=False,
                )
                report = build_redis_role_inventory(config)
                self.assertEqual(
                    report["roles"]["general_cache"]["status"], "invalid",
                )

    def test_role_inventory_detects_celery_reuse_of_otp_and_result_reuse_of_cache(self):
        general = "rediss://general_user:general-secret@redis.example:6380/1"
        otp = "rediss://otp_user:otp-secret@redis.example:6380/2"
        config = SimpleNamespace(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": general,
                },
                "otp": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": otp,
                },
            },
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
            LOOMERA_ENVIRONMENT="staging",
            LOOMERA_ENABLE_CELERY=True,
            CELERY_BROKER_URL=otp,
            CELERY_RESULT_BACKEND=general,
        )
        report = build_redis_role_inventory(config)
        self.assertIn("celery_broker_shares_api_otp_principal",
                      report["warnings"])
        self.assertIn("celery_result_shares_general_cache_principal",
                      report["warnings"])

    def test_role_inventory_warns_when_dedicated_location_is_not_selected(self):
        general = "rediss://general_user:general-secret@redis.example:6380/1"
        otp = "rediss://otp_user:otp-secret@otp.example:6380/2"
        config = SimpleNamespace(
            CACHES={
                "default": {
                    "BACKEND": "django_redis.cache.RedisCache",
                    "LOCATION": general,
                }
            },
            LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default",
            LOOMERA_API_AUTH_OTP_CACHE_LOCATION=otp,
            LOOMERA_ENVIRONMENT="staging",
            LOOMERA_ENABLE_CELERY=False,
        )
        report = build_redis_role_inventory(config)
        self.assertIn(
            "api_otp_dedicated_location_configured_but_alias_default",
            report["warnings"],
        )

    def test_role_inventory_rejects_zero_port_and_invalid_database_path(self):
        for location in (
            "rediss://cache_user:secret@redis.example:0/1",
            "rediss://cache_user:secret@redis.example:6380/1/not-a-db",
        ):
            with self.subTest(location=location):
                config = SimpleNamespace(
                    CACHES={
                        "default": {
                            "BACKEND": "django_redis.cache.RedisCache",
                            "LOCATION": location,
                        }
                    },
                    LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default",
                    LOOMERA_ENVIRONMENT="staging",
                    LOOMERA_ENABLE_CELERY=False,
                )
                report = build_redis_role_inventory(config)
                self.assertEqual(
                    report["roles"]["general_cache"]["status"], "invalid",
                )

    def test_role_audit_command_is_settings_only_and_redacted(self):
        import io
        from django.core.management import call_command
        from django.test import override_settings

        output = io.StringIO()
        secret = "phase731-audit-secret"
        location = f"rediss://audit_user:{secret}@audit.example:6380/0"
        with (
            override_settings(
                LOOMERA_ENVIRONMENT="staging",
                LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default",
                LOOMERA_ENABLE_CELERY=True,
                CACHES={
                    "default": {
                        "BACKEND": "django_redis.cache.RedisCache",
                        "LOCATION": location,
                    }
                },
                CELERY_BROKER_URL=location,
                CELERY_RESULT_BACKEND=location,
            ),
            patch(
                "django.db.connection.cursor",
                side_effect=AssertionError("role audit must not query SQL"),
            ),
        ):
            call_command(
                "audit_phase7_otp_redis_roles",
                json=True,
                stdout=output,
            )
        rendered = output.getvalue()
        self.assertIn('"redis_connections_opened": false', rendered)
        self.assertIn('"database_connections_opened": false', rendered)
        self.assertIn('"api_otp_shares_general_cache_alias"', rendered)
        for value in ("audit.example", "audit_user", secret):
            self.assertNotIn(value, rendered)
