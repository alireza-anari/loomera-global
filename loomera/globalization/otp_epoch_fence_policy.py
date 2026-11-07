"""Phase 7.16 pure synthetic epoch/owner/token fencing evidence.

The returned 'fixture_only' result is NOT a production lease, distributed
consensus, authorization to authenticate, or cross-store atomicity proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_HEX = re.compile(r"[0-9a-f]{32}\Z")
_WITNESS = frozenset({"verified", "missing", "unavailable", "corrupt", "halted"})
_OWNER = frozenset({"original", "promoted", "unknown"})
_REDISTATE = frozenset({"matched", "missing", "stale", "future", "corrupt"})
_ACK = frozenset({"confirmed", "lost", "unknown"})


@dataclass(frozen=True, slots=True)
class SyntheticEpochFenceEvidence:
    witness_status: str
    witness_owner: str
    candidate_owner: str
    witness_epoch: int
    candidate_epoch: int
    redis_epoch: int
    witness_token: str
    candidate_token: str
    redis_token: str
    redis_marker_status: str
    redis_master_role: bool
    dual_master_possible: bool
    old_primary_readonly: bool
    write_acknowledgement: str
    witness_read_atomic_with_redis_write: bool
    multi_host_quorum_attested: bool
    no_real_users_or_sessions: bool


@dataclass(frozen=True, slots=True)
class SyntheticEpochFenceAssessment:
    status: str
    fixture_write_observation_possible: bool = False
    manual_reconciliation_required: bool = True
    authenticated: bool = False
    otp_consume_allowed: bool = False
    otp_reissue_allowed: bool = False
    session_created: bool = False
    session_retry_allowed: bool = False
    legacy_fallback_allowed: bool = False
    production_cutover_allowed: bool = False
    real_consensus_proven: bool = False


def assess_synthetic_epoch_fence(
    evidence: SyntheticEpochFenceEvidence,
) -> SyntheticEpochFenceAssessment:
    if type(evidence) is not SyntheticEpochFenceEvidence:
        raise TypeError("exact Phase 7.16 synthetic evidence required")
    for field, choices in (
        ("witness_status", _WITNESS),
        ("witness_owner", _OWNER),
        ("candidate_owner", _OWNER),
        ("redis_marker_status", _REDISTATE),
        ("write_acknowledgement", _ACK),
    ):
        value = getattr(evidence, field)
        if type(value) is not str or value not in choices:
            raise ValueError("unknown synthetic fencing enum")
    for field in (
        "redis_master_role", "dual_master_possible", "old_primary_readonly",
        "witness_read_atomic_with_redis_write",
        "multi_host_quorum_attested", "no_real_users_or_sessions",
    ):
        if type(getattr(evidence, field)) is not bool:
            raise ValueError("strict boolean evidence required")
    for field in ("witness_epoch", "candidate_epoch", "redis_epoch"):
        value = getattr(evidence, field)
        if type(value) is not int or not 1 <= value <= 1_000_000_000:
            raise ValueError("bounded exact epoch required")
    for field in ("witness_token", "candidate_token", "redis_token"):
        value = getattr(evidence, field)
        if type(value) is not str or _HEX.fullmatch(value) is None:
            raise ValueError("synthetic 32-hex token required")

    if not evidence.no_real_users_or_sessions:
        return SyntheticEpochFenceAssessment("unsafe_real_data_scope")
    if evidence.witness_status == "halted":
        return SyntheticEpochFenceAssessment("witness_halted")
    if evidence.witness_status != "verified":
        return SyntheticEpochFenceAssessment("witness_untrusted")
    if evidence.witness_owner == "unknown" or evidence.candidate_owner == "unknown":
        return SyntheticEpochFenceAssessment("owner_untrusted")
    if evidence.witness_owner != evidence.candidate_owner:
        return SyntheticEpochFenceAssessment("wrong_owner")
    if evidence.candidate_epoch != evidence.witness_epoch:
        return SyntheticEpochFenceAssessment("stale_or_future_candidate_epoch")
    if evidence.candidate_token != evidence.witness_token:
        return SyntheticEpochFenceAssessment("stale_or_forged_candidate_token")
    if evidence.redis_marker_status != "matched":
        return SyntheticEpochFenceAssessment("redis_marker_untrusted")
    if evidence.redis_epoch != evidence.witness_epoch:
        return SyntheticEpochFenceAssessment("redis_epoch_diverged")
    if evidence.redis_token != evidence.witness_token:
        return SyntheticEpochFenceAssessment("redis_token_diverged")
    if not evidence.redis_master_role:
        return SyntheticEpochFenceAssessment("not_redis_master")
    if evidence.dual_master_possible:
        return SyntheticEpochFenceAssessment("dual_master_not_fenced")
    if not evidence.old_primary_readonly:
        return SyntheticEpochFenceAssessment("old_primary_still_writable")
    if evidence.write_acknowledgement != "confirmed":
        return SyntheticEpochFenceAssessment("uncertain_prior_write")
    if not evidence.witness_read_atomic_with_redis_write:
        return SyntheticEpochFenceAssessment("cross_store_fence_not_atomic")
    if not evidence.multi_host_quorum_attested:
        return SyntheticEpochFenceAssessment("independent_quorum_missing")
    return SyntheticEpochFenceAssessment(
        "synthetic_fixture_only_manual_review",
        fixture_write_observation_possible=True,
    )
