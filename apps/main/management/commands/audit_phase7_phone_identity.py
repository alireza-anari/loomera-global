"""Offline-only phone identity preview; source files may contain phone PII."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from django.core.management.base import BaseCommand, CommandError

from loomera.globalization.phone_identity import PhoneIdentityInputError
from loomera.globalization.phone_collision_audit import (
    preview_phone_identity_collisions,
)

MARKER = "LOOMERA_PHASE7_AUTHORIZED_OFFLINE_PHONE_EXPORT"
MARKER_VALUE = "I_CONFIRM_AUTHORIZED_SENSITIVE_OFFLINE_COPY"
MAX_FILE_BYTES = 5_000_000
MANIFEST_KEYS = frozenset((
    "schema_version", "scope", "authorization_reference", "export_sha256",
    "expected_accounts", "default_country", "contains_phone_personal_data",
    "operation",
))


def _unique_object(pairs):
    mapping = {}
    for key, value in pairs:
        if key in mapping:
            raise PhoneIdentityInputError("duplicate JSON keys")
        mapping[key] = value
    return mapping


def _reject_nonfinite(_):
    raise PhoneIdentityInputError("invalid JSON numeric literal")


def _strict_json(path_text):
    try:
        path = Path(path_text)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise PhoneIdentityInputError("offline file missing or oversized")
        contents = path.read_bytes()
        if len(contents) > MAX_FILE_BYTES:
            raise PhoneIdentityInputError("offline file oversized")
        data = json.loads(
            contents.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PhoneIdentityInputError("invalid offline JSON file") from exc
    return contents, data


def _validate_manifest(data):
    if (
        type(data) is not dict
        or frozenset(data) != MANIFEST_KEYS
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or data["scope"] != "authorized_isolated_phone_identity_export"
        or data["operation"] != "canonical_collision_preview_only"
        or data["contains_phone_personal_data"] is not True
        or type(data["authorization_reference"]) is not str
        or re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_./:-]{3,79}",
            data["authorization_reference"]
        ) is None
        or type(data["export_sha256"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", data["export_sha256"]) is None
    ):
        raise PhoneIdentityInputError("invalid offline provenance manifest")
    if (
        type(data["expected_accounts"]) is not int
        or not 1 <= data["expected_accounts"] <= 50000
        or type(data["default_country"]) is not str
        or re.fullmatch(r"[A-Z]{2}", data["default_country"]) is None
    ):
        raise PhoneIdentityInputError("invalid manifest scope or country")


class Command(BaseCommand):
    help = (
        "Audit ONLY an explicitly authorized sensitive offline phone export; "
        "aggregate output, no database or account modifications."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--input", required=True)
        parser.add_argument("--acknowledge-sensitive-offline-copy", action="store_true")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        if (
            not options.get("acknowledge_sensitive_offline_copy")
            or os.environ.get(MARKER) != MARKER_VALUE
        ):
            raise CommandError(
                "Sensitive offline copy requires two acknowledgments; "
                "no file has been opened."
            )
        try:
            _, manifest = _strict_json(options["manifest"])
            _validate_manifest(manifest)
            raw_bytes, payload = _strict_json(options["input"])
            if hashlib.sha256(raw_bytes).hexdigest() != manifest["export_sha256"]:
                raise PhoneIdentityInputError("invalid export integrity checksum")
            if (
                type(payload) is not dict
                or frozenset(payload) != {"schema_version", "representation", "rows"}
                or type(payload["schema_version"]) is not int
                or payload["schema_version"] != 1
                or payload["representation"] != "existing_user_mobile_number"
            ):
                raise PhoneIdentityInputError("unsupported account export format")
            result = preview_phone_identity_collisions(
                payload["rows"],
                expected_accounts=manifest["expected_accounts"],
                default_country=manifest["default_country"],
            )
        except (PhoneIdentityInputError, ValueError, TypeError) as exc:
            raise CommandError(
                "Offline phone identity audit rejected input; no records, "
                "phone values or identifiers disclosed."
            ) from exc
        result["export_checksum_verified"] = True
        result["authorization_operator_declared_not_independently_verified"] = True
        self.stdout.write(json.dumps(result, sort_keys=True, ensure_ascii=False))
        if not result["preflight_structurally_clean"]:
            raise CommandError(
                "Phone identity preflight found blockers; account migration "
                "and canonical uniqueness cutover remain forbidden."
            )
