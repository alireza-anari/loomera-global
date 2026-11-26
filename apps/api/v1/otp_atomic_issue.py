"""Phase 7.36: opt-in four-key atomic legacy OTP issuance on one Redis node.

OFF by default. Uses the existing django-redis serialized STRING representation
and WATCH/MULTI/EXEC to commit challenge, cooldown and mobile/IP quota together.
No OTP delivery or session grant. Does not prove durable multi-master fencing,
end-to-end issue/verify protocol idempotency, or production cutover safety.
"""
from __future__ import annotations

from dataclasses import dataclass
from pickle import UnpicklingError
import re
import zlib
from typing import Any

from redis.exceptions import RedisError, WatchError

_DIGEST = re.compile(r"[0-9a-f]{40}\Z")
_RECOVERY_ERRORS = (
    RedisError, OSError, RuntimeError, ValueError, TypeError, AttributeError,
    LookupError, EOFError, UnpicklingError, zlib.error,
)


@dataclass(frozen=True, slots=True)
class AtomicOtpIssueOutcome:
    status: str
    retry_after: int = 0


_NUMERIC_WIRE = re.compile(rb"(?:0|[1-9][0-9]{0,19})\Z")


def _read_legacy_string(
    pipe: Any, key: str, max_ttl_ms: int, *, numeric: bool = False
):
    """Inspect one WATCHed key without unpickling existing Redis data.

    Redis stores django-redis integer counters as plain decimal bytes, not
    pickles. Existing challenge bytes are intentionally never deserialized
    by the issuer, since any live challenge conservatively blocks reissue.
    """
    kind = pipe.type(key)
    if kind == b"none":
        return "missing", None, 0
    if kind != b"string":
        return "invalid", None, 0
    remaining = pipe.pttl(key)
    if (
        type(remaining) is not int
        or remaining <= 0
        or remaining > max_ttl_ms + 1000
    ):
        return "invalid", None, 0
    raw = pipe.get(key)
    if type(raw) is not bytes:
        return "invalid", None, 0
    if not numeric:
        return "present", None, remaining
    if _NUMERIC_WIRE.fullmatch(raw) is None:
        return "invalid", None, 0
    return "present", int(raw), remaining


def _encoded(backend: Any, value: Any) -> bytes | int:
    wire = backend.client.encode(value)
    if type(value) is int:
        if type(wire) is not int or wire != value:
            raise ValueError("unexpected integer encoding")
        return wire
    if type(wire) is not bytes or backend.client.decode(wire) != value:
        raise ValueError("unsupported legacy wire representation")
    return wire


