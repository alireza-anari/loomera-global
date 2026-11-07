"""Phase 7.20 WATCH/MULTI candidate on disposable Django-Redis STRING fixtures.

NOT imported by auth code; NOT a production verifier or session grant.
WATCH must precede the raw byte read: both DELETE races and identical-byte
ABA reissues then conflict, unlike legacy get/compare/delete.
Single Redis node only: this does NOT establish failover durability/fencing.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import secrets
from typing import Any, Callable

from redis.exceptions import WatchError

PREFIX = "loomera:phase720:synthetic-watch-only:"
REDIS_URL = "redis://127.0.0.1:6412/15"
_FIXTURE_ID = re.compile(r"[0-9a-f]{32}\Z")
_LOGICAL = re.compile(r"record:app_login:09[0-9]{9}\Z")
_SHA1_DIGEST = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class WatchCandidateEvidence:
    status: str
    synthetic_record_deleted: bool = False
    authenticated: bool = False
    session_created: bool = False
    otp_production_consume_allowed: bool = False
    production_cutover_authorized: bool = False
    failover_fencing_proven: bool = False
    legacy_rate_limit_race_fixed: bool = False
    legacy_otp_replay_race_fixed: bool = False


def validate_synthetic_scope(
    cache: Any, redis_client: Any, *, fixture_id: str, logical_key: str
) -> str:
    """Strictly reject non-CI, nonlocal, unknown-prefix and wrong-DB clients."""
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("GITHUB_RUN_ID")
            or os.environ.get("LOOMERA_PHASE720_TEST_REDIS") != "1"):
        raise RuntimeError("Phase 7.20 requires explicit GitHub disposable grant")
    if type(fixture_id) is not str or not _FIXTURE_ID.fullmatch(fixture_id):
        raise ValueError("random fixture id required")
    if type(logical_key) is not str or not _LOGICAL.fullmatch(logical_key):
        raise ValueError("only synthetic legacy app_login logical key supported")
    prefix = PREFIX + fixture_id
    if getattr(cache, "key_prefix", None) != prefix or getattr(cache, "version", None) != 1:
        raise RuntimeError("unexpected Django-Redis namespace or version")
    if getattr(cache, "_server", None) != REDIS_URL:
        raise RuntimeError("Django-Redis backend not explicitly isolated")
    try:
        kw = redis_client.connection_pool.connection_kwargs
        host, port, db = kw.get("host"), kw.get("port"), kw.get("db")
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable raw Redis client") from exc
    if (host != "127.0.0.1" or type(port) is not int or port != 6412
            or type(db) is not int or db != 15):
        raise RuntimeError("raw Redis client must be loopback:6412 DB15")
    expected = f"{prefix}:1:{logical_key}"
    if str(cache.make_key(logical_key)) != expected:
        raise RuntimeError("unexpected physical key transformation")
    return expected


def _valid_legacy_record(record: Any, *, logical_key: str, now_ts: int) -> bool:
    if type(record) is not dict:
        return False
    required = {"purpose", "mobile_number", "code_hash", "created_at",
                "expires_at", "attempts", "max_attempts", "verified"}
    if not required.issubset(record):
        return False
    expected_mobile = logical_key.rsplit(":", 1)[-1]
    return (
        record["purpose"] == "app_login"
        and record["mobile_number"] == expected_mobile
        and type(record["code_hash"]) is str
        and _SHA1_DIGEST.fullmatch(record["code_hash"]) is not None
        and type(record["created_at"]) is int
        and type(record["expires_at"]) is int
        and record["created_at"] >= 0
        and record["created_at"] <= now_ts <= record["expires_at"]
        and type(record["attempts"]) is int
        and type(record["max_attempts"]) is int
        and 0 <= record["attempts"] < record["max_attempts"] <= 10
        and record["verified"] is False
    )


def attempt_synthetic_watch_consume(
    cache: Any, redis_client: Any, *, fixture_id: str, logical_key: str,
    submitted_digest: str, now_ts: int,
    on_watched_read: Callable[[], None] | None = None,
) -> WatchCandidateEvidence:
    """Try a single-winner DELETE of the EXACT observed serialized STRING.

    Use WATCH before GET; any intervening SET, DELETE or same-byte reissue
    causes EXEC to conflict. No TTL extension, retries or fallback.
    Wrong code does not update attempts (candidate is INCOMPLETE).
    Hook is only to force deterministic race/ABA test scheduling.
    """
    physical = validate_synthetic_scope(
        cache, redis_client, fixture_id=fixture_id, logical_key=logical_key,
    )
    if (type(submitted_digest) is not str
            or _SHA1_DIGEST.fullmatch(submitted_digest) is None):
        raise ValueError("only synthetic 40-hex SHA1 digest accepted")
    if type(now_ts) is not int or now_ts < 0:
        raise ValueError("strict synthetic timestamp required")
    if on_watched_read is not None and not callable(on_watched_read):
        raise TypeError("test-only schedule hook must be callable")

    try:
        with redis_client.pipeline(transaction=True) as transaction:
            transaction.watch(physical)
            kind = transaction.type(physical)
            if kind == b"none":
                return WatchCandidateEvidence("missing")
            if kind != b"string":
                return WatchCandidateEvidence("wrong_redis_type")
            ttl_ms = transaction.pttl(physical)
            if type(ttl_ms) is not int or not 0 < ttl_ms <= 180_000:
                return WatchCandidateEvidence("invalid_ttl")
            raw = transaction.get(physical)
            if type(raw) is not bytes:
                return WatchCandidateEvidence("invalid_wire")
            try:
                record = cache.client.decode(raw)
            except Exception:
                return WatchCandidateEvidence("invalid_wire")
            if not _valid_legacy_record(record, logical_key=logical_key, now_ts=now_ts):
                return WatchCandidateEvidence("invalid_record")
            if not secrets.compare_digest(record["code_hash"], submitted_digest):
                return WatchCandidateEvidence("wrong_digest")

            # WATCH remains held across this deliberate test-only scheduling
            # hook. A competing deletion or byte-identical new SET MUST abort.
            if on_watched_read is not None:
                on_watched_read()
            transaction.multi()
            transaction.delete(physical)
            deleted = transaction.execute()
            if deleted != [1]:
                return WatchCandidateEvidence("delete_unconfirmed")
            return WatchCandidateEvidence("synthetic_single_winner", True)
    except WatchError:
        return WatchCandidateEvidence("concurrent_modification_conflict")
    except Exception:
        # No retry to an unsafe get/delete path; no exception details or
        # mobile, raw bytes, digest or backend endpoint escape.
        return WatchCandidateEvidence("backend_unavailable")
