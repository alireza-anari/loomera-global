"""Phase 3.37: Chromium smoke of production appointment modal markup and JS.

Uses the real modal fragments and modal/rating controller from the production
template, with a small fixture for missing server data. It is not a full
authenticated booking journey or screen-reader/manual release sign-off.
"""
from gettext import translation as load_translation
import html
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DETAIL = (ROOT / "templates/orders/appointment_detail.html").read_text(encoding="utf-8")


def between(source, start, end):
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j <= i:
        raise AssertionError("Could not isolate production template section")
    return source[i:j]


MODAL_JS = between(
    DETAIL,
    "  const manageModal = document.getElementById('manageModal');",
    "  window.addToCalendar = function () {",
)
MANAGE_TEMPLATE = between(
    DETAIL, "<!-- MANAGE MODAL -->", "\n{% if customer_progress.can_review %}"
)
REVIEW_TEMPLATE = between(
    DETAIL, '<div id="reviewModal"', "\n{% endif %}\n\n\n{% endblock %}"
)
TRANS_TAG = re.compile(r"""{%\s*trans\s+(['"])(.*?)\1\s*%}""", re.DOTALL)
RATING_LOOP = re.compile(
    r'{%\s*for star in "12345"\s*%}(.*?){%\s*endfor\s*%}', re.DOTALL
)
BLOCKTRANS_RATING = (
    "{% blocktrans with star=star %}Rating {{ star }} out of 5{% endblocktrans %}"
)


def get_catalog(language):
    return load_translation(
        "django", localedir=str(ROOT / "locale"), languages=[language]
    )


def translate_tags(source, catalog):
    return TRANS_TAG.sub(
        lambda match: html.escape(catalog.gettext(match.group(2)), quote=True),
        source,
    )


def build_modal_fixture(language):
    catalog = get_catalog(language)
    manage = MANAGE_TEMPLATE.replace(
        "{% url 'orders:reschedule' appointment.id %}",
        "/appointments/123/reschedule/",
    ).replace("{{ cancellation_policy.title }}", "Cancellation policy")
    manage = translate_tags(manage, catalog)

    review = REVIEW_TEMPLATE
    loop = RATING_LOOP.search(review)
    if not loop:
        raise AssertionError("Production review rating loop was not found")
    button_template = loop.group(1)
    buttons = []
    for star in "12345":
        label = catalog.gettext("Rating %(star)s out of 5") % {"star": star}
        button = button_template.replace(
            BLOCKTRANS_RATING, html.escape(label, quote=True)
        ).replace("{{ star }}", star)
        buttons.append(button)
    review = review[:loop.start()] + "".join(buttons) + review[loop.end():]
    review = review.replace(
        "{% csrf_token %}",
        '<input type="hidden" name="csrfmiddlewaretoken" value="fixture-token">',
    )
    review = review.replace(
        "{{ appointment.service.service_name|default:generic_service_name }}",
        "Haircut",
    )
    review = review.replace(
        "{% if appointment.stylist %}{{ appointment.stylist.get_fullName }}{% else %}—{% endif %}",
        "Mina",
    )
    review = translate_tags(review, catalog)

    if "{%" in manage or "{{" in manage or "{%" in review or "{{" in review:
        raise AssertionError("Fixture still contains unresolved Django template syntax")

    trigger_manage = html.escape(catalog.gettext("Manage appointment"))
    trigger_review = html.escape(catalog.gettext("Leave a review"))
    page = f"""<!doctype html>
<html lang="{language}" dir="{'ltr' if language == 'en' else 'rtl'}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ width: 100%; margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; color: #222; }}
  main {{ padding: 1rem; }}
  button, textarea {{ font: inherit; }}
  .hidden {{ display: none !important; }}
  .flex {{ display: flex; }}
  .fixed {{ position: fixed; }}
  .inset-0 {{ inset: 0; }}
  .overflow-y-auto {{ overflow-y: auto; }}
  .overflow-hidden {{ overflow: hidden; }}
  .min-h-dvh {{ min-height: 100dvh; }}
  .items-center {{ align-items: center; }}
  .justify-center {{ justify-content: center; }}
  .px-4 {{ padding-left: 1rem; padding-right: 1rem; }}
  .py-6 {{ padding-top: 1.5rem; padding-bottom: 1.5rem; }}
  .relative {{ position: relative; }}
  .w-full {{ width: 100%; }}
  .max-w-md {{ max-width: 28rem; }}
  .max-w-lg {{ max-width: 32rem; }}
  .grid {{ display: grid; }}
  .grid-cols-5 {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }}
  .gap-2 {{ gap: .5rem; }}
  .gap-3 {{ gap: .75rem; }}
  .gap-4 {{ gap: 1rem; }}
  .mt-2 {{ margin-top: .5rem; }}
  .mt-3 {{ margin-top: .75rem; }}
  .mt-6 {{ margin-top: 1.5rem; }}
  textarea {{ width: 100%; min-height: 5rem; }}
  #manageModal {{ z-index: 1200; }}
  #reviewModal {{ z-index: 80; }}
  #manageModal .relative {{ z-index: 1; }}
  #manageModal [data-modal-backdrop] {{ position: fixed; inset: 0; width: 100%; height: 100%; }}
</style>
</head>
<body>
<main>
  <button id="manage-trigger" type="button" onclick="openManageModal()">{trigger_manage}</button>
  <button id="review-trigger" type="button" onclick="openReviewModal()">{trigger_review}</button>
  <p>Appointment reference <bdi dir="ltr">LM-2031-AB</bdi></p>
</main>
{manage}
{review}
</body>
</html>"""
    return page, catalog