def _retry_seconds(ttl_ms: int) -> int:
    return max(1, (ttl_ms + 999) // 1000)


def atomic_issue_legacy_record(
    *,
    cache_backend: Any,
    logical_keys: tuple[str, str, str, str],
    record: dict[str, Any],
    now_ts: int,
    record_ttl_seconds: int,
    resend_ttl_seconds: int,
    mobile_hour_limit: int,
    ip_hour_limit: int,
) -> AtomicOtpIssueOutcome:
    """One confirmed four-SET Redis transaction or no successful issuance.

    The four existing logical key formats must be supplied in this exact order:
    record, resend, mobile hourly quota, IP hourly quota. Watch ALL four keys
    before any reads; never retry on conflict or a lost EXEC response. A live
    record is not overwritten merely because its resend cooldown elapsed.
    This is conservative and deliberately changes only explicitly opted-in
    issuance; the default legacy behavior is unchanged.
    """
    if (
        type(logical_keys) is not tuple
        or len(logical_keys) != 4
        or any(type(key) is not str or not key for key in logical_keys)
        or len(set(logical_keys)) != 4
        or type(record) is not dict
        or type(now_ts) is not int
        or now_ts < 0
        or type(record_ttl_seconds) is not int
        or not 60 <= record_ttl_seconds <= 3600
        or type(resend_ttl_seconds) is not int
        or not 30 <= resend_ttl_seconds <= 3600
        or type(mobile_hour_limit) is not int
        or not 1 <= mobile_hour_limit <= 10000
        or type(ip_hour_limit) is not int
        or not 1 <= ip_hour_limit <= 10000
        or type(record.get("purpose")) is not str
        or type(record.get("mobile_number")) is not str
        or type(record.get("code_hash")) is not str
        or _DIGEST.fullmatch(record["code_hash"]) is None
        or type(record.get("created_at")) is not int
        or record["created_at"] != now_ts
        or type(record.get("expires_at")) is not int
        or record["expires_at"] != now_ts + record_ttl_seconds
        or type(record.get("attempts")) is not int
        or record["attempts"] != 0
        or type(record.get("max_attempts")) is not int
        or record["max_attempts"] < 1
        or type(record.get("verified")) is not bool
        or record["verified"] is not False
    ):
        return AtomicOtpIssueOutcome("unavailable")

    try:
        from django_redis.cache import RedisCache
        from django_redis.client import DefaultClient

        if (
            type(cache_backend) is not RedisCache
            or type(cache_backend.client) is not DefaultClient
        ):
            return AtomicOtpIssueOutcome("unavailable")

        physical = tuple(str(cache_backend.make_key(k)) for k in logical_keys)
        if len(set(physical)) != 4 or any(not key for key in physical):
            return AtomicOtpIssueOutcome("unavailable")
        client = cache_backend.client.get_client(write=True)
        if client.connection_pool.connection_kwargs.get(
            "decode_responses", False
        ) is not False:
            return AtomicOtpIssueOutcome("unavailable")

        with client.pipeline(transaction=True) as pipe:
            pipe.watch(*physical)
            record_state, _, record_ttl = _read_legacy_string(
                pipe, physical[0], record_ttl_seconds * 1000
            )
            if record_state == "invalid":
                return AtomicOtpIssueOutcome("unavailable")
            if record_state == "present":
                return AtomicOtpIssueOutcome(
                    "challenge_pending", _retry_seconds(record_ttl)
                )

            cooldown_state, cooldown, cooldown_ttl = _read_legacy_string(
                pipe, physical[1], resend_ttl_seconds * 1000, numeric=True
            )
            if cooldown_state == "invalid":
                return AtomicOtpIssueOutcome("unavailable")
            if cooldown_state == "present":
                if type(cooldown) is not int or not 0 <= cooldown <= now_ts:
                    return AtomicOtpIssueOutcome("unavailable")
                # TTL, not an untrusted wall-clock subtraction, is authoritative.
                return AtomicOtpIssueOutcome(
                    "resend_limited", _retry_seconds(cooldown_ttl)
                )

            mobile_state, mobile_used, mobile_ttl = _read_legacy_string(
                pipe, physical[2], 3600 * 1000, numeric=True
            )
            ip_state, ip_used, ip_ttl = _read_legacy_string(
                pipe, physical[3], 3600 * 1000, numeric=True
            )
            if mobile_state == "invalid" or ip_state == "invalid":
                return AtomicOtpIssueOutcome("unavailable")
            if mobile_state == "missing":
                mobile_used = 0
            if ip_state == "missing":
                ip_used = 0
            if (
                type(mobile_used) is not int or mobile_used < 0
                or type(ip_used) is not int or ip_used < 0
            ):
                return AtomicOtpIssueOutcome("unavailable")
            if mobile_used >= mobile_hour_limit:
                return AtomicOtpIssueOutcome(
                    "mobile_limited", _retry_seconds(mobile_ttl)
                )
            if ip_used >= ip_hour_limit:
                return AtomicOtpIssueOutcome(
                    "ip_limited", _retry_seconds(ip_ttl)
                )

            encoded = (
                _encoded(cache_backend, record),
                _encoded(cache_backend, now_ts),
                _encoded(cache_backend, mobile_used + 1),
                _encoded(cache_backend, ip_used + 1),
            )
            pipe.multi()
            pipe.set(physical[0], encoded[0], ex=record_ttl_seconds)
            pipe.set(physical[1], encoded[1], ex=resend_ttl_seconds)
            if mobile_state == "missing":
                pipe.set(physical[2], encoded[2], ex=3600)
            else:
                pipe.set(physical[2], encoded[2], xx=True, keepttl=True)
            if ip_state == "missing":
                pipe.set(physical[3], encoded[3], ex=3600)
            else:
                pipe.set(physical[3], encoded[3], xx=True, keepttl=True)
            result = pipe.execute()
            if (
                type(result) is not list
                or len(result) != 4
                or any(value is not True for value in result)
            ):
                return AtomicOtpIssueOutcome("unavailable")
            return AtomicOtpIssueOutcome("issued")
    except WatchError:
        return AtomicOtpIssueOutcome("unavailable")
    except _RECOVERY_ERRORS:
        # A lost EXEC reply is indistinguishable from successful server commit:
        # never report an accepted issuance, never retry or fall back.
        return AtomicOtpIssueOutcome("unavailable")
