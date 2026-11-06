"""Read-only, bounded Phase 5.2 wall-clock cutover risk report."""
from __future__ import annotations

from collections import Counter
import json

from django.core.management.base import BaseCommand, CommandError

from apps.orders.models import OrderDetail
from loomera.globalization.timezone_rehearsal import inspect_appointment_wall_clock


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
BLOCKERS = frozenset(
    (
        "missing_start",
        "legacy_dst_gap",
        "legacy_dst_overlap",
        "invalid_iana_zone",
        "candidate_dst_gap",
        "candidate_dst_overlap",
        "explicit_zone_shift",
    )
)


def audit_appointments(records, *, max_appointments: int) -> dict:
    """Consume at most N+1 ORM rows; return aggregate-only, deterministic JSON data."""
    counts = Counter({key: 0 for key in CLASSIFICATIONS})
    scanned = 0
    truncated = False
    overnight = 0
    max_absolute_shift = 0
    for day, start, end, timezone_name in records:
        if scanned >= max_appointments:
            truncated = True
            break
        risk = inspect_appointment_wall_clock(day, start, end, timezone_name)
        counts[risk.classification] += 1
        scanned += 1
        if risk.overnight_or_zero_duration:
            overnight += 1
        if risk.utc_delta_minutes is not None:
            max_absolute_shift = max(
                max_absolute_shift, abs(risk.utc_delta_minutes)
            )
    blocking_rows = sum(counts[key] for key in BLOCKERS)
    return {
        "phase": "5.2",
        "scan_limit": max_appointments,
        "appointments_examined": scanned,
        "scan_complete": not truncated,
        "classifications": dict(sorted(counts.items())),
        "overnight_or_zero_duration_count": overnight,
        "largest_candidate_utc_shift_minutes": max_absolute_shift,
        "blocking_appointment_count": blocking_rows,
        "human_review_required": bool(blocking_rows or overnight or truncated),
        "cutover_authorized": False,
        "writes_performed": 0,
    }


class Command(BaseCommand):
    help = (
        "Read-only Phase 5.2 appointment timezone risk analysis. "
        "No IDs/PII, migration, or appointment edits."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-appointments", type=int, default=5000,
            help="Maximum rows scanned; 1..50000. Reports truncation.",
        )
        parser.add_argument(
            "--json", action="store_true", help="Emit aggregate JSON"
        )
        parser.add_argument(
            "--fail-on-risk", action="store_true",
            help="Return nonzero when risk is present or scan is truncated",
        )

    def handle(self, *args, **options):
        limit = options.get("max_appointments", 5000)
        if limit is None or not 1 <= limit <= 50000:
            raise CommandError("--max-appointments must be between 1 and 50000")
        records = (
            OrderDetail.objects.order_by("pk")
            .values_list(
                "date", "time", "end_time", "salon__timezone_name"
            )[: limit + 1]
            .iterator(chunk_size=500)
        )
        report = audit_appointments(records, max_appointments=limit)
        rendered = json.dumps(report, sort_keys=True, ensure_ascii=False)
        if options.get("json"):
            self.stdout.write(rendered)
        else:
            self.stdout.write("Phase 5.2 timezone cutover audit (read-only):")
            for key, value in sorted(report.items()):
                self.stdout.write(f"{key}: {value}")
        if options.get("fail_on_risk") and report["human_review_required"]:
            raise CommandError(
                "Timezone cutover requires human review or a complete scan; "
                "no records were changed."
            )
