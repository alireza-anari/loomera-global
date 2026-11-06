"""Phase 7.1: pure E.164 candidate boundary and offline collision preflight."""
from __future__ import annotations

import hashlib
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.main.management.commands import audit_phase7_phone_identity as command
from loomera.globalization.phone_collision_audit import (
    preview_phone_identity_collisions,
)
from loomera.globalization.phone_identity import (
    PhoneIdentityInputError,
    to_candidate_e164,
)


class Phase71PhoneIdentityTests(SimpleTestCase):
    def test_iranian_legacy_forms_converge_to_one_candidate(self):
        for value in (
            "09123456789", "+989123456789", "00989123456789",
            "989123456789", "9123456789", "۰۹۱۲۳۴۵۶۷۸۹",
            "٠٩١٢٣٤٥٦٧٨٩", "0912 345-6789", "+98 912-345-6789",
        ):
            with self.subTest(value=value):
                self.assertEqual(to_candidate_e164(value), "+989123456789")
                self.assertEqual(
                    to_candidate_e164(to_candidate_e164(value)),
                    "+989123456789",
                )

    def test_explicit_foreign_e164_requires_no_local_number_guess(self):
        self.assertEqual(
            to_candidate_e164("+4915123456789", default_country="DE"),
            "+4915123456789",
        )
        self.assertEqual(
            to_candidate_e164("+447911123456", default_country="IR"),
            "+447911123456",
        )
        for value in ("015123456789", "004915123456789", "4915123456789"):
            with self.subTest(value=value):
                with self.assertRaises(PhoneIdentityInputError):
                    to_candidate_e164(value, default_country="DE")

    def test_rejects_malformed_and_non_mobile_iran_without_echoing_number(self):
        invalid = (
            "", "0912345678", "091234567890", "099", "02123456789",
            "+982112345678", "+9809123456789", "009891234567890",
            "0912abc6789", "0912_3456789", "0912\n3456789",
            "０９１２３４５６７８９", "++989123456789", "0912/3456789",
            "+123", "000989123456789", "+989123456789999",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(PhoneIdentityInputError) as ctx:
                    to_candidate_e164(value)
                if value:
                    self.assertNotIn(value, str(ctx.exception))
                else:
                    self.assertEqual(str(ctx.exception), "invalid phone identity")
        for country in (None, "IRAN", "I1", "🇮🇷", True):
            with self.subTest(country=country):
                with self.assertRaises(PhoneIdentityInputError):
                    to_candidate_e164("09123456789", default_country=country)

    def test_does_not_mutate_existing_smsir_or_api_auth_code_paths(self):
        root = Path(__file__).resolve().parents[2]
        sources = {
            "apps/accounts/models.py": (
                "max_length=11, unique=True",
                'USERNAME_FIELD = "mobile_number"',
            ),
            "apps/api/v1/auth_serializers.py": (
                "def normalize_iran_mobile(",
                "def validate_mobile_for_auth(",
                "_IRAN_MOBILE_RE",
            ),
            "apps/accounts/services/sms.py": (
                "def format_smsir_mobile(",
                "def normalize_mobile_number(",
                "def mask_mobile_number(",
            ),
            "apps/accounts/views.py": (
                "username=cleaned_data[\"mobile_number\"]",
                "CustomUser.objects.get(mobile_number=data[\"mobile_number\"])",
            ),
            "apps/api/v1/auth_views.py": (
                "mobile_number=normalized_mobile",
                "mobile_number=mobile_number,",
            ),
        }
        for path, anchors in sources.items():
            text = (root / path).read_text(encoding="utf-8")
            for anchor in anchors:
                with self.subTest(path=path, anchor=anchor):
                    self.assertIn(anchor, text)


class Phase71CollisionAuditTests(SimpleTestCase):
    def _rows(self):
        return [
            {"account_id": 1, "mobile_number": "09123456789", "is_active": True},
            {"account_id": 2, "mobile_number": "۰۹۱۲۳۴۵۶۷۸۰", "is_active": False},
            {"account_id": 3, "mobile_number": "+4915123456789", "is_active": True},
        ]

    def test_clean_preview_is_aggregate_only_and_never_authorizes_migration(self):
        rows = self._rows()
        output = preview_phone_identity_collisions(
            rows, expected_accounts=3, default_country="IR"
        )
        self.assertTrue(output["preflight_structurally_clean"])
        self.assertEqual(output["candidate_iran_accounts"], 2)
        self.assertEqual(output["candidate_non_iran_accounts"], 1)
        self.assertEqual(output["active_accounts"], 2)
        self.assertEqual(output["inactive_accounts"], 1)
        self.assertEqual(output["canonical_collision_extra_accounts_count"], 0)
        self.assertFalse(output["identity_cutover_authorized"])
        self.assertFalse(output["uniqueness_migration_authorized"])
        self.assertFalse(output["sms_provider_change_authorized"])
        self.assertFalse(output["account_merge_authorized"])
        self.assertEqual(output["database_reads"], 0)
        self.assertEqual(output["writes_performed"], 0)
        encoded = json.dumps(output)
        for pii in ("09123456789", "+989123456789", "+4915123456789"):
            self.assertNotIn(pii, encoded)

    def test_alias_collision_including_inactive_account_blocks(self):
        rows = self._rows()
        rows[1]["mobile_number"] = "+989123456789"
        output = preview_phone_identity_collisions(rows, expected_accounts=3)
        self.assertFalse(output["preflight_structurally_clean"])
        self.assertEqual(output["canonical_collision_extra_accounts_count"], 1)
        self.assertEqual(
            output["canonical_collisions_involving_active_accounts_count"], 1
        )
        self.assertIn("canonical_identity_collisions", output["stop_reasons"])

    def test_two_inactive_aliases_also_block_and_never_auto_merge(self):
        rows = self._rows()
        rows[0]["is_active"] = False
        rows[1]["mobile_number"] = "00989123456789"
        output = preview_phone_identity_collisions(rows, expected_accounts=3)
        self.assertFalse(output["preflight_structurally_clean"])
        self.assertEqual(
            output["canonical_collisions_involving_active_accounts_count"], 0
        )
        self.assertEqual(output["canonical_collision_extra_accounts_count"], 1)
        self.assertFalse(output["account_merge_authorized"])

    def test_invalid_deleted_or_duplicate_ids_and_scope_are_hard_stops(self):
        rows = self._rows()
        rows[1]["mobile_number"] = "deleted-account-placeholder"
        rows[2]["account_id"] = 1
        result = preview_phone_identity_collisions(rows, expected_accounts=4)
        self.assertEqual(result["unparseable_phone_count"], 1)
        self.assertEqual(result["duplicate_account_id_count"], 1)
        self.assertIn(
            "incomplete_or_mismatched_snapshot_scope", result["stop_reasons"]
        )
        rows[2]["account_id"] = True
        self.assertEqual(
            preview_phone_identity_collisions(
                rows, expected_accounts=3
            )["invalid_account_id_count"], 1
        )

    def test_extra_sensitive_fields_are_rejected_before_reporting(self):
        rows = self._rows()
        rows[0]["email"] = "private@example.com"
        with self.assertRaises(PhoneIdentityInputError):
            preview_phone_identity_collisions(rows, expected_accounts=3)
        for row in (
            {"account_id": 1, "mobile_number": "09123456789", "is_active": 1},
            {"account_id": "1", "mobile_number": "09123456789", "is_active": True},
        ):
            output = preview_phone_identity_collisions([row], expected_accounts=1) \
                if type(row["is_active"]) is bool else None
            if output is not None:
                self.assertFalse(output["preflight_structurally_clean"])
            else:
                with self.assertRaises(PhoneIdentityInputError):
                    preview_phone_identity_collisions([row], expected_accounts=1)

    def test_invalid_count_country_and_empty_snapshot_fail_closed(self):
        for kwargs in (
            {"expected_accounts": 0},
            {"expected_accounts": 50001},
            {"expected_accounts": True},
            {"expected_accounts": 3, "default_country": "XXX"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(PhoneIdentityInputError):
                    preview_phone_identity_collisions(self._rows(), **kwargs)
        with self.assertRaises(PhoneIdentityInputError):
            preview_phone_identity_collisions([], expected_accounts=1)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


class Phase71OfflineFilesTests(SimpleTestCase):
    def fixture(self, folder, mutate_manifest=None):
        rows = Phase71CollisionAuditTests()._rows()
        export = encoded({
            "schema_version": 1,
            "representation": "existing_user_mobile_number",
            "rows": rows,
        })
        manifest = {
            "schema_version": 1,
            "scope": "authorized_isolated_phone_identity_export",
            "authorization_reference": "SYNTHETIC_TEST_APPROVAL",
            "export_sha256": hashlib.sha256(export).hexdigest(),
            "expected_accounts": 3,
            "default_country": "IR",
            "contains_phone_personal_data": True,
            "operation": "canonical_collision_preview_only",
        }
        if mutate_manifest:
            mutate_manifest(manifest)
        root = Path(folder)
        (root / "input.json").write_bytes(export)
        (root / "manifest.json").write_bytes(encoded(manifest))
        return {
            "manifest": str(root / "manifest.json"),
            "input": str(root / "input.json"),
            "acknowledge_sensitive_offline_copy": True,
            "as_json": True,
        }

    def test_requires_both_acknowledgments_before_reading_any_file(self):
        with TemporaryDirectory() as tmp:
            opts = self.fixture(tmp)
            with patch.dict(os.environ, {command.MARKER: ""}):
                with patch.object(Path, "read_bytes", side_effect=AssertionError):
                    with self.assertRaises(CommandError):
                        call_command("audit_phase7_phone_identity", **opts)
            with patch.dict(os.environ, {command.MARKER: command.MARKER_VALUE}):
                opts["acknowledge_sensitive_offline_copy"] = False
                with patch.object(Path, "read_bytes", side_effect=AssertionError):
                    with self.assertRaises(CommandError):
                        call_command("audit_phase7_phone_identity", **opts)

    def test_synthetic_snapshot_has_no_pii_in_stdout_and_no_cutover_permission(self):
        with TemporaryDirectory() as tmp:
            opts = self.fixture(tmp)
            output = StringIO()
            with patch.dict(os.environ, {command.MARKER: command.MARKER_VALUE}):
                call_command("audit_phase7_phone_identity", stdout=output, **opts)
            record = json.loads(output.getvalue())
            self.assertTrue(record["preflight_structurally_clean"])
            self.assertTrue(record["export_checksum_verified"])
            self.assertTrue(
                record["authorization_operator_declared_not_independently_verified"]
            )
            self.assertFalse(record["identity_cutover_authorized"])
            self.assertNotIn("SYNTHETIC_TEST_APPROVAL", output.getvalue())
            self.assertNotIn("09123456789", output.getvalue())

    def test_bad_checksum_and_unexpected_pii_field_block_without_output(self):
        with TemporaryDirectory() as tmp:
            opts = self.fixture(tmp)
            (Path(tmp) / "input.json").write_bytes(b"{}")
            output = StringIO()
            with patch.dict(os.environ, {command.MARKER: command.MARKER_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_phase7_phone_identity", stdout=output, **opts)
            self.assertEqual(output.getvalue(), "")
        with TemporaryDirectory() as tmp:
            opts = self.fixture(tmp, mutate_manifest=lambda x: x.update(email="x"))
            with patch.dict(os.environ, {command.MARKER: command.MARKER_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_phase7_phone_identity", **opts)

    def test_mismatched_expected_accounts_rejected_with_aggregate_only(self):
        with TemporaryDirectory() as tmp:
            opts = self.fixture(tmp, mutate_manifest=lambda m: m.update(
                expected_accounts=4
            ))
            output = StringIO()
            with patch.dict(os.environ, {command.MARKER: command.MARKER_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_phase7_phone_identity", stdout=output, **opts)
            self.assertIn(
                "incomplete_or_mismatched_snapshot_scope",
                output.getvalue()
            )

    def test_duplicate_json_keys_and_nonfinite_numbers_never_echo_input(self):
        for payload in (
            b'{"schema_version":1,"schema_version":1}',
            b'{"expected_accounts":NaN}',
        ):
            with TemporaryDirectory() as tmp:
                opts = self.fixture(tmp)
                (Path(tmp) / "manifest.json").write_bytes(payload)
                with patch.dict(os.environ, {command.MARKER: command.MARKER_VALUE}):
                    with self.assertRaises(CommandError) as ctx:
                        call_command("audit_phase7_phone_identity", **opts)
                self.assertNotIn("expected_accounts", str(ctx.exception))

    def test_auditor_has_no_database_or_otp_delivery_imports(self):
        from loomera.globalization import phone_identity, phone_collision_audit
        import inspect
        for module in (phone_identity, phone_collision_audit, command):
            source = inspect.getsource(module)
            self.assertNotIn("django.db", source)
            self.assertNotIn(".objects.", source)
            self.assertNotIn("send_otp_sms", source)
            self.assertNotIn("cursor.execute(", source)
