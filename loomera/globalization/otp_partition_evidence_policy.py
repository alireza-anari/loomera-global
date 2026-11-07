"""Phase 7.15: pure synthetic network-partition and external-witness policy.

This is a design preflight, not a usable distributed lease. All inputs are
caller-supplied unverified claims; not a single output authorizes OTP or login.
"""
from __future__ import annotations

from dataclasses import dataclass

_LINK = frozenset({"linked", "partitioned", "restoring", "unknown"})
_ROLE = frozenset({"master", "replica_readonly", "down", "unknown"})
_WITNESS = frozenset({"verified", "missing", "stale", "corrupt", "unavailable"})
_MODE = frozenset({"observing", "halted", "unknown"})
_MARKER = frozenset({"matched", "divergent", "missing", "corrupt", "unreadable"})
_ACK = frozenset({"acknowledged", "unknown", "timeout", "not_attempted"})


@dataclass(frozen=True, slots=True)
class SyntheticPartitionEvidence:
    replication_link: str
    original_role: str
    promoted_role: str
    independent_witness: str
    witness_mode: str
    witness_generation: int
    client_expected_generation: int
    original_marker: str
    promoted_marker: str
    original_generation: int
    promoted_generation: int
    original_write_ack: str
    promoted_write_ack: str
    post_partition_inventory_complete: bool
    old_writer_fenced_by_consensus: bool
    durable_multi_host_quorum: bool
    real_data_absent: bool
    owner_authorized: bool


@dataclass(frozen=True, slots=True)
class SyntheticPartitionDecision:
    status: str
    manual_reconciliation_required: bool = True
    login_allowed: bool = False
    otp_consume_allowed: bool = False
    otp_reissue_allowed: bool = False
    write_on_either_master_allowed: bool = False
    marker_reseed_allowed: bool = False
    session_retry_allowed: bool = False
    legacy_fallback_allowed: bool = False
    production_cutover_allowed: bool = False
    old_primary_fenced_proven: bool = False
    real_quorum_proven: bool = False


def assess_synthetic_partition(
    evidence: SyntheticPartitionEvidence,
) -> SyntheticPartitionDecision:
    """Fail closed on ambiguity; all-green still means manual review only."""
    if type(evidence) is not SyntheticPartitionEvidence:
        raise TypeError("exact synthetic partition evidence required")
    for field, choices in (
        ("replication_link", _LINK),
        ("original_role", _ROLE),
        ("promoted_role", _ROLE),
        ("independent_witness", _WITNESS),
        ("witness_mode", _MODE),
        ("original_marker", _MARKER),
        ("promoted_marker", _MARKER),
        ("original_write_ack", _ACK),
        ("promoted_write_ack", _ACK),
    ):
        value = getattr(evidence, field)
        if type(value) is not str or value not in choices:
            raise ValueError("unsupported synthetic partition enum")
    for field in (
        "post_partition_inventory_complete", "old_writer_fenced_by_consensus",
        "durable_multi_host_quorum", "real_data_absent", "owner_authorized",
    ):
        if type(getattr(evidence, field)) is not bool:
            raise ValueError("exact synthetic boolean required")
    for field in (
        "witness_generation", "client_expected_generation",
        "original_generation", "promoted_generation",
    ):
        value = getattr(evidence, field)
        if type(value) is not int or not 1 <= value <= 1_000_000_000:
            raise ValueError("bounded exact synthetic generation required")

    if not evidence.real_data_absent:
        return SyntheticPartitionDecision("unsafe_real_data_scope")
    if evidence.original_role == "master" and evidence.promoted_role == "master":
        return SyntheticPartitionDecision("dual_master_split_brain")
    if evidence.replication_link != "linked":
        return SyntheticPartitionDecision("replication_untrusted")
    if evidence.original_role != "replica_readonly" or evidence.promoted_role != "master":
        return SyntheticPartitionDecision("roles_untrusted")
    if evidence.independent_witness != "verified":
        return SyntheticPartitionDecision("witness_untrusted")
    if evidence.witness_mode == "halted":
        return SyntheticPartitionDecision("terminal_witness_halt")
    if evidence.witness_mode != "observing":
        return SyntheticPartitionDecision("witness_mode_untrusted")
    if evidence.witness_generation != evidence.client_expected_generation:
        return SyntheticPartitionDecision("witness_epoch_mismatch")
    if evidence.original_marker != "matched" or evidence.promoted_marker != "matched":
        return SyntheticPartitionDecision("markers_untrusted")
    if (
        evidence.original_generation < evidence.witness_generation
        or evidence.promoted_generation < evidence.witness_generation
    ):
        return SyntheticPartitionDecision("marker_regressed")
    if (
        evidence.original_generation > evidence.witness_generation
        or evidence.promoted_generation > evidence.witness_generation
    ):
        return SyntheticPartitionDecision("marker_ahead_untrusted")
    if (
        evidence.original_write_ack != "acknowledged"
        or evidence.promoted_write_ack != "acknowledged"
    ):
        return SyntheticPartitionDecision("write_commit_ambiguous")
    if not evidence.post_partition_inventory_complete:
        return SyntheticPartitionDecision("inventory_untrusted")
    if not evidence.old_writer_fenced_by_consensus:
        return SyntheticPartitionDecision("old_writer_not_fenced")
    if not evidence.durable_multi_host_quorum:
        return SyntheticPartitionDecision("quorum_unproven")
    if not evidence.owner_authorized:
        return SyntheticPartitionDecision("owner_signoff_missing")
    # No synthetic claims demonstrate real atomic cross-store transactions.
    return SyntheticPartitionDecision("manual_review_only")
