"""Phase 3 slice 3.6: localized and safe submit-pending indicators."""

from pathlib import Path

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import translation

from loomera.globalization.interactive_messages import MESSAGE_IDS, interactive_messages


ENABLED = (("en", "English"), ("fa", "فارسی"), ("ar", "العربية"))
EXPECTED = {
    "en": ("Saving…", "Sending…", "Working…"),
    "fa": ("در حال ذخیره…", "در حال ارسال…", "در حال انجام…"),
    "ar": ("جارٍ الحفظ…", "جارٍ الإرسال…", "جارٍ التنفيذ…"),
}


@override_settings(
    LOOMERA_ENABLED_LANGUAGES=["en", "fa", "ar"],
    LOOMERA_DEFAULT_LANGUAGE="fa",
    LANGUAGES=ENABLED,
)
class LocalizedSubmitPendingTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def tearDown(self):
        translation.deactivate_all()

    def test_ten_explicit_submit_states_extend_without_changing_prior_catalog(self):
        keys = (
            "saving", "registering", "sending", "creating", "logging_in",
            "confirming", "activating", "deleting", "cancelling", "working",
        )
        self.assertEqual(len(MESSAGE_IDS), 41)
        for key in keys:
            self.assertIn("submit." + key, MESSAGE_IDS)
        self.assertEqual(MESSAGE_IDS["submit.working"], "Working…")
        self.assertEqual(MESSAGE_IDS["validation.required"], "This field is required.")
        self.assertEqual(MESSAGE_IDS["feedback.close"], "Close message")

    def test_versioned_sources_and_compiled_gettext_resolve_every_submit_state(self):
        for language in ("en", "fa", "ar"):
            with self.subTest(language=language):
                folder = Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES"
                po = (folder / "django.po").read_text(encoding="utf-8")
                self.assertTrue((folder / "django.mo").is_file())
                for key, msgid in MESSAGE_IDS.items():
                    if not key.startswith("submit."):
                        continue
                    self.assertIn('msgid "' + msgid + '"', po)
                    with translation.override(language):
                        actual = translation.gettext(msgid)
                    self.assertTrue(actual)
                    if language == "en":
                        self.assertEqual(actual, msgid)
                    else:
                        self.assertNotEqual(actual, msgid)
                with translation.override(language):
                    self.assertEqual(
                        tuple(translation.gettext(MESSAGE_IDS["submit." + key])
                              for key in ("saving", "sending", "working")),
                        EXPECTED[language],
                    )

    def test_request_language_isolation_and_disabled_fallback(self):
        for language in ("en", "ar", "fa", "ar", "en"):
            request = RequestFactory().get("/", HTTP_ACCEPT_LANGUAGE=language)
            data = interactive_messages(request)["interactive_messages"]
            self.assertEqual(data["language"], language)
            self.assertEqual(data["messages"]["submit.saving"], EXPECTED[language][0])
            self.assertEqual(set(data["messages"]), set(MESSAGE_IDS))
        with override_settings(
            LOOMERA_DEFAULT_LANGUAGE="fa",
            LOOMERA_ENABLED_LANGUAGES=["fa"],
            LANGUAGES=(("fa", "فارسی"),),
        ):
            request = RequestFactory().get("/", HTTP_ACCEPT_LANGUAGE="en")
            data = interactive_messages(request)["interactive_messages"]
            self.assertEqual(data["language"], "fa")
            self.assertEqual(data["messages"]["submit.sending"], EXPECTED["fa"][1])

    def test_bridge_restricts_keys_and_preserves_single_mapping_instance(self):
        js = self.source("static/js/interactive_i18n.js")
        self.assertIn("(feedback|validation|submit|password)", js)
        self.assertIn("Object.create(null)", js)
        self.assertIn("Object.freeze(messages)", js)
        self.assertIn('payload.language', js)
        self.assertIn("isTrustedMessage:", js)
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("eval(", js)

    def test_submitter_replaces_children_with_safe_text_not_dynamic_html(self):
        js = self.source("static/js/pages/form_interactions.js")
        self.assertIn("label.textContent = pendingLabel;", js)
        self.assertIn("submitter.replaceChildren(icon, label);", js)
        self.assertNotIn("submitter.innerHTML = " + chr(96) + "<i", js)
        self.assertIn("submitter.dataset.lmOriginalHtml = submitter.innerHTML;", js)
        self.assertIn("submitter.innerHTML = submitter.dataset.lmOriginalHtml;", js)
        self.assertIn("submitter.dataset.lmOriginalValue = submitter.value;", js)
        self.assertIn("submitter.value = pendingLabel;", js)
        self.assertIn("submitter.setAttribute('aria-busy', 'true');", js)
        self.assertIn("submitter.classList.add('lm-submit-pending')", js)

    def test_pending_inference_localizes_preapproved_states_only(self):
        js = self.source("static/js/pages/form_interactions.js")
        for key in MESSAGE_IDS:
            if key.startswith("submit."):
                self.assertIn("'" + key + "'", js)
        self.assertIn("window.LoomeraI18n?.isTrustedMessage?.(explicit)", js)
        self.assertIn("locale === 'fa' && explicit", js)
        self.assertIn("const legacyLabel", js)
        self.assertIn("data-lm-no-submit-feedback", js)
        self.assertIn("if (event.defaultPrevented) return;", js)
        self.assertIn("form.dataset.lmSubmitting = 'true'", js)
        self.assertIn("document.querySelectorAll('[data-lm-submit-pending=\"true\"]')", js)

    def test_email_legal_calendar_payment_settings_are_unaffected(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
