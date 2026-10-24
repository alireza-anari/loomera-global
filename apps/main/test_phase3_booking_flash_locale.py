"""Phase 3.21: compiled gettext booking flash security and translation parity.

The verified translations below are retained as test-only review fixtures.
Production only holds Persian msgids and reads native fa/en/ar gettext .mo.
"""
from pathlib import Path
from types import MappingProxyType

from django.conf import settings
from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation
from django.utils.safestring import mark_safe

from apps.main.templatetags.ui_message_extras import clean_ui_message
from apps.main.ui_feedback import user_error_message, user_ui_message
from loomera.globalization.booking_flash_messages import BOOKING_FLASH_MSGIDS
from loomera.globalization.interactive_messages import MESSAGE_IDS

APPROVED_TRANSLATIONS = (
    ("error", "خدمات انتخاب‌شده معتبر نیستند.", "The selected services are invalid.", "الخدمات المحددة غير صالحة."),
    ("error", "اطلاعات سالن و خدمات برای رزرو کامل نیست.", "Salon and service details are incomplete for this booking.", "بيانات الصالون والخدمات غير مكتملة لإتمام الحجز."),
    ("error", "یک یا چند خدمت انتخاب‌شده معتبر نیست.", "One or more selected services are invalid.", "خدمة واحدة أو أكثر من الخدمات المحددة غير صالحة."),
    ("error", "متخصص انتخاب‌شده معتبر نیست.", "The selected professional is invalid.", "المتخصص المحدد غير صالح."),
    ("error", "سالن مربوط به این لینک فعال نیست یا در دسترس نیست.", "The salon for this link is inactive or unavailable.", "الصالون المرتبط بهذا الرابط غير نشط أو غير متاح."),
    ("error", "برای این متخصص در این مجموعه خدمت فعالی پیدا نشد.", "No active services are available for this professional at this salon.", "لا تتوفر خدمات نشطة لهذا المتخصص في هذا الصالون."),
    ("error", "خدمت انتخاب‌شده برای این متخصص معتبر نیست.", "The selected service is not valid for this professional.", "الخدمة المحددة غير صالحة لهذا المتخصص."),
    ("error", "اطلاعات رزرو ناقص است.", "The booking details are incomplete.", "بيانات الحجز غير مكتملة."),
    ("error", "این زمان همین حالا توسط کاربر دیگری نهایی شده است. لطفاً یک زمان آزاد دیگر انتخاب کنید.", "This time slot has just been booked by someone else. Please choose another available time.", "تم حجز هذا الموعد للتو من قِبل مستخدم آخر. يُرجى اختيار موعد آخر متاح."),
    ("error", "برای این رزرو امکان رزرو مجدد وجود ندارد.", "This booking cannot be booked again.", "لا يمكن إعادة حجز هذا الموعد."),
    ("success", "رزرو شما با موفقیت ثبت شد.", "Your booking was completed successfully.", "تم تسجيل حجزك بنجاح."),
    ("success", "اطلاعات رزرو قبلی بازیابی شد. حالا زمان جدید را انتخاب کنید.", "Your previous booking details were restored. Now choose a new time.", "تم استعادة بيانات حجزك السابق. اختر الآن موعدًا جديدًا."),
    ("success", "دیدگاه و امتیاز شما ثبت شد و بعد از بررسی نمایش داده می‌شود.", "Your review and rating were submitted and will appear after moderation.", "تم إرسال تقييمك ومراجعتك وسيظهران بعد المراجعة."),
    ("info", "برای برخی خدمات، متخصص قبلی در دسترس نبود و می‌توانید زمان جدید را با متخصص آزاد انتخاب کنید.", "The previous professional is unavailable for some services. You can choose a new time with an available professional.", "المتخصص السابق غير متاح لبعض الخدمات. يمكنك اختيار موعد جديد مع متخصص متاح."),
)
TONES = {
    "error": (constants.ERROR, "alert"),
    "success": (constants.SUCCESS, "status"),
    "info": (constants.INFO, "status"),
}


