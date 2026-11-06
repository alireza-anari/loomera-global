"""Phase 6.4: offline-only, non-mutating legacy/ISO shadow comparison.

No ORM, Django connection, database migrations, deployment, or PII output.
A structurally clean comparison is NOT authorization for any cutover.
"""
from __future__ import annotations

from datetime import date, timedelta
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loomera.globalization.weekdays import (
    iso_to_legacy_weekday,
    legacy_to_iso_weekday,
    legacy_opening_day_from_date,
)

MAX_ROWS = 10000
MAX_CALENDAR_PROBES = 2500000
SOURCE_FIELDS = frozenset((
    "row_id", "salon_id", "day_of_week", "is_closed",
    "open_time", "close_time", "timezone_name",
))
SHADOW_FIELDS = SOURCE_FIELDS | {"iso_weekday"}
TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")


class WeekdayCutoverInputError(ValueError):
    """An invalid offline input contract, never echoing record values."""


def _valid_id(value):
    return type(value) is int and value > 0


def _valid_day(value):
    return type(value) is int and 1 <= value <= 7


def _valid_timezone(value):
    if type(value) is not str or not value or len(value) > 64:
        return False
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def _valid_clock(value):
    return type(value) is str and TIME_RE.fullmatch(value) is not None


def _inspect(rows, *, shadow):
    if type(rows) is not list or not 1 <= len(rows) <= MAX_ROWS:
        raise WeekdayCutoverInputError("offline row count outside the bounded contract")
    ids = {}
    day_map = {}
    iso_map = {}
    salons = set()
    zones_by_salon = {}
    counts = {
        "invalid_identifiers": 0,
        "invalid_legacy_days": 0,
        "invalid_time_windows": 0,
        "unverified_or_unsupported_timezones": 0,
        "duplicate_row_ids": 0,
        "duplicate_salon_legacy_days": 0,
        "duplicate_salon_iso_days": 0,
        "invalid_or_mismatched_iso_days": 0,
        "inconsistent_salon_timezones": 0,
    }
    for row in rows:
        if type(row) is not dict or frozenset(row) != (
            SHADOW_FIELDS if shadow else SOURCE_FIELDS
        ):
            raise WeekdayCutoverInputError("offline row shape is not allowed")
        row_id, salon_id, legacy_day = (
            row["row_id"], row["salon_id"], row["day_of_week"]
        )
        valid_identity = _valid_id(row_id) and _valid_id(salon_id)
        valid_legacy = _valid_day(legacy_day)
        if not valid_identity:
            counts["invalid_identifiers"] += 1
        if not valid_legacy:
            counts["invalid_legacy_days"] += 1
        closed, opened, closes = (
            row["is_closed"], row["open_time"], row["close_time"]
        )
        if (
            type(closed) is not bool
            or (closed and (opened is not None or closes is not None))
            or (
                closed is False
                and (
                    not _valid_clock(opened)
                    or not _valid_clock(closes)
                    or opened >= closes
                )
            )
        ):
            counts["invalid_time_windows"] += 1
        if not _valid_timezone(row["timezone_name"]):
            counts["unverified_or_unsupported_timezones"] += 1
        if shadow:
            iso = row["iso_weekday"]
            if (
                not _valid_day(iso) or not valid_legacy
                or iso != legacy_to_iso_weekday(legacy_day)
            ):
                counts["invalid_or_mismatched_iso_days"] += 1
        if not valid_identity:
            continue
        salons.add(salon_id)
        if salon_id in zones_by_salon:
            if zones_by_salon[salon_id] != row["timezone_name"]:
                counts["inconsistent_salon_timezones"] += 1
        else:
            zones_by_salon[salon_id] = row["timezone_name"]
        if row_id in ids:
            counts["duplicate_row_ids"] += 1
        else:
            ids[row_id] = row
        if valid_legacy:
            key = (salon_id, legacy_day)
            if key in day_map:
                counts["duplicate_salon_legacy_days"] += 1
            else:
                day_map[key] = (closed, opened, closes, row["timezone_name"])
        if shadow and _valid_day(row["iso_weekday"]):
            iso_key = (salon_id, row["iso_weekday"])
            if iso_key in iso_map:
                counts["duplicate_salon_iso_days"] += 1
            else:
                iso_map[iso_key] = (closed, opened, closes, row["timezone_name"])
    counts["missing_legacy_days"] = 7 * len(salons) - len(day_map)
    if shadow:
        counts["missing_iso_days"] = 7 * len(salons) - len(iso_map)
    return {
        "ids": ids, "day_map": day_map, "iso_map": iso_map,
        "salons": salons, "counts": counts,
    }


