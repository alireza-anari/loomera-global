"""Phase 3.37: Chromium smoke of production appointment modal markup and JS.

Uses the real modal fragments and modal/rating controller from the production
template, with a small fixture for missing server data. It is not a full
authenticated booking journey or screen-reader/manual release sign-off.
"""
from gettext import translation as load_translation
import html
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DETAIL = (ROOT / "templates/orders/appointment_detail.html").read_text(encoding="utf-8")


def between(source, start, end):
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j <= i:
        raise AssertionError("Could not isolate production template section")
    return source[i:j]


PAGE_SCRIPT = between(DETAIL, "{% block js %}", "{% endblock %}").replace("{% block js %}", "")
MANAGE_TEMPLATE = between(
    DETAIL, "<!-- MANAGE MODAL -->", "\n{% if customer_progress.can_review %}"
)
REVIEW_TEMPLATE = between(
    DETAIL, '<div id="reviewModal"', "\n{% endif %}\n\n\n{% endblock %}"
)
# Render unmodified production modal fragments with Django, native gettext and
# the shipped CSS. The surrounding shell/domain data and URLconf are controlled
# test inputs, so this remains component evidence, not an authenticated route.
import django
from django.conf import settings
from django.template import Context, Engine
from django.urls import include, path
from django.utils import translation

urlpatterns = [path("appointments/", include(([
    path("<int:pk>/reschedule/", lambda request, pk: None, name="reschedule"),
    path("<int:pk>/calendar/", lambda request, pk: None, name="appointment_ics"),
    path("<int:pk>/cancel/", lambda request, pk: None, name="cancel_appointment"),
], "orders")))]
if not settings.configured:
    settings.configure(
        SECRET_KEY="component-test-only", USE_I18N=True,
        LANGUAGE_CODE="fa", LANGUAGES=[("fa", "Persian"), ("en", "English"), ("ar", "Arabic")],
        LOCALE_PATHS=[ROOT / "locale"], ROOT_URLCONF=__name__, INSTALLED_APPS=[],
    )
    django.setup()
ENGINE = Engine(libraries={"i18n": "django.templatetags.i18n"})
PRODUCTION_CSS = "\n".join((ROOT / "static/css" / name).read_text(encoding="utf-8")
    for name in ("output.css", "loomera-brand.css", "loomera-palette-override.css"))


def get_catalog(language):
    return load_translation("django", localedir=str(ROOT / "locale"), languages=[language])


