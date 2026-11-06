"""Phase 7.4 — actual PostgreSQL UNIQUE/CAS behavior on an EPHEMERAL test table.

ONLY execute using Django's isolated PostGIS CI *test database*.
No user model/table, migrations, real accounts, OTP, or deployment touched.
The SQL is test-only and is deliberately not imported by application code.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import FieldDoesNotExist
from django.db import (
    DatabaseError, IntegrityError, close_old_connections, connection,
    connections, transaction,
)
from django.test import TransactionTestCase

from apps.accounts.models import CustomUser


# Literal name controlled by test source: never accept a dynamic user table name.
TABLE = "loomera_phase74_synthetic_phone_shadow"
SOURCE_FIXTURES = (
    (101, "09123456789", True),
    (102, "09123456780", False),
    (103, "09123456781", True),
)


class InjectedRollback(Exception):
    """Synthetic transactional failure; never a customer-facing error."""


class Phase74PostGISPhoneShadowRehearsal(TransactionTestCase):
    """Exercise PostgreSQL, not the RLock simulator of Phase 7.3."""

    databases = {"default"}

    def setUp(self):
        super().setUp()
        if not connection.settings_dict["ENGINE"].endswith(".postgis"):
            self.fail("Phase 7.4 requires an isolated PostGIS test database")
        # The Django test runner provisions an isolated database. This is a
        # NEW test-owned table, not an ALTER of accounts_customuser.
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
            cursor.execute(f'''
                CREATE TABLE "{TABLE}" (
                    account_id BIGINT PRIMARY KEY,
                    mobile_number VARCHAR(11) NOT NULL UNIQUE,
                    is_active BOOLEAN NOT NULL,
                    canonical_mobile_e164 VARCHAR(16) NULL UNIQUE,
                    phone_identity_revision INTEGER NOT NULL DEFAULT 0,
                    CONSTRAINT phase74_nonnegative_revision
                        CHECK (phone_identity_revision >= 0),
                    CONSTRAINT phase74_e164_syntax
                        CHECK (
                            canonical_mobile_e164 IS NULL
                            OR (
                                char_length(canonical_mobile_e164) BETWEEN 9 AND 16
                                AND left(canonical_mobile_e164, 1) = '+'
                                AND substring(canonical_mobile_e164, 2, 1)
                                    BETWEEN '1' AND '9'
                                AND translate(
                                    substring(canonical_mobile_e164 FROM 2),
                                    '0123456789', ''
                                ) = ''
                            )
                        )
                )
            ''')
            cursor.executemany(
                f'''
                INSERT INTO "{TABLE}"
                    (account_id, mobile_number, is_active)
                VALUES (%s, %s, %s)
                ''',
                SOURCE_FIXTURES,
            )

    def tearDown(self):
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
        finally:
            super().tearDown()

    @staticmethod
    def _snapshot():
        """Test-local tuples; NEVER log raw values or return in a public report."""
        with connections["default"].cursor() as cursor:
            cursor.execute(f'''
                SELECT account_id, mobile_number, is_active,
                       canonical_mobile_e164, phone_identity_revision
                  FROM "{TABLE}"
                 ORDER BY account_id
            ''')
            return tuple(cursor.fetchall())

    @staticmethod
    def _claim(
        account_id, candidate, *, legacy, active, version=0,
    ):
        """Test-only SQL CAS with implicit PostgreSQL row lock + UNIQUE index.

        A future application implementation must additionally validate the
        candidate maps to the source and the operator-approved account state.
        SQL here deliberately tests uniqueness *even for conflicting targets*.
        """
        try:
            with transaction.atomic(using="default"):
                with connections["default"].cursor() as cursor:
                    cursor.execute(f'''
                        UPDATE "{TABLE}"
                           SET canonical_mobile_e164 = %s,
                               phone_identity_revision = phone_identity_revision + 1
                         WHERE account_id = %s
                           AND mobile_number = %s
                           AND is_active = %s
                           AND phone_identity_revision = %s
                           AND canonical_mobile_e164 IS NULL
                     RETURNING phone_identity_revision
                    ''', [candidate, account_id, legacy, active, version])
                    updated = cursor.fetchone()
            return "applied" if updated is not None else "stale_or_mismatched"
        except IntegrityError:
            # PostgreSQL rolls back the *whole* atomic block, not a
            # half-written row. Do not retry/reassign another account.
            return "unique_or_check_conflict"

    @staticmethod
    def _rollback(
        account_id, *, legacy, active, version,
    ):
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cursor:
                cursor.execute(f'''
                    UPDATE "{TABLE}"
                       SET canonical_mobile_e164 = NULL,
                           phone_identity_revision = phone_identity_revision + 1
                     WHERE account_id = %s
                       AND mobile_number = %s
                       AND is_active = %s
                       AND phone_identity_revision = %s
                       AND canonical_mobile_e164 IS NOT NULL
                 RETURNING phone_identity_revision
                ''', [account_id, legacy, active, version])
                return "applied" if cursor.fetchone() is not None else "stale_or_mismatched"

    @staticmethod
    def _thread_claim(barrier, *, account_id, candidate, legacy, active, version=0):
        # Django uses thread-local DB connections. Confirm these are two
        # independent PostgreSQL sessions, not merely threads with one RLock.
        close_old_connections()
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                backend = cursor.fetchone()[0]
            barrier.wait(timeout=20)
            result = Phase74PostGISPhoneShadowRehearsal._claim(
                account_id, candidate, legacy=legacy, active=active,
                version=version,
            )
            return backend, result
        finally:
            connections["default"].close()

    def test_backend_real_postgis_and_table_not_customuser(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT PostGIS_Version()")
            self.assertTrue(cursor.fetchone()[0])
            cursor.execute("SELECT current_database()")
            self.assertTrue(cursor.fetchone()[0].startswith("test_"))
            cursor.execute(
                "SELECT to_regclass(%s)", [f"public.{TABLE}"]
            )
            self.assertIsNotNone(cursor.fetchone()[0])
            cursor.execute(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename=%s",
                [TABLE],
            )
            definitions = [row[0].upper() for row in cursor.fetchall()]
        self.assertTrue(any(
            "UNIQUE INDEX" in d and "(CANONICAL_MOBILE_E164)" in d
            and "WHERE" not in d for d in definitions
        ))
        with self.assertRaises(FieldDoesNotExist):
            CustomUser._meta.get_field("canonical_mobile_e164")
        self.assertEqual(len(self._snapshot()), 3)

    def test_multiple_null_claims_allowed_and_inactive_unique_scope(self):
        before = self._snapshot()
        self.assertEqual(sum(row[3] is None for row in before), 3)
        self.assertEqual(
            self._claim(102, "+989123456780", legacy="09123456780", active=False),
            "applied",
        )
        self.assertEqual(
            self._claim(101, "+989123456780", legacy="09123456789", active=True),
            "unique_or_check_conflict",
        )
        after = self._snapshot()
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[1][3], "+989123456780")
        self.assertEqual(after[1][4], 1)
        self.assertFalse(after[1][2])

    def test_database_e164_syntax_contract_accepts_valid_ir_and_foreign_shapes(self):
        # Direct DB predicate proof, independent of any Python normalizer.
        before = self._snapshot()
        for candidate in ("+989123456789", "+4915123456789", "+447911123456"):
            with self.subTest(candidate_length=len(candidate)):
                self.assertEqual(
                    self._claim(
                        101, candidate,
                        legacy="09123456789", active=True,
                        version=self._snapshot()[0][4],
                    ), "applied",
                )
                self.assertEqual(
                    self._rollback(
                        101, legacy="09123456789", active=True,
                        version=self._snapshot()[0][4],
                    ), "applied",
                )
        after = self._snapshot()
        self.assertEqual(after[0][1:4], before[0][1:4])
        self.assertEqual(after[0][4], 6)

    def test_constraint_rejects_invalid_syntax_and_negative_revision(self):
        initial = self._snapshot()
        for invalid in ("+123", "989123456789", "text"):
            with self.subTest(length=len(invalid)):
                self.assertEqual(
                    self._claim(101, invalid, legacy="09123456789", active=True),
                    "unique_or_check_conflict",
                )
                self.assertEqual(self._snapshot(), initial)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f'UPDATE "{TABLE}" SET phone_identity_revision=-1 '
                        'WHERE account_id=101'
                    )
        self.assertEqual(self._snapshot(), initial)

    def test_stale_revision_and_legacy_or_active_drift_fail_closed(self):
        before = self._snapshot()
        self.assertEqual(
            self._claim(101, "+989123456789",
                        legacy="09123456789", active=True, version=1),
            "stale_or_mismatched",
        )
        self.assertEqual(
            self._claim(101, "+989123456789",
                        legacy="09123456780", active=True),
            "stale_or_mismatched",
        )
        self.assertEqual(
            self._claim(101, "+989123456789",
                        legacy="09123456789", active=False),
            "stale_or_mismatched",
        )
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(
            self._claim(101, "+989123456789",
                        legacy="09123456789", active=True),
            "applied",
        )
        self.assertEqual(
            self._claim(101, "+989123456789",
                        legacy="09123456789", active=True),
            "stale_or_mismatched",
        )

    def test_transaction_rollback_of_successful_claim_on_late_failure(self):
        before = self._snapshot()
        with self.assertRaises(InjectedRollback):
            with transaction.atomic():
                self.assertEqual(
                    self._claim(
                        101, "+989123456789", legacy="09123456789",
                        active=True,
                    ), "applied",
                )
                raise InjectedRollback
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(
            self._claim(101, "+989123456789",
                        legacy="09123456789", active=True),
            "applied",
        )

    def test_two_row_batch_integrity_failure_rolls_back_first_write(self):
        self.assertEqual(
            self._claim(103, "+989123456781",
                        legacy="09123456781", active=True),
            "applied",
        )
        before = self._snapshot()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'''
                        UPDATE "{TABLE}"
                           SET canonical_mobile_e164=%s,
                               phone_identity_revision=phone_identity_revision+1
                         WHERE account_id=101
                    ''', ["+989123456789"])
                    cursor.execute(f'''
                        UPDATE "{TABLE}"
                           SET canonical_mobile_e164=%s,
                               phone_identity_revision=phone_identity_revision+1
                         WHERE account_id=102
                    ''', ["+989123456781"])
        # Neither update can commit: the original row 103 is retained and
        # the first row has reverted to its original NULL and revision.
        self.assertEqual(self._snapshot(), before)

    def test_versioned_shadow_rollback_preserves_legacy_and_inactive_flag(self):
        before = self._snapshot()
        self.assertEqual(
            self._claim(102, "+989123456780",
                        legacy="09123456780", active=False),
            "applied",
        )
        self.assertEqual(
            self._rollback(102, legacy="09123456780", active=False, version=0),
            "stale_or_mismatched",
        )
        self.assertEqual(
            self._rollback(102, legacy="09123456780", active=True, version=1),
            "stale_or_mismatched",
        )
        self.assertEqual(
            self._rollback(102, legacy="09123456780", active=False, version=1),
            "applied",
        )
        after = self._snapshot()
        self.assertEqual(after[1][1:4], before[1][1:4])
        self.assertEqual(after[1][4], 2)
        self.assertEqual(
            self._rollback(102, legacy="09123456780", active=False, version=1),
            "stale_or_mismatched",
        )
        self.assertEqual(
            self._claim(102, "+989123456780",
                        legacy="09123456780", active=False, version=2),
            "applied",
        )

    def test_two_postgres_sessions_same_row_compete_only_one_wins(self):
        barrier = Barrier(3, timeout=20)
        kwargs = dict(
            account_id=101, candidate="+989123456789",
            legacy="09123456789", active=True,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(self._thread_claim, barrier, **kwargs)
            b = pool.submit(self._thread_claim, barrier, **kwargs)
            barrier.wait(timeout=20)
            results = [a.result(timeout=20), b.result(timeout=20)]
        self.assertEqual(len({x[0] for x in results}), 2)
        self.assertEqual(
            sorted(x[1] for x in results), ["applied", "stale_or_mismatched"]
        )
        after = self._snapshot()
        self.assertEqual(after[0][4], 1)
        self.assertEqual(after[0][3], "+989123456789")

    def test_two_postgres_sessions_different_rows_same_canonical_unique_wins(self):
        barrier = Barrier(3, timeout=20)
        shared = "+989123456789"
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(
                self._thread_claim, barrier,
                account_id=101, candidate=shared,
                legacy="09123456789", active=True,
            )
            b = pool.submit(
                self._thread_claim, barrier,
                account_id=102, candidate=shared,
                legacy="09123456780", active=False,
            )
            barrier.wait(timeout=20)
            outcomes = [a.result(timeout=20), b.result(timeout=20)]
        self.assertEqual(len({x[0] for x in outcomes}), 2)
        self.assertEqual(
            sorted(x[1] for x in outcomes),
            ["applied", "unique_or_check_conflict"],
        )
        data = self._snapshot()
        self.assertEqual(sum(row[3] == shared for row in data), 1)
        self.assertEqual(sum(row[4] for row in data), 1)

    def test_two_postgres_sessions_disjoint_valid_claims_both_commit(self):
        barrier = Barrier(3, timeout=20)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(
                self._thread_claim, barrier,
                account_id=101, candidate="+989123456789",
                legacy="09123456789", active=True,
            )
            b = pool.submit(
                self._thread_claim, barrier,
                account_id=102, candidate="+989123456780",
                legacy="09123456780", active=False,
            )
            barrier.wait(timeout=20)
            outcomes = [a.result(timeout=20), b.result(timeout=20)]
        self.assertEqual(len({x[0] for x in outcomes}), 2)
        self.assertEqual([x[1] for x in outcomes], ["applied", "applied"])
        data = self._snapshot()
        self.assertEqual(sum(row[3] is not None for row in data), 2)
        self.assertFalse(data[1][2])

    def test_no_real_user_table_or_migrations_are_written(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        source = (root / "apps/accounts/models.py").read_text(encoding="utf-8")
        self.assertIn('USERNAME_FIELD = "mobile_number"', source)
        self.assertIn("max_length=11, unique=True", source)
        # The test-only SQL is constrained to the dedicated fixture table.
        from inspect import getsource
        module_text = getsource(type(self))
        protected_table = CustomUser._meta.db_table.upper()
        for verb in ("UPDATE", "ALTER TABLE", "DELETE FROM", "INSERT INTO"):
            self.assertNotIn(
                verb + ' "' + protected_table + '"',
                module_text.upper(),
            )
