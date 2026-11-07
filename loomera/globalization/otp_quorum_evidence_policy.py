"""Phase 7.17 quorum INTERSECTION evidence only, never live consensus.

Three voter observations can establish a bounded synthetic majority in one
epoch, but are not authenticated remote attestations, leases, or permission to
write to OTP/account/session stores. Missing or conflicting votes fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_HEX = re.compile(r"[0-9a-f]{32}\Z")
_NODES = ("a", "b", "c")
_STATES = frozenset({"ready", "voted", "halted", "unavailable", "corrupt", "missing"})


@dataclass(frozen=True, slots=True)
class SyntheticVoterClaim:
    node: str
    state: str
    epoch: int
    token: str


@dataclass(frozen=True, slots=True)
class SyntheticQuorumReview:
    status: str
    matching_votes: int = 0
    operator_review_required: bool = True
    authenticated: bool = False
    otp_consume_allowed: bool = False
    session_created: bool = False
    can_write_production: bool = False
    can_issue_otp: bool = False
    can_retry_session: bool = False
    raw_old_primary_fenced: bool = False
    consensus_safety_proven: bool = False
    legacy_fallback_authorized: bool = False


def review_synthetic_quorum(
    claims: tuple[SyntheticVoterClaim, ...], *,
    target_epoch: int, candidate_token: str, candidate_owner: str,
) -> SyntheticQuorumReview:
    if type(claims) is not tuple or len(claims) != 3:
        raise ValueError("three fixed voter observations required")
    if type(target_epoch) is not int or target_epoch != 2:
        raise ValueError("only synthetic epoch 2 can be reviewed")
    if type(candidate_token) is not str or _HEX.fullmatch(candidate_token) is None:
        raise ValueError("exact synthetic candidate token required")
    if type(candidate_owner) is not str or candidate_owner != "promoted":
        raise ValueError("only synthetic promoted owner supported")
    for index, claim in enumerate(claims):
        if type(claim) is not SyntheticVoterClaim:
            raise TypeError("typed voter observations required")
        if type(claim.node) is not str or claim.node != _NODES[index]:
            raise ValueError("fixed unique a/b/c voter order required")
        if type(claim.state) is not str or claim.state not in _STATES:
            raise ValueError("unsupported voter state")
        if type(claim.epoch) is not int or not 0 <= claim.epoch <= 3:
            raise ValueError("bounded voter epoch required")
        if type(claim.token) is not str or (
            claim.token != "none" and _HEX.fullmatch(claim.token) is None
        ):
            raise ValueError("malformed voter token")
        if (
            (claim.state == "ready" and claim.epoch != 1)
            or (claim.state == "voted" and claim.epoch != 2)
            or (claim.state == "halted" and claim.epoch != 3)
            or (claim.state in ("missing", "unavailable", "corrupt")
                and (claim.epoch != 0 or claim.token != "none"))
        ):
            raise ValueError("inconsistent voter observation")

    if any(claim.state == "halted" for claim in claims):
        return SyntheticQuorumReview("terminal_halt_observed")
    if any(
        claim.state == "voted" and claim.token != candidate_token
        for claim in claims
    ):
        return SyntheticQuorumReview("conflicting_candidate_observed")
    matching = sum(
        claim.state == "voted" and claim.token == candidate_token
        for claim in claims
    )
    if matching < 2:
        return SyntheticQuorumReview("majority_unavailable", matching)
    return SyntheticQuorumReview("synthetic_majority_observed_only", matching)
