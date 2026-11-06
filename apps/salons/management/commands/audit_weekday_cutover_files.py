"""Phase 6.4 offline-only weekday comparison; never connects to a database."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from loomera.globalization.weekday_cutover_audit import (
    WeekdayCutoverInputError,
    compare_weekday_shadow,
)

MARKER = "LOOMERA_PHASE6_OFFLINE_SANITIZED_CONFIRMATION"
MARKER_VALUE = "I_CONFIRM_AUTHORIZED_OFFLINE_SANITIZED_COPY"
MAX_FILE_BYTES = 4_000_000
MANIFEST_FIELDS = frozenset((
    "schema_version", "source_kind", "authorization_reference",
    "source_sha256", "shadow_sha256", "expected_rows", "expected_salons",
    "sample_start", "sample_days", "timezone_provenance",
    "contains_customer_pii", "operation",
))


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise WeekdayCutoverInputError("duplicate JSON object keys")
        value[key] = item
    return value


def _no_nonfinite(value):
    raise WeekdayCutoverInputError("non-finite JSON number forbidden")


def _bounded_json_file(filename):
    try:
        path = Path(filename)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise WeekdayCutoverInputError("offline file missing or oversized")
        raw = path.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            raise WeekdayCutoverInputError("offline file oversized")
        decoded = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=_no_nonfinite,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise WeekdayCutoverInputError("offline JSON input could not be validated") from exc
    return raw, decoded


def _validate_manifest(manifest):
    if type(manifest) is not dict or frozenset(manifest) != MANIFEST_FIELDS:
        raise WeekdayCutoverInputError("unsupported offline manifest schema")
    if (
        type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or manifest["source_kind"] != "operator_authorized_sanitized_offline_copy"
        or manifest["operation"] != "shadow_iso_weekday_preview_only"
        or manifest["contains_customer_pii"] is not False
        or manifest["timezone_provenance"] not in ("operator_verified", "unverified")
        or type(manifest["authorization_reference"]) is not str
        or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./:-]{3,79}",
                        manifest["authorization_reference"]) is None
    ):
        raise WeekdayCutoverInputError("missing offline provenance declaration")
    for name in ("source_sha256", "shadow_sha256"):
        sha = manifest[name]
        if type(sha) is not str or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
            raise WeekdayCutoverInputError("missing SHA-256 integrity declaration")
    if (
        type(manifest["sample_start"]) is not str
        or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}",
                        manifest["sample_start"]) is None
    ):
        raise WeekdayCutoverInputError("invalid calendar window declaration")
    try:
        start = date.fromisoformat(manifest["sample_start"])
    except ValueError as exc:
        raise WeekdayCutoverInputError("invalid calendar window declaration") from exc
    return start


def _checked_payload(payload, representation):
    if (
        type(payload) is not dict
        or frozenset(payload) != {"schema_version", "representation", "rows"}
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["representation"] != representation
    ):
        raise WeekdayCutoverInputError("unsupported weekday fixture representation")
    return payload["rows"]


class Command(BaseCommand):
    help = (
        "Offline-only, bounded and fail-closed legacy/ISO shadow comparison; "
        "no database access, no migration or cutover authority."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--source", required=True)
        parser.add_argument("--shadow", required=True)
        parser.add_argument("--acknowledge-offline-sanitized-copy",
                            action="store_true")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        if (
            not options.get("acknowledge_offline_sanitized_copy")
            or os.environ.get(MARKER) != MARKER_VALUE
        ):
            raise CommandError(
                "Offline sanitized-copy acknowledgment required; no file opened."
            )
        try:
            _, manifest = _bounded_json_file(options["manifest"])
            start = _validate_manifest(manifest)
            source_bytes, source = _bounded_json_file(options["source"])
            shadow_bytes, shadow = _bounded_json_file(options["shadow"])
            if (
                hashlib.sha256(source_bytes).hexdigest() != manifest["source_sha256"]
                or hashlib.sha256(shadow_bytes).hexdigest() != manifest["shadow_sha256"]
            ):
                raise WeekdayCutoverInputError("offline snapshot checksum mismatch")
            source_rows = _checked_payload(source, "legacy_saturday_1")
            shadow_rows = _checked_payload(shadow, "legacy_with_iso_shadow")
            report = compare_weekday_shadow(
                source_rows, shadow_rows,
                expected_rows=manifest["expected_rows"],
                expected_salons=manifest["expected_salons"],
                sample_start=start,
                sample_days=manifest["sample_days"],
                timezone_provenance_verified=(
                    manifest["timezone_provenance"] == "operator_verified"
                ),
            )
        except (WeekdayCutoverInputError, ValueError, TypeError) as exc:
            raise CommandError(
                "Offline weekday snapshot integrity gate rejected input; "
                "no records or identifiers disclosed."
            ) from exc
        report["byte_checksums_matched"] = True
        report["file_access_authorization_operator_declared"] = True
        report["file_access_authorization_independently_verified"] = False
        self.stdout.write(json.dumps(report, sort_keys=True, ensure_ascii=False))
        if not report["structural_parity_verified"]:
            raise CommandError(
                "Offline weekday comparison found blocking integrity or parity "
                "issues. No migration or cutover authorized."
            )
