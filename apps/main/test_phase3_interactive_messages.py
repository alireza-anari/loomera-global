"""Phase 3 slice 3.5: gettext-to-browser interactive feedback contract tests."""

import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import translation

from loomera.globalization.interactive_messages import (
    MESSAGE_IDS,
    interactive_messages,
)


ENABLED = (("en", "English"), ("ar", "العربية"), ("fa", "فارسی"))


@override_settings(
    LOOMERA_ENABLED_LANGUAGES=["en", "ar", "fa"],
    LOOMERA_DEFAULT_LANGUAGE="fa",
    LANGUAGES=ENABLED,
)
class InteractiveMessagesContractTests(SimpleTestCase):
    @staticmethod
    def _path(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @staticmethod
    def _response_for(language):
        request = RequestFactory().get("/", HTTP_ACCEPT_LANGUAGE=language)
        return interactive_messages(request)["interactive_messages"]

    def tearDown(self):
        translation.deactivate_all()

    def test_versioned_allowlist_has_no_dynamic_server_or_private_fields(self):
        self.assertEqual(len(MESSAGE_IDS), 24)
        self.assertEqual(set(MESSAGE_IDS), set(dict(MESSAGE_IDS)))
        self.assertTrue(all(k.startswith(("feedback.", "validation.")) for k in MESSAGE_IDS))
        self.assertEqual(MESSAGE_IDS["validation.required"], "This field is required.")
        self.assertEqual(MESSAGE_IDS["feedback.close"], "Close message")
        self.assertFalse(any("{user}" in v or "{token}" in v for v in MESSAGE_IDS.values()))
        with self.assertRaises(TypeError):
            MESSAGE_IDS["x"] = "wrong"

    def test_compiled_catalogs_match_all_msgids_in_three_languages(self):
        for language in ("en", "fa", "ar"):
            with self.subTest(language=language):
                folder = Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES"
                self.assertTrue((folder / "django.po").is_file())
                self.assertTrue((folder / "django.mo").is_file())
                with translation.override(language):
                    for key, original in MESSAGE_IDS.items():
                        actual = translation.gettext(original)
                        self.assertTrue(actual, key)
                        if language == "en":
                            self.assertEqual(actual, original, key)
                        else:
                            self.assertNotEqual(actual, original, key)
                self.assertIn('msgid "Language"', (folder / "django.po").read_text(encoding="utf-8"))

    def test_request_language_resolves_and_is_not_leaked_across_requests(self):
        for lang in ("ar", "en", "fa", "en", "ar"):
            with self.subTest(language=lang):
                result = self._response_for(lang)
                self.assertEqual(result["language"], lang)
                self.assertEqual(set(result["messages"]), set(MESSAGE_IDS))
                self.assertEqual(result["messages"]["validation.required"],
                                 {"en": "This field is required.",
                                  "fa": "تکمیل این فیلد الزامی است.",
                                  "ar": "هذا الحقل مطلوب."}[lang])
        self.assertEqual(
            self._response_for("en")["messages"]["feedback.title.error"], "Not completed"
        )

    def test_disallowed_accept_language_does_not_choose_disabled_catalog(self):
        with override_settings(
            LOOMERA_ENABLED_LANGUAGES=["fa"],
            LOOMERA_DEFAULT_LANGUAGE="fa",
            LANGUAGES=(("fa", "فارسی"),),
        ):
            result = self._response_for("en-US,ar;q=0.9")
            self.assertEqual(result["language"], "fa")
            self.assertEqual(result["messages"]["feedback.close"], "بستن پیام")

    def test_safe_json_script_serialization_round_trip_and_escaping(self):
        payload = self._response_for("ar")
        rendered = Template(
            '{{ interactive_messages|json_script:"loomera-interactive-messages" }}'
        ).render(Context({"interactive_messages": payload}))
        self.assertIn('id="loomera-interactive-messages"', rendered)
        self.assertEqual(rendered.count("<script"), 1)
        match = re.search(r"<script[^>]*>(.*?)</script>", rendered, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), payload)
        unsafe = Template(
            '{{ interactive_messages|json_script:"loomera-interactive-messages" }}'
        ).render(Context({"interactive_messages": {
            "language": "en",
            "messages": {"validation.required": "</script><script>alert(1)</script>"},
        }}))
        self.assertNotIn("</script><script>", unsafe)
        self.assertIn("\\u003C", unsafe)

    def test_browser_bridge_precedes_feedback_and_app_js_on_both_shells(self):
        for path in ("templates/base.html", "templates/dashboard_template.html"):
            with self.subTest(path=path):
                text = self._path(path)
                self.assertEqual(text.count('interactive_messages|json_script:'), 1)
                self.assertEqual(text.count("js/interactive_i18n.js"), 1)
                self.assertLess(text.index('interactive_messages|json_script:'),
                                text.index("js/interactive_i18n.js"))
                self.assertLess(text.index("js/interactive_i18n.js"),
                                text.index("js/feedback.js"))
                self.assertLess(text.index("js/interactive_i18n.js"),
                                text.index("js/app.js"))
        processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
        self.assertEqual(processors.count(
            "loomera.globalization.interactive_messages.interactive_messages"), 1)
        self.assertTrue(finders.find("js/interactive_i18n.js"))

    def test_validation_js_uses_catalog_keys_with_legacy_fa_fallback(self):
        source = self._path("static/js/pages/form_interactions.js")
        for key in MESSAGE_IDS:
            if key.startswith("validation."):
                self.assertIn(key, source, key)
        self.assertIn("window.LoomeraI18n?.format?", source)
        self.assertIn("'تکمیل این فیلد الزامی است.'", source)
        self.assertIn("field.validity", source)
        self.assertIn("ensureInlineError(field,", source)
        self.assertIn("field.setAttribute('aria-invalid', 'true')", source)
        self.assertIn("event.preventDefault()", source)
        self.assertIn("window.LoomeraFeedback?.error?", source)

    def test_feedback_filters_untrusted_external_content_in_alternate_languages(self):
        source = self._path("static/js/feedback.js")
        self.assertIn('if (locale !== "fa")', source)
        self.assertIn("isTrustedMessage?.(text)", source)
        self.assertIn("technicalPattern.test(text)", source)
        self.assertIn('node.setAttribute("role", meta.role)', source)
        self.assertIn("body.textContent = text", source)
        self.assertIn('text("feedback.close"', source)
        for key in MESSAGE_IDS:
            if key.startswith("feedback."):
                self.assertIn(key, source, key)
        self.assertIn("const replacements = [", source)
        self.assertTrue(finders.find("js/feedback.js"))

    def test_json_bridge_has_bounded_keys_and_never_evaluates_data(self):
        source = self._path("static/js/interactive_i18n.js")
        self.assertIn("JSON.parse(element.textContent", source)
        self.assertIn("Object.freeze(messages)", source)
        self.assertIn("Object.freeze({", source)
        self.assertIn("Object.prototype.hasOwnProperty.call(messages, key)", source)
        self.assertIn('["fa", "en", "ar"]', source)
        self.assertIn('approved.has(value.trim())', source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("eval(", source)
        self.assertNotIn("fetch(", source)

    def test_business_calendar_currency_and_auth_contracts_unchanged(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        self.assertTrue(settings.LOOMERA_ENABLED_LANGUAGES)
