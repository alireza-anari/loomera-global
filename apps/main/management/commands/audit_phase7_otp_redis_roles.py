"""Read-only, redacted Phase 7.31 Redis runtime-role audit command."""
from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from loomera.globalization.otp_redis_runtime_role_policy import (
    audit_runtime_redis_roles,
)


class Command(BaseCommand):
    help = (
        "Audit Redis cache/OTP/Celery role separation from settings only; "
        "does not connect to Redis or authorize Production."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--json", action="store_true", dest="as_json",
            help="Print the redacted machine-readable audit document.",
        )

    def handle(self, *args, **options):
        report = audit_runtime_redis_roles(settings)
        if options.get("as_json"):
            self.stdout.write(json.dumps(
                report, ensure_ascii=True, sort_keys=True,
            ))
            return

        self.stdout.write(
            f"Phase {report['phase']} Redis runtime-role audit "
            f"environment={report['environment']}"
        )
        for role in report["roles"]:
            self.stdout.write(
                "ROLE {name}: active={active} status={status} "
                "tls={tls_enabled} named_acl_user={named_acl_user_present} "
                "password={password_present} endpoint={endpoint_group} "
                "principal={principal_group}".format(**role)
            )
        for finding in report["findings"]:
            self.stdout.write(f"BLOCKER {finding}")
        self.stdout.write(
            "RELEASE_GATE=BLOCKED "
            "(configuration inventory is not server-side ACL or ingress proof)"
        )
