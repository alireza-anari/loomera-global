"""Phase 7.25 CI-only Redis split-brain OTP operation ledger adversarial drill.

This is a separately scoped two-node reenactment of Phase 7.24's exact
Django-Redis 5.4 legacy STRING CAS primitive, reusing its wire/ledger/reply
helpers.  Does NOT import or alter live OTP/auth/session code.  It exists to
prove why a single-master idempotency ledger cannot confer globally unique
operation execution when a disconnected Redis primary remains writable.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import secrets
from typing import Any

from redis.exceptions import WatchError

from loomera.globalization.otp_legacy_issue_rate_rehearsal import (
    MOBILE_LIMIT, IP_LIMIT, RECORD_TTL, RESEND_TTL, RATE_TTL,
    _read_present, _serialized,
)
from loomera.globalization.otp_legacy_idempotency_rehearsal import (
    LEDGER_TTL, SyntheticIdempotencyEvidence, _read_ledger,
    _ledger_payload, _confirmed,
)
from loomera.globalization.otp_legacy_state_machine_rehearsal import (
    _legacy_record_valid,
)

PREFIX = "loomera:phase725:synthetic-two-master-only:"
OLD_URL = "redis://127.0.0.1:6415/15"
PROMOTED_URL = "redis://127.0.0.1:6416/15"
_ALLOWED_MOBILES = frozenset({"09123456789", "09123456780", "09123456781"})
_ID = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class SyntheticSplitBrainEvidence:
    status: str
    two_local_master_claims: bool = False
    divergent_ledgers_observed: bool = False
    old_primary_raw_bypass_observed: bool = False
    globally_unique_execution_proven: bool = False
    global_fencing_proven: bool = False
    globally_durable_idempotency_proven: bool = False
    safe_production_replay: bool = False
    real_authentication_allowed: bool = False
    real_session_created: bool = False
    production_cutover_authorized: bool = False


def validate_two_master_scope(
    cache: Any, client: Any, *, fixture_id: str, mobile: str,
    digest: str, operation_id: str, kind: str,
    now_ts: int, ip_tag: str = "synthetic_ip_01",
) -> tuple[str, str, str, str, str, str]:
    """Fail *before* network IO if not one of the exact two fixture servers."""
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("LOOMERA_PHASE725_TEST_REDIS") != "1"
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")):
        raise RuntimeError("Phase 7.25 requires isolated GitHub CI grant")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("invalid random disposable fixture")
    if type(mobile) is not str or mobile not in _ALLOWED_MOBILES:
        raise ValueError("only three fixed synthetic mobiles allowed")
    if type(ip_tag) is not str or ip_tag != "synthetic_ip_01":
        raise ValueError("real client IPs forbidden")
    if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
        raise ValueError("only fixed-format fake digests permitted")
    if type(operation_id) is not str or _ID.fullmatch(operation_id) is None:
        raise ValueError("invalid synthetic operation id")
    if type(kind) is not str or kind not in ("issue", "verify"):
        raise ValueError("invalid synthetic operation kind")
    if type(now_ts) is not int or now_ts < 0:
        raise ValueError("invalid synthetic clock")
    expected_prefix = PREFIX + fixture_id
    url = getattr(cache, "_server", None)
    if (url not in (OLD_URL, PROMOTED_URL)
            or getattr(cache, "key_prefix", None) != expected_prefix
            or type(getattr(cache, "version", None)) is not int
            or getattr(cache, "version", None) != 1):
        raise RuntimeError("unexpected legacy cache backend or prefix")
    expected_port = 6415 if url == OLD_URL else 6416
    try:
        kwargs = client.connection_pool.connection_kwargs
        host, port, db = kwargs.get("host"), kwargs.get("port"), kwargs.get("db")
        decode = kwargs.get("decode_responses", False)
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis client") from exc
    if (host != "127.0.0.1" or type(port) is not int or port != expected_port
            or type(db) is not int or db != 15 or decode is not False):
        raise RuntimeError("client must use exact 6415 or 6416 fixture DB15")
    hour = now_ts // 3600
    logical = (
        "operation:synthetic:" + operation_id,
        f"record:app_login:{mobile}",
        f"resend:app_login:{mobile}",
        f"rate:mobile:app_login_{mobile}:{hour}",
        f"rate:ip:{ip_tag}:{hour}",
    )
    physical = tuple(str(cache.make_key(k)) for k in logical)
    expected = tuple(f"{expected_prefix}:1:{k}" for k in logical)
    if physical != expected or len(set(physical)) != 5:
        raise RuntimeError("invalid physical Django-Redis key mapping")
    # MUST match Phase 7.24 exactly. A replica lacks a ledger entry even if
    # the same globally supplied operation ID was committed to old primary.
    fp = hashlib.sha256(
        ("phase724|v1|" + kind + "|" + mobile + "|" + ip_tag + "|" + digest)
        .encode("ascii"),
    ).hexdigest()
    return (*physical, fp)


def issue_on_synthetic_master(
    cache: Any, client: Any, *, fixture_id: str, mobile: str,
    digest: str, operation_id: str, now_ts: int = 1050,
) -> SyntheticIdempotencyEvidence:
    """Same five-key WATCH/MULTI/EXEC and legacy Django-Redis bytes as 7.24."""
    ledger, rec, cool, mob_rate, ip_rate, fingerprint = validate_two_master_scope(
        cache, client, fixture_id=fixture_id, mobile=mobile,
        digest=digest, operation_id=operation_id,
        kind="issue", now_ts=now_ts,
    )
    try:
        with client.pipeline(transaction=True) as pipe:
            pipe.watch(ledger, rec, cool, mob_rate, ip_rate)
            prior = _read_ledger(pipe, cache, ledger, fingerprint)
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
                pipe, cache, mob_rate, max_ttl_ms=RATE_TTL * 1000,
            )
            i_state, ip = _read_present(
                pipe, cache, ip_rate, max_ttl_ms=RATE_TTL * 1000,
            )
            if m_state == "invalid" or i_state == "invalid":
                return SyntheticIdempotencyEvidence("invalid_rate_state")
            if m_state == "missing":
                m = 0
            if i_state == "missing":
                ip = 0
            if (type(m) is not int or type(ip) is not int
                    or not 0 <= m <= MOBILE_LIMIT
                    or not 0 <= ip <= IP_LIMIT):
                return SyntheticIdempotencyEvidence("invalid_rate_state")
            if m >= MOBILE_LIMIT:
                return SyntheticIdempotencyEvidence("mobile_rate_limited")
            if ip >= IP_LIMIT:
                return SyntheticIdempotencyEvidence("ip_rate_limited")
            record = {
                "purpose": "app_login", "mobile_number": mobile,
                "code_hash": digest, "created_at": now_ts,
                "expires_at": now_ts + RECORD_TTL,
                "attempts": 0, "max_attempts": 5, "verified": False,
                "delivery": {
                    "channel": "sms", "mode": "simulated",
                    "sent": False, "provider": "none",
                },
            }
            try:
                payload = (
                    _serialized(cache, record),
                    _serialized(cache, now_ts),
                    _serialized(cache, m + 1),
                    _serialized(cache, ip + 1),
                    _ledger_payload(
                        cache, fingerprint, status="synthetic_issued",
                        mobile_left=MOBILE_LIMIT - m - 1,
                        ip_left=IP_LIMIT - ip - 1,
                    ),
                )
            except Exception:
                return SyntheticIdempotencyEvidence("serialization_unavailable")
            pipe.multi()
            pipe.set(rec, payload[0], ex=RECORD_TTL)
            pipe.set(cool, payload[1], ex=RESEND_TTL)
            if m_state == "missing":
                pipe.set(mob_rate, payload[2], ex=RATE_TTL)
            else:
                pipe.set(mob_rate, payload[2], xx=True, keepttl=True)
            if i_state == "missing":
                pipe.set(ip_rate, payload[3], ex=RATE_TTL)
            else:
                pipe.set(ip_rate, payload[3], xx=True, keepttl=True)
            pipe.set(ledger, payload[4], ex=LEDGER_TTL)
            if not _confirmed(pipe.execute(), count=5):
                return SyntheticIdempotencyEvidence("issue_unconfirmed")
            return SyntheticIdempotencyEvidence(
                "synthetic_issued", mutation_confirmed=True,
                mobile_requests_remaining=MOBILE_LIMIT - m - 1,
                ip_requests_remaining=IP_LIMIT - ip - 1,
            )
    except WatchError:
        return SyntheticIdempotencyEvidence("concurrent_modification_conflict")
    except Exception:
        return SyntheticIdempotencyEvidence("backend_unavailable")


def verify_on_synthetic_master(
    cache: Any, client: Any, *, fixture_id: str, mobile: str,
    digest: str, operation_id: str, now_ts: int = 1050,
) -> SyntheticIdempotencyEvidence:
    """Same 2-key legacy CAS and idempotency semantics as 7.24, per master."""
    ledger, rec, _, _, _, fingerprint = validate_two_master_scope(
        cache, client, fixture_id=fixture_id, mobile=mobile,
        digest=digest, operation_id=operation_id,
        kind="verify", now_ts=now_ts,
    )
    try:
        with client.pipeline(transaction=True) as pipe:
            pipe.watch(ledger, rec)
            prior = _read_ledger(pipe, cache, ledger, fingerprint)
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
            match = secrets.compare_digest(record["code_hash"], digest)
            next_attempts = record["attempts"] + 1
            if match:
                status, remaining, delete = "synthetic_single_winner", None, True
            elif next_attempts >= record["max_attempts"]:
                status, remaining, delete = "synthetic_exhausted", 0, True
            else:
                status, remaining, delete = (
                    "synthetic_invalid_attempt",
                    record["max_attempts"] - next_attempts,
                    False,
                )
            try:
                entry = _ledger_payload(
                    cache, fingerprint, status=status, remaining=remaining,
                )
                if not delete:
                    updated = dict(record)
                    updated["attempts"] = next_attempts
                    updated_raw = _serialized(cache, updated)
                    if type(updated_raw) is not bytes:
                        return SyntheticIdempotencyEvidence("serialization_unavailable")
            except Exception:
                return SyntheticIdempotencyEvidence("serialization_unavailable")
            pipe.multi()
            if delete:
                pipe.delete(rec)
            else:
                pipe.set(rec, updated_raw, xx=True, keepttl=True)
            pipe.set(ledger, entry, ex=LEDGER_TTL)
            if not _confirmed(pipe.execute(), count=2, delete_first=delete):
                return SyntheticIdempotencyEvidence("verify_unconfirmed")
            return SyntheticIdempotencyEvidence(
                status, attempts_remaining=remaining, mutation_confirmed=True,
            )
    except WatchError:
        return SyntheticIdempotencyEvidence("concurrent_modification_conflict")
    except Exception:
        return SyntheticIdempotencyEvidence("backend_unavailable")


def summarize_split_brain(
    *, old_master_role: str, promoted_role: str,
    old_issue_ledger: bytes | None, new_issue_ledger: bytes | None,
    old_challenge: bytes | None, new_challenge: bytes | None,
    old_bypass_write_confirmed: bool,
) -> SyntheticSplitBrainEvidence:
    """Observer-only release blocker. No claim of enforcing authority."""
    for role in (old_master_role, promoted_role):
        if type(role) is not str:
            raise ValueError("invalid redis role")
    if (old_master_role == "master" and promoted_role == "master"
            and type(old_issue_ledger) is bytes
            and type(new_issue_ledger) is bytes
            and old_issue_ledger != new_issue_ledger
            and type(old_challenge) is bytes
            and type(new_challenge) is bytes
            and old_challenge != new_challenge):
        return SyntheticSplitBrainEvidence(
            "two_masters_divergent_same_operation",
            two_local_master_claims=True,
            divergent_ledgers_observed=True,
            old_primary_raw_bypass_observed=old_bypass_write_confirmed,
        )
    return SyntheticSplitBrainEvidence("insufficient_single_node_authority")