class BookingFlashLocaleTests(SimpleTestCase):
    def tearDown(self):
        translation.deactivate_all()

    @staticmethod
    def render(level, raw):
        return render_to_string(
            "partials/messages.html", {"messages": [Message(level, raw)]}
        )

    def test_only_tone_scoped_msgids_remain_in_runtime(self):
        self.assertIsInstance(BOOKING_FLASH_MSGIDS, MappingProxyType)
        self.assertEqual(set(BOOKING_FLASH_MSGIDS), set(TONES))
        self.assertEqual(
            {tone: len(values) for tone, values in BOOKING_FLASH_MSGIDS.items()},
            {"error": 10, "success": 3, "info": 1},
        )
        self.assertEqual(
            {(tone, source) for tone, sources in BOOKING_FLASH_MSGIDS.items()
             for source in sources},
            {(tone, source) for tone, source, _, _ in APPROVED_TRANSLATIONS},
        )
        for tone, sources in BOOKING_FLASH_MSGIDS.items():
            for source in sources:
                self.assertIn(tone, TONES)
                self.assertNotIn("{", source)
                self.assertNotIn("<", source)
        with self.assertRaises(TypeError):
            BOOKING_FLASH_MSGIDS["warning"] = ("unapproved",)

    def test_all_fourteen_compiled_gettext_translations_match_reviewed_fixture(self):
        for tone, source, english, arabic in APPROVED_TRANSLATIONS:
            for language, expected in (("fa", source), ("en", english), ("ar", arabic)):
                with self.subTest(tone=tone, lang=language, source=source[:25]):
                    with translation.override(language):
                        self.assertEqual(translation.gettext(source), expected)

    def test_actual_flash_html_localizes_fa_en_ar_source_forms(self):
        for tone, source, english, arabic in APPROVED_TRANSLATIONS:
            level, role = TONES[tone]
            for raw in (source, english, arabic):
                for language in ("en", "ar"):
                    with translation.override(language):
                        with self.subTest(tone=tone, lang=language, raw=raw[:20]):
                            expected = english if language == "en" else arabic
                            self.assertEqual(clean_ui_message(raw, tone), expected)
                            html = self.render(level, raw)
                            self.assertIn(expected, html)
                            self.assertIn('role="' + role + '"', html)
                            self.assertIn("data-flash-close", html)
                            self.assertNotIn(
                                translation.gettext(MESSAGE_IDS["feedback.default." + tone]),
                                html,
                            )

    def test_danger_alias_is_error_but_warning_remains_unapproved(self):
        source = BOOKING_FLASH_MSGIDS["error"][0]
        for language in ("en", "ar"):
            with translation.override(language):
                self.assertEqual(
                    clean_ui_message(source, "danger"), translation.gettext(source)
                )
                self.assertEqual(
                    clean_ui_message(source, "warning"),
                    translation.gettext(MESSAGE_IDS["feedback.default.warning"]),
                )
                self.assertIn('role="alert"', self.render(constants.ERROR, source))

    def test_no_cross_tone_promotion_from_any_compiled_language(self):
        for tone, source, english, arabic in APPROVED_TRANSLATIONS:
            for candidate_tone in ("error", "warning", "success", "info"):
                if candidate_tone == tone:
                    continue
                for language in ("en", "ar"):
                    with translation.override(language):
                        with self.subTest(source=tone, target=candidate_tone, lang=language):
                            expected = translation.gettext(
                                MESSAGE_IDS["feedback.default." + candidate_tone]
                            )
                            for raw in (source, english, arabic):
                                self.assertEqual(clean_ui_message(raw, candidate_tone), expected)

    def test_unreviewed_payment_and_sensitive_user_data_fail_closed(self):
        threats = (
            "پرداخت درگاه برای این مشتری با اطلاعات مالی ناشناخته انجام شد.",
            "اطلاعات این رزرو برای رزرو مجدد کامل نیست.",
            "کد تخفیف VIP100 برای این مشتری اعمال شد.",
            "رزرو شما با موفقیت ثبت شد. شماره: 09123456789",
            "Your booking was completed successfully. user@email.test",
            "SQL Error: SELECT * FROM users",
            mark_safe("<script>alert('danger')</script>"),
            "کد تست شما: 12345678",
        )
        for language in ("en", "ar"):
            with translation.override(language):
                for tone, (level, _) in TONES.items():
                    fallback = translation.gettext(MESSAGE_IDS["feedback.default." + tone])
                    for raw in threats:
                        with self.subTest(lang=language, tone=tone, raw=str(raw)[:30]):
                            html = self.render(level, raw)
                            self.assertEqual(clean_ui_message(raw, tone), fallback)
                            self.assertIn(fallback, html)
                            for secret in ("09123456789", "email.test", "SELECT *",
                                           "12345678", "<script>", "danger"):
                                self.assertNotIn(secret, html)

    def test_approved_messages_cannot_be_extended_with_untrusted_details(self):
        for tone, source, english, arabic in APPROVED_TRANSLATIONS:
            for language in ("en", "ar"):
                with translation.override(language):
                    fallback = translation.gettext(MESSAGE_IDS["feedback.default." + tone])
                    for raw in (
                        source + " 09123456789",
                        english + " booking #8675309",
                        arabic + " user=private",
                        source[:-1],
                        source + "<b>",
                    ):
                        with self.subTest(lang=language, tone=tone, raw=raw[:25]):
                            self.assertEqual(clean_ui_message(raw, tone), fallback)

    def test_persian_historical_sanitizer_and_original_copy_unchanged(self):
        with translation.override("fa"):
            for tone, source, _, _ in APPROVED_TRANSLATIONS:
                with self.subTest(source=source):
                    expected = (user_error_message(source) if tone == "error" else
                                user_ui_message(source, allow_latin_data=True))
                    self.assertEqual(clean_ui_message(source, tone), expected)
                    self.assertIn(expected, self.render(TONES[tone][0], source))
            self.assertEqual(
                clean_ui_message("ValueError: SQL failure", "error"),
                user_error_message("ValueError: SQL failure"),
            )

    def test_all_approved_sources_still_emitted_by_active_booking_views(self):
        source = (Path(settings.BASE_DIR) / "apps/orders/views.py").read_text(encoding="utf-8")
        for tone, msgid, _, _ in APPROVED_TRANSLATIONS:
            with self.subTest(tone=tone, source=msgid):
                self.assertIn(msgid, source)
                self.assertIn("messages." + tone + "(", source)
        self.assertIn("resolve_booking_sequence(", source)
        self.assertIn("transaction.atomic(", source)
        self.assertIn("record_booking_quick_link_started(", source)

    def test_request_language_switch_no_cache_and_browser_dictionary_is_unchanged(self):
        self.assertEqual(len(MESSAGE_IDS), 41)
        for language in ("en", "ar", "fa", "ar", "en"):
            with translation.override(language):
                for tone, msgid, en, ar in APPROVED_TRANSLATIONS:
                    with self.subTest(lang=language, tone=tone):
                        expected = msgid if language == "fa" else (
                            en if language == "en" else ar
                        )
                        self.assertIn(expected, self.render(TONES[tone][0], msgid))
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")

    def test_runtime_does_not_embed_duplicate_translated_booking_table(self):
        runtime = (Path(settings.BASE_DIR) /
                   "loomera/globalization/booking_flash_messages.py").read_text(
                       encoding="utf-8"
                   )
        for _, _, english, arabic in APPROVED_TRANSLATIONS:
            self.assertNotIn(english, runtime)
            self.assertNotIn(arabic, runtime)
        self.assertIn("MappingProxyType", runtime)
        filter_source = (Path(settings.BASE_DIR) /
                         "apps/main/templatetags/ui_message_extras.py").read_text(
                             encoding="utf-8"
                         )
        self.assertIn("BOOKING_FLASH_MSGIDS.get(tone, ())", filter_source)
        self.assertIn("translation.gettext(msgid)", filter_source)
        self.assertNotIn("trusted_booking_flash", filter_source)
