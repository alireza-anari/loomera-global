"""Read-only, redacted Redis role inventory from Django settings only."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.main.cache_preflight import build_redis_role_inventory


class Command(BaseCommand):
    help = (
        "Print a redacted Redis role inventory from Django settings without "
        "opening Redis or database connections."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print the redacted inventory as JSON.",
        )

    def handle(self, *args, **options):
        payload = build_redis_role_inventory()
        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self.stdout.write("=== Loomera Redis Runtime Roles ===")
        self.stdout.write(f"environment={payload['environment']}")
        self.stdout.write(f"api_otp_cache_alias={payload['api_otp_cache_alias']}")
        for role, details in payload["roles"].items():
            self.stdout.write(
                f"{role}: status={details.get('status', 'unknown')} "
                f"endpoint_group={details.get('endpoint_group', '-') or '-'} "
                f"principal_group={details.get('principal_group', '-') or '-'} "
                f"database_index={details.get('database_index', '-')}"
            )
        for warning in payload["warnings"]:
            self.stdout.write(self.style.WARNING(f"WARN {warning}"))
        self.stdout.write("redis_connections_opened=false")
        self.stdout.write("database_connections_opened=false")
        self.stdout.write("secrets_emitted=false")
        self.stdout.write("production_release_authorized=false")
