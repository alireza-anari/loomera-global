"""Phase 7.17: three disposable Redis witness votes, NOT distributed consensus.

Three distinct Redis 7.4 processes on ONE GitHub runner have independent local
AOF volumes but no secure distributed quorum service, independent sites,
authentication, trusted time, automatic election, or real lease enforcement.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

HEX = re.compile(r"[0-9a-f]{32}\Z")
PREFIX = "loomera:phase717:synthetic-vote-only:"
PORTS = {"a": 6405, "b": 6406, "c": 6407}
STATUSES = frozenset({
    "seeded", "already_seeded", "ready", "voted", "vote_recorded",
    "already_voted", "conflicting_vote", "halted", "already_halted",
    "missing", "corrupt", "stale_epoch", "backend_unavailable",
})

VOTE_SCRIPT = r"""
local k=KEYS[1]
local cmd=ARGV[1]
if cmd=='seed' then
    if redis.call('EXISTS',k)==1 then
        return {'already_seeded',0,'none'}
    end
    redis.call('HSET',k,'fixture',ARGV[2],'state','ready','epoch','1',
        'owner','original','token',ARGV[4])
    redis.call('PEXPIRE',k,600000)
    return {'seeded',1,ARGV[4]}
end
if redis.call('EXISTS',k)==0 then return {'missing',0,'none'} end
if redis.call('TYPE',k).ok~='hash' then return {'corrupt',0,'none'} end
local x=redis.call('HMGET',k,'fixture','state','epoch','owner','token')
local e=tonumber(x[3])
if x[1]~=ARGV[2]
    or not e or e<1 or e>3 or tostring(e)~=x[3]
    or redis.call('PTTL',k)<=0
    or not x[5] or string.len(x[5])~=32
    or not string.match(x[5],'^[0-9a-f]+$')
    or ((x[2]=='ready') and (e~=1 or x[4]~='original'))
    or ((x[2]=='voted') and (e~=2 or x[4]~='promoted'))
    or ((x[2]=='halted') and (e~=3 or x[4]~='promoted'))
    or (x[2]~='ready' and x[2]~='voted' and x[2]~='halted') then
    return {'corrupt',0,'none'}
end
if cmd=='inspect' then return {x[2],e,x[5]} end
if x[2]=='halted' then return {'already_halted',e,x[5]} end
if cmd=='vote' then
    if x[2]=='voted' then
        if ARGV[4]==x[5] then
            return {'already_voted',e,x[5]}
        end
        return {'conflicting_vote',e,x[5]}
    end
    if tonumber(ARGV[5])~=1 or ARGV[3]~=x[5]
        or not ARGV[4] or string.len(ARGV[4])~=32
        or not string.match(ARGV[4],'^[0-9a-f]+$')
        or ARGV[4]==x[5] then
        return {'stale_epoch',e,x[5]}
    end
    redis.call('HSET',k,'state','voted','owner','promoted',
        'epoch','2','token',ARGV[4])
    return {'vote_recorded',2,ARGV[4]}
end
if cmd=='halt' then
    if x[2]~='voted' or tonumber(ARGV[5])~=2
        or ARGV[3]~=x[5] then
        return {'stale_epoch',e,x[5]}
    end
    redis.call('HSET',k,'state','halted','epoch','3')
    return {'halted',3,x[5]}
