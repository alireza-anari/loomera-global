"""Phase 7.24 real Redis 7.4 AOF + django-redis 5.4 OTP idempotency suite.

Runs in the SAME Phase 7.22 / 7.23 disposable Redis container, port 6414,
DB15. Only fabricated mobile/IP, random fixture-owned keys, no real OTP.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="phase724-test-only-secret-not-production")
import redis
from redis.client import Pipeline
from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache

from loomera.globalization.otp_legacy_issue_rate_rehearsal import (
    PREFIX, REDIS_URL, validate_synthetic_scope,
)
from loomera.globalization.otp_legacy_idempotency_rehearsal import (
    LEDGER_TTL, SyntheticIdempotencyEvidence,
    attempt_synthetic_idempotent_issue, attempt_synthetic_idempotent_verify,
)

MOBILE = "09123456789"
IP_TAG = "synthetic_ip_01"
GOOD = "123456"
BAD = "000000"


def digest(code=GOOD):
    return salted_hmac(
        "loomera.api.auth.otp", f"app_login:{MOBILE}:{code}",
    ).hexdigest()


def new_cache(fixture):
    return RedisCache(REDIS_URL, {
        "KEY_PREFIX": PREFIX + fixture, "VERSION": 1,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    })


def new_client():
    return redis.Redis.from_url(
        REDIS_URL, socket_connect_timeout=1, socket_timeout=5,
    )


class Phase724IdempotencyOnRealRedisTests(unittest.TestCase):
    def setUp(self):
        if (os.environ.get("GITHUB_ACTIONS") != "true"
                or not os.environ.get("GITHUB_RUN_ID")
                or not os.environ.get("GITHUB_RUN_ATTEMPT")
                or os.environ.get("LOOMERA_PHASE722_TEST_REDIS") != "1"
                or os.environ.get("LOOMERA_PHASE724_TEST_REDIS") != "1"):
            self.fail("explicit disposable GitHub CI grants required")
        self.fixture = uuid4().hex
        self.cache = new_cache(self.fixture)
        self.raw = new_client()
        self.assertTrue(self.raw.ping())
        self.keys = validate_synthetic_scope(
            self.cache, self.raw, fixture_id=self.fixture, mobile=MOBILE,
            ip_tag=IP_TAG, now_ts=1050, code_digest=digest(),
        )
        self.ledger_keys = set()

    def tearDown(self):
        try:
            self.raw.delete(*(list(self.keys) + sorted(self.ledger_keys)))
        finally:
            self.raw.close()

    def ledger(self, op):
        key = str(self.cache.make_key("operation:synthetic:" + str(op)))
        self.ledger_keys.add(key)
        return key

    def issue(self, op, *, code=GOOD, now_ts=1050,
              cache=None, client=None, on_watched_read=None):
        self.ledger(op)
        return attempt_synthetic_idempotent_issue(
            self.cache if cache is None else cache,
            self.raw if client is None else client,
            fixture_id=self.fixture, mobile=MOBILE, ip_tag=IP_TAG,
            now_ts=now_ts, code_digest=digest(code), operation_id=op,
            on_watched_read=on_watched_read,
        )

    def verify(self, op, *, code=GOOD, now_ts=1050,
               cache=None, client=None, on_watched_read=None):
        self.ledger(op)
        return attempt_synthetic_idempotent_verify(
            self.cache if cache is None else cache,
            self.raw if client is None else client,
            fixture_id=self.fixture, mobile=MOBILE, ip_tag=IP_TAG,
            now_ts=now_ts, submitted_digest=digest(code), operation_id=op,
            on_watched_read=on_watched_read,
        )

    def assert_no_auth(self, result):
        self.assertIsInstance(result, SyntheticIdempotencyEvidence)
        for field in (
            "real_otp_issued_or_consumed", "real_authentication_allowed",
            "real_session_created", "automatic_retry_or_grant_authorized",
            "production_cutover_authorized", "live_idempotency_fixed",
            "multihost_fencing_proven", "cross_store_consistency_proven",
        ):
            self.assertIs(getattr(result, field), False, field)
        for secret in (MOBILE, IP_TAG, GOOD, BAD, digest(), self.fixture):
            self.assertNotIn(secret, repr(result))

    def assert_counters(self, mobile=1, ip=1):
        self.assertEqual(self.raw.get(self.keys[2]), str(mobile).encode())
        self.assertEqual(self.raw.get(self.keys[3]), str(ip).encode())

    def test_issue_commits_five_keys_and_replay_does_not_charge_twice(self):
        op = uuid4().hex
        first = self.issue(op)
        self.assertEqual(first.status, "synthetic_issued")
        self.assertTrue(first.mutation_confirmed)
        self.assertFalse(first.replay_observed)
        self.assert_no_auth(first)
        key = self.ledger(op)
        record_before = self.raw.get(self.keys[0])
        ledger_before = self.raw.get(key)
        ttl = self.raw.pttl(key)
        self.assertTrue(0 < ttl <= LEDGER_TTL * 1000)
        self.assertIsInstance(ledger_before, bytes)
        self.assertEqual(
            self.cache.get(f"record:app_login:{MOBILE}")["code_hash"], digest(),
        )
        self.assert_counters()
        replay = self.issue(op, now_ts=1059)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_issued")
        self.assertTrue(replay.replay_observed)
        self.assertFalse(replay.mutation_confirmed)
        self.assertEqual(replay.mobile_requests_remaining, 1)
        self.assertEqual(replay.ip_requests_remaining, 2)
        self.assert_no_auth(replay)
        self.assertEqual(self.raw.get(self.keys[0]), record_before)
        self.assertEqual(self.raw.get(key), ledger_before)
        self.assertTrue(0 < self.raw.pttl(key) <= ttl)
        self.assert_counters()

    def test_correct_verification_replays_after_record_is_deleted_no_session(self):
        self.assertEqual(self.issue(uuid4().hex).status, "synthetic_issued")
        op = uuid4().hex
        first = self.verify(op)
        self.assertEqual(first.status, "synthetic_single_winner")
        self.assertTrue(first.mutation_confirmed)
        self.assertIsNone(self.raw.get(self.keys[0]))
        self.assert_no_auth(first)
        ledger_key = self.ledger(op)
        raw_before = self.raw.get(ledger_key)
        replay = self.verify(op, now_ts=1051)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_single_winner")
        self.assertFalse(replay.mutation_confirmed)
        self.assertTrue(replay.replay_observed)
        self.assert_no_auth(replay)
        self.assertEqual(self.raw.get(ledger_key), raw_before)
        self.assertEqual(self.verify(uuid4().hex).status, "missing")
        self.assertEqual(
            self.issue(uuid4().hex, code="654321").status,
            "resend_cooldown_active",
        )
        self.assert_counters()

    def test_wrong_attempt_replay_never_charges_twice_even_after_ack_loss(self):
        self.assertEqual(self.issue(uuid4().hex).status, "synthetic_issued")
        op = uuid4().hex
        execute = Pipeline.execute
        def commit_then_lose(pipe, *args, **kwargs):
            execute(pipe, *args, **kwargs)
            raise TimeoutError("fake attempt committed, response lost")
        with patch.object(Pipeline, "execute", commit_then_lose):
            uncertain = self.verify(op, code=BAD)
        self.assertEqual(uncertain.status, "backend_unavailable")
        self.assertFalse(uncertain.mutation_confirmed)
        self.assert_no_auth(uncertain)
        self.assertEqual(
            self.cache.get(f"record:app_login:{MOBILE}")["attempts"], 1,
        )
        ledger_before = self.raw.get(self.ledger(op))
        replay = self.verify(op, code=BAD, now_ts=1051)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_invalid_attempt")
        self.assertEqual(replay.attempts_remaining, 4)
        self.assertTrue(replay.replay_observed)
        self.assertFalse(replay.mutation_confirmed)
        self.assert_no_auth(replay)
        self.assertEqual(self.raw.get(self.ledger(op)), ledger_before)
        self.assertEqual(
            self.cache.get(f"record:app_login:{MOBILE}")["attempts"], 1,
        )
        self.assert_counters()

    def test_exhaustion_replay_never_consumes_a_new_generation(self):
        self.assertEqual(self.issue(uuid4().hex).status, "synthetic_issued")
        logical = f"record:app_login:{MOBILE}"
        previous = self.cache.get(logical)
        self.cache.set(logical, {**previous, "attempts": 4}, timeout=100)
        op = uuid4().hex
        exhausted = self.verify(op, code=BAD)
        self.assertEqual(exhausted.status, "synthetic_exhausted")
        self.assertEqual(exhausted.attempts_remaining, 0)
        self.assertTrue(exhausted.mutation_confirmed)
        self.assertIsNone(self.raw.get(self.keys[0]))
        replay = self.verify(op, code=BAD, now_ts=1051)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_exhausted")
        self.assertEqual(replay.attempts_remaining, 0)
        self.assert_no_auth(replay)
        self.assert_counters()

    def test_lost_issue_exec_ack_retry_same_op_no_new_code_or_rate_charge(self):
        op = uuid4().hex
        execute = Pipeline.execute
        def commit_then_lose(pipe, *args, **kwargs):
            execute(pipe, *args, **kwargs)
            raise TimeoutError("fake issue committed but acknowledgement lost")
        with patch.object(Pipeline, "execute", commit_then_lose):
            uncertain = self.issue(op)
        self.assertEqual(uncertain.status, "backend_unavailable")
        self.assertFalse(uncertain.mutation_confirmed)
        self.assert_no_auth(uncertain)
        before = self.raw.get(self.keys[0])
        self.assertIsNotNone(before)
        self.assert_counters()
        replay = self.issue(op, now_ts=1060)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_issued")
        self.assertFalse(replay.mutation_confirmed)
        self.assert_no_auth(replay)
        self.assertEqual(self.raw.get(self.keys[0]), before)
        self.assert_counters()

    def test_lost_correct_consume_ack_retry_same_op_only_observes_ledger(self):
        self.assertEqual(self.issue(uuid4().hex).status, "synthetic_issued")
        op = uuid4().hex
        execute = Pipeline.execute
        def commit_then_lose(pipe, *args, **kwargs):
            execute(pipe, *args, **kwargs)
            raise TimeoutError("fake verify consumed, acknowledgement lost")
        with patch.object(Pipeline, "execute", commit_then_lose):
            uncertain = self.verify(op)
        self.assertEqual(uncertain.status, "backend_unavailable")
        self.assert_no_auth(uncertain)
        self.assertIsNone(self.raw.get(self.keys[0]))
        replay = self.verify(op)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_single_winner")
        self.assert_no_auth(replay)
        self.assertEqual(self.verify(uuid4().hex).status, "missing")

    def test_operation_identifier_reuse_with_different_digest_is_denied(self):
        op = uuid4().hex
        self.assertEqual(self.issue(op).status, "synthetic_issued")
        record_before = self.raw.get(self.keys[0])
        ledger_before = self.raw.get(self.ledger(op))
        mismatch = self.issue(op, code="654321")
        self.assertEqual(mismatch.status, "operation_reuse_conflict")
        self.assert_no_auth(mismatch)
        self.assertEqual(self.raw.get(self.keys[0]), record_before)
        self.assertEqual(self.raw.get(self.ledger(op)), ledger_before)
        self.assert_counters()

    def test_global_operation_id_cannot_switch_from_issue_to_verify(self):
        op = uuid4().hex
        self.assertEqual(self.issue(op).status, "synthetic_issued")
        wrong_kind = self.verify(op)
        self.assertEqual(wrong_kind.status, "operation_reuse_conflict")
        self.assertFalse(wrong_kind.mutation_confirmed)
        self.assert_no_auth(wrong_kind)
        self.assertIsNotNone(self.raw.get(self.keys[0]))
        self.assert_counters()

    def test_verification_operation_cannot_switch_digest_after_commit(self):
        self.assertEqual(self.issue(uuid4().hex).status, "synthetic_issued")
        op = uuid4().hex
        self.assertEqual(self.verify(op, code=BAD).status,
                         "synthetic_invalid_attempt")
        record_before = self.raw.get(self.keys[0])
        other_digest = self.verify(op, code=GOOD)
        self.assertEqual(other_digest.status, "operation_reuse_conflict")
        self.assertFalse(other_digest.mutation_confirmed)
        self.assert_no_auth(other_digest)
        self.assertEqual(self.raw.get(self.keys[0]), record_before)
        self.assertEqual(self.cache.get(f"record:app_login:{MOBILE}")["attempts"], 1)

    def test_corrupt_persistent_or_wrong_type_ledger_fails_closed(self):
        op = uuid4().hex
        key = self.ledger(op)
        self.raw.set(key, b"untrusted non-Django wire", ex=60)
        self.assertEqual(self.issue(op).status, "invalid_operation_ledger")
        self.assertIsNone(self.raw.get(self.keys[0]))
        self.raw.persist(key)
        self.assertEqual(self.issue(op).status, "invalid_operation_ledger")
        self.raw.delete(key)
        self.raw.hset(key, "not", "string")
        self.raw.pexpire(key, 60000)
        self.assertEqual(self.issue(op).status, "invalid_operation_ledger")
        self.raw.delete(key)
        self.cache.set(
            f"operation:synthetic:{op}",
            {"fingerprint": "a" * 64, "prior_status": "synthetic_issued",
             "remaining": True, "mobile_left": 1, "ip_left": 2},
            timeout=60,
        )
        self.assertEqual(self.issue(op).status, "invalid_operation_ledger")
        self.assertIsNone(self.raw.get(self.keys[0]))

    def test_concurrent_same_issue_operation_exactly_one_commit_then_replay(self):
        op = uuid4().hex
        barrier = Barrier(2, timeout=20)
        def contend():
            c = new_client()
            try:
                return self.issue(
                    op, cache=new_cache(self.fixture), client=c,
                    on_watched_read=lambda: barrier.wait(timeout=20),
                )
            finally:
                c.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(contend) for _ in range(2)]
            results = [f.result(timeout=25) for f in futures]
        self.assertEqual(
            sorted(r.status for r in results),
            ["concurrent_modification_conflict", "synthetic_issued"],
        )
        self.assertEqual(sum(r.mutation_confirmed for r in results), 1)
        replay = self.issue(op)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_issued")
        self.assert_counters()
        self.assert_no_auth(replay)

    def test_concurrent_same_wrong_verify_operation_one_attempt_then_replay(self):
        self.assertEqual(self.issue(uuid4().hex).status, "synthetic_issued")
        op = uuid4().hex
        barrier = Barrier(2, timeout=20)
        def contend():
            c = new_client()
            try:
                return self.verify(
                    op, code=BAD, cache=new_cache(self.fixture), client=c,
                    on_watched_read=lambda: barrier.wait(timeout=20),
                )
            finally:
                c.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(contend) for _ in range(2)]
            results = [f.result(timeout=25) for f in futures]
        self.assertEqual(
            sorted(x.status for x in results),
            ["concurrent_modification_conflict", "synthetic_invalid_attempt"],
        )
        replay = self.verify(op, code=BAD)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_invalid_attempt")
        self.assert_no_auth(replay)
        self.assertEqual(self.cache.get(f"record:app_login:{MOBILE}")["attempts"], 1)

    def test_distinct_wrong_operation_ids_each_charge_one_attempt(self):
        self.assertEqual(self.issue(uuid4().hex).status, "synthetic_issued")
        first = self.verify(uuid4().hex, code=BAD)
        second = self.verify(uuid4().hex, code=BAD)
        self.assertEqual(first.attempts_remaining, 4)
        self.assertEqual(second.attempts_remaining, 3)
        self.assertTrue(first.mutation_confirmed and second.mutation_confirmed)
        self.assertEqual(self.cache.get(f"record:app_login:{MOBILE}")["attempts"], 2)
        self.assert_no_auth(second)

    def test_replayed_old_verification_operation_does_not_touch_reissued_code(self):
        self.assertEqual(self.issue(uuid4().hex).status, "synthetic_issued")
        verify_op = uuid4().hex
        self.assertEqual(self.verify(verify_op).status, "synthetic_single_winner")
        # Test-only cooldown removal; rate counters stay within limits.
        self.raw.delete(self.keys[1])
        new_issue = self.issue(uuid4().hex, code="654321", now_ts=1051)
        self.assertEqual(new_issue.status, "synthetic_issued")
        newer = self.raw.get(self.keys[0])
        self.assert_counters(2, 2)
        replay = self.verify(verify_op, now_ts=1051)
        self.assertEqual(replay.status, "synthetic_replayed")
        self.assertEqual(replay.prior_status, "synthetic_single_winner")
        self.assert_no_auth(replay)
        self.assertEqual(self.raw.get(self.keys[0]), newer)
        self.assertEqual(self.verify(uuid4().hex, code="654321", now_ts=1051).status,
                         "synthetic_single_winner")
        self.assert_counters(2, 2)

    def test_scope_denies_non_ci_remote_wrong_db_and_invalid_operation_ids(self):
        op = uuid4().hex
        with patch.dict(os.environ, {"LOOMERA_PHASE724_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.issue(op)
        with self.assertRaises(ValueError):
            self.issue("unsafe-op")
        with self.assertRaises(ValueError):
            self.issue(True)
        with self.assertRaises(ValueError):
            self.verify(op, now_ts=True)
        with self.assertRaises(TypeError):
            self.issue(op, on_watched_read="invalid")
        wrong = redis.Redis.from_url("redis://127.0.0.1:6414/14")
        with self.assertRaises(RuntimeError):
            self.verify(op, client=wrong)
        self.assertIsNone(self.raw.get(self.keys[0]))

    def test_explicit_ledger_loss_invalidates_bounded_exactly_once_proof(self):
        op = uuid4().hex
        self.assertEqual(self.issue(op).status, "synthetic_issued")
        self.assert_counters()
        # Rehearse premature ledger loss + challenge/cooldown expiry ONLY in
        # the disposable synthetic Redis. Never assert global exactly-once.
        self.raw.delete(self.ledger(op), self.keys[0], self.keys[1])
        second = self.issue(op, now_ts=1051)
        self.assertEqual(second.status, "synthetic_issued")
        self.assertTrue(second.mutation_confirmed)
        self.assert_counters(2, 2)
        self.assert_no_auth(second)

    def test_physical_aof_restart_persists_ledger_and_prevents_double_charge(self):
        expected = (
            f"loomera-p722-{os.environ['GITHUB_RUN_ID']}-"
            f"{os.environ['GITHUB_RUN_ATTEMPT']}-redis"
        )
        self.assertEqual(os.environ.get("LOOMERA_PHASE724_CONTAINER"), expected)
        labels = json.loads(subprocess.check_output(
            ["docker", "inspect", "--format", "{{json .Config.Labels}}", expected],
            text=True, timeout=15,
        ))
        self.assertEqual(labels.get("loomera.phase723"), "synthetic")
        self.assertEqual(labels.get("loomera.phase724"), "idempotency-test")
        issue_op, wrong_op = uuid4().hex, uuid4().hex
        self.assertEqual(self.issue(issue_op).status, "synthetic_issued")
        self.assertEqual(self.verify(wrong_op, code=BAD).status,
                         "synthetic_invalid_attempt")
        original_record = self.raw.get(self.keys[0])
        original_ledgers = (
            self.raw.get(self.ledger(issue_op)),
            self.raw.get(self.ledger(wrong_op)),
        )
        self.assert_counters()
        subprocess.run(["docker", "stop", expected], check=True, timeout=30,
                       capture_output=True)
        try:
            self.assertEqual(self.issue(issue_op).status, "backend_unavailable")
            self.assertEqual(self.verify(wrong_op, code=BAD).status,
                             "backend_unavailable")
        finally:
            subprocess.run(["docker", "start", expected], check=True, timeout=30,
                           capture_output=True)
        for _ in range(80):
            try:
                if self.raw.ping():
                    break
            except redis.exceptions.RedisError:
                pass
            time.sleep(.1)
        else:
            self.fail("disposable Redis failed to recover after AOF restart")
        self.assertEqual(self.raw.get(self.keys[0]), original_record)
        self.assertEqual(self.raw.get(self.ledger(issue_op)), original_ledgers[0])
        self.assertEqual(self.raw.get(self.ledger(wrong_op)), original_ledgers[1])
        issued = self.issue(issue_op, now_ts=1052)
        wrong = self.verify(wrong_op, code=BAD, now_ts=1052)
        self.assertEqual(issued.status, "synthetic_replayed")
        self.assertEqual(wrong.status, "synthetic_replayed")
        self.assertEqual(issued.prior_status, "synthetic_issued")
        self.assertEqual(wrong.prior_status, "synthetic_invalid_attempt")
        self.assert_no_auth(issued)
        self.assert_no_auth(wrong)
        self.assertEqual(self.cache.get(f"record:app_login:{MOBILE}")["attempts"], 1)
        self.assert_counters()


if __name__ == "__main__":
    unittest.main(verbosity=2)
