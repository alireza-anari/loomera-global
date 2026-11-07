"""Phase 7.16 LOCAL Redis per-instance epoch/token Lua CAS experiment.

The Lua transaction is atomic on ONE Redis node only. SQLite witness checks
before EVAL are TOCTOU; old raw Redis masters can still accept prior tokens.
It is not a multi-host quorum, real OTP, real session, or production fencing.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

from loomera.globalization.otp_epoch_witness_rehearsal import (
    SyntheticLocalEpochWitness,
)

_ID = re.compile(r"[0-9a-f]{32}\Z")
PORTS = {"original": 6397, "promoted": 6398}
PREFIX = "loomera:phase716:synthetic-epoch-only:"
_STATUSES = frozenset({
    "initialized", "already_initialized", "partially_lost", "both_lost",
    "fence_lost", "counter_lost", "corrupt", "active", "adopted", "written",
    "fenced", "stale_sequence", "stale_epoch", "already_promoted",
    "backend_unavailable", "witness_untrusted", "witness_halted",
    "stale_token", "leader_untrusted", "not_selected", "not_master",
    "mutation_not_granted", "adoption_not_granted",
})

SEED = r"""
local a=redis.call('EXISTS',KEYS[1])
local b=redis.call('EXISTS',KEYS[2])
if a==1 and b==1 then return {'already_initialized',0,0} end
if a~=b then return {'partially_lost',0,0} end
redis.call('HSET',KEYS[1],'epoch','1','owner','original',
    'token',ARGV[2],'fixture',ARGV[1])
redis.call('HSET',KEYS[2],'epoch','1','owner','original',
    'token',ARGV[2],'fixture',ARGV[1],'sequence','0')
redis.call('PEXPIRE',KEYS[1],600000)
redis.call('PEXPIRE',KEYS[2],600000)
return {'initialized',1,0}
"""

EPOCH_SCRIPT = r"""
local a=redis.call('EXISTS',KEYS[1])
local b=redis.call('EXISTS',KEYS[2])
if a==0 and b==0 then return {'both_lost',0,0} end
if a==0 then return {'fence_lost',0,0} end
if b==0 then return {'counter_lost',0,0} end
if redis.call('TYPE',KEYS[1]).ok~='hash'
    or redis.call('TYPE',KEYS[2]).ok~='hash' then
    return {'corrupt',0,0}
end
local x=redis.call('HMGET',KEYS[1],'epoch','owner','token','fixture')
local y=redis.call('HMGET',KEYS[2],'epoch','owner','token','fixture','sequence')
local e=tonumber(x[1])
local seq=tonumber(y[5])
if not e or e<1 or e>1000000000 or tostring(e)~=x[1]
    or not seq or seq<0 or seq>1000000000 or tostring(seq)~=y[5]
    or (x[2]~='original' and x[2]~='promoted')
    or not x[3] or string.len(x[3])~=32
    or x[4]~=ARGV[2] or y[4]~=ARGV[2]
    or x[1]~=y[1] or x[2]~=y[2] or x[3]~=y[3]
    or redis.call('PTTL',KEYS[1])<=0
    or redis.call('PTTL',KEYS[2])<=0 then
    return {'corrupt',0,0}
end
if ARGV[1]=='inspect' then return {'active',e,seq} end
if ARGV[1]=='write' then
    if tonumber(ARGV[4])~=e or ARGV[3]~=x[2]
        or ARGV[5]~=x[3] then
        return {'fenced',e,seq}
    end
    if tonumber(ARGV[6])~=seq then return {'stale_sequence',e,seq} end
    if seq>=1000000000 then return {'corrupt',0,0} end
    redis.call('HSET',KEYS[2],'sequence',tostring(seq+1))
    return {'written',e,seq+1}
end
if ARGV[1]=='adopt' then
    if x[2]=='promoted' then return {'already_promoted',e,seq} end
    if ARGV[3]~='promoted'
        or tonumber(ARGV[4])~=e+1
        or tonumber(ARGV[6])~=e or ARGV[7]~=x[3]
        or ARGV[8]~=x[2] or ARGV[5]==x[3]
        or string.len(ARGV[5])~=32 then
        return {'fenced',e,seq}
    end
    if e>=1000000000 then return {'corrupt',0,0} end
    for _,key in ipairs(KEYS) do
        redis.call('HSET',key,'epoch',tostring(e+1),
            'owner','promoted','token',ARGV[5])
    end
    return {'adopted',e+1,seq}
