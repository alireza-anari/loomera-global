"""Phase 3.30 — preview/checkout native gettext and payment-choice parity.

Database-free coverage for all 58 checkout strings, compiled fa/en/ar catalogs,
Django blocktrans interpolation, lazy form labels and unchanged payment values.
"""
import json
from pathlib import Path
import struct

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase, override_settings
from django.utils import translation

from apps.orders.forms import AppointmentCheckoutForm

LANGUAGES = ("fa", "en", "ar")
CHECKOUT_MSGIDS = (
    "Booking confirmation",
    "Review the service, professional, time, and price before confirming.",
    "Back to time selection",
    "Step 4 of 4",
    "Review booking details",
    "Overall booking time",
    "Multi-day booking",
    "This booking is scheduled across multiple days.",
    "To keep the services in order, part of this booking is scheduled for later days. Details for each day are shown before final confirmation.",
    "services",
    "Services, professionals and times",
    "Appointment date",
    "Appointment time",
    "Duration",
    "Auto-selected",
    "Service discount",
    "Payment",
    "Discounts and payment method",
    "First visit · digital payment",
    "Have a discount code?",
    "Discount code",
    "Enter your discount code",
    "Apply discount",
    "Remove code",
    "Coupon code",
    "was applied successfully.",
    "Discount cap for this code:",
    "Discount amount:",
    "Campaign cap:",
    "Payment method",
    "The appointment is booked now; pay at the salon when you arrive.",
    "Payment is completed through the online gateway.",
    "Wallet balance:",
    "Payment is made when you arrive at the salon.",
    "The booking is registered now; payment will be made when you arrive at the salon.",
    "Online payment is completed through the gateway; the booking is finalized after payment is confirmed.",
    "Price summary",
    "Service subtotal",
    "Coupon discount",
    "Total discounts",
    "Amount due",
    "Final amount",
    "Finalize booking",
    "Submitting booking",
    "Payment summary",
    "Salon",
    "Number of services",
    "Review the services, professionals, and times before finalizing your booking.",
    "Back to booking preview",
    "Payment and confirmation",
    "Review your booking details",
    "Online payment",
    "Pay with wallet",
    "Pay at the salon",
    "In the beta, only pay-at-the-salon is available.",
    "For a first visit to this salon, only digital payment (online or wallet) is allowed.",
    "on",
    "%(amount)s toman discount has been applied to this booking.",
)


