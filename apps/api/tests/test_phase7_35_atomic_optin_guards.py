"""Phase 7.35 offline guards for opt-in real API atomic OTP verification.

No Redis, database, account or production cache is accessed by these tests.
Real Django-Redis bytes/races are exercised separately in isolated Redis CI.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from apps.api.v1 import auth_otp
from apps.api.v1.auth_views import ApiOtpVerifyAPIView
from apps.api.v1.otp_atomic_verify import AtomicOtpOutcome, atomic_verify_legacy_record

ROOT = Path(__file__).resolve().parents[3]
MOBILE = "09123456789"
CODE = "123456"


@override_settings(
    LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_VERIFY=True,
    LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
    LOOMERA_API_AUTH_OTP_FAIL_CLOSED=True,
    LOOMERA_API_AUTH_OTP_LENGTH=6,
)
class Phase735AtomicOtpOptinGuards(SimpleTestCase):
    def verify(self, outcome):
        with (
            patch("apps.api.v1.auth_otp._otp_cache", return_value=object()),
            patch(
                "apps.api.v1.otp_atomic_verify.atomic_verify_legacy_record",
                return_value=outcome,
            ) as atomic,
        ):
            result = auth_otp.verify_api_otp_code(
                mobile_number=MOBILE, code=CODE
            )
        atomic.assert_called_once()
        kwargs = atomic.call_args.kwargs
        self.assertEqual(kwargs["mobile_number"], MOBILE)
        self.assertEqual(kwargs["purpose"], auth_otp.API_AUTH_OTP_PURPOSE_LOGIN)
        self.assertEqual(kwargs["ttl_seconds"], auth_otp.api_otp_ttl_seconds())
        self.assertEqual(kwargs["submitted_hash"], auth_otp.hash_otp_code(
            mobile_number=MOBILE, code=CODE,
            purpose=auth_otp.API_AUTH_OTP_PURPOSE_LOGIN,
        ))
        return result

    def test_confirmed_atomic_consumption_is_only_success_outcome(self):
        record = {"verified": True, "verified_at": 1000}
        self.assertEqual(
            self.verify(AtomicOtpOutcome("verified", record=record)), record
        )

    def test_missing_expired_exhausted_wrong_and_conflict_map_to_safe_results(self):
        cases = (
            ("missing", auth_otp.ApiOtpNotFound),
            ("expired", auth_otp.ApiOtpExpired),
            ("exhausted", auth_otp.ApiOtpMaxAttemptsExceeded),
            ("wrong", auth_otp.ApiOtpInvalidCode),
            ("unavailable", auth_otp.ApiOtpRateLimitUnavailable),
        )
        for status, expected in cases:
            with self.subTest(status=status):
                with self.assertRaises(expected) as exception:
                    self.verify(AtomicOtpOutcome(status, attempts_remaining=2))
                if status == "wrong":
                    self.assertEqual(exception.exception.attempts_remaining, 2)

    def test_verified_without_record_never_authenticates(self):
        with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
            self.verify(AtomicOtpOutcome("verified"))

    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default")
    def test_atomic_flag_rejects_shared_default_cache_before_any_io(self):
        with patch("apps.api.v1.auth_otp._otp_cache") as cache:
            with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                auth_otp.verify_api_otp_code(mobile_number=MOBILE, code=CODE)
        cache.assert_not_called()

    @override_settings(LOOMERA_API_AUTH_OTP_FAIL_CLOSED=False)
    def test_atomic_flag_rejects_failopen_cache_policy_before_any_io(self):
        with patch("apps.api.v1.auth_otp._otp_cache") as cache:
            with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                auth_otp.verify_api_otp_code(mobile_number=MOBILE, code=CODE)
        cache.assert_not_called()

    def test_conflict_http_503_cannot_look_up_user_or_create_session(self):
        request = APIRequestFactory().post(
            "/api/v1/auth/otp/verify/",
            {"mobile_number": MOBILE, "code": CODE},
            format="json",
        )
        with (
            patch(
                "apps.api.v1.otp_atomic_verify.atomic_verify_legacy_record",
                return_value=AtomicOtpOutcome("unavailable"),
            ),
            patch("apps.api.v1.auth_otp._otp_cache", return_value=object()),
            patch.object(
                ApiOtpVerifyAPIView, "_get_active_user_by_mobile",
            ) as user_lookup,
            patch("apps.api.v1.auth_views.login") as login,
        ):
            response = ApiOtpVerifyAPIView.as_view()(request)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data["error"]["code"], "otp_rate_limit_unavailable"
        )
        user_lookup.assert_not_called()
        login.assert_not_called()

    def test_default_path_never_calls_atomic_module(self):
        with (
            override_settings(
                LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_VERIFY=False,
                LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default",
            ),
            patch(
                "apps.api.v1.otp_atomic_verify.atomic_verify_legacy_record",
                side_effect=AssertionError("unexpected atomic call"),
            ),
            patch("apps.api.v1.auth_otp._cache_get", return_value=None),
        ):
            with self.assertRaises(auth_otp.ApiOtpNotFound):
                auth_otp.verify_api_otp_code(mobile_number=MOBILE, code=CODE)

    def test_nonredis_backend_refused_without_io(self):
        result = atomic_verify_legacy_record(
            cache_backend=object(),
            logical_key="test:record:app_login:09123456789",
            mobile_number=MOBILE,
            purpose="app_login",
            submitted_hash="a" * 40,
            now_ts=1050,
            ttl_seconds=120,
        )
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.record)

    def test_source_anchors_no_fallback_and_release_blocked(self):
        auth_source = inspect.getsource(auth_otp.verify_api_otp_code)
        module_source = inspect.getsource(atomic_verify_legacy_record)
        settings_source = (
            ROOT / "loomera/settings/base.py"
        ).read_text(encoding="utf-8")
        self.assertIn('LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_VERIFY', auth_source)
        self.assertIn('LOOMERA_API_AUTH_OTP_CACHE_ALIAS', auth_source)
        self.assertIn('if outcome.status == "verified"', auth_source)
        self.assertIn("raise ApiOtpRateLimitUnavailable", auth_source)
        self.assertIn("pipe.watch(physical)", module_source)
        self.assertIn("pipe.delete(physical)", module_source)
        self.assertIn("xx=True, keepttl=True", module_source)
        self.assertIn("except WatchError:", module_source)
        self.assertIn("default=False", settings_source)
        self.assertIn('LOOMERA_API_AUTH_OTP_FAIL_CLOSED', settings_source)
        self.assertNotIn("FLUSHDB", module_source)
        self.assertNotIn("FLUSHALL", module_source)

        matrix = json.loads((
            ROOT / "docs/globalization/PHASE7_35_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.35")
        self.assertTrue(matrix["atomic_verify_flag_disabled_by_default"])
        self.assertTrue(matrix["single_node_legacy_watch_verify_optin_wired"])
        for name in (
            "production_cutover_authorized",
            "multihost_fencing_proven",
            "otp_issue_rate_atomicity_proven",
            "session_cross_store_atomicity_proven",
            "sms_delivery_durable",
            "deployment_executed",
        ):
            self.assertFalse(matrix[name], name)
        self.assertEqual(matrix["release_gate"], "BLOCKED")
