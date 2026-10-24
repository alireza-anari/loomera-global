"""Phase 3.22–3.24: compiled checkout/settlement/reschedule flash locale boundary.

Exercises the actual Django message partial and all shipped PO/MO catalogs.
Never executes a financial mutation, payment gateway, appointment write or SMS.
"""
from pathlib import Path
from types import MappingProxyType
import struct

from django.conf import settings
from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.main.templatetags.ui_message_extras import clean_ui_message
from apps.main.ui_feedback import user_error_message, user_ui_message
from loomera.globalization.booking_flash_catalog_migration import (
    inspect_booking_gettext_catalog, inspect_checkout_gettext_catalog,
)
from loomera.globalization.booking_flash_messages import BOOKING_FLASH_MSGIDS
from loomera.globalization.checkout_flash_messages import CHECKOUT_FLASH_MSGIDS
from loomera.globalization.interactive_messages import MESSAGE_IDS

LEVELS = {
    "error": (constants.ERROR, "alert"),
    "info": (constants.INFO, "status"),
    "warning": (constants.WARNING, "alert"),
    "success": (constants.SUCCESS, "status"),
}

# Independent snapshots of selected high-stakes reviewed translations.
CRITICAL_COPY = {
    "مبلغ قابل پرداخت برای این رزرو معتبر نیست.": (
        "The payable amount for this booking is invalid.",
        "المبلغ المستحق لهذا الحجز غير صالح.",
    ),
    "قیمت یا جزئیات مالی این رزرو از زمان مشاهده پیش‌نمایش تغییر کرده است. لطفاً مبلغ جدید را بررسی و دوباره تأیید کنید.": (
        "The price or financial details changed since the preview. Review the new amount and confirm again.",
        "تغيّر السعر أو التفاصيل المالية منذ المعاينة. يُرجى مراجعة المبلغ الجديد وتأكيده مجددًا.",
    ),
    "این رزرو قبلاً از نظر مالی نهایی شده است.": (
        "This booking has already been financially settled.",
        "تمت تسوية هذا الحجز ماليًا بالفعل.",
    ),
    "کد تخفیف نامعتبر بود و بدون تخفیف، رزرو ادامه پیدا کرد.": (
        "The discount code was invalid, so the booking continued without a discount.",
        "رمز الخصم غير صالح، لذا استمر الحجز دون خصم.",
    ),
    "زمان نوبت با موفقیت تغییر کرد.": (
        "The appointment time was changed successfully.",
        "تم تغيير وقت الموعد بنجاح.",
    ),
}


