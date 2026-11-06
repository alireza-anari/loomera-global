"""Phase 7.2: synthetic identity shadow parity and CURRENT auth/OTP guardrails."""
from __future__ import annotations

import hashlib
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from apps.accounts import forms, views
from apps.accounts.services.sms import format_smsir_mobile, mask_mobile_number
from apps.api.v1 import auth_otp, auth_serializers, auth_views
from apps.main.management.commands import audit_phase7_phone_shadow as command
from loomera.globalization.phone_identity import (
    PhoneIdentityInputError,
    to_candidate_e164,
)
from loomera.globalization.phone_identity_transition import (
    compare_phone_identity_shadow,
)

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/globalization/PHASE7_2_AUTH_CONSUMER_INVENTORY.json"


def identity_fixture():
    source = [
        {"account_id": 101, "mobile_number": "09123456789", "is_active": True},
        {"account_id": 102, "mobile_number": "09123456780", "is_active": False},
        {"account_id": 103, "mobile_number": "09123456781", "is_active": True},
    ]
    shadow = [
        {**row, "canonical_mobile_number": to_candidate_e164(row["mobile_number"])}
        for row in source
    ]
    return source, shadow


def compare(source, shadow, **overrides):
    kwargs = {
        "expected_accounts": 3,
        "expected_active_accounts": 2,
        "expected_inactive_accounts": 1,
    }
    kwargs.update(overrides)
    return compare_phone_identity_shadow(source, shadow, **kwargs)


class Phase72ShadowParityTests(SimpleTestCase):
    def test_clean_reordered_projection_is_not_a_cutover_permission(self):
        before, after = identity_fixture()
        report = compare(list(reversed(before)), list(reversed(after)))
        self.assertTrue(report["shadow_identity_structurally_clean"])
        self.assertEqual(report["stop_reasons"], [])
        self.assertEqual(report["source_accounts_examined"], 3)
        self.assertEqual(report["shadow_accounts_examined"], 3)
        self.assertEqual(report["source_inactive_accounts"], 1)
        for gate in (
            "historical_otp_cache_key_bridge_verified",
            "existing_sessions_transition_verified",
            "phone_number_plan_allocation_verified",
            "shadow_uniqueness_migration_authorized",
            "account_reactivation_authorized",
            "production_identity_cutover_authorized",
        ):
            self.assertFalse(report[gate])
        self.assertEqual(report["database_reads"], 0)
        self.assertEqual(report["writes_performed"], 0)
        for secret in ("09123456789", "+989123456789", '"account_id":', '"canonical_mobile_number":'):
            self.assertNotIn(secret, json.dumps(report))

    def test_iso_style_alias_projection_mismatch_and_shadow_collision_block(self):
        before, after = identity_fixture()
        after[0]["canonical_mobile_number"] = "+989123456780"
        report = compare(before, after)
        self.assertFalse(report["shadow_identity_structurally_clean"])
        self.assertEqual(report["shadow_canonical_mapping_mismatches"], 1)
        self.assertEqual(report["shadow_canonical_alias_collisions"], 1)
        self.assertIn("canonical_alias_collision", report["stop_reasons"])

    def test_e164_is_not_allowed_to_replace_legacy_login_field(self):
        before, after = identity_fixture()
        after[0]["mobile_number"] = "+989123456789"
        report = compare(before, after)
        self.assertFalse(report["shadow_identity_structurally_clean"])
        self.assertEqual(report["legacy_login_identifier_modified_accounts"], 1)
        self.assertIn("legacy_login_identifier_modified", report["stop_reasons"])

    def test_inactive_account_cannot_be_silently_activated(self):
        before, after = identity_fixture()
        after[1]["is_active"] = True
        report = compare(before, after)
        self.assertFalse(report["shadow_identity_structurally_clean"])
        self.assertEqual(report["inactive_accounts_activated_in_shadow"], 1)
        self.assertIn("legacy_account_activation_status_modified", report["stop_reasons"])

    def test_duplicate_missing_and_reassigned_ids_block(self):
        for scenario in ("duplicate", "missing", "reassigned", "unexpected"):
            before, after = identity_fixture()
            if scenario == "duplicate":
                after[1]["account_id"] = after[0]["account_id"]
            if scenario == "missing":
                after.pop()
            if scenario == "reassigned":
                after[0]["account_id"] = 707
            if scenario == "unexpected":
                after.append({**after[0], "account_id": 777})
            with self.subTest(scenario=scenario):
                report = compare(before, after)
                self.assertFalse(report["shadow_identity_structurally_clean"])
                self.assertTrue(report["stop_reasons"])

    def test_deleted_placeholders_legacy_digits_and_collisions_block(self):
        before, after = identity_fixture()
        before[1]["mobile_number"] = "98000000001"  # intentionally anonymized
        after[1]["mobile_number"] = "98000000001"
        after[1]["canonical_mobile_number"] = None
        report = compare(before, after)
        self.assertFalse(report["shadow_identity_structurally_clean"])
        self.assertEqual(report["source_unparseable_phone_values"], 1)
        self.assertEqual(report["source_noncanonical_legacy_storage"], 1)
        before, after = identity_fixture()
        before[1]["mobile_number"] = "۰۹۱۲۳۴۵۶۷۸۹"
        after[1]["mobile_number"] = "۰۹۱۲۳۴۵۶۷۸۹"
        after[1]["canonical_mobile_number"] = "+989123456789"
        report = compare(before, after)
        self.assertFalse(report["shadow_identity_structurally_clean"])
        self.assertGreater(report["source_canonical_alias_collisions"], 0)
        self.assertGreater(report["source_noncanonical_legacy_storage"], 0)

    def test_invalid_row_field_status_bool_id_and_count_fail_closed(self):
        before, after = identity_fixture()
        after[0]["email"] = "private@example.com"
        with self.assertRaises(PhoneIdentityInputError):
            compare(before, after)
        before, after = identity_fixture()
        after[1]["is_active"] = 0
        with self.assertRaises(PhoneIdentityInputError):
            compare(before, after)
        before, after = identity_fixture()
        after[0]["account_id"] = True
        self.assertGreater(compare(before, after)["shadow_invalid_account_ids"], 0)
        for overrides in (
            {"expected_accounts": 0},
            {"expected_accounts": True},
            {"expected_active_accounts": True},
            {"expected_active_accounts": 3},
        ):
            before, after = identity_fixture()
            with self.subTest(overrides=overrides):
                with self.assertRaises(PhoneIdentityInputError):
                    compare(before, after, **overrides)

    def test_declared_scope_cannot_hide_missing_active_or_inactive_accounts(self):
        before, after = identity_fixture()
        result = compare(before, after, expected_active_accounts=1,
                         expected_inactive_accounts=2)
        self.assertFalse(result["shadow_identity_structurally_clean"])
        self.assertIn("declared_account_scope_or_status_mismatch", result["stop_reasons"])
        before, after = identity_fixture()
        after[0]["is_active"] = False
        after[1]["is_active"] = True
        result = compare(before, after)
        self.assertFalse(result["shadow_identity_structurally_clean"])
        self.assertEqual(result["account_status_changed_accounts"], 2)

    def test_anchored_inventory_matches_existing_auth_consumers(self):
        manifest = json.loads(INVENTORY.read_text(encoding="utf-8"))
        self.assertEqual(manifest["phase"], "7.2")
        self.assertFalse(manifest["dynamic_completeness"])
        anchors = manifest["reviewed"]
        self.assertGreaterEqual(len(anchors), 28)
        cache = {}
        for entry in anchors:
            path = entry["path"]
            if path not in cache:
                cache[path] = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path, anchor=entry["anchor"]):
                self.assertIn(entry["anchor"], cache[path])


