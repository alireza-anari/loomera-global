"""Phase 7.35 real Redis tests of the OFF-by-default live-compatible CAS.

Only disposable Phase 7.21 Redis at 127.0.0.1:6413/15, with independent
random synthetic Phase 7.35 keys. No Django auth, users, sessions or SMS.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, current_thread, main_thread
import os
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="phase735-synthetic-hmac-only-not-production")

from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache
import redis
from redis.client import Pipeline

from apps.api.v1.otp_atomic_verify import (
    AtomicOtpOutcome,
    atomic_verify_legacy_record,
)

REDIS_URL = "redis://127.0.0.1:6413/15"
PREFIX = "loomera:phase735:synthetic-only:"
MOBILE = "09123456789"
PURPOSE = "app_login"
LOGICAL = "loomera:phase735:record:app_login:" + MOBILE
GOOD_CODE = "123456"
OTHER_CODE = "654321"
BAD_CODE = "000000"


def digest(code):
    return salted_hmac(
        "loomera.api.auth.otp", f"{PURPOSE}:{MOBILE}:{code}",
    ).hexdigest()


class Phase735LiveAtomicLegacyRedisTests(unittest.TestCase):
    def setUp(self):
        if (
            os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")
            or os.environ.get("LOOMERA_PHASE721_TEST_REDIS") != "1"
            or os.environ.get("LOOMERA_PHASE735_TEST_REDIS") != "1"
        ):
            self.fail("Phase 7.35 must run in explicitly granted disposable CI")
        self.raw = redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=2, socket_timeout=5,
        )
        self.assertTrue(self.raw.ping())
        self.fixture_id = uuid4().hex
        self.cache = RedisCache(REDIS_URL, {
            "KEY_PREFIX": PREFIX + self.fixture_id,
            "VERSION": 1,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        })
        self.physical = str(self.cache.make_key(LOGICAL))
        self.assertEqual(
            self.physical, PREFIX + self.fixture_id + ":1:" + LOGICAL
        )
        self.now = int(time.time())
        self.seed()

    def tearDown(self):
        try:
            # Delete ONLY this test's exact known key: no scan, flush or wildcard.
            self.raw.delete(self.physical)
        finally:
            self.raw.close()

    def record(self, code=GOOD_CODE, **overrides):
        payload = {
            "purpose": PURPOSE,
            "mobile_number": MOBILE,
            "code_hash": digest(code),
            "created_at": self.now - 5,
            "expires_at": self.now + 120,
            "attempts": 0,
            "max_attempts": 3,
            "verified": False,
            "delivery": {
                "channel": "sms", "mode": "simulated",
                "sent": False, "provider": "none",
            },
        }
        payload.update(overrides)
        return payload

    def seed(self, record=None):
        self.assertTrue(self.cache.set(
            LOGICAL,
            self.record() if record is None else record,
            timeout=120,
        ))

    def transition(self, code=GOOD_CODE, **overrides):
        options = {
            "cache_backend": self.cache,
            "logical_key": LOGICAL,
            "mobile_number": MOBILE,
            "purpose": PURPOSE,
            "submitted_hash": digest(code),
            "now_ts": self.now,
            "ttl_seconds": 120,
        }
        options.update(overrides)
        result = atomic_verify_legacy_record(**options)
        self.assertIsInstance(result, AtomicOtpOutcome)
        self.assertNotIn(MOBILE, repr(result))
        self.assertNotIn(digest(code), repr(result))
        self.assertNotIn(self.physical, repr(result))
        return result

    def test_true_legacy_pickled_string_roundtrip_and_exact_successful_delete(self):
        raw = self.raw.get(self.physical)
        self.assertIs(type(raw), bytes)
        self.assertEqual(self.raw.type(self.physical), b"string")
        self.assertEqual(self.cache.client.decode(raw), self.record())
        first = self.transition()
        self.assertEqual(first.status, "verified")
        self.assertIs(first.record["verified"], True)
        self.assertFalse(self.raw.exists(self.physical))
        self.assertEqual(self.transition().status, "missing")

    def test_wrong_attempt_increments_without_ttl_extension_then_consumes(self):
        initial = self.raw.pttl(self.physical)
        wrong = self.transition(code=BAD_CODE)
        self.assertEqual((wrong.status, wrong.attempts_remaining), ("wrong", 2))
        record = self.cache.get(LOGICAL)
        self.assertEqual(record["attempts"], 1)
        self.assertEqual(record["delivery"], self.record()["delivery"])
        self.assertLessEqual(self.raw.pttl(self.physical), initial + 20)
        self.assertEqual(self.transition().status, "verified")

    def test_last_wrong_attempt_deletes_and_exhausts(self):
        self.seed(self.record(attempts=2, max_attempts=3))
        self.assertEqual(self.transition(code=BAD_CODE).status, "exhausted")
        self.assertEqual(self.raw.exists(self.physical), 0)
        self.assertEqual(self.transition().status, "missing")

    def test_missing_expired_exhausted_and_corrupt_records_do_not_grant(self):
        self.raw.delete(self.physical)
        self.assertEqual(self.transition().status, "missing")
        self.seed(self.record(expires_at=self.now - 1))
        self.assertEqual(self.transition().status, "expired")
        self.seed(self.record(attempts=3))
        self.assertEqual(self.transition().status, "exhausted")
        self.seed(self.record(mobile_number="09000000000"))
        self.assertEqual(self.transition().status, "unavailable")
        self.seed(self.record(code_hash="not-a-valid-digest"))
        self.assertEqual(self.transition().status, "unavailable")
        self.assertTrue(self.raw.exists(self.physical))

    def test_invalid_wire_type_and_permanent_ttl_never_authorize(self):
        self.raw.set(self.physical, b"not-pickled")
        self.assertEqual(self.transition().status, "unavailable")
        self.raw.delete(self.physical)
        self.raw.hset(self.physical, "field", "value")
        self.assertEqual(self.transition().status, "unavailable")
        self.raw.delete(self.physical)
        self.seed()
        self.assertTrue(self.raw.persist(self.physical))
        self.assertEqual(self.transition().status, "unavailable")

    def test_two_correct_workers_have_exactly_one_confirmed_delete(self):
        gate = Barrier(2, timeout=15)
        original = Pipeline.get

        def observed(pipe, key, *args, **kwargs):
            result = original(pipe, key, *args, **kwargs)
            if str(key) == self.physical:
                gate.wait(timeout=15)
            return result

        with (
            patch.object(Pipeline, "get", observed),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [pool.submit(self.transition) for _ in range(2)]
            states = sorted(f.result(timeout=22).status for f in futures)
        self.assertEqual(states, ["unavailable", "verified"])
        self.assertEqual(self.raw.exists(self.physical), 0)

    def test_two_wrong_workers_charge_exactly_one_attempt(self):
        gate = Barrier(2, timeout=15)
        original = Pipeline.get

        def observed(pipe, key, *args, **kwargs):
            result = original(pipe, key, *args, **kwargs)
            if str(key) == self.physical:
                gate.wait(timeout=15)
            return result

        with (
            patch.object(Pipeline, "get", observed),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [
                pool.submit(self.transition, code=BAD_CODE) for _ in range(2)
            ]
            states = sorted(f.result(timeout=22).status for f in futures)
        self.assertEqual(states, ["unavailable", "wrong"])
        self.assertEqual(self.cache.get(LOGICAL)["attempts"], 1)

    def reissue_during_watch(self, new_record):
        observed = Event()
        resume = Event()
        original = Pipeline.get

        def paused_after_get(pipe, key, *args, **kwargs):
            value = original(pipe, key, *args, **kwargs)
            if str(key) == self.physical and current_thread() is not main_thread():
                observed.set()
                if not resume.wait(timeout=15):
                    raise RuntimeError("fixture barrier timed out")
            return value

        with (
            patch.object(Pipeline, "get", paused_after_get),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(self.transition)
            try:
                self.assertTrue(observed.wait(timeout=12))
                self.seed(new_record)
            finally:
                resume.set()
            result = future.result(timeout=20)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(self.cache.get(LOGICAL), new_record)

    def test_identical_byte_reissue_never_consumed_by_stale_verifier(self):
        original = self.record()
        self.reissue_during_watch(original)
        self.assertEqual(self.transition().status, "verified")

    def test_new_generation_reissue_survives_stale_correct_verifier(self):
        new_record = self.record(code=OTHER_CODE)
        self.reissue_during_watch(new_record)
        self.assertEqual(self.transition(code=OTHER_CODE).status, "verified")

    def test_lost_exec_ack_cannot_be_misreported_as_verified(self):
        real_execute = Pipeline.execute

        def commit_then_lose_reply(pipe, *args, **kwargs):
            real_execute(pipe, *args, **kwargs)
            raise ConnectionError("simulated private response loss")

        with patch.object(Pipeline, "execute", commit_then_lose_reply):
            response = self.transition()
        self.assertEqual(response.status, "unavailable")
        self.assertEqual(self.raw.exists(self.physical), 0)

    def test_invalid_backend_and_parameters_fail_before_network(self):
        denied = atomic_verify_legacy_record(
            cache_backend=object(), logical_key=LOGICAL,
            mobile_number=MOBILE, purpose=PURPOSE,
            submitted_hash=digest(GOOD_CODE), now_ts=self.now,
            ttl_seconds=120,
        )
        self.assertEqual(denied.status, "unavailable")
        self.assertEqual(
            self.transition(ttl_seconds=0).status, "unavailable"
        )
        self.assertEqual(
            self.transition(submitted_hash="invalid").status, "unavailable"
        )
        self.assertTrue(self.raw.exists(self.physical))


if __name__ == "__main__":
    unittest.main()
