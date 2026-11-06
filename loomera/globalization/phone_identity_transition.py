"""Phase 7.2: pure offline phone identity shadow reconciliation; never live auth.

Raw phone numbers remain personal data. Only aggregate counts/constant
reason codes are returned. No database, login, OTP or SMS calls are made.
"""
from __future__ import annotations

import re

from loomera.globalization.phone_collision_audit import (
    MAX_ACCOUNTS,
    preview_phone_identity_collisions,
)
from loomera.globalization.phone_identity import (
    PhoneIdentityInputError,
    to_candidate_e164,
)

LEGACY_FIELDS = frozenset(("account_id", "mobile_number", "is_active"))
SHADOW_FIELDS = LEGACY_FIELDS | {"canonical_mobile_number"}
LEGACY_STORAGE_RE = re.compile(r"09[0-9]{9}\Z")


def _scan(rows, *, shadow: bool, default_country: str):
    if type(rows) is not list or not 1 <= len(rows) <= MAX_ACCOUNTS:
        raise PhoneIdentityInputError("invalid offline identity row bounds")
    by_id = {}
    canonical_id = {}
    invalid_ids = duplicates = legacy_unparseable = legacy_noncanonical = 0
    shadow_mismatches = shadow_collisions = 0
    active = inactive = 0
    for row in rows:
        if type(row) is not dict or frozenset(row) != (
            SHADOW_FIELDS if shadow else LEGACY_FIELDS
        ):
            raise PhoneIdentityInputError("invalid offline identity row schema")
        ident, mobile, state = (
            row["account_id"], row["mobile_number"], row["is_active"]
        )
        if type(state) is not bool:
            raise PhoneIdentityInputError("invalid legacy account status")
        active += int(state)
        inactive += int(not state)
        id_valid = type(ident) is int and ident > 0
        if not id_valid:
            invalid_ids += 1
        elif ident in by_id:
            duplicates += 1
        else:
            by_id[ident] = row
        if type(mobile) is not str or LEGACY_STORAGE_RE.fullmatch(mobile) is None:
            legacy_noncanonical += 1
        try:
            expected = to_candidate_e164(mobile, default_country=default_country)
        except PhoneIdentityInputError:
            expected = None
            legacy_unparseable += 1
        if shadow:
            candidate = row["canonical_mobile_number"]
            if type(candidate) is not str or expected is None or candidate != expected:
                shadow_mismatches += 1
            if type(candidate) is str and id_valid:
                if candidate in canonical_id and canonical_id[candidate] != ident:
                    shadow_collisions += 1
                else:
                    canonical_id[candidate] = ident
    return {
        "by_id": by_id, "total": len(rows),
        "active": active, "inactive": inactive,
        "invalid_ids": invalid_ids, "duplicate_ids": duplicates,
        "legacy_unparseable": legacy_unparseable,
        "legacy_noncanonical": legacy_noncanonical,
        "shadow_mismatches": shadow_mismatches,
        "shadow_collisions": shadow_collisions,
    }


