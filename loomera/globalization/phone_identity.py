"""Phase 7.1: pure, conservative phone identity *proposal* (not wired to auth).

E.164 syntactic normalization is not proof of valid numbering allocation or SMS
deliverability. Existing CustomUser.mobile_number/login/SMS contracts remain intact.
"""
from __future__ import annotations

import re

PERSIAN_ARABIC_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
E164_SYNTAX = re.compile(r"\+[1-9][0-9]{7,14}\Z")
IRAN_MOBILE_NATIONAL = re.compile(r"9[0-9]{9}\Z")
COUNTRY_HINT = re.compile(r"[A-Z]{2}\Z")
ASCII_ALLOWED = re.compile(r"\+?[0-9 -]+\Z")


class PhoneIdentityInputError(ValueError):
    """Input invalid, no phone numbers included in exception messages."""


def to_candidate_e164(value: str, *, default_country: str = "IR") -> str:
    """Return candidate international identity, without changing any user.

    Iranian mobile inputs may use 09xxxxxxxxx, 9xxxxxxxxx, 989xxxxxxxxx,
    00989xxxxxxxxx, or +989xxxxxxxxx with Persian/Arabic digits and
    simple spaces/hyphens. Other countries require explicit +E.164.
    Parentheses, letters, Unicode lookalikes and local foreign formats are
    not guessed or silently stripped.
    """
    if type(default_country) is not str:
        raise PhoneIdentityInputError("invalid country hint")
    country = default_country.upper()
    if COUNTRY_HINT.fullmatch(country) is None:
        raise PhoneIdentityInputError("invalid country hint")
    if type(value) is not str or not value or len(value) > 64:
        raise PhoneIdentityInputError("invalid phone identity")
    text = value.translate(PERSIAN_ARABIC_DIGITS).strip(" ")
    if ASCII_ALLOWED.fullmatch(text) is None:
        raise PhoneIdentityInputError("invalid phone identity")
    compact = text.replace(" ", "").replace("-", "")
    if compact.startswith("+"):
        candidate = compact
    elif country == "IR":
        if compact.startswith("0098"):
            candidate = "+" + compact[2:]
        elif compact.startswith("98") and len(compact) == 12:
            candidate = "+" + compact
        elif compact.startswith("09") and len(compact) == 11:
            candidate = "+98" + compact[1:]
        elif compact.startswith("9") and len(compact) == 10:
            candidate = "+98" + compact
        else:
            raise PhoneIdentityInputError("invalid phone identity")
    else:
        raise PhoneIdentityInputError("explicit international form required")
    if E164_SYNTAX.fullmatch(candidate) is None:
        raise PhoneIdentityInputError("invalid phone identity")
    # The existing authentication domain accepts Iranian *mobile* numbers,
    # not arbitrary Iranian landlines. Do not widen it by accident.
    if candidate.startswith("+98") and IRAN_MOBILE_NATIONAL.fullmatch(
        candidate[3:]
    ) is None:
        raise PhoneIdentityInputError("invalid Iranian mobile identity")
    return candidate
