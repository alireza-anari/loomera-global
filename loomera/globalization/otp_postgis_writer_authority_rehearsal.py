"""Phase 7.26: deliberately UNWIRED PostgreSQL OTP write-authority rehearsal.

Only the isolated GitHub PostGIS test DB and two fixed synthetic tables.
This is a cooperating-writer serialization experiment, NOT an authorization
service. Raw Redis clients bypass it, and no Redis/SMS/account side-effect
is committed atomically with its ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re

from django.db import connections, transaction

LEASE = "loomera_phase726_synthetic_lease"
LEDGER = "loomera_phase726_synthetic_operations"
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_OWNERS = frozenset({"old", "promoted"})


@dataclass(frozen=True, slots=True)
class SyntheticAuthorityObservation:
    status: str
    synthetic_database_insert: bool = False
    real_authentication_allowed: bool = False
    real_otp_issued_or_consumed: bool = False
    real_session_created: bool = False
    real_sms_sent: bool = False
    global_redis_writers_fenced: bool = False
    cross_store_atomicity_proven: bool = False
    production_cutover_authorized: bool = False


def verify_ci_test_scope(conn) -> None:
    """Reject production or non-PostGIS databases BEFORE any SQL."""
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("LOOMERA_PHASE726_TEST_POSTGIS") != "1"
        or not os.environ.get("GITHUB_RUN_ID")
        or not os.environ.get("GITHUB_RUN_ATTEMPT")
    ):
        raise RuntimeError("phase726_ci_grant_required")
    settings = conn.settings_dict
    name = settings.get("NAME")
    if (
        conn.vendor != "postgresql"
        or not str(settings.get("ENGINE", "")).endswith(".postgis")
        or type(name) is not str
        or not name.startswith("test_")
        or name == "test_"
    ):
        raise RuntimeError("phase726_isolated_postgis_test_database_required")


def _check_epoch_owner(owner: str, epoch: int) -> None:
    if type(owner) is not str or owner not in _OWNERS:
        raise ValueError("invalid_synthetic_owner")
    if type(epoch) is not int or not 1 <= epoch <= 1000000:
        raise ValueError("invalid_synthetic_epoch")


def _check_operation(operation_id: str, fingerprint: str) -> None:
    if type(operation_id) is not str or _HEX32.fullmatch(operation_id) is None:
        raise ValueError("invalid_synthetic_operation")
    if type(fingerprint) is not str or _HEX64.fullmatch(fingerprint) is None:
        raise ValueError("invalid_synthetic_fingerprint")


class SyntheticPostGISWriterAuthority:
    """A test-only gate; no interface to an actual Redis or auth write."""

    def __init__(self, alias: str = "default"):
        if alias != "default" or type(alias) is not str:
            raise RuntimeError("phase726_default_test_database_only")
        self.alias = alias
        verify_ci_test_scope(connections[alias])

    def _connection(self):
        conn = connections[self.alias]
        verify_ci_test_scope(conn)
        return conn

    def claim(self, *, owner: str, epoch: int, operation_id: str,
              fingerprint: str) -> SyntheticAuthorityObservation:
        _check_epoch_owner(owner, epoch)
        _check_operation(operation_id, fingerprint)
        self._connection()
        # SELECT FOR UPDATE makes the lease check and operation claim
        # serialize with promotion and with other cooperating callers.
        with transaction.atomic(using=self.alias):
            with connections[self.alias].cursor() as cur:
                cur.execute(
                    f'SELECT epoch, owner, mode FROM "{LEASE}" '
                    'WHERE singleton=1 FOR UPDATE'
                )
                state = cur.fetchone()
                if state is None:
                    return SyntheticAuthorityObservation("missing_authority")
                active_epoch, active_owner, mode = state
                if mode != "active":
                    return SyntheticAuthorityObservation("terminal_halt")
                if active_epoch != epoch or active_owner != owner:
                    return SyntheticAuthorityObservation("stale_writer")
                cur.execute(
                    f'INSERT INTO "{LEDGER}" '
                    '(operation_id, fingerprint, epoch, owner) '
                    'VALUES (%s, %s, %s, %s) '
                    'ON CONFLICT (operation_id) DO NOTHING '
                    'RETURNING operation_id',
                    [operation_id, fingerprint, epoch, owner],
                )
                if cur.fetchone() is not None:
                    return SyntheticAuthorityObservation(
                        "synthetic_committed", synthetic_database_insert=True
                    )
                cur.execute(
                    f'SELECT fingerprint, epoch, owner FROM "{LEDGER}" '
                    'WHERE operation_id=%s',
                    [operation_id],
                )
                existing = cur.fetchone()
                if existing == (fingerprint, epoch, owner):
                    return SyntheticAuthorityObservation("same_operation_observed")
                return SyntheticAuthorityObservation("global_operation_conflict")

    def promote(self, *, expected_owner: str, expected_epoch: int,
                new_owner: str) -> SyntheticAuthorityObservation:
        _check_epoch_owner(expected_owner, expected_epoch)
        _check_epoch_owner(new_owner, expected_epoch)
        # Explicit one-way exercise; no implicit recovery or reverse failover.
        if not (expected_owner == "old" and expected_epoch == 1
                and new_owner == "promoted"):
            return SyntheticAuthorityObservation("unapproved_promotion")
        self._connection()
        with transaction.atomic(using=self.alias):
            with connections[self.alias].cursor() as cur:
                cur.execute(
                    f'UPDATE "{LEASE}" SET epoch=epoch+1, owner=%s '
                    'WHERE singleton=1 AND epoch=%s AND owner=%s '
                    'AND mode=%s RETURNING epoch',
                    [new_owner, expected_epoch, expected_owner, "active"],
                )
                return SyntheticAuthorityObservation(
                    "synthetic_promoted" if cur.fetchone() == (2,)
                    else "promotion_stale_or_halted"
                )

    def halt(self, *, owner: str, epoch: int) -> SyntheticAuthorityObservation:
        _check_epoch_owner(owner, epoch)
        self._connection()
        with transaction.atomic(using=self.alias):
            with connections[self.alias].cursor() as cur:
                cur.execute(
                    f'UPDATE "{LEASE}" SET mode=%s '
                    'WHERE singleton=1 AND epoch=%s AND owner=%s '
                    'AND mode=%s RETURNING epoch',
                    ["halted", epoch, owner, "active"],
                )
                return SyntheticAuthorityObservation(
                    "synthetic_halted" if cur.fetchone() == (epoch,)
                    else "halt_stale_or_terminal"
                )
