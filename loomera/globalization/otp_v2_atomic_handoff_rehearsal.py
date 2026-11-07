"""Phase 7.10: isolated, synthetic Redis OTP generation and session-handoff model.

Never import this module into live authentication. It does not verify real OTPs,
read users, create sessions, send SMS, change cache namespaces or grant login.
It operates on a *single* random fixture Redis HASH on localhost DB15 only.
All states expire after 10 minutes FOR CI ISOLATION; this is not a durable
production gate or a recommended production design.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

KEY_PREFIX = "loomera:phase710:synthetic-only:"
_KEY = re.compile(r"loomera:phase710:synthetic-only:[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED = frozenset({
    "created", "already_exists", "activated", "issued", "already_issued",
    "wrong_mode", "stale_generation", "missing", "corrupt",
    "binding_mismatch", "no_challenge", "invalid_digest", "exhausted",
    "consumed", "already_consumed", "expired", "would_admit",
    "already_admitted", "inactive_subject", "session_ineligible",
    "receipt_expired", "halted", "already_halted", "backend_unavailable",
})

# Single physical key and fixture-only TTL prevent split-brain during this
# *standalone* rehearsal. A real Redis Cluster / failover is NOT validated.
BOOT_SCRIPT = r"""
if redis.call('EXISTS', KEYS[1]) ~= 0 then return {'already_exists', 0, 0} end
redis.call('HSET', KEYS[1], 'mode', 'observe', 'generation', 1,
    'challenge', 'none', 'admitted', 0, 'attempts', 0, 'max_attempts', 3)
redis.call('PEXPIRE', KEYS[1], 600000)
return {'created', 1, 0}
"""

ACTIVATE_SCRIPT = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation', 'challenge')
if not x[1] then return {'missing', 0, 0} end
local g = tonumber(x[2])
if not g or g < 1 or g > 1000000000 or not x[3] then
    return {'corrupt', 0, 0}
end
if x[1] ~= 'observe' or x[3] ~= 'none' then
    return {'wrong_mode', g, 0}
end
if g ~= tonumber(ARGV[1]) then return {'stale_generation', g, 0} end
redis.call('HSET', KEYS[1], 'mode', 'v2_simulated')
g = redis.call('HINCRBY', KEYS[1], 'generation', 1)
return {'activated', g, 0}
"""

ISSUE_SCRIPT = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation', 'challenge')
if not x[1] then return {'missing', 0, 0} end
local g = tonumber(x[2])
if not g or g < 1 or g > 1000000000 or not x[3] then
    return {'corrupt', 0, 0}
end
if x[1] ~= 'v2_simulated' then return {'wrong_mode', g, 0} end
if g ~= tonumber(ARGV[1]) then return {'stale_generation', g, 0} end
if x[3] ~= 'none' then return {'already_issued', g, 0} end
local now = tonumber(redis.call('TIME')[1])
redis.call('HSET', KEYS[1], 'challenge', 'issued',
    'purpose', ARGV[2], 'subject', ARGV[3], 'digest', ARGV[4],
    'expires_at', now + tonumber(ARGV[5]), 'attempts', 0,
    'max_attempts', 3, 'receipt_until', 0, 'admitted', 0)
