"""Phase 3.38 — real Chromium smoke of checkout CTA and coupon keyboard behavior.

Uses the **actual** production checkout form start-tag translations, the real
compiled Django gettext catalogs, and the complete production checkout guard
JavaScript. Forms are isolated fixtures, not authenticated checkout, live
banking, real gateway calls, or screen-reader/manual release approval.
"""
from gettext import translation as gettext_translation
import html
from pathlib import Path
import re

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
GUARD = (ROOT / "static/js/pages/booking_checkout_submit_guard.js").read_text(encoding="utf-8")
PAGES = ("checkout.html", "reservation_preview.html")
TRANS = re.compile(r"""{%\s*trans\s+(['"])(.*?)\1\s*%}""")
SOURCES = {
    "online": ("Pay online and confirm booking", "Redirecting to payment gateway"),
    "wallet": ("Pay with wallet", "Processing wallet payment"),
    "pay_in_salon": ("Confirm pay-at-salon booking", "Submitting booking"),
}


def build_fixture(template, language):
    src = (ROOT / "templates/orders" / template).read_text(encoding="utf-8")
    match = re.search(r"<form\b[^>]*?data-checkout-guard-form\b[^>]*?>", src, re.DOTALL)
    assert match, f"Missing production guarded checkout form in {template}"
    form = match.group(0).replace("{% url 'orders:checkout' %}", "/fixture-checkout/")
    catalog = gettext_translation("django", localedir=str(ROOT / "locale"), languages=[language])
    form = TRANS.sub(lambda m: html.escape(catalog.gettext(m.group(2)), quote=True), form)
    assert "{%" not in form and "{{" not in form, "Unresolved form HTML metadata"
    assert 'data-checkout-online-label=' in form
    assert 'data-checkout-wallet-loading=' in form
    assert 'data-checkout-salon-label=' in form

    choices = "".join(
        f'<label data-payment-option><input type="radio" name="payment_method" '
        f'value="{value}" {"checked" if value == "pay_in_salon" else ""}>'
        f'{value}</label>' for value in SOURCES
    )
    page = f"""<!doctype html><html lang="{language}"
      dir="{'ltr' if language == 'en' else 'rtl'}"><head>
      <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <style>* {{box-sizing:border-box}} body {{font:16px Arial,sans-serif;margin:0}}
      main {{max-width:100%;padding:1rem}} button,input {{font:inherit}}
      button {{padding:.4rem}} label {{display:block;margin:.2rem}}</style>
      </head><body><main>
      {form}
      {choices}
      <input data-checkout-coupon-input id="coupon" type="text" name="coupon_code">
      <button id="coupon-apply" data-checkout-coupon-action="apply" type="submit"
        name="form_action" value="apply_coupon">Apply coupon</button>
      <button type="submit" name="form_action" value="clear_coupon">Clear coupon</button>
      <aside data-checkout-mobile-bar data-keyboard-hidden="false">
        <button id="mobile-confirm" data-checkout-final-submit type="submit"
          name="form_action" value="confirm_checkout">Original</button>
      </aside>
      </form>
      <button id="desktop-confirm" form="appointment-checkout-form" data-checkout-final-submit
        type="submit" name="form_action" value="confirm_checkout">Original desktop</button>
      </main></body></html>"""
    return page, catalog


