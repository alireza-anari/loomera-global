"""Phase 7.20 offline scoped WATCH candidate and blocked-release checks."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_legacy_watch_candidate as candidate

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_20_EXIT_MATRIX.json"
FIXTURE = "a" * 32
LOGICAL = "record:app_login:09123456789"


class FakeCache:
    key_prefix = candidate.PREFIX + FIXTURE
    version = 1
    _server = candidate.REDIS_URL

    def make_key(self, logical):
        return f"{self.key_prefix}:1:{logical}"


class FakeRedis:
    connection_pool = SimpleNamespace(connection_kwargs={
        "host": "127.0.0.1", "port": 6412, "db": 15,
    })


class Phase720WatchCandidateOfflineTests(SimpleTestCase):
    def scope(self, cache=None, raw=None, **changes):
        kwargs = {"fixture_id": FIXTURE, "logical_key": LOGICAL}
        kwargs.update(changes)
        return candidate.validate_synthetic_scope(
            FakeCache() if cache is None else cache,
            FakeRedis() if raw is None else raw,
            **kwargs,
        )

    def test_unauthorized_environment_rejected_before_any_redis_io(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE720_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.scope()

    def test_strict_test_only_scope_hard_bound_port_db_and_key(self):
        with patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase720-offline",
            "LOOMERA_PHASE720_TEST_REDIS": "1",
        }):
            self.assertEqual(
                self.scope(), f"{candidate.PREFIX}{FIXTURE}:1:{LOGICAL}",
            )
            for overrides in (
                {"fixture_id": "not-a-fixture"},
                {"logical_key": "record:app_login:+989123456789"},
                {"logical_key": "record:password_reset:09123456789"},
                {"fixture_id": True},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    self.scope(**overrides)

    def test_remote_cache_and_raw_clients_strictly_rejected(self):
        with patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase720-offline",
            "LOOMERA_PHASE720_TEST_REDIS": "1",
        }):
            for field, value in (
                ("key_prefix", candidate.PREFIX + "b" * 32),
                ("version", 2),
                ("_server", "redis://127.0.0.1:6379/15"),
                ("_server", "redis://remote.example:6412/15"),
            ):
                cache = FakeCache()
                setattr(cache, field, value)
                with self.subTest(field=field), self.assertRaises(RuntimeError):
                    self.scope(cache=cache)
            for field, value in (
                ("host", "remote.example"),
                ("port", 6379),
                ("port", True),
                ("db", 14),
                ("db", False),
            ):
                kw = dict(FakeRedis.connection_pool.connection_kwargs)
                kw[field] = value
                raw = SimpleNamespace(connection_pool=SimpleNamespace(
                    connection_kwargs=kw,
                ))
                with self.subTest(field=field), self.assertRaises(RuntimeError):
                    self.scope(raw=raw)

    def test_real_legacy_record_valid_for_synthetic_review(self):
        row = {
            "purpose": "app_login", "mobile_number": "09123456789",
            "code_hash": "a" * 40, "created_at": 1000,
            "expires_at": 1120, "attempts": 0, "max_attempts": 5,
            "verified": False,
        }
        self.assertTrue(candidate._valid_legacy_record(
            row, logical_key=LOGICAL, now_ts=1050,
        ))
        for field, value in (
            ("purpose", "password_reset"), ("mobile_number", "09123456780"),
            ("code_hash", "a" * 64), ("code_hash", "plaintext"),
            ("created_at", True), ("expires_at", False),
            ("created_at", 1051), ("expires_at", 1049),
            ("attempts", 5), ("attempts", -1),
            ("max_attempts", True), ("max_attempts", 11),
            ("verified", True),
        ):
            with self.subTest(field=field, value=value):
                self.assertFalse(candidate._valid_legacy_record(
                    {**row, field: value}, logical_key=LOGICAL, now_ts=1050,
                ))
        self.assertFalse(candidate._valid_legacy_record(
            {"purpose": "app_login"}, logical_key=LOGICAL, now_ts=1050,
        ))

    def test_all_returned_evidence_never_grants_real_auth(self):
        flags = [f.name for f in fields(candidate.WatchCandidateEvidence)
                 if f.name not in ("status", "synthetic_record_deleted")]
        for status, consumed in (
            ("synthetic_single_winner", True),
            ("concurrent_modification_conflict", False),
            ("wrong_digest", False),
            ("backend_unavailable", False),
            ("delete_unconfirmed", False),
        ):
            report = candidate.WatchCandidateEvidence(status, consumed)
            self.assertEqual(report.synthetic_record_deleted, consumed)
            for flag in flags:
                self.assertFalse(getattr(report, flag), flag)
            for secret in ("09123456789", "123456", "a" * 40):
                self.assertNotIn(secret, repr(report))

    def test_watch_precedes_get_and_delete_requires_exec_one(self):
        src = inspect.getsource(candidate.attempt_synthetic_watch_consume)
        self.assertLess(src.index("transaction.watch(physical)"),
                        src.index("transaction.get(physical)"))
        self.assertLess(src.index("transaction.get(physical)"),
                        src.index("transaction.multi()"))
        self.assertLess(src.index("transaction.multi()"),
                        src.index("transaction.delete(physical)"))
        self.assertLess(src.index("transaction.delete(physical)"),
                        src.index("transaction.execute()"))
        self.assertIn("except WatchError:", src)
        self.assertIn('deleted != [1]', src)
        self.assertIn('WatchCandidateEvidence("concurrent_modification_conflict")',
                      src)
        self.assertNotIn("cache.get(", src)
        self.assertNotIn("cache.delete(", src)
        self.assertNotIn("eval(", src)
        self.assertNotIn("flushdb(", src)

    def test_candidate_cannot_import_or_access_live_auth_database_and_sessions(self):
        src = inspect.getsource(candidate)
        for forbidden in (
            "apps.api.v1.auth_otp", "apps.accounts.models",
            "django.contrib.auth", "django.db", "request.session",
            "login(request", ".objects.", "cache.set(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, src)

    def test_no_live_auth_import_or_pipeline_wiring(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            data = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_legacy_watch_candidate", data)
            self.assertNotIn("attempt_synthetic_watch_consume", data)
        original = (ROOT / "apps/api/v1/auth_otp.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("record = _cache_get(key)", original)
        self.assertIn("secrets.compare_digest(expected_hash, submitted_hash)", original)
        self.assertIn("cache.delete(key)", original)

    def test_ci_disposable_and_negative_cases_present(self):
        shell = (ROOT / "tests/phase7_redis_legacy_watch_ci.sh").read_text()
        test = (ROOT / "tests/phase7_legacy_watch_candidate_test.py").read_text()
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        for anchor in (
            "GITHUB_ACTIONS", "LOOMERA_PHASE720_TEST_REDIS",
            "GITHUB_RUN_ID", "127.0.0.1:6412:6379",
            "redis:7.4-alpine", "trap cleanup EXIT",
            "docker rm -f", "docker volume rm", "docker network rm",
        ):
            self.assertIn(anchor, shell)
        for anchor in (
            "test_two_independent_workers_watching_before_read_one_exact_winner",
            "test_identical_raw_bytes_reissue_after_watch_is_aba_conflict",
            "test_new_generation_with_new_digest_after_watch_not_deleted",
            "test_denied_env_remote_cache_wrong_db_and_wrong_prefix_before_io",
        ):
            self.assertIn(anchor, test)
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_legacy_watch_candidate",
            workflow,
        )
        self.assertIn("bash tests/phase7_redis_legacy_watch_ci.sh", workflow)
        for forbidden in ("FLUSHALL", "FLUSHDB", "docker system prune"):
            self.assertNotIn(forbidden, shell)

    def test_phase720_matrix_explicitly_blocks_legacy_cutover(self):
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "7.20")
        self.assertEqual(
            data["baseline_main_sha"],
            "919629f60d18ac9bdb3ad68414219c5facd00086",
        )
        for flag in (
            "live_auth_wired", "production_cache_migrated",
            "real_otp_replay_race_fixed", "real_rate_limit_atomicity_fixed",
            "web_otp_and_password_reset_sessions_migrated",
            "redis_failover_global_fence_proven",
            "real_accounts_or_sessions_accessed",
            "owner_security_signoff", "production_deployment_authorized",
            "deployed",
        ):
            self.assertIs(data[flag], False, flag)
        self.assertIn("BLOCKED", data["release_gate"])
