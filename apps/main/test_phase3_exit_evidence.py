"""Phase 3 exit evidence and CI de-duplication contract.

These are structural audits. A green test must not be interpreted as
browser, screen-reader, visual or production deployment acceptance.
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Phase3ExitEvidenceTests(SimpleTestCase):
    @staticmethod
    def read(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @classmethod
    def matrix(cls):
        return json.loads(cls.read("docs/globalization/PHASE3_EXIT_MATRIX.json"))

    def test_all_end_to_end_journeys_have_real_automated_sources(self):
        matrix = self.matrix()
        self.assertEqual(matrix["schema_version"], 1)
        scenarios = matrix["manual_scenarios"]
        self.assertEqual(len(scenarios), 8)
        self.assertEqual(len({row["area"] for row in scenarios}), 8)
        for row in scenarios:
            with self.subTest(area=row["area"]):
                self.assertTrue(row["pages"])
                self.assertTrue(row["checks"])
                self.assertTrue(row["automated"])
                for test_file in row["automated"]:
                    self.assertTrue(
                        (Path(settings.BASE_DIR) / test_file).is_file(), test_file
                    )

    def test_every_required_locale_and_manual_viewport_is_recorded(self):
        matrix = self.matrix()
        self.assertEqual(
            [(entry["language"], entry["direction"]) for entry in
             matrix["required_locales"]],
            [("fa", "rtl"), ("en", "ltr"), ("ar", "rtl")],
        )
        self.assertEqual(matrix["manual_viewports"],
                         ["360x800", "768x1024", "1440x900"])
        evidence = matrix["evidence_required"]
        self.assertIn("pass_fail", evidence["per_scenario"])
        self.assertIn("screen_reader_if_applicable", evidence["per_scenario"])
        self.assertIn("screenshot_or_recording_reference", evidence["per_scenario"])
        self.assertIn("WebKit/Safari", evidence["browser_targets"])
        self.assertGreaterEqual(len(evidence["signoff_requires"]), 4)

    def test_no_unearned_manual_or_deployment_acceptance(self):
        matrix = self.matrix()
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["production_deployment"], "NOT_PERFORMED")
        self.assertEqual(matrix["source_repository"], "READ_ONLY")
        self.assertEqual(matrix["manual_evidence"], [])
        for gate in ("real_browser_visual", "real_keyboard_acceptance",
                     "screen_reader_acceptance", "responsive_zoom",
                     "release_deployment_approval"):
            self.assertIn(gate, matrix["open_gates"])
        audit = self.read("docs/globalization/PHASE3_EXIT_AUDIT.md")
        self.assertIn("NOT EXITED", audit)
        self.assertIn("not Phase 3 exit", audit)
        self.assertIn("No automatic merge", audit)

    def test_existing_booking_guards_run_once_in_consolidated_ci(self):
        workflow = self.read(".github/workflows/ci.yml")
        for module in (
            "test_phase3_booking_flash_locale",
            "test_phase3_rebooking_locale_flow",
            "test_phase3_booking_gettext_migration",
            "test_phase3_booking_bidirectional_accessibility",
        ):
            with self.subTest(module=module):
                self.assertEqual(workflow.count("apps.main." + module), 1)
        self.assertIn("node --check static/js/select_stylist.js", workflow)
        self.assertIn("node --check static/js/select_datetime.js", workflow)
        self.assertIn(
            "node --test tests/js/phase3_booking_journey_runtime.test.cjs",
            workflow,
        )
        self.assertIn("apps.main.test_phase3_exit_evidence", workflow)

    def test_revised_datetime_markup_escapes_one_time_only(self):
        source = self.read("static/js/select_datetime.js")
        self.assertIn("escapeBookingHtml(subtitle || 'در انتظار زمان')", source)
        self.assertIn(
            "const subtitle = picked ? `${formatGregorianToJalali(picked.date)} • ${picked.time}`",
            source,
        )
        self.assertIn(
            "${formatGregorianToJalali(picked.date)}، ${picked.time}",
            source,
        )
        self.assertIn("escapeBookingHtml(summary.pickedLabel)", source)
        self.assertIn('role="group" aria-label="ساعت‌های آزاد"', source)

    def test_previously_approved_fa_legacy_contracts_remain(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        order = self.read("apps/orders/views.py")
        self.assertIn("transaction.atomic(", order)
        self.assertIn("payment.mark_success(", order)
        self.assertIn("resolve_booking_sequence(", order)
