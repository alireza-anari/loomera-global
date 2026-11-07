"""Phase 7.14: typed synthetic Redis replica-promotion evidence policy.

No network, OTP, session, user lookup, write, or Production authorization.
A reported promoted role is not a durable independently attested leader lease.
"""
from __future__ import annotations

from dataclasses import dataclass

_TOPOLOGY = frozenset({
    "linked_replica", "promoted_standalone", "rejoined_replica",
    "split_brain", "unknown",
})
_LEADER = frozenset({"original", "promoted", "ambiguous", "missing"})
_MARKER = frozenset({"matched", "missing", "stale", "future", "corrupt"})
_MODE = frozenset({"observing", "quarantined", "halted", "unknown"})
_ACK = frozenset({"acknowledged", "timeout", "unknown", "not_attempted"})
_OLD = frozenset({"offline", "replica_readonly", "master_writable", "unknown"})


@dataclass(frozen=True, slots=True)
class SyntheticPromotionEvidence:
    topology: str
    proposed_leader: str
    original_primary_status: str
    marker_replication: str
    marker_after_promotion: str
    generation_before: int
    generation_after: int
    mode_before: str
    mode_after: str
    cause_unchanged: bool
    fingerprint_unchanged: bool
    old_writer_guard_active: bool
    replica_sync_observed: bool
    source_write_ack: str
    session_ledger_settled: bool
    real_account_data_absent: bool
    independent_durable_lease: bool
    owner_signoff_claimed: bool


@dataclass(frozen=True, slots=True)
class SyntheticPromotionReview:
    status: str
    operator_review_required: bool = True
    authenticated: bool = False
    otp_reissue_allowed: bool = False
    session_created: bool = False
    session_retry_allowed: bool = False
    cutover_allowed: bool = False
    legacy_fallback_allowed: bool = False
    real_failover_safety_proven: bool = False
    old_leader_fenced_proven: bool = False


def review_synthetic_replica_promotion(
    evidence: SyntheticPromotionEvidence,
) -> SyntheticPromotionReview:
    """Every state returns a non-authorizing decision, including 'all green'."""
    if type(evidence) is not SyntheticPromotionEvidence:
        raise TypeError("exact synthetic promotion evidence required")
    for field, choices in (
        ("topology", _TOPOLOGY),
        ("proposed_leader", _LEADER),
        ("original_primary_status", _OLD),
        ("marker_replication", _MARKER),
        ("marker_after_promotion", _MARKER),
        ("mode_before", _MODE),
        ("mode_after", _MODE),
        ("source_write_ack", _ACK),
    ):
        value = getattr(evidence, field)
        if type(value) is not str or value not in choices:
            raise ValueError("unsupported synthetic promotion state")
    for field in (
        "cause_unchanged", "fingerprint_unchanged",
        "old_writer_guard_active", "replica_sync_observed",
        "session_ledger_settled", "real_account_data_absent",
        "independent_durable_lease", "owner_signoff_claimed",
    ):
        if type(getattr(evidence, field)) is not bool:
            raise ValueError("exact boolean evidence required")
    for field in ("generation_before", "generation_after"):
        value = getattr(evidence, field)
        if type(value) is not int or not 1 <= value <= 1_000_000_000:
            raise ValueError("bounded generation required")

    if not evidence.real_account_data_absent:
        return SyntheticPromotionReview("unsafe_fixture_scope")
    if evidence.topology in ("split_brain", "unknown"):
        return SyntheticPromotionReview("topology_ambiguous")
    if evidence.topology not in ("promoted_standalone", "rejoined_replica"):
        return SyntheticPromotionReview("promotion_unverified")
    if evidence.proposed_leader != "promoted":
        return SyntheticPromotionReview("leader_not_promoted")
    if not evidence.replica_sync_observed:
        return SyntheticPromotionReview("replica_sync_unproven")
    if evidence.marker_replication != "matched":
        return SyntheticPromotionReview("replication_marker_untrusted")
    if evidence.marker_after_promotion != "matched":
        return SyntheticPromotionReview("promoted_marker_untrusted")
    if evidence.generation_after < evidence.generation_before:
        return SyntheticPromotionReview("generation_regressed")
    if evidence.generation_after > evidence.generation_before:
        return SyntheticPromotionReview("generation_ahead_untrusted")
    if evidence.mode_before != evidence.mode_after:
        return SyntheticPromotionReview("mode_changed")
    if evidence.mode_after == "unknown":
        return SyntheticPromotionReview("mode_unknown")
    if not evidence.fingerprint_unchanged:
        return SyntheticPromotionReview("fingerprint_mismatch")
    if not evidence.cause_unchanged:
        return SyntheticPromotionReview("cause_mismatch")
    if evidence.source_write_ack != "acknowledged":
        return SyntheticPromotionReview("commit_ambiguous")
    if evidence.original_primary_status == "master_writable":
        return SyntheticPromotionReview("old_primary_still_writable")
    if evidence.original_primary_status == "unknown":
        return SyntheticPromotionReview("old_primary_untrusted")
    if not evidence.old_writer_guard_active:
        return SyntheticPromotionReview("old_writer_guard_missing")
    if not evidence.session_ledger_settled:
        return SyntheticPromotionReview("session_ledger_untrusted")
    if not evidence.owner_signoff_claimed:
        return SyntheticPromotionReview("owner_signoff_unverified")
    if not evidence.independent_durable_lease:
        return SyntheticPromotionReview("durable_lease_missing")
    # Even a caller's claimed independent lease has no cryptographic proof.
    # Promotion and rejoining on one Docker host cannot prove real fencing.
    return SyntheticPromotionReview("manual_review_only")
