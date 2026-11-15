"""Live API OTP cache-alias selection guards; default behavior stays unchanged."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.api.v1 import auth_otp


class FakeOtpCache:
    def __init__(self):
        self.values = {}
        self.calls = []

    def get(self, key, default=None):
        self.calls.append(("get", key))
        return self.values.get(key, default)

    def set(self, key, value, timeout=None):
        self.calls.append(("set", key, timeout))
        self.values[key] = value
        return True

    def delete(self, key):
        self.calls.append(("delete", key))
        return self.values.pop(key, None) is not None


class ApiOtpCacheAliasTests(SimpleTestCase):
    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default")
    def test_default_alias_preserves_existing_global_cache_proxy(self):
        self.assertIs(auth_otp._otp_cache(), auth_otp.cache)

    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp")
    def test_dedicated_alias_resolves_only_the_named_cache(self):
        fake = FakeOtpCache()
        with patch("apps.api.v1.auth_otp.caches", {"otp": fake}):
            self.assertIs(auth_otp._otp_cache(), fake)

    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp")
    def test_get_set_and_delete_helpers_use_the_dedicated_alias(self):
        fake = FakeOtpCache()
        with patch("apps.api.v1.auth_otp.caches", {"otp": fake}):
            auth_otp._cache_set("synthetic:record", {"marker": "only-test"}, timeout=30)
            self.assertEqual(
                auth_otp._cache_get("synthetic:record"),
                {"marker": "only-test"},
            )
            self.assertTrue(auth_otp._cache_delete(
                "synthetic:record", context="synthetic", required=True,
            ))
        self.assertEqual(
            [entry[0] for entry in fake.calls],
            ["set", "get", "delete"],
        )

    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp")
    def test_rate_counter_uses_dedicated_alias(self):
        fake = FakeOtpCache()
        with (
            patch("apps.api.v1.auth_otp.caches", {"otp": fake}),
            patch("apps.api.v1.auth_otp.api_otp_now_ts", return_value=3600),
        ):
            auth_otp._increment_hour_rate(scope="ip", value="synthetic", limit=5)
        self.assertEqual([entry[0] for entry in fake.calls], ["get", "set"])
        self.assertTrue(fake.calls[0][1].startswith("loomera:api-auth-otp:rate:"))
