"""Phase 7.5: reversible *test-only* Django schema operations on PostGIS.

This is NOT a migrations/ file or a production migration. Historical
migration Operations + SchemaEditor run on a dedicated synthetic table in
Django's ephemeral test database. Do not import this module from app code.
"""
from __future__ import annotations

from copy import deepcopy
import re

from django.core.exceptions import FieldDoesNotExist
from django.db import IntegrityError, connection, migrations, models, transaction
from django.db.migrations.state import ProjectState
from django.test import TransactionTestCase

from apps.accounts.models import CustomUser
from loomera.globalization.phone_identity import (
    PhoneIdentityInputError,
    to_candidate_e164,
)

APP_LABEL = "phase75_synthetic"
MODEL_NAME = "SyntheticPhoneRecord"
TABLE = "loomera_phase75_phone_shadow_fixture"
SOURCE_ROWS = (
    (101, "09123456789", True),
    (102, "09123456780", False),
    (103, "09123456781", True),
)
LEGACY_NUMBER = re.compile(r"09[0-9]{9}\Z")
MAX_FIXTURE_ROWS = 100


class OfflineRehearsalBlocked(Exception):
    """Fixed reason only; do not include a phone, account ID or SQL params."""


class SyntheticInterruption(Exception):
    """An injected failure, never a real service outage."""


