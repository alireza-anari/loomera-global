"""Phase 3.34: real Chromium smoke of the production booking time-slot renderer.

Runs JavaScript extracted from static/js/select_datetime.js in an actual browser
engine, with an intentionally isolated (non-server) fixture for availability.
This is NOT end-to-end payment/booking, real zoom, or screen-reader sign-off.
"""
from pathlib import Path
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "static/js/select_datetime.js").read_text(encoding="utf-8")
SHELL = (ROOT / "templates/base.html").read_text(encoding="utf-8")
DATE_TEMPLATE = (ROOT / "templates/orders/select_datetime.html").read_text(encoding="utf-8")


def between(source, start, end):
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j <= i:
        raise AssertionError(f"Cannot isolate real production JS: {start}")
    return source[i:j]


HELPERS = between(SCRIPT, "  function escapeBookingHtml(value) {", "  function loadDataFromPage() {")
DIGITS = between(SCRIPT, "  function toPersianDigits(value) {", "  function normalizeDigits(value) {")
RENDERER = between(SCRIPT, "  function renderTimeSlots(", "  function updateContinueButton() {")

viewport = re.search(r'<meta name="viewport"\s+content="([^"]+)"', SHELL)
assert viewport, "Production viewport tag was not found"
assert "maximum-scale" not in viewport.group(1).lower(), "Mobile user zoom is blocked"
assert "user-scalable=no" not in viewport.group(1).lower(), "Mobile user zoom is blocked"
assert 'id="serviceSwitcher"' in DATE_TEMPLATE
assert 'role="group" aria-label="{% trans \'Selected services\' %}"' in DATE_TEMPLATE

translations = {
    "fa": {"available_times": "ساعت‌های قابل رزرو", "selected": "انتخاب‌شده", "times": "زمان", "morning": "صبح"},
    "en": {"available_times": "Available appointment times", "selected": "Selected", "times": "times", "morning": "Morning"},
    "ar": {"available_times": "الأوقات المتاحة للحجز", "selected": "تم الاختيار", "times": "أوقات", "morning": "الصباح"},
}

PRELUDE = """
window.state = {currentIndex: 0, currentTime: null};
window.updated = 0;
window.updateContinueButton = () => { window.updated += 1; };
window.getPickedForIndex = () => null;
window.groupSlotsByPeriod = (slots) => [{
    key: 'morning', icon: 'fa-sun',
    label: window.LoomeraI18n.text('booking.morning', 'صبح'),
    slots,
}];
window.bookingSlots = [
  {time:'09:00', end_time:'09:45', stylistName:'O\\'Reilly <img src=x onerror=alert(1)> & سارا'},
  {time:'10:00', end_time:'10:45', stylistName:'A&B <svg/onload=alert(1)>'},
];
"""


def run_one(browser, language, viewport_width):
    direction = "ltr" if language == "en" else "rtl"
    page = browser.new_page(viewport={"width": viewport_width, "height": 800})
    try:
        page.set_content(
            '<!doctype html><html lang="' + language + '" dir="' + direction + '">'
            '<head><meta name="viewport" content="' + viewport.group(1) + '"></head>'
            '<body><main style="max-width:100%;margin:0 auto">'
            '<div id="serviceSwitcher" role="group" aria-label="Selected services"></div>'
            '<div id="times"></div><button id="later">Next</button>'
            '</main></body></html>'
        )
        page.evaluate(
            """(value) => {window.LoomeraI18n = {
              text: (key, fallback) => value[key.replace(/^booking\\./, '')] || fallback
            };}""",
            translations[language],
        )
        page.add_script_tag(
            content=PRELUDE + "\n" + HELPERS + "\n" + DIGITS + "\n" +
            RENDERER + "\nwindow.renderBookingSlotsForSmoke = renderTimeSlots;\n"
        )
        page.evaluate(
            "() => window.renderBookingSlotsForSmoke(window.bookingSlots, {requestedStylistId:'any'}, false)"
        )

        slots = page.locator('[data-time-slot]')
        assert slots.count() == 2, (language, viewport_width)
        assert page.locator("img").count() == 0, "Name injection executed as markup"
        assert page.locator("svg").count() == 0, "Malicious specialist SVG became markup"

        group = page.get_by_role("group", name=translations[language]["available_times"])
        assert group.count() == 1, "The time-slot group has no localized accessible name"
        assert slots.nth(0).get_attribute("aria-pressed") == "false"
        assert "O'Reilly <img" in slots.nth(0).get_attribute("aria-label")
        assert "09:00 – 09:45" in slots.nth(0).get_attribute("aria-label")
        assert slots.nth(0).locator('span[dir="ltr"]').count() == 1

        # Actual keyboard navigation (Tab -> Enter -> Tab -> Space) must
        # continue to work after each full innerHTML replacement.
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.dataset.time") == "09:00"
        page.keyboard.press("Enter")
        assert page.evaluate("document.activeElement.dataset.time") == "09:00"
        assert slots.nth(0).get_attribute("aria-pressed") == "true"
        assert page.evaluate("window.state.currentTime") == "09:00"

        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.dataset.time") == "10:00"
        page.keyboard.press("Space")
        assert page.evaluate("document.activeElement.dataset.time") == "10:00"
        assert slots.nth(1).get_attribute("aria-pressed") == "true"
        assert slots.nth(0).get_attribute("aria-pressed") == "false"
        assert page.evaluate("window.state.currentTime") == "10:00"
        assert page.evaluate("window.updated") == 2
        assert page.evaluate("document.documentElement.dir") == direction

        digit_result = page.evaluate("toPersianDigits('1234567890')")
        expected = {
            "fa": "۱۲۳۴۵۶۷۸۹۰",
            "en": "1234567890",
            "ar": "١٢٣٤٥٦٧٨٩٠",
        }[language]
        assert digit_result == expected, (language, digit_result)
    except Exception:
        folder = ROOT / "artifacts" / "phase3-browser"
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / f"{language}-{viewport_width}.png"), full_page=True)
        raise
    finally:
        page.close()


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for language in ("fa", "en", "ar"):
                for width in (360, 768, 1440):
                    run_one(browser, language, width)
                    print(f"PASS Chromium renderer keyboard/focus {language}/{width}")
        finally:
            browser.close()
    print("9 browser scenarios passed: production renderer functions, not full journey or screen-reader acceptance")


if __name__ == "__main__":
    main()
