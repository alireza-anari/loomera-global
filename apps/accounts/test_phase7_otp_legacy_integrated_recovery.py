"""Phase 7.23 offline guards for synthetic issue/consume/outage integration."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_legacy_integrated_recovery_rehearsal as integrated
from loomera.globalization import otp_legacy_issue_rate_rehearsal as issuer

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "a" * 32
MOBILE = "09123456789"
IP_TAG = "synthetic_ip_01"
DIGEST = "a" * 40


class FakeCache:
    key_prefix = issuer.PREFIX + FIXTURE
    version = 1
    _server = issuer.REDIS_URL

    def make_key(self, logical):
        return f"{self.key_prefix}:1:{logical}"


class FakeRedis:
    connection_pool = SimpleNamespace(connection_kwargs={
        "host": "127.0.0.1", "port": 6414, "db": 15,
    })


class Phase723IntegratedRecoveryOfflineTests(SimpleTestCase):
    def opts(self):
        return {
            "fixture_id": FIXTURE, "mobile": MOBILE, "ip_tag": IP_TAG,
            "now_ts": 1050, "submitted_digest": DIGEST,
        }

    def run_guard(self, cache=None, raw=None, **changes):
        options = self.opts()
        options.update(changes)
        return integrated.attempt_synthetic_integrated_verify(
            FakeCache() if cache is None else cache,
            FakeRedis() if raw is None else raw,
            **options,
        )

    @staticmethod
    def grant():
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase723-offline",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE722_TEST_REDIS": "1",
            "LOOMERA_PHASE723_TEST_REDIS": "1",
        })

    def test_missing_phase723_grant_refuses_before_network(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE723_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.run_guard()

    def test_phase722_grant_and_exact_physical_key_are_still_required(self):
        with self.grant():
            with patch.dict(os.environ, {"LOOMERA_PHASE722_TEST_REDIS": "0"}):
                with self.assertRaises(RuntimeError):
                    self.run_guard()
            wrong = FakeCache()
            wrong.key_prefix = issuer.PREFIX + "b" * 32
            with self.assertRaises(RuntimeError):
                self.run_guard(cache=wrong)
            wrong_db = SimpleNamespace(connection_pool=SimpleNamespace(
                connection_kwargs={"host": "127.0.0.1", "port": 6414, "db": 14},
            ))
            with self.assertRaises(RuntimeError):
                self.run_guard(raw=wrong_db)
            for item in (
                {"fixture_id": "bad"},
                {"mobile": "+989123456789"},
                {"ip_tag": "203.0.113.1"},
                {"submitted_digest": "plaintext"},
                {"now_ts": True},
            ):
                with self.subTest(item=item), self.assertRaises(ValueError):
                    self.run_guard(**item)
            with self.assertRaises(TypeError):
                self.run_guard(on_watched_read="fake")

    def test_all_result_classes_retain_hard_no_auth_and_no_retry_flags(self):
        flags = [
            f.name for f in fields(integrated.SyntheticIntegratedVerifyEvidence)
            if f.name not in (
                "status", "attempts_remaining",
                "mutation_confirmed", "synthetic_record_consumed",
            )
        ]
        for result in (
            integrated.SyntheticIntegratedVerifyEvidence(
                "synthetic_single_winner", mutation_confirmed=True,
                synthetic_record_consumed=True,
            ),
            integrated.SyntheticIntegratedVerifyEvidence(
                "synthetic_invalid_attempt", attempts_remaining=4,
                mutation_confirmed=True,
            ),
            integrated.SyntheticIntegratedVerifyEvidence(
                "synthetic_exhausted", attempts_remaining=0,
                mutation_confirmed=True,
            ),
            integrated.SyntheticIntegratedVerifyEvidence("backend_unavailable"),
            integrated.SyntheticIntegratedVerifyEvidence(
                "concurrent_modification_conflict",
            ),
        ):
            for field in flags:
                self.assertFalse(getattr(result, field), field)
            for secret in (MOBILE, IP_TAG, DIGEST, FIXTURE, "123456"):
                self.assertNotIn(secret, repr(result))

    def test_watch_precedes_raw_get_and_only_one_transaction(self):
        src = inspect.getsource(integrated.attempt_synthetic_integrated_verify)
        self.assertLess(src.index("pipe.watch(record_key)"),
                        src.index("pipe.get(record_key)"))
        self.assertLess(src.index("pipe.get(record_key)"),
                        src.index("pipe.multi()"))
        self.assertIn("pipe.delete(record_key)", src)
        self.assertIn("pipe.set(record_key, payload, xx=True, keepttl=True)", src)
        self.assertIn("_confirmed_delete(pipe.execute())", src)
        self.assertIn("_confirmed_set(pipe.execute())", src)
        self.assertIn("except WatchError:", src)
        for dangerous in (
            "cache.get(", "cache.set(", "cache.delete(",
            "flushdb(", "flushall(", "redis_client.eval(",
        ):
            self.assertNotIn(dangerous, src)

    def test_issuer_and_verifier_use_exact_same_scope_and_key(self):
        src = inspect.getsource(integrated.attempt_synthetic_integrated_verify)
        self.assertIn("validate_synthetic_scope(", src)
        self.assertIn("record_key, _, _, _ =", src)
        self.assertIn("_legacy_record_valid(", src)
        self.assertIn("secrets.compare_digest(", src)
        self.assertIn("_serialized(cache, updated)", src)
        self.assertIn("automatic_retry_authorized: bool = False",
                      inspect.getsource(integrated))

    def test_no_live_code_connected_to_synthetic_candidate(self):
        src = inspect.getsource(integrated)
        for forbidden in (
            "apps.api.v1.auth_otp", "apps.accounts.models",
            "django.db", "django.contrib.auth", "request.session",
            "login(request", ".objects.", "send_otp_sms(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, src)
        for p in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            live = (ROOT / p).read_text(encoding="utf-8")
            self.assertNotIn("otp_legacy_integrated_recovery_rehearsal", live)
            self.assertNotIn("attempt_synthetic_integrated_verify", live)
        live_auth = (ROOT / "apps/api/v1/auth_otp.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("record = _cache_get(key)", live_auth)
        self.assertIn(
            "secrets.compare_digest(expected_hash, submitted_hash)", live_auth,
        )
        self.assertIn("cache.delete(key)", live_auth)

    def test_real_stop_restart_exact_test_only_docker_guard(self):
        shell = (ROOT / "tests/phase7_redis_legacy_issue_rate_ci.sh").read_text(
            encoding="utf-8"
        )
        real = (ROOT / "tests/phase7_legacy_integrated_recovery_test.py").read_text(
            encoding="utf-8"
        )
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for required in (
            "LOOMERA_PHASE723_TEST_REDIS", "LOOMERA_PHASE723_CONTAINER",
            "--label loomera.phase723=synthetic",
            "python tests/phase7_legacy_integrated_recovery_test.py",
            "127.0.0.1:6414:6379", "trap cleanup EXIT",
        ):
            self.assertIn(required, shell)
        for required in (
            "test_physical_test_container_shutdown_fail_closed_and_aof_resume",
            "test_lost_issue_ack_never_reissues_or_double_charges_on_retry",
            "test_lost_consume_ack_does_not_grant_session_even_if_deleted",
            "test_lost_wrong_attempt_ack_must_not_auto_retry",
            "test_reissue_racing_stale_watched_verification_aborts_old_code",
            "test_two_verifiers_from_same_issued_record_have_one_winner",
            'json.loads(labels).get("loomera.phase723")',
        ):
            self.assertIn(required, real)
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_legacy_integrated_recovery",
            ci,
        )
        for dangerous in ("FLUSHALL", "FLUSHDB", "docker system prune"):
            self.assertNotIn(dangerous, shell)

    def test_phase723_matrix_keeps_release_blocked(self):
        m = json.loads((
            ROOT / "docs/globalization/PHASE7_23_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(m["phase"], "7.23")
        self.assertEqual(
            m["baseline_main_sha"],
            "08496038f90bdb1cd4b2b04f2f3be6358d12f98c",
        )
        for name in (
            "live_auth_wired", "live_issue_and_consume_race_fixed",
            "real_otp_or_sms_sent", "production_rollout_authorized",
            "old_master_globally_fenced", "multihost_consensus_proven",
            "cross_store_session_atomicity_proven",
            "retry_idempotency_guaranteed", "real_user_data_accessed",
            "owner_security_signoff", "deployed",
        ):
            self.assertIs(m[name], False, name)
        self.assertIn("BLOCKED", m["release_gate"])
