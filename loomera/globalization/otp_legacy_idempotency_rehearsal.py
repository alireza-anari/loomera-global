"""Phase 7.24 — bounded synthetic OTP operation-idempotency ledger (CI ONLY).

On the SAME isolated Redis node and exact Django-Redis 5.4 legacy STRING keys
used in Phase 7.22/7.23, WATCH the operation ledger AND affected challenge /
rate keys before read; enqueue the ledger in the SAME MULTI/EXEC. Synthetic
retries of an acknowledged-or-ambiguous commit recover the prior *test-only*
outcome without extra quota charge, attempt decrement or verification.

No Django login, SMS, Production, failover/partition fencing or global durable
exactly-once semantics. Ledger eviction/expiry loses the guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import secrets
from typing import Any, Callable

from redis.exceptions import WatchError

from loomera.globalization.otp_legacy_issue_rate_rehearsal import (
    MOBILE_LIMIT, IP_LIMIT, RECORD_TTL, RESEND_TTL, RATE_TTL,
    _read_present, _serialized, validate_synthetic_scope,
)
from loomera.globalization.otp_legacy_state_machine_rehearsal import (
    _legacy_record_valid,
)

LEDGER_TTL = 3900  # deliberately longer than all 3600s synthetic rate keys
_OP_ID = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_PRIOR = frozenset({
    "synthetic_issued", "synthetic_single_winner",
    "synthetic_invalid_attempt", "synthetic_exhausted",
})


@dataclass(frozen=True, slots=True)
class SyntheticIdempotencyEvidence:
    status: str
    prior_status: str | None = None
    attempts_remaining: int | None = None
    mobile_requests_remaining: int | None = None
    ip_requests_remaining: int | None = None
    mutation_confirmed: bool = False
    replay_observed: bool = False
    real_otp_issued_or_consumed: bool = False
    real_authentication_allowed: bool = False
    real_session_created: bool = False
    automatic_retry_or_grant_authorized: bool = False
    production_cutover_authorized: bool = False
    live_idempotency_fixed: bool = False
    multihost_fencing_proven: bool = False
    cross_store_consistency_proven: bool = False


def _prepare(cache: Any, redis_client: Any, *,
             fixture_id: str, mobile: str, ip_tag: str, now_ts: int,
             digest: str, operation_id: str, kind: str):
    """Strict CI-only scope before any Redis network access."""
    if os.environ.get("LOOMERA_PHASE724_TEST_REDIS") != "1":
        raise RuntimeError("Phase 7.24 requires explicit disposable CI grant")
    if type(operation_id) is not str or _OP_ID.fullmatch(operation_id) is None:
        raise ValueError("32-hex synthetic operation id required")
    record_key, cooldown_key, mobile_key, ip_key = validate_synthetic_scope(
        cache, redis_client, fixture_id=fixture_id, mobile=mobile,
        ip_tag=ip_tag, now_ts=now_ts, code_digest=digest,
    )
    # Global per-fixture key, not per operation type, catches reuse of an
    # issue operation ID as a verification ID (and vice versa).
    logical = "operation:synthetic:" + operation_id
    physical = str(cache.make_key(logical))
    expected = f"{cache.key_prefix}:1:{logical}"
    if physical != expected or physical in (
        record_key, cooldown_key, mobile_key, ip_key,
    ):
        raise RuntimeError("unexpected synthetic operation ledger key")
    # Exclude now_ts: retries may happen later with a different clock. Include
    # identity, issuer IP scope and digest: same operation cannot be repurposed.
    fingerprint = hashlib.sha256(
        ("phase724|v1|" + kind + "|" + mobile + "|" + ip_tag + "|" + digest)
        .encode("ascii"),
    ).hexdigest()
    return (physical, record_key, cooldown_key, mobile_key, ip_key, fingerprint)


def _read_ledger(pipe: Any, cache: Any, physical: str, fingerprint: str):
    state, item = _read_present(
        pipe, cache, physical, max_ttl_ms=LEDGER_TTL * 1000,
    )
    if state == "missing":
        return None
    if state != "present" or type(item) is not dict:
        return SyntheticIdempotencyEvidence("invalid_operation_ledger")
    if set(item) != {"fingerprint", "prior_status", "remaining", "mobile_left", "ip_left"}:
        return SyntheticIdempotencyEvidence("invalid_operation_ledger")
    if (type(item["fingerprint"]) is not str
            or _SHA256.fullmatch(item["fingerprint"]) is None
            or type(item["prior_status"]) is not str
            or item["prior_status"] not in _ALLOWED_PRIOR):
        return SyntheticIdempotencyEvidence("invalid_operation_ledger")
    for field in ("remaining", "mobile_left", "ip_left"):
        val = item[field]
        if val is not None and (type(val) is not int or not 0 <= val <= 10):
            return SyntheticIdempotencyEvidence("invalid_operation_ledger")
    if not secrets.compare_digest(item["fingerprint"], fingerprint):
        return SyntheticIdempotencyEvidence("operation_reuse_conflict")
    return SyntheticIdempotencyEvidence(
        "synthetic_replayed", prior_status=item["prior_status"],
        attempts_remaining=item["remaining"],
        mobile_requests_remaining=item["mobile_left"],
        ip_requests_remaining=item["ip_left"],
        replay_observed=True,
    )


def _ledger_payload(cache: Any, fingerprint: str, *,
                    status: str, remaining: int | None = None,
                    mobile_left: int | None = None, ip_left: int | None = None):
    return _serialized(cache, {
        "fingerprint": fingerprint,
        "prior_status": status,
        "remaining": remaining,
        "mobile_left": mobile_left,
        "ip_left": ip_left,
    })


def _confirmed(reply: Any, *, count: int, delete_first: bool = False) -> bool:
    if type(reply) is not list or len(reply) != count:
        return False
    if delete_first:
        return (type(reply[0]) is int and reply[0] == 1
                and all(x is True for x in reply[1:]))
    return all(x is True for x in reply)


def attempt_synthetic_idempotent_issue(
    cache: Any, redis_client: Any, *, fixture_id: str, mobile: str,
    ip_tag: str, now_ts: int, code_digest: str, operation_id: str,
    on_watched_read: Callable[[], None] | None = None,
) -> SyntheticIdempotencyEvidence:
    """Atomic five-key issue: four existing Phase 7.22 keys + op ledger."""
    ledger, rec, cool, mobile_key, ip_key, fp = _prepare(
        cache, redis_client, fixture_id=fixture_id, mobile=mobile,
        ip_tag=ip_tag, now_ts=now_ts, digest=code_digest,
        operation_id=operation_id, kind="issue",
    )
    if on_watched_read is not None and not callable(on_watched_read):
        raise TypeError("test scheduler must be callable")
    try:
        with redis_client.pipeline(transaction=True) as pipe:
            pipe.watch(ledger, rec, cool, mobile_key, ip_key)
            prior = _read_ledger(pipe, cache, ledger, fp)
            if prior is not None:
                return prior
            rec_state, _ = _read_present(
                pipe, cache, rec, max_ttl_ms=RECORD_TTL * 1000,
            )
            if rec_state == "invalid":
                return SyntheticIdempotencyEvidence("invalid_existing_record")
            if rec_state == "present":
                return SyntheticIdempotencyEvidence("challenge_already_pending")
            resend_state, resend = _read_present(
                pipe, cache, cool, max_ttl_ms=RESEND_TTL * 1000,
            )
            if resend_state == "invalid":
                return SyntheticIdempotencyEvidence("invalid_cooldown")
            if resend_state == "present":
                if type(resend) is not int or not 0 <= resend <= now_ts:
                    return SyntheticIdempotencyEvidence("invalid_cooldown")
                return SyntheticIdempotencyEvidence("resend_cooldown_active")

            m_state, m = _read_present(
                pipe, cache, mobile_key, max_ttl_ms=RATE_TTL * 1000,
            )
            ip_state, n = _read_present(
                pipe, cache, ip_key, max_ttl_ms=RATE_TTL * 1000,
            )
            if m_state == "invalid" or ip_state == "invalid":
                return SyntheticIdempotencyEvidence("invalid_rate_state")
            if m_state == "missing":
                m = 0
            if ip_state == "missing":
                n = 0
            if (type(m) is not int or type(n) is not int
                    or not 0 <= m <= MOBILE_LIMIT
                    or not 0 <= n <= IP_LIMIT):
                return SyntheticIdempotencyEvidence("invalid_rate_state")
            if m >= MOBILE_LIMIT:
                return SyntheticIdempotencyEvidence("mobile_rate_limited")
            if n >= IP_LIMIT:
                return SyntheticIdempotencyEvidence("ip_rate_limited")

            record = {
                "purpose": "app_login", "mobile_number": mobile,
                "code_hash": code_digest, "created_at": now_ts,
                "expires_at": now_ts + RECORD_TTL,
                "attempts": 0, "max_attempts": 5, "verified": False,
                "delivery": {
                    "channel": "sms", "mode": "simulated",
                    "sent": False, "provider": "none",
                },
            }
            try:
                payloads = (
                    _serialized(cache, record), _serialized(cache, now_ts),
                    _serialized(cache, m + 1), _serialized(cache, n + 1),
                    _ledger_payload(
                        cache, fp, status="synthetic_issued",
                        mobile_left=MOBILE_LIMIT - m - 1,
                        ip_left=IP_LIMIT - n - 1,
                    ),
                )
            except Exception:
                return SyntheticIdempotencyEvidence("serialization_unavailable")

            if on_watched_read is not None:
                on_watched_read()
            pipe.multi()
            pipe.set(rec, payloads[0], ex=RECORD_TTL)
            pipe.set(cool, payloads[1], ex=RESEND_TTL)
            if m_state == "missing":
                pipe.set(mobile_key, payloads[2], ex=RATE_TTL)
            else:
                pipe.set(mobile_key, payloads[2], xx=True, keepttl=True)
            if ip_state == "missing":
                pipe.set(ip_key, payloads[3], ex=RATE_TTL)
            else:
                pipe.set(ip_key, payloads[3], xx=True, keepttl=True)
            pipe.set(ledger, payloads[4], ex=LEDGER_TTL)
            reply = pipe.execute()
            if not _confirmed(reply, count=5):
                return SyntheticIdempotencyEvidence("issue_unconfirmed")
            return SyntheticIdempotencyEvidence(
                "synthetic_issued",
                mobile_requests_remaining=MOBILE_LIMIT - m - 1,
                ip_requests_remaining=IP_LIMIT - n - 1,
                mutation_confirmed=True,
            )
    except WatchError:
        return SyntheticIdempotencyEvidence("concurrent_modification_conflict")
    except Exception:
        return SyntheticIdempotencyEvidence("backend_unavailable")


def attempt_synthetic_idempotent_verify(
    cache: Any, redis_client: Any, *, fixture_id: str, mobile: str,
    ip_tag: str, now_ts: int, submitted_digest: str, operation_id: str,
    on_watched_read: Callable[[], None] | None = None,
) -> SyntheticIdempotencyEvidence:
    """Atomic two-key legacy VERIFY attempt and synthetic operation ledger.

    Replay lookup happens first. All committed correct, wrong and exhausted
    outcomes are stored with the record mutation in the same MULTI/EXEC.
    Replayed correct results NEVER grant login, even if record was consumed.
    """
    ledger, rec, _, _, _, fp = _prepare(
        cache, redis_client, fixture_id=fixture_id, mobile=mobile,
        ip_tag=ip_tag, now_ts=now_ts, digest=submitted_digest,
        operation_id=operation_id, kind="verify",
    )
    if on_watched_read is not None and not callable(on_watched_read):
        raise TypeError("test scheduler must be callable")
    try:
        with redis_client.pipeline(transaction=True) as pipe:
            pipe.watch(ledger, rec)
            prior = _read_ledger(pipe, cache, ledger, fp)
            if prior is not None:
                return prior
            kind = pipe.type(rec)
            if kind == b"none":
                return SyntheticIdempotencyEvidence("missing")
            if kind != b"string":
                return SyntheticIdempotencyEvidence("wrong_type")
            ttl = pipe.pttl(rec)
            if type(ttl) is not int or not 0 < ttl <= RECORD_TTL * 1000:
                return SyntheticIdempotencyEvidence("invalid_ttl")
            raw = pipe.get(rec)
            if type(raw) is not bytes:
                return SyntheticIdempotencyEvidence("invalid_wire")
            try:
                record = cache.client.decode(raw)
            except Exception:
                return SyntheticIdempotencyEvidence("invalid_wire")
            if not _legacy_record_valid(
                record, f"record:app_login:{mobile}", now_ts,
            ):
                return SyntheticIdempotencyEvidence("invalid_record")
            matched = secrets.compare_digest(
                record["code_hash"], submitted_digest,
            )
            next_attempts = record["attempts"] + 1
            if matched:
                status, left, delete = "synthetic_single_winner", None, True
            elif next_attempts >= record["max_attempts"]:
                status, left, delete = "synthetic_exhausted", 0, True
            else:
                status = "synthetic_invalid_attempt"
                left = record["max_attempts"] - next_attempts
                delete = False
            try:
                entry = _ledger_payload(
                    cache, fp, status=status, remaining=left,
                )
                if not delete:
                    updated = dict(record)
                    updated["attempts"] = next_attempts
                    updated_raw = _serialized(cache, updated)
                    if type(updated_raw) is not bytes:
                        return SyntheticIdempotencyEvidence("serialization_unavailable")
            except Exception:
                return SyntheticIdempotencyEvidence("serialization_unavailable")

            if on_watched_read is not None:
                on_watched_read()
            pipe.multi()
            if delete:
                pipe.delete(rec)
            else:
                pipe.set(rec, updated_raw, xx=True, keepttl=True)
            pipe.set(ledger, entry, ex=LEDGER_TTL)
            reply = pipe.execute()
            if not _confirmed(reply, count=2, delete_first=delete):
                return SyntheticIdempotencyEvidence("verify_unconfirmed")
            return SyntheticIdempotencyEvidence(
                status, attempts_remaining=left, mutation_confirmed=True,
            )
    except WatchError:
        return SyntheticIdempotencyEvidence("concurrent_modification_conflict")
    except Exception:
        return SyntheticIdempotencyEvidence("backend_unavailable")
