"""Generate reviewable gettext catalog appendices for the Phase 3 booking table.

This is a *draft-only* preparation utility: it never edits catalogs or .mo
artifacts. Promoting these translations requires atomically updating three
.po files and their compiled .mo peers, then moving the runtime away from
the transitional table after complete CI parity checks.
"""
from __future__ import annotations

import json
import re

from loomera.globalization.booking_flash_messages import BOOKING_FLASH_MESSAGES

LANGUAGES = ("fa", "en", "ar")
_BOOKING_CATALOG_MARKER = "#: loomera/globalization/booking_flash_messages.py"


def preview_booking_gettext_appendix(language: str, existing_po: str) -> str:
    """Return a deterministic PO appendix without modifying source or runtime.

    Fail closed on unsupported languages, incomplete PO headers, conflicting
    identifiers and unsafe/interpolated source messages.
    """
    if language not in LANGUAGES:
        raise ValueError("Unsupported booking catalog language")
    if not isinstance(existing_po, str):
        raise TypeError("Existing catalog must be UTF-8 text")
    if ('"Language: ' + language + r'\n"') not in existing_po:
        raise ValueError("Catalog language header mismatch")

    entries = []
    seen = set()
    for tone, source, english, arabic in BOOKING_FLASH_MESSAGES:
        if tone not in {"error", "success", "info"} or source in seen:
            raise ValueError("Duplicate or invalid booking message contract")
        seen.add(source)
        translation = {"fa": source, "en": english, "ar": arabic}[language]
        for value in (source, translation):
            if not value or any(ch in value for ch in ("\x00", "\n", "\r", "{", "}", "<", ">")):
                raise ValueError("Booking gettext entries must be static safe literals")
        msgid = json.dumps(source, ensure_ascii=False)
        if re.search(r'(?m)^msgid ' + re.escape(msgid) + r'$', existing_po):
            raise ValueError("Booking message already exists in catalog")
        entries.append(
            _BOOKING_CATALOG_MARKER + "\n"
            + 'msgid ' + msgid + "\n"
            + 'msgstr ' + json.dumps(translation, ensure_ascii=False) + "\n"
        )
    return "\n" + "\n".join(entries)
