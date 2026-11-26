"""Phase 7.37: default-off bounded duplicate suppression on OTP issuance."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from apps.api.v1 import auth_otp
from apps.api.v1.auth_views import ApiOtpRequestAPIView
from apps.api.v1.otp_atomic_issue import AtomicOtpIssueOutcome

MOBILE = "09123456789"
OP = "c7653cb8-32c1-4e80-aacd-a8b7d4364f52"
PEER = "192.0.2.17"


@override_settings(
    LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_VERIFY=True,
    LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_ISSUE=True,
    LOOMERA_API_AUTH_OTP_ISSUE_REPLAY_FENCE=True,
    LOOMERA_API_AUTH_OTP_CACHE_ALIAS="otp",
    LOOMERA_API_AUTH_OTP_FAIL_CLOSED=True,
)
class Phase737ReplayFenceTests(SimpleTestCase):
    def peer(self, operation=OP, address=PEER, forwarded="203.0.113.99"):
        return SimpleNamespace(META={
            "HTTP_IDEMPOTENCY_KEY": operation,
            "REMOTE_ADDR": address,
            "HTTP_X_FORWARDED_FOR": forwarded,
        })

    def operation(self, request=None, mobile=MOBILE):
        return auth_otp._otp_issue_operation(
            self.peer() if request is None else request,
            purpose="app_login", mobile_number=mobile,
            peer=PEER if request is None else request.META["REMOTE_ADDR"],
        )

    def test_operation_key_and_binding_are_opaque_stable_and_bound(self):
        key, digest = self.operation()
        self.assertEqual((key, digest), self.operation())
        self.assertEqual(len(digest), 64)
        self.assertRegex(key, r":issue-operation:v1:[0-9a-f]{64}$")
        for secret in (OP, MOBILE, PEER):
            self.assertNotIn(secret, key)
            self.assertNotIn(secret, digest)
        self.assertEqual(key, self.operation(mobile="09123456780")[0])
        self.assertNotEqual(digest, self.operation(mobile="09123456780")[1])
        self.assertNotEqual(digest, self.operation(self.peer(address="192.0.2.18"))[1])
        self.assertEqual((key, digest), self.operation(self.peer(forwarded="198.51.100.99")))

    def test_missing_malformed_or_oversized_id_rejected_before_cache(self):
        for value in (None, "", "abc", OP.upper(), "0" * 10000):
            with self.subTest(value_type=type(value).__name__):
                with patch("apps.api.v1.auth_otp._otp_cache") as cache:
                    with self.assertRaises(auth_otp.ApiOtpIdempotencyInvalid):
                        auth_otp.create_api_otp_request(
                            mobile_number=MOBILE, request=self.peer(value)
                        )
                cache.assert_not_called()

    @override_settings(LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_ISSUE=False)
    def test_replay_fence_without_atomic_issuer_rejected(self):
        with patch("apps.api.v1.auth_otp._otp_cache") as cache:
            with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                auth_otp.create_api_otp_request(mobile_number=MOBILE, request=self.peer())
        cache.assert_not_called()

    def test_actual_issue_dispatch_binds_same_operation_across_retries(self):
        with (
            patch("apps.api.v1.auth_otp._otp_cache", return_value=object()),
            patch("apps.api.v1.auth_otp.generate_numeric_otp", side_effect=["246810", "975310"]),
            patch("apps.api.v1.otp_atomic_issue.atomic_issue_legacy_record",
                  side_effect=[AtomicOtpIssueOutcome("issued"),
                               AtomicOtpIssueOutcome("operation_recorded")]) as issuer,
        ):
            result = auth_otp.create_api_otp_request(mobile_number=MOBILE, request=self.peer())
            with self.assertRaises(auth_otp.ApiOtpIdempotencyConflict):
                auth_otp.create_api_otp_request(mobile_number=MOBILE, request=self.peer())
        first, second = (call.kwargs for call in issuer.call_args_list)
        self.assertEqual(first["operation"], second["operation"])
        self.assertNotEqual(first["record"]["code_hash"], second["record"]["code_hash"])
        self.assertFalse(result.sent)

    def api(self, outcome, operation=OP):
        kwargs = {"REMOTE_ADDR": PEER}
        if operation is not None:
            kwargs["HTTP_IDEMPOTENCY_KEY"] = operation
        request = APIRequestFactory().post(
            "/api/v1/auth/otp/request/", {"mobile_number": MOBILE}, format="json", **kwargs
        )
        with (
            patch("apps.api.v1.auth_otp._otp_cache", return_value=object()),
            patch("apps.api.v1.otp_atomic_issue.atomic_issue_legacy_record",
                  return_value=AtomicOtpIssueOutcome(outcome)) as issuer,
        ):
            response = ApiOtpRequestAPIView.as_view()(request)
        return response, issuer

    def test_replay_and_binding_mismatch_have_same_public_conflict(self):
        for outcome in ("operation_recorded", "operation_conflict"):
            response, issuer = self.api(outcome)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["error"]["code"], "otp_request_replay_blocked")
            self.assertNotIn(MOBILE, str(response.data))
            self.assertNotIn(OP, str(response.data))
            self.assertNotIn("accepted", str(response.data))
            issuer.assert_called_once()

    def test_missing_id_is_400_without_issuer(self):
        response, issuer = self.api("issued", operation=None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "otp_idempotency_key_invalid")
        issuer.assert_not_called()

    def test_ambiguous_commit_still_returns_503(self):
        response, _ = self.api("unavailable")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"]["code"], "otp_rate_limit_unavailable")

    @override_settings(LOOMERA_API_AUTH_OTP_ISSUE_REPLAY_FENCE=False)
    def test_default_off_has_no_operation_parameter_and_old_response(self):
        response, issuer = self.api("issued", operation=None)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["accepted"])
        self.assertNotIn("operation", issuer.call_args.kwargs)
