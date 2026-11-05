"""Canonical calendar and business-timezone boundaries (Phase 5.1).

This module does not change existing booking/date query, reminder, or ICS behavior.
It provides an opt-in strict adapter while historical wall-clock values continue
to be interpreted through the pinned Tehran compatibility boundary.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError

from persiantools.jdatetime import JalaliDate


LEGACY_BOOKING_TIMEZONE = "Asia/Tehran"
_VALID_CALENDARS = frozenset(("gregorian", "jalali"))
_DATE_PATTERN = re.compile(r"^([0-9]{4})([-/])([0-9]{1,2})\2([0-9]{1,2})$")
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


class CalendarDateError(ValueError):
    """Invalid or calendar-ambiguous date input."""


class AmbiguousBusinessTimeError(ValueError):
    """A local business wall time has multiple UTC interpretations."""


class NonexistentBusinessTimeError(ValueError):
    """A local business wall time does not exist due to a clock transition."""


def resolve_calendar(calendar: str | None = None) -> str:
    """Select explicit calendar or deployment config, never infer from language."""
    value = settings.LOOMERA_DEFAULT_CALENDAR if calendar is None else calendar
    if not isinstance(value, str) or value not in _VALID_CALENDARS:
        raise ValueError("calendar must be 'gregorian' or 'jalali'")
    return value


def calendar_date_parts(day: date, *, calendar: str | None = None) -> tuple[int, int, int]:
    """Project a canonical Gregorian date to selected calendar components."""
    if not isinstance(day, date) or isinstance(day, datetime):
        raise TypeError("canonical date must be datetime.date, not datetime")
    if resolve_calendar(calendar) == "gregorian":
        return day.year, day.month, day.day
    converted = JalaliDate(day)
    return converted.year, converted.month, converted.day


def format_calendar_date(
    day: date, *, calendar: str | None = None, separator: str = "-"
) -> str:
    """Format a canonical Gregorian date; output uses stable ASCII digits."""
    if separator not in ("-", "/"):
        raise ValueError("separator must be '-' or '/'")
    year, month, day_of_month = calendar_date_parts(day, calendar=calendar)
    return f"{year:04d}{separator}{month:02d}{separator}{day_of_month:02d}"


def parse_calendar_date(value: str, *, calendar: str | None = None) -> date:
    """Parse explicit Gregorian/Jalali input into canonical Gregorian date.

    The calendar must come from an explicit selection or deployment contract;
    neither the shape nor the numerals imply a calendar. Invalid dates fail.
    """
    selected = resolve_calendar(calendar)
    if not isinstance(value, str) or not value or value != value.strip():
        raise CalendarDateError("calendar date must be a non-empty string")
    normalized = value.translate(_DIGIT_TRANSLATION)
    match = _DATE_PATTERN.fullmatch(normalized)
    if match is None:
        raise CalendarDateError("calendar date must use YYYY-MM-DD or YYYY/MM/DD")
    y, m, d = int(match[1]), int(match[3]), int(match[4])
    try:
        if selected == "gregorian":
            return date(y, m, d)
        converted = JalaliDate(y, m, d).to_gregorian()
        if calendar_date_parts(converted, calendar="jalali") != (y, m, d):
            raise CalendarDateError("invalid Jalali date")
        return converted
    except (ValueError, OverflowError) as exc:
        raise CalendarDateError("invalid calendar date") from exc


def validate_iana_timezone_name(value: str) -> None:
    """Django field validator for explicit IANA zone IDs (blank means legacy)."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValidationError("Enter a valid IANA timezone identifier.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValidationError("Enter a valid IANA timezone identifier.") from exc


def get_business_timezone(business: object) -> ZoneInfo:
    """Explicit business IANA zone; unset legacy rows remain Tehran wall-clock.

    An invalid explicit value is an error, *never* silently reinterpreted in
    a fallback zone. The deployment default is reserved for future new-salon
    onboarding and non-business operational context.
    """
    value = getattr(business, "timezone_name", "")
    if value in ("", None):
        return ZoneInfo(LEGACY_BOOKING_TIMEZONE)
    validate_iana_timezone_name(value)
    return ZoneInfo(value)


def business_local_to_utc(day: date, wall_time: time, business: object) -> datetime:
    """Resolve business wall time only if it maps to exactly one UTC instant.

    Rejects DST gaps and overlaps; a later booking integration must ask users
    to resolve ambiguous time instead of silently applying fold=0 or fold=1.
    """
    if not isinstance(day, date) or isinstance(day, datetime):
        raise TypeError("business day must be a date")
    if not isinstance(wall_time, time) or wall_time.tzinfo is not None:
        raise TypeError("business wall time must be a naive time")
    zone = get_business_timezone(business)
    naive = datetime.combine(day, wall_time)
    valid = set()
    for fold in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=fold)
        instant = aware.astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) == naive:
            valid.add(instant)
    if not valid:
        raise NonexistentBusinessTimeError("business wall time falls in a DST gap")
    if len(valid) != 1:
        raise AmbiguousBusinessTimeError("business wall time occurs twice")
    return valid.pop()


def utc_to_business_local(instant: datetime, business: object) -> datetime:
    """Convert an aware instant for presentation, without rewriting storage."""
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise TypeError("UTC conversion requires an aware datetime")
    if instant.utcoffset() is None:
        raise TypeError("UTC conversion requires an aware datetime")
    return instant.astimezone(get_business_timezone(business))
