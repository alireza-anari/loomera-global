"""Phase 3.35 — database-free quick-link native locale and token safety checks."""
import json
import struct
from pathlib import Path

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.utils import translation


class QuickBookingLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def tearDown(self):
        translation.deactivate_all()

    def test_39_reviewed_messages_compile_in_three_locales(self):
        ledger = json.loads(self.source("docs/globalization/PHASE3_35_MESSAGE_REVIEW.json"))
        self.assertEqual(ledger["phase"], "3.35")
        rows = ledger["message_rows"]
        self.assertEqual(len(rows), 39)
        self.assertEqual(len({row["en"] for row in rows}), 39)
        for lang in ("fa", "en", "ar"):
            po = self.source(f"locale/{lang}/LC_MESSAGES/django.po")
            mo = (Path(settings.BASE_DIR) / f"locale/{lang}/LC_MESSAGES/django.mo").read_bytes()
            self.assertEqual(struct.unpack_from("<I", mo)[0], 0x950412de)
            self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 553)
            with translation.override(lang):
                for row in rows:
                    msgid, value = row["en"], row[lang]
                    self.assertEqual(po.count("msgid " + json.dumps(msgid, ensure_ascii=False) + "\n"), 1, msgid)
                    self.assertTrue(value)
                    self.assertNotIn("<", value)
                    self.assertNotIn(">", value)
                    self.assertEqual(translation.gettext(msgid), value, msgid)

    def test_templates_compile_and_keep_user_selection_contract(self):
        invalid = self.source("templates/orders/quick_link_invalid.html")
        select = self.source("templates/orders/quick_link_stylist_services.html")
        for name in ("orders/quick_link_invalid.html", "orders/quick_link_stylist_services.html"):
            with self.subTest(template=name):
                self.assertIsNotNone(get_template(name))
        self.assertIn("{% trans 'Quick booking link unavailable' %}", invalid)
        self.assertIn("message|default:quick_link_default_message", invalid)
        self.assertIn("data-empty-service-error=", select)
        self.assertIn("form.dataset.emptyServiceError", select)
        self.assertNotIn('window.LoomeraFeedback?.error?.("حداقل', select)
        for token in ('name="salon_id"', 'name="stylist_id"', 'name="selected_services"',
                      'event.preventDefault()', 'form="quickStylistServicesForm"'):
            self.assertIn(token, select)
        self.assertNotIn('<bdi dir="auto"><bdi', select)
        self.assertEqual(select.count("data-booking-back-icon"), 2)
        self.assertEqual(select.count("data-quick-link-forward-icon"), 3)
        self.assertIn('html[dir="ltr"] [data-quick-link-forward-icon]',
                      self.source("static/css/components/bidirectional_booking.css"))

    def test_fixed_server_errors_gettext_and_token_state_are_preserved(self):
        source = self.source("apps/orders/views.py")
        begin = source.index("class BookingQuickLinkStylistServicesView(View):")
        end = source.index("class ReservationPreview(", begin)
        quick = source[begin:end]
        # Legacy booking flashes must remain exact Persian allowlisted IDs.
        # Their fa/en/ar presentation already flows through clean_ui_message;
        # replacing these with new English gettext IDs would fall back to a
        # generic banner and break the historical fail-closed allowlist.
        for msgid in ("متخصص انتخاب‌شده معتبر نیست.",
                      "سالن مربوط به این لینک فعال نیست یا در دسترس نیست.",
                      "برای این متخصص در این مجموعه خدمت فعالی پیدا نشد.",
                      "خدمت انتخاب‌شده برای این متخصص معتبر نیست."):
            self.assertIn(json.dumps(msgid, ensure_ascii=False), quick)
        for msgid in ("Select at least one service for this professional.",
                      "This quick booking link is incomplete.",
                      "This quick booking link is invalid."):
            self.assertIn('_(' + json.dumps(msgid) + ')', quick)
        from apps.main.templatetags.ui_message_extras import clean_ui_message
        with translation.override("en"):
            self.assertEqual(
                clean_ui_message("سالن مربوط به این لینک فعال نیست یا در دسترس نیست.", "error"),
                "The salon for this link is inactive or unavailable.",
            )
        with translation.override("ar"):
            self.assertEqual(
                clean_ui_message("خدمت انتخاب‌شده برای این متخصص معتبر نیست.", "error"),
                "الخدمة المحددة غير صالحة لهذا المتخصص.",
            )
        for contract in ("resolve_booking_quick_link_token(token)",
                         "_quick_booking_parse_service_ids(", "status=410",
                         '"salon_id"', '"stylist_selections"', '"datetime_selections"'):
            self.assertIn(contract, quick)
        self.assertIn("_('minutes')", quick)
        self.assertIn("_('toman')", quick)

    def test_exit_matrix_still_requires_manual_acceptance(self):
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["production_deployment"], "NOT_PERFORMED")
        self.assertEqual(matrix["manual_evidence"], [])
        self.assertEqual(len(matrix["open_gates"]), 5)