return {'issued', g, 0}
"""

VERIFY_SCRIPT = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation',
    'challenge', 'purpose', 'subject', 'digest', 'expires_at',
    'attempts', 'max_attempts')
if not x[1] then return {'missing', 0, 0} end
local g = tonumber(x[2])
if not g or g < 1 or g > 1000000000 or not x[3] then
    return {'corrupt', 0, 0}
end
if x[1] ~= 'v2_simulated' then return {'wrong_mode', g, 0} end
if g ~= tonumber(ARGV[1]) then return {'stale_generation', g, 0} end
if x[3] == 'none' then return {'no_challenge', g, 0} end
if x[3] == 'consumed' then return {'already_consumed', g, 0} end
if x[3] == 'expired' then return {'expired', g, 0} end
if x[3] == 'exhausted' then return {'exhausted', g, 0} end
local expires = tonumber(x[7])
local attempts = tonumber(x[8])
local maximum = tonumber(x[9])
if x[3] ~= 'issued' or not x[4] or not x[5] or not x[6]
    or not expires or not attempts or not maximum
    or maximum ~= 3 or attempts < 0 or attempts >= maximum then
    return {'corrupt', g, 0}
end
if tonumber(redis.call('TIME')[1]) >= expires then
    redis.call('HSET', KEYS[1], 'challenge', 'expired')
    redis.call('HDEL', KEYS[1], 'digest')
    return {'expired', g, 0}
end
if x[4] ~= ARGV[2] or x[5] ~= ARGV[3] then
    return {'binding_mismatch', g, 0}
end
-- Deliberately NOT a constant-time proof! This Lua comparison and its
-- 64-hex synthetic digests MUST NOT be reused in a real verifier.
if x[6] ~= ARGV[4] then
    attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
    if attempts >= maximum then
        redis.call('HSET', KEYS[1], 'challenge', 'exhausted')
        redis.call('HDEL', KEYS[1], 'digest')
        return {'exhausted', g, 0}
    end
    return {'invalid_digest', g, maximum - attempts}
end
-- The only consumption success is the atomic state change in this EVAL.
-- Retain a tombstone rather than deleting an issued challenge and letting
-- concurrent retries re-issue. No OTP or user session is materialized.
redis.call('HSET', KEYS[1], 'challenge', 'consumed',
    'receipt_until', tonumber(redis.call('TIME')[1]) + 5)
redis.call('HDEL', KEYS[1], 'digest')
return {'consumed', g, 0}
"""

ADMIT_SCRIPT = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation',
    'challenge', 'purpose', 'subject', 'receipt_until', 'admitted')
if not x[1] then return {'missing', 0, 0} end
local g, until_ts, admitted = tonumber(x[2]), tonumber(x[6]), tonumber(x[7])
if not g or g < 1 or g > 1000000000 or not x[3] or not admitted then
    return {'corrupt', 0, 0}
end
if x[1] ~= 'v2_simulated' then return {'wrong_mode', g, 0} end
if g ~= tonumber(ARGV[1]) then return {'stale_generation', g, 0} end
if x[3] ~= 'consumed' then return {'no_challenge', g, 0} end
if x[4] ~= ARGV[2] or x[5] ~= ARGV[3] then
    return {'binding_mismatch', g, 0}
end
if admitted ~= 0 then return {'already_admitted', g, 0} end
if not until_ts or until_ts <= 0 then return {'corrupt', g, 0} end
if tonumber(redis.call('TIME')[1]) >= until_ts then
    return {'receipt_expired', g, 0}
end
-- The caller's 'active account' is an UNTRUSTED SYNTHETIC flag and is
-- not a substitute for a live DB lookup / transaction / session store.
if ARGV[4] ~= '1' then return {'inactive_subject', g, 0} end
if ARGV[5] ~= '1' then return {'session_ineligible', g, 0} end
redis.call('HSET', KEYS[1], 'admitted', 1)
return {'would_admit', g, 0}
"""

HALT_SCRIPT = r"""
local x = redis.call('HMGET', KEYS[1], 'mode', 'generation')
if not x[1] then return {'missing', 0, 0} end
local g = tonumber(x[2])
if not g or g < 1 or g > 1000000000 then return {'corrupt', 0, 0} end
if x[1] == 'halted' then return {'already_halted', g, 0} end
if x[1] ~= 'observe' and x[1] ~= 'v2_simulated' then
    return {'corrupt', g, 0}
