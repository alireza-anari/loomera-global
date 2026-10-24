"""Phase 3.28: compiled fa/en/ar booking JS copy and feedback isolation."""
from pathlib import Path
import json
import re
import struct
from types import MappingProxyType

from django.conf import settings
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import translation

from loomera.globalization.booking_interactive_messages import BOOKING_UI_MESSAGE_IDS
from loomera.globalization.interactive_messages import MESSAGE_IDS, interactive_messages

LOCALES = (("fa", "rtl"), ("en", "ltr"), ("ar", "rtl"))


@override_settings(
    LOOMERA_ENABLED_LANGUAGES=["fa", "en", "ar"],
    LOOMERA_DEFAULT_LANGUAGE="fa",
    LANGUAGES=(("fa", "فارسی"), ("en", "English"), ("ar", "العربية")),
)
class BookingDynamicLocaleTests(SimpleTestCase):
    def tearDown(self):
        translation.deactivate_all()

    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def test_separate_immutable_booking_allowlist_keeps_old_41_messages(self):
        self.assertIsInstance(BOOKING_UI_MESSAGE_IDS, MappingProxyType)
        self.assertEqual(len(BOOKING_UI_MESSAGE_IDS), 37)
        self.assertEqual(len(MESSAGE_IDS), 41)
        self.assertFalse(set(BOOKING_UI_MESSAGE_IDS) & set(MESSAGE_IDS))
        self.assertEqual(len(set(BOOKING_UI_MESSAGE_IDS.values())), 37)
        for key, msgid in BOOKING_UI_MESSAGE_IDS.items():
            with self.subTest(key=key):
                self.assertRegex(key, r"^booking\.[a-z_]+$")
                self.assertTrue(msgid and len(msgid) <= 300)
                self.assertFalse(any(char in msgid for char in "<>{}"))
                self.assertNotIn("token", key)
                self.assertNotIn("payment", key)
                self.assertNotIn("mobile", key)
        with self.assertRaises(TypeError):
            BOOKING_UI_MESSAGE_IDS["booking.bad"] = "unapproved"

    def test_all_37_native_po_mo_entries_match_active_gettext(self):
        for lang, direction in LOCALES:
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            po = (folder / "django.po").read_text(encoding="utf-8")
            mo = (folder / "django.mo").read_bytes()
            with self.subTest(lang=lang):
                self.assertEqual(struct.unpack_from("<I", mo)[0], 0x950412de)
                self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 234)
                self.assertEqual(
                    po.count("#: loomera/globalization/booking_interactive_messages.py"),
                    37,
                )
                self.assertIn('"Language: ' + lang + r'\n"', po)
                with translation.override(lang):
                    for key, english in BOOKING_UI_MESSAGE_IDS.items():
                        escaped = re.escape(json.dumps(english, ensure_ascii=False))
                        matches = re.findall(
                            r'(?m)^msgid ' + escaped +
                            r'\nmsgstr ("(?:[^"\\]|\\.)*")$',
                            po,
                        )
                        with self.subTest(language=lang, key=key):
                            self.assertEqual(len(matches), 1)
                            value = json.loads(matches[0])
                            self.assertTrue(value)
                            self.assertNotIn("<", value)
                            self.assertEqual(translation.gettext(english), value)
                            if lang == "en":
                                self.assertEqual(value, english)
                            else:
                                self.assertNotEqual(value, english)

    def test_original_persian_booking_copy_and_semantics_are_preserved(self):
        expected = {
            "booking.any_professional": "فرقی ندارد",
            "booking.service": "خدمت",
            "booking.selected": "انتخاب‌شده",
            "booking.continue_time": "ادامه انتخاب زمان",
            "booking.morning": "صبح",
            "booking.noon": "ظهر",
            "booking.evening": "عصر",
            "booking.night": "شب",
            "booking.toman": "تومان",
        }
        with translation.override("fa"):
            for key, value in expected.items():
                self.assertEqual(translation.gettext(BOOKING_UI_MESSAGE_IDS[key]), value)

    def test_request_bridge_contains_exact_approved_booking_messages(self):
        for lang, _ in LOCALES:
            request = RequestFactory().get("/", HTTP_ACCEPT_LANGUAGE=lang)
            result = interactive_messages(request)["interactive_messages"]
            with self.subTest(lang=lang):
                self.assertEqual(result["language"], lang)
                self.assertEqual(len(result["messages"]), 78)
                with translation.override(lang):
                    for key, source in BOOKING_UI_MESSAGE_IDS.items():
                        self.assertEqual(result["messages"][key], translation.gettext(source))
                serialized = Template(
                    '{{ ui|json_script:"loomera-interactive-messages" }}'
                ).render(Context({"ui": result}))
                self.assertEqual(serialized.count("<script"), 1)
                payload = re.search(r"<script[^>]*>(.*?)</script>",
                                    serialized, re.DOTALL).group(1)
                self.assertEqual(json.loads(payload), result)

    def test_native_template_initial_state_is_translated_without_js(self):
        pages = (
            ("templates/orders/select_stylists.html",
             'trans "Continue to time selection"', "booking.continue_time"),
            ("templates/orders/select_datetime.html",
             'trans "Choose a date and time to continue"', "booking.choose_date_time"),
            ("templates/orders/select_datetime.html",
             'trans "No appointment time has been selected yet."',
             "booking.no_picked_yet"),
        )
        for page, marker, key in pages:
            src = self.source(page)
            self.assertIn("{% load static i18n %}", src)
            self.assertIn("{% " + marker + " %}", src)
            for lang, _ in LOCALES:
                with translation.override(lang):
                    result = Template(
                        '{% load i18n %}{% ' + marker + ' %}'
                    ).render(Context({}))
                    self.assertEqual(
                        result, translation.gettext(BOOKING_UI_MESSAGE_IDS[key])
                    )

    def test_booking_copy_is_not_promoted_to_trusted_flash_feedback(self):
        bridge = self.source("static/js/interactive_i18n.js")
        self.assertIn("feedback|validation|submit|password|booking", bridge)
        self.assertIn('!key.startsWith("booking.")', bridge)
        self.assertIn("approved.has(value.trim())", bridge)
        self.assertIn("Object.freeze(messages)", bridge)
        self.assertNotIn("innerHTML", bridge)
        self.assertNotIn("eval(", bridge)
        backend = self.source("apps/main/templatetags/ui_message_extras.py")
        self.assertNotIn("BOOKING_UI_MESSAGE_IDS", backend)

    def test_booking_dynamic_pages_use_native_compiled_bridge_without_js_table(self):
        date = self.source("static/js/select_datetime.js")
        staff = self.source("static/js/select_stylist.js")
        for js in (date, staff):
            self.assertIn("function bookingText(key, fallback)", js)
            self.assertIn("window.LoomeraI18n?.text?", js)
            self.assertNotIn("bookingCopyTranslations =", js)
        for key in (
            "booking.available_times", "booking.choose_date_time",
            "booking.morning", "booking.continue_time", "booking.services_remaining",
        ):
            self.assertIn(key, BOOKING_UI_MESSAGE_IDS)
        self.assertIn("bookingText('selected'", date)
        self.assertIn("bookingText('continue_time'", staff)
        self.assertIn("json_script:\"booking-stylist-selections\"",
                      self.source("templates/orders/select_datetime.html"))

    def test_no_change_to_iranian_defaults_or_checkout_business_rules(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        order = self.source("apps/orders/views.py")
        self.assertIn("transaction.atomic(", order)
        self.assertIn("resolve_booking_sequence(", order)
        self.assertIn("payment.mark_success(", order)
