"""Phase 7.22 safety, no-live-wiring and release blocks, no Redis required."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_legacy_issue_rate_rehearsal as candidate

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "a" * 32
MOBILE = "09123456789"
IP = "synthetic_ip_01"
DIGEST = "a" * 40


class FakeCache:
    key_prefix = candidate.PREFIX + FIXTURE
    version = 1
    _server = candidate.REDIS_URL

    def make_key(self, logical):
        return f"{self.key_prefix}:1:{logical}"


class FakeRedis:
    connection_pool = SimpleNamespace(connection_kwargs={
        "host": "127.0.0.1", "port": 6414, "db": 15,
    })


class Phase722LegacyIssueRateOfflineTests(SimpleTestCase):
    def scope(self, cache=None, raw=None, **changes):
        kwargs = {
            "fixture_id": FIXTURE, "mobile": MOBILE,
            "ip_tag": IP, "now_ts": 1050, "code_digest": DIGEST,
        }
        kwargs.update(changes)
        return candidate.validate_synthetic_scope(
            FakeCache() if cache is None else cache,
            FakeRedis() if raw is None else raw,
            **kwargs,
        )

    @staticmethod
    def grant():
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase722-offline",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE722_TEST_REDIS": "1",
        })

    def test_unauthorized_execution_denied_before_any_cache_io(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE722_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.scope()

    def test_exact_django_redis_four_key_namespace_and_hour(self):
        with self.grant():
            p = f"{candidate.PREFIX}{FIXTURE}:1:"
            keys = (
                f"{p}record:app_login:{MOBILE}",
                f"{p}resend:app_login:{MOBILE}",
                f"{p}rate:mobile:app_login_{MOBILE}:0",
                f"{p}rate:ip:{IP}:0",
            )
            self.assertEqual(self.scope(), keys)
            self.assertEqual(len(set(keys)), 4)
            next_hour = self.scope(now_ts=3600)
            self.assertEqual(keys[:2], next_hour[:2])
            self.assertNotEqual(keys[2:], next_hour[2:])

    def test_strict_rejects_nonfixture_ip_mobile_digest_clock(self):
        bad = [
            {"fixture_id": "unsafe"},
            {"fixture_id": True},
            {"mobile": "+989123456789"},
            {"mobile": "0912345678"},
            {"mobile": True},
            {"ip_tag": "198.51.100.20"},
            {"ip_tag": "synthetic_ip_1"},
            {"ip_tag": True},
            {"code_digest": "not-a-digest"},
            {"code_digest": "A" * 40},
            {"now_ts": True},
            {"now_ts": -1},
        ]
        with self.grant():
            for item in bad:
                with self.subTest(item=item), self.assertRaises(ValueError):
                    self.scope(**item)

    def test_exact_local_port_db_version_prefix_and_raw_byte_policy(self):
        with self.grant():
            for name, value in (
                ("key_prefix", candidate.PREFIX + "b" * 32),
                ("version", 2), ("version", True),
                ("_server", "redis://remote.invalid:6414/15"),
                ("_server", "redis://127.0.0.1:6379/15"),
            ):
                c = FakeCache()
                setattr(c, name, value)
                with self.subTest(name=name, value=value), self.assertRaises(RuntimeError):
                    self.scope(cache=c)
            for name, value in (
                ("host", "remote.invalid"),
                ("port", 6379),
                ("port", True),
                ("db", 14),
                ("db", False),
                ("decode_responses", True),
            ):
                kw = dict(FakeRedis.connection_pool.connection_kwargs)
                kw[name] = value
                client = SimpleNamespace(connection_pool=SimpleNamespace(
                    connection_kwargs=kw,
                ))
                with self.subTest(name=name, value=value), self.assertRaises(RuntimeError):
                    self.scope(raw=client)

    def test_statuses_never_authorize_real_issue_session_or_deploy(self):
        denied = [
            x.name for x in fields(candidate.SyntheticIssueEvidence)
            if x.name not in (
                "status", "mobile_requests_remaining",
                "ip_requests_remaining", "mutation_confirmed",
                "synthetic_record_created",
            )
        ]
        for result in (
            candidate.SyntheticIssueEvidence(
                "synthetic_issued", 1, 2,
                mutation_confirmed=True, synthetic_record_created=True,
            ),
            candidate.SyntheticIssueEvidence("resend_cooldown_active"),
            candidate.SyntheticIssueEvidence("mobile_rate_limited", 0),
            candidate.SyntheticIssueEvidence("ip_rate_limited", 1, 0),
            candidate.SyntheticIssueEvidence("concurrent_modification_conflict"),
            candidate.SyntheticIssueEvidence("backend_unavailable"),
        ):
            for flag in denied:
                self.assertIs(getattr(result, flag), False, flag)
            for secret in (FIXTURE, MOBILE, IP, DIGEST, "123456"):
                self.assertNotIn(secret, repr(result))

    def test_watch_four_keys_before_any_get_and_one_exec(self):
        src = inspect.getsource(candidate.attempt_synthetic_atomic_issue)
        self.assertLess(src.index("pipe.watch("),
                        src.index("_read_present("))
        self.assertLess(src.index("_read_present("),
                        src.index("pipe.multi()"))
        self.assertIn("pipe.set(record_key, payloads[0], ex=RECORD_TTL)", src)
        self.assertIn("pipe.set(cooldown_key, payloads[1], ex=RESEND_TTL)", src)
        self.assertIn("pipe.set(mobile_key, payloads[2], xx=True, keepttl=True)", src)
        self.assertIn("pipe.set(ip_key, payloads[3], xx=True, keepttl=True)", src)
        self.assertIn("pipe.execute()", src)
        self.assertIn("except WatchError:", src)
        self.assertIn("reply) != 4", src)
        self.assertIn("value is not True", src)
        for forbidden in (
            "cache.get(", "cache.set(", "cache.delete(",
            "redis_client.eval(", "flushdb(", "flushall(",
        ):
            self.assertNotIn(forbidden, src)

    def test_real_legacy_integer_wire_optimization_explicitly_preserved(self):
        src = inspect.getsource(candidate._serialized)
        self.assertIn("type(value) is int", src)
        self.assertIn("type(raw) is not int", src)
        self.assertIn("cache.client.encode(value)", src)
        self.assertIn("cache.client.decode(raw)", src)
        self.assertEqual(candidate.RECORD_TTL, 120)
        self.assertEqual(candidate.RESEND_TTL, 60)
        self.assertEqual(candidate.RATE_TTL, 3600)
        self.assertEqual(candidate.MOBILE_LIMIT, 2)
        self.assertEqual(candidate.IP_LIMIT, 3)

    def test_pipeline_never_imports_live_api_orm_sms_or_sessions(self):
        src = inspect.getsource(candidate)
        for forbidden in (
            "apps.api.v1.auth_otp", "apps.accounts.models", "django.db",
            "django.contrib.auth", "request.session", "login(request",
            "send_otp_sms(", ".objects.", "requests.post(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, src)
        for path in (
            "apps/api/v1/auth_otp.py",
            "apps/api/v1/auth_views.py",
            "apps/accounts/views.py",
            "apps/accounts/models.py",
        ):
            live = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_legacy_issue_rate_rehearsal", live)
            self.assertNotIn("attempt_synthetic_atomic_issue", live)

    def test_known_live_get_compare_delete_race_is_still_unfixed(self):
        src = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        self.assertIn("record = _cache_get(key)", src)
        self.assertIn("secrets.compare_digest(expected_hash, submitted_hash)", src)
        self.assertIn("cache.delete(key)", src)
        self.assertIn("return True", src)

    def test_ci_runner_isolation_concurrency_and_compose_contracts(self):
        shell = (ROOT / "tests/phase7_redis_legacy_issue_rate_ci.sh").read_text(
            encoding="utf-8"
        )
        test = (ROOT / "tests/phase7_legacy_issue_rate_test.py").read_text(
            encoding="utf-8"
        )
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        for anchor in (
            "GITHUB_ACTIONS", "LOOMERA_PHASE722_TEST_REDIS",
            "127.0.0.1:6414:6379", "redis:7.4-alpine", "trap cleanup EXIT",
            "docker rm -f", "docker volume rm", "docker network rm",
        ):
            self.assertIn(anchor, shell)
        for anchor in (
            "test_two_workers_same_mobile_same_ip_only_one_issuance",
            "test_two_different_mobiles_one_shared_ip_only_one_quota_increment",
            "test_test_only_consumer_compatible_with_phase721_legacy_record",
            "test_byte_identical_reissue_of_a_watched_rate_key_aborts",
            "test_commit_then_lose_response_cannot_authorize_any_real_otp",
            "test_three_distinct_mobiles_exhaust_shared_ip_quota",
            "test_hour_partition_uses_distinct_rate_keys",
        ):
            self.assertIn(anchor, test)
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_legacy_issue_rate",
            workflow,
        )
        self.assertIn("bash tests/phase7_redis_legacy_issue_rate_ci.sh", workflow)
        for forbidden in ("FLUSHALL", "FLUSHDB", "docker system prune"):
            self.assertNotIn(forbidden, shell)

    def test_release_matrix_blocks_all_real_otp_claims(self):
        m = json.loads((ROOT / "docs/globalization/PHASE7_22_EXIT_MATRIX.json")
                       .read_text(encoding="utf-8"))
        self.assertEqual(m["phase"], "7.22")
        self.assertEqual(
            m["baseline_main_sha"],
            "7f34b5639d089ec34285d7c5cf2d19f06e46fde6",
        )
        for flag in (
            "live_issue_or_rate_atomicity_fixed",
            "live_otp_consume_replay_fixed", "live_auth_or_sessions_rewired",
            "real_otp_sent", "all_legacy_sessions_drained",
            "old_master_globally_fenced", "multihost_consensus_proven",
            "cross_store_account_session_atomicity_proven",
            "real_user_data_accessed", "owner_security_signoff",
            "production_deployment_authorized", "deployed",
        ):
            self.assertIs(m[flag], False, flag)
        self.assertIn("BLOCKED", m["release_gate"])
