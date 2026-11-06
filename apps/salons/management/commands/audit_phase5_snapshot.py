"""Explicitly gated, read-only and consistent Phase 5.3 PostGIS clone audit.

Never run on a live deployment. Requires both a sanitized-clone DB name and
two deliberate operator acknowledgments. Database-enforced PostgreSQL
REPEATABLE READ READ ONLY protects records even if application code changes.
"""
from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.orders.models import OrderDetail
from loomera.globalization.snapshot_audit import (
    SnapshotAuditIntegrityError,
    scan_appointment_snapshot,
)


SNAPSHOT_MARKER = "LOOMERA_PHASE5_ISOLATED_SANITIZED_SNAPSHOT"
SNAPSHOT_MARKER_VALUE = "I_CONFIRM_ISOLATED_SANITIZED_COPY"


def validate_isolated_snapshot_access(
    *, engine: str, database_name: str, marker: str | None,
    acknowledged: bool, in_atomic_block: bool,
) -> None:
    """Deny ambiguous environments *before issuing any database query*."""
    if not acknowledged or marker != SNAPSHOT_MARKER_VALUE:
        raise CommandError(
            "Explicit authorization is required: set isolated snapshot marker "
            "and --acknowledge-isolated-sanitized-copy."
        )
    if engine != "django.contrib.gis.db.backends.postgis":
        raise CommandError("Phase 5.3 audit requires PostgreSQL/PostGIS.")
    if not isinstance(database_name, str) or not (
        database_name.startswith("test_")
        or database_name.startswith("phase5_snapshot_")
    ):
        raise CommandError(
            "Database must be a dedicated test_ or phase5_snapshot_ clone, "
            "not a live deployment."
        )
    if in_atomic_block:
        raise CommandError(
            "Audit must own its top-level repeatable-read read-only transaction."
        )


class Command(BaseCommand):
    help = (
        "Authorized sanitized PostGIS snapshot audit: read-only keyset scan, "
        "no identifiers in results, no timezone cutover."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--acknowledge-isolated-sanitized-copy", action="store_true",
            help="Explicitly confirm this DB is an authorized sanitized CLONE",
        )
        parser.add_argument(
            "--max-appointments", type=int, default=50000,
            help="Maximum rows to examine (1..1000000); incomplete is not a pass",
        )
        parser.add_argument(
            "--batch-size", type=int, default=500,
            help="Bounded keyset page size (1..5000)",
        )
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--fail-on-incomplete-or-risk", action="store_true",
            help="Fail if scan incomplete or potential timezone risk identified",
        )

    def handle(self, *args, **options):
        validate_isolated_snapshot_access(
            engine=connection.settings_dict["ENGINE"],
            database_name=str(connection.settings_dict.get("NAME", "")),
            marker=os.environ.get(SNAPSHOT_MARKER),
            acknowledged=bool(
                options.get("acknowledge_isolated_sanitized_copy")
            ),
            in_atomic_block=connection.in_atomic_block,
        )
        limit = options.get("max_appointments", 50000)
        size = options.get("batch_size", 500)
        if (
            type(limit) is not int or not 1 <= limit <= 1_000_000
            or type(size) is not int or not 1 <= size <= 5000
        ):
            raise CommandError("Invalid scan limit or batch size.")

        try:
            with transaction.atomic():
                # Must be first SQL statement in this fresh transaction.
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
                    cursor.execute(
                        "SELECT current_setting('transaction_read_only'), "
                        "current_setting('transaction_isolation')"
                    )
                    read_only, isolation = cursor.fetchone()
                if read_only != "on" or isolation != "repeatable read":
                    raise CommandError(
                        "Database did not confirm repeatable-read read-only mode."
                    )
                total = OrderDetail.objects.count()

                def fetch_page(last_pk, requested):
                    # No row payload leaves this command. Primary keys are used
                    # internally only to paginate a consistent snapshot.
                    return list(
                        OrderDetail.objects.filter(pk__gt=last_pk)
                        .order_by("pk")
                        .values_list(
                            "pk",
                            "date",
                            "time",
                            "end_time",
                            "occupied_until",
                            "salon__timezone_name",
                            "order__reminder_due_at",
                        )[:requested]
                    )

                report = scan_appointment_snapshot(
                    fetch_page=fetch_page,
                    total_records=total,
                    max_records=limit,
                    batch_size=size,
                )
        except SnapshotAuditIntegrityError as exc:
            raise CommandError(
                "Snapshot audit integrity error; no cutover evidence accepted."
            ) from exc

        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if options.get("json"):
            self.stdout.write(rendered)
        else:
            self.stdout.write("Phase 5.3 isolated PostGIS snapshot audit:")
            for key, value in sorted(report.items()):
                self.stdout.write(f"{key}: {value}")
        if options.get("fail_on_incomplete_or_risk") and (
            not report["scan_complete"] or report["potential_review_risks_count"]
        ):
            raise CommandError(
                "Snapshot scan incomplete or timezone risks found. "
                "Human signoff remains mandatory even without these risks."
            )
