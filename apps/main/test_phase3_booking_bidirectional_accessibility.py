"""Phase 3.25: booking RTL/LTR, keyboard payment radio and errors.

Structural/Django-rendered checks are not a visual browser, keyboard or
assistive-technology acceptance test. No external services or database.
"""
from pathlib import Path
import re

from django.conf import settings
from django.template import engines
from django.test import SimpleTestCase
from django.utils import translation

from apps.orders.forms import AppointmentCheckoutForm


class BookingBidirectionalAccessibilityTests(SimpleTestCase):
    BOOKING_TEMPLATES = (
        "templates/orders/_booking_step_header.html",
        "templates/orders/select_datetime.html",
        "templates/orders/select_stylists.html",
        "templates/orders/appointment_detail.html",
    )
    CHECKOUT_TEMPLATES = (
        "templates/orders/checkout.html",
        "templates/orders/reservation_preview.html",
    )
    FINANCIAL_TEMPLATES = CHECKOUT_TEMPLATES + (
        "templates/payments/appointment_result.html",
    )

    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def tearDown(self):
        translation.deactivate_all()

    def test_styles_are_loaded_once_after_existing_bidirectional_shell(self):
        src = self.source("templates/base.html")
        a = "css/components/bidirectional_shell.css"
        b = "css/components/bidirectional_booking.css"
        self.assertEqual(src.count(b), 1)
        self.assertLess(src.index(a), src.index(b))
        self.assertIn('dir="{{ deployment_locale.direction|default:', src)

    def test_only_ltr_navigation_icons_are_mirrored_without_reordering_controls(self):
        css = self.source("static/css/components/bidirectional_booking.css")
        self.assertIn('html[dir="ltr"] [data-booking-back-icon]', css)
        self.assertIn('transform: scaleX(-1);', css)
        self.assertNotIn('html[dir="rtl"]', css)
        self.assertNotIn("flex-direction: row-reverse", css)
        self.assertNotIn("order:", css)
        expected = {
            "templates/orders/_booking_step_header.html": 3,
            "templates/orders/select_datetime.html": 1,
            "templates/orders/select_stylists.html": 2,
            "templates/orders/appointment_detail.html": 2,
        }
        for path, count in expected.items():
            src = self.source(path)
            with self.subTest(path=path):
                self.assertEqual(src.count("data-booking-back-icon"), count)
                self.assertEqual(len(re.findall(
                    r'<i data-booking-back-icon class="fa-solid fa-arrow-right',
                    src,
                )), count)
                self.assertIn('aria-hidden="true"', src)
        for path in self.CHECKOUT_TEMPLATES:
            self.assertIn('"orders/_booking_step_header.html"', self.source(path))

    def test_checkout_and_preview_show_field_error_ids_matched_to_django_auto_id(self):
        for path in self.CHECKOUT_TEMPLATES:
            src = self.source(path)
            with self.subTest(path=path):
                for field in ("coupon_code", "payment_method"):
                    self.assertIn(
                        'id="{{ form.' + field + '.auto_id }}_error" role="alert"',
                        src,
                    )
                    self.assertIn("form." + field + ".errors", src)
                self.assertIn('data-checkout-guard-form', src)
                self.assertIn('name="form_action"', src)
                self.assertIn('data-checkout-final-submit', src)

    def test_invalid_checkout_widgets_generate_correct_aria_error_references(self):
        form = AppointmentCheckoutForm(
            data={"coupon_code": "X" * 101, "payment_method": "invalid"},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("coupon_code", form.errors)
        self.assertIn("payment_method", form.errors)
        coupon_html = str(form["coupon_code"])
        payment_html = str(form["payment_method"])
        self.assertIn('aria-invalid="true"', coupon_html)
        self.assertIn('aria-describedby="id_coupon_code_error"', coupon_html)
        self.assertIn('id="id_coupon_code"', coupon_html)
        self.assertIn('aria-invalid="true"', payment_html)
        # Django RadioSelect does not automatically attach aria-describedby.
        self.assertNotIn('aria-describedby="id_payment_method_error"', payment_html)
        for path in self.CHECKOUT_TEMPLATES:
            src = self.source(path)
            for name in ("coupon_code", "payment_method"):
                with self.subTest(path=path, name=name):
                    self.assertIn(
                        'id="{{ form.' + name + '.auto_id }}_error"',
                        src,
                    )
        self.assertEqual(form["coupon_code"].auto_id, "id_coupon_code")
        self.assertEqual(form["payment_method"].auto_id, "id_payment_method")


    def test_payment_radiogroups_render_error_links_only_when_invalid(self):
        for path in self.CHECKOUT_TEMPLATES:
            src = self.source(path)
            start = src.index('<div class="grid gap-3" role="radiogroup"')
            end = src.index(">", start) + 1
            fragment = engines["django"].from_string("{% load i18n %}" + src[start:end])
            for payment, invalid in (("invalid", True), ("pay_in_salon", False)):
                form = AppointmentCheckoutForm(
                    data={"coupon_code": "SAVE10", "payment_method": payment}
                )
                self.assertEqual(bool(form.errors.get("payment_method")), invalid)
                with self.subTest(path=path, payment=payment):
                    html = fragment.render({"form": form})
                    self.assertIn('role="radiogroup"', html)
                    if invalid:
                        self.assertIn('aria-invalid="true"', html)
                        self.assertIn('aria-describedby="id_payment_method_error"', html)
                    else:
                        self.assertNotIn("aria-describedby=", html)
                        self.assertNotIn('aria-invalid="true"', html)

    def test_preview_manual_coupon_widget_renders_invalid_and_valid_aria_states(self):
        src = self.source("templates/orders/reservation_preview.html")
        start = src.rfind("<input", 0, src.index("data-checkout-coupon-input"))
        end = src.index(">", src.index("data-checkout-coupon-input")) + 1
        fragment = engines["django"].from_string("{% load i18n %}" + src[start:end])
        for coupon, valid in (("INVALID" * 20, False), ("SAVE10", True)):
            form = AppointmentCheckoutForm(data={
                "coupon_code": coupon, "payment_method": "pay_in_salon",
            })
            self.assertEqual(form.is_valid(), valid)
            with self.subTest(coupon=coupon[:15]):
                html = fragment.render({"form": form, "checkout": {}})
                self.assertIn('dir="ltr"', html)
                self.assertIn('data-checkout-coupon-input', html)
                self.assertIn('aria-invalid="' + ("false" if valid else "true") + '"', html)
                if valid:
                    self.assertNotIn('aria-describedby="id_coupon_code_error"', html)
                else:
                    self.assertIn('aria-describedby="id_coupon_code_error"', html)

    def test_single_payment_radio_is_nested_in_a_real_label_and_stays_in_js_hook(self):
        src = self.source("templates/orders/reservation_preview.html")
        single = src.split(
            "{% if form.payment_method.field.choices|length == 1 %}", 1
        )[1].split("{% else %}", 1)[0]
        self.assertRegex(single, r"(?s)<label data-payment-option.*?<input type=\"radio\"")
        self.assertIn('{{ label }}', single)
        self.assertIn('checked class="sr-only"', single)
        self.assertIn("</label>", single)
        self.assertNotIn("</div>\n                {% endfor %}", single)
        js = self.source("static/js/pages/booking_checkout_submit_guard.js")
        self.assertIn('option.querySelector(\'input[type="radio"]\')', js)
        self.assertIn('option.dataset.selected = selected ? "1" : "0"', js)
        css = self.source("static/css/components/bidirectional_booking.css")
        self.assertIn('[data-payment-option]:focus-within', css)

    def test_multi_payment_radio_and_submit_contracts_are_not_changed(self):
        preview = self.source("templates/orders/reservation_preview.html")
        checkout = self.source("templates/orders/checkout.html")
        self.assertIn("{% for radio in form.payment_method %}", preview)
        self.assertIn("{% for radio in form.payment_method %}", checkout)
        self.assertIn("{{ radio.tag }}", preview)
        self.assertIn("{{ radio.tag }}", checkout)
        self.assertIn("data-checkout-payment-methods", preview)
        self.assertIn('role="radiogroup"', checkout)
        for page in (preview, checkout):
            self.assertIn('value="apply_coupon"', page)
            self.assertIn('value="clear_coupon"', page)
            self.assertIn('value="confirm_checkout"', page)

    def test_coupon_codes_are_isolated_without_reversing_currency_or_amounts(self):
        css = self.source("static/css/components/bidirectional_booking.css")
        self.assertIn("[data-booking-coupon-token]", css)
        self.assertIn("unicode-bidi: isolate;", css)
        for path in self.FINANCIAL_TEMPLATES:
            src = self.source(path)
            with self.subTest(path=path):
                self.assertIn('<bdi dir="ltr" data-booking-coupon-token>', src)
                self.assertIn("</bdi>", src)
                if path in self.CHECKOUT_TEMPLATES:
                    self.assertIn("{% trans 'toman' %}", src)
                else:
                    self.assertIn("{% trans 'toman' %}", src)
                    with translation.override("fa"):
                        self.assertEqual(translation.gettext("toman"), "تومان")
                self.assertNotIn('dir="rtl" data-booking-coupon-token', src)

    def test_booking_direction_guards_are_separate_from_locale_and_payment_logic(self):
        root = self.source("templates/base.html")
        self.assertIn('deployment_locale.language_code', root)
        self.assertIn('deployment_locale.direction', root)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        css = self.source("static/css/components/bidirectional_booking.css")
        self.assertNotIn("input[type=\"tel\"]", css)
        self.assertNotIn("input[type=\"number\"]", css)
        self.assertNotIn("data-checkout-final-submit", css)
