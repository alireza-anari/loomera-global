"""Phase 3.26: safe booking transport, markup, focus and number parity.

Checks actual Django JSON serialization with mixed script names and the
specific JS boundary contracts. Does not claim real-browser acceptance.
"""
from html.parser import HTMLParser
import json
from pathlib import Path

from django.conf import settings
from django.template import engines
from django.test import SimpleTestCase


class JsonScriptReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.payload = ""
        self.unexpected = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "script" and props.get("id") == "booking-stylist-selections":
            self.count += 1
            self.active = True
            assert props.get("type") == "application/json"
        elif tag not in ("script",):
            self.unexpected.append(tag)

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, value):
        if self.active:
            self.payload += value


class BookingJourneySecurityAndA11yTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def test_safe_json_script_replaces_html_attribute_transport(self):
        template = self.source("templates/orders/select_datetime.html")
        self.assertIn('json_script:"booking-stylist-selections"', template)
        self.assertNotIn("stylist_selections_json|safe", template)
        self.assertNotIn("data-selections=", template)
        js = self.source("static/js/select_datetime.js")
        self.assertIn("getElementById('booking-stylist-selections')", js)
        self.assertIn("JSON.parse(JSON.parse(jsonNode.textContent", js)
        self.assertIn("Array.isArray(rawSelections)", js)
        self.assertNotIn("source.dataset.selections", js)

    def test_actual_django_json_script_round_trips_special_names(self):
        template = self.source("templates/orders/select_datetime.html")
        script_line = next(line for line in template.splitlines()
                           if 'json_script:"booking-stylist-selections"' in line)
        raw = "O'Reilly <b> & Team – سارا"
        names = [{"serviceId": 42, "serviceName": raw,
                  "stylistName": "خدمات <special> A&B",
                  "stylistId": "21", "serviceDuration": 30}]
        html = engines["django"].from_string(script_line).render({
            "stylist_selections_json": json.dumps(names, ensure_ascii=False)
        })
        reader = JsonScriptReader()
        reader.feed(html)
        self.assertEqual(reader.count, 1)
        self.assertEqual(reader.unexpected, [])
        self.assertNotIn("<b>", html)
        self.assertNotIn("<special>", html)
        self.assertIn("\\u003C", html)
        self.assertEqual(json.loads(json.loads(reader.payload)), names)

    def test_display_html_escapes_all_person_controlled_names(self):
        js = self.source("static/js/select_datetime.js")
        self.assertIn("function escapeBookingHtml(value)", js)
        self.assertIn("return String(value ?? '').replace(", js)
        for expr in (
            "selection.serviceName || bookingText('service', 'خدمت')",
            "getCurrentDisplayStylist(selection)",
            "existing.stylistName || getCurrentDisplayStylist(selection)",
            "slot.stylistName",
            "summary.parts[0] || 'خدمت'",
            "summary.specialist",
            "summary.pickedLabel",
            "slot.time",
            "slot.end_time",
        ):
            with self.subTest(expr=expr):
                self.assertIn("escapeBookingHtml(" + expr + ")", js)
        self.assertNotIn("${slot.stylistName}", js)
        self.assertNotIn("${selection.serviceName || 'خدمت'}", js)

    def test_time_slot_focus_survives_dom_replacement(self):
        js = self.source("static/js/select_datetime.js")
        self.assertIn("renderTimeSlots(slots, selection, false);", js)
        self.assertIn("candidate.dataset.time === state.currentTime", js)
        self.assertIn("replacement?.focus({ preventScroll: true });", js)
        self.assertIn("data-time-slot", js)
        self.assertIn("aria-pressed=", js)
        self.assertIn('bdi dir="ltr"', js)

    def test_specialist_options_are_native_pressed_buttons_in_named_groups(self):
        template = self.source("templates/orders/select_stylists.html")
        js = self.source("static/js/select_stylist.js")
        self.assertIn('role="group" aria-label="{% blocktrans with service=', template)
        self.assertEqual(template.count('aria-pressed="false"'), 2)
        self.assertNotIn('aria-selected=', template)
        self.assertNotIn("setAttribute('aria-selected'", js)
        self.assertIn("setAttribute('aria-pressed', 'true')", js)
        self.assertIn("setAttribute('aria-pressed', 'false')", js)
        self.assertIn("button.disabled", js)
        self.assertIn("handleStylistSelection", js)

    def test_language_digit_maps_are_explicit_and_fallback_to_fa(self):
        date_js = self.source("static/js/select_datetime.js")
        staff_js = self.source("static/js/select_stylist.js")
        self.assertIn("function bookingDigitMap()", date_js)
        for digits in ("0123456789", "٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹"):
            self.assertIn(digits, date_js)
        self.assertIn("document.documentElement.lang", date_js)
        self.assertIn("document.documentElement.lang", staff_js)
        self.assertIn("new Intl.NumberFormat(locale)", date_js)
        self.assertIn("toLocaleString(locale)", staff_js)
        self.assertIn("JalaliDate.jalaliToGregorian(", date_js)
        self.assertIn("JalaliDate.gregorianToJalali(", date_js)
        self.assertIn("normalizeDigits(", date_js)

    def test_submit_payload_and_availability_guard_are_unchanged(self):
        date_template = self.source("templates/orders/select_datetime.html")
        staff_template = self.source("templates/orders/select_stylists.html")
        date_js = self.source("static/js/select_datetime.js")
        staff_js = self.source("static/js/select_stylist.js")
        for marker in ('id="dateTimeSelectionForm"', 'name="booking_data"',
                       'id="bookingDataInput"', '{% csrf_token %}'):
            self.assertIn(marker, date_template)
        for marker in ('id="stylistSelectionForm"', 'name="stylist_selections"',
                       'id="stylistSelectionsInput"', '{% csrf_token %}'):
            self.assertIn(marker, staff_template)
        self.assertIn("bookingInput.value = JSON.stringify(bookingData)", date_js)
        self.assertIn("bookingForm.submit()", date_js)
        self.assertIn("input.value = JSON.stringify(selections)", staff_js)
        self.assertIn("form.submit()", staff_js)
        self.assertIn("findStalePickedSelection(", date_js)
        self.assertIn("getAvailabilityForDate(", date_js)

    def test_checkout_payment_result_guards_still_present(self):
        checkout = self.source("templates/orders/checkout.html")
        preview = self.source("templates/orders/reservation_preview.html")
        payment = self.source("templates/payments/appointment_result.html")
        for markup in (checkout, preview):
            self.assertIn("data-checkout-final-submit", markup)
            self.assertIn("data-checkout-guard-form", markup)
        self.assertIn('role="status"', payment)
        self.assertIn("data-payment-result-hero", payment)

    def test_default_iranian_locale_time_calendar_and_currency_unchanged(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        root = self.source("templates/base.html")
        self.assertIn("deployment_locale.language_code", root)
        self.assertIn("deployment_locale.direction", root)
