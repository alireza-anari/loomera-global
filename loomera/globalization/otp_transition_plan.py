"""Phase 7.9: offline metadata-only OTP cutover rehearsal decision.

NO runtime integration, cache access, account reads, OTP codes, or approval
granting. An apparent "ready" result licenses only synthetic testing.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OfflineOtpDrainEvidence:
    inventory_complete: bool
    legacy_writers_frozen: bool
    cache_backend_healthy: bool
    session_scope_complete: bool
    api_legacy_pending: int
    web_signup_pending: int
    password_reset_pending: int
    unknown_format_pending: int
    last_legacy_issue_ts: int
    longest_legacy_ttl_seconds: int
    now_ts: int
    clock_margin_seconds: int = 30


@dataclass(frozen=True, slots=True)
class OfflineOtpTransitionDecision:
    status: str
    seconds_until_rehearsal: int = 0
    production_cutover_authorized: bool = False
    authenticated: bool = False
    rollback_to_legacy_authorized: bool = False


def assess_offline_otp_drain(evidence: OfflineOtpDrainEvidence) -> OfflineOtpTransitionDecision:
    """Deterministic, fail-closed review of synthetic *aggregate* metadata.

    Counts do not prove an exhaustive inventory; inventory and frozen-writer
    evidence must be independently established in a future owner-approved
    workflow. This method NEVER grants permission to switch a real verifier.
    """
    if type(evidence) is not OfflineOtpDrainEvidence:
        raise TypeError("explicit offline aggregate evidence required")
    for field in (
        "inventory_complete", "legacy_writers_frozen",
        "cache_backend_healthy", "session_scope_complete",
    ):
        if type(getattr(evidence, field)) is not bool:
            raise ValueError("invalid aggregate boolean evidence")
    for field in (
        "api_legacy_pending", "web_signup_pending",
        "password_reset_pending", "unknown_format_pending",
    ):
        value = getattr(evidence, field)
        if type(value) is not int or value < 0 or value > 1_000_000:
            raise ValueError("invalid aggregate pending count")
    for field in (
        "last_legacy_issue_ts", "longest_legacy_ttl_seconds",
        "now_ts", "clock_margin_seconds",
    ):
        if type(getattr(evidence, field)) is not int:
            raise ValueError("invalid timestamp or interval")
    if (
        evidence.last_legacy_issue_ts <= 0
        or evidence.now_ts <= 0
        or not 1 <= evidence.longest_legacy_ttl_seconds <= 86400
        or not 30 <= evidence.clock_margin_seconds <= 3600
    ):
        raise ValueError("unbounded synthetic drain window")
    if evidence.now_ts < evidence.last_legacy_issue_ts:
        return OfflineOtpTransitionDecision("clock_inconsistent")
    if not (evidence.inventory_complete and evidence.session_scope_complete):
        return OfflineOtpTransitionDecision("inventory_untrusted")
    if not evidence.cache_backend_healthy:
        return OfflineOtpTransitionDecision("backend_unavailable")
    if not evidence.legacy_writers_frozen:
        return OfflineOtpTransitionDecision("writers_not_frozen")
    if evidence.unknown_format_pending:
        return OfflineOtpTransitionDecision("unknown_legacy_formats")
    if evidence.api_legacy_pending:
        return OfflineOtpTransitionDecision("api_legacy_pending")
    if evidence.web_signup_pending:
        return OfflineOtpTransitionDecision("web_signup_pending")
    if evidence.password_reset_pending:
        return OfflineOtpTransitionDecision("password_reset_pending")
    wait_until = (
        evidence.last_legacy_issue_ts
        + evidence.longest_legacy_ttl_seconds
        + evidence.clock_margin_seconds
    )
    if evidence.now_ts < wait_until:
        return OfflineOtpTransitionDecision(
            "drain_window_active", wait_until - evidence.now_ts,
        )
    return OfflineOtpTransitionDecision("simulation_ready")
