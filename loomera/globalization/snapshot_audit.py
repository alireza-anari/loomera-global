"""Privacy-preserving, deterministic Phase 5.3 authorized snapshot scan.

Pure aggregation only. The caller owns the PostGIS read-only repeatable-read
transaction and performs the keyset queries. No row identifiers are returned.
No classification is permission to reinterpret a historical booking.
"""
from __future__ import annotations

from collections import Counter

from apps.salons.management.commands.audit_phase5_timezone_cutover import (
    BLOCKERS,
    CLASSIFICATIONS,
)
from loomera.globalization.timezone_rehearsal import inspect_appointment_wall_clock


class SnapshotAuditIntegrityError(ValueError):
    """The expected stable read-only snapshot could not be audited completely."""


def scan_appointment_snapshot(*, fetch_page, total_records: int, max_records: int,
                              batch_size: int) -> dict:
    """Scan sorted (pk,date,time,end,occupied,zone,reminder) tuples via keyset.

    Never emit a PK, PII, an individual date/time, a zone value, or a reminder
    instant. A missing/skipped/duplicated source row cannot be certified by
    aggregate counts alone; database consistency is enforced by the caller.
    """
    if (
        type(total_records) is not int or total_records < 0
        or type(max_records) is not int or not 1 <= max_records <= 1_000_000
        or type(batch_size) is not int or not 1 <= batch_size <= 5000
    ):
        raise ValueError("invalid snapshot scan size or count")
    counts = Counter({name: 0 for name in CLASSIFICATIONS})
    scanned = 0
    last_pk = 0
    overnight = 0
    missing_end = 0
    missing_occupied = 0
    occupied_not_after_start = 0
    reminders_present = 0
    greatest_shift = 0
    scan_target = min(total_records, max_records)

    while scanned < scan_target:
        requested = min(batch_size, scan_target - scanned)
        page = fetch_page(last_pk, requested)
        if not isinstance(page, (list, tuple)) or not 1 <= len(page) <= requested:
            raise SnapshotAuditIntegrityError("snapshot page count invalid")
        for record in page:
            if not isinstance(record, (list, tuple)) or len(record) != 7:
                raise SnapshotAuditIntegrityError("snapshot row shape invalid")
            pk, day, start, end, occupied, zone, reminder = record
            if type(pk) is not int or pk <= last_pk:
                raise SnapshotAuditIntegrityError("snapshot ordering invalid")
            last_pk = pk
            result = inspect_appointment_wall_clock(day, start, end, zone)
            counts[result.classification] += 1
            scanned += 1
            overnight += int(result.overnight_or_zero_duration)
            missing_end += int(end is None)
            missing_occupied += int(occupied is None)
            occupied_not_after_start += int(
                occupied is not None and start is not None
                and occupied <= start
            )
            reminders_present += int(reminder is not None)
            if result.utc_delta_minutes is not None:
                greatest_shift = max(greatest_shift, abs(result.utc_delta_minutes))
        if len(page) < requested and scanned < scan_target:
            raise SnapshotAuditIntegrityError("snapshot lost rows while paging")

    complete = scanned == total_records
    blockers = sum(counts[key] for key in BLOCKERS)
    risk_total = blockers + overnight + missing_end + occupied_not_after_start
    reasons = []
    if not complete:
        reasons.append("scan_incomplete")
    if blockers:
        reasons.append("candidate_or_legacy_timezone_risks")
    if overnight or occupied_not_after_start:
        reasons.append("wall_clock_rollover_requires_review")
    if missing_end:
        reasons.append("missing_end_time")
    # This is universally true for old appointments, even with all zero risks:
    # explicit metadata may have been entered *after* booking creation.
    reasons.append("historical_timezone_provenance_unverified")
    reasons.append("real_data_approval_and_reconciliation_required")

    return {
        "schema_version": 1,
        "phase": "5.3",
        "source_scope": "operator_declared_isolated_sanitized_postgis_snapshot",
        "transaction_isolation": "repeatable_read_read_only",
        "scan_limit": max_records,
        "batch_size": batch_size,
        "total_appointments_in_snapshot": total_records,
        "appointments_examined": scanned,
        "scan_complete": complete,
        "classifications": dict(sorted(counts.items())),
        "overnight_or_zero_duration_count": overnight,
        "missing_end_time_count": missing_end,
        "missing_occupied_until_count": missing_occupied,
        "occupied_until_not_after_start_count": occupied_not_after_start,
        "appointments_with_reminder_timestamp_count": reminders_present,
        "largest_candidate_utc_shift_minutes": greatest_shift,
        "blocking_appointment_count": blockers,
        "potential_review_risks_count": risk_total,
        "review_reasons": reasons,
        "human_review_required": True,
        "cutover_authorized": False,
        "production_migration_authorized": False,
        "writes_performed": 0,
    }
