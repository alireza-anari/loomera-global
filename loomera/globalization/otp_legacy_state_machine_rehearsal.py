"""Phase 7.21 — synthetic complete per-record OTP WATCH state transition.

Never imported by authentication, session, API, or Production code.  A single
Redis 7.4 server is NOT a durable multi-host authority or an approved verifier.

The only operations on an actual Django-Redis 5.4 serialized STRING are:
  correct code: WATCH -> validation -> MULTI DEL -> EXEC [1]
  wrong code:   WATCH -> validation -> MULTI SET XX KEEPTTL -> EXEC [True]
  last wrong:   WATCH -> validation -> MULTI DEL -> EXEC [1]
All other states fail closed with NO mutation and NO authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import secrets
from typing import Any, Callable

from redis.exceptions import WatchError

PREFIX = "loomera:phase721:synthetic-record-only:"
REDIS_URL = "redis://127.0.0.1:6413/15"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_LOGICAL = re.compile(r"record:app_login:09[0-9]{9}\Z")
_DIGEST = re.compile(r"[0-9a-f]{40}\Z")
MAX_TTL_MS = 180_000


@dataclass(frozen=True, slots=True)
class SyntheticOtpTransition:
    status: str
    attempts_remaining: int | None = None
    mutation_confirmed: bool = False
    synthetic_challenge_consumed: bool = False
    real_authentication_allowed: bool = False
    real_session_created: bool = False
    real_otp_issued_or_consumed: bool = False
    production_cutover_authorized: bool = False
    historical_legacy_race_fixed: bool = False
    atomic_issuance_or_rates_proven: bool = False
    durable_multihost_fencing_proven: bool = False
    cross_store_consistency_proven: bool = False


def validate_scope(cache: Any, redis_client: Any, *,
                   fixture_id: str, logical_key: str) -> str:
    """Fail before IO on wrong host, key, CI grant or Django cache namespace."""
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("LOOMERA_PHASE721_TEST_REDIS") != "1"
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")):
        raise RuntimeError("Phase 7.21 requires explicit disposable GitHub CI")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("invalid isolated fixture identifier")
    if type(logical_key) is not str or _LOGICAL.fullmatch(logical_key) is None:
        raise ValueError("unexpected logical key")
    prefix = PREFIX + fixture_id
    if (getattr(cache, "key_prefix", None) != prefix
            or type(getattr(cache, "version", None)) is not int
            or getattr(cache, "version", None) != 1
            or getattr(cache, "_server", None) != REDIS_URL):
        raise RuntimeError("Django-Redis backend or namespace not isolated")
    try:
        kw = redis_client.connection_pool.connection_kwargs
        host, port, db = kw.get("host"), kw.get("port"), kw.get("db")
        decode_responses = kw.get("decode_responses", False)
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis client") from exc
    if (host != "127.0.0.1" or type(port) is not int or port != 6413
            or type(db) is not int or db != 15 or decode_responses is not False):
        raise RuntimeError("only raw-byte loopback Redis DB15/6413 permitted")
    physical = f"{prefix}:1:{logical_key}"
    if str(cache.make_key(logical_key)) != physical:
        raise RuntimeError("unexpected physical key")
    return physical


def _legacy_record_valid(record: Any, logical_key: str, now_ts: int) -> bool:
    if type(record) is not dict:
        return False
    required = {"purpose", "mobile_number", "code_hash", "created_at",
                "expires_at", "attempts", "max_attempts", "verified"}
    if not required.issubset(record):
        return False
    mobile = logical_key.rsplit(":", 1)[-1]
    return (
        record["purpose"] == "app_login"
        and type(record["mobile_number"]) is str
        and record["mobile_number"] == mobile
        and type(record["code_hash"]) is str
        and _DIGEST.fullmatch(record["code_hash"]) is not None
        and type(record["created_at"]) is int
        and 0 <= record["created_at"] <= now_ts
        and type(record["expires_at"]) is int
        and now_ts <= record["expires_at"]
        and type(record["attempts"]) is int
        and type(record["max_attempts"]) is int
        and 0 <= record["attempts"] < record["max_attempts"] <= 10
        and record["verified"] is False
    )


def _confirmed_delete(reply: Any) -> bool:
    return type(reply) is list and len(reply) == 1 and type(reply[0]) is int and reply[0] == 1


def _confirmed_set(reply: Any) -> bool:
    return type(reply) is list and len(reply) == 1 and reply[0] is True


def apply_synthetic_otp_transition(
    cache: Any, redis_client: Any, *, fixture_id: str, logical_key: str,
    submitted_digest: str, now_ts: int,
    on_watched_read: Callable[[], None] | None = None,
) -> SyntheticOtpTransition:
    """Single-node optimistic atomic success, invalid-attempt and exhaustion.

    WATCH precedes TYPE/PTTL/GET. On nonterminal wrong code, use the SAME
    transaction connection to SET XX KEEPTTL serialized Django-Redis bytes;
    no expiry extension and no accidental re-creation of an expired record.
    An intervening SET (even identical bytes), expiry, or DEL aborts EXEC.
    No retry of an ambiguous result, no unsafe fallback, and no real grant.
    """
    physical = validate_scope(
        cache, redis_client, fixture_id=fixture_id, logical_key=logical_key,
    )
    if type(submitted_digest) is not str or _DIGEST.fullmatch(submitted_digest) is None:
        raise ValueError("synthetic 40-hex digest required")
    if type(now_ts) is not int or now_ts < 0:
        raise ValueError("strict synthetic timestamp required")
    if on_watched_read is not None and not callable(on_watched_read):
        raise TypeError("only callable deterministic test scheduling hook allowed")

    try:
        with redis_client.pipeline(transaction=True) as pipe:
            pipe.watch(physical)
            kind = pipe.type(physical)
            if kind == b"none":
                return SyntheticOtpTransition("missing")
            if kind != b"string":
                return SyntheticOtpTransition("wrong_type")
            ttl_ms = pipe.pttl(physical)
            if type(ttl_ms) is not int or not 0 < ttl_ms <= MAX_TTL_MS:
                return SyntheticOtpTransition("invalid_ttl")
            raw = pipe.get(physical)
            if type(raw) is not bytes:
                return SyntheticOtpTransition("invalid_wire")
            try:
                record = cache.client.decode(raw)
            except Exception:
                return SyntheticOtpTransition("invalid_wire")
            if not _legacy_record_valid(record, logical_key, now_ts):
                return SyntheticOtpTransition("invalid_record")

            matched = secrets.compare_digest(
                record["code_hash"], submitted_digest,
            )
            if on_watched_read is not None:
                on_watched_read()
            if matched:
                pipe.multi()
                pipe.delete(physical)
                reply = pipe.execute()
                if not _confirmed_delete(reply):
                    return SyntheticOtpTransition("delete_unconfirmed")
                return SyntheticOtpTransition(
                    "synthetic_single_winner", mutation_confirmed=True,
                    synthetic_challenge_consumed=True,
                )

            next_attempts = record["attempts"] + 1
            if next_attempts >= record["max_attempts"]:
                pipe.multi()
                pipe.delete(physical)
                reply = pipe.execute()
                if not _confirmed_delete(reply):
                    return SyntheticOtpTransition("exhaustion_unconfirmed")
                return SyntheticOtpTransition(
                    "synthetic_exhausted", attempts_remaining=0,
                    mutation_confirmed=True,
                )

            # Serialize *exactly* via django-redis 5.4, not a new HASH schema.
            updated = dict(record)
            updated["attempts"] = next_attempts
            try:
                encoded = cache.client.encode(updated)
                if type(encoded) is not bytes or cache.client.decode(encoded) != updated:
                    return SyntheticOtpTransition("serialization_unavailable")
            except Exception:
                return SyntheticOtpTransition("serialization_unavailable")

            pipe.multi()
            # Redis >= 6: XX prevents recreating missing keys; KEEPTTL avoids
            # extending the challenge lifetime during wrong-code retries.
            pipe.set(physical, encoded, xx=True, keepttl=True)
            reply = pipe.execute()
            if not _confirmed_set(reply):
                return SyntheticOtpTransition("attempt_update_unconfirmed")
            return SyntheticOtpTransition(
                "synthetic_invalid_attempt",
                attempts_remaining=record["max_attempts"] - next_attempts,
                mutation_confirmed=True,
            )
    except WatchError:
        return SyntheticOtpTransition("concurrent_modification_conflict")
    except Exception:
        # Even if EXEC's network response is lost after server-side commit,
        # this status must never be interpreted as authentication permission.
        return SyntheticOtpTransition("backend_unavailable")