def run_one(browser, template, language, width):
    page = browser.new_page(viewport={"width": width, "height": 800})
    try:
        fixture, catalog = build_fixture(template, language)
        page.set_content(fixture)
        page.add_script_tag(content=GUARD)
        page.evaluate("""() => {
          window.fixtureSubmits = [];
          const form = document.querySelector('[data-checkout-guard-form]');
          form.addEventListener('submit', e => {
            window.fixtureSubmits.push(e.submitter?.value || '');
            e.preventDefault();
          });
          document.dispatchEvent(new Event('DOMContentLoaded'));
        }""")
        form = page.locator('[data-checkout-guard-form]')
        mobile = page.locator('#mobile-confirm')
        desktop = page.locator('#desktop-confirm')
        assert page.evaluate("document.documentElement.dir") == ("ltr" if language == "en" else "rtl")
        assert form.get_attribute("data-checkout-guard-bound") == "1"
        for method, (label_id, busy_id) in SOURCES.items():
            page.locator(f'input[name="payment_method"][value="{method}"]').check()
            expected = catalog.gettext(label_id)
            for button in (mobile, desktop):
                assert button.locator("span").inner_text() == expected, (template, language, method)
                assert button.get_attribute("data-loading-label") == catalog.gettext(busy_id)
            assert form.get_attribute("aria-busy") == "false"

        # Customer coupon field hides/inerts mobile CTA, then Enter applies
        # the coupon instead of creating a reservation or payment.
        page.locator('#coupon').focus()
        bar = page.locator('[data-checkout-mobile-bar]')
        assert bar.get_attribute("aria-hidden") == "true"
        assert bar.get_attribute("inert") is not None
        page.keyboard.type("SAVE10")
        page.keyboard.press("Enter")
        coupon_actions = page.evaluate("window.fixtureSubmits")
        assert coupon_actions and coupon_actions[-1] == "apply_coupon", (
            template, language, width, coupon_actions,
            page.evaluate("Array.from(document.querySelectorAll('[data-checkout-action-proxy]')).map(x => [x.name,x.value])"),
        )
        assert form.get_attribute("aria-busy") == "false"
        assert desktop.is_enabled() and mobile.is_enabled()
        page.evaluate("document.getElementById('coupon').blur()")
        assert bar.get_attribute("aria-hidden") == "false"
        assert bar.get_attribute("inert") is None

        # A tampered label is still rendered as text, never HTML.
        page.evaluate("""() => {document.querySelector('form').dataset.checkoutWalletLabel =
          '<img src=x onerror=alert(1)> & wallet';}""")
        page.locator('input[value="wallet"]').check()
        assert mobile.locator("span").inner_text() == "<img src=x onerror=alert(1)> & wallet"
        assert page.locator("img").count() == 0

        # Reset form attributes to native compiled locale translation.
        page.evaluate("(value) => document.querySelector('form').dataset.checkoutWalletLabel=value",
                      catalog.gettext(SOURCES["wallet"][0]))
        page.locator('input[value="pay_in_salon"]').check()
        page.locator('input[value="online"]').check()
        desktop.click()
        assert form.get_attribute("aria-busy") == "true"
        assert not mobile.is_enabled() and not desktop.is_enabled()
        expected_busy = catalog.gettext(SOURCES["online"][1])
        assert mobile.locator("span").inner_text() == expected_busy
        assert desktop.locator("span").inner_text() == expected_busy
        assert page.evaluate("window.fixtureSubmits[-1]") == "confirm_checkout"

        # Second submit must be blocked by original guard. Browser back/restore
        # clears both disabled state and transient confirmation action proxy.
        blocked = page.evaluate("""() => {
          const form=document.querySelector('form');
          const event=new SubmitEvent('submit', {bubbles:true,cancelable:true,
            submitter:document.querySelector('#desktop-confirm')});
          form.dispatchEvent(event);
          return event.defaultPrevented;
        }""")
        assert blocked
        page.evaluate("window.dispatchEvent(new Event('pageshow'))")
        assert form.get_attribute("aria-busy") == "false"
        assert desktop.is_enabled() and mobile.is_enabled()
        assert mobile.locator("span").inner_text() == catalog.gettext(SOURCES["online"][0])
        assert page.locator('[data-checkout-action-proxy="1"]').count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    except Exception:
        folder = ROOT / "artifacts/phase3-browser"
        folder.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(folder / f"checkout-{template}-{language}-{width}.png"), full_page=True)
        raise
    finally:
        page.close()


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for template in PAGES:
                for language in ("fa", "en", "ar"):
                    for width in (360, 768, 1440):
                        run_one(browser, template, language, width)
                        print(f"PASS guarded checkout {template} {language}/{width}")
        finally:
            browser.close()
    print("18 checkout fixture scenarios passed; not a live payment/booking or manual AT audit")


if __name__ == "__main__":
    main()