class Phase75ReversiblePhoneShadowMigration(TransactionTestCase):
    """Genuine Django migration operations; never the CustomUser schema."""

    databases = {"default"}

    def setUp(self):
        super().setUp()
        if not connection.settings_dict["ENGINE"].endswith(".postgis"):
            self.fail("Isolated PostGIS backend required")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), PostGIS_Version()")
            database_name, version = cursor.fetchone()
        if not database_name.startswith("test_") or not version:
            self.fail("Synthetic test database and PostGIS extension required")

        self.baseline = ProjectState()
        self.create = migrations.CreateModel(
            name=MODEL_NAME,
            fields=[
                ("account_id", models.BigIntegerField(primary_key=True)),
                ("mobile_number", models.CharField(max_length=11, unique=True)),
                ("is_active", models.BooleanField()),
            ],
            options={"db_table": TABLE},
        )
        self.forward_ops = (
            migrations.AddField(
                model_name=MODEL_NAME, name="canonical_mobile_e164",
                field=models.CharField(max_length=16, null=True, unique=True),
            ),
            migrations.AddField(
                model_name=MODEL_NAME, name="phone_identity_revision",
                field=models.PositiveIntegerField(default=0),
            ),
            migrations.RunSQL(
                sql=f'''
                    ALTER TABLE "{TABLE}"
                    ADD CONSTRAINT phase75_e164_candidate_shape
                    CHECK (
                        canonical_mobile_e164 IS NULL OR (
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
                ''',
                reverse_sql=f'''
                    ALTER TABLE "{TABLE}"
                    DROP CONSTRAINT phase75_e164_candidate_shape
                ''',
            ),
        )
        self.expanded = False
        self.forward_states = None
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
        self.legacy_state = self._apply((self.create,), self.baseline)[-1]
        with connection.cursor() as cursor:
            cursor.executemany(
                f'''
                    INSERT INTO "{TABLE}"
                        (account_id, mobile_number, is_active)
                    VALUES (%s, %s, %s)
                ''',
                SOURCE_ROWS,
            )
        self.source_before = self._source_snapshot()

    def tearDown(self):
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
        finally:
            super().tearDown()

    @staticmethod
    def _apply(operations, initial):
        """Use historical ProjectState and *real* SchemaEditor forwards."""
        states = [initial]
        with connection.schema_editor() as editor:
            for operation in operations:
                next_state = states[-1].clone()
                operation.state_forwards(APP_LABEL, next_state)
                operation.database_forwards(
                    APP_LABEL, editor, states[-1], next_state
                )
                states.append(next_state)
        return states

    def _expand(self):
        if self.expanded:
            raise OfflineRehearsalBlocked("schema_already_expanded")
        self.forward_states = self._apply(self.forward_ops, self.legacy_state)
        self.expanded = True

    def _shrink(self):
        if not self.expanded:
            raise OfflineRehearsalBlocked("schema_not_expanded")
        with connection.cursor() as cursor:
            cursor.execute(
                f'''SELECT COUNT(*) FROM "{TABLE}"
                    WHERE canonical_mobile_e164 IS NOT NULL'''
            )
            if cursor.fetchone()[0]:
                # Real migrations must have their OWN reviewed rollback policy.
                raise OfflineRehearsalBlocked("outstanding_canonical_claims")
        with connection.schema_editor() as editor:
            for index in reversed(range(len(self.forward_ops))):
                self.forward_ops[index].database_backwards(
                    APP_LABEL,
                    editor,
                    self.forward_states[index + 1],
                    self.forward_states[index],
                )
        self.expanded = False
        self.forward_states = None

    @staticmethod
    def _source_snapshot():
        with connection.cursor() as cursor:
            cursor.execute(f'''
                SELECT account_id, mobile_number, is_active
                  FROM "{TABLE}" ORDER BY account_id
            ''')
            return tuple(cursor.fetchall())

    @staticmethod
    def _shadow_snapshot():
        with connection.cursor() as cursor:
            cursor.execute(f'''
                SELECT account_id, mobile_number, is_active,
                       canonical_mobile_e164, phone_identity_revision
                  FROM "{TABLE}" ORDER BY account_id
            ''')
            return tuple(cursor.fetchall())

    @staticmethod
    def _columns():
        with connection.cursor() as cursor:
            cursor.execute(
                '''SELECT column_name
                     FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s''',
                [TABLE],
            )
            return {row[0] for row in cursor.fetchall()}

    @staticmethod
    def _unique_index_count():
        with connection.cursor() as cursor:
            cursor.execute(
                '''SELECT COUNT(*)
                     FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = %s
                      AND indexdef ILIKE '%%UNIQUE INDEX%%'
                      AND indexdef ILIKE '%%(canonical_mobile_e164)%%'
                      AND indexdef NOT ILIKE '%% WHERE %%' ''',
                [TABLE],
            )
            return cursor.fetchone()[0]

    @staticmethod
    def _preflight():
        rows = Phase75ReversiblePhoneShadowMigration._source_snapshot()
        if not 1 <= len(rows) <= MAX_FIXTURE_ROWS or len(rows) != len(SOURCE_ROWS):
            raise OfflineRehearsalBlocked("incomplete_fixture_scope")
        seen = set()
        mapped = []
        for account_id, legacy, active in rows:
            if (
                type(account_id) is not int or account_id <= 0
                or type(active) is not bool
                or type(legacy) is not str
                or LEGACY_NUMBER.fullmatch(legacy) is None
            ):
                raise OfflineRehearsalBlocked("unsupported_legacy_identity")
            try:
                candidate = to_candidate_e164(legacy)
            except PhoneIdentityInputError as exc:
                raise OfflineRehearsalBlocked("unparseable_identity") from exc
            if candidate in seen:
                raise OfflineRehearsalBlocked("canonical_alias_collision")
            seen.add(candidate)
            mapped.append((account_id, legacy, active, candidate))
        return mapped

    def _backfill(self, *, chunk_size, stop_after_chunks=None, fail_on_account=None):
        """Synthetic bounded per-chunk ACID; retry is idempotent and guarded.

        Stale/surprising shadow rows always fail closed. Preflight covers the
        complete source snapshot BEFORE any SQL UPDATE. Every UPDATE binds
        account ID, source number, status, revision and NULL shadow together.
        """
        if not self.expanded:
            raise OfflineRehearsalBlocked("schema_not_expanded")
        if type(chunk_size) is not int or not 1 <= chunk_size <= 3:
            raise OfflineRehearsalBlocked("invalid_chunk_size")
        if (
            stop_after_chunks is not None
            and (type(stop_after_chunks) is not int or stop_after_chunks < 0)
        ):
            raise OfflineRehearsalBlocked("invalid_stop_checkpoint")
        mapped = self._preflight()
        applied, skipped, chunks_done = 0, 0, 0
        for index in range(0, len(mapped), chunk_size):
            if stop_after_chunks is not None and chunks_done >= stop_after_chunks:
                break
            part = mapped[index:index + chunk_size]
            with transaction.atomic():
                for account_id, legacy, active, candidate in part:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f'''SELECT canonical_mobile_e164, phone_identity_revision
                                 FROM "{TABLE}" WHERE account_id = %s''',
                            [account_id],
                        )
                        row = cursor.fetchone()
                    if row is None:
                        raise OfflineRehearsalBlocked("missing_account")
                    current, revision = row
                    if current == candidate and revision == 1:
                        skipped += 1
                        continue
                    if current is not None or revision != 0:
                        raise OfflineRehearsalBlocked("shadow_or_revision_drift")
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute(f'''
                                UPDATE "{TABLE}"
                                   SET canonical_mobile_e164 = %s,
                                       phone_identity_revision =
                                           phone_identity_revision + 1
                                 WHERE account_id = %s
                                   AND mobile_number = %s
                                   AND is_active = %s
                                   AND phone_identity_revision = 0
                                   AND canonical_mobile_e164 IS NULL
                             RETURNING phone_identity_revision
                            ''', [candidate, account_id, legacy, active])
                            claim = cursor.fetchone()
                    except IntegrityError as exc:
                        raise OfflineRehearsalBlocked(
                            "canonical_uniqueness_or_shape_conflict"
                        ) from exc
                    if claim != (1,):
                        raise OfflineRehearsalBlocked("concurrent_source_drift")
                    applied += 1
                    if account_id == fail_on_account:
                        raise SyntheticInterruption
            chunks_done += 1
        return {
            "applied": applied,
            "already_claimed": skipped,
            "chunks_committed": chunks_done,
            "source_accounts": len(mapped),
            "preflight_scope_complete": True,
            "live_accounts_modified": False,
            "production_migration_authorized": False,
        }

    def _clear_claims_for_test_only_rollback(self):
        """Explicit synthetic clear; never a real data migration runbook."""
        if not self.expanded:
            raise OfflineRehearsalBlocked("schema_not_expanded")
        rows = self._preflight()
        with transaction.atomic():
            for account_id, legacy, active, candidate in rows:
                with connection.cursor() as cursor:
                    cursor.execute(f'''
                        UPDATE "{TABLE}"
                           SET canonical_mobile_e164 = NULL,
                               phone_identity_revision =
                                   phone_identity_revision + 1
                         WHERE account_id = %s AND mobile_number = %s
                           AND is_active = %s
                           AND canonical_mobile_e164 = %s
                           AND phone_identity_revision = 1
                     RETURNING phone_identity_revision
                    ''', [account_id, legacy, active, candidate])
                    if cursor.fetchone() != (2,):
                        raise OfflineRehearsalBlocked("rollback_version_mismatch")

    def test_nullable_expansion_creates_unique_index_without_touching_customuser(self):
        original = self.source_before
        self.assertEqual(self._columns(), {
            "account_id", "mobile_number", "is_active",
        })
        with self.assertRaises(FieldDoesNotExist):
            CustomUser._meta.get_field("canonical_mobile_e164")
        self._expand()
        self.assertEqual(self._columns(), {
            "account_id", "mobile_number", "is_active",
            "canonical_mobile_e164", "phone_identity_revision",
        })
        self.assertEqual(self._unique_index_count(), 1)
        self.assertEqual(self._source_snapshot(), original)
        self.assertEqual(
            sum(row[3] is None and row[4] == 0 for row in self._shadow_snapshot()),
            3,
        )
        # AddField(default=0) backfills existing rows, but migration
        # SchemaEditor does not promise a persistent SQL DEFAULT for raw
        # inserts. A future writer must supply revision explicitly.
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT column_default
                     FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = %s
                      AND column_name = 'phone_identity_revision'""",
                [TABLE],
            )
            self.assertIsNone(cursor.fetchone()[0])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM django_migrations WHERE app = %s",
                [APP_LABEL],
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        with self.assertRaises(FieldDoesNotExist):
            CustomUser._meta.get_field("phone_identity_revision")

    def test_two_chunk_backfill_preserves_legacy_and_inactive(self):
        self._expand()
        data = self._backfill(chunk_size=2)
        self.assertEqual(data["applied"], 3)
        self.assertEqual(data["chunks_committed"], 2)
        self.assertFalse(data["production_migration_authorized"])
        self.assertEqual(self._source_snapshot(), self.source_before)
        projected = self._shadow_snapshot()
        self.assertEqual([row[4] for row in projected], [1, 1, 1])
        self.assertEqual(
            [row[3] for row in projected],
            [to_candidate_e164(item[1]) for item in self.source_before],
        )
        self.assertFalse(projected[1][2])

    def test_interrupted_batches_resume_idempotently_without_revisions_replayed(self):
        self._expand()
        first = self._backfill(chunk_size=1, stop_after_chunks=1)
        self.assertEqual(first["applied"], 1)
        self.assertEqual(sum(row[3] is not None for row in self._shadow_snapshot()), 1)
        second = self._backfill(chunk_size=1)
        self.assertEqual(second["applied"], 2)
        self.assertEqual(second["already_claimed"], 1)
        before = self._shadow_snapshot()
        repeat = self._backfill(chunk_size=2)
        self.assertEqual(repeat["applied"], 0)
        self.assertEqual(repeat["already_claimed"], 3)
        self.assertEqual(self._shadow_snapshot(), before)
        self.assertEqual(self._source_snapshot(), self.source_before)

    def test_failure_inside_first_chunk_leaves_no_partial_records(self):
        self._expand()
        before = self._shadow_snapshot()
        with self.assertRaises(SyntheticInterruption):
            self._backfill(chunk_size=3, fail_on_account=102)
        self.assertEqual(self._shadow_snapshot(), before)
        self.assertEqual(self._source_snapshot(), self.source_before)

    def test_second_chunk_failure_preserves_prior_committed_checkpoint_only(self):
        self._expand()
        with self.assertRaises(SyntheticInterruption):
            self._backfill(chunk_size=1, fail_on_account=102)
        state = self._shadow_snapshot()
        self.assertEqual([row[4] for row in state], [1, 0, 0])
        resumed = self._backfill(chunk_size=2)
        self.assertEqual(resumed["applied"], 2)
        self.assertEqual(resumed["already_claimed"], 1)
        self.assertEqual(self._source_snapshot(), self.source_before)

    def test_unknown_placeholder_stops_entire_preflight_before_writes(self):
        self._expand()
        with connection.cursor() as cursor:
            cursor.execute(
                f'UPDATE "{TABLE}" SET mobile_number = %s WHERE account_id = %s',
                ["98000000001", 103],
            )
        before = self._shadow_snapshot()
        with self.assertRaisesRegex(
            OfflineRehearsalBlocked, "^unsupported_legacy_identity$"
        ):
            self._backfill(chunk_size=1)
        self.assertEqual(self._shadow_snapshot(), before)

    def test_unexpected_accounts_stop_scope_before_any_backfill(self):
        self._expand()
        with connection.cursor() as cursor:
            cursor.execute(f'''
                INSERT INTO "{TABLE}"
                    (account_id, mobile_number, is_active, phone_identity_revision)
                VALUES (%s, %s, %s, %s)
            ''', [404, "09123456782", False, 0])
        before = self._shadow_snapshot()
        with self.assertRaisesRegex(
            OfflineRehearsalBlocked, "^incomplete_fixture_scope$"
        ):
            self._backfill(chunk_size=1)
        self.assertEqual(self._shadow_snapshot(), before)

    def test_preexisting_wrong_shadow_blocks_whole_chunk(self):
        self._expand()
        with connection.cursor() as cursor:
            cursor.execute(f'''
                UPDATE "{TABLE}"
                   SET canonical_mobile_e164 = %s,
                       phone_identity_revision = 1
                 WHERE account_id = 102
            ''', ["+4915123456789"])
        before = self._shadow_snapshot()
        with self.assertRaisesRegex(
            OfflineRehearsalBlocked, "^shadow_or_revision_drift$"
        ):
            self._backfill(chunk_size=3)
        self.assertEqual(self._shadow_snapshot(), before)
        self.assertEqual(self._source_snapshot(), self.source_before)

    def test_reverse_operations_refuse_claimed_shadow_and_preserve_login(self):
        self._expand()
        self._backfill(chunk_size=2)
        before = self._shadow_snapshot()
        with self.assertRaisesRegex(
            OfflineRehearsalBlocked, "^outstanding_canonical_claims$"
        ):
            self._shrink()
        self.assertEqual(self._shadow_snapshot(), before)
        self.assertEqual(self._unique_index_count(), 1)
        self._clear_claims_for_test_only_rollback()
        self.assertTrue(all(row[3] is None for row in self._shadow_snapshot()))
        self._shrink()
        self.assertEqual(self._columns(), {
            "account_id", "mobile_number", "is_active",
        })
        self.assertEqual(self._unique_index_count(), 0)
        self.assertEqual(self._source_snapshot(), self.source_before)
        self._expand()
        self.assertEqual(self._unique_index_count(), 1)
        self.assertEqual(self._source_snapshot(), self.source_before)
        self.assertTrue(all(
            row[3] is None and row[4] == 0
            for row in self._shadow_snapshot()
        ))

    def test_reverse_without_claims_is_idempotent_on_legacy_schema(self):
        self._expand()
        self._shrink()
        self.assertFalse(self.expanded)
        self.assertEqual(self._source_snapshot(), self.source_before)
        with self.assertRaisesRegex(
            OfflineRehearsalBlocked, "^schema_not_expanded$"
        ):
            self._shrink()
        self._expand()
        self.assertEqual(self._unique_index_count(), 1)

    def test_fail_closed_on_invalid_checkpoint_and_stale_version(self):
        self._expand()
        for size in (0, -1, True, 4):
            with self.subTest(size=size):
                with self.assertRaises(OfflineRehearsalBlocked):
                    self._backfill(chunk_size=size)
        for stop in (True, -1, "1"):
            with self.subTest(stop=stop):
                with self.assertRaises(OfflineRehearsalBlocked):
                    self._backfill(chunk_size=1, stop_after_chunks=stop)
        with connection.cursor() as cursor:
            cursor.execute(f'''
                UPDATE "{TABLE}"
                   SET phone_identity_revision = 9 WHERE account_id = 101
            ''')
        with self.assertRaisesRegex(
            OfflineRehearsalBlocked, "^shadow_or_revision_drift$"
        ):
            self._backfill(chunk_size=3)
        self.assertEqual(
            [row[3] for row in self._shadow_snapshot()], [None, None, None]
        )
