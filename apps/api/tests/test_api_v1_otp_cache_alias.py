"""Phase 7.31 API OTP cache-alias routing regressions."""
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from apps.api.v1.auth_otp import (
    ApiOtpRateLimitUnavailable,
    API_AUTH_OTP_PURPOSE_LOGIN,
    api_otp_cache_alias,
    create_api_otp_request,
    load_api_otp_record,
    otp_hour_rate_cache_key,
    otp_record_cache_key,
    otp_resend_cache_key,
    verify_api_otp_code,
)


def _cache_config():
    return {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "phase731-default-cache",
        },
        "otp": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "phase731-otp-cache",
        },
    }


@override_settings(
    CACHES=_cache_config(),
    LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
    LOOMERA_API_AUTH_OTP_FAIL_CLOSED=True,
    LOOMERA_API_AUTH_OTP_LENGTH=6,
    LOOMERA_API_AUTH_OTP_TTL_SECONDS=120,
    LOOMERA_API_AUTH_OTP_RESEND_SECONDS=60,
    LOOMERA_API_AUTH_OTP_REQUEST_RATE_PER_MOBILE_HOUR=5,
    LOOMERA_API_AUTH_OTP_REQUEST_RATE_PER_IP_HOUR=30,
)
class ApiOtpDedicatedCacheAliasTests(SimpleTestCase):
    def setUp(self):
        caches["default"].clear()
        caches["otp"].clear()

    def test_request_rate_resend_and_record_state_use_only_otp_alias(self):
        mobile = "09121234567"
        with patch(
            "apps.api.v1.auth_otp.generate_numeric_otp", return_value="123456",
        ):
            create_api_otp_request(mobile_number=mobile)

        record_key = otp_record_cache_key(
            purpose=API_AUTH_OTP_PURPOSE_LOGIN, mobile_number=mobile,
        )
        resend_key = otp_resend_cache_key(
            purpose=API_AUTH_OTP_PURPOSE_LOGIN, mobile_number=mobile,
        )
        rate_key = otp_hour_rate_cache_key(
            scope="mobile", value=f"{API_AUTH_OTP_PURPOSE_LOGIN}:{mobile}",
        )

        self.assertEqual(api_otp_cache_alias(), "otp")
        self.assertIsNotNone(caches["otp"].get(record_key))
        self.assertIsNotNone(caches["otp"].get(resend_key))
        self.assertEqual(caches["otp"].get(rate_key), 1)
        self.assertIsNone(caches["default"].get(record_key))
        self.assertIsNone(caches["default"].get(resend_key))
        self.assertIsNone(caches["default"].get(rate_key))

    def test_successful_verify_consumes_record_from_dedicated_alias(self):
        mobile = "09121234567"
        with patch(
            "apps.api.v1.auth_otp.generate_numeric_otp", return_value="123456",
        ):
            create_api_otp_request(mobile_number=mobile)

        key = otp_record_cache_key(
            purpose=API_AUTH_OTP_PURPOSE_LOGIN, mobile_number=mobile,
        )
        self.assertIsNotNone(caches["otp"].get(key))
        result = verify_api_otp_code(mobile_number=mobile, code="123456")
        self.assertTrue(result["verified"])
        self.assertIsNone(caches["otp"].get(key))
        self.assertIsNone(caches["default"].get(key))

    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="missing")
    def test_missing_alias_fails_closed_before_otp_state_is_accepted(self):
        with self.assertRaises(ApiOtpRateLimitUnavailable):
            load_api_otp_record(mobile_number="09121234567")

    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default")
    def test_default_alias_remains_backward_compatible(self):
        mobile = "09121234567"
        with patch(
            "apps.api.v1.auth_otp.generate_numeric_otp", return_value="123456",
        ):
            create_api_otp_request(mobile_number=mobile)
        key = otp_record_cache_key(
            purpose=API_AUTH_OTP_PURPOSE_LOGIN, mobile_number=mobile,
        )
        self.assertEqual(api_otp_cache_alias(), "default")
        self.assertIsNotNone(caches["default"].get(key))
        self.assertIsNone(caches["otp"].get(key))

    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="missing")
    @override_settings(LOOMERA_API_AUTH_OTP_FAIL_CLOSED=False)
    def test_explicit_local_open_policy_is_preserved_for_missing_alias(self):
        self.assertIsNone(load_api_otp_record(mobile_number="09121234567"))
