"""Phase 7.31 guards for deployed Redis configuration and safe cache probes."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.main.cache_preflight import (
    CacheProbeError,
    assess_cache_configuration,
    assess_redis_url,
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
