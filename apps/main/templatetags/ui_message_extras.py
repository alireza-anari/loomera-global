"""Display-only feedback filters; never pass arbitrary server text to alt locales."""
from django import template
from django.utils import translation

from apps.main.ui_feedback import user_error_message, user_ui_message
from loomera.globalization.interactive_messages import MESSAGE_IDS
from loomera.globalization.booking_flash_messages import BOOKING_FLASH_MSGIDS
from loomera.globalization.quick_link_flash_messages import QUICK_LINK_FLASH_MSGIDS
from loomera.globalization.checkout_flash_messages import CHECKOUT_FLASH_MSGIDS

register = template.Library()

# Only existing audited browser feedback strings and the reviewed *literal*
# account/OTP gettext messages may cross into non-Persian flash UI.
# No dynamic domain text, user data, provider errors or formatting arguments.
_TRUSTED_ERROR_KEYS = ("validation.notice", "validation.server_form")
_TRUSTED_DOMAIN_FLASH_MSGIDS = {
    # Only literal account/OTP messages from the live views which already have
    # reviewed fa/en/ar compiled gettext entries. No interpolated OTPs, mobile
    # numbers, user names or provider errors are allowed on this boundary.
    "error": (
        "شماره موبایل یا رمز عبور اشتباه است.",
        "کد تایید منقضی شده است. لطفاً دوباره درخواست کد بدهید.",
        "جلسه بازیابی یا ثبت‌نام منقضی شده است.",
        "تعداد تلاش‌های مجاز تمام شده است. لطفاً دوباره درخواست کد بدهید.",
        "کد تایید بیش از حد اشتباه وارد شد. لطفاً دوباره درخواست کد بدهید.",
        "کاربر مرتبط با این کد پیدا نشد.",
        "اطلاعات وارد شده اشتباه است.",
    ),
    "info": ("ابتدا شماره موبایل و کد دریافتی را ثبت کنید.",),
}

_CATALOG_LANGUAGES = ("fa", "en", "ar")


def _flash_tone(tag_set):
    if tag_set.intersection({"error", "danger"}):
        return "error"
    if "warning" in tag_set:
        return "warning"
    if "success" in tag_set:
        return "success"
    return "info"


def _approved_flash_body(value, tone, language):
    """Translate exact allowlisted literals; otherwise use a typed safe fallback.

    The matching candidates are literal msgids and their *compiled* catalog
    translations. Deliberately reject arbitrary Persian/English/Arabic text,
    interpolation, near matches, composite messages and backend payloads.
    """
    raw = str(value or "").strip()
    allowed_msgid = None
    keys = ("feedback.default." + tone,)
    if tone in {"error", "warning"}:
        keys += _TRUSTED_ERROR_KEYS
    # Domain messages are gated by tone; never accept success copy as an error
    # or OTP/session errors as success/info. Generic catalog keys stay separate.
    candidates = (
        tuple(MESSAGE_IDS[key] for key in keys)
        + _TRUSTED_DOMAIN_FLASH_MSGIDS.get(tone, ())
        + BOOKING_FLASH_MSGIDS.get(tone, ())
        + QUICK_LINK_FLASH_MSGIDS.get(tone, ())
        + CHECKOUT_FLASH_MSGIDS.get(tone, ())
    )
    if raw and len(raw) <= 300:
        for msgid in candidates:
            if raw == msgid:
                allowed_msgid = msgid
                break
            for known_language in _CATALOG_LANGUAGES:
                with translation.override(known_language):
                    if raw == translation.gettext(msgid):
                        allowed_msgid = msgid
                        break
            if allowed_msgid is not None:
                break

    with translation.override(language):
        return translation.gettext(
            allowed_msgid or MESSAGE_IDS["feedback.default." + tone]
        )


@register.filter
def clean_ui_message(value, tags=""):
    """Normalize flash text without leaking unreviewed server or user content.

    Preserve the historical Persian sanitizer unchanged. English/Arabic
    display only exact catalog-approved body copy, or their localized generic
    fallback for the selected flash tone.
    """
    tag_set = set(str(tags or "").split())
    language = (translation.get_language() or "fa").split("-")[0].lower()
    if language in {"en", "ar"}:
        return _approved_flash_body(value, _flash_tone(tag_set), language)
    if tag_set.intersection({"error", "danger", "warning"}):
        return user_error_message(value)
    if tag_set.intersection({"success", "info"}):
        return user_ui_message(value, allow_latin_data=True)
    return user_ui_message(value)
