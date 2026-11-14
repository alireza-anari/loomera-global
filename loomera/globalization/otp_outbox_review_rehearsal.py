"""Phase 7.30: UNWIRED, CI-only, read-only cross-store incident review.

One bounded SQL observation and two Redis GETs may reveal contradictions but
cannot establish an atomic cross-store snapshot, authorize reconciliation,
prove delivery, or fence a privileged / previously authenticated socket.
No live OTP, account, session, SMS, production client or runtime path.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import os
import re
from typing import Any

from django.db import connection

from loomera.globalization.otp_postgis_writer_authority_rehearsal import (
    LEDGER, LEASE, _check_operation, verify_ci_test_scope,
)
from loomera.globalization.otp_postgis_outbox_rehearsal import OUTBOX
from loomera.globalization.otp_restricted_writer_gateway_rehearsal import (
    DB, PORT, PREFIX,
)

READER_USER = "phase728_legacy"
_ID = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class SyntheticReviewEvidence:
    classification: str
    marker_present: bool = False
    redis_reads_stable: bool = False
    requires_manual_review: bool = True
    auto_replay_allowed: bool = False
    redis_marker_repair_allowed: bool = False
    real_otp_authentication_allowed: bool = False
    real_session_created: bool = False
    external_sms_delivery_proven: bool = False
    all_redis_ingress_fenced: bool = False
    cross_store_atomic_snapshot_proven: bool = False
    production_release_authorized: bool = False


def validate_review_scope(reader: Any, fixture_id: str) -> str:
    """Verify grants, fixture ID and exact read-only principal BEFORE IO."""
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("LOOMERA_PHASE726_TEST_POSTGIS") != "1"
        or os.environ.get("LOOMERA_PHASE728_TEST_REDIS") != "1"
        or os.environ.get("LOOMERA_PHASE729_TEST_OUTBOX") != "1"
        or os.environ.get("LOOMERA_PHASE730_TEST_REVIEW") != "1"
        or not os.environ.get("GITHUB_RUN_ID")
        or not os.environ.get("GITHUB_RUN_ATTEMPT")
    ):
        raise RuntimeError("phase730_all_ci_grants_required")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("phase730_invalid_fixture_id")
    kwargs = getattr(getattr(reader, "connection_pool", None),
                     "connection_kwargs", None)
    if type(kwargs) is not dict or (
        kwargs.get("host") != "127.0.0.1"
        or type(kwargs.get("port")) is not int or kwargs["port"] != PORT
        or type(kwargs.get("db")) is not int or kwargs["db"] != DB
        or kwargs.get("username") != READER_USER
    ):
        raise RuntimeError("phase730_readonly_fixture_client_required")
    return PREFIX + fixture_id + ":"


class SyntheticReadOnlyCrossStoreReviewer:
    """No writes or retries; observation itself is NOT a recovery permit."""

    def __init__(self, reader: Any, fixture_id: str):
        self.reader = reader
        self.fixture_id = fixture_id
        self._scope()

    def _scope(self) -> str:
        prefix = validate_review_scope(self.reader, self.fixture_id)
        verify_ci_test_scope(connection)
        return prefix

    @staticmethod
    def _sql_observation(operation_id: str):
        # ONE PostgreSQL statement supplies a consistent local SQL snapshot.
        # FULL OUTER JOIN also catches orphan ledger and orphan intent.
        # It is NOT consistent with Redis GET before or after this statement.
        with connection.cursor() as cur:
            cur.execute(
                f'SELECT l.fingerprint, l.epoch, l.owner, '
                f'o.fingerprint, o.epoch, o.owner, o.state, '
                f'(SELECT epoch FROM "{LEASE}" WHERE singleton=1), '
                f'(SELECT owner FROM "{LEASE}" WHERE singleton=1), '
                f'(SELECT mode FROM "{LEASE}" WHERE singleton=1) '
                f'FROM "{LEDGER}" l FULL OUTER JOIN "{OUTBOX}" o '
                'ON l.operation_id=o.operation_id '
                'WHERE COALESCE(l.operation_id, o.operation_id)=%s',
                [operation_id],
            )
            return cur.fetchone()

    @staticmethod
    def _classification(row, fingerprint: str, marker) -> str:
        if row is None:
            return "untracked_redis_marker" if marker is not None else "no_intent_or_marker"
        ledger_fp, ledger_epoch, ledger_owner = row[:3]
        intent_fp, intent_epoch, intent_owner, state = row[3:7]
        lease_epoch, lease_owner, lease_mode = row[7:10]
        if ledger_fp is None:
            return "orphan_intent_without_ledger"
        if intent_fp is None:
            return "orphan_ledger_without_intent"
        if not (
            hmac.compare_digest(ledger_fp, fingerprint)
            and hmac.compare_digest(intent_fp, fingerprint)
            and ledger_epoch == intent_epoch
            and ledger_owner == intent_owner
        ):
            return "conflicting_sql_identity"
        if lease_epoch is None:
            return "authority_missing"
        if lease_mode != "active":
            return "authority_halted"
        if (lease_epoch, lease_owner) != (ledger_epoch, ledger_owner):
            return "owner_epoch_stale"
        if state not in {"pending", "inflight", "observed", "quarantined"}:
            return "unknown_sql_state"
        if marker is None:
            return state + "_marker_absent"
        if hmac.compare_digest(marker, fingerprint.encode("ascii")):
            return state + "_marker_matches_untrusted"
        return state + "_foreign_marker"

    def inspect(self, *, operation_id: str, fingerprint: str
                ) -> SyntheticReviewEvidence:
        _check_operation(operation_id, fingerprint)
        key = self._scope() + "operation:" + operation_id
        # Exact-key GET only. No SCAN, key listing, writes, outbox update,
        # recovery, credential change, log of fingerprint, or SMS dispatch.
        before = self.reader.get(key)
        row = self._sql_observation(operation_id)
        after = self.reader.get(key)
        if any(value is not None and type(value) is not bytes
               for value in (before, after)):
            raise RuntimeError("phase730_invalid_redis_reply")
        stable = before == after
        classification = (
            self._classification(row, fingerprint, after)
            if stable else "redis_changed_during_review"
        )
        return SyntheticReviewEvidence(
            classification=classification,
            marker_present=after is not None,
            redis_reads_stable=stable,
        )
