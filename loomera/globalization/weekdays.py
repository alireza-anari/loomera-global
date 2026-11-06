"""Phase 6.1: compatibility-only weekday boundary.

Persisted SalonOpeningHours.day_of_week is Saturday=1 through Friday=7.
ISO weekdays use Monday=1 through Sunday=7. This module NEVER migrates
stored values or uses the display week's first day to interpret a booking.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


# Index zero is deliberately invalid: persisted legacy values are 1..7.
_LEGACY_TO_ISO = (None, 6, 7, 1, 2, 3, 4, 5)
_ISO_TO_LEGACY = (None, 3, 4, 5, 6, 7, 1, 2)


def _checked_weekday(value: int, *, representation: str) -> int:
    # bool is an int subclass; never permit True/False as day identifiers.
    if type(value) is not int:
        raise TypeError(f"{representation} weekday must be an integer")
    if value not in range(1, 8):
        raise ValueError(f"{representation} weekday must be in 1..7")
    return value


def legacy_to_iso_weekday(legacy_day: int) -> int:
    """Convert persisted Saturday=1 numbering to ISO Monday=1 numbering."""
    return _LEGACY_TO_ISO[_checked_weekday(legacy_day, representation="legacy")]


def iso_to_legacy_weekday(iso_day: int) -> int:
    """Convert ISO Monday=1 numbering to persisted Saturday=1 numbering."""
    return _ISO_TO_LEGACY[_checked_weekday(iso_day, representation="ISO")]


def legacy_opening_day_from_date(value: date) -> int:
    """Match existing .weekday() booking lookups exactly for dates/datetimes.

    Accept datetime too because preexisting consumers accepted it. This does
    not resolve timezone or calendar preference; callers supply a calendar day.
    """
    if not isinstance(value, date):
        raise TypeError("opening day lookup requires a date or datetime")
    return iso_to_legacy_weekday(value.isoweekday())


def saturday_first_form_index_from_date(value: date) -> int:
    """Zero-based Saturday=0..Friday=6 for the legacy weekly-shift POST.

    Unlike SalonOpeningHours.day_of_week (Saturday=1..Friday=7), the manager
    `day-{index}-shifts` form and its JavaScript consume exactly these indices.
    Keep the storage and form contracts distinct.
    """
    return legacy_opening_day_from_date(value) - 1


def ordered_iso_weekdays(*, first_day_iso: int = 1) -> tuple[int, ...]:
    """Presentation-only weekday ordering; never changes storage identity."""
    first = _checked_weekday(first_day_iso, representation="ISO")
    return tuple(((first - 1 + offset) % 7) + 1 for offset in range(7))


def start_of_display_week(value: date, *, first_day_iso: int = 1) -> date:
    """Presentation week start for a canonical day, not a booking weekday."""
    if type(value) is not date:
        raise TypeError("display week requires a canonical date (not datetime)")
    first = _checked_weekday(first_day_iso, representation="ISO")
    return value - timedelta(days=(value.isoweekday() - first) % 7)
