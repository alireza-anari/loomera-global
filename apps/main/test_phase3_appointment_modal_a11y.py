"""Phase 3.37 — appointment modal keyboard/focus regression guards."""
from pathlib import Path

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
        self.assertEqual(source.count("data-modal-initial-focus"), 2)
        self.assertIn('aria-hidden="true" tabindex="-1" data-modal-backdrop', source)
        self.assertIn('aria-pressed="false"', source)

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
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, source)

    def test_phase337_browser_smoke_is_wired_into_ci_and_exit_matrix(self):
        workflow = self.read(".github/workflows/ci.yml")
        self.assertIn("apps.main.test_phase3_appointment_modal_a11y", workflow)
        self.assertIn("python tests/browser/phase3_post_booking_chromium.py", workflow)
        matrix = __import__("json").loads(
            self.read("docs/globalization/PHASE3_EXIT_MATRIX.json")
        )
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
