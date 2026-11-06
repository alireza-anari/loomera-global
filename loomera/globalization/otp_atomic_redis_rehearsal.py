"""Phase 7.7: test-only Redis atomic OTP rehearsal, NOT a login adapter.

All Redis writes are restricted to a synthetic namespace on the local CI
Redis DB 15 behind an explicit environment guard. Never import this in
the live authentication, web signup or password reset paths.

The legacy Django cache stores a different serialization and has distinct
rate, resend and session policies; this experiment does NOT bridge them.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

SYNTHETIC_PREFIX = "loomera:phase77:synthetic-only:"
_SYNTHETIC_KEY = re.compile(r"loomera:phase77:synthetic-only:[0-9a-f]{32}\Z")
_LEGACY_IR_PHONE = re.compile(r"09[0-9]{9}\Z")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_PURPOSE = "app_login"

# A single Redis EVAL is the *linearization point*. A successful consume
# returns only when DEL of the same challenge key returns exactly 1.
# Purpose, source legacy mobile, expiry, max-attempts and the code digest
# are checked on the Redis server under its atomic script execution.
# No OTP secrets or account IDs are returned to Python.
ATOMIC_CONSUME_SCRIPT = r"""
local item = redis.call('HMGET', KEYS[1],
    'purpose', 'legacy_mobile', 'code_digest',
    'expires_at', 'attempts', 'max_attempts')
if not item[1] then
    return {'missing', '0'}
end
if not item[2] or not item[3] or not item[4]
    or not item[5] or not item[6] then
    return {'invalid_record', '0'}
end
if item[1] ~= ARGV[1] or item[2] ~= ARGV[2] then
    return {'bound_mismatch', '0'}
end
local expires_at = tonumber(item[4])
local attempts = tonumber(item[5])
local max_attempts = tonumber(item[6])
local now = tonumber(ARGV[4])
if not expires_at or not attempts or not max_attempts or not now
    or attempts < 0 or max_attempts <= 0 then
    return {'invalid_record', '0'}
end
if expires_at <= now or redis.call('PTTL', KEYS[1]) <= 0 then
    if redis.call('DEL', KEYS[1]) ~= 1 then
        return {'delete_unconfirmed', '0'}
    end
    return {'expired', '0'}
end
if attempts >= max_attempts then
    if redis.call('DEL', KEYS[1]) ~= 1 then
        return {'delete_unconfirmed', '0'}
    end
    return {'exhausted', '0'}
end
if item[3] == ARGV[3] then
    if redis.call('DEL', KEYS[1]) ~= 1 then
        return {'delete_unconfirmed', '0'}
    end
    return {'consumed', '0'}
end
attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts >= max_attempts then
    if redis.call('DEL', KEYS[1]) ~= 1 then
        return {'delete_unconfirmed', '0'}
    end
    return {'exhausted', '0'}
end
return {'invalid', tostring(max_attempts - attempts)}
"""

# Never overwrite an existing OTP: a duplicate seed must NOT reset the
# attempt counter or extend TTL. Future production request/resend policy
# requires a separately reviewed migration plan.
ATOMIC_SEED_SCRIPT = r"""
if redis.call('EXISTS', KEYS[1]) ~= 0 then
    return 0
end
redis.call('HSET', KEYS[1],
    'purpose', ARGV[1],
    'legacy_mobile', ARGV[2],
    'code_digest', ARGV[3],
    'expires_at', ARGV[4],
    'attempts', '0',
    'max_attempts', ARGV[5])