def compare_weekday_shadow(
    source_rows, shadow_rows, *, expected_rows, expected_salons,
    sample_start, sample_days, timezone_provenance_verified,
):
    """Compare authorized *in-memory* offline fixtures, never touch DB.

    A 7-day schedule repeats by weekday. Calendar probes additionally verify
    mapping parity across an operator-chosen date horizon (incl. leap/DST
    boundaries); timezone *instant* equivalence needs Phase 5 evidence.
    """
    if (
        type(expected_rows) is not int or not 1 <= expected_rows <= MAX_ROWS
        or type(expected_salons) is not int
        or not 1 <= expected_salons <= MAX_ROWS
        or type(sample_start) is not date
        or type(sample_days) is not int or not 7 <= sample_days <= 1461
        or expected_salons * sample_days > MAX_CALENDAR_PROBES
        or type(timezone_provenance_verified) is not bool
    ):
        raise WeekdayCutoverInputError("invalid offline comparison bounds")
    before = _inspect(source_rows, shadow=False)
    after = _inspect(shadow_rows, shadow=True)
    source_ids, shadow_ids = before["ids"], after["ids"]
    common = source_ids.keys() & shadow_ids.keys()
    changed = sum(
        any(source_ids[id_][field] != shadow_ids[id_][field]
            for field in SOURCE_FIELDS)
        for id_ in common
    )
    salons = before["salons"] | after["salons"]
    mismatched_day_probes = 0
    # Retain a genuine date probe, not just a row-key comparison. Comparison
    # values include closure, open/close times and declared IANA zone.
    for offset in range(sample_days):
        day = sample_start + timedelta(days=offset)
        source_day = legacy_opening_day_from_date(day)
        iso_day = day.isoweekday()
        for salon_id in salons:
            old = before["day_map"].get((salon_id, source_day))
            new = after["iso_map"].get((salon_id, iso_day))
            if old != new:
                mismatched_day_probes += 1
    missing = len(source_ids.keys() - shadow_ids.keys())
    unexpected = len(shadow_ids.keys() - source_ids.keys())
    source_issues = sum(before["counts"].values())
    shadow_issues = sum(after["counts"].values())
    reasons = []
    if len(source_rows) != expected_rows or len(shadow_rows) != expected_rows:
        reasons.append("declared_record_count_mismatch")
    if len(before["salons"]) != expected_salons or len(after["salons"]) != expected_salons:
        reasons.append("declared_salon_count_mismatch")
    if source_issues:
        reasons.append("legacy_source_integrity_blockers")
    if shadow_issues:
        reasons.append("candidate_shadow_integrity_blockers")
    if missing or unexpected:
        reasons.append("missing_or_unexpected_row_identity")
    if changed:
        reasons.append("legacy_field_drift")
    if mismatched_day_probes:
        reasons.append("calendar_schedule_parity_mismatch")
    if not timezone_provenance_verified:
        reasons.append("timezone_provenance_unverified")
    if sample_days < 366:
        reasons.append("representative_year_boundary_rehearsal_incomplete")
    reasons = sorted(set(reasons))
    return {
        "schema_version": 1,
        "phase": "6.4",
        "mode": "operator_declared_sanitized_offline_comparison",
        "source_rows": len(source_rows),
        "shadow_rows": len(shadow_rows),
        "declared_rows": expected_rows,
        "declared_salons": expected_salons,
        "source_salons_observed": len(before["salons"]),
        "shadow_salons_observed": len(after["salons"]),
        "source_issues": dict(sorted(before["counts"].items())),
        "shadow_issues": dict(sorted(after["counts"].items())),
        "missing_shadow_row_ids_count": missing,
        "unexpected_shadow_row_ids_count": unexpected,
        "modified_legacy_field_rows": changed,
        "calendar_probe_days": sample_days,
        "calendar_probe_count": sample_days * len(salons),
        "calendar_mismatched_probes": mismatched_day_probes,
        "operator_declared_timezone_provenance": timezone_provenance_verified,
        "structural_parity_verified": not reasons,
        "stop_reasons": reasons,
        "human_review_required": True,
        "migration_approved": False,
        "rollback_approved": False,
        "cutover_authorized": False,
        "production_deployment_authorized": False,
        "database_reads": 0,
        "writes_performed": 0,
    }
