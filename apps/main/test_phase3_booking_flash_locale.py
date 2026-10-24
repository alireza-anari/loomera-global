"""Phase 3.19: booking/service flash display localization safety regression.

These tests use actual Django flash partial rendering, no database, payments,
bookings, SMS or external translation services. No backend domain change.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation
from django.utils.safestring import mark_safe

from apps.main.templatetags.ui_message_extras import clean_ui_message
from apps.main.ui_feedback import user_error_message, user_ui_message
from loomera.globalization.booking_flash_messages import (
    BOOKING_FLASH_MESSAGES, trusted_booking_flash,
)
from loomera.globalization.interactive_messages import MESSAGE_IDS

TONES = {
    "error": (constants.ERROR, "alert"),
    "success": (constants.SUCCESS, "status"),
    "info": (constants.INFO, "status"),
}


class BookingFlashLocaleTests(SimpleTestCase):
    def tearDown(self):
        translation.deactivate_all()

    @staticmethod
    def render(level, raw):
        return render_to_string(
            "partials/messages.html", {"messages": [Message(level, raw)]}
        )

    @staticmethod
    def expected(language, english, arabic):
        return english if language == "en" else arabic

    def test_reviewed_catalog_is_immutable_and_tone_scoped(self):
        self.assertIsInstance(BOOKING_FLASH_MESSAGES, tuple)
        self.assertEqual(len(BOOKING_FLASH_MESSAGES), 14)
        counts = {tone: sum(row[0] == tone for row in BOOKING_FLASH_MESSAGES)
                  for tone in TONES}
        self.assertEqual(counts, {"error": 10, "success": 3, "info": 1})
        self.assertEqual(len({r[1] for r in BOOKING_FLASH_MESSAGES}), 14)
        for tone, fa, en, ar in BOOKING_FLASH_MESSAGES:
            with self.subTest(fa=fa):
                self.assertIn(tone, TONES)
                for message in (fa, en, ar):
                    self.assertEqual(message, message.strip())
                    self.assertFalse(any(piece in message for piece in (
                        "%(", "{", "}", "<", ">", "http://", "https://"
                    )))
                    self.assertLess(len(message), 300)
                self.assertTrue(all((fa, en, ar)))
        with self.assertRaises(TypeError):
            BOOKING_FLASH_MESSAGES[0] = ("injected",)

    def test_all_approved_phrases_render_for_en_ar_from_each_source_language(self):
        for tone, fa, en, ar in BOOKING_FLASH_MESSAGES:
            level, role = TONES[tone]
            for raw in (fa, en, ar):
                for language in ("en", "ar"):
                    with self.subTest(tone=tone, locale=language, source=raw[:25]):
                        with translation.override(language):
                            expected = self.expected(language, en, ar)
                            html = self.render(level, raw)
                            self.assertEqual(clean_ui_message(raw, tone), expected)
                            self.assertIn(expected, html)
                            self.assertIn('role="' + role + '"', html)
                            self.assertIn('data-flash-close', html)
                            self.assertIn('data-flash-message', html)
                            self.assertNotIn(
                                translation.gettext(MESSAGE_IDS["feedback.default." + tone]),
                                html,
                            )

    def test_danger_alias_has_error_tone_but_warning_is_not_implicitly_error(self):
        error_row = next(r for r in BOOKING_FLASH_MESSAGES if r[0] == "error")
        fa, en, ar = error_row[1:]
        for language in ("en", "ar"):
            with translation.override(language):
                with self.subTest(language=language):
                    self.assertEqual(clean_ui_message(fa, "danger"),
                                     self.expected(language, en, ar))
                    html = self.render(constants.ERROR, fa)
                    self.assertIn('role="alert"', html)
                    self.assertEqual(clean_ui_message(fa, "warning"),
                                     translation.gettext(MESSAGE_IDS["feedback.default.warning"]))

    def test_no_cross_tone_promotion_even_for_exact_translations(self):
        for tone, fa, en, ar in BOOKING_FLASH_MESSAGES:
            for target_tone in ("error", "warning", "success", "info"):
                if target_tone == tone:
                    continue
                for language in ("en", "ar"):
                    with translation.override(language):
                        with self.subTest(source=tone, target=target_tone, lang=language):
                            fallback = translation.gettext(
                                MESSAGE_IDS["feedback.default." + target_tone]
                            )
                            for raw in (fa, en, ar):
                                self.assertEqual(clean_ui_message(raw, target_tone), fallback)

    def test_near_miss_and_personal_or_provider_data_are_never_echoed(self):
        threats = [
            "پرداخت در مجموعه فقط بعد از پایان خدمت فعال می‌شود.",
            "اطلاعات این رزرو برای رزرو مجدد کامل نیست.",
            "کد تخفیف روی مبلغ نهایی اعمال شد.",
            "رزرو شما با موفقیت ثبت شد. شماره: 09123456789",
            "رزرو شما با موفقیت ثبت شد. user@email.test",
            "SQL Error: SELECT * FROM users",
            mark_safe("<script>alert('danger')</script>"),
            "کد تست شما: 12345678",
        ]
        for language in ("en", "ar"):
            with translation.override(language):
                for tone, (level, _) in TONES.items():
                    fallback = translation.gettext(
                        MESSAGE_IDS["feedback.default." + tone]
                    )
                    for raw in threats:
                        with self.subTest(language=language, tone=tone, raw=str(raw)[:30]):
                            html = self.render(level, raw)
                            self.assertEqual(clean_ui_message(raw, tone), fallback)
                            self.assertIn(fallback, html)
                            for secret in ("09123456789", "email.test", "SELECT *",
                                           "12345678", "<script>", "danger"):
                                self.assertNotIn(secret, html)

    def test_approved_phrases_cannot_be_extended_with_user_data(self):
        for tone, fa, en, ar in BOOKING_FLASH_MESSAGES:
            for language in ("en", "ar"):
                with translation.override(language):
                    fallback = translation.gettext(
                        MESSAGE_IDS["feedback.default." + tone]
                    )
                    for raw in (
                        fa + " 12345", en + " booking #8675309",
                        ar + " user=private", fa[:-1], fa + "<b>",
                    ):
                        with self.subTest(tone=tone, locale=language, raw=raw[:25]):
                            self.assertEqual(clean_ui_message(raw, tone), fallback)
                            self.assertIsNone(trusted_booking_flash(raw, tone, language))

    def test_fa_preserves_historical_domain_messages_and_technical_sanitizer(self):
        with translation.override("fa"):
            for tone, fa, _, _ in BOOKING_FLASH_MESSAGES:
                with self.subTest(tone=tone, source=fa):
                    expected = user_error_message(fa) if tone == "error" else (
                        user_ui_message(fa, allow_latin_data=True)
                    )
                    self.assertEqual(clean_ui_message(fa, tone), expected)
                    self.assertIn(expected, self.render(TONES[tone][0], fa))
            self.assertEqual(
                clean_ui_message("ValueError: SQL failure", "error"),
                user_error_message("ValueError: SQL failure"),
            )

    def test_translation_contract_does_not_expand_browser_catalog_or_change_defaults(self):
        self.assertEqual(len(MESSAGE_IDS), 41)
        for tone, fa, en, ar in BOOKING_FLASH_MESSAGES:
            self.assertNotIn(fa, MESSAGE_IDS.values())
            self.assertIsNone(trusted_booking_flash(fa, "warning", "en"))
            self.assertIsNone(trusted_booking_flash(fa, tone, "fa"))
            self.assertIsNone(trusted_booking_flash(fa, tone, "de"))
        for name, expected in (
            ("LANGUAGE_CODE", "fa"),
            ("TIME_ZONE", "Asia/Tehran"),
            ("LOOMERA_DEFAULT_CALENDAR", "jalali"),
            ("LOOMERA_DEFAULT_CURRENCY", ""),
        ):
            self.assertEqual(getattr(settings, name), expected)

    def test_active_booking_views_are_read_only_and_contain_reviewed_sources(self):
        source = (Path(settings.BASE_DIR) / "apps/orders/views.py").read_text(encoding="utf-8")
        for tone, fa, _, _ in BOOKING_FLASH_MESSAGES:
            with self.subTest(fa=fa):
                self.assertIn(fa, source)
                self.assertIn("messages." + tone + "(", source)
        self.assertIn("resolve_booking_sequence(", source)
        self.assertIn("transaction.atomic(", source)
        self.assertIn("record_booking_quick_link_started(", source)

    def test_render_language_switch_does_not_cache_previous_locale(self):
        for language in ("en", "ar", "fa", "ar", "en"):
            with translation.override(language):
                for tone, fa, en, ar in BOOKING_FLASH_MESSAGES:
                    with self.subTest(lang=language, tone=tone):
                        expected = fa if language == "fa" else (
                            en if language == "en" else ar
                        )
                        self.assertIn(expected, self.render(TONES[tone][0], fa))
