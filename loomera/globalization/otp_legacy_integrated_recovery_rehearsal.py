"""Phase 7.23: test-only consume/issue composition on the SAME Redis keys.

Only disposable Phase 7.22 fixture records on 127.0.0.1:6414 DB15.
No authentication/session grants and NO production usage.  This narrow
single-writable-master WATCH candidate is not a multihost fencing solution.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import secrets
from typing import Any, Callable

from redis.exceptions import WatchError

from loomera.globalization.otp_legacy_issue_rate_rehearsal import (
    RECORD_TTL, _serialized, validate_synthetic_scope,
)
from loomera.globalization.otp_legacy_state_machine_rehearsal import (
    _confirmed_delete, _confirmed_set, _legacy_record_valid,
)


@dataclass(frozen=True, slots=True)
class SyntheticIntegratedVerifyEvidence:
    status: str
    attempts_remaining: int | None = None
    mutation_confirmed: bool = False
    synthetic_record_consumed: bool = False
    automatic_retry_authorized: bool = False
    real_authentication_allowed: bool = False
    real_session_created: bool = False
    real_otp_issued_or_consumed: bool = False
    production_cutover_authorized: bool = False
    live_races_fixed: bool = False
    multihost_fencing_proven: bool = False
    cross_store_consistency_proven: bool = False


def attempt_synthetic_integrated_verify(
    cache: Any, redis_client: Any, *, fixture_id: str, mobile: str,
    ip_tag: str, now_ts: int, submitted_digest: str,
    on_watched_read: Callable[[], None] | None = None,
) -> SyntheticIntegratedVerifyEvidence:
    """Per-record WATCH state transition on the exact Phase 7.22 issue key.

    Issuer WATCHes record + cooldown + two counters; consumer WATCHes
    the *same physical record key*.  Redis guarantees single-node
    transaction serialization and WATCH conflict on any intervening SET.
    Every return, including "synthetic consumed", denies real login.
    Ambiguous EXEC response is NOT safe for blind automatic retry.
    """
    if os.environ.get("LOOMERA_PHASE723_TEST_REDIS") != "1":
        raise RuntimeError("Phase 7.23 integration is explicitly CI-only")
    record_key, _, _, _ = validate_synthetic_scope(
        cache, redis_client, fixture_id=fixture_id, mobile=mobile,
        ip_tag=ip_tag, now_ts=now_ts, code_digest=submitted_digest,
    )
    if on_watched_read is not None and not callable(on_watched_read):
        raise TypeError("scheduler hook must be callable")
    try:
        with redis_client.pipeline(transaction=True) as pipe:
            pipe.watch(record_key)
            kind = pipe.type(record_key)
            if kind == b"none":
                return SyntheticIntegratedVerifyEvidence("missing")
            if kind != b"string":
                return SyntheticIntegratedVerifyEvidence("wrong_type")
            ttl_ms = pipe.pttl(record_key)
            if type(ttl_ms) is not int or not 0 < ttl_ms <= RECORD_TTL * 1000:
                return SyntheticIntegratedVerifyEvidence("invalid_ttl")
            raw = pipe.get(record_key)
            if type(raw) is not bytes:
                return SyntheticIntegratedVerifyEvidence("invalid_wire")
            try:
                record = cache.client.decode(raw)
            except Exception:
                return SyntheticIntegratedVerifyEvidence("invalid_wire")
            if not _legacy_record_valid(
                record, f"record:app_login:{mobile}", now_ts,
            ):
                return SyntheticIntegratedVerifyEvidence("invalid_record")

            matched = secrets.compare_digest(
                record["code_hash"], submitted_digest,
            )
            if on_watched_read is not None:
                on_watched_read()
            if matched:
                pipe.multi()
                pipe.delete(record_key)
                if not _confirmed_delete(pipe.execute()):
                    return SyntheticIntegratedVerifyEvidence("delete_unconfirmed")
                return SyntheticIntegratedVerifyEvidence(
                    "synthetic_single_winner",
                    mutation_confirmed=True,
                    synthetic_record_consumed=True,
                )

            attempts = record["attempts"] + 1
            if attempts >= record["max_attempts"]:
                pipe.multi()
                pipe.delete(record_key)
                if not _confirmed_delete(pipe.execute()):
                    return SyntheticIntegratedVerifyEvidence("exhaustion_unconfirmed")
                return SyntheticIntegratedVerifyEvidence(
                    "synthetic_exhausted", attempts_remaining=0,
                    mutation_confirmed=True,
                )

            updated = dict(record)
            updated["attempts"] = attempts
            try:
                payload = _serialized(cache, updated)
                if type(payload) is not bytes:
                    return SyntheticIntegratedVerifyEvidence("serialization_unavailable")
            except Exception:
                return SyntheticIntegratedVerifyEvidence("serialization_unavailable")
            pipe.multi()
            pipe.set(record_key, payload, xx=True, keepttl=True)
            if not _confirmed_set(pipe.execute()):
                return SyntheticIntegratedVerifyEvidence("attempt_update_unconfirmed")
            return SyntheticIntegratedVerifyEvidence(
                "synthetic_invalid_attempt",
                attempts_remaining=record["max_attempts"] - attempts,
                mutation_confirmed=True,
            )
    except WatchError:
        return SyntheticIntegratedVerifyEvidence("concurrent_modification_conflict")
    except Exception:
        # A timeout after EXEC can hide an already committed mutation. Never
        # automatically retry this operation or issue a real auth grant.
        return SyntheticIntegratedVerifyEvidence("backend_unavailable")
