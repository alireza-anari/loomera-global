"""Phase 7.11: pure synthetic cross-store recovery decision, never a login grant.

This has no database, cache, session, authentication or network dependencies.
Every flag and state is caller supplied and cannot prove real-world ownership.
"""
from __future__ import annotations

from dataclasses import dataclass

_READ = frozenset({"healthy", "unavailable", "timeout", "ambiguous"})
_MARKER = frozenset({"pinned", "missing", "stale", "corrupt"})
_CHALLENGE = frozenset({"unissued", "issued", "consumed", "expired", "unknown"})
_ACCOUNT = frozenset({"active", "inactive", "deleting", "missing", "ambiguous"})
_SESSION = frozenset({
    "not_started", "rejected", "timeout", "unconfirmed", "duplicate", "claimed",
})


@dataclass(frozen=True, slots=True)
class SyntheticCrossStoreEvidence:
    redis_read: str
    marker: str
    expected_generation: int
    observed_generation: int
    challenge: str
    consume_acknowledged: bool
    account: str
    authoritative_account_snapshot: bool
    session_write: str
    authoritative_session_snapshot: bool
    reset_grants_drained: bool
    inventory_trusted: bool
    quarantine_acknowledged: bool
    operator_halted: bool


@dataclass(frozen=True, slots=True)
class SyntheticRecoveryDecision:
    status: str
    manual_reconciliation_required: bool = True
    safe_to_retry_otp: bool = False
    safe_to_retry_session_write: bool = False
    authenticated: bool = False
    session_created: bool = False
    production_recovery_authorized: bool = False
    legacy_fallback_authorized: bool = False


def assess_synthetic_cross_store_recovery(
    evidence: SyntheticCrossStoreEvidence,
) -> SyntheticRecoveryDecision:
    """Return fixed *denial* reason; even a coherent view is only observational.

    An observed Redis consume/claim cannot establish a Django session; neither
    can a claimed session establish that the account is still active. A timeout
    after a write is ambiguous, not a safe instruction to retry.
    """
    if type(evidence) is not SyntheticCrossStoreEvidence:
        raise TypeError("exact synthetic recovery evidence required")
    for field, choices in (
        ("redis_read", _READ), ("marker", _MARKER),
        ("challenge", _CHALLENGE), ("account", _ACCOUNT),
        ("session_write", _SESSION),
    ):
        value = getattr(evidence, field)
        if type(value) is not str or value not in choices:
            raise ValueError("unsupported synthetic recovery state")
    for field in (
        "consume_acknowledged", "authoritative_account_snapshot",
        "authoritative_session_snapshot", "reset_grants_drained",
        "inventory_trusted", "quarantine_acknowledged", "operator_halted",
    ):
        if type(getattr(evidence, field)) is not bool:
            raise ValueError("synthetic recovery evidence must use exact booleans")
    for field in ("expected_generation", "observed_generation"):
        value = getattr(evidence, field)
        if type(value) is not int or not 1 <= value <= 1_000_000_000:
            raise ValueError("invalid synthetic generation")

    if evidence.operator_halted:
        return SyntheticRecoveryDecision("halted")
    if evidence.redis_read != "healthy":
        return SyntheticRecoveryDecision("redis_untrusted")
    if evidence.marker != "pinned":
        return SyntheticRecoveryDecision("version_marker_untrusted")
    if evidence.observed_generation != evidence.expected_generation:
        return SyntheticRecoveryDecision("generation_mismatch")
    if not evidence.quarantine_acknowledged:
        return SyntheticRecoveryDecision("quarantine_unconfirmed")
    if not evidence.inventory_trusted:
        return SyntheticRecoveryDecision("inventory_untrusted")
    if not evidence.authoritative_account_snapshot:
        return SyntheticRecoveryDecision("account_snapshot_untrusted")
    if not evidence.authoritative_session_snapshot:
        return SyntheticRecoveryDecision("session_snapshot_untrusted")
    if evidence.account != "active":
        return SyntheticRecoveryDecision("account_not_active")
    if not evidence.reset_grants_drained:
        return SyntheticRecoveryDecision("reset_grant_pending")
    if evidence.challenge != "consumed":
        return SyntheticRecoveryDecision("challenge_not_consumed")
    if not evidence.consume_acknowledged:
        return SyntheticRecoveryDecision("consume_ack_ambiguous")
    if evidence.session_write != "claimed":
        return SyntheticRecoveryDecision("session_outcome_untrusted")
    # A logically consistent *fixture* is not evidence of a real Django login.
    return SyntheticRecoveryDecision("manual_review_only")
