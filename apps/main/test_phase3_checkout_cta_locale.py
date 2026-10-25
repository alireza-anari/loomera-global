"""Phase 3.38 — localized checkout CTA and keyboard-safety contract.

Django gettext + structural guards; live Chromium fixture checks are separate.
No database, bank, gateway, checkout booking, or Production mutations.
"""
import json
from pathlib import Path
import struct

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils import translation

SOURCES = {
    "Pay online and confirm booking": {
        "fa": "پرداخت و ثبت رزرو",
        "en": "Pay online and confirm booking",
        "ar": "الدفع الإلكتروني وتأكيد الحجز",
    },
    "Redirecting to payment gateway": {
        "fa": "در حال انتقال به درگاه",
        "en": "Redirecting to payment gateway",
        "ar": "جارٍ التحويل إلى بوابة الدفع",
    },
    "Processing wallet payment": {
        "fa": "در حال پرداخت",
        "en": "Processing wallet payment",
        "ar": "جارٍ الدفع من المحفظة",
    },
    "Confirm pay-at-salon booking": {
        "fa": "ثبت رزرو",
        "en": "Confirm pay-at-salon booking",
        "ar": "تأكيد الحجز والدفع في الصالون",
    },
}

METADATA = {
    "checkout-online-label": "Pay online and confirm booking",
    "checkout-online-loading": "Redirecting to payment gateway",
    "checkout-wallet-label": "Pay with wallet",
    "checkout-wallet-loading": "Processing wallet payment",
    "checkout-salon-label": "Confirm pay-at-salon booking",
    "checkout-salon-loading": "Submitting booking",
}


class CheckoutCtaRuntimeLocaleTests(SimpleTestCase):
    TEMPLATES = ("templates/orders/checkout.html", "templates/orders/reservation_preview.html")

    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def tearDown(self):
        translation.deactivate_all()

    def test_four_new_gettext_ids_are_compiled_in_all_languages(self):
        for lang in ("fa", "en", "ar"):
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            po = (folder / "django.po").read_text(encoding="utf-8")
            mo = (folder / "django.mo").read_bytes()
            with self.subTest(language=lang):
                self.assertEqual(struct.unpack_from("<I", mo, 0)[0], 0x950412de)
                self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 605)
                for source, values in SOURCES.items():
                    entry = ("msgid " + json.dumps(source, ensure_ascii=False) +
                             "\nmsgstr " + json.dumps(values[lang], ensure_ascii=False))
                    self.assertIn(entry, po)
                    self.assertEqual(po.count("msgid " + json.dumps(source) + "\n"), 1)
                    with translation.override(lang):
                        self.assertEqual(translation.gettext(source), values[lang])

    def test_both_forms_render_six_gettext_attributes_on_initial_load(self):
        for path in self.TEMPLATES:
            src = self.source(path)
            self.assertEqual(src.count("data-checkout-guard-form"), 1)
            for data_name, message in METADATA.items():
                with self.subTest(template=path, attribute=data_name):
                    declaration = 'data-' + data_name + '="{% trans \''
                    self.assertIn(declaration + message + "' %}\"", src)
                    for lang in ("fa", "en", "ar"):
                        with translation.override(lang):
                            markup = Template("{% load i18n %}" +
                                declaration + message + "' %}\"").render(Context({}))
                            self.assertIn(translation.gettext(message), markup)

    def test_payment_copy_flows_to_both_ctas_without_html_interpolation(self):
        js = self.source("static/js/pages/booking_checkout_submit_guard.js")
        for key in ("checkoutOnlineLabel", "checkoutOnlineLoading",
                    "checkoutWalletLabel", "checkoutWalletLoading",
                    "checkoutSalonLabel", "checkoutSalonLoading"):
            self.assertIn(key, js)
        self.assertIn("button.replaceChildren(icon, caption)", js)
        self.assertIn("caption.textContent = label", js)
        self.assertNotIn("button.innerHTML =", js)
        self.assertNotIn("originalLabels", js)
        self.assertIn("form.dataset.checkoutSubmitting", js)
        self.assertIn("button.disabled = busy", js)
        self.assertIn("button.setAttribute(\"aria-disabled\"", js)

    def test_hidden_mobile_confirm_action_is_also_inert(self):
        js = self.source("static/js/pages/booking_checkout_submit_guard.js")
        self.assertIn('bar.setAttribute("aria-hidden", hidden ? "true" : "false")', js)
        self.assertIn("bar.inert = hidden", js)
        self.assertIn("COUPON_INPUT_SELECTOR", js)
        self.assertIn("ensureActionProxy(form, APPLY_COUPON_ACTION)", js)
        self.assertIn("form.requestSubmit(applyButton || undefined)", js)
        for page in self.TEMPLATES:
            markup = self.source(page)
            self.assertIn("data-checkout-mobile-bar", markup)
            self.assertIn("data-checkout-coupon-action", markup)
            self.assertIn("data-checkout-final-submit", markup)

    def test_payment_method_and_post_contracts_are_unchanged(self):
        js = self.source("static/js/pages/booking_checkout_submit_guard.js")
        for name in ("confirm_checkout", "apply_coupon", "clear_coupon",
                     "online", "wallet", "pay_in_salon"):
            self.assertIn(name, js)
        self.assertIn("event.preventDefault()", js)
        self.assertIn("event.stopPropagation()", js)
        self.assertIn("form.dataset.checkoutSubmitting === \"1\"", js)
        self.assertIn("ensureActionProxy(form, CONFIRM_ACTION)", js)
        for page in self.TEMPLATES:
            markup = self.source(page)
            self.assertIn('value="confirm_checkout"', markup)
            self.assertIn('value="apply_coupon"', markup)
            self.assertIn('value="clear_coupon"', markup)
            self.assertIn("data-checkout-guard-form", markup)

    def test_booking_copy_not_promoted_into_server_trusted_flashes(self):
        js = self.source("static/js/interactive_i18n.js")
        self.assertIn('!key.startsWith("booking.")', js)
        self.assertIn("approved.has(value.trim())", js)
        self.assertNotIn("window.LoomeraFeedback", self.source(
            "static/js/pages/booking_checkout_submit_guard.js"
        ))
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")

    def test_phase_three_still_needs_manual_acceptance(self):
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["manual_evidence"], [])
        for gate in ("real_browser_visual", "real_keyboard_acceptance",
                     "screen_reader_acceptance", "responsive_zoom",
                     "release_deployment_approval"):
            self.assertIn(gate, matrix["open_gates"])
