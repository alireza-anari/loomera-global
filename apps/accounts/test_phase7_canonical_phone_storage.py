"""Exit A: actual installed account storage on the disposable Django test DB."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from apps.accounts.models import CustomUser, AccountDeletionRequest
from apps.api.v1.auth_serializers import validate_mobile_for_auth
from loomera.globalization.phone_identity import to_candidate_e164

OLD = ("accounts", "0004_userworkspacepreference")
NEW = ("accounts", "0005_canonical_phone_storage")
IR = "09123456789"
IR_ALIAS = "+989123456789"
FOREIGN = "+12025550100"
TOMBSTONE = "98000000001"


class CanonicalPhoneStorageTests(TransactionTestCase):
    def create(self, mobile, active=True):
        return CustomUser.objects.create(
            mobile_number=mobile, is_active=active, password="!",
        )

    def test_legacy_and_explicit_foreign_storage_is_database_derived(self):
        for value in (IR, "09123456780", FOREIGN, "+123456789012345"):
            with self.subTest(value=value):
                user = self.create(value)
                user.refresh_from_db()
                self.assertEqual(user.mobile_number, value)
                self.assertEqual(user.canonical_mobile_number, to_candidate_e164(value))
        self.assertEqual(CustomUser.USERNAME_FIELD, "mobile_number")
        self.assertFalse(validate_mobile_for_auth(FOREIGN)[0])
        # Storage expansion does not broaden legacy model-form validation.
        with self.assertRaises(ValidationError):
            CustomUser._meta.get_field("mobile_number").clean(FOREIGN, None)

    def test_database_uniqueness_includes_inactive_accounts_and_iran_aliases(self):
        original = self.create(IR, active=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create(IR_ALIAS)
        original.refresh_from_db()
        self.assertFalse(original.is_active)
        self.assertEqual(original.canonical_mobile_number, IR_ALIAS)
        self.assertEqual(CustomUser.objects.count(), 1)

    def test_legacy_rekey_to_tombstone_releases_canonical_identity(self):
        user = self.create(IR)
        CustomUser.objects.filter(pk=user.pk).update(
            mobile_number=TOMBSTONE, is_active=False, password="!",
        )
        user.refresh_from_db()
        self.assertIsNone(user.canonical_mobile_number)
        replacement = self.create(IR)
        replacement.refresh_from_db()
        self.assertEqual(replacement.canonical_mobile_number, IR_ALIAS)
        self.assertNotEqual(user.pk, replacement.pk)

    def test_bulk_write_recomputes_instead_of_leaving_stale_claim(self):
        user = self.create(IR)
        user.mobile_number = "09123456780"
        CustomUser.objects.bulk_update([user], ["mobile_number"])
        user.refresh_from_db()
        self.assertEqual(user.canonical_mobile_number, "+989123456780")
        self.assertFalse(CustomUser.objects.filter(canonical_mobile_number=IR_ALIAS).exists())

    def test_invalid_values_have_no_canonical_identity(self):
        # Preserve compatibility for opaque historic placeholders and programmatic
        # writes, but never project them to a canonical login identity.
        for value in (TOMBSTONE, "۰۹۱۲۳۴۵۶۷۸۹", "+982112345678", "+12025550100\n"):
            user = self.create(value, active=False)
            user.refresh_from_db()
            self.assertIsNone(user.canonical_mobile_number)

    def test_independent_postgres_transactions_cannot_claim_same_identity(self):
        if connection.vendor != "postgresql":
            self.skipTest("independent PostgreSQL uniqueness proof")
        gate = Barrier(2, timeout=10)

        def insert(value):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                try:
                    with transaction.atomic():
                        CustomUser.objects.create(mobile_number=value, password="!")
                    return "committed"
                except IntegrityError:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(insert, value) for value in (IR, IR_ALIAS)]
            self.assertEqual(sorted(f.result(timeout=25) for f in futures),
                             ["committed", "conflict"])
        self.assertEqual(CustomUser.objects.filter(canonical_mobile_number=IR_ALIAS).count(), 1)

    def test_actual_migration_graph_preserves_ids_status_password_and_deletion_evidence(self):
        if connection.vendor != "postgresql":
            self.skipTest("actual PostgreSQL migration rehearsal")
        executor = MigrationExecutor(connection)
        executor.migrate([OLD])
        old_apps = executor.loader.project_state([OLD]).apps
        OldUser = old_apps.get_model("accounts", "CustomUser")
        OldDeletion = old_apps.get_model("accounts", "AccountDeletionRequest")
        try:
            active = OldUser.objects.create(mobile_number=IR, is_active=True, password="fixture-hash")
            inactive = OldUser.objects.create(mobile_number="09123456780", is_active=False, password="!")
            deleted = OldUser.objects.create(mobile_number=TOMBSTONE, is_active=False, password="!")
            deletion = OldDeletion.objects.create(
                user_id=deleted.pk, original_user_id=deleted.pk,
                status="anonymized", anonymized_at=timezone.now(),
            )
            MigrationExecutor(connection).migrate([NEW])
            active_row = CustomUser.objects.get(pk=active.pk)
            self.assertEqual((active_row.mobile_number, active_row.password, active_row.is_active),
                             (IR, "fixture-hash", True))
            self.assertEqual(active_row.canonical_mobile_number, IR_ALIAS)
            self.assertFalse(CustomUser.objects.get(pk=inactive.pk).is_active)
            self.assertIsNone(CustomUser.objects.get(pk=deleted.pk).canonical_mobile_number)
            self.assertEqual(AccountDeletionRequest.objects.get(pk=deletion.pk).user_id, deleted.pk)
            MigrationExecutor(connection).migrate([OLD])
            self.assertEqual(OldUser.objects.get(pk=active.pk).mobile_number, IR)
        finally:
            MigrationExecutor(connection).migrate([NEW])

    def test_forward_migration_refuses_unverified_placeholder_and_alias_without_pii(self):
        if connection.vendor != "postgresql":
            self.skipTest("actual PostgreSQL migration rehearsal")
        executor = MigrationExecutor(connection)
        executor.migrate([OLD])
        OldUser = executor.loader.project_state([OLD]).apps.get_model("accounts", "CustomUser")
        invalid = []
        try:
            invalid.append(OldUser.objects.create(
                mobile_number=TOMBSTONE, is_active=False, password="!",
            ).pk)
            invalid.append(OldUser.objects.create(
                mobile_number="۰۹۱۲۳۴۵۶۷۸۹", is_active=True, password="!",
            ).pk)
            with self.assertRaisesRegex(RuntimeError, r"unresolved account rows=2") as failure:
                MigrationExecutor(connection).migrate([NEW])
            self.assertNotIn(TOMBSTONE, str(failure.exception))
            self.assertNotIn("۰۹۱۲۳۴۵۶۷۸۹", str(failure.exception))
            self.assertEqual(OldUser.objects.filter(pk__in=invalid).count(), 2)
        finally:
            OldUser.objects.filter(pk__in=invalid).delete()
            MigrationExecutor(connection).migrate([NEW])

    def test_reverse_migration_refuses_foreign_identifier_without_truncation(self):
        if connection.vendor != "postgresql":
            self.skipTest("actual PostgreSQL migration rehearsal")
        user = self.create(FOREIGN)
        try:
            with self.assertRaisesRegex(RuntimeError, r"unresolved account rows=1"):
                MigrationExecutor(connection).migrate([OLD])
            user.refresh_from_db()
            self.assertEqual(user.mobile_number, FOREIGN)
            self.assertEqual(user.canonical_mobile_number, FOREIGN)
        finally:
            CustomUser.objects.filter(pk=user.pk).delete()
            MigrationExecutor(connection).migrate([NEW])
