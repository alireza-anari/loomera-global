"""Phase 7.21 offline CI policy, strict scope and blocked-release guards."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_legacy_state_machine_rehearsal as sm

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "a" * 32
LOGICAL = "record:app_login:09123456789"


class FakeCache:
    key_prefix = sm.PREFIX + FIXTURE
    version = 1
    _server = sm.REDIS_URL

    def make_key(self, logical_key):
        return f"{self.key_prefix}:1:{logical_key}"


class FakeRedis:
    connection_pool = SimpleNamespace(connection_kwargs={
        "host": "127.0.0.1", "port": 6413, "db": 15,
    })


class Phase721PerRecordStateMachineOfflineTests(SimpleTestCase):
    def scope(self, cache=None, client=None, **changes):
        opts = {"fixture_id": FIXTURE, "logical_key": LOGICAL}
        opts.update(changes)
        return sm.validate_scope(
            FakeCache() if cache is None else cache,
            FakeRedis() if client is None else client,
            **opts,
        )

    def test_explicit_grant_required_before_any_backend_io(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE721_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.scope()

    def test_accepts_exact_local_fake_fixture_only_with_test_grant(self):
        with patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase721-offline",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE721_TEST_REDIS": "1",
        }):
            self.assertEqual(self.scope(), f"{sm.PREFIX}{FIXTURE}:1:{LOGICAL}")
            for kw in (
                {"fixture_id": True},
                {"fixture_id": "bad"},
                {"logical_key": "record:app_login:+989123456789"},
                {"logical_key": "record:password_reset:09123456789"},
            ):
                with self.subTest(kw=kw), self.assertRaises(ValueError):
                    self.scope(**kw)

    def test_reject_remote_ports_db_namespace_and_text_decoding(self):
        env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase721-offline",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE721_TEST_REDIS": "1",
        }
        with patch.dict(os.environ, env):
            for name, value in (
                ("key_prefix", sm.PREFIX + "b" * 32),
                ("version", False),
                ("version", 2),
                ("_server", "redis://127.0.0.1:6379/15"),
                ("_server", "redis://remote.invalid:6413/15"),
            ):
                with self.subTest(name=name, value=value):
                    c = FakeCache()
                    setattr(c, name, value)
                    with self.assertRaises(RuntimeError):
                        self.scope(cache=c)
            for name, value in (
                ("host", "remote.invalid"),
                ("port", 6379),
                ("port", True),
                ("db", 0),
                ("db", False),
                ("decode_responses", True),
            ):
                with self.subTest(name=name, value=value):
                    kw = dict(FakeRedis.connection_pool.connection_kwargs)
                    kw[name] = value
                    client = SimpleNamespace(connection_pool=SimpleNamespace(
                        connection_kwargs=kw,
                    ))
                    with self.assertRaises(RuntimeError):
                        self.scope(client=client)

    def test_legacy_type_purpose_identity_clock_and_attempt_invariants(self):
        row = {
            "purpose": "app_login", "mobile_number": "09123456789",
            "code_hash": "a" * 40,
            "created_at": 1000, "expires_at": 1120,
            "attempts": 1, "max_attempts": 5, "verified": False,
        }
        self.assertTrue(sm._legacy_record_valid(row, LOGICAL, 1050))
        for name, value in (
            ("purpose", "password_reset"),
            ("mobile_number", "09123456780"),
            ("mobile_number", True),
            ("code_hash", "123456"),
            ("code_hash", "A" * 40),
            ("created_at", True),
            ("created_at", 1051),
            ("expires_at", False),
            ("expires_at", 1049),
            ("attempts", -1),
            ("attempts", True),
            ("attempts", 5),
            ("max_attempts", 0),
            ("max_attempts", 11),
            ("max_attempts", False),
            ("verified", True),
        ):
            with self.subTest(name=name, value=value):
                self.assertFalse(sm._legacy_record_valid(
                    {**row, name: value}, LOGICAL, 1050,
                ))
        self.assertFalse(sm._legacy_record_valid(
            {"purpose": "app_login"}, LOGICAL, 1050,
        ))
        self.assertFalse(sm._legacy_record_valid("not a dict", LOGICAL, 1050))

    def test_exec_reply_must_be_strict_single_confirmed_mutation(self):
        self.assertTrue(sm._confirmed_delete([1]))
        for reply in (None, [], [0], [True], [2], [1, 1], [1.0]):
            with self.subTest(reply=reply):
                self.assertFalse(sm._confirmed_delete(reply))
        self.assertTrue(sm._confirmed_set([True]))
        for reply in (None, [], [False], [1], [True, True], ["OK"]):
            with self.subTest(reply=reply):
                self.assertFalse(sm._confirmed_set(reply))

    def test_no_phase21_result_can_grant_production_auth(self):
        denied = [
            f.name for f in fields(sm.SyntheticOtpTransition)
            if f.name not in (
                "status", "attempts_remaining",
                "mutation_confirmed", "synthetic_challenge_consumed",
            )
        ]
        for result in (
            sm.SyntheticOtpTransition("synthetic_single_winner",
                                      mutation_confirmed=True,
                                      synthetic_challenge_consumed=True),
            sm.SyntheticOtpTransition("synthetic_invalid_attempt",
                                      attempts_remaining=4, mutation_confirmed=True),
            sm.SyntheticOtpTransition("synthetic_exhausted",
                                      attempts_remaining=0, mutation_confirmed=True),
            sm.SyntheticOtpTransition("concurrent_modification_conflict"),
            sm.SyntheticOtpTransition("backend_unavailable"),
        ):
            for field in denied:
                self.assertIs(getattr(result, field), False, field)
            for secret in ("09123456789", "123456", "a" * 40):
                self.assertNotIn(secret, repr(result))

    def test_watch_get_cas_reuses_one_pipeline_no_unsafe_fallback(self):
        src = inspect.getsource(sm.apply_synthetic_otp_transition)
        self.assertLess(src.index("pipe.watch(physical)"),
                        src.index("pipe.get(physical)"))
        self.assertLess(src.index("pipe.get(physical)"),
                        src.index("pipe.multi()"))
        self.assertIn("pipe.delete(physical)", src)
        self.assertIn("pipe.set(physical, encoded, xx=True, keepttl=True)", src)
        self.assertIn("pipe.execute()", src)
        self.assertIn("except WatchError:", src)
        for forbidden in (
            "cache.get(", "cache.set(", "cache.delete(",
            "redis_client.eval(", "flushdb(", "flushall(",
        ):
            self.assertNotIn(forbidden, src)

    def test_no_account_orm_sms_sessions_or_live_auth_imports(self):
        src = inspect.getsource(sm)
        for forbidden in (
            "apps.accounts.models", "apps.api.v1.auth_otp",
            "django.db", "django.contrib.auth",
            "request.session", "login(request",
            ".objects.", "send_otp_sms(",
        ):
            self.assertNotIn(forbidden, src)
        for path in (
            "apps/api/v1/auth_otp.py",
            "apps/api/v1/auth_views.py",
            "apps/accounts/views.py",
            "apps/accounts/models.py",
        ):
            data = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_legacy_state_machine_rehearsal", data)
            self.assertNotIn("apply_synthetic_otp_transition", data)

    def test_live_legacy_get_compare_delete_still_unfixed(self):
        src = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        self.assertIn("record = _cache_get(key)", src)
        self.assertIn(
            "secrets.compare_digest(expected_hash, submitted_hash)", src,
        )
        self.assertIn("cache.delete(key)", src)
        self.assertIn("return True", src)

    def test_fixed_docker_isolation_real_concurrency_and_negative_cases(self):
        shell = (ROOT / "tests/phase7_redis_legacy_state_machine_ci.sh").read_text()
        tests = (ROOT / "tests/phase7_legacy_state_machine_test.py").read_text()
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        for anchor in (
            "GITHUB_ACTIONS", "LOOMERA_PHASE721_TEST_REDIS",
            "127.0.0.1:6413:6379", "redis:7.4-alpine", "trap cleanup EXIT",
            "docker rm -f", "docker volume rm", "docker network rm",
        ):
            self.assertIn(anchor, shell)
        for anchor in (
            "test_two_correct_workers_one_consumes_other_conflicts",
            "test_two_wrong_workers_increment_once_with_optimistic_conflict",
            "test_correct_and_wrong_worker_race_never_both_commit",
            "test_last_wrong_and_correct_race_never_both_commit",
            "test_same_byte_aba_reissue_fences_wrong_attempt_and_correct_consume",
            "test_replaced_generation_not_consumed_or_charged_old_attempt",
            "test_lost_exec_response_never_returns_success_or_retry",
        ):
            self.assertIn(anchor, tests)
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_legacy_state_machine",
            workflow,
        )
        self.assertIn("bash tests/phase7_redis_legacy_state_machine_ci.sh",
                      workflow)
        for forbidden in ("FLUSHALL", "FLUSHDB", "docker system prune"):
            self.assertNotIn(forbidden, shell)

    def test_release_matrix_keeps_every_live_change_blocked(self):
        matrix = json.loads((ROOT / "docs/globalization/PHASE7_21_EXIT_MATRIX.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.21")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "2e6f2b9933479c53d94b5fffaeddbabdbd95771b",
        )
        for flag in (
            "real_otp_atomicity_fixed", "real_otp_attempts_fixed",
            "real_otp_issuance_and_rates_fixed",
            "live_auth_or_sessions_rewired", "legacy_sessions_drain_completed",
            "old_master_globally_fenced", "multihost_consensus_proven",
            "cross_store_account_session_atomicity_proven",
            "real_user_data_accessed",
            "owner_security_signoff", "production_deployment_authorized",
            "deployed",
        ):
            self.assertIs(matrix[flag], False, flag)
        self.assertIn("BLOCKED", matrix["release_gate"])