def focusable_count(page, modal_id):
    return page.evaluate(
        """(id) => {
          const modal = document.getElementById(id);
          return Array.from(modal.querySelectorAll(
            'a[href], button, input:not([type="hidden"]), textarea, select, [tabindex]'
          )).filter((element) => (
            !element.disabled && element.tabIndex >= 0
            && element.getClientRects().length > 0
            && getComputedStyle(element).visibility !== 'hidden'
          )).length;
        }""",
        modal_id,
    )


def run_one(browser, language, width):
    direction = "ltr" if language == "en" else "rtl"
    page = browser.new_page(viewport={"width": width, "height": 800})
    try:
        fixture, catalog = build_modal_fixture(language)
        page.set_content(fixture)
        page.add_script_tag(content=MODAL_JS)
        page.evaluate(
            """() => {
              const form = document.querySelector('#reviewModal form');
              form.addEventListener('submit', (event) => {
                window.reviewSubmitWasPrevented = event.defaultPrevented;
                event.preventDefault();
              });
            }"""
        )
        assert page.evaluate("document.documentElement.dir") == direction
        assert page.locator("#manageModal").get_attribute("aria-hidden") == "true"
        assert page.locator("#reviewModal").get_attribute("aria-hidden") == "true"

        # Management modal: title receives initial focus, Tab wraps both ways,
        # Escape closes the dialog, restores scroll and returns focus to opener.
        page.locator("#manage-trigger").click()
        assert page.locator("#manageModal").get_attribute("aria-hidden") == "false"
        assert page.evaluate("document.activeElement.id") == "manageModalTitle"
        assert page.evaluate("document.body.style.overflow") == "hidden"
        assert focusable_count(page, "manageModal") >= 3
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.activeElement.textContent.trim()") == catalog.gettext("Close")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == catalog.gettext("Close")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        page.keyboard.press("Escape")
        assert page.locator("#manageModal").get_attribute("aria-hidden") == "true"
        assert page.evaluate("document.body.style.overflow") == ""
        assert page.evaluate("document.activeElement.id") == "manage-trigger"

        # Review modal: invalid submissions are stopped and announced, and the
        # actual score field/pressed states are updated with keyboard input.
        page.locator("#review-trigger").click()
        assert page.locator("#reviewModal").get_attribute("aria-hidden") == "false"
        assert page.evaluate("document.activeElement.id") == "reviewModalTitle"
        assert page.evaluate("document.body.style.overflow") == "hidden"
        for star in "12345":
            label = catalog.gettext("Rating %(star)s out of 5") % {"star": star}
            assert page.locator(f'[data-score="{star}"]').get_attribute("aria-label") == label
            assert page.locator(f'[data-score="{star}"]').get_attribute("aria-pressed") == "false"
        assert page.locator('[data-review-score]').input_value() == ""

        page.locator('#reviewModal form button[type="submit"]').click()
        assert page.evaluate("window.reviewSubmitWasPrevented") is True
        assert page.locator('[data-review-rating]').get_attribute("aria-invalid") == "true"
        error = page.locator('[data-review-rating-error]')
        assert error.get_attribute("aria-hidden") == "false"
        assert "hidden" not in (error.get_attribute("class") or "").split()
        assert error.inner_text() == catalog.gettext(
            "Please select a rating before submitting your review."
        )
        assert page.evaluate("document.activeElement.dataset.score") == "1"

        page.locator('[data-score="3"]').focus()
        page.keyboard.press("Space")
        assert page.locator('[data-review-score]').input_value() == "3"
        assert page.locator('[data-review-rating]').get_attribute("aria-invalid") == "false"
        assert error.get_attribute("aria-hidden") == "true"
        assert "hidden" in (error.get_attribute("class") or "").split()
        for star in "12345":
            expected = "true" if int(star) <= 3 else "false"
            assert page.locator(f'[data-score="{star}"]').get_attribute("aria-pressed") == expected
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        page.keyboard.press("Escape")
        assert page.locator("#reviewModal").get_attribute("aria-hidden") == "true"
        assert page.evaluate("document.body.style.overflow") == ""
        assert page.evaluate("document.activeElement.id") == "review-trigger"
    except Exception:
        folder = ROOT / "artifacts" / "phase3-browser"
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / f"post-booking-{language}-{width}.png"), full_page=True)
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
                    print(f"PASS Chromium appointment dialogs {language}/{width}")
        finally:
            browser.close()
    print("9 Chromium fixture scenarios passed across both production modal controllers; not full-app E2E or screen-reader acceptance")


if __name__ == "__main__":
    main()