end
return {'corrupt',0,0}
"""


@dataclass(frozen=True, slots=True)
class SyntheticEpochWrite:
    status: str
    epoch: int = 0
    sequence: int = 0
    authenticated: bool = False
    session_created: bool = False
    otp_reissue_allowed: bool = False
    can_resume: bool = False
    safe_to_retry: bool = False
    production_cutover_authorized: bool = False
    legacy_fallback_authorized: bool = False
    cross_store_atomicity_proven: bool = False


def _token(token: str):
    if type(token) is not str or _ID.fullmatch(token) is None:
        raise ValueError("exact synthetic fencing token required")


def _epoch(epoch: int):
    if type(epoch) is not int or not 1 <= epoch < 1_000_000_000:
        raise ValueError("bounded exact synthetic epoch required")


def _guard(client: Any, fixture_id: str, node: str):
    if os.environ.get("LOOMERA_PHASE716_TEST_REDIS") != "1":
        raise RuntimeError("explicit isolated Redis grant required")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("synthetic lowercase fixture id required")
    if type(node) is not str or node not in PORTS:
        raise ValueError("fixed test node required")
    try:
        kw = client.connection_pool.connection_kwargs
    except (TypeError, AttributeError) as exc:
        raise RuntimeError("unverifiable Redis client") from exc
    if (
        kw.get("host") != "127.0.0.1"
        or type(kw.get("port")) is not int or kw.get("port") != PORTS[node]
        or type(kw.get("db")) is not int or kw.get("db") != 15
        or kw.get("username") is not None or kw.get("password") is not None
        or kw.get("ssl") not in (None, False)
        or kw.get("unix_socket_path") is not None
    ):
        raise RuntimeError("only localhost isolated Redis 6397/6398 DB15")


class SyntheticEpochRedisFence:
    """Test-only adapter, zero authorization to authenticate or create a session."""

    def __init__(self, client: Any, *, fixture_id: str, node: str,
                 witness: SyntheticLocalEpochWitness):
        _guard(client, fixture_id, node)
        if type(witness) is not SyntheticLocalEpochWitness:
            raise TypeError("exact local synthetic witness required")
        self._client, self._id, self._node, self._witness = (
            client, fixture_id, node, witness,
        )
        self._keys = (
            PREFIX + fixture_id + ":fence",
            PREFIX + fixture_id + ":counter",
        )

    def _preflight(self, *, owner: str, epoch: int,
                   token: str) -> str | None:
        _guard(self._client, self._id, self._node)
        observed = self._witness.inspect()
        if observed.status == "halted":
            return "witness_halted"
        if observed.status != "active":
            return "witness_untrusted"
        if (
            observed.owner != owner or observed.epoch != epoch
            or observed.token != token
        ):
            return "stale_token"
        leader = os.environ.get("LOOMERA_PHASE716_ACTIVE_LEADER")
        if leader not in PORTS:
            return "leader_untrusted"
        if leader != self._node or owner != self._node:
            return "not_selected"
        try:
            role = self._client.info(section="replication")
            if type(role) is not dict or role.get("role") != "master":
                return "not_master"
        except Exception:
            return "backend_unavailable"
        return None

    def _eval(self, script: str, *args: Any) -> SyntheticEpochWrite:
        _guard(self._client, self._id, self._node)
        try:
            result = self._client.eval(script, 2, *self._keys, *args)
            if type(result) not in (list, tuple) or len(result) != 3:
                return SyntheticEpochWrite("backend_unavailable")
            status, epoch, sequence = result
            if type(status) is bytes:
                status = status.decode("ascii")
            if (
                type(status) is not str or status not in _STATUSES
                or type(epoch) is not int or not 0 <= epoch <= 1_000_000_000
                or type(sequence) is not int or not 0 <= sequence <= 1_000_000_000
            ):
                return SyntheticEpochWrite("backend_unavailable")
            return SyntheticEpochWrite(status, epoch, sequence)
        except Exception:
            # A committed marker write may have lost its reply. No auto-retry.
            return SyntheticEpochWrite("backend_unavailable")

    def initialize_fixture(self, *, token: str) -> SyntheticEpochWrite:
        _token(token)
        if os.environ.get("LOOMERA_PHASE716_ALLOW_SEED") != "1":
            raise RuntimeError("test fixture preparation only")
        denial = self._preflight(owner="original", epoch=1, token=token)
        if denial:
            return SyntheticEpochWrite(denial)
        return self._eval(SEED, self._id, token)

    def inspect(self, *, owner: str, epoch: int, token: str) -> SyntheticEpochWrite:
        _epoch(epoch)
        _token(token)
        denial = self._preflight(owner=owner, epoch=epoch, token=token)
        if denial:
            return SyntheticEpochWrite(denial)
        return self._eval(EPOCH_SCRIPT, "inspect", self._id, owner, epoch, token, 0)

    def write_fixture_marker(
        self, *, owner: str, epoch: int, token: str, expected_sequence: int,
    ) -> SyntheticEpochWrite:
        _epoch(epoch)
        _token(token)
        if type(expected_sequence) is not int or not 0 <= expected_sequence < 1_000_000_000:
            raise ValueError("bounded synthetic sequence required")
        denial = self._preflight(owner=owner, epoch=epoch, token=token)
        if denial:
            return SyntheticEpochWrite(denial)
        if os.environ.get("LOOMERA_PHASE716_ALLOW_TEST_WRITE") != "1":
            return SyntheticEpochWrite("mutation_not_granted")
        return self._eval(
            EPOCH_SCRIPT, "write", self._id, owner, epoch, token, expected_sequence,
        )

    def adopt_after_rotation(
        self, *, old_epoch: int, old_token: str, new_token: str,
    ) -> SyntheticEpochWrite:
        _epoch(old_epoch)
        _token(old_token)
        _token(new_token)
        if os.environ.get("LOOMERA_PHASE716_ALLOW_TEST_ADOPT") != "1":
            return SyntheticEpochWrite("adoption_not_granted")
        denial = self._preflight(
            owner="promoted", epoch=old_epoch + 1, token=new_token,
        )
        if denial:
            return SyntheticEpochWrite(denial)
        return self._eval(
            EPOCH_SCRIPT, "adopt", self._id, "promoted",
            old_epoch + 1, new_token, old_epoch, old_token, "original",
        )

    def cleanup_owned_fixture(self):
        _guard(self._client, self._id, self._node)
        if os.environ.get("LOOMERA_PHASE716_ALLOW_SEED") != "1":
            raise RuntimeError("fixture cleanup only during prep tests")
        self._client.delete(*self._keys)
