"""Phase 3.34: unlock mobile zoom and verify accessible booking controls.

Structural source checks complement (not substitute for) the separate
Chromium run against the actual production time-slot rendering functions.
"""
import json
from pathlib import Path
import re

from django.conf import settings
from django.test import SimpleTestCase


class BrowserKeyboardZoomContractTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def test_shared_viewport_does_not_disable_user_zoom(self):
        base = self.source("templates/base.html")
        match = re.search(
            r'<meta name="viewport"\s+content="([^"]+)"', base
        )
        self.assertIsNotNone(match)
        viewport = match.group(1).lower()
        self.assertIn("width=device-width", viewport)
        self.assertIn("initial-scale=1", viewport)
        self.assertIn("viewport-fit=cover", viewport)
        self.assertNotIn("maximum-scale", viewport)
        self.assertNotIn("user-scalable=no", viewport)

    def test_service_switcher_is_named_group_of_buttons_not_false_list(self):
        template = self.source("templates/orders/select_datetime.html")
        self.assertIn(
            'role="group" aria-label="{% trans \'Selected services\' %}"',
            template,
        )
        self.assertRegex(template, r'id="serviceSwitcher"[^>]*role="group"')
        self.assertIn(
            'aria-label="{% trans \'Services and professionals\' %}"',
            template,
        )
        js = self.source("static/js/select_datetime.js")
        self.assertIn('data-time-slot', js)
        self.assertIn('aria-pressed="${isSelected ? \'true\' : \'false\'}"', js)

    def test_clock_group_and_range_are_locale_safe_and_keyboard_continuous(self):
        js = self.source("static/js/select_datetime.js")
        self.assertIn(
            'aria-label="${escapeBookingHtml(bookingText(\'available_times\'', js
        )
        self.assertIn(
            "${escapeBookingHtml(slot.time)} – ${escapeBookingHtml(slot.end_time)}",
            js,
        )
        self.assertIn('<bdi dir="ltr">${escapeBookingHtml(slot.end_time)}</bdi>', js)
        self.assertIn("replacement?.focus({ preventScroll: true });", js)
        self.assertIn("candidate.dataset.time === state.currentTime", js)
        self.assertIn("escapeBookingHtml(slot.stylistName)", js)

    def test_real_browser_smoke_runs_nine_isolated_runtime_scenarios(self):
        runner = self.source("tests/browser/phase3_booking_keyboard_chromium.py")
        self.assertIn("from playwright.sync_api import sync_playwright", runner)
        self.assertIn("static/js/select_datetime.js", runner)
        self.assertIn('("fa", "en", "ar")', runner)
        self.assertIn("(360, 768, 1440)", runner)
        self.assertIn('page.keyboard.press("Enter")', runner)
        self.assertIn('page.keyboard.press("Space")', runner)
        self.assertIn('page.keyboard.press("Tab")', runner)
        self.assertIn("user-scalable=no", runner)
        self.assertIn("not full journey or screen-reader acceptance", runner)

    def test_ci_has_separate_headless_chromium_job_and_failure_evidence(self):
        workflow = self.source(".github/workflows/ci.yml")
        self.assertIn("\n  browser-smoke:\n", workflow)
        self.assertIn("playwright==1.55.0", workflow)
        self.assertIn("playwright install --with-deps chromium", workflow)
        self.assertIn(
            "python tests/browser/phase3_booking_keyboard_chromium.py",
            workflow,
        )
        self.assertIn("actions/upload-artifact@v4", workflow)

    def test_chromium_smoke_does_not_prematurely_close_manual_release(self):
        matrix = json.loads(
            self.source("docs/globalization/PHASE3_EXIT_MATRIX.json")
        )
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["manual_evidence"], [])
        for gate in (
            "real_browser_visual", "real_keyboard_acceptance",
            "screen_reader_acceptance", "responsive_zoom",
            "release_deployment_approval",
        ):
            self.assertIn(gate, matrix["open_gates"])
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
