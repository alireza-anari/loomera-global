"""Phase 3.31 — booking result and appointment identifiers across bidi locales.

Structural regressions prevent visual isolation from changing machine
values, link targets, monetary expressions, or payment state branches.
Real-browser and screen-reader acceptance remain explicitly open.
"""
from pathlib import Path
import re

from django.conf import settings
from django.test import SimpleTestCase


class PaymentResultBidirectionalTests(SimpleTestCase):
    @staticmethod
    def read(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def test_payment_result_machine_ids_are_isolated_not_transformed(self):
        template = self.read("templates/payments/appointment_result.html")
        for raw in (
            "{{ order.order_number|default:'—' }}",
            "{{ payment.ref_id }}",
            "{{ payment.gateway_track_id }}",
        ):
            with self.subTest(raw=raw):
                self.assertIn('<bdi dir="ltr" data-payment-machine-id>' + raw + "</bdi>", template)
                self.assertEqual(template.count(raw), 1)
        self.assertIn('data-booking-coupon-token', template)
        self.assertIn('dir="ltr" data-booking-coupon-token', template)

    def test_status_and_provider_are_direction_autonomous_not_unescaped_html(self):
        template = self.read("templates/payments/appointment_result.html")
        for raw in (
            "{{ order.salon.salon_name|default:'—' }}",
            "{{ payment_method_label|default:'—' }}",
            "{{ payment_provider_label|default:'—' }}",
            "{{ payment_status_label }}",
            "{{ order_status_label }}",
            "{{ day.date }}",
            "{{ day.time_label }}",
        ):
            with self.subTest(raw=raw):
                self.assertIn('<bdi dir="auto" data-payment-human-label>' + raw + "</bdi>", template)
        self.assertIn('role="status"', template)
        self.assertIn('role="alert"', template)
        self.assertIn("is_payment_pending_review", template)
        self.assertIn("is_pay_in_salon_followup", template)
        self.assertIn("pay_in_salon_online_failed", template)

    def test_financial_amounts_and_provider_server_logic_untouched(self):
        template = self.read("templates/payments/appointment_result.html")
        for expression in (
            "{{ order.subtotal_amount|floatformat:0 }}",
            "{{ order.basket_discount_amount|floatformat:0 }}",
            "{{ order.coupon_discount_amount|floatformat:0 }}",
            "{{ order.discount_amount|floatformat:0 }}",
            "{{ order.tax_amount|floatformat:0 }}",
            "{{ payment.amount|floatformat:0 }}",
        ):
            self.assertIn(expression, template)
        self.assertNotIn("|safe", template)
        self.assertNotIn("data-payment-machine-id|", template)

    def test_appointment_reference_and_visible_phone_are_ltr_isolated(self):
        template = self.read("templates/orders/appointment_detail.html")
        self.assertIn(
            '<bdi dir="ltr" data-payment-machine-id>{{ appointment.order.order_number|default:\'---\' }}</bdi>',
            template,
        )
        self.assertIn(
            '<bdi dir="ltr" data-payment-machine-id>{{ appointment.salon.phone_number }}</bdi>',
            template,
        )
        self.assertIn('href="tel:{{ appointment.salon.phone_number }}"', template)
        self.assertNotIn('href="tel:<bdi', template)

    def test_appointment_visible_times_are_isolated_without_changing_filters(self):
        template = self.read("templates/orders/appointment_detail.html")
        self.assertGreaterEqual(
            template.count('<bdi dir="auto">{{ item.time|persian_time }}</bdi>'), 2,
        )
        self.assertGreaterEqual(
            template.count('<bdi dir="auto">{{ item.end_time|persian_time }}</bdi>'), 2,
        )
        self.assertNotIn("item.time|safe", template)

    def test_booking_back_icons_and_currency_styles_still_respect_direction(self):
        template = self.read("templates/orders/appointment_detail.html")
        self.assertGreaterEqual(template.count("data-booking-back-icon"), 2)
        css = self.read("static/css/components/bidirectional_booking.css")
        self.assertIn('html[dir="ltr"] [data-booking-back-icon]', css)
        self.assertIn("data-booking-coupon-token", css)
        self.assertIn("unicode-bidi: isolate;", css)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")

    def test_exit_acceptance_has_not_been_falsely_signed_off(self):
        import json
        data = json.loads(self.read("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(data["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(data["manual_evidence"], [])
        self.assertIn("screen_reader_acceptance", data["open_gates"])
