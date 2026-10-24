"""Versioned, request-scoped UI text for trusted browser form feedback.

This contract is deliberately limited to generic client validation, flash UI and submit-pending feedback.
It never transports raw server validation, business, payment or permission data.
"""
from __future__ import annotations

from types import MappingProxyType

from django.utils import translation

from loomera.globalization.locale import get_deployment_locale_context
from loomera.globalization.booking_interactive_messages import BOOKING_UI_MESSAGE_IDS
from loomera.globalization.booking_journey_messages import BOOKING_JOURNEY_MESSAGE_IDS


# Stable keys are consumed by static JS. The msgids are English source phrases
# compiled in the existing en/fa/ar Django gettext catalogs.
MESSAGE_IDS = MappingProxyType({
    "feedback.title.error": "Not completed",
    "feedback.title.success": "Completed",
    "feedback.title.warning": "Needs review",
    "feedback.title.info": "Information",
    "feedback.default.error": "This action could not be completed. Please try again.",
    "feedback.default.success": "The action completed successfully.",
    "feedback.default.warning": "This item needs review.",
    "feedback.default.info": "The information was updated.",
    "feedback.close": "Close message",
    "submit.saving": "Saving…",
    "submit.registering": "Registering…",
    "submit.sending": "Sending…",
    "submit.creating": "Creating…",
    "submit.logging_in": "Signing in…",
    "submit.confirming": "Confirming…",
    "submit.activating": "Activating…",
    "submit.deleting": "Deleting…",
    "submit.cancelling": "Cancelling…",
    "submit.working": "Working…",
    "validation.invalid": "The field value is invalid.",
    "validation.required": "This field is required.",
    "validation.email": "Enter a valid email address.",
    "validation.url": "Enter a valid URL.",
    "validation.type": "The value does not match the field format.",
    "validation.pattern": "The value does not match the required pattern.",
    "validation.too_short": "Enter at least {min} characters.",
    "validation.too_long": "Enter no more than {max} characters.",
    "validation.range_under": "The value must be at least {min}.",
    "validation.range_over": "The value must be no more than {max}.",
    "validation.step": "The value does not match the allowed step.",
    "validation.bad_input": "The value could not be processed. Please check it.",
    "validation.correct": "The field value is invalid. Please correct it.",
    "validation.notice": "Please correct the highlighted fields.",
    "validation.server_form": "The form information is invalid. Please review it.",
    "password.strength.strong": "Strong password.",
    "password.strength.acceptable": "Acceptable password; consider making it stronger.",
    "password.strength.guidance": "At least 8 characters; numbers, letters and symbols make it stronger.",
    "password.show": "Show password",
    "password.hide": "Hide password",
    "password.mismatch": "Passwords do not match.",
    "password.too_short": "Password must be at least 8 characters long.",
})


def interactive_messages(request):
    """Expose only allowlisted static translations, not user/server messages.

    The explicit language override makes this safe in independently rendered
    request templates, even if the Django translation state was activated by
    another request earlier in the same worker.
    """
    language = get_deployment_locale_context(request).language_code
    with translation.override(language):
        messages = {
            key: translation.gettext(msgid)
            for key, msgid in (*MESSAGE_IDS.items(), *BOOKING_UI_MESSAGE_IDS.items(), *BOOKING_JOURNEY_MESSAGE_IDS.items())
        }
    return {"interactive_messages": {"language": language, "messages": messages}}
