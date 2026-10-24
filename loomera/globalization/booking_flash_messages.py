"""Audited, literal booking/service flash strings for the transitional Phase 3 UI.

The active booking views still emit their existing Persian messages. These
exact, static, tone-scoped translations are used only at the flash display
boundary, until the corresponding gettext catalogs can be reviewed and
compiled together. No interpolation, runtime translation, or domain decisions.
"""
from __future__ import annotations

# (tone, exact Persian source, approved English rendering, approved Arabic rendering).
# Immutable tuple-of-tuples: never populated from a request, database, or external API.
BOOKING_FLASH_MESSAGES = (
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


def trusted_booking_flash(raw: str, tone: str, language: str) -> str | None:
    """Return only an exact approved static translation for the given tone."""
    if language not in ("en", "ar") or tone not in ("error", "success", "info"):
        return None
    for approved_tone, persian, english, arabic in BOOKING_FLASH_MESSAGES:
        if approved_tone == tone and raw in (persian, english, arabic):
            return english if language == "en" else arabic
    return None
