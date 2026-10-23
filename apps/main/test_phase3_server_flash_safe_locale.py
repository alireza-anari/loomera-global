"""Phase 3.17: request-locale-safe server flash bodies.

Tests intentionally render real Django partials and compiled catalogs without
a database or any external services. This is not browser screen-reader QA.
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
from apps.main.ui_feedback import (
    DEFAULT_ERROR_MESSAGE, user_error_message, user_ui_message,
)
from loomera.globalization.interactive_messages import MESSAGE_IDS


TONES = (
    (constants.ERROR, "error", "alert"),
    (constants.WARNING, "warning", "alert"),
    (constants.SUCCESS, "success", "status"),
    (constants.INFO, "info", "status"),
)


class ServerFlashSafeLocaleTests(SimpleTestCase):
    @staticmethod
    def render(level, content):
        return render_to_string("partials/messages.html", {
            "messages": [Message(level, content)],
        })

    def tearDown(self):
        translation.deactivate_all()

    def test_untrusted_flash_bodies_resolve_to_translated_typed_fallback(self):
        for language in ("en", "ar"):
            with translation.override(language):
                for level, tone, role in TONES:
                    with self.subTest(lang=language, tone=tone):
                        expected = translation.gettext(
                            MESSAGE_IDS["feedback.default." + tone]
                        )
                        html = self.render(level, "Sensitive runtime payload 8675309")
                        self.assertIn(expected, html)
                        self.assertNotIn("Sensitive runtime payload", html)
                        self.assertNotIn("8675309", html)
                        self.assertIn(f'role="{role}"', html)
                        self.assertIn('data-flash-close', html)

    def test_sql_exceptions_markup_and_user_pii_never_reach_alt_language_html(self):
        threats = (
            "KeyError: auth_token=secret; SQL SELECT * FROM users",
            "<img src=x onerror=alert(1)>",
            "User mobile 09123456789",
            "خطای مشتری خصوصی 09123456789",
            mark_safe("<script>alert('private')</script>"),
            "External.provider exception Traceback",
            "The action completed successfully. [user@email.test]",
        )
        for language in ("en", "ar"):
            with translation.override(language):
                expected = translation.gettext(MESSAGE_IDS["feedback.default.error"])
                for content in threats:
                    with self.subTest(lang=language, content=str(content)):
                        html = self.render(constants.ERROR, content)
                        self.assertIn(expected, html)
                        self.assertNotIn("09123456789", html)
                        self.assertNotIn("user@email.test", html)
                        self.assertNotIn("secret", html)
                        self.assertNotIn("KeyError", html)
                        self.assertNotIn("<script>", html)
                        self.assertNotIn("<img ", html)
                        self.assertNotIn("Traceback", html)

    def test_exact_trusted_catalog_messages_translate_across_all_source_locales(self):
        for target in ("en", "ar"):
            for level, tone, _ in TONES:
                key = "feedback.default." + tone
                msgid = MESSAGE_IDS[key]
                for origin in ("fa", "en", "ar"):
                    with translation.override(origin):
                        original = translation.gettext(msgid)
                    with translation.override(target):
                        with self.subTest(target=target, origin=origin, tone=tone):
                            expected = translation.gettext(msgid)
                            self.assertEqual(clean_ui_message(original, tone), expected)
                            self.assertIn(expected, self.render(level, original))

    def test_known_validation_notices_are_scoped_to_warning_or_error(self):
        for key in ("validation.notice", "validation.server_form"):
            msgid = MESSAGE_IDS[key]
            with translation.override("fa"):
                persian_notice = translation.gettext(msgid)
            for language in ("en", "ar"):
                with translation.override(language):
                    for tag in ("error", "danger", "warning"):
                        with self.subTest(key=key, language=language, tag=tag):
                            self.assertEqual(
                                clean_ui_message(persian_notice, tag),
                                translation.gettext(msgid),
                            )
                    self.assertEqual(
                        clean_ui_message(persian_notice, "success"),
                        translation.gettext(MESSAGE_IDS["feedback.default.success"]),
                    )

    def test_nonexact_or_cross_tone_messages_are_not_implicitly_trusted(self):
        for language in ("en", "ar"):
            with translation.override(language):
                expected_error = translation.gettext(MESSAGE_IDS["feedback.default.error"])
                expected_success = translation.gettext(MESSAGE_IDS["feedback.default.success"])
                for candidate in (
                    MESSAGE_IDS["feedback.default.error"] + "!",
                    "  " + MESSAGE_IDS["feedback.default.error"] + " —debug",
                    "A" * 5000,
                    "Untranslated valid-looking sentence",
                ):
                    with self.subTest(lang=language, candidate=candidate[:40]):
                        self.assertEqual(clean_ui_message(candidate, "error"), expected_error)
                self.assertEqual(
                    clean_ui_message(MESSAGE_IDS["feedback.default.error"], "success"),
                    expected_success,
                )
                self.assertEqual(clean_ui_message("anything", ""), translation.gettext(
                    MESSAGE_IDS["feedback.default.info"]
                ))

    def test_language_switch_does_not_retain_previous_request_fallback(self):
        sequence = ("en", "ar", "fa", "ar", "en")
        for language in sequence:
            with translation.override(language):
                with self.subTest(language=language):
                    outcome = clean_ui_message("ValueError: private database", "error")
                    expected = (
                        DEFAULT_ERROR_MESSAGE if language == "fa"
                        else translation.gettext(MESSAGE_IDS["feedback.default.error"])
                    )
                    self.assertEqual(outcome, expected)

    def test_persian_legacy_sanitizer_maintains_exact_domain_and_positive_copy(self):
        with translation.override("fa"):
            examples = (
                ("ثبت با موفقیت انجام شد.", "success"),
                ("مشکلی در ثبت درخواست رخ داد.", "error"),
                ("وضعیت سالن Salon A ثبت شد.", "info"),
            )
            for message, tag in examples:
                with self.subTest(tag=tag):
                    expected = (
                        user_error_message(message)
                        if tag == "error"
                        else user_ui_message(message, allow_latin_data=True)
                    )
                    self.assertEqual(clean_ui_message(message, tag), expected)
            self.assertEqual(
                clean_ui_message("KeyError: private SQL", "error"), DEFAULT_ERROR_MESSAGE
            )

    def test_scope_keeps_only_existing_catalog_keys_and_template_escape(self):
        filter_src = (Path(settings.BASE_DIR) /
                      "apps/main/templatetags/ui_message_extras.py").read_text(encoding="utf-8")
        template = (Path(settings.BASE_DIR) /
                    "templates/partials/messages.html").read_text(encoding="utf-8")
        self.assertIn('language in {"en", "ar"}', filter_src)
        self.assertIn('translation.override(known_language)', filter_src)
        self.assertIn('_TRUSTED_ERROR_KEYS', filter_src)
        self.assertIn("return user_error_message(value)", filter_src)
        self.assertIn("return user_ui_message(value, allow_latin_data=True)", filter_src)
        self.assertIn("{{ message|clean_ui_message:message.tags }}", template)
        self.assertNotIn("|safe", template)
        self.assertIn('aria-live="polite"', template)
        self.assertEqual(len(MESSAGE_IDS), 41)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
