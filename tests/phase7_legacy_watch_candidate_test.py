"""Phase 7.20 real Redis + actual django-redis 5.4 legacy wire WATCH tests.

A candidate negative preflight on 127.0.0.1:6412 DB15, never real login.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="phase720-only-test-key-never-production")

import redis
from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache

from loomera.globalization.otp_legacy_watch_candidate import (
    PREFIX, REDIS_URL, WatchCandidateEvidence,
    attempt_synthetic_watch_consume, validate_synthetic_scope,
)

MOBILE = "09123456789"  # fabricated, no customer data
LOGICAL = f"record:app_login:{MOBILE}"
CODE = "123456"  # synthetic only


def digest(code=CODE):
    return salted_hmac(
        "loomera.api.auth.otp", f"app_login:{MOBILE}:{code}",
    ).hexdigest()


def record(code=CODE, **extra):
    return {
        "purpose": "app_login",
        "mobile_number": MOBILE,
        "code_hash": digest(code),
        "created_at": 1000,
        "expires_at": 1120,
        "attempts": 0,
        "max_attempts": 5,
        "verified": False,
        "delivery": {"channel": "sms", "mode": "simulated", "sent": False,
                     "provider": "none"},
        **extra,
    }


def new_cache(fixture_id, *, url=REDIS_URL):
    return RedisCache(url, {
        "KEY_PREFIX": PREFIX + fixture_id,
        "VERSION": 1,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    })


class Phase720RealSerializedWatchCandidateTests(unittest.TestCase):
    def setUp(self):
        if (os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("LOOMERA_PHASE720_TEST_REDIS") != "1"
                or not os.environ.get("GITHUB_RUN_ID")):
            self.fail("explicit disposable CI-only Redis grant required")
        self.client = redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=2, socket_timeout=3,
        )
        self.assertTrue(self.client.ping())
        self.fixture_id = uuid4().hex
        self.cache = new_cache(self.fixture_id)
        self.physical = str(self.cache.make_key(LOGICAL))

    def tearDown(self):
        try:
            # Delete ONLY our known test fixture key; no flush, scan, wildcard.
            self.client.delete(self.physical)
        finally:
            self.client.close()

    def put(self, value=None, ttl=120):
        self.assertTrue(self.cache.set(
            LOGICAL, record() if value is None else value, timeout=ttl,
        ))

    def consume(self, *, cache=None, client=None, **changes):
        args = {
            "fixture_id": self.fixture_id,
            "logical_key": LOGICAL,
            "submitted_digest": digest(),
            "now_ts": 1050,
        }
        args.update(changes)
        return attempt_synthetic_watch_consume(
            self.cache if cache is None else cache,
            self.client if client is None else client,
            **args,
        )

    def assert_no_grant(self, outcome):
        self.assertIsInstance(outcome, WatchCandidateEvidence)
        for field in ("authenticated", "session_created",
                      "otp_production_consume_allowed",
                      "production_cutover_authorized",
                      "failover_fencing_proven",
                      "legacy_rate_limit_race_fixed",
                      "legacy_otp_replay_race_fixed"):
            self.assertFalse(getattr(outcome, field), field)
        for sensitive in (MOBILE, CODE, digest(), self.physical, "phase720-only-test-key"):
            self.assertNotIn(sensitive, repr(outcome))

    def test_real_django_redis_54_pickled_string_wire_single_consumer(self):
        self.put()
        self.assertEqual(self.client.type(self.physical), b"string")
        self.assertGreater(self.client.pttl(self.physical), 0)
        self.assertEqual(self.cache.get(LOGICAL), record())
        raw = self.client.get(self.physical)
        self.assertIsInstance(raw, bytes)
        self.assertEqual(self.cache.client.decode(raw), record())
        outcome = self.consume()
        self.assertEqual(outcome.status, "synthetic_single_winner")
        self.assertTrue(outcome.synthetic_record_deleted)
        self.assert_no_grant(outcome)
        self.assertEqual(self.client.type(self.physical), b"none")
        again = self.consume()
        self.assertEqual(again.status, "missing")
        self.assertFalse(again.synthetic_record_deleted)
        self.assert_no_grant(again)

    def test_two_independent_workers_watching_before_read_one_exact_winner(self):
        self.put()
        barrier = Barrier(2, timeout=20)

        def contend():
            c = redis.Redis.from_url(
                REDIS_URL, socket_connect_timeout=2, socket_timeout=5,
            )
            try:
                separate_cache = new_cache(self.fixture_id)
                return self.consume(
                    cache=separate_cache, client=c,
                    on_watched_read=lambda: barrier.wait(timeout=20),
                )
            finally:
                c.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(contend), pool.submit(contend)
            results = [a.result(timeout=20), b.result(timeout=20)]
        self.assertEqual(
            sorted(row.status for row in results),
            ["concurrent_modification_conflict", "synthetic_single_winner"],
        )
        self.assertEqual(sum(row.synthetic_record_deleted for row in results), 1)
        self.assertIsNone(self.cache.get(LOGICAL))
        for row in results:
            self.assert_no_grant(row)

    def test_identical_raw_bytes_reissue_after_watch_is_aba_conflict(self):
        """WATCH catches SET even when exact binary old/new payloads match."""
        self.put()
        before = self.client.get(self.physical)

        def same_bytes_reissue():
            self.assertTrue(self.client.set(
                self.physical, before, px=120000,
            ))

        result = self.consume(on_watched_read=same_bytes_reissue)
        self.assertEqual(result.status, "concurrent_modification_conflict")
        self.assertFalse(result.synthetic_record_deleted)
        self.assertEqual(self.client.get(self.physical), before)
        self.assert_no_grant(result)

    def test_new_generation_with_new_digest_after_watch_not_deleted(self):
        self.put()
        def rotate_generation():
            self.put(record(code="654321"))
        result = self.consume(on_watched_read=rotate_generation)
        self.assertEqual(result.status, "concurrent_modification_conflict")
        self.assertEqual(self.cache.get(LOGICAL)["code_hash"], digest("654321"))
        self.assert_no_grant(result)

    def test_wrong_digest_does_not_mutate_bytes_or_attempts(self):
        self.put()
        original = self.client.get(self.physical)
        before = self.client.pttl(self.physical)
        result = self.consume(submitted_digest=digest("000000"))
        self.assertEqual(result.status, "wrong_digest")
        self.assertFalse(result.synthetic_record_deleted)
        self.assertEqual(self.client.get(self.physical), original)
        self.assertLessEqual(self.client.pttl(self.physical), before)
        self.assertEqual(self.cache.get(LOGICAL)["attempts"], 0)
        self.assert_no_grant(result)

    def test_exhausted_expired_future_unverified_payloads_denied(self):
        for payload in (
            record(attempts=5),
            record(expires_at=1049),
            record(created_at=1070),
            record(verified=True),
            record(created_at=True),
            record(expires_at=False),
            record(max_attempts=0),
            record(max_attempts=11),
            record(purpose="password_reset"),
            record(mobile_number="09123456780"),
            record(code_hash="plaintext"),
            {"purpose": "app_login"},
        ):
            with self.subTest(payload=tuple(payload.keys())):
                self.put(payload)
                original = self.client.get(self.physical)
                result = self.consume()
                self.assertEqual(result.status, "invalid_record")
                self.assertEqual(self.client.get(self.physical), original)
                self.assert_no_grant(result)

    def test_no_ttl_and_wrong_type_denied_without_writes(self):
        self.put()
        self.assertTrue(self.client.persist(self.physical))
        result = self.consume()
        self.assertEqual(result.status, "invalid_ttl")
        self.assert_no_grant(result)
        self.assertEqual(self.client.type(self.physical), b"string")
        self.client.delete(self.physical)
        self.client.hset(self.physical, "purpose", "app_login")
        self.client.pexpire(self.physical, 120000)
        result = self.consume()
        self.assertEqual(result.status, "wrong_redis_type")
        self.assert_no_grant(result)
        self.assertEqual(self.client.type(self.physical), b"hash")

    def test_corrupt_wire_and_non_dict_string_denied(self):
        self.client.set(self.physical, b"not a Django-Redis cache object", ex=120)
        result = self.consume()
        self.assertEqual(result.status, "invalid_wire")
        self.assert_no_grant(result)
        self.assertIsNotNone(self.client.get(self.physical))
        self.put("plaintext instead of dict")
        result = self.consume()
        self.assertEqual(result.status, "invalid_record")
        self.assert_no_grant(result)

    def test_timeout_hook_failure_is_backend_unavailable_not_fallback(self):
        self.put()
        original = self.client.get(self.physical)
        def interrupted():
            raise TimeoutError("synthetic paused test only")
        result = self.consume(on_watched_read=interrupted)
        self.assertEqual(result.status, "backend_unavailable")
        self.assert_no_grant(result)
        self.assertEqual(self.client.get(self.physical), original)

    def test_real_legacy_resend_and_rate_records_untouched(self):
        self.put()
        resend = "resend:app_login:" + MOBILE
        rate = "rate:mobile:synthetic:1000"
        self.cache.set(resend, 1000, timeout=60)
        self.cache.set(rate, 3, timeout=3600)
        try:
            self.assertEqual(self.consume().status, "synthetic_single_winner")
            self.assertEqual(self.cache.get(resend), 1000)
            self.assertEqual(self.cache.get(rate), 3)
        finally:
            # Exact fixture-owned keys only.
            self.cache.delete(resend)
            self.cache.delete(rate)

    def test_denied_env_remote_cache_wrong_db_and_wrong_prefix_before_io(self):
        self.put()
        with patch.dict(os.environ, {"LOOMERA_PHASE720_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.consume()
        for broken in (
            new_cache(uuid4().hex),
            new_cache(self.fixture_id, url="redis://remote.invalid:6412/15"),
        ):
            with self.assertRaises(RuntimeError):
                self.consume(cache=broken)
        wrong_db = redis.Redis.from_url("redis://127.0.0.1:6412/14")
        with self.assertRaises(RuntimeError):
            self.consume(client=wrong_db)
        with self.assertRaises(ValueError):
            self.consume(logical_key="record:app_login:+989123456789")
        with self.assertRaises(ValueError):
            self.consume(fixture_id="not-a-uuid")
        with self.assertRaises(ValueError):
            self.consume(submitted_digest="not-a-digest")
        with self.assertRaises(ValueError):
            self.consume(now_ts=True)
        with self.assertRaises(TypeError):
            self.consume(on_watched_read="fake")
        self.assertIsNotNone(self.client.get(self.physical))

    def test_validate_scope_is_same_exact_physical_django_key(self):
        self.put()
        self.assertEqual(
            validate_synthetic_scope(
                self.cache, self.client,
                fixture_id=self.fixture_id, logical_key=LOGICAL,
            ),
            self.physical,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