end
return {'corrupt',0,'none'}
"""


@dataclass(frozen=True, slots=True)
class SyntheticVote:
    status: str
    epoch: int = 0
    token: str = "none"
    authenticated: bool = False
    session_created: bool = False
    can_grant_write: bool = False
    can_resume_otp: bool = False
    safe_to_retry: bool = False
    live_consensus_proven: bool = False
    legacy_fallback_authorized: bool = False
    production_recovery_authorized: bool = False


def _hex(value: str) -> None:
    if type(value) is not str or HEX.fullmatch(value) is None:
        raise ValueError("exact random synthetic 32-hex token required")


def _guard(client: Any, fixture_id: str, voter: str) -> None:
    if os.environ.get("LOOMERA_PHASE717_TEST_REDIS") != "1":
        raise RuntimeError("explicit disposable Phase 7.17 Redis grant required")
    _hex(fixture_id)
    if type(voter) is not str or voter not in PORTS:
        raise ValueError("only fixed a/b/c synthetic voters")
    try:
        kw = client.connection_pool.connection_kwargs
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis client") from exc
    if (
        kw.get("host") != "127.0.0.1"
        or type(kw.get("port")) is not int or kw.get("port") != PORTS[voter]
        or type(kw.get("db")) is not int or kw.get("db") != 15
        or kw.get("username") is not None or kw.get("password") is not None
        or kw.get("ssl") not in (None, False)
        or kw.get("unix_socket_path") is not None
    ):
        raise RuntimeError("only localhost 6405–6407 DB15 synthetic witnesses")


class SyntheticVoter:
    """One immutable candidate vote per independently hosted fixture Redis."""

    def __init__(self, client: Any, *, fixture_id: str, voter: str):
        _guard(client, fixture_id, voter)
        self.client, self.id, self.voter = client, fixture_id, voter
        self.key = PREFIX + fixture_id + ":" + voter

    def _eval(self, command: str, old: str = "none",
              new: str = "none", expected_epoch: int = 0) -> SyntheticVote:
        _guard(self.client, self.id, self.voter)
        try:
            value = self.client.eval(
                VOTE_SCRIPT, 1, self.key, command, self.id,
                old, new, expected_epoch,
            )
            if type(value) not in (list, tuple) or len(value) != 3:
                return SyntheticVote("backend_unavailable")
            status, epoch, token = value
            if type(status) is bytes:
                status = status.decode("ascii")
            if type(token) is bytes:
                token = token.decode("ascii")
            if (
                type(status) is not str or status not in STATUSES
                or type(epoch) is not int or not 0 <= epoch <= 3
                or type(token) is not str
                or (token != "none" and HEX.fullmatch(token) is None)
            ):
                return SyntheticVote("backend_unavailable")
            return SyntheticVote(status, epoch, token)
        except Exception:
            # Commit may precede a lost response. Never treat as a vote.
            return SyntheticVote("backend_unavailable")

    def seed_for_test(self, *, token: str) -> SyntheticVote:
        _hex(token)
        if os.environ.get("LOOMERA_PHASE717_ALLOW_SEED") != "1":
            raise RuntimeError("explicit initial fixture-only seed grant required")
        return self._eval("seed", new=token)

    def inspect(self) -> SyntheticVote:
        return self._eval("inspect")

    def vote_promote(self, *, expected_old_token: str,
                     new_token: str, expected_epoch: int = 1) -> SyntheticVote:
        _hex(expected_old_token)
        _hex(new_token)
        if type(expected_epoch) is not int or expected_epoch != 1:
            raise ValueError("voting is limited to synthetic epoch 1")
        if os.environ.get("LOOMERA_PHASE717_ALLOW_TEST_VOTE") != "1":
            raise RuntimeError("explicit synthetic vote grant required")
        return self._eval("vote", expected_old_token, new_token, expected_epoch)

    def terminal_halt(self, *, expected_token: str) -> SyntheticVote:
        _hex(expected_token)
        if os.environ.get("LOOMERA_PHASE717_ALLOW_TEST_HALT") != "1":
            raise RuntimeError("explicit synthetic stop grant required")
        return self._eval("halt", expected_token, "none", 2)

    def cleanup_owned_fixture(self) -> None:
        _guard(self.client, self.id, self.voter)
        if os.environ.get("LOOMERA_PHASE717_ALLOW_SEED") != "1":
            raise RuntimeError("test cleanup requires initial fixture grant")
        self.client.delete(self.key)
