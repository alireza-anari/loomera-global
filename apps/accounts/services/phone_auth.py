"""Exit B: separate password identity from SMS deliverability.

Iranian compatibility keeps legacy 09 identities. Foreign password identities
require explicit +E.164 and geographic mobile numbering metadata.
"""
import phonenumbers
from django.conf import settings
from loomera.globalization.phone_identity import PhoneIdentityInputError, to_candidate_e164


def canonical_password_enabled():
    return bool(getattr(settings, "LOOMERA_CANONICAL_PASSWORD_LOGIN", False))


def password_identity(value):
    candidate = to_candidate_e164(value, default_country="IR")
    if candidate.startswith("+98"):
        return candidate
    try:
        parsed = phonenumbers.parse(candidate, None)
    except phonenumbers.NumberParseException:
        raise PhoneIdentityInputError("invalid phone identity") from None
    if (
        not phonenumbers.is_valid_number(parsed)
        or phonenumbers.region_code_for_number(parsed) in (None, "001")
        or phonenumbers.number_type(parsed) not in (
            phonenumbers.PhoneNumberType.MOBILE,
            phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
        )
        or phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        != candidate
    ):
        raise PhoneIdentityInputError("invalid phone identity")
    return candidate


def legacy_sms_mobile(value):
    candidate = to_candidate_e164(value, default_country="IR")
    if not candidate.startswith("+98"):
        raise PhoneIdentityInputError("unsupported SMS destination")
    return "0" + candidate[3:]


def reject_sms_destination(value):
    if not canonical_password_enabled() and not (
        isinstance(value, str) and value.strip().startswith("+")
    ):
        return False
    try:
        legacy_sms_mobile(value)
    except PhoneIdentityInputError:
        return True
    return False
