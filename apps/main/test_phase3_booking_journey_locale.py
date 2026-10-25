"""Phase 3.29 — integrated booking-step gettext, live DOM copy and bidi audits.

Read-only and database-free. Browser visual/screen-reader acceptance is separate.
"""
import json
from pathlib import Path
import struct
from types import MappingProxyType

from django.conf import settings
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import translation

from loomera.globalization.booking_interactive_messages import BOOKING_UI_MESSAGE_IDS
from loomera.globalization.booking_journey_messages import BOOKING_JOURNEY_MESSAGE_IDS
from loomera.globalization.interactive_messages import MESSAGE_IDS, interactive_messages

LANGUAGES = ("fa", "en", "ar")


@override_settings(
    LOOMERA_ENABLED_LANGUAGES=["fa", "en", "ar"],
    LOOMERA_DEFAULT_LANGUAGE="fa",
    LANGUAGES=(("fa", "فارسی"), ("en", "English"), ("ar", "العربية")),
)
class BookingJourneyLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @classmethod
    def catalog(cls, lang):
        folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
        return (folder / "django.po").read_text(encoding="utf-8"), (folder / "django.mo").read_bytes()

    def tearDown(self):
        translation.deactivate_all()

    def test_17_display_only_keys_are_immutable_and_disjoint(self):
        self.assertIsInstance(BOOKING_JOURNEY_MESSAGE_IDS, MappingProxyType)
        self.assertEqual(len(BOOKING_JOURNEY_MESSAGE_IDS), 17)
        self.assertEqual(len(MESSAGE_IDS), 41)
        self.assertEqual(len(BOOKING_UI_MESSAGE_IDS), 37)
        self.assertEqual(len(set(BOOKING_JOURNEY_MESSAGE_IDS.values())), 17)
        self.assertFalse(set(BOOKING_JOURNEY_MESSAGE_IDS) & set(BOOKING_UI_MESSAGE_IDS))
        self.assertFalse(set(BOOKING_JOURNEY_MESSAGE_IDS) & set(MESSAGE_IDS))
        for name, msgid in BOOKING_JOURNEY_MESSAGE_IDS.items():
            with self.subTest(name=name):
                self.assertTrue(name.startswith("booking."))
                self.assertTrue(msgid and len(msgid) < 300)
                self.assertFalse(any(mark in msgid for mark in ("<", ">", "{", "}")))
        with self.assertRaises(TypeError):
            BOOKING_JOURNEY_MESSAGE_IDS["booking.unreviewed"] = "unreviewed"

    def test_all_58_new_compiled_gettext_literals_match_po_in_three_locales(self):
        sources = self.source("locale/en/LC_MESSAGES/django.po")
        lines = sources.splitlines()
        msgids = []
        for index, line in enumerate(lines):
            if line == "#: loomera/globalization/booking_journey_messages.py":
                self.assertEqual(lines[index + 1][:6], "msgid ")
                msgids.append(json.loads(lines[index + 1][6:]))
        self.assertEqual(len(msgids), 58)
        self.assertEqual(len(set(msgids)), 58)
        self.assertEqual(set(BOOKING_JOURNEY_MESSAGE_IDS.values()) - set(msgids), set())
        for language in LANGUAGES:
            po, mo = self.catalog(language)
            with self.subTest(language=language):
                self.assertEqual(struct.unpack_from("<I", mo)[0], 0x950412de)
                self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 611)
                self.assertEqual(po.count("#: loomera/globalization/booking_journey_messages.py"), 58)
                self.assertEqual(po.count("#: loomera/globalization/booking_interactive_messages.py"), 37)
                with translation.override(language):
                    for msgid in msgids:
                        anchor = 'msgid ' + json.dumps(msgid, ensure_ascii=False) + "\nmsgstr "
                        self.assertEqual(po.count(anchor), 1)
                        value = json.loads(po.split(anchor, 1)[1].splitlines()[0])
                        with self.subTest(key=msgid[:35]):
                            self.assertTrue(value)
                            self.assertNotIn("<", value)
                            self.assertEqual(translation.gettext(msgid), value)
                            if language == "en":
                                self.assertEqual(value, msgid)
                            else:
                                self.assertNotEqual(value, msgid)

    def test_reviewed_persian_multi_day_error_copy_did_not_change(self):
        expected = {
            "booking.available_ninety_days": "روزهای آزاد و غیرفعال این خدمت در ۹۰ روز آینده",
            "booking.no_slot": "بدون وقت",
            "booking.before_previous": "قبل از خدمت قبلی",
            "booking.no_room": "بدون جای خالی",
            "booking.suggested": "پیشنهادی",
            "booking.choose_other_day_action": "برای این خدمت روز دیگری انتخاب می‌کنم",
        }
        with translation.override("fa"):
            for key, original in expected.items():
                self.assertEqual(translation.gettext(BOOKING_JOURNEY_MESSAGE_IDS[key]), original)

    def test_request_scoped_bridge_delivers_95_only_reviewed_messages(self):
        for language in LANGUAGES:
            request = RequestFactory().get("/", HTTP_ACCEPT_LANGUAGE=language)
            data = interactive_messages(request)["interactive_messages"]
            self.assertEqual(data["language"], language)
            self.assertEqual(len(data["messages"]), 95)
            self.assertEqual(
                set(data["messages"]),
                set(MESSAGE_IDS) | set(BOOKING_UI_MESSAGE_IDS) | set(BOOKING_JOURNEY_MESSAGE_IDS),
            )
            with translation.override(language):
                for key, msgid in BOOKING_JOURNEY_MESSAGE_IDS.items():
                    self.assertEqual(data["messages"][key], translation.gettext(msgid))
            output = Template('{{ obj|json_script:"loomera-interactive-messages" }}').render(
                Context({"obj": data})
            )
            self.assertEqual(output.count("<script"), 1)
            self.assertNotIn("<img ", output)

    def test_shared_header_and_specialist_initial_state_use_native_gettext(self):
        header = self.source("templates/orders/_booking_step_header.html")
        staff = self.source("templates/orders/select_stylists.html")
        datetime = self.source("templates/orders/select_datetime.html")
        for msgid in ("Booking journey", "Booking steps", "Choose a service",
                      "Choose a professional", "Choose a time", "Confirm", "Step"):
            self.assertIn("trans '" + msgid + "'", header + staff)
        for msgid in ("No services selected", "First available professional",
                      "Price will be confirmed later", "Professional not selected",
                      "Total price", "In the next step, you will choose a time for each service."):
            self.assertIn("trans '" + msgid + "'", staff)
        for msgid in ("Choose a date and time", "Selected times",
                      "Preparing available times...", "Back to professional selection"):
            self.assertIn("trans '" + msgid + "'", datetime)
        for language in LANGUAGES:
            with translation.override(language):
                for msgid in ("Booking journey", "Choose a professional",
                              "No services selected", "Selected times"):
                    rendered = Template('{% load i18n %}{% trans "' + msgid + '" %}').render(Context({}))
                    self.assertEqual(rendered, translation.gettext(msgid))

    def test_client_day_choices_use_approved_bounded_gettext_at_html_sink(self):
        js = self.source("static/js/select_datetime.js")
        for key in ("calendar_guidance", "suggested", "available_ninety_days",
                    "default_still", "default_same_day", "no_slot", "no_room",
                    "before_previous", "other_day_hint", "choose_other_day_action",
                    "time_step", "chosen_services", "no_time_short"):
            self.assertIn("bookingText('" + key + "'", js)
        for phrase in ("bookingText('calendar_guidance'", "bookingText('another_day_for_service'",
                       "bookingText('other_day_hint'", "bookingText('choose_other_day_action'"):
            self.assertIn("escapeBookingHtml(" + phrase, js)
        self.assertIn("escapeBookingHtml(footerLabel)", js)
        self.assertIn("escapeBookingHtml(jalaliDay.getShortDayName())", js)
        self.assertIn("bookingInput.value = JSON.stringify(bookingData)", js)
        self.assertIn("getAvailabilityForDate(", js)
        self.assertIn("findStalePickedSelection(", js)

    def test_ltr_specialist_cards_and_mixed_script_names_are_direction_safe(self):
        css = self.source("static/css/components/bidirectional_booking.css")
        self.assertIn('html[dir="ltr"] [data-booking-step="staff-selection"] .stylist-option', css)
        self.assertIn("text-align: start;", css)
        self.assertNotIn('html[dir="rtl"] [data-booking-step="staff-selection"]', css)
        staff = self.source("templates/orders/select_stylists.html")
        js = self.source("static/js/select_datetime.js")
        for text in (staff, js):
            self.assertIn('dir="auto"', text)
            self.assertIn("data-booking-service-name", text)
        self.assertIn("escapeBookingHtml(selection.serviceName", js)

    def test_booking_display_only_keys_are_not_server_flash_allowlisted(self):
        bridge = self.source("static/js/interactive_i18n.js")
        self.assertIn('!key.startsWith("booking.")', bridge)
        self.assertIn("approved.has(value.trim())", bridge)
        self.assertNotIn("BOOKING_JOURNEY_MESSAGE_IDS", self.source(
            "apps/main/templatetags/ui_message_extras.py"
        ))
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")

    def test_manual_exit_gates_remain_blocked_until_browser_screenreader_review(self):
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["manual_evidence"], [])
        self.assertIn("screen_reader_acceptance", matrix["open_gates"])
        self.assertIn("real_browser_visual", matrix["open_gates"])
        self.assertIn("release_deployment_approval", matrix["open_gates"])
