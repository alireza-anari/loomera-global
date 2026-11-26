"""Phase 7.36 real Redis 7.4 four-key atomic issue tests.

CI-only with the existing disposable Phase 7.22 Redis 127.0.0.1:6414 DB15.
All mobile/IP data are synthetic. No production cache, sessions or SMS.
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
    settings.configure(SECRET_KEY="phase736-throwaway-signing-key-not-production")

from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache
import redis
from redis.client import Pipeline

from apps.api.v1.otp_atomic_issue import (
    AtomicOtpIssueOutcome, atomic_issue_legacy_record,
)

REDIS_URL = "redis://127.0.0.1:6414/15"
PREFIX = "loomera:phase736:synthetic-issue-only:"
MOBILE = "09123456789"
MOBILES = ("09123456780", "09123456781", "09123456782")
IP = "192_0_2_17"
OTHER_IP = "192_0_2_18"
GOOD_CODE = "123456"


def digest(mobile=MOBILE):
    return salted_hmac(
        "loomera.api.auth.otp", f"app_login:{mobile}:{GOOD_CODE}"
    ).hexdigest()


class Phase736AtomicIssueRealRedisTests(unittest.TestCase):
    def setUp(self):
        if (
            os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")
            or os.environ.get("LOOMERA_PHASE722_TEST_REDIS") != "1"
            or os.environ.get("LOOMERA_PHASE736_TEST_REDIS") != "1"
        ):
            self.fail("Phase 7.36 requires explicitly granted disposable GitHub CI")
        self.id = uuid4().hex
        self.cache = RedisCache(REDIS_URL, {
            "KEY_PREFIX": PREFIX + self.id,
            "VERSION": 1,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        })
        self.raw = redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=2, socket_timeout=5
        )
        self.assertTrue(self.raw.ping())
        self.now = int(time.time())
        self.known_keys = set()

    def tearDown(self):
        try:
            # Only exact fixture keys; never scan, flush or delete user data.
            if self.known_keys:
                self.raw.delete(*sorted(self.known_keys))
        finally:
            self.raw.close()

    def keys(self, mobile=MOBILE, ip=IP, now_ts=None):
        now_ts = self.now if now_ts is None else now_ts
        logical = (
            f"loomera:api-auth-otp:record:app_login:{mobile}",
            f"loomera:api-auth-otp:resend:app_login:{mobile}",
            f"loomera:api-auth-otp:rate:mobile:app_login_{mobile}:{now_ts // 3600}",
            f"loomera:api-auth-otp:rate:ip:app_login_{ip}:{now_ts // 3600}",
        )
        physical = tuple(str(self.cache.make_key(key)) for key in logical)
        self.known_keys.update(physical)
        self.assertEqual(len(set(physical)), 4)
        return logical, physical

    def record(self, mobile=MOBILE, now_ts=None, **overrides):
        now_ts = self.now if now_ts is None else now_ts
        record = {
            "purpose": "app_login",
            "mobile_number": mobile,
            "code_hash": digest(mobile),
            "created_at": now_ts,
            "expires_at": now_ts + 120,
            "attempts": 0,
            "max_attempts": 5,
            "verified": False,
            "delivery": {
                "channel": "sms", "mode": "simulated",
                "sent": False, "provider": "none",
            },
        }
        record.update(overrides)
        return record

    def issue(self, *, mobile=MOBILE, ip=IP, now_ts=None, mobile_limit=2,
              ip_limit=3, backend=None, logical_keys=None, **kwargs):
        now_ts = self.now if now_ts is None else now_ts
        default_keys, _ = self.keys(mobile=mobile, ip=ip, now_ts=now_ts)
        result = atomic_issue_legacy_record(
            cache_backend=self.cache if backend is None else backend,
            logical_keys=default_keys if logical_keys is None else logical_keys,
            record=self.record(mobile=mobile, now_ts=now_ts),
            now_ts=now_ts,
            record_ttl_seconds=120,
            resend_ttl_seconds=60,
            mobile_hour_limit=mobile_limit,
            ip_hour_limit=ip_limit,
            **kwargs,
        )
        self.assertIsInstance(result, AtomicOtpIssueOutcome)
        for forbidden in (
            mobile, GOOD_CODE, digest(mobile),
            self.id, "phase736-throwaway-signing-key-not-production",
        ):
            self.assertNotIn(forbidden, repr(result))
        return result

    def clear_challenge(self, mobile=MOBILE, ip=IP, now_ts=None):
        _, physical = self.keys(mobile=mobile, ip=ip, now_ts=now_ts)
        self.raw.delete(physical[0], physical[1])

    def test_four_keys_commit_as_one_legacy_wire_transaction(self):
        result = self.issue()
        self.assertEqual(result.status, "issued")
        _, physical = self.keys()
        self.assertEqual(self.raw.type(physical[0]), b"string")
        record = self.cache.client.decode(self.raw.get(physical[0]))
        self.assertEqual(record, self.record())
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[1])), self.now)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[2])), 1)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[3])), 1)
        for key, limit in zip(physical, (120, 60, 3600, 3600)):
            ttl = self.raw.pttl(key)
            self.assertGreater(ttl, 0)
            self.assertLessEqual(ttl, limit * 1000)
        self.assertNotIn("code", record)

    def test_live_challenge_blocks_after_cooldown_expires_without_quota_charge(self):
        self.assertEqual(self.issue().status, "issued")
        _, physical = self.keys()
        self.raw.delete(physical[1])
        again = self.issue()
        self.assertEqual(again.status, "challenge_pending")
        self.assertGreater(again.retry_after, 0)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[2])), 1)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[3])), 1)

    def test_cooldown_without_record_blocks_and_does_not_charge(self):
        self.assertEqual(self.issue().status, "issued")
        _, physical = self.keys()
        self.raw.delete(physical[0])
        again = self.issue()
        self.assertEqual(again.status, "resend_limited")
        self.assertGreater(again.retry_after, 0)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[2])), 1)

    def test_reissue_after_clearing_record_and_cooldown_keeps_rate_ttl(self):
        self.assertEqual(self.issue().status, "issued")
        _, physical = self.keys()
        prev_ttl = self.raw.pttl(physical[2])
        self.clear_challenge()
        self.assertEqual(self.issue().status, "issued")
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[2])), 2)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[3])), 2)
        self.assertLessEqual(self.raw.pttl(physical[2]), prev_ttl + 20)

    def test_mobile_quota_enforced_without_extra_write(self):
        self.assertEqual(self.issue(mobile_limit=2).status, "issued")
        self.clear_challenge()
        self.assertEqual(self.issue(mobile_limit=2).status, "issued")
        self.clear_challenge()
        denied = self.issue(mobile_limit=2)
        self.assertEqual(denied.status, "mobile_limited")
        self.assertGreater(denied.retry_after, 0)
        _, physical = self.keys()
        self.assertEqual(self.raw.exists(physical[0], physical[1]), 0)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[2])), 2)

    def test_shared_ip_quota_across_distinct_mobiles_is_atomic(self):
        for mobile in MOBILES[:2]:
            self.assertEqual(
                self.issue(mobile=mobile, ip_limit=2).status, "issued"
            )
        denied = self.issue(mobile=MOBILES[2], ip_limit=2)
        self.assertEqual(denied.status, "ip_limited")
        _, physical = self.keys(mobile=MOBILES[2])
        self.assertEqual(self.raw.exists(physical[0], physical[1], physical[2]), 0)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[3])), 2)

    def test_two_workers_same_mobile_one_issued_other_watch_conflict(self):
        gate = Barrier(2, timeout=15)
        original = Pipeline.multi

        def race(pipe, *args, **kwargs):
            gate.wait(timeout=15)
            return original(pipe, *args, **kwargs)

        with (
            patch.object(Pipeline, "multi", race),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [pool.submit(self.issue) for _ in range(2)]
            results = sorted(f.result(timeout=22).status for f in futures)
        self.assertEqual(results, ["issued", "unavailable"])
        _, physical = self.keys()
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[2])), 1)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[3])), 1)

    def test_two_different_mobiles_share_one_ip_quota_without_overspend(self):
        gate = Barrier(2, timeout=15)
        original = Pipeline.multi

        def race(pipe, *args, **kwargs):
            gate.wait(timeout=15)
            return original(pipe, *args, **kwargs)

        with (
            patch.object(Pipeline, "multi", race),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            futures = [
                pool.submit(self.issue, mobile=mobile, ip_limit=1)
                for mobile in MOBILES[:2]
            ]
            states = sorted(f.result(timeout=22).status for f in futures)
        self.assertEqual(states, ["issued", "unavailable"])
        _, ip_physical = self.keys(mobile=MOBILES[0])
        self.assertEqual(self.cache.client.decode(self.raw.get(ip_physical[3])), 1)
        _, a = self.keys(mobile=MOBILES[0])
        _, b = self.keys(mobile=MOBILES[1])
        self.assertEqual(
            self.raw.exists(a[0]) + self.raw.exists(b[0]), 1
        )

    def test_identical_watched_key_rewrite_aborts_issuance_without_partial_record(self):
        self.assertEqual(self.issue().status, "issued")
        self.clear_challenge()
        _, physical = self.keys()
        original_multi = Pipeline.multi
        seen = Event()
        resume = Event()

        def pause_before_multi(pipe, *args, **kwargs):
            if current_thread() is not main_thread():
                seen.set()
                if not resume.wait(timeout=15):
                    raise RuntimeError("synthetic barrier timeout")
            return original_multi(pipe, *args, **kwargs)

        with (
            patch.object(Pipeline, "multi", pause_before_multi),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(self.issue)
            try:
                self.assertTrue(seen.wait(timeout=12))
                original_bytes = self.raw.get(physical[2])
                self.assertTrue(self.raw.set(
                    physical[2], original_bytes, xx=True, keepttl=True
                ))
            finally:
                resume.set()
            result = future.result(timeout=20)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(self.raw.exists(physical[0], physical[1]), 0)
        self.assertEqual(self.cache.client.decode(self.raw.get(physical[2])), 1)

    def test_invalid_record_or_counter_wire_never_creates_new_challenge(self):
        _, physical = self.keys()
        self.raw.hset(physical[0], "bad", "type")
        self.assertEqual(self.issue().status, "unavailable")
        self.raw.delete(physical[0])
        self.raw.set(physical[2], b"not-an-integer", ex=3600)
        self.assertEqual(self.issue().status, "unavailable")
        self.raw.delete(physical[2])
        self.raw.set(physical[3], b"-1", ex=3600)
        self.assertEqual(self.issue().status, "unavailable")
        self.raw.delete(physical[3])
        self.raw.set(physical[1], b"broken", ex=60)
        self.assertEqual(self.issue().status, "unavailable")
        self.assertEqual(self.raw.exists(physical[0]), 0)

    def test_missing_counter_ttl_and_overlong_ttl_fail_closed(self):
        _, physical = self.keys()
        self.raw.set(physical[2], 1)
        self.assertEqual(self.issue().status, "unavailable")
        self.raw.delete(physical[2])
        self.raw.set(physical[2], 1, ex=4000)
        self.assertEqual(self.issue().status, "unavailable")
        self.assertEqual(self.raw.exists(physical[0]), 0)

    def test_commit_then_lost_exec_response_does_not_report_accepted(self):
        original = Pipeline.execute

        def commit_then_timeout(pipe, *args, **kwargs):
            original(pipe, *args, **kwargs)
            raise ConnectionError("synthetic private lost reply")

        with patch.object(Pipeline, "execute", commit_then_timeout):
            result = self.issue()
        self.assertEqual(result.status, "unavailable")
        _, physical = self.keys()
        # An ambiguous failure may already have committed ALL four records.
        self.assertEqual(self.raw.exists(*physical), 4)
        self.assertEqual(self.issue().status, "challenge_pending")

    def test_next_hour_uses_independent_rate_keys(self):
        self.assertEqual(self.issue().status, "issued")
        self.clear_challenge()
        next_ts = (self.now // 3600 + 1) * 3600 + 1
        next_issue = self.issue(now_ts=next_ts)
        self.assertEqual(next_issue.status, "issued")
        _, old_phys = self.keys()
        _, next_phys = self.keys(now_ts=next_ts)
        self.assertNotEqual(old_phys[2:], next_phys[2:])
        self.assertEqual(self.cache.client.decode(self.raw.get(old_phys[2])), 1)
        self.assertEqual(self.cache.client.decode(self.raw.get(next_phys[2])), 1)

    def test_nonredis_backend_refused_without_redis_io(self):
        self.assertEqual(self.issue(backend=object()).status, "unavailable")
        _, physical = self.keys()
        self.assertEqual(self.raw.exists(*physical), 0)


if __name__ == "__main__":
    unittest.main()
