"""Phase 7.3: concurrency rehearsal for a proposed E.164 shadow unique key.

This module is NOT a production identity repository, schema constraint,
authentication adapter, distributed lock, or replacement for database
transactions. Every input is an offline synthetic or separately authorized
sensitive snapshot; all returned data is aggregate or fixed status codes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock

from loomera.globalization.phone_collision_audit import MAX_ACCOUNTS
from loomera.globalization.phone_identity import (
    PhoneIdentityInputError,
    to_candidate_e164,
)
from loomera.globalization.phone_identity_transition import (
    LEGACY_FIELDS,
    LEGACY_STORAGE_RE,
)

PROPOSAL_FIELDS = frozenset((
    "account_id", "expected_version", "mobile_number",
    "is_active", "canonical_mobile_number",
))


@dataclass(frozen=True, slots=True)
class _OfflineIdentityRow:
    account_id: int
    mobile_number: str
    is_active: bool
    row_version: int = 0
    canonical_mobile_number: str | None = None


def _valid_id(value: object) -> bool:
    return type(value) is int and value > 0


def _decision(reason: str = "", *, applied: int = 0) -> dict:
    return {
        "status": "blocked" if reason else "applied",
        "reason": reason or "none",
        "applied": applied,
        "database_writes": 0,
        "authentication_side_effects": 0,
    }


class OfflinePhoneShadowReservation:
    """In-memory serializable *simulation*, not a cross-process DB guarantee.

    A single RLock makes individual/batch claims atomic ONLY for this Python
    object. Database row locking, UNIQUE indexes, concurrent web workers,
    crash recovery and message queues remain separately unverified.
    """

    def __init__(self, source_rows: list[dict]):
        if (
            type(source_rows) is not list
            or not 1 <= len(source_rows) <= MAX_ACCOUNTS
        ):
            raise PhoneIdentityInputError("invalid offline source scope")
        self._lock = RLock()
        self._rows: dict[int, _OfflineIdentityRow] = {}
        self._source_owners: dict[str, int] = {}
        self._shadow_owners: dict[str, int] = {}
        for item in source_rows:
            if type(item) is not dict or frozenset(item) != LEGACY_FIELDS:
                raise PhoneIdentityInputError("invalid offline source row schema")
            account_id = item["account_id"]
            phone = item["mobile_number"]
            active = item["is_active"]
            if (
                not _valid_id(account_id)
                or type(phone) is not str
                or LEGACY_STORAGE_RE.fullmatch(phone) is None
                or type(active) is not bool
            ):
                raise PhoneIdentityInputError("invalid legacy identity record")
            try:
                candidate = to_candidate_e164(phone)
            except PhoneIdentityInputError as exc:
                raise PhoneIdentityInputError("invalid legacy identity record") from exc
            if account_id in self._rows or candidate in self._source_owners:
                # Inactive accounts are NOT ignored. No account merge or reuse.
                raise PhoneIdentityInputError("duplicate or colliding source identity")
            self._rows[account_id] = _OfflineIdentityRow(
                account_id=account_id, mobile_number=phone, is_active=active,
            )
            self._source_owners[candidate] = account_id

    def _check_proposal(self, proposal: object) -> str:
        if type(proposal) is not dict or frozenset(proposal) != PROPOSAL_FIELDS:
            return "invalid_proposal_schema"
        account_id = proposal["account_id"]
        version = proposal["expected_version"]
        phone = proposal["mobile_number"]
        state = proposal["is_active"]
        canonical = proposal["canonical_mobile_number"]
        if (
            not _valid_id(account_id)
            or type(version) is not int or version < 0
            or type(phone) is not str or type(state) is not bool
            or type(canonical) is not str
        ):
            return "invalid_proposal_values"
        row = self._rows.get(account_id)
        if row is None:
            return "unknown_offline_account"
        if version != row.row_version:
            return "stale_row_version"
        if phone != row.mobile_number or state != row.is_active:
            return "source_identity_or_state_drift"
        try:
            normalized = to_candidate_e164(canonical)
        except PhoneIdentityInputError:
            return "invalid_canonical_candidate"
        if (
            normalized != canonical
            or canonical != to_candidate_e164(row.mobile_number)
        ):
            return "canonical_source_mismatch"
        if row.canonical_mobile_number is not None:
            return "already_claimed"
        if self._source_owners.get(canonical) != account_id:
            return "canonical_source_mismatch"
        owner = self._shadow_owners.get(canonical)
        if owner is not None and owner != account_id:
            return "canonical_uniqueness_collision"
        return ""

    def claim_one(
        self, *, account_id: int, expected_version: int, mobile_number: str,
        is_active: bool, canonical_mobile_number: str,
    ) -> dict:
        """One atomic offline claim; no live DB, cache, or SMS write."""
        return self.claim_batch([{
            "account_id": account_id, "expected_version": expected_version,
            "mobile_number": mobile_number, "is_active": is_active,
            "canonical_mobile_number": canonical_mobile_number,
        }])

    def claim_batch(self, proposals: list[dict]) -> dict:
        """All-or-nothing simulated compare-and-swap for a bounded batch."""
        if (
            type(proposals) is not list
            or not 1 <= len(proposals) <= len(self._rows)
        ):
            raise PhoneIdentityInputError("invalid offline proposal batch size")
        with self._lock:
            seen_ids = set()
            seen_candidates = set()
            for proposal in proposals:
                reason = self._check_proposal(proposal)
                if reason:
                    return _decision(reason)
                account_id = proposal["account_id"]
                canonical = proposal["canonical_mobile_number"]
                if account_id in seen_ids:
                    return _decision("duplicate_batch_account")
                if canonical in seen_candidates:
                    return _decision("duplicate_batch_candidate")
                seen_ids.add(account_id)
                seen_candidates.add(canonical)
            # Commit all changes only AFTER every guard passes under ONE lock.
            for proposal in proposals:
                account_id = proposal["account_id"]
                candidate = proposal["canonical_mobile_number"]
                row = self._rows[account_id]
                self._rows[account_id] = replace(
                    row, row_version=row.row_version + 1,
                    canonical_mobile_number=candidate,
                )
                self._shadow_owners[candidate] = account_id
            return _decision(applied=len(proposals))

    def rollback_one(
        self, *, account_id: int, expected_version: int,
        mobile_number: str, is_active: bool,
    ) -> dict:
        """Offline reversible *simulation*: clear shadow, keep legacy/state.

        This cannot roll back a real migration or restore a database backup.
        """
        if (
            not _valid_id(account_id)
            or type(expected_version) is not int or expected_version < 0
            or type(mobile_number) is not str or type(is_active) is not bool
        ):
            return _decision("invalid_rollback_values")
        with self._lock:
            row = self._rows.get(account_id)
            if row is None:
                return _decision("unknown_offline_account")
            if row.row_version != expected_version:
                return _decision("stale_row_version")
            if row.mobile_number != mobile_number or row.is_active != is_active:
                return _decision("source_identity_or_state_drift")
            candidate = row.canonical_mobile_number
            if candidate is None:
                return _decision("shadow_not_present")
            if self._shadow_owners.get(candidate) != account_id:
                return _decision("canonical_uniqueness_collision")
            self._rows[account_id] = replace(
                row, row_version=row.row_version + 1,
                canonical_mobile_number=None,
            )
            del self._shadow_owners[candidate]
            return _decision(applied=1)

    def audit(self) -> dict:
        """Only safe aggregate output; never IDs, phones, aliases or hashes."""
        with self._lock:
            rows = tuple(self._rows.values())
            owned = {
                r.canonical_mobile_number: r.account_id
                for r in rows if r.canonical_mobile_number is not None
            }
            match = (
                owned == self._shadow_owners
                and len(owned) == sum(
                    r.canonical_mobile_number is not None for r in rows
                )
                and all(
                    r.canonical_mobile_number is None
                    or r.canonical_mobile_number == to_candidate_e164(
                        r.mobile_number
                    )
                    for r in rows
                )
            )
            attached = len(owned)
            return {
                "schema_version": 1,
                "phase": "7.3",
                "mode": "in_memory_concurrency_rehearsal_only",
                "source_accounts": len(rows),
                "active_accounts": sum(r.is_active for r in rows),
                "inactive_accounts": sum(not r.is_active for r in rows),
                "shadow_claimed_accounts": attached,
                "shadow_unclaimed_accounts": len(rows) - attached,
                "shadow_claimed_inactive_accounts": sum(
                    r.canonical_mobile_number is not None and not r.is_active
                    for r in rows
                ),
                "shadow_index_consistent": match,
                "legacy_login_values_preserved": True,
                "live_database_uniqueness_verified": False,
                "multi_process_race_safety_verified": False,
                "migration_approved": False,
                "authentication_cutover_authorized": False,
                "database_reads": 0,
                "database_writes": 0,
            }
