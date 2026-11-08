"""Phase 7.22 synthetic all-four-key OTP issuance/cooldown/rate CAS.

CI ONLY, NOT a production OTP issuer, verifier, rate limiter or auth grant.
One isolated Redis master cannot establish durable multi-host fencing.
Real Django-Redis 5.4 pickled STRING serialization is used only on fixtures
created inside the disposable container. Never deserialize untrusted records.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any, Callable

from redis.exceptions import WatchError

PREFIX = "loomera:phase722:synthetic-issue-only:"
REDIS_URL = "redis://127.0.0.1:6414/15"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_MOBILE = re.compile(r"09[0-9]{9}\Z")
_DIGEST = re.compile(r"[0-9a-f]{40}\Z")
_IP_TAG = re.compile(r"synthetic_ip_[0-9]{2}\Z")
RECORD_TTL = 120
RESEND_TTL = 60
RATE_TTL = 3600
MOBILE_LIMIT = 2
IP_LIMIT = 3


@dataclass(frozen=True, slots=True)
class SyntheticIssueEvidence:
    status: str
    mobile_requests_remaining: int | None = None
    ip_requests_remaining: int | None = None
    mutation_confirmed: bool = False
    synthetic_record_created: bool = False
    real_otp_issued: bool = False
    real_otp_consumed: bool = False
    real_authentication_allowed: bool = False
    real_session_created: bool = False
    production_cutover_authorized: bool = False
    live_issuance_or_rate_atomicity_fixed: bool = False
    historical_legacy_race_fixed: bool = False
    multihost_fencing_proven: bool = False
    cross_store_consistency_proven: bool = False


def validate_synthetic_scope(cache: Any, redis_client: Any, *,
                             fixture_id: str, mobile: str,
                             ip_tag: str, now_ts: int,
                             code_digest: str) -> tuple[str, str, str, str]:
    """Reject any nonlocal/unauthorized cache BEFORE calling Redis."""
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("LOOMERA_PHASE722_TEST_REDIS") != "1"
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")):
        raise RuntimeError("Phase 7.22 requires disposable GitHub CI grant")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("invalid random fixture")
    if type(mobile) is not str or _MOBILE.fullmatch(mobile) is None:
        raise ValueError("only synthetic 09 mobile fixtures")
    if type(ip_tag) is not str or _IP_TAG.fullmatch(ip_tag) is None:
        raise ValueError("only synthetic IP tokens, never real addresses")
    if type(code_digest) is not str or _DIGEST.fullmatch(code_digest) is None:
        raise ValueError("synthetic salted HMAC digest must be SHA1 40hex")
    if type(now_ts) is not int or now_ts < 0:
        raise ValueError("strict nonnegative integer clock required")
    prefix = PREFIX + fixture_id
    if (getattr(cache, "key_prefix", None) != prefix
            or type(getattr(cache, "version", None)) is not int
            or getattr(cache, "version", None) != 1
            or getattr(cache, "_server", None) != REDIS_URL):
        raise RuntimeError("Django-Redis fixture backend not isolated")
    try:
        kw = redis_client.connection_pool.connection_kwargs
        host, port, db = kw.get("host"), kw.get("port"), kw.get("db")
        decode_responses = kw.get("decode_responses", False)
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable raw Redis client") from exc
    if (host != "127.0.0.1" or type(port) is not int or port != 6414
            or type(db) is not int or db != 15 or decode_responses is not False):
        raise RuntimeError("only isolated Redis 127.0.0.1:6414/15 allowed")
    hour = now_ts // 3600
    logical = (
        f"record:app_login:{mobile}",
        f"resend:app_login:{mobile}",
        f"rate:mobile:app_login_{mobile}:{hour}",
        f"rate:ip:{ip_tag}:{hour}",
    )
    physical = tuple(str(cache.make_key(key)) for key in logical)
    expected = tuple(f"{prefix}:1:{key}" for key in logical)
    if physical != expected or len(set(physical)) != 4:
        raise RuntimeError("unexpected Django-Redis key transformation")
    return physical


def _read_present(pipe: Any, cache: Any, key: str, *, max_ttl_ms: int):
    """Read exactly one WATCHed legacy STRING; distinguish missing/malformed."""
    kind = pipe.type(key)
    if kind == b"none":
        return "missing", None
    if kind != b"string":
        return "invalid", None
    ttl = pipe.pttl(key)
    if type(ttl) is not int or not 0 < ttl <= max_ttl_ms:
        return "invalid", None
    raw = pipe.get(key)
    if type(raw) is not bytes:
        return "invalid", None
    try:
        decoded = cache.client.decode(raw)
    except Exception:
        return "invalid", None
    return "present", decoded


def _serialized(cache: Any, value: Any) -> bytes | int:
    """Use real Django-Redis 5.4 wire, including its integer optimization.

    django-redis intentionally sends plain integers without pickling; redis-py
    serializes them to numeric Redis STRING bytes. Reject bool/subclass types.
    """
    raw = cache.client.encode(value)
    if type(value) is int:
        if type(raw) is not int or raw != value:
            raise ValueError("integer wire mismatch")
        return raw
    if type(raw) is not bytes or cache.client.decode(raw) != value:
        raise ValueError("legacy serializer roundtrip mismatch")
    return raw


def attempt_synthetic_atomic_issue(
    cache: Any, redis_client: Any, *, fixture_id: str, mobile: str,
    ip_tag: str, now_ts: int, code_digest: str,
    on_watched_read: Callable[[], None] | None = None,
) -> SyntheticIssueEvidence:
    """Atomically issue a fake code, cooldown and two rate counters.

    WATCH record+cooldown+mobile_hour+ip_hour before all reads.  No unsafe
    key-specific fallback. Existing challenge or cooldown blocks issuance.
    Every candidate SET command is queued in the same MULTI transaction.
    Counters never have their remaining TTL extended after first creation.
    On a lost EXEC reply, mutation may have committed, but NEVER grant success.
    """
    record_key, cooldown_key, mobile_key, ip_key = validate_synthetic_scope(
        cache, redis_client, fixture_id=fixture_id, mobile=mobile,
        ip_tag=ip_tag, now_ts=now_ts, code_digest=code_digest,
    )
    if on_watched_read is not None and not callable(on_watched_read):
        raise TypeError("scheduler hook must be callable")
    try:
        with redis_client.pipeline(transaction=True) as pipe:
            pipe.watch(record_key, cooldown_key, mobile_key, ip_key)
            record_state, _ = _read_present(
                pipe, cache, record_key, max_ttl_ms=RECORD_TTL * 1000,
            )
            if record_state == "invalid":
                return SyntheticIssueEvidence("invalid_existing_record")
            if record_state == "present":
                return SyntheticIssueEvidence("challenge_already_pending")
            cooldown_state, cooldown = _read_present(
                pipe, cache, cooldown_key, max_ttl_ms=RESEND_TTL * 1000,
            )
            if cooldown_state == "invalid":
                return SyntheticIssueEvidence("invalid_cooldown")
            if cooldown_state == "present":
                if type(cooldown) is not int or not 0 <= cooldown <= now_ts:
                    return SyntheticIssueEvidence("invalid_cooldown")
                # Existing TTL is authoritative even under simulated clock
                # drift; never skip a persisted cooldown.
                return SyntheticIssueEvidence("resend_cooldown_active")

            mobile_state, mobile_used = _read_present(
                pipe, cache, mobile_key, max_ttl_ms=RATE_TTL * 1000,
            )
            ip_state, ip_used = _read_present(
                pipe, cache, ip_key, max_ttl_ms=RATE_TTL * 1000,
            )
            if mobile_state == "invalid" or ip_state == "invalid":
                return SyntheticIssueEvidence("invalid_rate_state")
            if mobile_state == "missing":
                mobile_used = 0
            if ip_state == "missing":
                ip_used = 0
            if (type(mobile_used) is not int or type(ip_used) is not int
                    or not 0 <= mobile_used <= MOBILE_LIMIT
                    or not 0 <= ip_used <= IP_LIMIT):
                return SyntheticIssueEvidence("invalid_rate_state")
            if mobile_used >= MOBILE_LIMIT:
                return SyntheticIssueEvidence("mobile_rate_limited", 0)
            if ip_used >= IP_LIMIT:
                return SyntheticIssueEvidence(
                    "ip_rate_limited", MOBILE_LIMIT - mobile_used, 0,
                )

            record = {
                "purpose": "app_login",
                "mobile_number": mobile,
                "code_hash": code_digest,
                "created_at": now_ts,
                "expires_at": now_ts + RECORD_TTL,
                "attempts": 0,
                "max_attempts": 5,
                "verified": False,
                "delivery": {
                    "channel": "sms", "mode": "simulated",
                    "sent": False, "provider": "none",
                },
            }
            try:
                payloads = (
                    _serialized(cache, record),
                    _serialized(cache, now_ts),
                    _serialized(cache, mobile_used + 1),
                    _serialized(cache, ip_used + 1),
                )
            except Exception:
                return SyntheticIssueEvidence("serialization_unavailable")

            if on_watched_read is not None:
                on_watched_read()

            pipe.multi()
            pipe.set(record_key, payloads[0], ex=RECORD_TTL)
            pipe.set(cooldown_key, payloads[1], ex=RESEND_TTL)
            if mobile_state == "missing":
                pipe.set(mobile_key, payloads[2], ex=RATE_TTL)
            else:
                pipe.set(mobile_key, payloads[2], xx=True, keepttl=True)
            if ip_state == "missing":
                pipe.set(ip_key, payloads[3], ex=RATE_TTL)
            else:
                pipe.set(ip_key, payloads[3], xx=True, keepttl=True)
            reply = pipe.execute()
            if (type(reply) is not list or len(reply) != 4
                    or any(value is not True for value in reply)):
                return SyntheticIssueEvidence("issue_unconfirmed")
            return SyntheticIssueEvidence(
                "synthetic_issued",
                mobile_requests_remaining=MOBILE_LIMIT - mobile_used - 1,
                ip_requests_remaining=IP_LIMIT - ip_used - 1,
                mutation_confirmed=True,
                synthetic_record_created=True,
            )
    except WatchError:
        return SyntheticIssueEvidence("concurrent_modification_conflict")
    except Exception:
        return SyntheticIssueEvidence("backend_unavailable")
