"""Read-only pre-cutover classification of stored appointment wall clocks.

An explicit salon timezone is metadata: it is NOT proof that historical
appointments were created in that timezone. Any delta is a review risk, not a
request to rewrite rows. The live booking/ICS/reminder paths remain unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from types import SimpleNamespace

from django.core.exceptions import ValidationError

from loomera.globalization.calendar_time import (
    AmbiguousBusinessTimeError,
    NonexistentBusinessTimeError,
    business_local_to_utc,
)


# Fixed, non-PII risk taxonomy shared by all offline/DB cutover audits.
CLASSIFICATIONS = (
    "missing_start",
    "legacy_dst_gap",
    "legacy_dst_overlap",
    "legacy_tehran",
    "invalid_iana_zone",
    "candidate_dst_gap",
    "candidate_dst_overlap",
    "explicit_zone_shift",
    "explicit_zone_same_instant",
)
BLOCKERS = frozenset((
    "missing_start",
    "legacy_dst_gap",
    "legacy_dst_overlap",
    "invalid_iana_zone",
    "candidate_dst_gap",
    "candidate_dst_overlap",
    "explicit_zone_shift",
))


@dataclass(frozen=True, slots=True)
class CutoverRisk:
    classification: str
    utc_delta_minutes: int | None = None
    overnight_or_zero_duration: bool = False


def inspect_appointment_wall_clock(
    appointment_date: date | None,
    starts_at: time | None,
    ends_at: time | None,
    salon_timezone_name: str | None,
) -> CutoverRisk:
    """Compare legacy Tehran with a proposed IANA zone, without modifying data.

    This does not resolve overnight end dates; those are flagged separately.
    End-time equality is conservatively ambiguous, not assumed to be 24h.
    """
    if appointment_date is None or starts_at is None:
        return CutoverRisk("missing_start")
    if (
        not isinstance(appointment_date, date)
        or not isinstance(starts_at, time)
        or (ends_at is not None and not isinstance(ends_at, time))
    ):
        raise TypeError("Expected canonical date and wall-clock time fields")
    overnight = ends_at is not None and ends_at <= starts_at

    legacy = SimpleNamespace(timezone_name="")
    try:
        legacy_utc = business_local_to_utc(appointment_date, starts_at, legacy)
    except NonexistentBusinessTimeError:
        return CutoverRisk("legacy_dst_gap", overnight_or_zero_duration=overnight)
    except AmbiguousBusinessTimeError:
        return CutoverRisk("legacy_dst_overlap", overnight_or_zero_duration=overnight)

    if salon_timezone_name in ("", None):
        return CutoverRisk(
            "legacy_tehran", utc_delta_minutes=0,
            overnight_or_zero_duration=overnight,
        )
    proposed = SimpleNamespace(timezone_name=salon_timezone_name)
    try:
        candidate_utc = business_local_to_utc(appointment_date, starts_at, proposed)
    except ValidationError:
        return CutoverRisk("invalid_iana_zone", overnight_or_zero_duration=overnight)
    except NonexistentBusinessTimeError:
        return CutoverRisk("candidate_dst_gap", overnight_or_zero_duration=overnight)
    except AmbiguousBusinessTimeError:
        return CutoverRisk("candidate_dst_overlap", overnight_or_zero_duration=overnight)

    delta = candidate_utc - legacy_utc
    minutes = int(delta.total_seconds() // 60)
    return CutoverRisk(
        "explicit_zone_shift" if minutes != 0 else "explicit_zone_same_instant",
        utc_delta_minutes=minutes,
        overnight_or_zero_duration=overnight,
    )