redis.call('PEXPIRE', KEYS[1], ARGV[6])
return 1
"""


@dataclass(frozen=True, slots=True)
class AtomicRehearsalDecision:
    """Fixed statuses only. Even 'consumed' cannot log a user in."""

    status: str
    attempts_remaining: int = 0
    authenticated: bool = False
    legacy_auth_changed: bool = False


def _guard(client: Any, key: str) -> None:
    if os.environ.get("LOOMERA_PHASE77_TEST_REDIS") != "1":
        raise RuntimeError("Phase 7.7 offline Redis authorization absent")
    if type(key) is not str or _SYNTHETIC_KEY.fullmatch(key) is None:
        raise ValueError("test-only key namespace required")
    # Protect against accidental invocation against a remote production
    # cache or an application's normal Redis DB. No FLUSHDB/FLUSHALL.
    try:
        conn = client.connection_pool.connection_kwargs
        host = conn.get("host")
        db = conn.get("db")
        port = conn.get("port", 6379)
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis client scope") from exc
    if host not in {"localhost", "127.0.0.1"} or type(db) is not int or db != 15 or port != 6379:
        raise RuntimeError("Phase 7.7 requires local Redis DB 15")


def _arguments(purpose: str, legacy_mobile: str, digest: str) -> None:
    if (
        type(purpose) is not str or purpose != _ALLOWED_PURPOSE
        or type(legacy_mobile) is not str
        or _LEGACY_IR_PHONE.fullmatch(legacy_mobile) is None
        or type(digest) is not str
        or _SHA256_HEX.fullmatch(digest) is None
    ):
        raise ValueError("invalid synthetic OTP challenge arguments")


class SyntheticRedisOtpRehearsal:
    """A narrow Redis protocol rehearsal with no Django/auth integration."""

    def __init__(self, client: Any, *, key: str):
        _guard(client, key)
        self._client = client
        self._key = key

    def seed(
        self, *, purpose: str, legacy_mobile: str, code_digest: str,
        expires_at: int, now_ts: int, max_attempts: int = 3,
    ) -> bool:
        _arguments(purpose, legacy_mobile, code_digest)
        if (
            type(now_ts) is not int or now_ts <= 0
            or type(expires_at) is not int or expires_at <= now_ts
            or type(max_attempts) is not int or not 1 <= max_attempts <= 10
            or expires_at - now_ts > 600
        ):
            raise ValueError("invalid synthetic lifetime or attempt budget")
        try:
            return self._client.eval(
                ATOMIC_SEED_SCRIPT, 1, self._key, purpose,
                legacy_mobile, code_digest, expires_at,
                max_attempts, (expires_at - now_ts) * 1000,
            ) == 1
        except Exception:
            # A lost response after Redis committed is *ambiguous*.
            # Never claim a successful new challenge or retry blindly.
            return False

    def consume(
        self, *, purpose: str, legacy_mobile: str, code_digest: str,
        now_ts: int,
    ) -> AtomicRehearsalDecision:
        _arguments(purpose, legacy_mobile, code_digest)
        if type(now_ts) is not int or now_ts <= 0:
            raise ValueError("invalid synthetic verification clock")
        try:
            raw = self._client.eval(
                ATOMIC_CONSUME_SCRIPT, 1, self._key, purpose,
                legacy_mobile, code_digest, now_ts,
            )
            if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                return AtomicRehearsalDecision("backend_unavailable")
            status, count = raw
            if isinstance(status, bytes):
                status = status.decode("ascii")
            if isinstance(count, bytes):
                count = count.decode("ascii")
            if status not in {
                "missing", "bound_mismatch", "invalid_record",
                "expired", "exhausted", "invalid",
                "delete_unconfirmed", "consumed",
            }:
                return AtomicRehearsalDecision("backend_unavailable")
            if type(count) is not str or not count.isascii() or not count.isdigit():
                return AtomicRehearsalDecision("backend_unavailable")
            remaining = int(count)
            if remaining > 10 or (status != "invalid" and remaining != 0):
                return AtomicRehearsalDecision("backend_unavailable")
            return AtomicRehearsalDecision(status, remaining)
        except Exception:
            # Includes RedisTimeoutError, connection loss after EVAL,
            # serialization and unexpected backend responses.
            # Never infer that a successful DEL occurred from a timeout.
            return AtomicRehearsalDecision("backend_unavailable")

    def synthetic_cleanup(self) -> None:
        """Only the precise generated test key, never any user namespace."""
        _guard(self._client, self._key)
        self._client.delete(self._key)
