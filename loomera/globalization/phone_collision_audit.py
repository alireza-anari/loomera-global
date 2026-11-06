"""Phase 7.1: aggregated, no-PII-output preview of canonical phone collisions.

Accounts in an authorized isolated export may still include real phone PII.
Never emit source rows, raw phone values, hashes or account identifiers.
"""
from __future__ import annotations

from loomera.globalization.phone_identity import (
    PhoneIdentityInputError,
    to_candidate_e164,
)

MAX_ACCOUNTS = 50000


def preview_phone_identity_collisions(
    rows, *, expected_accounts: int, default_country: str = "IR",
) -> dict:
    """Inspect (account_id, phone_number, is_active) for a cutover blocker.

    This function accepts a finite, in-memory list only; it performs no DB
    access or file writes. Its return dictionary is safe to render/log.
    """
    if (
        type(expected_accounts) is not int
        or not 1 <= expected_accounts <= MAX_ACCOUNTS
        or type(rows) is not list
        or not 1 <= len(rows) <= MAX_ACCOUNTS
    ):
        raise PhoneIdentityInputError("invalid bounded offline account count")
    # Validate country even when all phone values are malformed.
    try:
        to_candidate_e164("+4915123456789", default_country=default_country)
    except PhoneIdentityInputError as exc:
        raise PhoneIdentityInputError("invalid country hint") from exc
    first_by_canonical = {}
    seen_account_ids = set()
    invalid_phone = 0
    invalid_account_ids = 0
    duplicate_account_ids = 0
    active_accounts = 0
    inactive_accounts = 0
    candidate_iran = 0
    candidate_other = 0
    collisions = 0
    collisions_involving_active = 0
    for item in rows:
        if (
            type(item) is not dict
            or frozenset(item) != {"account_id", "mobile_number", "is_active"}
        ):
            raise PhoneIdentityInputError("invalid account export row structure")
        account_id = item["account_id"]
        mobile = item["mobile_number"]
        active = item["is_active"]
        if type(active) is not bool:
            raise PhoneIdentityInputError("invalid account status")
        active_accounts += int(active)
        inactive_accounts += int(not active)
        valid_id = type(account_id) is int and account_id > 0
        if not valid_id:
            invalid_account_ids += 1
        elif account_id in seen_account_ids:
            duplicate_account_ids += 1
        else:
            seen_account_ids.add(account_id)
        try:
            e164 = to_candidate_e164(mobile, default_country=default_country)
        except PhoneIdentityInputError:
            invalid_phone += 1
            continue
        candidate_iran += int(e164.startswith("+98"))
        candidate_other += int(not e164.startswith("+98"))
        if not valid_id:
            continue
        existing = first_by_canonical.get(e164)
        if existing is None:
            first_by_canonical[e164] = (account_id, active)
        elif existing[0] != account_id:
            collisions += 1
            collisions_involving_active += int(existing[1] or active)
    reasons = []
    if len(rows) != expected_accounts:
        reasons.append("incomplete_or_mismatched_snapshot_scope")
    if invalid_phone:
        reasons.append("unparseable_phone_identifiers")
    if invalid_account_ids or duplicate_account_ids:
        reasons.append("invalid_or_duplicate_account_ids")
    if collisions:
        reasons.append("canonical_identity_collisions")
    return {
        "schema_version": 1,
        "phase": "7.1",
        "scope": "operator_supplied_offline_account_identity_export",
        "expected_accounts": expected_accounts,
        "accounts_examined": len(rows),
        "active_accounts": active_accounts,
        "inactive_accounts": inactive_accounts,
        "candidate_iran_accounts": candidate_iran,
        "candidate_non_iran_accounts": candidate_other,
        "unparseable_phone_count": invalid_phone,
        "invalid_account_id_count": invalid_account_ids,
        "duplicate_account_id_count": duplicate_account_ids,
        "canonical_collision_extra_accounts_count": collisions,
        "canonical_collisions_involving_active_accounts_count": (
            collisions_involving_active
        ),
        "preflight_structurally_clean": not reasons,
        "stop_reasons": reasons,
        "human_collision_review_required": True,
        "uniqueness_migration_authorized": False,
        "account_merge_authorized": False,
        "identity_cutover_authorized": False,
        "sms_provider_change_authorized": False,
        "database_reads": 0,
        "writes_performed": 0,
    }
