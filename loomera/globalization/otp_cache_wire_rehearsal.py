"""Phase 7.8: read-only, synthetic Django-Redis OTP wire preflight.

This is NOT an OTP verifier, converter, session bridge or runtime adapter.
It reads only deliberately created disposable fixtures on localhost Redis DB
15, with a per-test namespace and explicit environment grant.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

PREFIX = "loomera:phase78:synthetic-only:"
_FIXTURE = re.compile(r"[0-9a-f]{32}\Z")
_LOGICAL = re.compile(r"record:app_login:09[0-9]{9}\Z")
# Django salted_hmac defaults to SHA-1 (40 lowercase hex), not Phase 7.7 SHA-256.
_HASH = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class LegacyWireEvidence:
    """Only fixed result codes and bounded TTL; no secret or identity."""

    status: str
    ttl_ms: int = 0
    hash_compatible: bool = False
    authenticated: bool = False
    cutover_authorized: bool = False


def _verify_isolation(cache: Any, redis_client: Any, fixture_id: str, logical_key: str) -> None:
    if os.environ.get("LOOMERA_PHASE78_TEST_REDIS") != "1":
        raise RuntimeError("explicit Phase 7.8 synthetic fixture grant required")
    if type(fixture_id) is not str or _FIXTURE.fullmatch(fixture_id) is None:
        raise ValueError("random synthetic fixture id required")
    if type(logical_key) is not str or _LOGICAL.fullmatch(logical_key) is None:
        raise ValueError("synthetic legacy app-login key required")
    prefix = PREFIX + fixture_id
    if getattr(cache, "key_prefix", None) != prefix or getattr(cache, "version", None) != 1:
        raise RuntimeError("unverifiable isolated Django cache prefix")
    # Checking only the independent raw client is insufficient: a supplied
    # Django-Redis cache object could otherwise point at a remote backend.
    server = getattr(cache, "_server", None)
    if type(server) is not str or server not in {
        "redis://127.0.0.1:6379/15", "redis://localhost:6379/15",
    }:
        raise RuntimeError("Django-Redis fixture backend must be local DB15")
    try:
        conn = redis_client.connection_pool.connection_kwargs
        host, port, db = conn.get("host"), conn.get("port", 6379), conn.get("db")
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis connection") from exc
    if host not in {"localhost", "127.0.0.1"} or type(port) is not int or port != 6379 or type(db) is not int or db != 15:
        raise RuntimeError("only local disposable Redis DB15 permitted")
    if str(cache.make_key(logical_key)) != f"{prefix}:1:{logical_key}":
        raise RuntimeError("unexpected Django cache key transformation")


def inspect_synthetic_legacy_wire(
    cache: Any, redis_client: Any, *, fixture_id: str, logical_key: str
) -> LegacyWireEvidence:
    """Inspect a disposable legacy-format fixture without mutation or OTP auth.

    A successful inspection still CANNOT authorize a bridge: the Redis STRING
    stores Django-Redis's serialized dict, whereas Phase 7.7 expects a HASH.
    The result never contains the mobile number, code, digest or Redis key.
    """
    _verify_isolation(cache, redis_client, fixture_id, logical_key)
    try:
        physical = str(cache.make_key(logical_key))
        kind = redis_client.type(physical)
        if kind == b"none":
            return LegacyWireEvidence("absent")
        if kind != b"string":
            return LegacyWireEvidence("incompatible_redis_type")
        ttl = redis_client.pttl(physical)
        if type(ttl) is not int or ttl <= 0:
            return LegacyWireEvidence("missing_or_invalid_ttl")
        payload = cache.get(logical_key)
        if type(payload) is not dict:
            return LegacyWireEvidence("invalid_legacy_payload")
        expected_mobile = logical_key.rsplit(":", 1)[-1]
        required = {"purpose", "mobile_number", "code_hash", "created_at",
                    "expires_at", "attempts", "max_attempts", "verified"}
        if not required.issubset(payload):
            return LegacyWireEvidence("invalid_legacy_payload")
        if (
            payload["purpose"] != "app_login"
            or payload["mobile_number"] != expected_mobile
            or type(payload["code_hash"]) is not str
            or _HASH.fullmatch(payload["code_hash"]) is None
            or type(payload["created_at"]) is not int
            or type(payload["expires_at"]) is not int
            or payload["expires_at"] <= payload["created_at"]
            or type(payload["attempts"]) is not int
            or type(payload["max_attempts"]) is not int
            or not 0 <= payload["attempts"] < payload["max_attempts"] <= 10
            or payload["verified"] is not False
        ):
            return LegacyWireEvidence("invalid_legacy_payload")
        return LegacyWireEvidence("legacy_string_pending_drain", min(ttl, 600_000))
    except Exception:
        # Redis failure or malformed pickled fixture: cannot infer readiness.
        return LegacyWireEvidence("backend_unavailable")
