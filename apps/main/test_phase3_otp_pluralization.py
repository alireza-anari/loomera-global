"""Phase 3 slice 3.9: OTP remaining-attempt plural and counter invariants."""

from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import translation

from apps.accounts.views import (
    USER_SESSION_KEY,
    VerifyRegisterView,
    _format_remaining_otp_attempts,
)


SINGULAR = "کد وارد شده اشتباه است. %(count)d تلاش دیگر باقی مانده است."
PLURAL = "کد وارد شده اشتباه است. %(count)d تلاش دیگر باقی مانده‌اند."


class OtpRemainingAttemptsPluralTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def tearDown(self):
        translation.deactivate_all()

    def test_persian_exact_historical_copy_for_all_positive_counts(self):
        for number in (1, 2, 3, 5, 11, 101):
            with self.subTest(number=number), translation.override("fa"):
                self.assertEqual(
                    _format_remaining_otp_attempts(number),
                    f"کد وارد شده اشتباه است. {number} تلاش دیگر باقی مانده است.",
                )

    def test_english_singular_and_plural_actual_gettext_runtime(self):
        for number, expected in (
            (1, "The code is incorrect. 1 attempt remains."),
            (2, "The code is incorrect. 2 attempts remain."),
            (3, "The code is incorrect. 3 attempts remain."),
            (11, "The code is incorrect. 11 attempts remain."),
        ):
            with self.subTest(number=number), translation.override("en"):
                self.assertEqual(_format_remaining_otp_attempts(number), expected)

    def test_arabic_six_plural_categories_from_compiled_catalog(self):
        expected = (
            (0, "رمز التحقق غير صحيح. لم تتبق أي محاولات."),
            (1, "رمز التحقق غير صحيح. تبقت محاولة واحدة."),
            (2, "رمز التحقق غير صحيح. تبقت محاولتان."),
            (3, "رمز التحقق غير صحيح. تبقت 3 محاولات."),
            (7, "رمز التحقق غير صحيح. تبقت 7 محاولات."),
            (11, "رمز التحقق غير صحيح. تبقت 11 محاولة."),
            (99, "رمز التحقق غير صحيح. تبقت 99 محاولة."),
            (101, "رمز التحقق غير صحيح. تبقت 101 محاولة."),
        )
        for number, translated in expected:
            with self.subTest(number=number), translation.override("ar"):
                self.assertEqual(_format_remaining_otp_attempts(number), translated)

    def test_request_language_isolation_between_repeated_lookups(self):
        for lang, message in (
            ("en", "The code is incorrect. 2 attempts remain."),
            ("ar", "رمز التحقق غير صحيح. تبقت محاولتان."),
            ("fa", "کد وارد شده اشتباه است. 2 تلاش دیگر باقی مانده است."),
            ("en", "The code is incorrect. 2 attempts remain."),
        ):
            with translation.override(lang):
                self.assertEqual(_format_remaining_otp_attempts(2), message)

    def test_plural_sources_have_correct_number_of_forms_and_compiled_catalog(self):
        for lang, count in (("en", 2), ("fa", 2), ("ar", 6)):
            with self.subTest(lang=lang):
                folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
                po = (folder / "django.po").read_text(encoding="utf-8")
                self.assertTrue((folder / "django.mo").is_file())
                self.assertIn('msgid "' + SINGULAR + '"', po)
                self.assertIn('msgid_plural "' + PLURAL + '"', po)
                self.assertIn('#, python-format', po)
                for index in range(count):
                    self.assertIn("msgstr[" + str(index) + "] ", po)
                if lang == "ar":
                    self.assertIn("Plural-Forms: nplurals=6;", po)

    def test_otp_view_still_increments_and_locks_at_exact_max(self):
        # Execute the actual post handler with a session and a valid OTP form.
        # Only presentation response and flash transport are stubbed.
        request = RequestFactory().post("/accounts/verify/", {"active_code": "000000"})
        request.user = AnonymousUser()
        with override_settings(
            SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies"
        ):
            SessionMiddleware(lambda r: HttpResponse()).process_request(request)
            request.session[USER_SESSION_KEY] = {
                "active_code": "111111",
                "otp_attempts": 0,
                "otp_max_attempts": 3,
                "mobile_number": "09123456789",
                "signup_kind": "customer",
            }
            with (
                translation.override("en"),
                patch("apps.accounts.views.messages.error") as flash,
                patch("apps.accounts.views.render", return_value=HttpResponse("form")) as render,
                patch("apps.accounts.views._verification_back_url", return_value="/back/"),
            ):
                for attempts, remaining in ((1, 2), (2, 1)):
                    response = VerifyRegisterView.as_view()(request)
                    self.assertEqual(response.status_code, 200)
                    state = request.session[USER_SESSION_KEY]
                    self.assertEqual(state["otp_attempts"], attempts)
                    self.assertEqual(state["otp_max_attempts"], 3)
                    self.assertEqual(render.call_count, attempts)
                    message = flash.call_args.args[1]
                    self.assertEqual(
                        message,
                        f"The code is incorrect. {remaining} "
                        + ("attempt remains." if remaining == 1 else "attempts remain."),
                    )
                # Third failure must lock out, clear session and redirect; the
                # localized counter is not shown once remaining reaches zero.
                response = VerifyRegisterView.as_view()(request)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], "/back/")
                self.assertNotIn(USER_SESSION_KEY, request.session)
                self.assertEqual(render.call_count, 2)
                self.assertEqual(
                    flash.call_args.args[1],
                    "Too many incorrect verification codes. Request a new code.",
                )

    def test_preexpired_attempt_budget_does_not_render_counter(self):
        request = RequestFactory().post("/accounts/verify/", {"active_code": "000000"})
        request.user = AnonymousUser()
        with override_settings(
            SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies"
        ):
            SessionMiddleware(lambda r: HttpResponse()).process_request(request)
            request.session[USER_SESSION_KEY] = {
                "active_code": "111111",
                "otp_attempts": 3,
                "otp_max_attempts": 3,
                "mobile_number": "09123456789",
            }
            with (
                translation.override("ar"),
                patch("apps.accounts.views.messages.error") as flash,
                patch("apps.accounts.views._verification_back_url", return_value="/back/"),
            ):
                response = VerifyRegisterView.as_view()(request)
                self.assertEqual(response.status_code, 302)
                self.assertNotIn(USER_SESSION_KEY, request.session)
                self.assertEqual(
                    flash.call_args.args[1],
                    "لقد استنفدت جميع المحاولات المسموح بها. اطلب رمزًا جديدًا.",
                )

    def test_attempt_math_and_security_branches_are_unmodified(self):
        src = self.source("apps/accounts/views.py")
        start = src.index("class VerifyRegisterView(View):")
        end = src.index("class DismissMessagingWelcomePromptView(", start)
        block = src[start:end]
        self.assertIn('user_session["otp_attempts"] = (', block)
        self.assertIn('int(user_session.get("otp_attempts", 0) or 0) + 1', block)
        self.assertIn("remaining_attempts = max(", block)
        self.assertIn("if remaining_attempts <= 0:", block)
        self.assertIn("if int(user_session.get(\"otp_attempts\", 0) or 0) >= int(", block)
        self.assertIn("request.session.pop(USER_SESSION_KEY, None)", block)
        self.assertIn("_password_reset_session_ttl_seconds()", block)
        self.assertIn("_format_remaining_otp_attempts(remaining_attempts)", block)
        self.assertNotIn("f\"کد وارد شده اشتباه است.", block)
        self.assertIn("utils.create_state_token()", block)
        self.assertIn("login(request, user)", block)

    def test_unchanged_fa_defaults_and_security_limits(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
