"""Phase 7.26 fast, DB-free test of the synthetic authority boundary."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_postgis_writer_authority_rehearsal as model

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_26_EXIT_MATRIX.json"


class Phase726OfflineAuthorityGuards(SimpleTestCase):
    def grant(self):
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase726-offline",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE726_TEST_POSTGIS": "1",
        })

    @staticmethod
    def fake(**updates):
        data = {
            "vendor": "postgresql",
            "settings_dict": {
                "ENGINE": "django.contrib.gis.db.backends.postgis",
                "NAME": "test_phase726_fixture",
            },
        }
        data.update(updates)
        return SimpleNamespace(**data)

    def test_grant_and_test_database_are_mandatory(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                model.verify_ci_test_scope(self.fake())
        with self.grant():
            model.verify_ci_test_scope(self.fake())
            for values in (
                {"vendor": "sqlite"},
                {"settings_dict": {"ENGINE": "django.db.backends.sqlite3",
                                   "NAME": "test_phase726_fixture"}},
                {"settings_dict": {"ENGINE": "django.contrib.gis.db.backends.postgis",
                                   "NAME": "loomera_production"}},
                {"settings_dict": {"ENGINE": "django.contrib.gis.db.backends.postgis",
                                   "NAME": "test_"}},
                {"settings_dict": {"ENGINE": "django.contrib.gis.db.backends.postgis",
                                   "NAME": None}},
            ):
                with self.subTest(values=values), self.assertRaises(RuntimeError):
                    model.verify_ci_test_scope(self.fake(**values))

    def test_revoked_grants_never_pass(self):
        for missing in (
            "GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
            "LOOMERA_PHASE726_TEST_POSTGIS",
        ):
            with self.grant():
                os.environ.pop(missing)
                with self.subTest(missing=missing), self.assertRaises(RuntimeError):
                    model.verify_ci_test_scope(self.fake())

    def test_input_contracts_reject_truthy_or_untrusted_values(self):
        for value in ("master", "", None, 1, "production"):
            with self.subTest(owner=value), self.assertRaises(ValueError):
                model._check_epoch_owner(value, 1)
        for value in (True, 0, -1, 1000001, "1", None):
            with self.subTest(epoch=value), self.assertRaises(ValueError):
                model._check_epoch_owner("old", value)
        for op, digest in (
            ("a" * 31, "b" * 64),
            ("A" * 32, "b" * 64),
            ("a" * 32, "b" * 63),
            ("a" * 32, "B" * 64),
            (None, "b" * 64),
            ("a" * 32, True),
        ):
            with self.subTest(op=str(op), digest=str(digest)), self.assertRaises(ValueError):
                model._check_operation(op, digest)
        model._check_operation("a" * 32, "b" * 64)
        model._check_epoch_owner("promoted", 2)

    def test_every_observation_rejects_auth_session_sms_and_release(self):
        expected = {
            "real_authentication_allowed", "real_otp_issued_or_consumed",
            "real_session_created", "real_sms_sent",
            "global_redis_writers_fenced", "cross_store_atomicity_proven",
            "production_cutover_authorized",
        }
        self.assertTrue(expected.issubset({
            field.name for field in fields(model.SyntheticAuthorityObservation)
        }))
        for status in (
            "synthetic_committed", "same_operation_observed",
            "global_operation_conflict", "synthetic_promoted",
            "synthetic_halted", "stale_writer", "terminal_halt",
        ):
            observation = model.SyntheticAuthorityObservation(
                status, synthetic_database_insert=(status == "synthetic_committed")
            )
            for field in expected:
                self.assertIs(getattr(observation, field), False, field)
            self.assertNotIn("09123456789", repr(observation))

    def test_no_live_api_sms_account_or_auth_wiring(self):
        src = inspect.getsource(model)
        for prohibited in (
            "apps.accounts.models", "apps.api.v1", "login(request",
            "request.session", "sms_ir", "SMSIR", "FLUSHALL", "FLUSHDB",
            ".objects.", "REDIS_URL", "cache.delete(",
        ):
            self.assertNotIn(prohibited, src)
        self.assertIn("SELECT epoch, owner, mode", src)
        self.assertIn("FOR UPDATE", src)
        self.assertIn("ON CONFLICT (operation_id) DO NOTHING", src)
        self.assertIn("transaction.atomic", src)
        for path in (
            "apps/api/v1/auth_otp.py",
            "apps/accounts/models.py",
            "apps/accounts/views.py",
            "apps/api/v1/auth_views.py",
        ):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_postgis_writer_authority_rehearsal", text)
        self.assertNotIn("otp_postgis_writer_authority_rehearsal",
                         (ROOT / "loomera/settings.py").read_text(encoding="utf-8")
                         if (ROOT / "loomera/settings.py").exists() else "")

    def test_exit_matrix_keeps_production_blocked(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "7.26")
        self.assertEqual(data["baseline_main_sha"],
                         "d49a9bb92b1ff1ff0d4fe9786731dfaa1dbaa48b")
        self.assertTrue(data["release_gate"].startswith("BLOCKED"))
        for name in (
            "production_otp_wired", "real_customer_records_accessed",
            "old_master_raw_writers_fenced", "postgres_redis_atomicity_proven",
            "external_sms_exactly_once_proven", "real_session_idempotency_proven",
            "independent_security_signoff", "production_deployment_authorized",
            "deployed",
        ):
            self.assertIs(data[name], False, name)