def build_modal_fixture(language):
    catalog = get_catalog(language)
    context = Context({
        "appointment": {"id": 123, "service": {"service_name": "Cut & رنگ <img src=x>"},
                        "stylist": {"get_fullName": "Mina مریم & Sara"}},
        "cancellation_policy": {"title": "Cancellation policy"},
        "csrf_token": "component-token", "generic_service_name": catalog.gettext("Service"),
    })
    with translation.override(language):
        manage = ENGINE.from_string("{% load i18n %}" + MANAGE_TEMPLATE).render(context)
        review = ENGINE.from_string("{% load i18n %}" + REVIEW_TEMPLATE).render(context)
        script = ENGINE.from_string("{% load i18n %}" + PAGE_SCRIPT).render(context)
    trigger_manage = html.escape(catalog.gettext("Manage appointment"))
    trigger_review = html.escape(catalog.gettext("Leave a review"))
    page = f"""<!doctype html>
<html lang="{language}" dir="{'ltr' if language == 'en' else 'rtl'}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>{PRODUCTION_CSS}</style></head><body>
<header id="fixture-header"><a href="#main">Background header</a></header>
<main id="main">
  <section id="background-controls">
    <button id="manage-trigger" type="button" onclick="openManageModal()">{trigger_manage}</button>
    <button id="review-trigger" type="button" onclick="openReviewModal()">{trigger_review}</button>
  </section>
  <aside id="preexisting-inert" inert="original"><button>Unavailable</button></aside>
  {manage}{review}
</main>
{script}
</body></html>"""
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
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        fixture, catalog = build_modal_fixture(language)
        page.set_content(fixture)
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
        page.locator("#manage-trigger").focus()
        page.keyboard.press("Enter")
        assert page.locator("#manageModal").get_attribute("aria-hidden") == "false"
        assert page.evaluate("document.activeElement.id") == "manageModalTitle"
        assert page.evaluate("document.body.style.overflow") == "hidden"
        assert focusable_count(page, "manageModal") >= 3
        assert page.locator("#background-controls").evaluate("n => n.inert")
        assert page.locator("#fixture-header").evaluate("n => n.inert")
        page.locator("#review-trigger").evaluate("n => n.focus()")
        assert page.evaluate("document.activeElement.id") == "manageModalTitle"
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.activeElement.textContent.trim()") == catalog.gettext("Close")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == catalog.gettext("Close")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        page.keyboard.press("Escape")
        assert page.locator("#manageModal").get_attribute("aria-hidden") == "true"
        assert page.evaluate("document.body.style.overflow") == ""
        assert page.evaluate("document.activeElement.id") == "manage-trigger"
        assert not page.locator("#background-controls").evaluate("n => n.inert")
        assert page.locator("#preexisting-inert").get_attribute("inert") == "original"

        # Review modal: invalid submissions are stopped and announced, and the
        # actual score field/pressed states are updated with keyboard input.
        page.locator("#review-trigger").focus()
        page.keyboard.press("Enter")
        assert page.locator("#reviewModal").get_attribute("aria-hidden") == "false"
        assert page.evaluate("document.activeElement.id") == "reviewModalTitle"
        assert page.evaluate("document.body.style.overflow") == "hidden"
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.activeElement.textContent.trim()") == catalog.gettext("Leave a review")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == catalog.gettext("Close")
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
        # Nested opening: top layer remains visible/operable; the lower dialog
        # and background cannot receive focus. Then restore the original opener.
        page.locator("#manage-trigger").focus()
        page.keyboard.press("Enter")
        page.evaluate("window.openReviewModal()")
        assert page.locator("#manageModal").evaluate("n => n.inert")
        assert page.locator("#reviewModal").evaluate("n => !n.inert")
        assert page.evaluate("getComputedStyle(reviewModal).zIndex * 1 > getComputedStyle(manageModal).zIndex * 1")
        page.keyboard.press("Escape")
        assert page.evaluate("document.activeElement.id") == "manageModalTitle"
        page.keyboard.press("Escape")
        assert page.evaluate("document.activeElement.id") == "manage-trigger"

        # Short-height reflow is deliberately NOT called browser zoom acceptance.
        page.set_viewport_size({"width": width, "height": 320})
        page.locator("#review-trigger").focus()
        page.keyboard.press("Enter")
        panel = page.locator("#reviewModal > div")
        assert panel.evaluate("n => n.scrollHeight > n.clientHeight")
        assert panel.evaluate("n => getComputedStyle(n).overflowY") == "auto"
        assert panel.evaluate("n => n.getBoundingClientRect().top >= 0")
        assert panel.evaluate("n => n.getBoundingClientRect().bottom <= innerHeight")
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.activeElement.type") == "submit"
        assert page.locator('#reviewModal button[type="submit"]').evaluate(
            "n => n.getBoundingClientRect().top >= 0 && n.getBoundingClientRect().bottom <= innerHeight")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        folder = ROOT / "artifacts" / "phase3-browser"
        folder.mkdir(parents=True, exist_ok=True)
        assert not errors, errors
        page.screenshot(path=str(folder / f"post-booking-pass-{language}-{width}.png"), full_page=True)
        page.keyboard.press("Escape")
        assert page.locator("#preexisting-inert").get_attribute("inert") == "original"
    except Exception:
        folder = ROOT / "artifacts" / "phase3-browser"
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / f"post-booking-{language}-{width}.png"), full_page=True)
        raise
    finally:
        page.close()


def main():
    if sys.argv[1:] == ["--render-only"]:
        for language in ("fa", "en", "ar"):
            rendered, catalog = build_modal_fixture(language)
            assert "{%" not in rendered and "{{" not in rendered
            assert '<img src=x>' not in rendered and '&lt;img src=x&gt;' in rendered
            assert rendered.count('data-score=') == 5
            assert rendered.count("document.addEventListener('keydown'") == 1
            assert html.escape(catalog.gettext("Please select a rating before submitting your review."), quote=True) in rendered
            print(f"PASS Django modal HTML + complete page script {language}; browser NOT RUN")
        return
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
