"""Read-only validation of the compiled Phase 3 booking gettext migration.

Unlike the pre-migration preview builder, this audit inspects actual checked-in
PO entries and rejects duplicates, blanks, missing entries and locale drift.
The compiled .mo runtime is verified separately by Django regression tests.
"""
from __future__ import annotations

import json
import re

from loomera.globalization.booking_flash_messages import BOOKING_FLASH_MSGIDS

LANGUAGES = ("fa", "en", "ar")


def inspect_booking_gettext_catalog(language: str, po_content: str) -> dict[str, str]:
    """Inspect exactly the 14 approved msgids in a single native PO catalog.

    This is a pure auditing function: no writes, compilation, request state,
    string interpolation or fallback to unreviewed server data.
    """
    if language not in LANGUAGES:
        raise ValueError("Unsupported booking catalog language")
    if not isinstance(po_content, str):
        raise TypeError("Catalog must be UTF-8 text")
    if ('"Language: ' + language + r'\n"') not in po_content:
        raise ValueError("Catalog language header mismatch")

    audit = {}
    for tone, sources in BOOKING_FLASH_MSGIDS.items():
        if tone not in {"error", "success", "info"}:
            raise ValueError("Unreviewed booking flash tone")
        for msgid in sources:
            if not msgid or any(ch in msgid for ch in "\x00\r\n{}<>"):
                raise ValueError("Unsafe booking msgid")
            literal = json.dumps(msgid, ensure_ascii=False)
            hits = re.findall(
                r"(?m)^msgid " + re.escape(literal) +
                r'\nmsgstr ("(?:[^"\\]|\\.)*")$',
                po_content,
            )
            if len(hits) != 1:
                raise ValueError("Missing or duplicate booking msgid")
            translated = json.loads(hits[0])
            if not translated or any(ch in translated for ch in "\x00\r\n{}<>"):
                raise ValueError("Invalid or unreviewed booking translation")
            if len(translated) > 300:
                raise ValueError("Unexpectedly long booking translation")
            if language == "fa" and translated != msgid:
                raise ValueError("Historical Persian booking copy changed")
            if language != "fa" and translated == msgid:
                raise ValueError("Untranslated booking entry")
            audit[msgid] = translated
    if len(audit) != 14:
        raise ValueError("Invalid booking catalog size")
    return audit
