"""Phase 7.12: offline-only restart/failover evidence assessment.

No Redis/database/session access; no OTP, user identifier, secret, or key.
Inputs are unverified synthetic claims, never deployment authorization.
"""
from __future__ import annotations

from dataclasses import dataclass

_HEALTH = frozenset({"healthy", "timeout", "unavailable", "unknown"})
_MARKER = frozenset({"verified", "missing", "stale", "corrupt", "unreadable"})
_MODE = frozenset({"observing", "quarantined", "halted", "unknown"})
_TOPOLOGY = frozenset({"standalone", "promoted", "unknown", "split_brain"})
_SESSIONS = frozenset({"settled", "pending", "ambiguous", "unavailable"})


@dataclass(frozen=True, slots=True)
class SyntheticRestartEvidence:
    redis_health: str
    reference_marker: str
    volatile_marker: str
    expected_generation: int
    reference_generation: int
    volatile_generation: int
    reference_mode: str
    volatile_mode: str
    fingerprint_matches: bool
    topology: str
    topology_independently_verified: bool
    session_ledger: str
    owner_inventory_complete: bool
    legacy_writers_frozen: bool
    reset_grants_drained: bool
    owner_signoff_claimed: bool


@dataclass(frozen=True, slots=True)
class SyntheticRestartDecision:
    status: str
    human_reconciliation_required: bool = True
    can_authenticate: bool = False
    can_reissue_otp: bool = False
    can_resume_issuance: bool = False
    can_recreate_missing_marker: bool = False
    can_retry_session_write: bool = False
    legacy_fallback_authorized: bool = False
    production_cutover_authorized: bool = False


def assess_synthetic_restart(
    evidence: SyntheticRestartEvidence,
) -> SyntheticRestartDecision:
    """Reject ambiguity before any restart/resume decision, including all green.

    A caller claiming healthy markers or signoff does not prove a durable,
    independent store or ownership review. Never use this for live auth.
    """
    if type(evidence) is not SyntheticRestartEvidence:
        raise TypeError("explicit synthetic restart evidence required")
    for field, choices in (
        ("redis_health", _HEALTH),
        ("reference_marker", _MARKER),
        ("volatile_marker", _MARKER),
        ("reference_mode", _MODE),
        ("volatile_mode", _MODE),
        ("topology", _TOPOLOGY),
        ("session_ledger", _SESSIONS),
    ):
        value = getattr(evidence, field)
        if type(value) is not str or value not in choices:
            raise ValueError("invalid synthetic restart enum")
    for field in (
        "fingerprint_matches", "topology_independently_verified",
        "owner_inventory_complete", "legacy_writers_frozen",
        "reset_grants_drained", "owner_signoff_claimed",
    ):
        if type(getattr(evidence, field)) is not bool:
            raise ValueError("synthetic restart flags must be exact booleans")
    for field in (
        "expected_generation", "reference_generation", "volatile_generation",
    ):
        value = getattr(evidence, field)
        if type(value) is not int or not 1 <= value <= 1_000_000_000:
            raise ValueError("invalid bounded generation")

    if evidence.redis_health != "healthy":
        return SyntheticRestartDecision("redis_untrusted")
    if evidence.reference_marker != "verified":
        return SyntheticRestartDecision("reference_untrusted")
    if evidence.volatile_marker != "verified":
        return SyntheticRestartDecision("volatile_untrusted")
    if not evidence.fingerprint_matches:
        return SyntheticRestartDecision("fingerprint_mismatch")
    if evidence.volatile_generation < evidence.reference_generation:
        return SyntheticRestartDecision("generation_regressed")
    if evidence.volatile_generation > evidence.reference_generation:
        return SyntheticRestartDecision("generation_ahead_untrusted")
    if evidence.reference_generation != evidence.expected_generation:
        return SyntheticRestartDecision("expected_generation_mismatch")
    if evidence.reference_mode != evidence.volatile_mode:
        return SyntheticRestartDecision("mode_conflict")
    if evidence.reference_mode == "unknown":
        return SyntheticRestartDecision("mode_unknown")
    if evidence.reference_mode == "halted":
        return SyntheticRestartDecision("terminal_halt")
    if evidence.reference_mode == "quarantined":
        return SyntheticRestartDecision("quarantined")
    if evidence.topology != "standalone" or not evidence.topology_independently_verified:
        return SyntheticRestartDecision("topology_untrusted")
    if evidence.session_ledger != "settled":
        return SyntheticRestartDecision("session_ledger_untrusted")
    if not evidence.owner_inventory_complete:
        return SyntheticRestartDecision("inventory_untrusted")
    if not evidence.legacy_writers_frozen:
        return SyntheticRestartDecision("writers_not_frozen")
    if not evidence.reset_grants_drained:
        return SyntheticRestartDecision("reset_grants_pending")
    if not evidence.owner_signoff_claimed:
        return SyntheticRestartDecision("owner_signoff_missing")
    return SyntheticRestartDecision("manual_review_only")
