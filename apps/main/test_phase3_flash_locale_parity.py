"""Phase 3.16: server-rendered flash chrome and existing sanitizer parity.

Database-free real-template tests across compiled Django fa/en/ar catalogs.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation

from apps.main.ui_feedback import DEFAULT_ERROR_MESSAGE


TITLES = {
    "fa": ("انجام نشد", "انجام شد", "نیاز به بررسی", "اطلاع", "بستن پیام"),
    "en": ("Not completed", "Completed", "Needs review", "Information", "Close message"),
    "ar": ("لم تكتمل العملية", "تمت العملية", "تحتاج إلى مراجعة", "معلومات", "إغلاق الرسالة"),
}
TYPES = (
    (constants.ERROR, "error", "alert"),
    (constants.SUCCESS, "success", "status"),
    (constants.WARNING, "warning", "alert"),
    (constants.INFO, "info", "status"),
)


class FlashLocaleParityTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def tearDown(self):
        translation.deactivate_all()

    def test_actual_flash_titles_and_close_labels_follow_request_locale(self):
        for locale, expected in TITLES.items():
            with self.subTest(locale=locale), translation.override(locale):
                for (level, tag, role), title in zip(TYPES, expected[:4]):
                    with self.subTest(tone=tag):
                        html = render_to_string("partials/messages.html", {
                            "messages": [Message(level, "درخواست بررسی شد.")],
                        })
                        self.assertIn(title, html)
                        self.assertIn(f'role="{role}"', html)
                        self.assertIn(expected[4], html)
                        self.assertIn('data-flash-message', html)
                        self.assertIn('data-flash-close', html)
                        self.assertIn("درخواست بررسی شد.", html)

    def test_python_flash_sanitizer_still_blocks_technical_or_hostile_errors(self):
        for locale in TITLES:
            with self.subTest(locale=locale), translation.override(locale):
                html = render_to_string("partials/messages.html", {
                    "messages": [Message(constants.ERROR, "ValueError: SQL <script>alert(1)</script>")],
                })
                self.assertNotIn("ValueError:", html)
                self.assertNotIn("<script>alert(1)</script>", html)
                self.assertIn(DEFAULT_ERROR_MESSAGE, html)
                self.assertIn(TITLES[locale][0], html)

    def test_server_flash_markup_preserves_structure_and_uses_versioned_gettext(self):
        src = self.source("templates/partials/messages.html")
        self.assertIn("{% load i18n ui_message_extras %}", src)
        self.assertEqual(src.count("{% trans"), 5)
        for source in ("Not completed", "Completed", "Needs review", "Information", "Close message"):
            self.assertIn(f"'{source}'" if source == "Close message" else f'"{source}"', src)
        self.assertIn("message|clean_ui_message:message.tags", src)
        self.assertIn("message.tags", src)
        self.assertIn('data-dismiss-after="5000"', src)
        self.assertIn('aria-live="polite"', src)
        self.assertNotIn("{{ message|safe", src)

    def test_versioned_catalogs_keep_persian_and_arabic_notices(self):
        for language, expected in TITLES.items():
            with translation.override(language):
                for source, translated in zip(
                    ("Not completed", "Completed", "Needs review", "Information", "Close message"),
                    expected,
                ):
                    self.assertEqual(translation.gettext(source), translated)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")

    def test_js_feedback_does_not_shadow_browser_i18n_accessor(self):
        js = self.source("static/js/feedback.js")
        self.assertIn('const text = (key, fallback)', js)
        self.assertIn("const messageText = normalizeMessage(", js)
        self.assertIn("body.textContent = messageText", js)
        self.assertIn('text("feedback.close", "بستن پیام")', js)
        self.assertNotIn("const text = normalizeMessage(", js)
        self.assertIn("window.LoomeraFeedback = {", js)
