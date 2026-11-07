"""Phase 7.11 Redis recovery-quarantine rehearsal: disposable test fixtures ONLY.

Single-key monotone generation and terminal deny states. No account, OTP,
login, Django session or persistent routing marker. Standalone Redis DB15 only.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

PREFIX = "loomera:phase711:synthetic-only:"
_KEY = re.compile(r"loomera:phase711:synthetic-only:[0-9a-f]{32}\Z")
REASONS = frozenset({
    "none", "redis_timeout", "post_commit_timeout",
    "session_store_timeout", "session_claim_ambiguous",
    "account_deactivated", "generation_mismatch", "operator_stop",
})
_STATUSES = frozenset({
    "seeded", "already_seeded", "observing", "recorded", "already_recorded",
    "quarantined", "already_quarantined", "halted", "already_halted",
    "missing", "stale_generation", "wrong_mode", "corrupt",
    "backend_unavailable",
})

SEED = r"""
if redis.call('EXISTS', KEYS[1]) ~= 0 then return {'already_seeded', 0, 'none'} end
redis.call('HSET', KEYS[1], 'mode', 'observing', 'generation', 1,
    'challenge', 'none', 'reason', 'none')
redis.call('PEXPIRE', KEYS[1], 600000)
return {'seeded', 1, 'none'}
"""

RECORD_CONSUMED = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation', 'challenge', 'reason')
if not x[1] then return {'missing', 0, 'none'} end
local g = tonumber(x[2])
if not g or g < 1 or g > 1000000000 or not x[3] or not x[4] then
    return {'corrupt', 0, 'none'}
end
if x[1] ~= 'observing' then return {'wrong_mode', g, x[4]} end
if x[3] ~= 'none' and x[3] ~= 'consumed' or x[4] ~= 'none' then
    return {'corrupt', g, 'none'}
end
if g ~= tonumber(ARGV[1]) then return {'stale_generation', g, 'none'} end
if x[3] == 'consumed' then return {'already_recorded', g, 'none'} end
redis.call('HSET', KEYS[1], 'challenge', 'consumed')
return {'recorded', g, 'none'}
"""

QUARANTINE = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation', 'challenge', 'reason')
if not x[1] then return {'missing', 0, 'none'} end
local g = tonumber(x[2])
if not g or g < 1 or g > 1000000000 or not x[3] or not x[4] then
    return {'corrupt', 0, 'none'}
end
if x[1] == 'halted' then return {'already_halted', g, x[4]} end
if x[1] == 'quarantined' then return {'already_quarantined', g, x[4]} end
if x[1] ~= 'observing' or
   (x[3] ~= 'none' and x[3] ~= 'consumed') or x[4] ~= 'none' then
    return {'corrupt', g, 'none'}
end
if g ~= tonumber(ARGV[1]) then return {'stale_generation', g, 'none'} end
if g == 1000000000 then return {'corrupt', 0, 'none'} end
redis.call('HSET', KEYS[1], 'mode', 'quarantined', 'reason', ARGV[2])
g = redis.call('HINCRBY', KEYS[1], 'generation', 1)
return {'quarantined', g, ARGV[2]}
"""

HALT = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation', 'challenge', 'reason')
if not x[1] then return {'missing', 0, 'none'} end
local g = tonumber(x[2])
if not g or g < 1 or g > 1000000000 or not x[3] or not x[4] then
    return {'corrupt', 0, 'none'}
end
if x[1] == 'halted' then return {'already_halted', g, x[4]} end
if x[1] ~= 'observing' and x[1] ~= 'quarantined' then
    return {'corrupt', g, 'none'}
end
if x[3] ~= 'none' and x[3] ~= 'consumed' then
    return {'corrupt', g, 'none'}
end
if x[1] == 'observing' and x[4] ~= 'none' then
    return {'corrupt', g, 'none'}
end
if x[1] == 'quarantined' and x[4] == 'none' then
    return {'corrupt', g, 'none'}
end
if g ~= tonumber(ARGV[1]) then return {'stale_generation', g, 'none'} end
if g == 1000000000 then return {'corrupt', 0, 'none'} end
redis.call('HSET', KEYS[1], 'mode', 'halted')
g = redis.call('HINCRBY', KEYS[1], 'generation', 1)
return {'halted', g, x[4]}
"""

