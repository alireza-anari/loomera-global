"""Phase 3.36 — post-booking payment/appointment native gettext coverage.

These are database-free template and compiled-catalog guards. They do not
make real payments or count as browser, keyboard or screen-reader acceptance.
"""
import json
from pathlib import Path
import re
import struct

from django.conf import settings
from django.template import Context, Engine
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.utils import translation


class PostBookingTailLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @classmethod
    def ledger(cls):
        return json.loads(cls.source("docs/globalization/PHASE3_36_MESSAGE_REVIEW.json"))

    def tearDown(self):
        translation.deactivate_all()

    def test_47_reviewed_messages_match_compiled_gettext_for_all_languages(self):
        payload = self.ledger()
        self.assertEqual(payload["phase"], "3.36")
        self.assertEqual(payload["reused_existing_msgids"], ["Manage appointment"])
        rows = payload["message_rows"]
        self.assertEqual(len(rows), 47)
        self.assertEqual(len({row["en"] for row in rows}), 47)
        marker = "#: templates/payments/appointment_result.html templates/orders/appointment_detail.html"
        for lang in ("fa", "en", "ar"):
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            po = (folder / "django.po").read_text(encoding="utf-8")
            mo = (folder / "django.mo").read_bytes()
            self.assertEqual(struct.unpack_from("<I", mo)[0], 0x950412de)
            self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 601)
            self.assertEqual(po.count(marker), 47)
            with translation.override(lang):
                for row in rows:
                    en, value = row["en"], row[lang]
                    self.assertEqual(set(row), {"en", "fa", "ar"})
                    self.assertEqual(
                        po.count("msgid " + json.dumps(en, ensure_ascii=False) + "\n"),
                        1, en,
                    )
                    self.assertTrue(value)
                    self.assertEqual(translation.gettext(en), value)
                    self.assertNotIn("<", value)
                    self.assertNotIn(">", value)
                    self.assertEqual(
                        re.findall(r"%\(([^)]+)\)s", en),
                        re.findall(r"%\(([^)]+)\)s", value),
                    )
                    if lang == "en":
                        self.assertEqual(en, value)
                    else:
                        self.assertNotEqual(en, value)

    def test_payment_result_compiles_and_keeps_all_financial_outcome_guards(self):
        get_template("payments/appointment_result.html")
        src = self.source("templates/payments/appointment_result.html")
        for token in (
            "is_success", "is_payment_pending_review", "is_expired_checkout",
            "is_cancelled", "is_pay_in_salon_followup",
            "pay_in_salon_online_failed", "order.id", "data-payment-machine-id",
            "data-payment-human-label", "data-payment-result-hero",
            "role=\"status\"", "role=\"alert\"",
            "item.service.service_name|default:generic_service_name",
        ):
            self.assertIn(token, src)
        for msgid in (
            "Your appointment is ready for follow-up.",
            "Payment is under review.",
            "The payment window has expired.",
            "To avoid a duplicate payment, follow up on this transaction and do not pay again until its final status is known.",
            "Payment was not confirmed. If an amount was deducted, contact support.",
            "View appointments",
            "Follow up with support",
        ):
            self.assertIn("{% trans '" + msgid + "' %}", src)
        self.assertIn("?topic=پیگیری وضعیت پرداخت", src)
        self.assertIn("?topic=پیگیری پرداخت ناموفق", src)

    def test_appointment_details_compile_without_mutating_actions(self):
        get_template("orders/appointment_detail.html")
        src = self.source("templates/orders/appointment_detail.html")
        for token in (
            "role=\"dialog\"", "data-review-rating", 'name="score"',
            'name="comment_text"', "data-payment-machine-id",
            "href=\"tel:{{ appointment.salon.phone_number }}\"",
            "window.openNavigation = function ()", "navigator.clipboard.writeText(destination)",
            "window.LoomeraFeedback?.info?.(NAVIGATION_COPIED_NOTICE);",
            "navigation_copied_message|escapejs",
            "appointment.service.service_name|default:generic_service_name",
            "data-appointment-reminder",
        ):
            self.assertIn(token, src)
        for msgid in (
            "Appointment summary", "Financial summary", "Appointment transactions",
            "Salon information", "Booking number", "Close appointment management",
            "Reschedule", "Your rating", "Optional review",
        ):
            self.assertIn("{% trans '" + msgid + "' %}", src)
        self.assertIn(
            'aria-label="{% blocktrans with star=star %}Rating {{ star }} out of 5{% endblocktrans %}"',
            src,
        )
        self.assertNotIn("window.LoomeraFeedback?.info?.('برای مسیریابی", src)

    def test_star_rating_interpolates_correctly_in_fa_en_ar(self):
        template = Engine.get_default().from_string(
            '{% load i18n %}{% blocktrans with star=star %}'
            'Rating {{ star }} out of 5{% endblocktrans %}'
        )
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                for number in ("1", "5"):
                    rendered = template.render(Context({"star": number}))
                    translated = translation.gettext("Rating %(star)s out of 5")
                    self.assertEqual(rendered, translated % {"star": number})

    def test_manual_phase3_exit_remains_explicitly_blocked(self):
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["production_deployment"], "NOT_PERFORMED")
        self.assertEqual(matrix["manual_evidence"], [])
        for gate in (
            "real_browser_visual", "real_keyboard_acceptance",
            "screen_reader_acceptance", "responsive_zoom",
            "release_deployment_approval",
        ):
            self.assertIn(gate, matrix["open_gates"])
