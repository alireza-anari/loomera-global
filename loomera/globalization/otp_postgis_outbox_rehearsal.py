"""Phase 7.29: UNWIRED synthetic PostgreSQL outbox / Redis marker exercise.

The committed intent precedes any Redis side effect. A durable 'inflight'
barrier is committed BEFORE Redis SET NX. Ambiguous results are never retried.
This is neither a real outbox dispatcher nor a production authentication path.
"""
from __future__ import annotations

from dataclasses import dataclass
import os

from django.db import connection, transaction

from loomera.globalization.otp_postgis_writer_authority_rehearsal import (
    LEASE, SyntheticPostGISWriterAuthority, _check_epoch_owner,
    _check_operation, verify_ci_test_scope,
)
from loomera.globalization.otp_restricted_writer_gateway_rehearsal import (
    validate_gateway_scope,
)

OUTBOX = "loomera_phase729_synthetic_outbox"


@dataclass(frozen=True, slots=True)
class SyntheticOutboxObservation:
    status: str
    synthetic_redis_marker_written: bool = False
    real_authentication_allowed: bool = False
    real_otp_issue_or_consume_allowed: bool = False
    real_session_created: bool = False
    real_sms_sent: bool = False
    cross_store_atomicity_proven: bool = False
    all_redis_ingress_fenced: bool = False
    production_release_authorized: bool = False


class SyntheticPostGISOutboxRehearsal:
    """Only a cooperating disposable CI fixture; never import from live auth."""

    def __init__(self, client, fixture_id: str):
        self.client = client
        self.fixture_id = fixture_id
        self._scope()
        self.authority = SyntheticPostGISWriterAuthority()

    def _scope(self) -> str:
        if os.environ.get("LOOMERA_PHASE729_TEST_OUTBOX") != "1":
            raise RuntimeError("phase729_explicit_ci_grant_required")
        prefix = validate_gateway_scope(self.client, self.fixture_id)
        verify_ci_test_scope(connection)
        return prefix

    @staticmethod
    def _validate(owner: str, epoch: int, operation_id: str,
                  fingerprint: str) -> None:
        _check_epoch_owner(owner, epoch)
        _check_operation(operation_id, fingerprint)

    @staticmethod
    def _locked_status(cur, owner: str, epoch: int, operation_id: str,
                       fingerprint: str) -> str:
        # Lock the lease first, in the same ordering as phase 7.26 promotion.
        cur.execute(
            f'SELECT epoch, owner, mode FROM "{LEASE}" '
            'WHERE singleton=1 FOR UPDATE'
        )
        lease = cur.fetchone()
        if lease is None:
            return "missing_authority"
        if lease[2] != "active":
            return "terminal_halt"
        if lease[:2] != (epoch, owner):
            return "stale_writer"
        cur.execute(
            f'SELECT fingerprint, epoch, owner, state FROM "{OUTBOX}" '
            'WHERE operation_id=%s FOR UPDATE', [operation_id],
        )
        row = cur.fetchone()
        if row is None:
            return "missing_committed_intent"
        if row[:3] != (fingerprint, epoch, owner):
            return "intent_fingerprint_conflict"
        return row[3]

    def enqueue(self, *, owner: str, epoch: int, operation_id: str,
                fingerprint: str) -> SyntheticOutboxObservation:
        self._validate(owner, epoch, operation_id, fingerprint)
        self._scope()
        # Both ledger and intent commit together; no network call here.
        with transaction.atomic(using="default"):
            claim = self.authority.claim(
                owner=owner, epoch=epoch, operation_id=operation_id,
                fingerprint=fingerprint,
            )
            if claim.status != "synthetic_committed":
                return SyntheticOutboxObservation(claim.status)
            with connection.cursor() as cur:
                cur.execute(
                    f'INSERT INTO "{OUTBOX}" '
                    '(operation_id, fingerprint, epoch, owner, state) '
                    'VALUES (%s, %s, %s, %s, %s)',
                    [operation_id, fingerprint, epoch, owner, "pending"],
                )
        return SyntheticOutboxObservation("synthetic_intent_committed")

    def dispatch_once(self, *, owner: str, epoch: int, operation_id: str,
                      fingerprint: str) -> SyntheticOutboxObservation:
        self._validate(owner, epoch, operation_id, fingerprint)
        key = self._scope() + "operation:" + operation_id
        # Commit one-way 'inflight' BEFORE crossing the SQL/Redis boundary.
        # A crash after this point leaves an un-retryable intent for review.
        with transaction.atomic(using="default"):
            with connection.cursor() as cur:
                state = self._locked_status(
                    cur, owner, epoch, operation_id, fingerprint,
                )
                if state != "pending":
                    return SyntheticOutboxObservation(self._refusal(state))
                cur.execute(
                    f'UPDATE "{OUTBOX}" SET state=%s '
                    'WHERE operation_id=%s AND state=%s',
                    ["inflight", operation_id, "pending"],
                )
                if cur.rowcount != 1:
                    raise RuntimeError("phase729_arm_cas_failed")
        # Promotion is serialized against the second lease lock and Redis SET.
        # No blind recovery from Redis failures or database commit ambiguity.
        with transaction.atomic(using="default"):
            with connection.cursor() as cur:
                state = self._locked_status(
                    cur, owner, epoch, operation_id, fingerprint,
                )
                if state != "inflight":
                    return SyntheticOutboxObservation(self._refusal(state))
                acknowledged = self.client.set(key, fingerprint, nx=True)
                final_state = "observed" if acknowledged is True else "quarantined"
                cur.execute(
                    f'UPDATE "{OUTBOX}" SET state=%s '
                    'WHERE operation_id=%s AND state=%s',
                    [final_state, operation_id, "inflight"],
                )
                if cur.rowcount != 1:
                    raise RuntimeError("phase729_complete_cas_failed")
        if final_state == "observed":
            return SyntheticOutboxObservation(
                "synthetic_marker_observed", synthetic_redis_marker_written=True,
            )
        return SyntheticOutboxObservation("marker_collision_quarantined")

    @staticmethod
    def _refusal(state: str) -> str:
        return {
            "inflight": "inflight_requires_manual_review",
            "observed": "already_observed_no_retry",
            "quarantined": "quarantined_no_retry",
            "pending": "pending",
        }.get(state, state)

    def inspect_read_only(self, *, operation_id: str, fingerprint: str
                          ) -> SyntheticOutboxObservation:
        # Inspection is evidence only. Never writes, retries, repairs or logs
        # a real OTP. A matching Redis byte string is not a delivery receipt.
        _check_operation(operation_id, fingerprint)
        key = self._scope() + "operation:" + operation_id
        with connection.cursor() as cur:
            cur.execute(
                f'SELECT fingerprint, state FROM "{OUTBOX}" '
                'WHERE operation_id=%s', [operation_id],
            )
            row = cur.fetchone()
        if row is None:
            return SyntheticOutboxObservation("intent_missing_no_repair")
        if row[0] != fingerprint:
            return SyntheticOutboxObservation("intent_fingerprint_conflict")
        marker = self.client.get(key)
        if marker is not None and marker != fingerprint.encode("ascii"):
            return SyntheticOutboxObservation("foreign_marker_no_repair")
        if marker is None:
            return SyntheticOutboxObservation(row[1] + "_marker_absent_no_repair")
        return SyntheticOutboxObservation(row[1] + "_marker_matches_no_receipt")
