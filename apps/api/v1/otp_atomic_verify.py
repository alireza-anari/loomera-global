"""Phase 7.35: opt-in single-Redis-node atomic legacy OTP verification.

The default API authentication path does NOT import or execute this module.
A named, dedicated django-redis OTP role is mandatory at the call site. This
optimistic state machine protects an individual legacy STRING challenge
against concurrent verification and same-byte SET/reissue (WATCH before GET).
It does NOT prove multihost writer fencing, failover durability, atomic issue
and rate limits, SMS delivery or cross-store session/account consistency.

Only the existing django-redis serialized dictionary wire format is supported.
No new Redis hashes, Lua, automatic retries or login/session grants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import secrets
from typing import Any

from redis.exceptions import WatchError

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class AtomicOtpOutcome:
    status: str
    attempts_remaining: int = 0
    # Never include a credential, mobile number or raw cache record in repr/logs.
    record: dict[str, Any] | None = field(default=None, repr=False)


def _valid_record(
    record: Any, *, mobile_number: str, purpose: str, now_ts: int
) -> bool:
    if type(record) is not dict:
        return False
    required = {
        "purpose", "mobile_number", "code_hash", "created_at",
        "expires_at", "attempts", "max_attempts", "verified",
    }
    if not required.issubset(record):
        return False
    return (
        type(record["purpose"]) is str
        and record["purpose"] == purpose
        and type(record["mobile_number"]) is str
        and record["mobile_number"] == mobile_number
        and type(record["code_hash"]) is str
        and _SHA1.fullmatch(record["code_hash"]) is not None
        and type(record["created_at"]) is int
        and type(record["expires_at"]) is int
        and 0 <= record["created_at"] <= now_ts
        and record["expires_at"] >= record["created_at"]
        and type(record["attempts"]) is int
        and type(record["max_attempts"]) is int
        and 0 <= record["attempts"] <= record["max_attempts"] <= 100
        and record["max_attempts"] > 0
        and record["verified"] is False
    )


def _confirmed_delete(reply: Any) -> bool:
    return (
        type(reply) is list and len(reply) == 1
        and type(reply[0]) is int and reply[0] == 1
    )


def _confirmed_set(reply: Any) -> bool:
    return type(reply) is list and len(reply) == 1 and reply[0] is True


def atomic_verify_legacy_record(
    *,
    cache_backend: Any,
    logical_key: str,
    mobile_number: str,
    purpose: str,
    submitted_hash: str,
    now_ts: int,
    ttl_seconds: int,
) -> AtomicOtpOutcome:
    """Single-key WATCH/MULTI verify and wrong-attempt CAS on legacy bytes.

    Unconfirmed EXEC, backend errors, WATCH conflicts and invalid wire state all
    fail closed as "unavailable". The caller must NEVER authenticate for such a
    result, even if Redis applied a mutation but lost the acknowledgement.
    Concurrent reissuance with SET, including identical bytes, invalidates
    WATCH. Never retry automatically or fall back to get/compare/delete.
    """
    if (
        type(logical_key) is not str
        or type(mobile_number) is not str
        or type(purpose) is not str
        or type(submitted_hash) is not str
        or _SHA1.fullmatch(submitted_hash) is None
        or type(now_ts) is not int
        or now_ts < 0
        or type(ttl_seconds) is not int
        or not 60 <= ttl_seconds <= 3600
    ):
        return AtomicOtpOutcome("unavailable")

    try:
        # Explicitly refuse non-redis, non-default serializers and response
        # decoding: WATCH must compare the exact bytes Django-Redis stores.
        from django_redis.cache import RedisCache
        from django_redis.client import DefaultClient

        if (
            type(cache_backend) is not RedisCache
            or type(cache_backend.client) is not DefaultClient
        ):
            return AtomicOtpOutcome("unavailable")
        physical = cache_backend.make_key(logical_key)
        if type(str(physical)) is not str or not str(physical):
            return AtomicOtpOutcome("unavailable")
        client = cache_backend.client.get_client(write=True)
        connection_settings = client.connection_pool.connection_kwargs
        if connection_settings.get("decode_responses", False) is not False:
            return AtomicOtpOutcome("unavailable")
        with client.pipeline(transaction=True) as pipe:
            pipe.watch(physical)
            kind = pipe.type(physical)
            if kind == b"none":
                return AtomicOtpOutcome("missing")
            if kind != b"string":
                return AtomicOtpOutcome("unavailable")
            ttl_ms = pipe.pttl(physical)
            if (
                type(ttl_ms) is not int or ttl_ms <= 0
                or ttl_ms > ttl_seconds * 1000 + 1000
            ):
                return AtomicOtpOutcome("unavailable")
            raw = pipe.get(physical)
            if type(raw) is not bytes:
                return AtomicOtpOutcome("unavailable")
            try:
                # This uses the same serializer as legacy cache.get. Operators
                # MUST ensure dedicated Redis writer ACL and trusted storage;
                # untrusted pickle is not made safe by WATCH.
                record = cache_backend.client.decode(raw)
            except Exception:
                return AtomicOtpOutcome("unavailable")
            if not _valid_record(
                record, mobile_number=mobile_number,
                purpose=purpose, now_ts=now_ts,
            ):
                return AtomicOtpOutcome("unavailable")
            if record["expires_at"] < now_ts:
                # Do not delete a possibly reissued generation during cleanup.
                return AtomicOtpOutcome("expired")
            if record["attempts"] >= record["max_attempts"]:
                return AtomicOtpOutcome("exhausted")

            if secrets.compare_digest(record["code_hash"], submitted_hash):
                pipe.multi()
                pipe.delete(physical)
                if not _confirmed_delete(pipe.execute()):
                    return AtomicOtpOutcome("unavailable")
                result = dict(record)
                result["verified"] = True
                result["verified_at"] = now_ts
                return AtomicOtpOutcome("verified", record=result)

            next_attempts = record["attempts"] + 1
            if next_attempts >= record["max_attempts"]:
                pipe.multi()
                pipe.delete(physical)
                if not _confirmed_delete(pipe.execute()):
                    return AtomicOtpOutcome("unavailable")
                return AtomicOtpOutcome("exhausted")

            updated = dict(record)
            updated["attempts"] = next_attempts
            try:
                encoded = cache_backend.client.encode(updated)
                if (
                    type(encoded) is not bytes
                    or cache_backend.client.decode(encoded) != updated
                ):
                    return AtomicOtpOutcome("unavailable")
            except Exception:
                return AtomicOtpOutcome("unavailable")

            pipe.multi()
            # XX refuses recreation after expiry; KEEPTTL never extends lifetime.
            pipe.set(physical, encoded, xx=True, keepttl=True)
            if not _confirmed_set(pipe.execute()):
                return AtomicOtpOutcome("unavailable")
            return AtomicOtpOutcome(
                "wrong", attempts_remaining=record["max_attempts"] - next_attempts
            )
    except WatchError:
        return AtomicOtpOutcome("unavailable")
    except Exception:
        # No raw error details, redis URL, mobile, submitted digest or pickle
        # leak, including after a possibly committed but unacknowledged EXEC.
        return AtomicOtpOutcome("unavailable")
