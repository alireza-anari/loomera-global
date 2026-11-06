"""Phase 7.6: synthetic OTP drain and live web/API legacy challenge invariants.

No production cache, session backend, SMS delivery, or database required.
Mocks call existing view/helper functions, never a proposed auth bridge.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.accounts import views
from apps.api.v1 import auth_otp, auth_views
from loomera.globalization.otp_session_transition_audit import (
    review_legacy_otp_transition,
)
from loomera.globalization.phone_identity import PhoneIdentityInputError

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_6_OTP_SESSION_CONTRACT.json"
MOBILE = "09123456789"
E164 = "+989123456789"
PURPOSE = auth_otp.API_AUTH_OTP_PURPOSE_LOGIN


def roster():
    return [
        {"account_id": 101, "mobile_number": MOBILE, "is_active": True},
        {"account_id": 102, "mobile_number": "09123456780", "is_active": False},
    ]


def otp_metadata(*, namespace="api_app_login", account_id=101, mobile=MOBILE,
                 issued=1000, expiry=1120, attempts=0, max_attempts=3,
                 consumed=False, deleted=False, grant=None):
    return {
        "account_id": account_id,
        "mobile_number": mobile,
        "namespace": namespace,
        "issued_at": issued,
        "expires_at": expiry,
        "attempts": attempts,
        "max_attempts": max_attempts,
        "consumed": consumed,
        "cache_delete_confirmed": deleted,
        "password_reset_grant_until": grant,
    }


def review(challenges, *, now=1050, **overrides):
    kwargs = {
        "expected_accounts": 2,
        "expected_challenges": len(challenges),
        "now_ts": now,
        "cache_integrity_confirmed": True,
        "session_store_scope_confirmed": True,
    }
    kwargs.update(overrides)
    return review_legacy_otp_transition(roster(), challenges, **kwargs)


class FakeOtpCache:
    """Single-process deterministic fake, not a concurrency guarantee."""

    def __init__(self, *, fail_get=False, fail_set=False, fail_delete=False):
        self.data = {}
        self.calls = []
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.fail_delete = fail_delete

    def get(self, key, default=None):
        self.calls.append(("get", key))
        if self.fail_get:
            raise RuntimeError("synthetic cache unavailable")
        return self.data.get(key, default)

    def set(self, key, value, timeout=None):
        self.calls.append(("set", key))
        if self.fail_set:
            raise RuntimeError("synthetic cache unavailable")
        self.data[key] = value

    def delete(self, key):
        self.calls.append(("delete", key))
        if self.fail_delete:
            raise RuntimeError("synthetic cache unavailable")
        return self.data.pop(key, None) is not None


class Phase76OfflineDrainTests(SimpleTestCase):
    def test_clean_empty_snapshot_is_not_auth_cutover_authorization(self):
        r = review([])
        self.assertTrue(r["metadata_drain_structurally_clean"])
        self.assertEqual(r["stop_reasons"], [])
        self.assertEqual(r["challenges_examined"], 0)
        for flag in (
            "concurrent_verify_atomicity_proven",
            "web_plaintext_session_code_eliminated",
            "otp_replay_security_signoff_obtained",
            "canonical_login_cutover_authorized",
        ):
            self.assertFalse(r[flag])
        for key in ("database_reads", "cache_reads", "sessions_read", "writes_performed"):
            self.assertEqual(r[key], 0)

    def test_active_web_and_api_challenges_block_even_with_matching_e164(self):
        cases = [
            otp_metadata(),
            otp_metadata(namespace="web_signup", max_attempts=5),
            otp_metadata(namespace="web_password_reset", max_attempts=5),
        ]
        for item in cases:
            with self.subTest(namespace=item["namespace"]):
                result = review([item])
                self.assertFalse(result["metadata_drain_structurally_clean"])
                self.assertEqual(result["outstanding_unexpired_challenges"], 1)
                self.assertIn("outstanding_unexpired_legacy_challenge",
                              result["stop_reasons"])

    def test_alias_cannot_rebind_challenge_to_different_legacy_owner(self):
        for props in (
            {"account_id": 102},
            {"mobile": "09123456780"},
            {"account_id": 999},
        ):
            with self.subTest(props=props):
                result = review([otp_metadata(**props)])
                self.assertFalse(result["metadata_drain_structurally_clean"])
                self.assertTrue(
                    result["unknown_challenge_accounts"]
                    or result["mismatched_legacy_account_bindings"]
                )

    def test_inactive_account_challenge_is_a_hard_stop(self):
        result = review([otp_metadata(
            account_id=102, mobile="09123456780", consumed=True,
            deleted=True,
        )])
        self.assertIn("inactive_account_challenge_requires_owner_review",
                      result["stop_reasons"])

    def test_expired_not_consumed_requires_cleanup_even_without_live_ttl(self):
        result = review([otp_metadata(expiry=1030)], now=1050)
        self.assertEqual(result["expired_unconsumed_challenges"], 1)
        self.assertIn("expired_challenge_cleanup_unverified",
                      result["stop_reasons"])

    def test_consumed_api_otp_requires_deletion_evidence_and_not_replay_proof(self):
        unsafe = review([otp_metadata(consumed=True, deleted=False)])
        self.assertEqual(unsafe["api_consumed_without_deletion_proof"], 1)
        self.assertIn("api_challenge_deletion_unverified",
                      unsafe["stop_reasons"])
        clean = review([otp_metadata(consumed=True, deleted=True)])
        self.assertTrue(clean["metadata_drain_structurally_clean"])
        self.assertFalse(clean["concurrent_verify_atomicity_proven"])
        self.assertFalse(clean["canonical_login_cutover_authorized"])

    def test_password_reset_grant_stays_live_after_otp_consume(self):
        result = review([otp_metadata(
            namespace="web_password_reset", consumed=True,
            grant=1400,
        )])
        self.assertEqual(result["outstanding_password_reset_grants"], 1)
        self.assertIn("password_reset_session_grant_outstanding",
                      result["stop_reasons"])

    def test_untrusted_cache_or_session_scope_block_even_when_empty(self):
        for field in ("cache_integrity_confirmed", "session_store_scope_confirmed"):
            result = review([], **{field: False})
            self.assertFalse(result["metadata_drain_structurally_clean"])
            self.assertTrue(result["stop_reasons"])

    def test_future_issued_and_exhausted_active_are_blockers(self):
        result = review([otp_metadata(
            issued=1070, expiry=1200, attempts=3, max_attempts=3
        )])
        self.assertEqual(result["future_issued_challenges"], 1)
        self.assertEqual(result["exhausted_active_challenges"], 1)
        self.assertFalse(result["metadata_drain_structurally_clean"])

    def test_declared_snapshot_scope_must_match_source_and_challenges(self):
        mismatch = review([], expected_challenges=1)
        self.assertIn("declared_snapshot_scope_mismatch",
                      mismatch["stop_reasons"])
        mismatch = review([], expected_accounts=1)
        self.assertIn("declared_snapshot_scope_mismatch",
                      mismatch["stop_reasons"])

    def test_strict_metadata_never_accepts_secrets_hashes_or_ids_as_output(self):
        row = otp_metadata()
        for extra in ("active_code", "otp_hash", "email", "session_id", "ip_address"):
            with self.subTest(extra=extra):
                with self.assertRaises(PhoneIdentityInputError):
                    review([{**row, extra: "secret"}])
        report = review([otp_metadata(consumed=True, deleted=True)])
        serialized = json.dumps(report, ensure_ascii=False)
        for raw in (MOBILE, E164, '"account_id":', '"mobile_number":',
                    "123456", "session_id"):
            self.assertNotIn(raw, serialized)

    def test_bad_clock_types_invalid_attempts_purpose_and_legacy_rejected(self):
        for bad in (
            {"issued": 0}, {"expiry": 1000},
            {"attempts": -1}, {"max_attempts": 0},
            {"consumed": 1}, {"namespace": "shadow_api"},
            {"mobile": E164}, {"grant": 1300},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(PhoneIdentityInputError):
                    review([otp_metadata(**bad)])
        for param in (
            {"now_ts": True}, {"now_ts": -1},
            {"cache_integrity_confirmed": 1},
            {"session_store_scope_confirmed": "yes"},
            {"expected_challenges": True},
        ):
            with self.subTest(param=param):
                with self.assertRaises(PhoneIdentityInputError):
                    review_legacy_otp_transition(
                        roster(), [], expected_accounts=2,
                        expected_challenges=0, now_ts=1050, **param
                    ) if "now_ts" not in param and "expected_challenges" not in param else (
                        review_legacy_otp_transition(
                            roster(), [], expected_accounts=2,
                            expected_challenges=param.get("expected_challenges", 0),
                            now_ts=param.get("now_ts", 1050),
                            cache_integrity_confirmed=True,
                            session_store_scope_confirmed=True,
                        )
                    )

    def test_pure_audit_no_orm_cache_sessions_or_sms(self):
        from loomera.globalization import otp_session_transition_audit
        text = inspect.getsource(otp_session_transition_audit)
        for forbidden in ("django.db", ".objects.", "cache.get(", "cache.set(",
                          "send_otp_sms(", "session.get(", "request.session",
                          "login(request", "requests.get("):
            self.assertNotIn(forbidden, text)


@override_settings(
    LOOMERA_API_AUTH_OTP_FAIL_CLOSED=True,
    LOOMERA_API_AUTH_OTP_LENGTH=6,
    LOOMERA_API_AUTH_OTP_TTL_SECONDS=120,
    LOOMERA_API_AUTH_OTP_RESEND_SECONDS=60,
    LOOMERA_API_AUTH_MAX_VERIFY_ATTEMPTS=3,
)
class Phase76ExistingApiOtpTests(SimpleTestCase):
    def test_alias_request_and_verify_keep_single_legacy_namespace_and_replay_block(self):
        cache = FakeOtpCache()
        with (patch.object(auth_otp, "cache", cache),
              patch.object(auth_otp, "generate_numeric_otp", return_value="123456"),
              patch.object(auth_otp, "api_otp_now_ts", return_value=1000)):
            challenge = auth_otp.create_api_otp_request(mobile_number=E164)
            self.assertEqual(challenge.mobile_number, MOBILE)
            legacy_key = auth_otp.otp_record_cache_key(
                purpose=PURPOSE, mobile_number=MOBILE
            )
            self.assertIn(legacy_key, cache.data)
            self.assertNotIn("123456", json.dumps(cache.data))
            self.assertEqual(cache.data[legacy_key]["mobile_number"], MOBILE)
            result = auth_otp.verify_api_otp_code(
                mobile_number=MOBILE, code="123456"
            )
            self.assertEqual(result["mobile_number"], MOBILE)
            self.assertNotIn(legacy_key, cache.data)
            with self.assertRaises(auth_otp.ApiOtpNotFound):
                auth_otp.verify_api_otp_code(
                    mobile_number=E164, code="123456"
                )
            touched = [key for _, key in cache.calls]
            self.assertTrue(all("+989" not in key for key in touched))

    def test_other_mobile_or_wrong_purpose_cannot_use_existing_otp(self):
        cache = FakeOtpCache()
        with (patch.object(auth_otp, "cache", cache),
              patch.object(auth_otp, "generate_numeric_otp", return_value="123456"),
              patch.object(auth_otp, "api_otp_now_ts", return_value=1000)):
            auth_otp.create_api_otp_request(mobile_number=MOBILE)
            for number, purpose in (
                ("09123456780", PURPOSE),
                (MOBILE, "password_reset"),
            ):
                with self.subTest(number=number, purpose=purpose):
                    with self.assertRaises(auth_otp.ApiOtpNotFound):
                        auth_otp.verify_api_otp_code(
                            mobile_number=number, code="123456",
                            purpose=purpose,
                        )

    def test_wrong_attempts_preserve_counter_and_max_attempts_remove_record(self):
        cache = FakeOtpCache()
        with (patch.object(auth_otp, "cache", cache),
              patch.object(auth_otp, "generate_numeric_otp", return_value="123456"),
              patch.object(auth_otp, "api_otp_now_ts", return_value=1000)):
            auth_otp.create_api_otp_request(mobile_number=MOBILE)
            for remaining in (2, 1):
                with self.assertRaises(auth_otp.ApiOtpInvalidCode) as exc:
                    auth_otp.verify_api_otp_code(
                        mobile_number=MOBILE, code="000000"
                    )
                self.assertEqual(exc.exception.attempts_remaining, remaining)
            with self.assertRaises(auth_otp.ApiOtpMaxAttemptsExceeded):
                auth_otp.verify_api_otp_code(
                    mobile_number=MOBILE, code="000000"
                )
            self.assertIsNone(auth_otp.load_api_otp_record(mobile_number=MOBILE))

    def test_expired_old_challenge_not_usable_via_new_candidate(self):
        cache = FakeOtpCache()
        with (patch.object(auth_otp, "cache", cache),
              patch.object(auth_otp, "generate_numeric_otp", return_value="123456"),
              patch.object(auth_otp, "api_otp_now_ts", return_value=1000)) as time_mock:
            auth_otp.create_api_otp_request(mobile_number=MOBILE)
            time_mock.return_value = 1121
            with self.assertRaises(auth_otp.ApiOtpExpired):
                auth_otp.verify_api_otp_code(
                    mobile_number=E164, code="123456"
                )
            self.assertIsNone(auth_otp.load_api_otp_record(mobile_number=MOBILE))

    def test_successful_code_cannot_authenticate_when_cache_delete_fails(self):
        cache = FakeOtpCache(fail_delete=True)
        with (patch.object(auth_otp, "cache", cache),
              patch.object(auth_otp, "generate_numeric_otp", return_value="123456"),
              patch.object(auth_otp, "api_otp_now_ts", return_value=1000)):
            auth_otp.create_api_otp_request(mobile_number=MOBILE)
            with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                auth_otp.verify_api_otp_code(
                    mobile_number=E164, code="123456"
                )

    def test_cache_get_and_set_fail_closed_without_legacy_key_recovery_guess(self):
        for flag in ("fail_get", "fail_set"):
            fake = FakeOtpCache(**{flag: True})
            with (patch.object(auth_otp, "cache", fake),
                  patch.object(auth_otp, "generate_numeric_otp", return_value="123456"),
                  patch.object(auth_otp, "api_otp_now_ts", return_value=1000)):
                with self.subTest(flag=flag):
                    with self.assertRaises(auth_otp.ApiOtpRateLimitUnavailable):
                        auth_otp.create_api_otp_request(mobile_number=E164)

    def test_resend_cooldown_applies_to_legacy_and_plus98_alias(self):
        cache = FakeOtpCache()
        with (patch.object(auth_otp, "cache", cache),
              patch.object(auth_otp, "generate_numeric_otp", return_value="123456"),
              patch.object(auth_otp, "api_otp_now_ts", return_value=1000)):
            auth_otp.create_api_otp_request(mobile_number=MOBILE)
            with self.assertRaises(auth_otp.ApiOtpRateLimited) as exc:
                auth_otp.create_api_otp_request(mobile_number=E164)
            self.assertEqual(exc.exception.scope, "mobile_resend")


class Phase76ExistingWebSessionTests(SimpleTestCase):
    def _request(self, session, code):
        request = RequestFactory().post("/accounts/verify/", {"active_code": code})
        request.session = {views.USER_SESSION_KEY: session}
        request.user = SimpleNamespace(is_authenticated=False)
        return request

    def test_password_reset_session_retains_legacy_lookup_and_no_login(self):
        with patch.object(views, "_now_ts", return_value=1000):
            session = views._create_verification_session(
                mobile_number=E164, code="12345", remember_password=True
            )
        request = self._request(session, "12345")
        fake_form = SimpleNamespace(
            is_valid=lambda: True, cleaned_data={"active_code": "12345"}
        )
        with (patch.object(views, "_now_ts", return_value=1000),
              patch.object(views, "VerifyRegisterForm", return_value=fake_form),
              patch.object(views.CustomUser.objects, "get",
                           return_value=SimpleNamespace(pk=101)) as get_user,
              patch.object(views, "login") as login,
              patch.object(views, "redirect", return_value=HttpResponse("ok"))):
            response = views.VerifyRegisterView().post(request)
        self.assertEqual(response.status_code, 200)
        get_user.assert_called_once_with(mobile_number=MOBILE)
        login.assert_not_called()
        state = request.session[views.USER_SESSION_KEY]
        self.assertTrue(state["otp_verified"])
        self.assertGreater(state["password_reset_authorized_until"], 1000)

    def test_expired_web_session_removed_without_auth_lookup_or_login(self):
        with patch.object(views, "_now_ts", return_value=1000):
            session = views._create_verification_session(
                mobile_number=MOBILE, code="12345", signup_kind="customer"
            )
        request = self._request(session, "12345")
        with (patch.object(views, "_now_ts", return_value=2000),
              patch.object(views.messages, "error"),
              patch.object(views.CustomUser.objects, "get") as get_user,
              patch.object(views, "login") as login,
              patch.object(views, "redirect", return_value=HttpResponse("expired"))):
            response = views.VerifyRegisterView().post(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(views.USER_SESSION_KEY, request.session)
        get_user.assert_not_called()
        login.assert_not_called()

    def test_wrong_web_otp_does_not_lookup_or_activate_account(self):
        with patch.object(views, "_now_ts", return_value=1000):
            session = views._create_verification_session(
                mobile_number=MOBILE, code="12345", signup_kind="customer"
            )
        request = self._request(session, "00000")
        fake_form = SimpleNamespace(
            is_valid=lambda: True, cleaned_data={"active_code": "00000"}
        )
        with (patch.object(views, "_now_ts", return_value=1000),
              patch.object(views, "VerifyRegisterForm", return_value=fake_form),
              patch.object(views.CustomUser.objects, "get") as get_user,
              patch.object(views.messages, "error"),
              patch.object(views, "render", return_value=HttpResponse("invalid")),
              patch.object(views, "login") as login):
            response = views.VerifyRegisterView().post(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.session[views.USER_SESSION_KEY]["otp_attempts"], 1)
        get_user.assert_not_called()
        login.assert_not_called()

    def test_web_otp_cooldown_is_purpose_scoped_not_e164_shadow_key(self):
        key_a = views._otp_cooldown_cache_key(
            purpose=views.OTP_PURPOSE_SIGNUP, mobile_number=MOBILE
        )
        key_b = views._otp_cooldown_cache_key(
            purpose=views.OTP_PURPOSE_SIGNUP, mobile_number=E164
        )
        key_reset = views._otp_cooldown_cache_key(
            purpose=views.OTP_PURPOSE_PASSWORD_RESET, mobile_number=MOBILE
        )
        self.assertEqual(key_a, key_b)
        self.assertNotEqual(key_a, key_reset)
        self.assertNotIn(E164, key_a)


class Phase76ContractTests(SimpleTestCase):
    def test_manifest_declares_all_migration_release_gates_blocked(self):
        m = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(m["phase"], "7.6")
        self.assertFalse(m["authorization"]["canonical_login_cutover"])
        self.assertFalse(m["authorization"]["dual_cache_key_bridge"])
        self.assertFalse(m["authorization"]["new_sms_delivery_provider"])
        self.assertFalse(m["evidence"]["atomic_multiworker_api_challenge_consume"])
        self.assertFalse(m["evidence"]["web_plaintext_session_code_migrated"])
        self.assertFalse(m["evidence"]["old_session_ttl_coverage_proven"])
        for item in m["source_anchors"]:
            self.assertIn(
                item["anchor"],
                (ROOT / item["path"]).read_text(encoding="utf-8"),
            )
