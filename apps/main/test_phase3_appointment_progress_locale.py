"""Phase 3.33: multilingual appointment progress and reminder-state copy.

Database-free regression guards keep booking-state decisions and Jalali
formatting intact while translating fixed customer-facing lifecycle text.
"""
import json
from datetime import datetime
from pathlib import Path
import re
import struct
from types import SimpleNamespace

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.utils import timezone, translation

from apps.dashboards.jalali_utils import format_jalali_with_weekday, format_time_fa
from apps.orders.lifecycle import (
    LIFECYCLE_LABELS,
    build_customer_progress_context,
    build_progress_steps,
)


class AppointmentProgressLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @staticmethod
    def order(**overrides):
        values = {
            "status": "pending",
            "register_date": None,
            "stylist_confirmed_at": None,
            "stylist_approved": False,
            "customer_arrived_at": None,
            "service_started_at": None,
            "service_completed_at": None,
            "selected_payment_method": "online",
            "is_paid": False,
            "review_requested_at": None,
            "review_completed_at": None,
            "reminder_due_at": None,
            "reminder_status": "",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    @classmethod
    def ledger(cls):
        return json.loads(cls.source("docs/globalization/PHASE3_33_MESSAGE_REVIEW.json"))

    def tearDown(self):
        translation.deactivate_all()

    def test_review_ledger_has_24_unique_messages_with_matching_placeholders(self):
        payload = self.ledger()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["phase"], "3.33")
        rows = payload["message_rows"]
        self.assertEqual(len(rows), 24)
        self.assertEqual(len({row["en"] for row in rows}), 24)
        for row in rows:
            self.assertEqual(set(row), {"en", "fa", "ar"})
            self.assertEqual(
                sorted(re.findall(r"%\(([^)]+)\)[a-z]", row["en"])),
                sorted(re.findall(r"%\(([^)]+)\)[a-z]", row["fa"])),
            )
            self.assertEqual(
                sorted(re.findall(r"%\(([^)]+)\)[a-z]", row["en"])),
                sorted(re.findall(r"%\(([^)]+)\)[a-z]", row["ar"])),
            )
            for lang in ("en", "fa", "ar"):
                self.assertTrue(row[lang].strip())
                self.assertLess(len(row[lang]), 500)
                for forbidden in ("<", ">", "{", "}"):
                    self.assertNotIn(forbidden, row[lang])

    def test_all_reviewed_messages_match_compiled_fa_en_ar_catalogs(self):
        rows = self.ledger()["message_rows"]
        marker = "#: docs/globalization/PHASE3_33_MESSAGE_REVIEW.json"
        for lang in ("fa", "en", "ar"):
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            po = (folder / "django.po").read_text(encoding="utf-8")
            mo = (folder / "django.mo").read_bytes()
            self.assertEqual(struct.unpack_from("<I", mo, 0)[0], 0x950412de)
            self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 514)
            self.assertEqual(po.count(marker), 24)
            lines = po.splitlines()
            added = {
                json.loads(lines[index + 1][6:])
                for index, line in enumerate(lines)
                if line == marker and lines[index + 1].startswith("msgid ")
            }
            self.assertEqual(len(added), 24)
            with translation.override(lang):
                for row in rows:
                    with self.subTest(lang=lang, msgid=row["en"][:45]):
                        self.assertEqual(translation.gettext(row["en"]), row[lang])

    def test_lifecycle_labels_follow_the_active_locale_instead_of_import_locale(self):
        expected = {
            "booked": "Booking received",
            "awaiting_stylist_confirmation": "Awaiting professional confirmation",
            "stylist_confirmed": "Confirmed by professional",
            "arrived": "Customer arrived at salon",
            "in_service": "Service in progress",
            "completed": "Completed",
            "no_show": "No-show",
            "pay_in_salon_pending": "Salon payment outstanding",
            "paid": "Paid",
            "review_pending": "Ready to leave a review",
            "reviewed": "Review submitted",
            "cancelled": "Cancelled",
        }
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                for key, msgid in expected.items():
                    with self.subTest(lang=lang, stage=key):
                        self.assertEqual(str(LIFECYCLE_LABELS[key]), translation.gettext(msgid))

    def test_progress_descriptions_localize_without_changing_the_current_stage(self):
        expected_stage_labels = {
            "booked": "Booking received",
            "awaiting_stylist_confirmation": "Awaiting professional confirmation",
            "stylist_confirmed": "Confirmed by professional",
            "arrived": "Customer arrived at salon",
            "in_service": "Service in progress",
            "completed": "Completed",
            "paid": "Paid",
            "review_pending": "Ready to leave a review",
            "reviewed": "Review submitted",
        }
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                order = self.order()
                steps, current = build_progress_steps(order)
                by_key = {step["key"]: step for step in steps}
                self.assertEqual(current, "awaiting_stylist_confirmation")
                self.assertEqual(by_key["booked"]["description"], translation.gettext(
                    "Your booking request has been received."
                ))
                self.assertEqual(by_key["awaiting_stylist_confirmation"]["description"],
                    translation.gettext(
                        "After your booking is confirmed, the selected time is finalized "
                        "in the professional's schedule."
                    ))
                self.assertEqual(by_key["stylist_confirmed"]["description"],
                    translation.gettext(
                        "This appointment time is confirmed and has been added to the "
                        "professional's schedule."
                    ))
                self.assertEqual(by_key["arrived"]["description"],
                    translation.gettext("Your arrival at the salon has been recorded."))
                self.assertEqual(by_key["in_service"]["description"],
                    translation.gettext("Your service is in progress."))
                self.assertEqual(by_key["completed"]["description"],
                    translation.gettext("Your service is complete."))
                self.assertEqual(by_key["review_pending"]["description"],
                    translation.gettext("You can share your experience of this appointment."))
                self.assertEqual(by_key["reviewed"]["description"],
                    translation.gettext("Your review has been submitted."))
                for key, msgid in expected_stage_labels.items():
                    self.assertEqual(str(by_key[key]["label"]), translation.gettext(msgid))

    def test_reminder_text_tracks_scheduled_sent_and_skipped_state_even_with_old_due_time(self):
        due_at = timezone.make_aware(
            datetime(2026, 10, 27, 10, 30),
            timezone.get_current_timezone(),
        )
        local_due = timezone.localtime(due_at)
        expected_scheduled = (
            "Your appointment reminder is scheduled for %(date)s at %(time)s."
        )
        variables = {
            "date": format_jalali_with_weekday(local_due.date()),
            "time": format_time_fa(local_due.time()),
        }
        skipped_msgid = (
            "An automatic reminder could not be scheduled because the appointment "
            "was too soon or no valid time was available."
        )
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                scheduled = build_customer_progress_context(self.order(
                    reminder_due_at=due_at, reminder_status="scheduled"
                ))
                self.assertEqual(
                    scheduled["reminder_text"],
                    translation.gettext(expected_scheduled) % variables,
                )
                sent = build_customer_progress_context(self.order(
                    reminder_due_at=due_at, reminder_status="sent"
                ))
                self.assertEqual(
                    sent["reminder_text"],
                    translation.gettext("Your appointment reminder has been sent."),
                )
                skipped = build_customer_progress_context(self.order(
                    reminder_due_at=due_at, reminder_status="skipped"
                ))
                self.assertEqual(skipped["reminder_text"], translation.gettext(skipped_msgid))
                empty = build_customer_progress_context(self.order())
                self.assertEqual(empty["reminder_text"], "")

    def test_pay_at_salon_progress_copy_preserves_financial_state(self):
        completed_at = timezone.make_aware(
            datetime(2026, 10, 25, 12, 0),
            timezone.get_current_timezone(),
        )
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                order = self.order(
                    selected_payment_method="pay_in_salon",
                    service_completed_at=completed_at,
                    is_paid=False,
                )
                steps, current = build_progress_steps(order)
                by_key = {step["key"]: step for step in steps}
                self.assertEqual(current, "pay_in_salon_pending")
                self.assertFalse(by_key["pay_in_salon_pending"]["is_done"])
                self.assertEqual(
                    by_key["pay_in_salon_pending"]["description"],
                    translation.gettext("Payment for this appointment is completed at the salon."),
                )
                self.assertEqual(
                    by_key["pay_in_salon_pending"]["meta"],
                    translation.gettext("Pay at salon"),
                )

    def test_appointment_detail_renders_localized_progress_and_reminder_slots(self):
        template = self.source("templates/orders/appointment_detail.html")
        self.assertIn("{% trans 'Booking received' as booking_received_fallback %}", template)
        self.assertEqual(template.count("default:booking_received_fallback"), 2)
        self.assertEqual(template.count("data-appointment-reminder"), 2)
        self.assertEqual(template.count('{% trans "Appointment reminder" %}'), 2)
        self.assertIn(
            "The service is complete. The salon will record your in-person payment "
            "once it has been collected; you do not need to confirm it.",
            template,
        )
        for msgid in (
            "Rate and review", "Leave a review", "Services for this appointment",
            "Selected service and professional", "Payment, policies and salon information",
            "Primary payment", "Number of services", "Total duration", "More details",
            "Service details", "Pay at salon",
        ):
            self.assertIn(msgid, template)
        self.assertIn("{{ total_duration }} {% trans 'minutes' %}", template)
        self.assertIn("{{ item.display_duration_minutes }} {% trans 'minutes' %}", template)
        self.assertNotIn("خدمت انجام شده است. پس از دریافت وجه، مجموعه پرداخت حضوری را ثبت می‌کند", template)
        self.assertNotIn("ثبت امتیاز و دیدگاه", template)
        self.assertNotIn("تعداد خدمات", template)
        self.assertNotIn("مدت کل", template)
        get_template("orders/appointment_detail.html")

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