def compare_phone_identity_shadow(
    source_rows,
    proposed_shadow_rows,
    *,
    expected_accounts: int,
    expected_active_accounts: int,
    expected_inactive_accounts: int,
    default_country: str = "IR",
) -> dict:
    """Fail-closed 1:1 ID, login field, active state and canonical mapping.

    Input must be an independently authorized *offline* export. Inactive and
    deleted placeholders are NOT recycled or automatically reactivated.
    """
    if (
        type(expected_accounts) is not int
        or not 1 <= expected_accounts <= MAX_ACCOUNTS
        or type(expected_active_accounts) is not int
        or type(expected_inactive_accounts) is not int
        or expected_active_accounts < 0
        or expected_inactive_accounts < 0
        or expected_active_accounts + expected_inactive_accounts != expected_accounts
    ):
        raise PhoneIdentityInputError("invalid expected account scope")
    source = _scan(source_rows, shadow=False, default_country=default_country)
    shadow = _scan(proposed_shadow_rows, shadow=True, default_country=default_country)
    preview = preview_phone_identity_collisions(
        source_rows, expected_accounts=expected_accounts,
        default_country=default_country,
    )
    source_ids, shadow_ids = source["by_id"], shadow["by_id"]
    common = source_ids.keys() & shadow_ids.keys()
    missing = len(source_ids.keys() - shadow_ids.keys())
    additional = len(shadow_ids.keys() - source_ids.keys())
    changed_mobile = sum(
        source_ids[key]["mobile_number"] != shadow_ids[key]["mobile_number"]
        for key in common
    )
    changed_status = sum(
        source_ids[key]["is_active"] != shadow_ids[key]["is_active"]
        for key in common
    )
    inactive_to_active = sum(
        source_ids[key]["is_active"] is False
        and shadow_ids[key]["is_active"] is True
        for key in common
    )
    reasons = []
    if (
        source["total"] != expected_accounts
        or shadow["total"] != expected_accounts
        or source["active"] != expected_active_accounts
        or shadow["active"] != expected_active_accounts
        or source["inactive"] != expected_inactive_accounts
        or shadow["inactive"] != expected_inactive_accounts
    ):
        reasons.append("declared_account_scope_or_status_mismatch")
    if missing or additional:
        reasons.append("missing_or_unexpected_shadow_account")
    if (
        source["invalid_ids"] or shadow["invalid_ids"]
        or source["duplicate_ids"] or shadow["duplicate_ids"]
    ):
        reasons.append("duplicate_or_invalid_account_identity")
    if (
        source["legacy_unparseable"] or shadow["legacy_unparseable"]
        or source["legacy_noncanonical"] or shadow["legacy_noncanonical"]
    ):
        reasons.append("legacy_storage_identity_requires_resolution")
    if preview["canonical_collision_extra_accounts_count"] or shadow["shadow_collisions"]:
        reasons.append("canonical_alias_collision")
    if shadow["shadow_mismatches"]:
        reasons.append("shadow_canonical_mapping_mismatch")
    if changed_mobile:
        reasons.append("legacy_login_identifier_modified")
    if changed_status:
        reasons.append("legacy_account_activation_status_modified")
    return {
        "schema_version": 1,
        "phase": "7.2",
        "mode": "offline_identity_shadow_review_only",
        "declared_accounts": expected_accounts,
        "source_accounts_examined": source["total"],
        "shadow_accounts_examined": shadow["total"],
        "declared_active_accounts": expected_active_accounts,
        "declared_inactive_accounts": expected_inactive_accounts,
        "source_active_accounts": source["active"],
        "shadow_active_accounts": shadow["active"],
        "source_inactive_accounts": source["inactive"],
        "shadow_inactive_accounts": shadow["inactive"],
        "missing_shadow_accounts": missing,
        "unexpected_shadow_accounts": additional,
        "source_invalid_account_ids": source["invalid_ids"],
        "shadow_invalid_account_ids": shadow["invalid_ids"],
        "source_duplicate_account_ids": source["duplicate_ids"],
        "shadow_duplicate_account_ids": shadow["duplicate_ids"],
        "source_unparseable_phone_values": source["legacy_unparseable"],
        "shadow_unparseable_phone_values": shadow["legacy_unparseable"],
        "source_noncanonical_legacy_storage": source["legacy_noncanonical"],
        "shadow_noncanonical_legacy_storage": shadow["legacy_noncanonical"],
        "source_canonical_alias_collisions": preview["canonical_collision_extra_accounts_count"],
        "shadow_canonical_alias_collisions": shadow["shadow_collisions"],
        "shadow_canonical_mapping_mismatches": shadow["shadow_mismatches"],
        "legacy_login_identifier_modified_accounts": changed_mobile,
        "account_status_changed_accounts": changed_status,
        "inactive_accounts_activated_in_shadow": inactive_to_active,
        "shadow_identity_structurally_clean": not reasons,
        "stop_reasons": sorted(set(reasons)),
        "historical_otp_cache_key_bridge_verified": False,
        "existing_sessions_transition_verified": False,
        "phone_number_plan_allocation_verified": False,
        "shadow_uniqueness_migration_authorized": False,
        "account_reactivation_authorized": False,
        "production_identity_cutover_authorized": False,
        "human_owner_review_required": True,
        "database_reads": 0,
        "writes_performed": 0,
    }
