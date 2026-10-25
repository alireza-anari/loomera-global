"""Phase 3.34: remaining appointment-detail and review-form localization.

Only fixed UI copy is translated. Salon/service/customer data, booking
identifiers, financial state and navigation behavior remain data/logic.
"""
import json
from pathlib import Path
import re
import struct

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.utils import translation


class AppointmentDetailStaticLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @classmethod
    def ledger(cls):
        return json.loads(cls.source("docs/globalization/PHASE3_34_MESSAGE_REVIEW.json"))

    def tearDown(self):
        translation.deactivate_all()

    def test_review_ledger_has_27_unique_messages_and_matching_placeholders(self):
        payload = self.ledger()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["phase"], "3.34")
        rows = payload["message_rows"]
        self.assertEqual(len(rows), 27)
        self.assertEqual(len({row["en"] for row in rows}), 27)
        for row in rows:
            self.assertEqual(set(row), {"en", "fa", "ar"})
            signature = lambda text: sorted(re.findall(r"%\(([^)]+)\)[a-z]", text))
            self.assertEqual(signature(row["en"]), signature(row["fa"]))
            self.assertEqual(signature(row["en"]), signature(row["ar"]))
            for lang in ("en", "fa", "ar"):
                self.assertTrue(row[lang].strip())
                self.assertLess(len(row[lang]), 500)
                for forbidden in ("<", ">", "{", "}"):
                    self.assertNotIn(forbidden, row[lang])

    def test_all_reviewed_messages_match_the_three_compiled_catalogs(self):
        rows = self.ledger()["message_rows"]
        marker = "#: docs/globalization/PHASE3_34_MESSAGE_REVIEW.json"
        for lang in ("fa", "en", "ar"):
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            po = (folder / "django.po").read_text(encoding="utf-8")
            mo = (folder / "django.mo").read_bytes()
            self.assertEqual(struct.unpack_from("<I", mo, 0)[0], 0x950412de)
            self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 541)
            self.assertEqual(po.count(marker), 27)
            lines = po.splitlines()
            added = {
                json.loads(lines[index + 1][6:])
                for index, line in enumerate(lines)
                if line == marker and lines[index + 1].startswith("msgid ")
            }
            self.assertEqual(len(added), 27)
            with translation.override(lang):
                for row in rows:
                    with self.subTest(lang=lang, msgid=row["en"][:45]):
                        self.assertEqual(translation.gettext(row["en"]), row[lang])

    def test_score_accessibility_label_interpolates_for_all_locales(self):
        msgid = "Rate %(score)s out of 5"
        row = next(item for item in self.ledger()["message_rows"] if item["en"] == msgid)
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                rendered = translation.gettext(msgid) % {"score": 4}
                self.assertEqual(rendered, row[lang] % {"score": 4})
                self.assertIn("4", rendered)
                self.assertNotIn("%(score)s", rendered)

    def test_appointment_detail_has_no_remaining_hardcoded_persian_ui_copy(self):
        template = self.source("templates/orders/appointment_detail.html")
        self.assertNotRegex(template, r"[آ-ی]")
        for msgid in (
            "Back to my appointments", "Appointment at a glance", "View transactions",
            "Call salon", "Add to calendar", "Appointment summary",
            "Services, professionals and time", "Time range", "Financial summary",
            "Transactions for this appointment", "Salon information",
            "Appointment summary and actions", "View salon page",
            "Close appointment management",
            "Only actions that are currently available are shown here.",
            "Change time", "Choose a new date and time", "Close", "Review",
            "Your service and professional are already selected for this appointment. "
            "Rate your experience and add a comment if you wish.",
            "Your rating", "Rate {{ score }} out of 5",
            "Select a rating to highlight all stars at that level.",
            "Optional review",
            "If you have an experience that could help others, share it here...",
            "Cancel",
        ):
            self.assertIn(msgid, template)

        self.assertIn("Appointment details", template)
        self.assertIn("Appointment date", template)
        self.assertIn("Final amount", template)
        self.assertIn("Order number", template)
        self.assertIn("Manage appointment", template)
        self.assertIn("{% trans 'Service' as service_fallback %}", template)
        self.assertIn('default:service_fallback', template)
        self.assertIn('{% blocktrans with score=star %}Rate {{ score }} out of 5{% endblocktrans %}', template)
        self.assertNotIn("</bdi> تا <bdi", template)
        get_template("orders/appointment_detail.html")

    def test_dynamic_service_salon_and_machine_data_remain_untranslated(self):
        template = self.source("templates/orders/appointment_detail.html")
        for data_binding in (
            "{{ appointment.service.service_name|default:service_fallback }}",
            "{{ appointment.stylist.get_fullName }}",
            "{{ appointment.salon.salon_name }}",
            "{{ appointment.salon.address }}",
            "{{ appointment.order.order_number|default:'---' }}",
            "{{ appointment.salon.phone_number }}",
            "data-payment-machine-id",
            "<bdi dir=\"ltr\"",
        ):
            self.assertIn(data_binding, template)
        self.assertIn("{{ item.time|persian_time }}", template)
        self.assertIn("{{ visit_date_label }}", template)
        self.assertIn("{{ visit_time_label }}", template)

    def test_navigation_fallback_uses_translated_and_escaped_message(self):
        template = self.source("templates/orders/appointment_detail.html")
        self.assertIn(
            '{% trans "To use your device\'s navigation app, open this page on your phone. '
            'The destination has been copied." as navigationFallbackMessage %}',
            template,
        )
        self.assertIn(
            'const navigationFallbackMessage = "{{ navigationFallbackMessage|escapejs }}";',
            template,
        )
        self.assertIn("window.LoomeraFeedback?.info?.(navigationFallbackMessage);", template)
        self.assertNotIn("برای مسیریابی با برنامه دستگاه", template)

    def test_navigation_and_review_controls_keep_existing_handlers(self):
        template = self.source("templates/orders/appointment_detail.html")
        for handler in (
            "onclick=\"addToCalendar()\"",
            "onclick=\"openNavigation()\"",
            "onclick=\"openManageModal()\"",
            "window.openReviewModal && window.openReviewModal()",
            "window.closeReviewModal && window.closeReviewModal()",
        ):
            self.assertIn(handler, template)
        self.assertIn('name="comment_text"', template)
        self.assertIn('name="score"', template)
        self.assertIn("{% csrf_token %}", template)

    def test_phase3_manual_acceptance_and_deployment_gates_remain_blocked(self):
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["manual_evidence"], [])
        for gate in (
            "real_browser_visual", "real_keyboard_acceptance",
            "screen_reader_acceptance", "responsive_zoom",
            "release_deployment_approval",
        ):
            self.assertIn(gate, matrix["open_gates"])
