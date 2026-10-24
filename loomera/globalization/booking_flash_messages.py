"""Immutable approved booking flash msgids backed by compiled Django gettext.

All localized renderings come from the versioned fa/en/ar .po + .mo catalogs.
This module provides only exact source identifiers and their approved flash
tones. It deliberately contains no duplicate runtime translation table.
"""
from types import MappingProxyType

BOOKING_FLASH_MSGIDS = MappingProxyType({
    "error": (
        "خدمات انتخاب‌شده معتبر نیستند.",
        "اطلاعات سالن و خدمات برای رزرو کامل نیست.",
        "یک یا چند خدمت انتخاب‌شده معتبر نیست.",
        "متخصص انتخاب‌شده معتبر نیست.",
        "سالن مربوط به این لینک فعال نیست یا در دسترس نیست.",
        "برای این متخصص در این مجموعه خدمت فعالی پیدا نشد.",
        "خدمت انتخاب‌شده برای این متخصص معتبر نیست.",
        "اطلاعات رزرو ناقص است.",
        "این زمان همین حالا توسط کاربر دیگری نهایی شده است. لطفاً یک زمان آزاد دیگر انتخاب کنید.",
        "برای این رزرو امکان رزرو مجدد وجود ندارد.",
    ),
    "success": (
        "رزرو شما با موفقیت ثبت شد.",
        "اطلاعات رزرو قبلی بازیابی شد. حالا زمان جدید را انتخاب کنید.",
        "دیدگاه و امتیاز شما ثبت شد و بعد از بررسی نمایش داده می‌شود.",
    ),
    "info": (
        "برای برخی خدمات، متخصص قبلی در دسترس نبود و می‌توانید زمان جدید را با متخصص آزاد انتخاب کنید.",
    ),
})
