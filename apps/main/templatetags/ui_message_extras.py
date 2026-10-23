"""Display-only feedback filters; never pass arbitrary server text to alt locales."""
from django import template
from django.utils import translation

from apps.main.ui_feedback import user_error_message, user_ui_message
from loomera.globalization.interactive_messages import MESSAGE_IDS

register = template.Library()

# Only these existing, audited *static* browser feedback strings may cross from
# server flash messages into non-Persian UI. No user data, provider errors,
# formatting arguments or domain-specific message text is translated here.
_TRUSTED_FLASH_KEYS = (
    "feedback.default.error",
    "feedback.default.success",
    "feedback.default.warning",
    "feedback.default.info",
    "validation.notice",
    "validation.server_form",
)
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
    if raw and len(raw) <= 300:
        for key in _TRUSTED_FLASH_KEYS:
            msgid = MESSAGE_IDS[key]
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