class CheckoutFlashLocaleTests(SimpleTestCase):
    def tearDown(self):
        translation.deactivate_all()

    @staticmethod
    def locale_dir(language):
        return Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES"

    @staticmethod
    def render(level, message):
        return render_to_string(
            "partials/messages.html", {"messages": [Message(level, message)]
                                        },
        )

    @classmethod
    def catalog(cls, language):
        return inspect_checkout_gettext_catalog(
            language, (cls.locale_dir(language) / "django.po").read_text(
                encoding="utf-8"
            ),
        )

    def test_reviewed_tone_scope_is_immutable_and_contains_twenty_six_messages(self):
        self.assertIsInstance(CHECKOUT_FLASH_MSGIDS, MappingProxyType)
        self.assertEqual(set(CHECKOUT_FLASH_MSGIDS), set(LEVELS))
        self.assertEqual(
            {tone: len(messages) for tone, messages in CHECKOUT_FLASH_MSGIDS.items()},
            {"error": 14, "info": 5, "warning": 3, "success": 4},
        )
        flat = [m for phrases in CHECKOUT_FLASH_MSGIDS.values() for m in phrases]
        self.assertEqual(len(flat), 26)
        self.assertEqual(len(set(flat)), 26)
        self.assertFalse(set(flat) & {
            msgid for messages in BOOKING_FLASH_MSGIDS.values() for msgid in messages
        })
        for m in flat:
            self.assertTrue(m)
            self.assertLessEqual(len(m), 300)
            for forbidden in ("{", "}", "<", ">", "\n", "09123456789"):
                self.assertNotIn(forbidden, m)
        with self.assertRaises(TypeError):
            CHECKOUT_FLASH_MSGIDS["error"] = ("override",)

    def test_po_and_compiled_mo_have_all_twenty_six_exact_entries_per_language(self):
        for language in ("fa", "en", "ar"):
            with self.subTest(lang=language):
                po = (self.locale_dir(language) / "django.po").read_text(encoding="utf-8")
                compiled = (self.locale_dir(language) / "django.mo").read_bytes()
                self.assertEqual(struct.unpack_from("<I", compiled, 0)[0], 0x950412de)
                self.assertEqual(struct.unpack_from("<I", compiled, 8)[0], 292)
                approved = inspect_checkout_gettext_catalog(language, po)
                self.assertEqual(len(approved), 26)
                self.assertEqual(po.count(
                    "#: loomera/globalization/checkout_flash_messages.py"
                ), 26)
                self.assertEqual(len(inspect_booking_gettext_catalog(language, po)), 14)
                with translation.override(language):
                    for msgid, expected in approved.items():
                        with self.subTest(msgid=msgid[:35]):
                            self.assertEqual(translation.gettext(msgid), expected)

    def test_critical_settlement_and_checkout_copy_is_independently_pinned(self):
        for language, index in (("en", 0), ("ar", 1)):
            with translation.override(language):
                for msgid, translated in CRITICAL_COPY.items():
                    with self.subTest(lang=language, msgid=msgid[:30]):
                        self.assertEqual(translation.gettext(msgid), translated[index])

    def test_real_server_flash_renders_approved_source_and_compiled_locales(self):
        originals = self.catalog("fa")
        translated = {lang: self.catalog(lang) for lang in ("en", "ar")}
        for tone, sources in CHECKOUT_FLASH_MSGIDS.items():
            level, expected_role = LEVELS[tone]
            for source in sources:
                for supplied in (source, translated["en"][source], translated["ar"][source]):
                    for language in ("en", "ar"):
                        with translation.override(language):
                            with self.subTest(tone=tone, language=language, value=supplied[:20]):
                                expected = translated[language][source]
                                self.assertEqual(clean_ui_message(supplied, tone), expected)
                                html = self.render(level, supplied)
                                self.assertIn(escape(expected), html)
                                self.assertIn(f'role="{expected_role}"', html)
                                self.assertIn("data-flash-close", html)
                                self.assertNotIn(
                                    translation.gettext(MESSAGE_IDS["feedback.default." + tone]),
                                    html,
                                )
        self.assertEqual(set(originals), set(translated["en"]))

    def test_warning_checkout_is_alert_and_cannot_be_promoted_to_success(self):
        warning = CHECKOUT_FLASH_MSGIDS["warning"][0]
        for lang in ("en", "ar"):
            with translation.override(lang):
                self.assertIn('role="alert"', self.render(constants.WARNING, warning))
                self.assertEqual(clean_ui_message(warning, "warning"),
                                 translation.gettext(warning))
                self.assertEqual(clean_ui_message(warning, "success"),
                                 translation.gettext(MESSAGE_IDS["feedback.default.success"]))

    def test_tone_isolation_for_every_approved_source_and_all_locale_forms(self):
        catalogs = {lang: self.catalog(lang) for lang in ("fa", "en", "ar")}
        for tone, sources in CHECKOUT_FLASH_MSGIDS.items():
            for source in sources:
                for other in LEVELS:
                    if other == tone:
                        continue
                    for lang in ("en", "ar"):
                        with translation.override(lang):
                            expected = translation.gettext(
                                MESSAGE_IDS["feedback.default." + other]
                            )
                            with self.subTest(tone=tone, other=other, lang=lang):
                                for supplied in (catalogs[x][source] for x in catalogs):
                                    self.assertEqual(clean_ui_message(supplied, other),
                                                     expected)

    def test_untrusted_amounts_phone_coupon_and_gateway_payloads_fail_closed(self):
        source = CHECKOUT_FLASH_MSGIDS["info"][0]
        cases = (
            source + " mobile=09123456789",
            CHECKOUT_FLASH_MSGIDS["error"][4] + " amount=999000",
            CHECKOUT_FLASH_MSGIDS["warning"][1] + " user@email.test",
            CHECKOUT_FLASH_MSGIDS["success"][0] + " code=VIP100",
            "ValueError: SQL SELECT * FROM payments",
            mark_safe("<img src=x onerror=alert('private')>"),
            "پرداخت درگاه callback_token=secret",
        )
        for lang in ("en", "ar"):
            with translation.override(lang):
                for tone, (level, _) in LEVELS.items():
                    fallback = translation.gettext(MESSAGE_IDS["feedback.default." + tone])
                    for raw in cases:
                        with self.subTest(lang=lang, tone=tone, case=str(raw)[:30]):
                            html = self.render(level, raw)
                            self.assertEqual(clean_ui_message(raw, tone), fallback)
                            self.assertIn(fallback, html)
                            for private in ("09123456789", "999000", "email.test",
                                            "VIP100", "SELECT *", "<img ", "secret"):
                                self.assertNotIn(private, html)

    def test_older_booking_and_account_catalogs_still_render(self):
        for lang in ("en", "ar"):
            with translation.override(lang):
                self.assertEqual(
                    clean_ui_message(BOOKING_FLASH_MSGIDS["success"][0], "success"),
                    translation.gettext(BOOKING_FLASH_MSGIDS["success"][0]),
                )
                account = "کد تایید منقضی شده است. لطفاً دوباره درخواست کد بدهید."
                self.assertEqual(clean_ui_message(account, "error"),
                                 translation.gettext(account))

    def test_legacy_persian_copy_and_business_defaults_are_unchanged(self):
        with translation.override("fa"):
            for tone, sources in CHECKOUT_FLASH_MSGIDS.items():
                for source in sources:
                    expected = (user_error_message(source) if tone in ("error", "warning")
                                else user_ui_message(source, allow_latin_data=True))
                    with self.subTest(tone=tone, source=source[:20]):
                        self.assertEqual(clean_ui_message(source, tone), expected)
                        self.assertIn(expected, self.render(LEVELS[tone][0], source))
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        self.assertEqual(len(MESSAGE_IDS), 41)

    def test_checkout_source_still_emits_literal_strings_no_backend_changes(self):
        source = (Path(settings.BASE_DIR) / "apps/orders/views.py").read_text(encoding="utf-8")
        for tone, sources in CHECKOUT_FLASH_MSGIDS.items():
            self.assertIn("messages." + tone + "(", source)
            for msgid in sources:
                with self.subTest(msgid=msgid[:35]):
                    self.assertIn(msgid, source)
        self.assertIn("_build_checkout_submission_fingerprint(", source)
        self.assertIn("transaction.atomic(", source)
        self.assertIn("_has_pending_pay_in_salon_online_payment(", source)
        runtime = (Path(settings.BASE_DIR) /
                   "loomera/globalization/checkout_flash_messages.py").read_text(
                       encoding="utf-8"
                   )
        for translation_value in CRITICAL_COPY.values():
            self.assertNotIn(translation_value[0], runtime)
            self.assertNotIn(translation_value[1], runtime)


    def test_wallet_payment_and_pay_at_salon_success_copy_is_pinned(self):
        completed = (
            "مبلغ رزرو از کیف پول شما کسر شد و نوبت با موفقیت ثبت شد.",
            "The booking amount was deducted from your wallet, and your appointment was booked successfully.",
            "خُصم مبلغ الحجز من محفظتك، وتم تسجيل موعدك بنجاح.",
        )
        deferred = (
            "نوبت شما قطعی شد و در برنامه کاری متخصص قرار گرفت. پرداخت این سفارش در مجموعه انجام می‌شود.",
            "Your appointment is confirmed and added to the professional's schedule. Payment for this order will be made at the salon.",
            "تم تأكيد موعدك وإضافته إلى جدول عمل المتخصص. سيُدفع ثمن هذا الطلب في الصالون.",
        )
        self.assertEqual(CHECKOUT_FLASH_MSGIDS["success"][-2:], (
            completed[0], deferred[0],
        ))
        for row in (completed, deferred):
            for lang, expected in zip(("fa", "en", "ar"), row):
                with self.subTest(lang=lang, source=row[0][:25]):
                    with translation.override(lang):
                        self.assertEqual(translation.gettext(row[0]), expected)
                        self.assertIn(escape(expected), self.render(constants.SUCCESS, row[0]))
                        self.assertIn('role="status"', self.render(constants.SUCCESS, row[0]))

    def test_success_source_is_issued_only_after_its_distinct_financial_state(self):
        views = (Path(settings.BASE_DIR) / "apps/orders/views.py").read_text(
            encoding="utf-8"
        )
        wallet_start = views.index(
            "if payment_method == AppointmentCheckoutForm.PAYMENT_METHOD_WALLET:"
        )
        salon_start = views.index(
            "if payment_method == AppointmentCheckoutForm.PAYMENT_METHOD_SALON:",
            wallet_start,
        )
        gateway_start = views.index(
            "from apps.payments.gateways import initiate_payment",
            salon_start,
        )
        wallet = views[wallet_start:salon_start]
        salon = views[salon_start:gateway_start]
        self.assertIn("wallet.withdraw(", wallet)
        self.assertIn("payment.mark_success(", wallet)
        self.assertIn('order.status = "paid"', wallet)
        self.assertIn("order.is_paid = True", wallet)
        self.assertIn(CHECKOUT_FLASH_MSGIDS["success"][-2], wallet)
        self.assertIn('"payments:appointment_result"', wallet)
        self.assertIn('order.status = "pending"', salon)
        self.assertNotIn("order.is_paid = True", salon)
        self.assertNotIn("payment.mark_success(", salon)
        self.assertIn(CHECKOUT_FLASH_MSGIDS["success"][-1], salon)
        self.assertIn('reverse("orders:appointments")', salon)

    def test_financial_success_copy_never_authorizes_raw_sensitive_data(self):
        wallet, salon = CHECKOUT_FLASH_MSGIDS["success"][-2:]
        for lang in ("en", "ar"):
            with translation.override(lang):
                success_fallback = translation.gettext(
                    MESSAGE_IDS["feedback.default.success"]
                )
                for original in (wallet, salon):
                    for contaminated in (
                        original + " wallet=09123456789",
                        original + " payment=secret",
                        original + " amount=750000",
                    ):
                        with self.subTest(lang=lang, phrase=original[:25]):
                            self.assertEqual(
                                clean_ui_message(contaminated, "success"),
                                success_fallback,
                            )
                            rendered = self.render(constants.SUCCESS, contaminated)
                            self.assertIn(escape(success_fallback), rendered)
                            for private in ("09123456789", "secret", "750000"):
                                self.assertNotIn(private, rendered)
                    for wrong_tone in ("error", "warning", "info"):
                        with self.subTest(lang=lang, wrong_tone=wrong_tone):
                            expected = translation.gettext(
                                MESSAGE_IDS["feedback.default." + wrong_tone]
                            )
                            self.assertEqual(
                                clean_ui_message(original, wrong_tone), expected
                            )

    def test_read_only_auditor_rejects_missing_duplicate_and_corrupt_catalogs(self):
        po = (self.locale_dir("en") / "django.po").read_text(encoding="utf-8")
        first = CHECKOUT_FLASH_MSGIDS["error"][0]
        literal = 'msgid "' + first + '"'
        block = po[po.index(literal):]
        block = block[:block.index("\n\n")]
        for changed in (
            po.replace(literal, 'msgid "Missing source"', 1),
            po + "\n" + block + "\n",
            po.replace(block.split("msgstr ")[-1], '""', 1),
        ):
            with self.assertRaises(ValueError):
                inspect_checkout_gettext_catalog("en", changed)
        with self.assertRaises(ValueError):
            inspect_checkout_gettext_catalog("ar", po)
        with self.assertRaises(ValueError):
            inspect_checkout_gettext_catalog("de", po)
        with self.assertRaises(TypeError):
            inspect_checkout_gettext_catalog("en", b"bad")
