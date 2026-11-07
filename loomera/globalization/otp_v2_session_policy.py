"""Phase 7.10 purely offline session-handoff review for synthetic inputs.

Caller-supplied flags are NOT identity proof or authorization. This has no
Django/cache/database imports or side effects and always denies real login.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SyntheticSessionEvidence:
    atomic_consume_confirmed: bool
    generation_fenced: bool
    purpose_bound: bool
    legacy_identity_unchanged: bool
    exactly_one_active_account: bool
    account_not_deleting: bool
    no_outstanding_password_reset_grant: bool
    cache_healthy: bool
    session_store_healthy: bool
    session_not_previously_admitted: bool
    receipt_within_deadline: bool
    not_halted: bool


@dataclass(frozen=True, slots=True)
class SyntheticSessionReview:
    status: str
    authenticated: bool = False
    session_created: bool = False
    production_authorized: bool = False
    rollback_to_legacy_authorized: bool = False


def review_synthetic_session_handoff(
    evidence: SyntheticSessionEvidence,
) -> SyntheticSessionReview:
    """Fail-closed decision ordering without identities, codes, sessions or I/O.

    No combination of these *unverified caller flags* can establish a real
    session; even a complete candidate is only an offline simulation.
    """
    if type(evidence) is not SyntheticSessionEvidence:
        raise TypeError("explicit synthetic evidence required")
    for field in SyntheticSessionEvidence.__dataclass_fields__:
        if type(getattr(evidence, field)) is not bool:
            raise ValueError("synthetic evidence must contain exact booleans")
    for field, status in (
        ("not_halted", "halted"),
        ("cache_healthy", "cache_unavailable"),
        ("session_store_healthy", "session_store_unavailable"),
        ("generation_fenced", "stale_generation"),
        ("purpose_bound", "wrong_purpose"),
        ("atomic_consume_confirmed", "unconfirmed_consume"),
        ("receipt_within_deadline", "receipt_expired"),
        ("legacy_identity_unchanged", "identity_changed"),
        ("exactly_one_active_account", "active_account_not_unique"),
        ("account_not_deleting", "account_deactivation_pending"),
        ("no_outstanding_password_reset_grant", "reset_grant_pending"),
        ("session_not_previously_admitted", "already_admitted"),
    ):
        if not getattr(evidence, field):
            return SyntheticSessionReview(status)
    return SyntheticSessionReview("simulation_candidate")
