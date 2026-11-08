"""Phase 7.26 real PostgreSQL lease + global synthetic operation-ID UNIQUE races.

Only fixed tables in Django's disposable isolated PostGIS CI test database.
This does not fence arbitrary Redis writers or execute live OTP/SMS/session IO.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import (
    DatabaseError, close_old_connections, connection, connections, transaction,
)
from django.test import TransactionTestCase

from loomera.globalization.otp_postgis_writer_authority_rehearsal import (
    LEASE, LEDGER, SyntheticPostGISWriterAuthority,
    verify_ci_test_scope,
)


class SyntheticRollback(Exception):
    pass


class Phase726PostGISSingleWriterTest(TransactionTestCase):
    databases = {"default"}

    def setUp(self):
        super().setUp()
        verify_ci_test_scope(connection)
        with connection.cursor() as cur:
            cur.execute("SELECT current_database(), PostGIS_Version()")
            database, version = cur.fetchone()
            self.assertTrue(database.startswith("test_"))
            self.assertTrue(version)
            cur.execute(f'DROP TABLE IF EXISTS "{LEDGER}"')
            cur.execute(f'DROP TABLE IF EXISTS "{LEASE}"')
            cur.execute(
                f'CREATE TABLE "{LEASE}" ('
                'singleton INTEGER PRIMARY KEY CHECK (singleton=1), '
                'epoch INTEGER NOT NULL CHECK (epoch BETWEEN 1 AND 1000000), '
                "owner VARCHAR(12) NOT NULL CHECK (owner IN ('old', 'promoted')), "
                "mode VARCHAR(12) NOT NULL CHECK (mode IN ('active', 'halted')))"
            )
            cur.execute(
                f'CREATE TABLE "{LEDGER}" ('
                'operation_id CHAR(32) PRIMARY KEY, '
                'fingerprint CHAR(64) NOT NULL, '
                'epoch INTEGER NOT NULL, '
                'owner VARCHAR(12) NOT NULL)'
            )
            cur.execute(
                f'INSERT INTO "{LEASE}" (singleton, epoch, owner, mode) '
                "VALUES (1, 1, 'old', 'active')"
            )
        self.gate = SyntheticPostGISWriterAuthority()

    def tearDown(self):
        try:
            with connection.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{LEDGER}"')
                cur.execute(f'DROP TABLE IF EXISTS "{LEASE}"')
        finally:
            super().tearDown()

    @staticmethod
    def ledger():
        with connections["default"].cursor() as cur:
            cur.execute(f'SELECT operation_id, fingerprint, epoch, owner '
                        f'FROM "{LEDGER}" ORDER BY operation_id')
            return tuple(cur.fetchall())

    @staticmethod
    def lease():
        with connections["default"].cursor() as cur:
            cur.execute(f'SELECT epoch, owner, mode FROM "{LEASE}" WHERE singleton=1')
            return cur.fetchone()

    def claim(self, *, op="a" * 32, digest="b" * 64, owner="old", epoch=1):
        return self.gate.claim(
            owner=owner, epoch=epoch,
            operation_id=op, fingerprint=digest,
        )

    @staticmethod
    def worker(barrier, op, digest, owner="old", epoch=1):
        close_old_connections()
        try:
            with connections["default"].cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                pid = cur.fetchone()[0]
            barrier.wait(timeout=20)
            result = SyntheticPostGISWriterAuthority().claim(
                owner=owner, epoch=epoch, operation_id=op, fingerprint=digest
            )
            return pid, result.status
        finally:
            connections["default"].close()

    def test_real_postgis_unique_index_and_synthetic_only_tables(self):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE schemaname='public' "
                "AND tablename=%s", [LEDGER]
            )
            idx = [row[0].upper() for row in cur.fetchall()]
        self.assertTrue(any("UNIQUE INDEX" in s and "OPERATION_ID" in s for s in idx))
        self.assertEqual(self.lease(), (1, "old", "active"))
        self.assertEqual(self.ledger(), ())

    def test_single_claim_and_identical_retry_are_not_double_insert(self):
        first = self.claim()
        self.assertEqual(first.status, "synthetic_committed")
        self.assertTrue(first.synthetic_database_insert)
        self.assertEqual(self.claim().status, "same_operation_observed")
        self.assertEqual(len(self.ledger()), 1)
        self.assertFalse(first.real_authentication_allowed)
        self.assertFalse(first.cross_store_atomicity_proven)

    def test_same_operation_with_different_payload_denied(self):
        self.assertEqual(self.claim().status, "synthetic_committed")
        self.assertEqual(self.claim(digest="c" * 64).status,
                         "global_operation_conflict")
        self.assertEqual(self.ledger()[0][1], "b" * 64)

    def test_two_real_connections_race_with_same_id_and_different_digests(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(self.worker, barrier, "a" * 32, "b" * 64)
            f2 = pool.submit(self.worker, barrier, "a" * 32, "c" * 64)
            pid1, status1 = f1.result(timeout=30)
            pid2, status2 = f2.result(timeout=30)
        self.assertNotEqual(pid1, pid2)
        self.assertEqual(
            sorted((status1, status2)),
            ["global_operation_conflict", "synthetic_committed"],
        )
        self.assertEqual(len(self.ledger()), 1)

    def test_two_real_connections_same_payload_one_insert_one_observation(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.worker, barrier, "d" * 32, "e" * 64)
                for _ in range(2)
            ]
            outcomes = [f.result(timeout=30)[1] for f in futures]
        self.assertEqual(sorted(outcomes),
                         ["same_operation_observed", "synthetic_committed"])
        self.assertEqual(len(self.ledger()), 1)

    def test_promotion_fences_cooperating_old_writer_but_not_raw_redis(self):
        self.assertEqual(self.gate.promote(
            expected_owner="old", expected_epoch=1, new_owner="promoted"
        ).status, "synthetic_promoted")
        self.assertEqual(self.lease(), (2, "promoted", "active"))
        self.assertEqual(self.claim().status, "stale_writer")
        self.assertEqual(self.claim(owner="promoted", epoch=2).status,
                         "synthetic_committed")
        self.assertEqual(len(self.ledger()), 1)

    def test_global_id_conflict_survives_epoch_rotation(self):
        self.assertEqual(self.claim().status, "synthetic_committed")
        self.gate.promote(expected_owner="old", expected_epoch=1,
                          new_owner="promoted")
        self.assertEqual(
            self.claim(owner="promoted", epoch=2).status,
            "global_operation_conflict",
        )
        self.assertEqual(
            self.claim(op="f" * 32, owner="promoted", epoch=2).status,
            "synthetic_committed",
        )
        self.assertEqual(len(self.ledger()), 2)

    def test_competing_promotions_are_one_way(self):
        barrier = Barrier(2)

        def promote_worker():
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                return SyntheticPostGISWriterAuthority().promote(
                    expected_owner="old", expected_epoch=1,
                    new_owner="promoted"
                ).status
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(promote_worker) for _ in range(2)]
            statuses = [f.result(timeout=30) for f in futures]
        self.assertEqual(sorted(statuses),
                         ["promotion_stale_or_halted", "synthetic_promoted"])
        self.assertEqual(self.lease(), (2, "promoted", "active"))

    def test_stale_or_reverse_promotion_never_changes_lease(self):
        self.assertEqual(self.gate.promote(
            expected_owner="promoted", expected_epoch=2, new_owner="old"
        ).status, "unapproved_promotion")
        self.assertEqual(self.gate.promote(
            expected_owner="old", expected_epoch=2, new_owner="promoted"
        ).status, "unapproved_promotion")
        self.assertEqual(self.lease(), (1, "old", "active"))

    def test_halt_is_terminal_even_for_promoted_writer(self):
        self.gate.promote(expected_owner="old", expected_epoch=1,
                          new_owner="promoted")
        self.assertEqual(self.gate.halt(owner="promoted", epoch=2).status,
                         "synthetic_halted")
        self.assertEqual(self.claim(owner="promoted", epoch=2).status,
                         "terminal_halt")
        self.assertEqual(self.gate.halt(owner="promoted", epoch=2).status,
                         "halt_stale_or_terminal")
        self.assertEqual(self.lease(), (2, "promoted", "halted"))

    def test_atomic_rollback_reverts_ledger_claim(self):
        with self.assertRaises(SyntheticRollback):
            with transaction.atomic():
                self.assertEqual(self.claim().status, "synthetic_committed")
                raise SyntheticRollback()
        self.assertEqual(self.ledger(), ())
        self.assertEqual(self.claim().status, "synthetic_committed")

    def test_missing_authority_does_not_auto_seed(self):
        with connection.cursor() as cur:
            cur.execute(f'DELETE FROM "{LEASE}"')
        self.assertEqual(self.claim().status, "missing_authority")
        self.assertEqual(self.ledger(), ())

    def test_missing_ledger_relation_fails_closed_without_fallback(self):
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE "{LEDGER}"')
        with self.assertRaises(DatabaseError):
            self.claim()
        self.assertEqual(self.lease(), (1, "old", "active"))
