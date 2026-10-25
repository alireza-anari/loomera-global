"""Phase 3.39: Chromium cross-step browser fixture using real booking JS transport.

Unlike isolated single-widget tests, this executes the real selection handlers
and real calendar step switcher and form serializer in one page. The booking
payload never reaches a server; no live Django rendering, auth, availability
API, payment gateway, order creation, screen reader or manual release signoff.
"""
from gettext import translation as gettext_translation
import html
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STAFF = (ROOT / "static/js/select_stylist.js").read_text(encoding="utf-8")
DATES = (ROOT / "static/js/select_datetime.js").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates/orders/select_stylists.html").read_text(encoding="utf-8")


def between(content, start, end):
    a = content.find(start)
    b = content.find(end, a + len(start))
    if a < 0 or b <= a:
        raise AssertionError(f"Production JS block not found: {start}")
    return content[a:b]


AMOUNT_PARSER = between(STAFF, "    function parseAmount(value) {",
                        "    function formatAmount(value) {")
STYLIST_FUNCTIONS = between(
    STAFF, "    function buildSelectionFromButton(button) {",
    "    function updateSelectionUI(selectedButton) {"
)
DATE_HELPERS = between(
    DATES, "  function escapeBookingHtml(value) {", "  function loadDataFromPage() {"
)
SWITCHER = between(DATES, "  function renderServiceSwitcher() {",
                   "  function renderStepContent(selection, existing) {")
SUBMIT = between(DATES, "  function submitBooking() {",
                 "  function formatDate(dateObject) {")
assert 'data-stylist-name="{% trans \'First available professional\' %}"' in TEMPLATE
assert 'blocktrans with service=' in TEMPLATE
assert 'blocktrans with professional=' in TEMPLATE


def run_one(browser, language, width):
    catalog = gettext_translation(
        "django", localedir=str(ROOT / "locale"), languages=[language]
    )
    display_name = catalog.gettext("First available professional")
    service_name = 'Hair <img src=x onerror=alert(1)> & مریم'
    label = catalog.gettext("Choose first available professional for %(service)s") % {
        "service": service_name,
    }
    page = browser.new_page(viewport={"width": width, "height": 800})
    try:
        page.set_content(f"""<!doctype html><html lang="{language}"
          dir="{'ltr' if language == 'en' else 'rtl'}"><head>
          <meta name="viewport" content="width=device-width,initial-scale=1">
          <style>*{{box-sizing:border-box}}body{{margin:0;font:16px Arial}}
          main{{max-width:100%;padding:1rem}}button{{font:inherit}}</style></head>
          <body><main>
          <button type="button" class="stylist-option" id="choose-any"
            data-service-id="15" data-service-name="{html.escape(service_name,quote=True)}"
            data-service-duration="45" data-stylist-id="any"
            data-stylist-name="{html.escape(display_name,quote=True)}"
            data-stylist-price="400000" aria-pressed="false"
            aria-label="{html.escape(label,quote=True)}"> {html.escape(display_name)}</button>
          <div id="serviceSwitcher" role="group"></div>
          <form id="dateTimeSelectionForm"><input id="bookingDataInput" name="booking_data"></form>
          <button id="later">Next</button></main></body></html>""")
        page.add_script_tag(content="""
          window.state={services:{},selections:[],picked:{},currentIndex:0,salonId:27};
          window.updateSelectionUI=()=>{window.selectionUiUpdated=true};
          window.updateContinueButton=()=>{window.continueUpdated=true};
          window.LoomeraI18n={text:(key,fallback)=>({
            'booking.service':'Service',
            'booking.awaiting_time':'Awaiting time'
          }[key]||fallback)};
          window.getSelectionKey=selection=>selection.serviceId;
          window.formatGregorianToJalali=()=> '۱۴۰۵/۰۸/۱۲';
          window.formatDuration=()=> '45 minutes';
          window.getDefaultDateForCurrentStep=()=> '2026-11-03';
          window.getPickedForIndex=()=> null;
          window.renderCurrentStep=()=>Promise.resolve();
        """ + "\n" + AMOUNT_PARSER + "\n" + STYLIST_FUNCTIONS + "\n" + DATE_HELPERS
            + "\n" + SWITCHER + "\n" + SUBMIT + """
          document.querySelector('#choose-any').addEventListener('click',handleStylistSelection);
          document.querySelector('#dateTimeSelectionForm').submit=()=>{window.bookingSubmitted=true};
        """)
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.id") == "choose-any"
        page.keyboard.press("Enter")
        picked = page.evaluate("window.state.services['15']")
        assert picked["requestedStylistId"] == "any"
        assert picked["stylistName"] == display_name, (language, picked)
        assert picked["serviceName"] == service_name
        assert page.evaluate("window.continueUpdated") is True

        page.evaluate("""() => {
          const selection=window.state.services['15'];
          window.state.selections=[selection];
          window.state.picked={'15':{
            date:'2026-11-03',time:'10:00',end_time:'10:45',
            stylistName:'SARA & <img src=x onerror=1>',stylistId:'41'}};
          renderServiceSwitcher();
        }""")
        label_text = page.locator("#serviceSwitcher [data-booking-service-name]").inner_text()
        assert label_text == service_name
        assert page.locator("#serviceSwitcher img").count() == 0
        assert page.locator("#serviceSwitcher button").get_attribute("aria-current") == "step"
        page.evaluate("submitBooking()")
        outgoing = page.evaluate("JSON.parse(document.getElementById('bookingDataInput').value)")
        assert outgoing["salon_id"] == 27
        assert outgoing["stylist_selections"][0]["requestedStylistId"] == "any"
        assert outgoing["stylist_selections"][0]["stylistName"] == display_name
        assert outgoing["stylist_selections"][0]["serviceName"] == service_name
        assert outgoing["datetime_selections"]["15"]["time"] == "10:00"
        assert page.evaluate("window.bookingSubmitted") is True
        assert page.locator("img").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    except Exception:
        path = ROOT / "artifacts/phase3-browser"
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(path / f"handoff-{language}-{width}.png"), full_page=True
        )
        raise
    finally:
        page.close()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for language in ("fa", "en", "ar"):
                for width in (360, 768, 1440):
                    run_one(browser, language, width)
                    print(f"PASS Chromium booking handoff {language}/{width}")
        finally:
            browser.close()
    print("9 cross-step browser fixtures passed; no live authenticated booking/financial action")


if __name__ == "__main__":
    main()
