"""Read-only pre-cutover audit of salon timezone coverage and booking snapshots."""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.orders.models import OrderDetail
from apps.salons.models import Salon
from loomera.globalization.calendar_time import validate_iana_timezone_name


class Command(BaseCommand):
    help = (
        "Inspect explicit IANA salon zones and canonical appointment field coverage "
        "without modifying any database records."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--json", action="store_true", help="Print deterministic JSON audit output"
        )
        parser.add_argument(
            "--fail-on-invalid",
            action="store_true",
            help="Return a nonzero exit code if invalid explicit IANA zones exist",
        )

    def handle(self, *args, **options):
        total_salons = Salon.objects.count()
        legacy = Salon.objects.filter(timezone_name="").count()
        explicit_names = sorted(
            Salon.objects.exclude(timezone_name="").values_list(
                "timezone_name", flat=True
            ).distinct()
        )
        invalid_names = []
        for name in explicit_names:
            try:
                validate_iana_timezone_name(name)
            except ValidationError:
                invalid_names.append(name)

        appointments = OrderDetail.objects.all()
        report = {
            "salons_total": total_salons,
            "salons_legacy_unset_timezone": legacy,
            "salons_with_explicit_timezone": total_salons - legacy,
            "explicit_timezones_distinct": len(explicit_names),
            "invalid_explicit_timezone_count": len(invalid_names),
            "appointments_total": appointments.count(),
            "appointments_legacy_unset_timezone": appointments.filter(
                salon__timezone_name=""
            ).count(),
            "appointments_with_date_and_time": appointments.filter(
                date__isnull=False, time__isnull=False
            ).count(),
            "appointments_missing_date_or_time": appointments.filter(
                Q(date__isnull=True) | Q(time__isnull=True)
            ).count(),
            "writes_performed": 0,
        }
        # Report aggregates only; do not expose business/customer identifiers.
        result = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if options["json"]:
            self.stdout.write(result)
        else:
            self.stdout.write("Phase 5 timezone data audit (read-only):")
            for key, value in sorted(report.items()):
                self.stdout.write(f"{key}: {value}")
        if options["fail_on_invalid"] and invalid_names:
            raise CommandError(
                "Invalid explicit IANA timezone(s) detected; fix records before cutover."
            )
