"""Phase 3.40 — checkout/preview mixed-direction user data at actual Django sinks.

Tests real template fragments with Django autoescaping and checks that native
booking/coupon/payment form contracts remain unchanged. No DB/gateway writes,
manual accessibility or authenticated browser acceptance are claimed.
"""
from pathlib import Path
from django.conf import settings
from django.template import engines
from django.test import SimpleTestCase
from django.utils import translation


class CheckoutHumanDirectionTests(SimpleTestCase):
    PAGES = ("templates/orders/checkout.html", "templates/orders/reservation_preview.html")
    HUMAN_KEYS = (
        "checkout.salon.salon_name", "checkout.salon.address",
        "detail.service.service_name", "detail.stylist.user.get_fullName",
        "checkout.booking_policy.title", "checkout.booking_policy.description",
        "checkout.booking_policy.hint",
    )
    DATE_KEYS = ("day.date", "detail.date", "checkout.overall_date_label",
                 "checkout.overall_time_label")
    TIME_KEYS = ("day.start", "day.end", "detail.time", "detail.end_time")

    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @staticmethod
    def token_fragment(source, key, direction, marker):
        token = "{{ " + key + " }}"
        tag = f'<bdi dir="{direction}" {marker}>' + token + "</bdi>"
        if tag not in source:
            raise AssertionError(f"Checkout BDI boundary missing: {key}")
        return tag

    def tearDown(self):
        translation.deactivate_all()

    def test_all_customer_names_and_policy_text_are_isolated(self):
        for path in self.PAGES:
            source = self.source(path)
            for key in self.HUMAN_KEYS:
                with self.subTest(path=path, key=key):
                    fragment = self.token_fragment(
                        source, key, "auto", "data-checkout-human-label")
                    self.assertIn(fragment, source)
            self.assertGreaterEqual(source.count("data-checkout-human-label"), 8)
            self.assertIn('data-checkout-step=', source)

    def test_booking_dates_and_clock_tokens_have_stable_isolation(self):
        for path in self.PAGES:
            source = self.source(path)
            for key in self.DATE_KEYS:
                with self.subTest(path=path, key=key):
                    self.token_fragment(
                        source, key, "auto",
                        "data-checkout-date-time-summary" if key.startswith("checkout.") else "data-checkout-date-token",
                    )
            for key in self.TIME_KEYS:
                with self.subTest(path=path, key=key):
                    self.token_fragment(source, key, "ltr", "data-checkout-time-token")
            self.assertIn("{{ detail.time }}", source)
            self.assertIn("{{ detail.end_time }}", source)

    def test_real_django_fragments_automatically_escape_untrusted_values(self):
        data = {
            "checkout": {
                "salon": {
                    "salon_name": "استودیو O'Reilly & <img src=x onerror=1>",
                    "address": 'Berlin <svg/onload=1> & تهران',
                },
                "booking_policy": {
                    "title": 'Rules <img src=x onerror=1> & شرایط',
                    "description": 'An O\'Reilly "agreement" & <script>alert(1)</script>',
                    "hint": 'زمان • <b>no markup</b> & instructions',
                },
                "overall_date_label": "۱۴۰۵/۰۸/۱۲",
                "overall_time_label": "09:30 – 10:15",
            },
            "detail": {
                "service": {"service_name": "Cut & Color <svg/onload=1> مریم"},
                "stylist": {"user": {"get_fullName": "Sara O'Reilly & <img src=x>"}},
                "date": "۱۴۰۵/۰۸/۱۲", "time": "09:30", "end_time": "10:15",
            },
            "day": {"date": "۱۴۰۵/۰۸/۱۲", "start": "09:30", "end": "10:15"},
        }
        from django.template.base import Variable
        for path in self.PAGES:
            source = self.source(path)
            for key in (*self.HUMAN_KEYS, *self.DATE_KEYS, *self.TIME_KEYS):
                direction = "ltr" if key in self.TIME_KEYS else "auto"
                marker = (
                    "data-checkout-human-label" if key in self.HUMAN_KEYS
                    else "data-checkout-time-token" if key in self.TIME_KEYS
                    else "data-checkout-date-time-summary" if key.startswith("checkout.")
                    else "data-checkout-date-token"
                )
                fragment = self.token_fragment(source, key, direction, marker)
                expected = Variable(key).resolve(data)
                for lang in ("fa", "en", "ar"):
                    with self.subTest(page=path, key=key, lang=lang), translation.override(lang):
                        rendered = engines["django"].from_string(fragment).render(data)
                        self.assertIn(f'dir="{direction}"', rendered)
                        self.assertIn("data-checkout-", rendered)
                        if "<" in str(expected):
                            self.assertNotIn("<script", rendered)
                            self.assertNotIn("<img ", rendered)
                            self.assertNotIn("<svg/", rendered)
                            self.assertNotIn("<b>no markup", rendered)
                            self.assertIn("&lt;", rendered)
                        if "&" in str(expected):
                            self.assertIn("&amp;", rendered)
                        self.assertIn("</bdi>", rendered)

    def test_preview_and_checkout_keep_identical_user_data_fields(self):
        checkout, preview = map(self.source, self.PAGES)
        for key in (*self.HUMAN_KEYS, *self.DATE_KEYS, *self.TIME_KEYS):
            token = "{{ " + key + " }}"
            self.assertIn(token, checkout)
            self.assertIn(token, preview)
        for source in (checkout, preview):
            for marker in (
                'id="appointment-checkout-form"',
                "data-checkout-guard-form",
                'value="confirm_checkout"',
                'value="apply_coupon"',
                'value="clear_coupon"',
                "data-checkout-payment-methods",
                "data-checkout-final-submit",
            ):
                self.assertIn(marker, source)
        self.assertIn('name="form_action"', checkout)
        self.assertIn('name="form_action"', preview)

    def test_checkout_result_uses_separate_machine_identifier_and_human_labels(self):
        result = self.source("templates/payments/appointment_result.html")
        self.assertIn('dir="ltr" data-payment-machine-id', result)
        self.assertIn('dir="auto" data-payment-human-label', result)
        self.assertIn('data-payment-result-hero', result)
        self.assertIn('aria-live="polite"', result)
        self.assertIn('role="status"', result)

    def test_historical_defaults_and_manual_release_blockers_still_hold(self):
        import json
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["manual_evidence"], [])
        self.assertIn("screen_reader_acceptance", matrix["open_gates"])
        self.assertIn("release_deployment_approval", matrix["open_gates"])