@override_settings(
    LOOMERA_ENABLED_LANGUAGES=["fa", "en", "ar"],
    LOOMERA_DEFAULT_LANGUAGE="fa",
    LANGUAGES=(("fa", "فارسی"), ("en", "English"), ("ar", "العربية")),
)
class BookingCheckoutLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @staticmethod
    def catalog(language):
        folder = Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES"
        return (
            (folder / "django.po").read_text(encoding="utf-8"),
            (folder / "django.mo").read_bytes(),
        )

    def tearDown(self):
        translation.deactivate_all()

    def test_58_checkout_sources_are_compiled_and_translated_in_all_locales(self):
        self.assertEqual(len(CHECKOUT_MSGIDS), 58)
        self.assertEqual(len(set(CHECKOUT_MSGIDS)), 58)
        reference = "#: templates/orders/reservation_preview.html templates/orders/checkout.html apps/orders/forms.py"
        for language in LANGUAGES:
            po, mo = self.catalog(language)
            lines = po.splitlines()
            source_ids = [
                json.loads(lines[index + 1][6:])
                for index, line in enumerate(lines[:-1])
                if line == reference
            ]
            self.assertEqual(len(source_ids), 58)
            self.assertEqual(set(source_ids), set(CHECKOUT_MSGIDS))
            self.assertEqual(struct.unpack_from("<I", mo)[0], 0x950412de)
            self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 611)
            with translation.override(language):
                for msgid in CHECKOUT_MSGIDS:
                    anchor = "msgid " + json.dumps(msgid, ensure_ascii=False) + "\nmsgstr "
                    self.assertEqual(po.count(anchor), 1, msgid)
                    value = json.loads(po.split(anchor, 1)[1].splitlines()[0])
                    self.assertTrue(value)
                    self.assertNotIn("<", value)
                    self.assertNotIn(">", value)
                    self.assertEqual(translation.gettext(msgid), value)
                    if language == "en":
                        self.assertEqual(value, msgid)
                    else:
                        self.assertNotEqual(value, msgid)
                    if "%(amount)s" in msgid:
                        self.assertIn("%(amount)s", value)

    def test_preview_and_checkout_use_native_gettext_without_changing_submit_contracts(self):
        preview = self.source("templates/orders/reservation_preview.html")
        checkout = self.source("templates/orders/checkout.html")
        form_source = self.source("apps/orders/forms.py")
        combined = preview + checkout
        for msgid in (
            "Booking confirmation", "Step 4 of 4", "Review booking details",
            "Overall booking time", "Multi-day booking", "Services, professionals and times",
            "Appointment date", "Appointment time", "Auto-selected", "Service discount",
            "Discounts and payment method", "Have a discount code?", "Apply discount",
            "Remove code", "Coupon code", "was applied successfully.", "Payment method",
            "Price summary", "Service subtotal", "Coupon discount", "Total discounts",
            "Amount due", "Final amount", "Finalize booking", "Submitting booking",
            "Payment summary", "Salon", "Number of services",
        ):
            self.assertIn("{% trans '" + msgid + "' %}", combined)
        self.assertIn("{% blocktrans with amount=checkout.basket_discount_amount|floatformat:0 %}", preview)
        self.assertIn("{{ amount }} toman discount has been applied to this booking.", preview)
        self.assertIn("{% trans 'Enter your discount code' %}", combined)
        self.assertIn('_("Enter your discount code")', form_source)
        self.assertIn('value="apply_coupon"', preview + checkout)
        self.assertIn('value="clear_coupon"', preview + checkout)
        self.assertIn('value="confirm_checkout"', preview + checkout)
        self.assertIn("data-checkout-final-submit", preview + checkout)
        self.assertIn("data-loading-label=\"{% trans 'Submitting booking' %}\"", preview + checkout)
        self.assertIn('dir="ltr" data-booking-coupon-token', preview + checkout)
        self.assertNotIn("name=\"form_action\" value=\"confirm_payment\"", preview + checkout)

    def test_blocktrans_formats_amount_after_translation_without_losing_currency_or_value(self):
        template = Template(
            '{% load i18n %}{% blocktrans with amount=amount %}'
            '{{ amount }} toman discount has been applied to this booking.'
            '{% endblocktrans %}'
        )
        msgid = "%(amount)s toman discount has been applied to this booking."
        for language in LANGUAGES:
            with translation.override(language):
                rendered = template.render(Context({"amount": "125000"}))
                expected = translation.gettext(msgid) % {"amount": "125000"}
                with self.subTest(language=language):
                    self.assertEqual(rendered, expected)
                    self.assertIn("125000", rendered)
                    self.assertNotIn("%(amount)s", rendered)

    @override_settings(ONLINE_PAYMENT_ENABLED=True)
    def test_payment_choice_labels_and_coupon_field_are_lazy_localized(self):
        expected = {
            "en": ["Online payment", "Pay with wallet", "Pay at the salon"],
            "fa": ["پرداخت آنلاین", "پرداخت با کیف پول", "پرداخت در مجموعه"],
            "ar": ["الدفع الإلكتروني", "الدفع بالمحفظة", "الدفع في الصالون"],
        }
        for language in LANGUAGES:
            with translation.override(language):
                form = AppointmentCheckoutForm()
                self.assertEqual(str(form.fields["coupon_code"].label), translation.gettext("Discount code"))
                self.assertEqual(
                    str(form.fields["coupon_code"].widget.attrs["placeholder"]),
                    translation.gettext("Enter your discount code"),
                )
                self.assertEqual(str(form.fields["payment_method"].label), translation.gettext("Payment method"))
                choices = [str(label) for _, label in form.fields["payment_method"].choices]
                self.assertEqual(choices, expected[language])
                self.assertEqual(
                    [value for value, _ in form.fields["payment_method"].choices],
                    ["online", "wallet", "pay_in_salon"],
                )

    def test_payment_validation_messages_are_translated_without_changing_allowed_values(self):
        expected = {
            "en": (
                "In the beta, only pay-at-the-salon is available.",
                "For a first visit to this salon, only digital payment (online or wallet) is allowed.",
            ),
            "fa": (
                "در نسخه بتا فقط پرداخت در مجموعه فعال است.",
                "برای اولین مراجعه به این مجموعه، فقط پرداخت دیجیتال (آنلاین یا کیف پول) مجاز است.",
            ),
            "ar": (
                "في الإصدار التجريبي، الدفع في الصالون فقط متاح.",
                "في الزيارة الأولى لهذا الصالون، يُسمح بالدفع الرقمي فقط (عبر الإنترنت أو المحفظة).",
            ),
        }
        for language in LANGUAGES:
            with translation.override(language), override_settings(ONLINE_PAYMENT_ENABLED=False):
                beta = AppointmentCheckoutForm(data={"coupon_code": "", "payment_method": "online"})
                beta.fields["payment_method"].choices = [("online", "Online payment")]
                self.assertFalse(beta.is_valid())
                self.assertEqual(str(beta.errors["payment_method"][0]), expected[language][0])
            with translation.override(language), override_settings(ONLINE_PAYMENT_ENABLED=True):
                first_visit = AppointmentCheckoutForm(
                    data={"coupon_code": "", "payment_method": "pay_in_salon"},
                    requires_online_payment=True,
                )
                first_visit.fields["payment_method"].choices = [
                    ("pay_in_salon", "Pay at the salon"),
                    ("online", "Online payment"),
                ]
                self.assertFalse(first_visit.is_valid())
                self.assertEqual(str(first_visit.errors["payment_method"][0]), expected[language][1])
