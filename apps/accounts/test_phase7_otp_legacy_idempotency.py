"""Phase 7.24 offline preflight: idempotency ledger scope, safety and BLOCKED."""
from __future__ import annotations

from dataclasses import fields
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from loomera.globalization import otp_legacy_idempotency_rehearsal as idem
from loomera.globalization import otp_legacy_issue_rate_rehearsal as issue

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "a" * 32
OP = "b" * 32
MOBILE = "09123456789"
IP_TAG = "synthetic_ip_01"
DIGEST = "c" * 40


class FakeCache:
    key_prefix = issue.PREFIX + FIXTURE
    version = 1
    _server = issue.REDIS_URL

    def make_key(self, logical):
        return f"{self.key_prefix}:1:{logical}"


class FakeRedis:
    connection_pool = SimpleNamespace(connection_kwargs={
        "host": "127.0.0.1", "port": 6414, "db": 15,
    })


class Phase724IdempotencyOfflinePolicyTests(SimpleTestCase):
    def scope(self, *, cache=None, client=None, operation_id=OP,
              kind="issue", **updates):
        opts = {
            "fixture_id": FIXTURE, "mobile": MOBILE,
            "ip_tag": IP_TAG, "now_ts": 1050, "digest": DIGEST,
            "operation_id": operation_id, "kind": kind,
        }
        opts.update(updates)
        return idem._prepare(
            FakeCache() if cache is None else cache,
            FakeRedis() if client is None else client,
            **opts,
        )

    @staticmethod
    def granted():
        return patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "phase724-offline",
            "GITHUB_RUN_ATTEMPT": "1",
            "LOOMERA_PHASE722_TEST_REDIS": "1",
            "LOOMERA_PHASE724_TEST_REDIS": "1",
        })

    def test_test_only_guard_required_before_network_access(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE724_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.scope()
        with self.granted():
            with patch.dict(os.environ, {"LOOMERA_PHASE722_TEST_REDIS": "0"}):
                with self.assertRaises(RuntimeError):
                    self.scope()

    def test_all_five_physical_keys_and_fingerprint_scope(self):
        with self.granted():
            physical = self.scope()
            prefix = f"{issue.PREFIX}{FIXTURE}:1:"
            self.assertEqual(physical[0], prefix + "operation:synthetic:" + OP)
            self.assertEqual(physical[1], prefix + "record:app_login:" + MOBILE)
            self.assertEqual(physical[2], prefix + "resend:app_login:" + MOBILE)
            self.assertEqual(
                physical[3], prefix + f"rate:mobile:app_login_{MOBILE}:0",
            )
            self.assertEqual(physical[4], prefix + f"rate:ip:{IP_TAG}:0")
            self.assertEqual(len(set(physical[:5])), 5)
            self.assertEqual(len(physical[5]), 64)
            self.assertEqual(physical[5], self.scope(now_ts=1060)[5])
            self.assertNotEqual(physical[5], self.scope(kind="verify")[5])
            self.assertNotEqual(physical[5], self.scope(digest="d" * 40)[5])

    def test_strict_rejects_invalid_op_and_untrusted_redis_scope(self):
        with self.granted():
            for op in ("unsafe", "A" * 32, True, "0" * 31, "0" * 33):
                with self.subTest(op=op), self.assertRaises(ValueError):
                    self.scope(operation_id=op)
            broken = FakeCache()
            broken._server = "redis://remote.invalid:6414/15"
            with self.assertRaises(RuntimeError):
                self.scope(cache=broken)
            wrongdb = SimpleNamespace(connection_pool=SimpleNamespace(
                connection_kwargs={"host": "127.0.0.1", "port": 6414, "db": 14},
            ))
            with self.assertRaises(RuntimeError):
                self.scope(client=wrongdb)
            with self.assertRaises(ValueError):
                self.scope(digest="plaintext")
            with self.assertRaises(ValueError):
                self.scope(ip_tag="192.0.2.1")

    def test_result_object_never_grants_production_or_auto_retry(self):
        forbidden = [
            x.name for x in fields(idem.SyntheticIdempotencyEvidence)
            if x.name not in (
                "status", "prior_status", "attempts_remaining",
                "mobile_requests_remaining", "ip_requests_remaining",
                "mutation_confirmed", "replay_observed",
            )
        ]
        for row in (
            idem.SyntheticIdempotencyEvidence("synthetic_issued",
                                               mutation_confirmed=True),
            idem.SyntheticIdempotencyEvidence(
                "synthetic_replayed", prior_status="synthetic_single_winner",
                replay_observed=True,
            ),
            idem.SyntheticIdempotencyEvidence("backend_unavailable"),
            idem.SyntheticIdempotencyEvidence("operation_reuse_conflict"),
        ):
            for field in forbidden:
                self.assertIs(getattr(row, field), False, field)
            for secret in (FIXTURE, OP, MOBILE, IP_TAG, DIGEST, "123456"):
                self.assertNotIn(secret, repr(row))

    def test_strict_ledger_validation_and_conflicting_operation_statuses(self):
        self.assertEqual(idem.LEDGER_TTL, 3900)
        self.assertGreater(idem.LEDGER_TTL, issue.RATE_TTL)
        self.assertFalse(idem._confirmed([True] * 4, count=5))
        self.assertFalse(idem._confirmed([True] * 5 + [True], count=5))
        self.assertFalse(idem._confirmed([True, True, False, True, True], count=5))
        self.assertTrue(idem._confirmed([True] * 5, count=5))
        self.assertTrue(idem._confirmed([1, True], count=2, delete_first=True))
        for invalid in ([False, True], [0, True], [True, True],
                        [1.0, True], [1, False]):
            with self.subTest(reply=invalid):
                self.assertFalse(
                    idem._confirmed(invalid, count=2, delete_first=True),
                )
        self.assertEqual(
            idem._ALLOWED_PRIOR,
            frozenset({
                "synthetic_issued", "synthetic_single_winner",
                "synthetic_invalid_attempt", "synthetic_exhausted",
            }),
        )

    def test_watch_ledger_plus_all_keys_before_read_or_mutation(self):
        src_issue = inspect.getsource(idem.attempt_synthetic_idempotent_issue)
        src_verify = inspect.getsource(idem.attempt_synthetic_idempotent_verify)
        self.assertLess(src_issue.index("pipe.watch(ledger, rec, cool, mobile_key, ip_key)"),
                        src_issue.index("_read_ledger("))
        self.assertLess(src_issue.index("_read_ledger("),
                        src_issue.index("pipe.multi()"))
        self.assertLess(src_verify.index("pipe.watch(ledger, rec)"),
                        src_verify.index("_read_ledger("))
        self.assertLess(src_verify.index("_read_ledger("),
                        src_verify.index("pipe.get(rec)"))
        self.assertIn("pipe.set(ledger, payloads[4], ex=LEDGER_TTL)", src_issue)
        self.assertIn("pipe.set(ledger, entry, ex=LEDGER_TTL)", src_verify)
        self.assertIn("pipe.set(mobile_key, payloads[2], xx=True, keepttl=True)", src_issue)
        self.assertIn("pipe.set(ip_key, payloads[3], xx=True, keepttl=True)", src_issue)
        self.assertIn("pipe.set(rec, updated_raw, xx=True, keepttl=True)", src_verify)
        self.assertIn("_confirmed(reply, count=2, delete_first=delete)", src_verify)
        for src in (src_issue, src_verify):
            for forbidden in (
                "cache.get(", "cache.set(", "cache.delete(",
                "flushdb(", "flushall(", "redis_client.eval(",
            ):
                self.assertNotIn(forbidden, src)

    def test_no_live_auth_models_sessions_or_sms_in_candidate(self):
        src = inspect.getsource(idem)
        for forbidden in (
            "apps.api.v1.auth_otp", "apps.accounts.models",
            "django.contrib.auth", "django.db", "request.session",
            "login(request", ".objects.", "send_otp_sms(",
        ):
            self.assertNotIn(forbidden, src)
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            live = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("otp_legacy_idempotency_rehearsal", live)
            self.assertNotIn("attempt_synthetic_idempotent_issue", live)
            self.assertNotIn("attempt_synthetic_idempotent_verify", live)
        otp_live = (ROOT / "apps/api/v1/auth_otp.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("record = _cache_get(key)", otp_live)
        self.assertIn("secrets.compare_digest(expected_hash, submitted_hash)", otp_live)
        self.assertIn("cache.delete(key)", otp_live)

    def test_real_aof_rehearsal_and_ci_runner_remain_disposable(self):
        sh = (ROOT / "tests/phase7_redis_legacy_issue_rate_ci.sh").read_text(
            encoding="utf-8"
        )
        real = (ROOT / "tests/phase7_legacy_idempotency_test.py").read_text(
            encoding="utf-8"
        )
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        for part in (
            "GITHUB_ACTIONS", "LOOMERA_PHASE724_TEST_REDIS",
            "LOOMERA_PHASE724_CONTAINER",
            "--label loomera.phase724=idempotency-test",
            "python tests/phase7_legacy_idempotency_test.py",
            "127.0.0.1:6414:6379", "redis:7.4-alpine",
            "trap cleanup EXIT", "docker rm -f", "docker volume rm",
            "docker network rm",
        ):
            self.assertIn(part, sh)
        for part in (
            "test_physical_aof_restart_persists_ledger_and_prevents_double_charge",
            "test_lost_issue_exec_ack_retry_same_op_no_new_code_or_rate_charge",
            "test_lost_correct_consume_ack_retry_same_op_only_observes_ledger",
            "test_wrong_attempt_replay_never_charges_twice_even_after_ack_loss",
            "test_concurrent_same_issue_operation_exactly_one_commit_then_replay",
            "test_concurrent_same_wrong_verify_operation_one_attempt_then_replay",
            "test_explicit_ledger_loss_invalidates_bounded_exactly_once_proof",
        ):
            self.assertIn(part, real)
        self.assertIn(
            "python manage.py test apps.accounts.test_phase7_otp_legacy_idempotency",
            workflow,
        )
        self.assertIn(
            "bash tests/phase7_redis_legacy_issue_rate_ci.sh",
            workflow,
        )
        for forbidden in ("FLUSHDB", "FLUSHALL", "docker system prune"):
            self.assertNotIn(forbidden, sh)

    def test_release_gate_cannot_mark_live_idempotency_repaired(self):
        data = json.loads((
            ROOT / "docs/globalization/PHASE7_24_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "7.24")
        self.assertEqual(
            data["baseline_main_sha"],
            "b9dfa8979d5b73e85020d53e1f57837b4315c718",
        )
        for field in (
            "production_auth_wired", "real_otp_retry_idempotency_fixed",
            "real_otp_replay_race_fixed", "owner_security_signoff",
            "old_master_globally_fenced", "multihost_consensus_proven",
            "external_sms_delivery_idempotent",
            "account_session_transaction_proven",
            "untrusted_pickle_boundary_approved",
            "production_deployment_authorized", "deployed",
        ):
            self.assertIs(data[field], False, field)
        self.assertIn("BLOCKED", data["release_gate"])
