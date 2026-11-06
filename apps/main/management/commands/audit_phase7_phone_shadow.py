"""Strict offline source↔shadow identity preflight. NEVER accesses user DB."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from django.core.management.base import BaseCommand, CommandError

from loomera.globalization.phone_identity import PhoneIdentityInputError
from loomera.globalization.phone_identity_transition import (
    compare_phone_identity_shadow,
)

ACK_ENV = "LOOMERA_PHASE7_AUTHORIZED_OFFLINE_PHONE_EXPORT"
ACK_VALUE = "I_CONFIRM_AUTHORIZED_SENSITIVE_OFFLINE_COPY"
MAX_FILE_BYTES = 5_000_000
MANIFEST_FIELDS = frozenset((
    "schema_version", "operation", "scope", "authorization_reference",
    "source_sha256", "shadow_sha256", "expected_accounts",
    "expected_active_accounts", "expected_inactive_accounts",
    "default_country", "contains_phone_personal_data",
))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PhoneIdentityInputError("duplicate JSON keys")
        result[key] = value
    return result


def _reject_nonfinite(_):
    raise PhoneIdentityInputError("invalid JSON number")


def _read_json(path_text):
    try:
        path = Path(path_text)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise PhoneIdentityInputError("offline file missing or oversized")
        raw = path.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            raise PhoneIdentityInputError("offline file oversized")
        parsed = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise PhoneIdentityInputError("offline JSON invalid") from exc
    return raw, parsed


def _validate_manifest(manifest):
    if (
        type(manifest) is not dict
        or frozenset(manifest) != MANIFEST_FIELDS
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or manifest["operation"] != "compare_phone_e164_shadow_only"
        or manifest["scope"] != "authorized_isolated_phone_identity_export"
        or manifest["contains_phone_personal_data"] is not True
        or type(manifest["authorization_reference"]) is not str
        or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_./:-]{3,79}",
            manifest["authorization_reference"],
        ) is None
        or type(manifest["default_country"]) is not str
        or re.fullmatch(r"[A-Z]{2}", manifest["default_country"]) is None
    ):
        raise PhoneIdentityInputError("invalid offline manifest")
    for name in ("source_sha256", "shadow_sha256"):
        if (
            type(manifest[name]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", manifest[name]) is None
        ):
            raise PhoneIdentityInputError("invalid SHA-256 declaration")
    for name in (
        "expected_accounts", "expected_active_accounts", "expected_inactive_accounts"
    ):
        if type(manifest[name]) is not int:
            raise PhoneIdentityInputError("invalid declared scope")


def _payload(data, representation):
    if (
        type(data) is not dict
        or frozenset(data) != {"schema_version", "representation", "rows"}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or data["representation"] != representation
    ):
        raise PhoneIdentityInputError("unsupported offline representation")
    return data["rows"]


class Command(BaseCommand):
    help = (
        "Compare isolated authorized sensitive offline phone source/shadow "
        "files; aggregate-only, zero database access, no migration."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--source", required=True)
        parser.add_argument("--shadow", required=True)
        parser.add_argument("--acknowledge-sensitive-offline-copy", action="store_true")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        if (
            not options.get("acknowledge_sensitive_offline_copy")
            or os.environ.get(ACK_ENV) != ACK_VALUE
        ):
            raise CommandError(
                "Both sensitive offline copy acknowledgments are required."
            )
        try:
            _, manifest = _read_json(options["manifest"])
            _validate_manifest(manifest)
            source_bytes, source = _read_json(options["source"])
            shadow_bytes, shadow = _read_json(options["shadow"])
            if (
                hashlib.sha256(source_bytes).hexdigest() != manifest["source_sha256"]
                or hashlib.sha256(shadow_bytes).hexdigest() != manifest["shadow_sha256"]
            ):
                raise PhoneIdentityInputError("offline file SHA-256 mismatch")
            result = compare_phone_identity_shadow(
                _payload(source, "existing_user_mobile_number"),
                _payload(shadow, "existing_user_plus_canonical_shadow"),
                expected_accounts=manifest["expected_accounts"],
                expected_active_accounts=manifest["expected_active_accounts"],
                expected_inactive_accounts=manifest["expected_inactive_accounts"],
                default_country=manifest["default_country"],
            )
        except (PhoneIdentityInputError, ValueError, TypeError) as exc:
            raise CommandError(
                "Phone identity offline preflight rejected input; "
                "no personal data or identifiers disclosed."
            ) from exc
        result["source_shadow_byte_hashes_verified"] = True
        result["authorization_operator_declared_not_independently_verified"] = True
        self.stdout.write(json.dumps(result, sort_keys=True, ensure_ascii=False))
        if not result["shadow_identity_structurally_clean"]:
            raise CommandError(
                "Phone shadow parity blockers remain; no identity cutover authorized."
            )
