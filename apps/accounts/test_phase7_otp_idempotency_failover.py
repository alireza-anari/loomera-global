"""Phase 7.25 offline safety gates: real two-master negative ID ledger proof.

No Redis/Docker required for Fast job. Live application files are read-only.
"""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_legacy_idempotency_failover_rehearsal as drill
from loomera.globalization import otp_legacy_idempotency_rehearsal as prior

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "a" * 32
OP = "b" * 32
DIGEST = "c" * 40
MOBILE = "09123456789"


class FakeCache:
    version = 1
    key_prefix = drill.PREFIX + FIXTURE
    _server = drill.OLD_URL

    def make_key(self, logical):
        return f"{self.key_prefix}:1:{logical}"


class FakeClient:
    connection_pool = SimpleNamespace(connection_kwargs={
        "host": "127.0.0.1", "port": 6415, "db": 15,
    })


class Phase725RealFailoverIdempotencyOfflineGuards(SimpleTestCase):
    @staticmethod
    def grant():
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase725-offline",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE725_TEST_REDIS": "1",
        })

    def scope(self, *, cache=None, client=None, **updates):
        options = {
            "fixture_id": FIXTURE, "mobile": MOBILE,
            "digest": DIGEST, "operation_id": OP,
            "kind": "issue", "now_ts": 1050,
        }
        options.update(updates)
        return drill.validate_two_master_scope(
            FakeCache() if cache is None else cache,
            FakeClient() if client is None else client,
            **options,
        )

    def test_exact_two_local_hosts_db_15_and_ledger_key(self):
        with self.grant():
            physical = self.scope()
            p = f"{drill.PREFIX}{FIXTURE}:1:"
            self.assertEqual(physical[:5], (
                p + "operation:synthetic:" + OP,
                p + "record:app_login:" + MOBILE,
                p + "resend:app_login:" + MOBILE,
                p + "rate:mobile:app_login_" + MOBILE + ":0",
                p + "rate:ip:synthetic_ip_01:0",
            ))
            self.assertEqual(len(set(physical[:5])), 5)
            self.assertEqual(len(physical[5]), 64)
            self.assertEqual(self.scope(now_ts=1051)[5], physical[5])
            self.assertNotEqual(
                self.scope(digest="d" * 40)[5], physical[5],
            )
            self.assertNotEqual(self.scope(kind="verify")[5], physical[5])
            replica = FakeCache()
            replica._server = drill.PROMOTED_URL
            raw = SimpleNamespace(connection_pool=SimpleNamespace(
                connection_kwargs={
                    "host": "127.0.0.1", "port": 6416, "db": 15,
                },
            ))
            self.assertEqual(self.scope(cache=replica, client=raw), physical)
            self.assertEqual(drill.OLD_URL, "redis://127.0.0.1:6415/15")
            self.assertEqual(drill.PROMOTED_URL, "redis://127.0.0.1:6416/15")
            self.assertEqual(drill.PREFIX,
                             "loomera:phase725:synthetic-two-master-only:")

    def test_unauthorized_scope_fails_before_any_redis_operation(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE725_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.scope()
        with self.grant():
            bad = (
                {"fixture_id": "unsafe"},
                {"fixture_id": True},
                {"mobile": "09123456782"},
                {"mobile": "+989123456789"},
                {"mobile": True},
                {"ip_tag": "198.51.100.1"},
                {"ip_tag": True},
                {"digest": "plaintext"},
                {"digest": "A" * 40},
                {"operation_id": "not-uuid"},
                {"operation_id": True},
                {"kind": "recover"},
                {"kind": True},
                {"now_ts": True},
                {"now_ts": -1},
            )
            for kwargs in bad:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    self.scope(**kwargs)

    def test_unsafe_endpoint_wrong_port_db_or_prefix_rejected(self):
        with self.grant():
            for backend in (
                "redis://remote.invalid:6415/15",
                "redis://127.0.0.1:6379/15",
                "redis://127.0.0.1:6415/14",
            ):
                cache = FakeCache()
                cache._server = backend
                with self.subTest(backend=backend), self.assertRaises(RuntimeError):
                    self.scope(cache=cache)
            wrong_cache = FakeCache()
            wrong_cache.key_prefix = drill.PREFIX + "f" * 32
            with self.assertRaises(RuntimeError):
                self.scope(cache=wrong_cache)
            for key, bad in (
                ("host", "remote.invalid"),
                ("port", 6379), ("port", True),
                ("db", 14), ("db", False),
                ("decode_responses", True),
            ):
                opts = dict(FakeClient.connection_pool.connection_kwargs)
                opts[key] = bad
                raw = SimpleNamespace(connection_pool=SimpleNamespace(
                    connection_kwargs=opts,
                ))
                with self.subTest(key=key, bad=bad), self.assertRaises(RuntimeError):
                    self.scope(client=raw)

    def test_fingerprint_identical_to_phase724_protocol(self):
        src = inspect.getsource(drill.validate_two_master_scope)
        old = inspect.getsource(prior._prepare)
        for token in (
            '"phase724|v1|"', "hashlib.sha256(", 'kind + "|"',
            'mobile + "|"', 'ip_tag + "|"', 'digest)',
        ):
            self.assertIn(token, src)
            self.assertIn(token, old)
        self.assertIn("operation:synthetic:", src)

    def test_both_master_writers_watch_exact_ledger_and_state_first(self):
        source_issue = inspect.getsource(drill.issue_on_synthetic_master)
        source_verify = inspect.getsource(drill.verify_on_synthetic_master)
        self.assertLess(
            source_issue.index("pipe.watch(ledger, rec, cool, mob_rate, ip_rate)"),
            source_issue.index("_read_ledger("),
        )
        self.assertLess(
            source_issue.index("_read_ledger("),
            source_issue.index("pipe.multi()"),
        )
        self.assertLess(
            source_verify.index("pipe.watch(ledger, rec)"),
            source_verify.index("_read_ledger("),
        )
        self.assertLess(
            source_verify.index("_read_ledger("),
            source_verify.index("pipe.get(rec)"),
        )
        for src in (source_issue, source_verify):
            self.assertIn("except WatchError:", src)
            self.assertIn("pipe.set(ledger,", src)
            self.assertIn("pipe.execute()", src)
            for forbidden in (
                "cache.get(", "cache.set(", "cache.delete(",
                "flushdb(", "flushall(", "redis_client.eval(",
            ):
                self.assertNotIn(forbidden, src)
        self.assertIn("_confirmed(pipe.execute(), count=5)", source_issue)
        self.assertIn("xx=True, keepttl=True", source_issue)
        self.assertIn("_confirmed(pipe.execute(), count=2, delete_first=delete)",
                      source_verify)
        self.assertIn("_ledger_payload(", source_verify)
        self.assertIn("_legacy_record_valid(", source_verify)

    def test_split_brain_observer_never_authorizes_any_real_action(self):
        both = drill.summarize_split_brain(
            old_master_role="master", promoted_role="master",
            old_issue_ledger=b"old-fingerprint",
            new_issue_ledger=b"other-fingerprint",
            old_challenge=b"old-record",
            new_challenge=b"other-record",
            old_bypass_write_confirmed=True,
        )
        self.assertEqual(both.status, "two_masters_divergent_same_operation")
        self.assertTrue(both.two_local_master_claims)
        self.assertTrue(both.divergent_ledgers_observed)
        self.assertTrue(both.old_primary_raw_bypass_observed)
        for model in (
            both,
            drill.summarize_split_brain(
                old_master_role="master", promoted_role="slave",
                old_issue_ledger=b"same", new_issue_ledger=b"same",
                old_challenge=b"same", new_challenge=b"same",
                old_bypass_write_confirmed=False,
            ),
        ):
            for item in fields(drill.SyntheticSplitBrainEvidence):
                if item.name in (
                    "status", "two_local_master_claims",
                    "divergent_ledgers_observed",
                    "old_primary_raw_bypass_observed",
                ):
                    continue
                self.assertIs(getattr(model, item.name), False, item.name)
        for secret in (MOBILE, FIXTURE, OP, DIGEST):
            self.assertNotIn(secret, repr(both))

    def test_actual_live_otp_and_session_files_not_rewired(self):
        code = inspect.getsource(drill)
        for forbidden in (
            "apps.api.v1.auth_otp", "apps.accounts.models",
            "django.db", "django.contrib.auth", "request.session",
            "login(request", ".objects.", "send_otp_sms(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            live = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_legacy_idempotency_failover_rehearsal", live)
            self.assertNotIn("issue_on_synthetic_master", live)
            self.assertNotIn("verify_on_synthetic_master", live)
        actual = (ROOT / "apps/api/v1/auth_otp.py").read_text(
            encoding="utf-8",
        )
        self.assertIn("record = _cache_get(key)", actual)
        self.assertIn("secrets.compare_digest(expected_hash, submitted_hash)",
                      actual)
        self.assertIn("cache.delete(key)", actual)

    def test_runner_physical_partition_host_bypass_and_aof_contract(self):
        shell = (ROOT / "tests/phase7_redis_idempotency_failover_ci.sh").read_text(
            encoding="utf-8",
        )
        drill_script = (ROOT / "tests/phase7_idempotency_failover_drill.py").read_text(
            encoding="utf-8",
        )
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for token in (
            "LOOMERA_PHASE725_TEST_REDIS",
            "127.0.0.1:6415:6379", "127.0.0.1:6416:6379",
            "--label loomera.phase725=synthetic-old",
            "--label loomera.phase725=synthetic-promoted",
            "redis:7.4-alpine", "--appendonly yes", "--appendfsync always",
            "REPLICAOF p725-old-repl 6379",
            "master_link_status:", "docker network disconnect",
            'docker exec "$promoted" redis-cli CLIENT KILL TYPE MASTER',
            "REPLICAOF NO ONE", "docker stop", "docker start",
            "trap cleanup EXIT", "docker volume rm -f",
            "docker network rm", "docker rm -f",
            'python tests/phase7_idempotency_failover_drill.py seed',
            'python tests/phase7_idempotency_failover_drill.py partition',
            'python tests/phase7_idempotency_failover_drill.py host-bypass',
            'python tests/phase7_idempotency_failover_drill.py after-restart',
        ):
            self.assertIn(token, shell)
        for token in (
            "p.wait(1, 5000)", "new.get(key) == expected",
            "Barrier(2, timeout=20)",
            "synthetic_issued\", \"synthetic_issued",
            "operation_reuse_conflict",
            "synthetic_single_winner",
            "synthetic_invalid_attempt",
            "old_primary_raw_bypass_observed",
            "old.eval(script, 1, bypass",
            'old.get(kb[0]) != new.get(kb[0])',
            '"attempts"] == 2',
            '"attempts"] == 1',
        ):
            self.assertIn(token, drill_script)
        self.assertIn("bash tests/phase7_redis_idempotency_failover_ci.sh", ci)
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_idempotency_failover",
            ci,
        )
        for forbidden in ("FLUSHDB", "FLUSHALL", "docker system prune", "SCAN "):
            self.assertNotIn(forbidden, shell)

    def test_exit_matrix_remains_blocked_and_old_master_unfenced(self):
        path = ROOT / "docs/globalization/PHASE7_25_EXIT_MATRIX.json"
        matrix = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.25")
        self.assertEqual(
            matrix["baseline_main_sha"],
            "9bb72e4d7a1190df728e32147de849b14958edb9",
        )
        self.assertEqual(matrix["replication_before_partition"], "WAIT_1_AND_EXACT_BYTES")
        for field in (
            "live_otp_issue_or_verify_fixed",
            "real_otp_idempotency_globally_safe",
            "old_primary_host_writes_fenced",
            "globally_unique_operation_execution_proven",
            "quorum_or_consensus_proven",
            "durable_cross_master_reconciliation_proven",
            "account_or_session_atomicity_proven",
            "real_sms_delivery_idempotent",
            "owner_security_signoff",
            "production_deployment_authorized",
            "deployed",
        ):
            self.assertIs(matrix[field], False, field)
        self.assertIn("BLOCKED", matrix["release_gate"])