end
if g ~= tonumber(ARGV[1]) then return {'stale_generation', g, 0} end
redis.call('HSET', KEYS[1], 'mode', 'halted')
g = redis.call('HINCRBY', KEYS[1], 'generation', 1)
return {'halted', g, 0}
"""


@dataclass(frozen=True, slots=True)
class SyntheticOtpHandoffResult:
    status: str
    generation: int = 0
    attempts_remaining: int = 0
    authenticated: bool = False
    session_created: bool = False
    production_cutover_authorized: bool = False
    legacy_fallback_authorized: bool = False


def _bound_int(value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid bounded synthetic argument")


def _guard(client: Any, key: str) -> None:
    if os.environ.get("LOOMERA_PHASE710_TEST_REDIS") != "1":
        raise RuntimeError("explicit Phase 7.10 fixture grant required")
    if type(key) is not str or _KEY.fullmatch(key) is None:
        raise ValueError("random synthetic fixture key required")
    try:
        conn = client.connection_pool.connection_kwargs
        host, port, db = conn.get("host"), conn.get("port", 6379), conn.get("db")
    except (TypeError, AttributeError) as exc:
        raise RuntimeError("unverifiable client connection") from exc
    if (
        host not in {"127.0.0.1", "localhost"}
        or type(port) is not int or port != 6379
        or type(db) is not int or db != 15
        or conn.get("username") is not None
        or conn.get("password") is not None
    ):
        raise RuntimeError("only unauthenticated localhost Redis DB15 is allowed")


def _binding(purpose: str, subject: str) -> None:
    # Synthetic labels ONLY: not an email, mobile, account ID, or real purpose.
    if purpose not in ("app_login", "other_purpose") or type(purpose) is not str:
        raise ValueError("invalid synthetic purpose")
    if subject not in ("fixture_subject_a", "fixture_subject_b") or type(subject) is not str:
        raise ValueError("invalid synthetic subject")


class SyntheticOtpV2HandoffRehearsal:
    """A fixture-only Redis state machine, NOT a login/OTP service."""

    def __init__(self, client: Any, *, key: str):
        _guard(client, key)
        self._client, self._key = client, key

    def _call(self, script: str, *args: Any) -> SyntheticOtpHandoffResult:
        _guard(self._client, self._key)
        try:
            raw = self._client.eval(script, 1, self._key, *args)
            if not isinstance(raw, (tuple, list)) or len(raw) != 3:
                return SyntheticOtpHandoffResult("backend_unavailable")
            status, generation, remaining = raw
            if type(status) is bytes:
                status = status.decode("ascii")
            if type(status) is not str or status not in _ALLOWED:
                return SyntheticOtpHandoffResult("backend_unavailable")
            if type(generation) is not int or type(remaining) is not int:
                return SyntheticOtpHandoffResult("backend_unavailable")
            if not 0 <= generation <= 1_000_000_000 or not 0 <= remaining <= 3:
                return SyntheticOtpHandoffResult("backend_unavailable")
            return SyntheticOtpHandoffResult(status, generation, remaining)
        except Exception:
            # A post-commit Redis timeout means UNKNOWN, not a retryable grant.
            return SyntheticOtpHandoffResult("backend_unavailable")

    def bootstrap(self) -> SyntheticOtpHandoffResult:
        return self._call(BOOT_SCRIPT)

    def activate(self, *, expected_generation: int) -> SyntheticOtpHandoffResult:
        _bound_int(expected_generation, 1, 1_000_000_000)
        return self._call(ACTIVATE_SCRIPT, expected_generation)

    def issue(self, *, expected_generation: int, purpose: str, subject: str,
              synthetic_digest: str, ttl_seconds: int = 30) -> SyntheticOtpHandoffResult:
        _bound_int(expected_generation, 1, 1_000_000_000)
        _bound_int(ttl_seconds, 1, 120)
        _binding(purpose, subject)
        if type(synthetic_digest) is not str or _DIGEST.fullmatch(synthetic_digest) is None:
            raise ValueError("64-character synthetic digest required")
        return self._call(
            ISSUE_SCRIPT, expected_generation, purpose, subject,
            synthetic_digest, ttl_seconds,
        )

    def verify(self, *, expected_generation: int, purpose: str, subject: str,
               synthetic_digest: str) -> SyntheticOtpHandoffResult:
        _bound_int(expected_generation, 1, 1_000_000_000)
        _binding(purpose, subject)
        if type(synthetic_digest) is not str or _DIGEST.fullmatch(synthetic_digest) is None:
            raise ValueError("64-character synthetic digest required")
        return self._call(
            VERIFY_SCRIPT, expected_generation, purpose, subject, synthetic_digest,
        )

    def would_admit(self, *, expected_generation: int, purpose: str,
                    subject: str, synthetic_active: bool,
                    synthetic_session_eligible: bool) -> SyntheticOtpHandoffResult:
        _bound_int(expected_generation, 1, 1_000_000_000)
        _binding(purpose, subject)
        if type(synthetic_active) is not bool or type(synthetic_session_eligible) is not bool:
            raise ValueError("only explicit synthetic boolean evidence allowed")
        return self._call(
            ADMIT_SCRIPT, expected_generation, purpose, subject,
            int(synthetic_active), int(synthetic_session_eligible),
        )

    def halt(self, *, expected_generation: int) -> SyntheticOtpHandoffResult:
        _bound_int(expected_generation, 1, 1_000_000_000)
        return self._call(HALT_SCRIPT, expected_generation)

    def cleanup_owned_fixture(self) -> None:
        _guard(self._client, self._key)
        self._client.delete(self._key)
