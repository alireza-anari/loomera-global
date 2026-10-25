"""Phase 3.37 — appointment modal keyboard/focus regression guards."""
import json
from gettext import translation as load_translation
from pathlib import Path
import struct

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase


class AppointmentModalA11yTests(SimpleTestCase):
    @staticmethod
    def read(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def test_real_appointment_template_has_labeled_dialogs_and_initial_focus(self):
        get_template("orders/appointment_detail.html")
        source = self.read("templates/orders/appointment_detail.html")
        for modal_id, title_id in (
            ("manageModal", "manageModalTitle"),
            ("reviewModal", "reviewModalTitle"),
        ):
            with self.subTest(modal=modal_id):
                start = source.index('id="' + modal_id + '"')
                opening = source[source.rfind("<div ", 0, start):source.index(">", start) + 1]
                self.assertIn('role="dialog"', opening)
                self.assertIn('aria-modal="true"', opening)
                self.assertIn('aria-hidden="true"', opening)
                self.assertIn('aria-labelledby="' + title_id + '"', opening)
                self.assertIn('tabindex="-1"', opening)
        self.assertEqual(source.count('tabindex="-1" data-modal-initial-focus'), 2)
        self.assertIn('aria-hidden="true" tabindex="-1" data-modal-backdrop', source)
        self.assertIn('aria-pressed="false"', source)
        self.assertIn('aria-describedby="reviewRatingInstructions reviewRatingError"', source)

    def test_modal_controller_traps_focus_handles_escape_and_restores_opener(self):
        source = self.read("templates/orders/appointment_detail.html")
        for contract in (
            "const modalOpeners = new WeakMap();",
            "const modalStack = [];",
            "const getModalFocusable = (modal) => Array.from(",
            "const target = modal.querySelector('[data-modal-initial-focus]')",
            "event.key === 'Escape' || event.key === 'Esc'",
            "event.key !== 'Tab'",
            "const activeIndex = focusable.indexOf(document.activeElement);",
            "last.focus();",
            "first.focus();",
            "document.body.style.overflow = bodyOverflowBeforeModal;",
            "opener.focus();",
            "window.openManageModal = () => openModal(manageModal);",
            "window.openReviewModal = () => openModal(reviewModal);",
            "ratingForm?.addEventListener('submit', (event) => {",
            "ratingPicker.setAttribute('aria-invalid', 'true');",
            "if (buttons[0]) buttons[0].focus();",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, source)

    def test_missing_rating_has_reviewed_fa_en_ar_message_and_compiled_catalogs(self):
        ledger = json.loads(self.read("docs/globalization/PHASE3_37_MESSAGE_REVIEW.json"))
        self.assertEqual(ledger["phase"], "3.37")
        self.assertEqual(len(ledger["message_rows"]), 1)
        row = ledger["message_rows"][0]
        self.assertEqual(row["en"], "Please select a rating before submitting your review.")
        source = self.read("templates/orders/appointment_detail.html")
        self.assertIn("{% trans 'Please select a rating before submitting your review.' %}", source)
        view = self.read("apps/orders/views.py")
        self.assertIn('messages.error(request, _("Please select a rating before submitting your review."))', view)
        self.assertIn('score = int(request.POST.get("score") or 0)', view)
        self.assertIn("if score < 1 or score > 5:", view)
        for language in ("fa", "en", "ar"):
            with self.subTest(language=language):
                folder = Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES"
                compiled = (folder / "django.mo").read_bytes()
                self.assertEqual(struct.unpack_from("<I", compiled, 8)[0], 601)
                catalog = load_translation("django", localedir=str(Path(settings.BASE_DIR) / "locale"), languages=[language])
                self.assertEqual(catalog.gettext(row["en"]), row[language])
                self.assertTrue(row[language])

    def test_phase337_browser_smoke_is_wired_into_ci_and_exit_matrix(self):
        workflow = self.read(".github/workflows/ci.yml")
        self.assertIn("apps.main.test_phase3_appointment_modal_a11y", workflow)
        self.assertIn("python tests/browser/phase3_post_booking_chromium.py", workflow)
        matrix = json.loads(self.read("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        appointment_area = next(
            row for row in matrix["manual_scenarios"]
            if row["area"] == "Appointments and rebooking"
        )
        self.assertIn("tests/browser/phase3_post_booking_chromium.py",
                      appointment_area["automated"])
        self.assertIn("apps/main/test_phase3_appointment_modal_a11y.py",
                      appointment_area["automated"])
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["manual_evidence"], [])