class Phase72LiveAuthContractTests(SimpleTestCase):
    def test_api_otp_and_smsir_still_use_legacy_mobile_without_rekey(self):
        mobile = "09123456789"
        for alias in (mobile, "+989123456789", "00989123456789"):
            valid, normalized, _ = auth_serializers.validate_mobile_for_auth(alias)
            self.assertTrue(valid)
            self.assertEqual(normalized, mobile)
            self.assertEqual(format_smsir_mobile(alias), "9123456789")
            self.assertEqual(to_candidate_e164(alias), "+989123456789")
        self.assertEqual(mask_mobile_number(mobile), "0912***789")
        self.assertEqual(auth_otp.mask_mobile_for_api(mobile), "0912***789")
        self.assertEqual(auth_serializers.public_auth_policy()["phone_region"], "IR")
        self.assertFalse(auth_serializers.validate_mobile_for_auth("+4915123456789")[0])

    def test_web_session_and_rate_limit_namespace_remain_legacy(self):
        session = views._create_verification_session(
            mobile_number="+989123456789", code="12345",
            signup_kind="customer", remember_password=False,
        )
        self.assertEqual(session["mobile_number"], "09123456789")
        self.assertEqual(session["otp_attempts"], 0)
        self.assertEqual(session["otp_verified"], False)
        self.assertEqual(session["otp_purpose"], views.OTP_PURPOSE_SIGNUP)
        self.assertEqual(
            views._otp_cooldown_cache_key(purpose="signup", mobile_number="+989123456789"),
            views._otp_cooldown_cache_key(purpose="signup", mobile_number="09123456789"),
        )

    def test_api_hash_and_cache_keys_are_mobile_bound_not_implicitly_remapped(self):
        mobile = "09123456789"
        purpose = auth_otp.API_AUTH_OTP_PURPOSE_LOGIN
        old = auth_otp.hash_otp_code(
            mobile_number=mobile, code="123456", purpose=purpose
        )
        self.assertNotEqual(
            old,
            auth_otp.hash_otp_code(
                mobile_number="+989123456789", code="123456", purpose=purpose
            ),
        )
        self.assertNotEqual(
            auth_otp.otp_record_cache_key(purpose=purpose, mobile_number=mobile),
            auth_otp.otp_record_cache_key(
                purpose=purpose, mobile_number="+989123456789"
            ),
        )
        self.assertNotEqual(
            auth_otp.otp_resend_cache_key(purpose=purpose, mobile_number=mobile),
            auth_otp.otp_resend_cache_key(
                purpose=purpose, mobile_number="+989123456789"
            ),
        )

    def test_login_uses_exact_existing_form_username(self):
        request = RequestFactory().post("/accounts/login/", {
            "mobile_number": "09123456789", "password": "test-password",
        })
        form = SimpleNamespace(
            is_valid=lambda: True,
            cleaned_data={
                "mobile_number": "09123456789", "password": "test-password",
            },
        )
        with (
            patch.object(views.LoginUserView, "form_class", return_value=form),
            patch.object(views, "authenticate", return_value=None) as authenticate,
            patch.object(views.messages, "error"),
            patch.object(views, "render", return_value=HttpResponse("invalid")),
        ):
            response = views.LoginUserView().post(request)
        self.assertEqual(response.status_code, 200)
        authenticate.assert_called_once_with(
            username="09123456789", password="test-password",
        )

    def test_password_reset_looks_up_unchanged_legacy_username(self):
        request = RequestFactory().post("/accounts/remember/", {
            "mobile_number": "09123456789",
        })
        fake_form = SimpleNamespace(
            is_valid=lambda: True,
            cleaned_data={"mobile_number": "09123456789"},
        )
        user = SimpleNamespace(mobile_number="09123456789")
        expected_response = HttpResponse("verification")
        with (
            patch.object(views, "RememberPasswordForm", return_value=fake_form),
            patch.object(views.CustomUser.objects, "get", return_value=user) as get_user,
            patch.object(views, "_send_verification_code",
                         return_value=expected_response) as send,
        ):
            response = views.RememberPasswordView().post(request)
        self.assertIs(response, expected_response)
        get_user.assert_called_once_with(mobile_number="09123456789")
        self.assertEqual(send.call_args.kwargs["purpose"],
                         views.OTP_PURPOSE_PASSWORD_RESET)

    def test_inactive_role_reuse_does_not_bypass_admin_or_conflicting_role_guards(self):
        def check(existing, must_reuse):
            form = SimpleNamespace(
                cleaned_data={"mobile_number": "09123456789"},
                instance=SimpleNamespace(pk=None),
                signup_kind="customer",
            )
            with patch.object(forms.CustomUser.objects, "filter") as filter_user:
                filter_user.return_value.first.return_value = existing
                if must_reuse:
                    result = forms.BaseSignupForm.clean_mobile_number(form)
                    self.assertEqual(result, "09123456789")
                    self.assertIs(form._reuse_user, existing)
                    self.assertIs(form.instance, existing)
                else:
                    with self.assertRaises(ValidationError):
                        forms.BaseSignupForm.clean_mobile_number(form)
        check(SimpleNamespace(is_active=False, is_admin=False), True)
        check(SimpleNamespace(is_active=True, is_admin=False), False)
        check(SimpleNamespace(is_active=False, is_admin=True), False)
        check(SimpleNamespace(
            is_active=False, is_admin=False, stylist=SimpleNamespace()
        ), False)

    def test_api_authentication_only_queries_active_legacy_identity(self):
        fake_user = SimpleNamespace(pk=1, mobile_number="09123456789")
        with patch.object(auth_views, "get_user_model") as get_model:
            qs = get_model.return_value.objects.filter.return_value.order_by.return_value
            qs.first.return_value = fake_user
            found = auth_views.ApiOtpVerifyAPIView()._get_active_user_by_mobile(
                "09123456789"
            )
            get_model.return_value.objects.filter.assert_called_once_with(
                mobile_number="09123456789", is_active=True
            )
        self.assertIs(found, fake_user)


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class Phase72OfflineFilesTests(SimpleTestCase):
    def _fixture(self, directory, modify_manifest=None):
        source, shadow = identity_fixture()
        before = _json_bytes({
            "schema_version": 1,
            "representation": "existing_user_mobile_number",
            "rows": source,
        })
        after = _json_bytes({
            "schema_version": 1,
            "representation": "existing_user_plus_canonical_shadow",
            "rows": shadow,
        })
        manifest = {
            "schema_version": 1,
            "operation": "compare_phone_e164_shadow_only",
            "scope": "authorized_isolated_phone_identity_export",
            "authorization_reference": "SYNTHETIC_FIXTURE_ONLY",
            "source_sha256": hashlib.sha256(before).hexdigest(),
            "shadow_sha256": hashlib.sha256(after).hexdigest(),
            "expected_accounts": 3,
            "expected_active_accounts": 2,
            "expected_inactive_accounts": 1,
            "default_country": "IR",
            "contains_phone_personal_data": True,
        }
        if modify_manifest:
            modify_manifest(manifest)
        root = Path(directory)
        for name, payload in (
            ("manifest.json", _json_bytes(manifest)),
            ("before.json", before), ("after.json", after),
        ):
            (root / name).write_bytes(payload)
        return {
            "manifest": str(root / "manifest.json"),
            "source": str(root / "before.json"),
            "shadow": str(root / "after.json"),
            "acknowledge_sensitive_offline_copy": True,
            "as_json": True,
        }

    def test_missing_either_ack_does_not_open_any_file(self):
        with TemporaryDirectory() as root:
            args = self._fixture(root)
            with patch.dict(os.environ, {command.ACK_ENV: ""}):
                with patch.object(Path, "read_bytes", side_effect=AssertionError):
                    with self.assertRaises(CommandError):
                        call_command("audit_phase7_phone_shadow", **args)
            args["acknowledge_sensitive_offline_copy"] = False
            with patch.dict(os.environ, {command.ACK_ENV: command.ACK_VALUE}):
                with patch.object(Path, "read_bytes", side_effect=AssertionError):
                    with self.assertRaises(CommandError):
                        call_command("audit_phase7_phone_shadow", **args)

    def test_files_with_exact_hash_and_full_parity_do_not_authorize_cutover(self):
        with TemporaryDirectory() as root:
            args = self._fixture(root)
            output = StringIO()
            with patch.dict(os.environ, {command.ACK_ENV: command.ACK_VALUE}):
                call_command("audit_phase7_phone_shadow", stdout=output, **args)
            report = json.loads(output.getvalue())
            self.assertTrue(report["shadow_identity_structurally_clean"])
            self.assertTrue(report["source_shadow_byte_hashes_verified"])
            self.assertFalse(report["production_identity_cutover_authorized"])
            self.assertTrue(
                report["authorization_operator_declared_not_independently_verified"]
            )
            self.assertNotIn("09123456789", output.getvalue())
            self.assertNotIn("SYNTHETIC_FIXTURE_ONLY", output.getvalue())

    def test_sha_tamper_duplicate_json_keys_and_extra_pii_rejected_without_echo(self):
        with TemporaryDirectory() as root:
            args = self._fixture(root)
            (Path(root) / "after.json").write_bytes(b"{}")
            output = StringIO()
            with patch.dict(os.environ, {command.ACK_ENV: command.ACK_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_phase7_phone_shadow", stdout=output, **args)
            self.assertEqual(output.getvalue(), "")
        with TemporaryDirectory() as root:
            args = self._fixture(root)
            (Path(root) / "manifest.json").write_bytes(
                b'{"schema_version":1,"schema_version":1}'
            )
            with patch.dict(os.environ, {command.ACK_ENV: command.ACK_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_phase7_phone_shadow", **args)
        with TemporaryDirectory() as root:
            args = self._fixture(root, modify_manifest=lambda m: m.update(
                email="sensitive@example.com"
            ))
            with patch.dict(os.environ, {command.ACK_ENV: command.ACK_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_phase7_phone_shadow", **args)

    def test_incorrect_declared_active_counts_fail_nonzero_with_aggregates(self):
        with TemporaryDirectory() as root:
            args = self._fixture(root, modify_manifest=lambda m: m.update(
                expected_active_accounts=1, expected_inactive_accounts=2
            ))
            output = StringIO()
            with patch.dict(os.environ, {command.ACK_ENV: command.ACK_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_phase7_phone_shadow", stdout=output, **args)
            result = json.loads(output.getvalue())
            self.assertFalse(result["shadow_identity_structurally_clean"])
            self.assertEqual(
                result["stop_reasons"], ["declared_account_scope_or_status_mismatch"]
            )

    def test_pure_components_have_no_database_or_delivery_actions(self):
        from loomera.globalization import phone_identity_transition
        import inspect
        for module in (phone_identity_transition, command):
            text = inspect.getsource(module)
            for forbidden in (
                "django.db", ".objects.", "cursor.execute(", "send_otp_sms",
                "cache.set(", "transaction.atomic(", "login(request",
            ):
                self.assertNotIn(forbidden, text)