AUDIT = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation', 'challenge', 'reason')
if not x[1] then return {'missing', 0, 'none'} end
local g = tonumber(x[2])
if not g or g < 1 or g > 1000000000
    or (x[3] ~= 'none' and x[3] ~= 'consumed')
    or not x[4] or
    (x[1] ~= 'observing' and x[1] ~= 'quarantined' and x[1] ~= 'halted')
    or (x[1] == 'observing' and x[4] ~= 'none')
    or (x[1] == 'quarantined' and x[4] == 'none')
    or redis.call('PTTL', KEYS[1]) <= 0 then
    return {'corrupt', 0, 'none'}
end
return {x[1], g, x[4]}
"""


@dataclass(frozen=True, slots=True)
class SyntheticQuarantineResult:
    status: str
    generation: int = 0
    reason: str = "none"
    authenticated: bool = False
    session_created: bool = False
    safe_to_retry: bool = False
    legacy_fallback_authorized: bool = False
    production_recovery_authorized: bool = False


def _guard(client: Any, key: str) -> None:
    if os.environ.get("LOOMERA_PHASE711_TEST_REDIS") != "1":
        raise RuntimeError("explicit Phase 7.11 Redis test grant required")
    if type(key) is not str or _KEY.fullmatch(key) is None:
        raise ValueError("random, isolated Phase 7.11 fixture key required")
    try:
        conn = client.connection_pool.connection_kwargs
        host, port, db = conn.get("host"), conn.get("port", 6379), conn.get("db")
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis connection") from exc
    if (
        host not in ("localhost", "127.0.0.1")
        or type(port) is not int or port != 6379
        or type(db) is not int or db != 15
        or conn.get("username") is not None
        or conn.get("password") is not None
    ):
        raise RuntimeError("only unauthenticated localhost Redis DB15 is allowed")


def _generation(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 1_000_000_000:
        raise ValueError("invalid synthetic generation")


class SyntheticRecoveryQuarantine:
    """Single disposable Redis key; no login, rollback or recovery grant."""

    def __init__(self, client: Any, *, key: str):
        _guard(client, key)
        self._client = client
        self._key = key

    def _eval(self, script: str, *args: Any) -> SyntheticQuarantineResult:
        _guard(self._client, self._key)
        try:
            raw = self._client.eval(script, 1, self._key, *args)
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                return SyntheticQuarantineResult("backend_unavailable")
            status, generation, reason = raw
            if type(status) is bytes:
                status = status.decode("ascii")
            if type(reason) is bytes:
                reason = reason.decode("ascii")
            if (
                type(status) is not str or status not in _STATUSES
                or type(generation) is not int
                or not 0 <= generation <= 1_000_000_000
                or type(reason) is not str or reason not in REASONS
            ):
                return SyntheticQuarantineResult("backend_unavailable")
            return SyntheticQuarantineResult(status, generation, reason)
        except Exception:
            # A write may already have committed when its reply is lost.
            # The result stays unknown and never implies safe retry or login.
            return SyntheticQuarantineResult("backend_unavailable")

    def seed(self) -> SyntheticQuarantineResult:
        return self._eval(SEED)

    def record_synthetic_consume(self, *, expected_generation: int) -> SyntheticQuarantineResult:
        _generation(expected_generation)
        return self._eval(RECORD_CONSUMED, expected_generation)

    def quarantine(self, *, expected_generation: int, reason: str) -> SyntheticQuarantineResult:
        _generation(expected_generation)
        if type(reason) is not str or reason not in REASONS or reason == "none":
            raise ValueError("fixed synthetic quarantine reason required")
        return self._eval(QUARANTINE, expected_generation, reason)

    def halt(self, *, expected_generation: int) -> SyntheticQuarantineResult:
        _generation(expected_generation)
        return self._eval(HALT, expected_generation)

    def inspect(self) -> SyntheticQuarantineResult:
        # Inspection cannot authorize a retry even after a lost write reply.
        return self._eval(AUDIT)

    def cleanup_owned_fixture(self) -> None:
        _guard(self._client, self._key)
        self._client.delete(self._key)
