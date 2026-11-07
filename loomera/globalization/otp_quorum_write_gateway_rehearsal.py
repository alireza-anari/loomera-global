"""Phase 7.17 restricted synthetic majority-gated Redis write rehearsal.

Checking three witnesses then EVAL on a different Redis store is NOT atomic.
An unprotected old raw Redis master will still accept old-token writes.
Only disposable localhost 6403/6404 DB15 and fake fixture counters.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

from loomera.globalization.otp_epoch_redis_rehearsal import EPOCH_SCRIPT, SEED
from loomera.globalization.otp_quorum_evidence_policy import (
    SyntheticVoterClaim, SyntheticQuorumReview, review_synthetic_quorum,
)
from loomera.globalization.otp_quorum_voter_rehearsal import (
    SyntheticVoter,
)

_HEX = re.compile(r"[0-9a-f]{32}\Z")
_PORTS = {"original": 6403, "promoted": 6404}
PREFIX = "loomera:phase717:synthetic-write-only:"
_ALLOWED = frozenset({
    "initialized", "already_initialized", "active", "written", "adopted",
    "fenced", "corrupt", "stale_sequence", "both_lost", "fence_lost",
    "counter_lost", "already_promoted", "backend_unavailable",
})


@dataclass(frozen=True, slots=True)
class SyntheticGateWrite:
    status: str
    epoch: int = 0
    sequence: int = 0
    authenticated: bool = False
    session_created: bool = False
    can_issue_otp: bool = False
    can_retry: bool = False
    production_write_allowed: bool = False
    raw_writer_fenced: bool = False
    quorum_consensus_proven: bool = False
    legacy_fallback_authorized: bool = False


def _hex(value: str):
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise ValueError("random synthetic 32-hex fixture/token required")


def _guard(client: Any, fixture_id: str, node: str):
    if os.environ.get("LOOMERA_PHASE717_TEST_REDIS") != "1":
        raise RuntimeError("explicit isolated Phase 7.17 grant required")
    _hex(fixture_id)
    if type(node) is not str or node not in _PORTS:
        raise ValueError("fixed synthetic data node required")
    try:
        kw = client.connection_pool.connection_kwargs
    except (TypeError, AttributeError) as exc:
        raise RuntimeError("unverifiable Redis client") from exc
    if (
        kw.get("host") != "127.0.0.1"
        or type(kw.get("port")) is not int or kw.get("port") != _PORTS[node]
        or type(kw.get("db")) is not int or kw.get("db") != 15
        or kw.get("username") is not None or kw.get("password") is not None
        or kw.get("ssl") not in (None, False)
        or kw.get("unix_socket_path") is not None
    ):
        raise RuntimeError("only isolated localhost Redis data ports 6403/6404 DB15")


class SyntheticQuorumWriteGateway:
    """Test helper only: never an OTP/session/production authorization boundary."""

    def __init__(self, client: Any, *, fixture_id: str, node: str,
                 voters: tuple[SyntheticVoter, ...]):
        _guard(client, fixture_id, node)
        if type(voters) is not tuple or len(voters) != 3:
            raise TypeError("three synthetic Redis voter clients required")
        if any(type(v) is not SyntheticVoter for v in voters):
            raise TypeError("exact synthetic voter type required")
        if tuple(v.voter for v in voters) != ("a", "b", "c"):
            raise ValueError("fixed a/b/c voter ordering required")
        if any(v.id != fixture_id for v in voters):
            raise ValueError("voter fixture fingerprints must match")
        self.client, self.id, self.node, self.voters = client, fixture_id, node, voters
        self.keys = (PREFIX + fixture_id + ":fence",
                     PREFIX + fixture_id + ":counter")

    def quorum_observation(self, *, candidate_token: str) -> SyntheticQuorumReview:
        _hex(candidate_token)
        _guard(self.client, self.id, self.node)
        claims = []
        for voter in self.voters:
            v = voter.inspect()
            state = v.status if v.status in ("ready", "voted", "halted") else "unavailable"
            claims.append(SyntheticVoterClaim(
                node=voter.voter, state=state,
                epoch=v.epoch if state != "unavailable" else 0,
                token=v.token if state != "unavailable" else "none",
            ))
        return review_synthetic_quorum(
            tuple(claims), target_epoch=2,
            candidate_token=candidate_token, candidate_owner="promoted",
        )

    def _eval(self, script: str, *args: Any) -> SyntheticGateWrite:
        _guard(self.client, self.id, self.node)
        try:
            response = self.client.eval(script, 2, *self.keys, *args)
            if type(response) not in (list, tuple) or len(response) != 3:
                return SyntheticGateWrite("backend_unavailable")
            status, epoch, seq = response
            if type(status) is bytes:
                status = status.decode("ascii")
            if (
                type(status) is not str or status not in _ALLOWED
                or type(epoch) is not int or not 0 <= epoch <= 1_000_000_000
                or type(seq) is not int or not 0 <= seq <= 1_000_000_000
            ):
                return SyntheticGateWrite("backend_unavailable")
            return SyntheticGateWrite(status, epoch, seq)
        except Exception:
            # A committed EVAL may have lost its reply: never auto-retry.
            return SyntheticGateWrite("backend_unavailable")

    def seed_test_data(self, *, initial_token: str) -> SyntheticGateWrite:
        _hex(initial_token)
        if os.environ.get("LOOMERA_PHASE717_ALLOW_SEED") != "1":
            raise RuntimeError("disposable initial data fixture only")
        if self.node != "original":
            return SyntheticGateWrite("wrong_data_node")
        return self._eval(SEED, self.id, initial_token)

    def _preflight(self, token: str, *, required_flag: str) -> str | None:
        _guard(self.client, self.id, self.node)
        if self.node != "promoted":
            return "old_writer_denied_by_gateway"
        decision = self.quorum_observation(candidate_token=token)
        if decision.status != "synthetic_majority_observed_only":
            return decision.status
        try:
            info = self.client.info(section="replication")
            if type(info) is not dict or info.get("role") != "master":
                return "not_master"
        except Exception:
            return "backend_unavailable"
        if os.environ.get(required_flag) != "1":
            return "fixture_write_not_granted"
        return None

    def adopt_promoted_fixture(self, *, previous_token: str,
                               candidate_token: str) -> SyntheticGateWrite:
        _hex(previous_token)
        _hex(candidate_token)
        rejection = self._preflight(
            candidate_token, required_flag="LOOMERA_PHASE717_ALLOW_TEST_ADOPT",
        )
        if rejection:
            return SyntheticGateWrite(rejection)
        return self._eval(
            EPOCH_SCRIPT, "adopt", self.id, "promoted", 2,
            candidate_token, 1, previous_token, "original",
        )

    def write_promoted_fixture(self, *, candidate_token: str,
                               expected_sequence: int) -> SyntheticGateWrite:
        _hex(candidate_token)
        if (
            type(expected_sequence) is not int
            or not 0 <= expected_sequence < 1_000_000_000
        ):
            raise ValueError("bounded strict synthetic sequence required")
        rejection = self._preflight(
            candidate_token, required_flag="LOOMERA_PHASE717_ALLOW_TEST_WRITE",
        )
        if rejection:
            return SyntheticGateWrite(rejection)
        return self._eval(
            EPOCH_SCRIPT, "write", self.id, "promoted", 2,
            candidate_token, expected_sequence,
        )

    def cleanup_owned_fixture(self):
        _guard(self.client, self.id, self.node)
        if os.environ.get("LOOMERA_PHASE717_ALLOW_SEED") != "1":
            raise RuntimeError("fixture cleanup requires seed test grant")
        self.client.delete(*self.keys)
