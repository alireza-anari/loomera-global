"""Phase 7.29 strict Fast/offline guardrails; no PostGIS or Redis needed."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_postgis_outbox_rehearsal as outbox

ROOT = Path(__file__).resolve().parents[2]


class Phase729OfflineOutboxGuards(SimpleTestCase):
    @staticmethod
    def fake_client():
        return SimpleNamespace(connection_pool=SimpleNamespace(
            connection_kwargs={
                "host": "127.0.0.1", "port": 6428, "db": 15,
                "username": "phase728_gateway",
            },
        ))

    @staticmethod
    def grant():
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "729",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE726_TEST_POSTGIS": "1",
            "LOOMERA_PHASE728_TEST_REDIS": "1",
            "LOOMERA_PHASE729_TEST_OUTBOX": "1",
        })

    def test_scope_refuses_missing_phase729_grant_before_sql(self):
        with self.grant():
            with patch.dict(os.environ, {"LOOMERA_PHASE729_TEST_OUTBOX": "0"}):
                with self.assertRaisesRegex(RuntimeError, "phase729_explicit"):
                    outbox.SyntheticPostGISOutboxRehearsal._scope(
                        SimpleNamespace(
                            client=self.fake_client(), fixture_id="a" * 32,
                        )
                    )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "phase729_explicit"):
                outbox.SyntheticPostGISOutboxRehearsal._scope(
                    SimpleNamespace(
                        client=self.fake_client(), fixture_id="a" * 32,
                    )
                )

    def test_positive_scope_does_not_weaken_phase728_guards(self):
        from loomera.globalization.otp_restricted_writer_gateway_rehearsal import (
            validate_gateway_scope,
        )
        with self.grant():
            self.assertEqual(
                validate_gateway_scope(self.fake_client(), "a" * 32),
                "loomera:phase728:restricted-gateway-only:" + "a" * 32 + ":",
            )

    def test_bounded_outcome_never_grants_live_auth_or_release(self):
        for status in (
            "synthetic_intent_committed", "synthetic_marker_observed",
            "inflight_requires_manual_review", "marker_collision_quarantined",
            "already_observed_no_retry", "stale_writer",
            "pending_marker_absent_no_repair",
        ):
            record = outbox.SyntheticOutboxObservation(
                status,
                synthetic_redis_marker_written=(status == "synthetic_marker_observed"),
            )
            for field in (
                "real_authentication_allowed",
                "real_otp_issue_or_consume_allowed",
                "real_session_created", "real_sms_sent",
                "cross_store_atomicity_proven", "all_redis_ingress_fenced",
                "production_release_authorized",
            ):
                self.assertIs(getattr(record, field), False, field)
        self.assertIn("production_release_authorized", {
            field.name for field in fields(outbox.SyntheticOutboxObservation)
        })

    def test_source_requires_sql_first_committed_arm_and_no_retry(self):
        source = inspect.getsource(outbox)
        for marker in (
            "LOOMERA_PHASE729_TEST_OUTBOX",
            "validate_gateway_scope", "verify_ci_test_scope",
            "self.authority.claim(", "transaction.atomic",
            '"inflight"', "self.client.set(key, fingerprint, nx=True)",
            '"quarantined"', "inflight_requires_manual_review",
            "inspect_read_only", "FOR UPDATE",
        ):
            self.assertIn(marker, source)
        for forbidden in (
            "FLUSHALL", "FLUSHDB", "EVAL", "apps.api.v1",
            "apps.accounts.models", "request.session", "login(request",
            "cache.delete(", "sms_ir", "SMSIR", "redis://127.0.0.1:6379",
        ):
            self.assertNotIn(forbidden, source)

    def test_cannot_load_synthetic_outbox_into_live_auth_or_settings(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
            "loomera/settings.py", "loomera/settings/production.py",
        ):
            f = ROOT / path
            if f.exists():
                self.assertNotIn(
                    "otp_postgis_outbox_rehearsal",
                    f.read_text(encoding="utf-8"),
                )

    def test_real_postgis_suite_contains_all_cross_store_negative_proofs(self):
        source = (
            ROOT / "apps/accounts/test_phase7_postgis_mandatory_ingress.py"
        ).read_text(encoding="utf-8")
        for expected in (
            "test_phase729_commit_intent_before_any_redis_effect",
            "test_phase729_rollback_discards_sql_intent_and_ledger",
            "test_phase729_lost_ack_after_physical_set_never_retries",
            "test_phase729_failure_before_redis_call_remains_inflight",
            "test_phase729_preexisting_foreign_marker_is_quarantined",
            "test_phase729_two_sql_workers_only_one_can_dispatch",
            "test_phase729_stale_or_halted_authority_denies_pending_dispatch",
        ):
            self.assertIn(expected, source)

    def test_ci_runs_both_fast_and_physical_with_scoped_grants(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        runner = (
            ROOT / "tests/phase7_postgis_restricted_writer_ci.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_outbox_guards",
            workflow,
        )
        self.assertIn("LOOMERA_PHASE729_TEST_OUTBOX", workflow)
        self.assertIn("LOOMERA_PHASE729_TEST_OUTBOX", runner)
        self.assertIn(
            "apps.accounts.test_phase7_postgis_mandatory_ingress",
            runner,
        )
        for forbidden in ("FLUSHALL", "FLUSHDB", "docker system prune"):
            self.assertNotIn(forbidden, runner)

    def test_exit_matrix_stays_release_blocked(self):
        data = json.loads((
            ROOT / "docs/globalization/PHASE7_29_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "7.29")
        self.assertEqual(
            data["baseline_main_sha"],
            "913f00826ccb2f54a2e58c9dd093aa0c738e5245",
        )
        for field in (
            "real_auth_code_changed", "live_otp_outbox_connected",
            "cross_store_atomicity", "automatic_ambiguous_replay_safe",
            "redis_ingress_globally_mandatory", "external_sms_exactly_once",
            "real_session_account_consistency", "security_owner_approval",
            "production_deployment_authorized", "deployed",
        ):
            self.assertIs(data[field], False, field)
        self.assertTrue(data["release_gate"].startswith("BLOCKED"))
