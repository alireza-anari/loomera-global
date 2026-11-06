"""Real Redis 7 isolated multi-connection/process OTP atomicity rehearsal.

Run ONLY on GitHub's disposable Redis service, DB 15, with
LOOMERA_PHASE77_TEST_REDIS=1. All account numbers/OTP values are synthetic.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import multiprocessing
import os
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_atomic_redis_rehearsal import (
    ATOMIC_CONSUME_SCRIPT,
    ATOMIC_SEED_SCRIPT,
    AtomicRehearsalDecision,
    SyntheticRedisOtpRehearsal,
    SYNTHETIC_PREFIX,
)

REDIS_URL = "redis://127.0.0.1:6379/15"
MOBILE = "09123456789"  # Test fixture, not a real account
OTHER = "09123456780"
PURPOSE = "app_login"


def digest(*, mobile=MOBILE, code="123456", purpose=PURPOSE):
    """Synthetic HMAC protocol; does not match Django's live salted HMAC."""
    message = f"{purpose}:{mobile}:{code}".encode("ascii")
    return hmac.new(
        b"phase77-only-synthetic-unsafe-for-production",
        message, hashlib.sha256,
    ).hexdigest()


def independent_worker(url, key, barrier, result_queue):
    """Executed in separately spawned Python processes and Redis clients."""
    db = redis.Redis.from_url(url, decode_responses=False, socket_timeout=6)
    try:
        verifier = SyntheticRedisOtpRehearsal(db, key=key)
        barrier.wait(timeout=20)
        decision = verifier.consume(
            purpose=PURPOSE, legacy_mobile=MOBILE,
            code_digest=digest(), now_ts=1050,
        )
        result_queue.put((os.getpid(), decision.status, decision.authenticated))
    finally:
        db.close()


class RedisAtomicOtpRehearsalTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE77_TEST_REDIS") != "1":
            self.fail("An explicitly enabled ephemeral Redis CI service is required")
        self.client = redis.Redis.from_url(
            REDIS_URL, decode_responses=False, socket_timeout=6,
        )
        self.assertTrue(self.client.ping())
        self.key = SYNTHETIC_PREFIX + uuid4().hex
        self.otp = SyntheticRedisOtpRehearsal(self.client, key=self.key)

    def tearDown(self):
        try:
            self.otp.synthetic_cleanup()
        finally:
            self.client.close()

    def _seed(self, *, mobile=MOBILE, code="123456", limit=3):
        self.assertTrue(self.otp.seed(
            purpose=PURPOSE, legacy_mobile=mobile,
            code_digest=digest(mobile=mobile, code=code),
            expires_at=1120, now_ts=1000,
            max_attempts=limit,
        ))

    def _consume(self, *, mobile=MOBILE, code="123456", purpose=PURPOSE,
                 at=1050):
        return self.otp.consume(
            purpose=purpose, legacy_mobile=mobile,
            code_digest=digest(mobile=mobile, code=code, purpose=purpose),
            now_ts=at,
        )

    def test_connection_is_isolated_db15_and_no_global_flush(self):
        info = self.client.connection_pool.connection_kwargs
        self.assertEqual(info["db"], 15)
        self.assertEqual(info["host"], "127.0.0.1")
        self.assertTrue(self.key.startswith(SYNTHETIC_PREFIX))
        self.assertNotIn(MOBILE, self.key)

    def test_atomic_happy_path_consumes_once_and_replay_is_missing(self):
        self._seed()
        original = self.client.hgetall(self.key)
        self.assertNotIn(b"code", original)
        self.assertEqual(original[b"code_digest"].decode(), digest())
        self.assertNotIn(b"123456", original.values())
        first = self._consume()
        second = self._consume()
        self.assertEqual(first.status, "consumed")
        self.assertEqual(second.status, "missing")
        self.assertFalse(first.authenticated)
        self.assertFalse(self.client.exists(self.key))

    def test_duplicate_seed_does_not_replace_code_or_reset_attempts(self):
        self._seed()
        self.assertEqual(self._consume(code="000000").status, "invalid")
        before = self.client.hgetall(self.key)
        ttl = self.client.pttl(self.key)
        self.assertFalse(self.otp.seed(
            purpose=PURPOSE, legacy_mobile=MOBILE,
            code_digest=digest(code="999999"), expires_at=1200,
            now_ts=1000, max_attempts=10,
        ))
        self.assertEqual(self.client.hgetall(self.key), before)
        self.assertLessEqual(self.client.pttl(self.key), ttl)
        self.assertEqual(self._consume().status, "consumed")

    def test_wrong_attempts_atomic_aggregate_budget_and_exhaustion(self):
        self._seed(limit=3)
        self.assertEqual(self._consume(code="000000"),
                         AtomicRehearsalDecision("invalid", 2))
        self.assertEqual(self._consume(code="111111"),
                         AtomicRehearsalDecision("invalid", 1))
        self.assertEqual(self._consume(code="222222").status, "exhausted")
        self.assertEqual(self._consume().status, "missing")
        self.assertFalse(self.client.exists(self.key))

    def test_expired_challenge_is_deleted_without_consume(self):
        self._seed()
        self.assertEqual(self._consume(at=1120).status, "expired")
        self.assertEqual(self._consume(at=1120).status, "missing")

    def test_wrong_mobile_or_purpose_never_mutates_original_challenge(self):
        self._seed()
        for kwargs in (
            {"mobile": OTHER}, {"purpose": "password_reset"},
        ):
            # The future adapter cannot pass an unapproved purpose through
            # the public helper. A binding mismatch can still be rehearsed
            # directly by asking the Lua script with a different purpose.
            if kwargs.get("purpose"):
                response = self.client.eval(
                    ATOMIC_CONSUME_SCRIPT, 1, self.key,
                    "password_reset", MOBILE, digest(), 1050,
                )
                status = response[0].decode()
            else:
                status = self._consume(**kwargs).status
            self.assertEqual(status, "bound_mismatch")
        self.assertEqual(self.client.hget(self.key, "attempts"), b"0")
        self.assertEqual(self._consume().status, "consumed")

    def test_invalid_record_syntax_fails_closed(self):
        self._seed()
        self.client.hset(self.key, "attempts", "not-an-integer")
        self.assertEqual(self._consume().status, "invalid_record")
        self.assertTrue(self.client.exists(self.key))

    def test_two_independent_redis_clients_one_success_under_thread_race(self):
        self._seed()
        gate = Barrier(3, timeout=20)

        def contender():
            client = redis.Redis.from_url(
                REDIS_URL, decode_responses=False, socket_timeout=6,
            )
            try:
                consumer = SyntheticRedisOtpRehearsal(client, key=self.key)
                gate.wait(timeout=20)
                return consumer.consume(
                    purpose=PURPOSE, legacy_mobile=MOBILE,
                    code_digest=digest(), now_ts=1050,
                ).status
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(contender)
            b = pool.submit(contender)
            gate.wait(timeout=20)
            statuses = [a.result(timeout=20), b.result(timeout=20)]
        self.assertEqual(sorted(statuses), ["consumed", "missing"])
        self.assertFalse(self.client.exists(self.key))

    def test_two_spawned_worker_processes_cannot_both_consume(self):
        self._seed()
        ctx = multiprocessing.get_context("spawn")
        gate = ctx.Barrier(3, timeout=20)
        queue = ctx.Queue()
        processes = [
            ctx.Process(
                target=independent_worker,
                args=(REDIS_URL, self.key, gate, queue),
            ) for _ in range(2)
        ]
        try:
            for process in processes:
                process.start()
            gate.wait(timeout=20)
            results = [queue.get(timeout=25), queue.get(timeout=25)]
            self.assertEqual(len({r[0] for r in results}), 2)
            self.assertEqual(sorted(r[1] for r in results),
                             ["consumed", "missing"])
            self.assertEqual([r[2] for r in results], [False, False])
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=5)
            queue.close()
            queue.join_thread()

    def test_concurrent_wrong_codes_do_not_lose_attempt_counts(self):
        self._seed(limit=3)
        gate = Barrier(4, timeout=20)

        def wrong(code):
            client = redis.Redis.from_url(REDIS_URL, socket_timeout=6)
            try:
                gate.wait(timeout=20)
                return SyntheticRedisOtpRehearsal(client, key=self.key).consume(
                    purpose=PURPOSE, legacy_mobile=MOBILE,
                    code_digest=digest(code=code), now_ts=1050,
                ).status
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(wrong, s) for s in ("000000", "111111", "222222")]
            gate.wait(timeout=20)
            statuses = [j.result(timeout=20) for j in jobs]
        self.assertEqual(sorted(statuses), ["exhausted", "invalid", "invalid"])
        self.assertEqual(self._consume().status, "missing")

    def test_two_different_owners_using_same_code_cannot_share_challenge(self):
        self._seed(mobile=MOBILE)
        self.assertEqual(self._consume(mobile=OTHER).status, "bound_mismatch")
        self.assertEqual(self._consume().status, "consumed")

    def test_ambiguous_post_commit_timeout_never_returns_success(self):
        self._seed()

        class CommitThenLoseResponse:
            def __init__(self, real):
                self.connection_pool = real.connection_pool
                self.real = real

            def eval(self, *args):
                self.real.eval(*args)
                raise redis.exceptions.TimeoutError("synthetic packet loss")

        consumer = SyntheticRedisOtpRehearsal(
            CommitThenLoseResponse(self.client), key=self.key,
        )
        outcome = consumer.consume(
            purpose=PURPOSE, legacy_mobile=MOBILE,
            code_digest=digest(), now_ts=1050,
        )
        self.assertEqual(outcome.status, "backend_unavailable")
        self.assertFalse(outcome.authenticated)
        self.assertEqual(self._consume().status, "missing")

    def test_unconfirmed_delete_or_unknown_script_response_never_success(self):
        for fake in (
            [b"delete_unconfirmed", b"0"],
            [b"unexpected", b"0"],
            [b"consumed", b"not-a-number"],
            [b"consumed", b"1"],
            True,
        ):
            class ScriptResponse:
                connection_pool = self.client.connection_pool

                def eval(self, *args):
                    return fake

            v = SyntheticRedisOtpRehearsal(
                ScriptResponse(), key=self.key,
            ).consume(
                purpose=PURPOSE, legacy_mobile=MOBILE,
                code_digest=digest(), now_ts=1050,
            )
            self.assertNotEqual(v.status, "consumed")
            self.assertFalse(v.authenticated)

    def test_unknown_network_failure_is_always_fail_closed(self):
        class NetworkFailure:
            connection_pool = self.client.connection_pool

            def eval(self, *args):
                raise redis.exceptions.ConnectionError("synthetic unavailable")

        d = SyntheticRedisOtpRehearsal(
            NetworkFailure(), key=self.key,
        ).consume(
            purpose=PURPOSE, legacy_mobile=MOBILE,
            code_digest=digest(), now_ts=1050,
        )
        self.assertEqual(d.status, "backend_unavailable")
        self.assertFalse(d.authenticated)

    def test_authorization_guard_rejects_remote_database_or_wrong_prefix(self):
        for url in (
            "redis://127.0.0.1:6379/14",
            "redis://remote.example:6379/15",
        ):
            remote = redis.Redis.from_url(url)
            with self.subTest(url=url):
                with self.assertRaises(RuntimeError):
                    SyntheticRedisOtpRehearsal(remote, key=self.key)
        with self.assertRaises(ValueError):
            SyntheticRedisOtpRehearsal(
                self.client, key="loomera:api-auth-otp:record:app_login:bad",
            )
        with patch.dict(os.environ, {"LOOMERA_PHASE77_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                SyntheticRedisOtpRehearsal(self.client, key=self.key)

    def test_invalid_arguments_rejected_before_redis_mutation(self):
        self._seed()
        before = self.client.hgetall(self.key)
        for kwargs in (
            {"legacy_mobile": "+989123456789"},
            {"legacy_mobile": "98000000001"},
            {"purpose": "web_signup"},
            {"code_digest": "123456"},
            {"code_digest": True},
            {"now_ts": True},
            {"now_ts": -1},
        ):
            params = {
                "purpose": PURPOSE,
                "legacy_mobile": MOBILE,
                "code_digest": digest(),
                "now_ts": 1050,
            }
            params.update(kwargs)
            with self.subTest(param=next(iter(kwargs))):
                with self.assertRaises(ValueError):
                    self.otp.consume(**params)
        self.assertEqual(self.client.hgetall(self.key), before)

    def test_seed_rejects_unbounded_or_malformed_historical_challenge(self):
        for args in (
            {"max_attempts": True},
            {"max_attempts": 0},
            {"max_attempts": 11},
            {"expires_at": 1000},
            {"expires_at": 5000},
            {"now_ts": True},
        ):
            params = dict(
                purpose=PURPOSE, legacy_mobile=MOBILE,
                code_digest=digest(), expires_at=1120,
                now_ts=1000, max_attempts=3,
            )
            params.update(args)
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    self.otp.seed(**params)
        self.assertFalse(self.client.exists(self.key))

    def test_script_and_results_are_strictly_synthetic_contract_only(self):
        self.assertIn("HMGET", ATOMIC_CONSUME_SCRIPT)
        self.assertIn("HINCRBY", ATOMIC_CONSUME_SCRIPT)
        self.assertIn("redis.call('DEL'", ATOMIC_CONSUME_SCRIPT)
        self.assertIn("EXISTS", ATOMIC_SEED_SCRIPT)
        self.assertNotIn("FLUSHDB", ATOMIC_CONSUME_SCRIPT)
        self.assertNotIn("FLUSHALL", ATOMIC_SEED_SCRIPT)
        self._seed()
        out = self._consume()
        data = json.dumps(out.__dict__) if hasattr(out, "__dict__") else (
            f"{out.status},{out.attempts_remaining},{out.authenticated}"
        )
        for secret in (MOBILE, "123456", digest(), self.key):
            self.assertNotIn(secret, data)


if __name__ == "__main__":
    unittest.main()
