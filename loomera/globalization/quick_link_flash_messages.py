"""Exact, reviewed quick-booking user-facing flash identifiers.

Only the static empty-selection notice is eligible for the error tone.
No user-provided names, tokens, formatted values or provider bodies are trusted.
All translated values come from native compiled Django gettext catalogs.
"""
from types import MappingProxyType

QUICK_LINK_FLASH_MSGIDS = MappingProxyType({
    "error": ("Select at least one service for this professional.",),
})
