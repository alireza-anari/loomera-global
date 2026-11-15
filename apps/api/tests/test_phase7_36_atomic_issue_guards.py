"""Phase 7.36 offline and HTTP guards for default-off atomic OTP issuance.

No Redis, database, SMS provider, real identity or session IO occurs.
Physical WATCH/CAS is separately verified on disposable Redis in CI.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from apps.api.v1 import auth_otp
from apps.api.v1.auth_views import ApiOtpRequestAPIView
from apps.api.v1.otp_atomic_issue import (
    AtomicOtpIssueOutcome,
    atomic_issue_legacy_record,
)

ROOT = Path(__file__).resolve().parents[3]
MOBILE = "09123456789"
PEER_IP = "192.0.2.17"
SPOOFED_IP = "203.0.113.99"


@override_settings(
    LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_ISSUE=True,
    LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_VERIFY=True,
    LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
    LOOMERA_API_AUTH_OTP_FAIL_CLOSED=True,
    LOOMERA_API_AUTH_OTP_LENGTH=6,
    LOOMERA_API_AUTH_OTP_TTL_SECONDS=120,
    LOOMERA_API_AUTH_OTP_RESEND_SECONDS=60,
    LOOMERA_API_AUTH_OTP_REQUEST_RATE_PER_MOBILE_HOUR=3,
    LOOMERA_API_AUTH_OTP_REQUEST_RATE_PER_IP_HOUR=4,
)
class Phase736AtomicIssuerOfflineGuards(SimpleTestCase):
    def request(self, **extra):
        return SimpleNamespace(
            META={
                "REMOTE_ADDR": PEER_IP,
                "HTTP_X_FORWARDED_FOR": SPOOFED_IP,
                **extra,
            }
        )

    def call_issuer(self, status="issued", retry_after=0, request=None):
        with (
            patch("apps.api.v1.auth_otp.api_otp_now_ts", return_value=3605),
            patch("apps.api.v1.auth_otp.generate_numeric_otp", return_value="123456"),
            patch("apps.api.v1.auth_otp._otp_cache", return_value=object()),
            patch(
                "apps.api.v1.otp_atomic_issue.atomic_issue_legacy_record",
                return_value=AtomicOtpIssueOutcome(status, retry_after),
            ) as issued,
        ):
            result = auth_otp.create_api_otp_request(
                mobile_number=MOBILE,
                request=self.request() if request is None else request,
            )
        return result, issued

    def test_accepted_issue_uses_exact_four_legacy_keys_and_single_hour(self):
        result, call = self.call_issuer()
        self.assertEqual(result.mobile_number, MOBILE)
        self.assertEqual(result.mode, "simulated")
        self.assertIs(result.sent, False)
        params = call.call_args.kwargs
        expected = (
            auth_otp.otp_record_cache_key(
                purpose="app_login", mobile_number=MOBILE
            ),
            auth_otp.otp_resend_cache_key(
                purpose="app_login", mobile_number=MOBILE
            ),
            auth_otp.otp_hour_rate_cache_key(
                scope="mobile", value=f"app_login:{MOBILE}", now_ts=3605
            ),
            auth_otp.otp_hour_rate_cache_key(
                scope="ip", value=f"app_login:{PEER_IP}", now_ts=3605
            ),
        )
        self.assertEqual(params["logical_keys"], expected)
        self.assertNotIn(SPOOFED_IP, repr(params["logical_keys"]))
        self.assertEqual(params["now_ts"], 3605)
        self.assertEqual(params["record_ttl_seconds"], 120)
        self.assertEqual(params["resend_ttl_seconds"], 60)
        self.assertEqual(params["mobile_hour_limit"], 3)
        self.assertEqual(params["ip_hour_limit"], 4)
        record = params["record"]
        self.assertEqual(record["purpose"], "app_login")
        self.assertEqual(record["mobile_number"], MOBILE)
        self.assertEqual(record["created_at"], 3605)
        self.assertEqual(record["expires_at"], 3725)
        self.assertEqual(record["attempts"], 0)
        self.assertFalse(record["verified"])
        self.assertEqual(
            record["code_hash"],
            auth_otp.hash_otp_code(
                mobile_number=MOBILE, purpose="app_login", code="123456"
            ),
        )
        self.assertNotIn("code", record)
        self.assertNotIn("123456", repr(result))

    def test_four_limit_outcomes_are_safe_429_with_expected_scopes(self):
        mapping = (
            ("challenge_pending", "mobile_resend"),
            ("resend_limited", "mobile_resend"),
            ("mobile_limited", "mobile"),
            ("ip_limited", "ip"),
        )
        for status, scope in mapping:
            with self.subTest(status=status):
                with self.assertRaises(auth_otp.ApiOtpRateLimited) as thrown:
                    self.call_issuer(status=status, retry_after=27)
                self.assertEqual(thrown.exception.scope, scope)
                self.assertEqual(thrown.exception.retry_after, 27)

    def test_conflicts_invalid_storage_and_unknown_ack_fail_closed(self):
        for status in ("unavailable", "watch_conflict", "invalid_wire"):
            with self.subTest(status=status):
                with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                    self.call_issuer(status=status)

    @override_settings(LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_VERIFY=False)
    def test_issue_flag_without_atomic_verify_refused_before_cache_io(self):
        with patch("apps.api.v1.auth_otp._otp_cache") as backend:
            with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                auth_otp.create_api_otp_request(
                    mobile_number=MOBILE, request=self.request()
                )
        backend.assert_not_called()

    @override_settings(LOOMERA_API_AUTH_OTP_CACHE_ALIAS="default")
    def test_issue_flag_with_shared_redis_refused_before_cache_io(self):
        with patch("apps.api.v1.auth_otp._otp_cache") as backend:
            with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                auth_otp.create_api_otp_request(
                    mobile_number=MOBILE, request=self.request()
                )
        backend.assert_not_called()

    @override_settings(LOOMERA_API_AUTH_OTP_FAIL_CLOSED=False)
    def test_issue_flag_with_failopen_refused_before_cache_io(self):
        with patch("apps.api.v1.auth_otp._otp_cache") as backend:
            with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                auth_otp.create_api_otp_request(
                    mobile_number=MOBILE, request=self.request()
                )
        backend.assert_not_called()

    def test_missing_peer_ip_refused_rather_than_trusting_forwarded_header(self):
        request = self.request(REMOTE_ADDR="")
        with patch("apps.api.v1.auth_otp._otp_cache") as backend:
            with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                auth_otp.create_api_otp_request(
                    mobile_number=MOBILE, request=request
                )
        backend.assert_not_called()

    def test_unknown_transaction_http_503_without_sensitive_output(self):
        req = APIRequestFactory().post(
            "/api/v1/auth/otp/request/",
            {"mobile_number": MOBILE},
            format="json",
            REMOTE_ADDR=PEER_IP,
            HTTP_X_FORWARDED_FOR=SPOOFED_IP,
        )
        with (
            patch("apps.api.v1.auth_otp._otp_cache", return_value=object()),
            patch(
                "apps.api.v1.otp_atomic_issue.atomic_issue_legacy_record",
                return_value=AtomicOtpIssueOutcome("unavailable"),
            ),
        ):
            response = ApiOtpRequestAPIView.as_view()(req)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data["error"]["code"], "otp_rate_limit_unavailable"
        )
        self.assertNotIn(MOBILE, str(response.data))
        self.assertNotIn(SPOOFED_IP, str(response.data))

    def test_cooldown_http_429_does_not_expose_mobile_or_hash(self):
        req = APIRequestFactory().post(
            "/api/v1/auth/otp/request/",
            {"mobile_number": MOBILE},
            format="json",
            REMOTE_ADDR=PEER_IP,
        )
        with (
            patch("apps.api.v1.auth_otp._otp_cache", return_value=object()),
            patch(
                "apps.api.v1.otp_atomic_issue.atomic_issue_legacy_record",
                return_value=AtomicOtpIssueOutcome("resend_limited", 17),
            ),
        ):
            response = ApiOtpRequestAPIView.as_view()(req)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["error"]["details"]["scope"], "mobile_resend")
        self.assertEqual(
            response.data["error"]["details"]["retry_after_seconds"], 17
        )
        self.assertNotIn(MOBILE, str(response.data))

    @override_settings(LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_ISSUE=False)
    def test_default_issue_path_does_not_call_atomic_issuer(self):
        with (
            patch(
                "apps.api.v1.otp_atomic_issue.atomic_issue_legacy_record",
                side_effect=AssertionError("atomic issuer must not be called"),
            ),
            patch("apps.api.v1.auth_otp._check_resend_cooldown"),
            patch("apps.api.v1.auth_otp._increment_hour_rate"),
            patch("apps.api.v1.auth_otp._cache_set") as legacy_set,
        ):
            result = auth_otp.create_api_otp_request(
                mobile_number=MOBILE, request=self.request()
            )
        self.assertFalse(result.sent)
        self.assertEqual(legacy_set.call_count, 2)

    def test_nonredis_backend_never_makes_network_call(self):
        outcome = atomic_issue_legacy_record(
            cache_backend=object(),
            logical_keys=("a", "b", "c", "d"),
            record={
                "purpose": "app_login",
                "mobile_number": MOBILE,
                "code_hash": "a" * 40,
                "created_at": 1000,
                "expires_at": 1120,
                "attempts": 0,
                "max_attempts": 5,
                "verified": False,
            },
            now_ts=1000,
            record_ttl_seconds=120,
            resend_ttl_seconds=60,
            mobile_hour_limit=2,
            ip_hour_limit=3,
        )
        self.assertEqual(outcome.status, "unavailable")

    def test_released_contract_and_source_guards(self):
        module = inspect.getsource(atomic_issue_legacy_record)
        caller = inspect.getsource(auth_otp.create_api_otp_request)
        settings_text = (
            ROOT / "loomera/settings/base.py"
        ).read_text(encoding="utf-8")
        self.assertIn("pipe.watch(*physical)", module)
        self.assertIn("xx=True, keepttl=True", module)
        self.assertIn("pipe.execute()", module)
        self.assertIn("except WatchError:", module)
        self.assertIn("LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_ISSUE", caller)
        self.assertIn("LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_VERIFY", caller)
        self.assertIn('get("REMOTE_ADDR")', caller)
        self.assertIn('default=False', settings_text)
        self.assertNotIn("except Exception", module)
        self.assertNotIn("FLUSHDB", module)
        self.assertNotIn("FLUSHALL", module)
        matrix = json.loads((
            ROOT / "docs/globalization/PHASE7_36_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.36")
        self.assertTrue(matrix["atomic_issue_flag_disabled_by_default"])
        self.assertTrue(matrix["single_node_four_key_watch_issue_optin_wired"])
        for field in (
            "production_cutover_authorized",
            "multihost_fencing_proven",
            "delivery_outbox_implemented_live",
            "request_idempotency_live",
            "trusted_proxy_ip_chain_verified",
            "deployment_executed",
        ):
            self.assertFalse(matrix[field], field)
        self.assertEqual(matrix["release_gate"], "BLOCKED")
