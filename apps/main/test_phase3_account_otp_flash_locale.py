"""Phase 3.18: tightly reviewed, tone-scoped account/OTP flash translations.

Only existing compiled fa/en/ar literals qualify, never arbitrary provider,
business or user data. This suite uses real Django flash rendering, no DB.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation
from django.utils.safestring import mark_safe

from apps.main.templatetags.ui_message_extras import (
    _TRUSTED_DOMAIN_FLASH_MSGIDS,
    clean_ui_message,
)
from apps.main.ui_feedback import DEFAULT_ERROR_MESSAGE
from loomera.globalization.interactive_messages import MESSAGE_IDS


ERROR_MSGIDS = (
    "شماره موبایل یا رمز عبور اشتباه است.",
    "کد تایید منقضی شده است. لطفاً دوباره درخواست کد بدهید.",
    "جلسه بازیابی یا ثبت‌نام منقضی شده است.",
    "تعداد تلاش‌های مجاز تمام شده است. لطفاً دوباره درخواست کد بدهید.",
    "کد تایید بیش از حد اشتباه وارد شد. لطفاً دوباره درخواست کد بدهید.",
    "کاربر مرتبط با این کد پیدا نشد.",
    "اطلاعات وارد شده اشتباه است.",
)
INFO_MSGID = "ابتدا شماره موبایل و کد دریافتی را ثبت کنید."


class AuthOtpFlashLocaleTests(SimpleTestCase):
    def tearDown(self):
        translation.deactivate_all()

    @staticmethod
    def render(level, message):
        return render_to_string(
            "partials/messages.html", {"messages": [Message(level, message)]}
        )

    def test_tone_scoped_domain_allowlist_is_exactly_reviewed_eight_literals(self):
        self.assertEqual(set(_TRUSTED_DOMAIN_FLASH_MSGIDS), {"error", "info"})
        self.assertEqual(_TRUSTED_DOMAIN_FLASH_MSGIDS["error"], ERROR_MSGIDS)
        self.assertEqual(_TRUSTED_DOMAIN_FLASH_MSGIDS["info"], (INFO_MSGID,))
        self.assertNotIn("success", _TRUSTED_DOMAIN_FLASH_MSGIDS)
        self.assertNotIn("warning", _TRUSTED_DOMAIN_FLASH_MSGIDS)
        for item in ERROR_MSGIDS + (INFO_MSGID,):
            self.assertNotIn("%(", item)
            self.assertNotIn("{", item)
            self.assertNotIn("<", item)

    def test_exact_domain_error_messages_render_from_three_catalog_origins(self):
        for msgid in ERROR_MSGIDS:
            for origin in ("fa", "en", "ar"):
                with translation.override(origin):
                    original = translation.gettext(msgid)
                for requested_language in ("en", "ar"):
                    with self.subTest(msgid=msgid, origin=origin, lang=requested_language):
                        with translation.override(requested_language):
                            expected = translation.gettext(msgid)
                            self.assertEqual(clean_ui_message(original, "danger"), expected)
                            html = self.render(constants.ERROR, original)
                            self.assertIn(expected, html)
                            self.assertIn('role="alert"', html)
                            self.assertNotIn(
                                translation.gettext(MESSAGE_IDS["feedback.default.error"]),
                                html,
                            )

    def test_exact_info_message_is_translated_from_all_compiled_locales(self):
        for origin in ("fa", "en", "ar"):
            with translation.override(origin):
                original = translation.gettext(INFO_MSGID)
            for language in ("en", "ar"):
                with self.subTest(origin=origin, language=language):
                    with translation.override(language):
                        expected = translation.gettext(INFO_MSGID)
                        self.assertEqual(clean_ui_message(original, "info"), expected)
                        self.assertIn(expected, self.render(constants.INFO, original))

    def test_domain_messages_are_not_promoted_across_flash_tones(self):
        for language in ("en", "ar"):
            with translation.override(language):
                for msgid in ERROR_MSGIDS:
                    for tag in ("warning", "success", "info", ""):
                        with self.subTest(lang=language, tag=tag, msgid=msgid):
                            tone = tag or "info"
                            self.assertEqual(
                                clean_ui_message(msgid, tag),
                                translation.gettext(MESSAGE_IDS["feedback.default." + tone]),
                            )
                for tag in ("error", "danger", "warning", "success"):
                    tone = "error" if tag in ("error", "danger") else tag
                    with self.subTest(lang=language, tag=tag, msgid=INFO_MSGID):
                        self.assertEqual(
                            clean_ui_message(INFO_MSGID, tag),
                            translation.gettext(MESSAGE_IDS["feedback.default." + tone]),
                        )

    def test_dynamically_composed_otp_or_identity_messages_fail_closed(self):
        threats = (
            "کد قبلی هنوز معتبر است. لطفاً 29 ثانیه دیگر دوباره تلاش کنید.",
            "درگاه پیامک در حالت Sandbox است. کد تست شما: 12345678",
            "ارسال پیامک شبیه‌سازی شد. کد تست شما: 9876",
            "شماره موبایل یا رمز عبور اشتباه است. 09123456789",
            "کد تایید منقضی شده است. لطفاً دوباره درخواست کد بدهید. token=secret",
            "خطای پرداخت Stripe: transaction-id:456",
            "درخواست رزرو برای user@example.com",
            "SQL Error: SELECT * FROM accounts",
            mark_safe("<script>alert('private')</script>"),
        )
        for language in ("en", "ar"):
            with translation.override(language):
                for raw in threats:
                    with self.subTest(language=language, value=str(raw)[:50]):
                        expected = translation.gettext(MESSAGE_IDS["feedback.default.error"])
                        html = self.render(constants.ERROR, raw)
                        self.assertIn(expected, html)
                        for secret in ("12345678", "9876", "09123456789", "secret",
                                       "Stripe", "transaction-id", "example.com",
                                       "SELECT *", "<script>", "29"):
                            self.assertNotIn(secret, html)

    def test_unapproved_booking_payment_and_account_messages_still_fallback(self):
        for lang in ("en", "ar"):
            with translation.override(lang):
                for msg in (
                    "اطلاعات این رزرو برای رزرو مجدد کامل نیست.",
                    "پرداخت در مجموعه فقط بعد از پایان خدمت فعال می‌شود.",
                    "نقش متخصص به حساب شما اضافه شد.",
                    "کد تایید برای شما ارسال شد. لطفاً آن را وارد کنید.",
                ):
                    with self.subTest(lang=lang, msg=msg):
                        self.assertEqual(
                            clean_ui_message(msg, "error"),
                            translation.gettext(MESSAGE_IDS["feedback.default.error"]),
                        )

    def test_existing_active_account_views_emit_approved_gettext_literals(self):
        views = (Path(settings.BASE_DIR) / "apps/accounts/views.py").read_text(
            encoding="utf-8"
        )
        for phrase in ERROR_MSGIDS + (INFO_MSGID,):
            self.assertIn('gettext("' + phrase + '")', views)
        self.assertIn("request.session.pop(USER_SESSION_KEY, None)", views)
        self.assertIn("authenticate(", views)
        self.assertIn("otp_attempts", views)

    def test_persian_flash_body_and_domain_invariants_remain_unchanged(self):
        with translation.override("fa"):
            for msgid in ERROR_MSGIDS:
                with self.subTest(message=msgid):
                    self.assertEqual(clean_ui_message(msgid, "error"), msgid)
            self.assertEqual(
                clean_ui_message("ValueError: SQL private", "danger"),
                DEFAULT_ERROR_MESSAGE,
            )
            self.assertIn(INFO_MSGID, self.render(constants.INFO, INFO_MSGID))
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
