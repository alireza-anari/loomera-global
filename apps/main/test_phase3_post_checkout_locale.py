"""Phase 3.31: post-checkout payment-result and appointment journey localization.

All tests are database-free. Native gettext/PO/MO evidence and source
contracts do not substitute for real browser or assistive-technology QA.
"""
import json
from pathlib import Path
import re
import struct

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils import translation


class PostCheckoutJourneyLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @classmethod
    def rows(cls):
        source = json.loads(cls.source("docs/globalization/PHASE3_31_MESSAGE_REVIEW.json"))
        assert source["schema_version"] == 1
        return source["message_rows"]

    def tearDown(self):
        translation.deactivate_all()

    def test_all_reviewed_phrases_are_unique_and_safe_static_text(self):
        rows = self.rows()
        self.assertEqual(len(rows), 83)
        self.assertEqual(len({r["en"] for r in rows}), 83)
        for item in rows:
            with self.subTest(msgid=item["en"]):
                self.assertEqual(set(item), {"en", "fa", "ar"})
                for lang in ("en", "fa", "ar"):
                    self.assertTrue(item[lang].strip())
                    self.assertNotIn("<", item[lang])
                    self.assertNotIn(">", item[lang])
                    self.assertNotIn("{", item[lang])
                    self.assertNotIn("}", item[lang])
                    self.assertLess(len(item[lang]), 300)

    def test_76_new_native_po_entries_match_all_three_compiled_mo_catalogs(self):
        rows = self.rows()
        for lang in ("fa", "en", "ar"):
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            po = (folder / "django.po").read_text(encoding="utf-8")
            mo = (folder / "django.mo").read_bytes()
            self.assertEqual(struct.unpack_from("<I", mo, 0)[0], 0x950412de)
            self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 490)
            marker = "#: docs/globalization/PHASE3_31_MESSAGE_REVIEW.json"
            self.assertEqual(po.count(marker), 76)
            new_msgids = set()
            lines = po.splitlines()
            for i, line in enumerate(lines):
                if line == marker:
                    new_msgids.add(json.loads(lines[i + 1].removeprefix("msgid ")))
            self.assertEqual(len(new_msgids), 76)
            with translation.override(lang):
                for item in rows:
                    msgid = item["en"]
                    with self.subTest(lang=lang, msgid=msgid[:45]):
                        actual = translation.gettext(msgid)
                        self.assertTrue(actual)
                        if msgid in new_msgids:
                            self.assertEqual(actual, item[lang])
                        elif lang == "en":
                            self.assertEqual(actual, msgid)
                        else:
                            self.assertNotEqual(actual, msgid)

    def test_financial_outcome_branches_are_distinct_and_translated(self):
        source = self.source("templates/payments/appointment_result.html")
        self.assertIn("{% load jalali_extras i18n %}", source)
        for condition in (
            "is_success", "is_pay_in_salon_followup", "is_payment_pending_review",
            "is_expired_checkout", "is_cancelled", "pay_in_salon_online_failed",
        ):
            self.assertIn(condition, source)
        for msgid in (
            "Supplementary booking payment completed",
            "Your appointment is booked",
            "Payment under review",
            "Payment window expired",
            "You cancelled the payment",
            "Supplementary online payment not confirmed",
            "Your appointment remains active and the pay-at-salon method has been preserved.",
            "Payment failed",
            "Do not pay again",
        ):
            self.assertIn("{% trans '" + msgid + "' %}", source)
        # Do not claim the payment was taken in the pay-at-salon failure state.
        followup_start = source.index("{% if pay_in_salon_online_failed %}")
        failure_start = source.index("{% else %}", followup_start)
        followup = source[followup_start:failure_start]
        self.assertIn("Your appointment remains active", followup)
        self.assertNotIn("Supplementary booking payment completed", followup)
        self.assertIn('role="status"', source)
        self.assertIn('role="alert"', source)

    def test_native_template_translations_render_for_each_locale(self):
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                for message in (
                    "My appointments", "Upcoming appointments", "Payment failed",
                    "Payment under review", "Your appointment is booked",
                    "Pay at salon", "Appointment details", "Book again",
                    "Salon payment outstanding",
                ):
                    with self.subTest(lang=lang, msgid=message):
                        fragment = Template(
                            "{% load i18n %}{% trans '" + message + "' %}"
                        )
                        rendered = fragment.render(Context({}))
                        self.assertEqual(rendered, translation.gettext(message))
                        self.assertTrue(rendered)

    def test_appointments_and_components_keep_customer_actions_and_accessibility(self):
        page = self.source("templates/orders/appointments.html")
        self.assertIn("{% load static i18n %}", page)
        self.assertIn("{% trans 'My appointments' %}", page)
        self.assertIn('aria-label="{% trans \'Upcoming appointments\' %}"', page)
        self.assertIn("data-booking-back-icon", page)
        self.assertIn("clear_completed_booking_client_state", page)
        self.assertIn("sessionStorage.removeItem(key)", page)
        for path in (
            "templates/components/appointment_upcoming_card.html",
            "templates/components/appointment_past_item.html",
            "templates/components/appointments_empty_state.html",
        ):
            self.assertRegex(self.source(path), r"{% load (?:humanize )?i18n %}")
        upcoming = self.source("templates/components/appointment_upcoming_card.html")
        self.assertIn("{% trans 'Paid' %}", upcoming)
        self.assertIn("{% trans 'Pay at salon' %}", upcoming)
        self.assertIn("appointment.order.selected_payment_method == 'pay_in_salon'", upcoming)
        empty = self.source("templates/components/appointments_empty_state.html")
        self.assertIn("alt_text=no_bookings_alt", empty)
        self.assertIn("{% trans 'You have no appointments yet' %}", empty)

    def test_financial_identifiers_and_coupon_tokens_keep_correct_direction(self):
        source = self.source("templates/payments/appointment_result.html")
        for name in ("payment.ref_id", "payment.gateway_track_id", "order.order_number"):
            self.assertRegex(source, r'<bdi dir="ltr" data-payment-machine-id>[^<]*' + re.escape(name) + r"[^<]*</bdi>")
        self.assertIn('data-booking-coupon-token', source)
        self.assertIn('<bdi dir="ltr" data-booking-coupon-token>', source)
        self.assertIn("{% trans 'toman' %}", source)
        detail = self.source("templates/orders/appointment_detail.html")
        self.assertIn("{% trans 'Salon payment outstanding' %}", detail)
        self.assertIn("{% trans 'Awaiting professional confirmation' %}", detail)
        self.assertIn("{% trans 'Confirmed by professional' %}", detail)

    def test_booking_business_rules_and_manual_release_gates_stay_unchanged(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        source = self.source("apps/orders/views.py")
        self.assertIn("transaction.atomic(", source)
        self.assertIn("payment.mark_success(", source)
        self.assertIn("resolve_booking_sequence(", source)
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["manual_evidence"], [])
        self.assertIn("screen_reader_acceptance", matrix["open_gates"])
        self.assertIn("real_browser_visual", matrix["open_gates"])
        self.assertIn("release_deployment_approval", matrix["open_gates"])
