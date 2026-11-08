"""Phase 7.22 real Redis 7.4 + Django-Redis 5.4 issuance CAS integration.

All records, mobile numbers and IP tokens are fabricated. No API, account,
real identity, session, SMS provider, or Production cache is ever imported.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="phase722-test-only-hmac-key-never-production")

import redis
from redis.client import Pipeline
from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache

from loomera.globalization.otp_legacy_issue_rate_rehearsal import (
    PREFIX, REDIS_URL, MOBILE_LIMIT, IP_LIMIT, RECORD_TTL, RESEND_TTL, RATE_TTL,
    SyntheticIssueEvidence, attempt_synthetic_atomic_issue,
    validate_synthetic_scope,
)
from loomera.globalization.otp_legacy_state_machine_rehearsal import (
    _legacy_record_valid, _confirmed_delete,
)

MOBILE = "09123456789"  # known synthetic placeholder, never a contact
OTHER_MOBILES = ("09123456780", "09123456781", "09123456782")
IP = "synthetic_ip_01"
FAKE_CODE = "123456"


def digest(code=FAKE_CODE, mobile=MOBILE):
    return salted_hmac(
        "loomera.api.auth.otp", f"app_login:{mobile}:{code}",
    ).hexdigest()


def cache_for(fixture_id, *, url=REDIS_URL):
    return RedisCache(url, {
        "KEY_PREFIX": PREFIX + fixture_id,
        "VERSION": 1,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    })


class Phase722AtomicIssueAndRateIntegrationTests(unittest.TestCase):
    def setUp(self):
        if (os.environ.get("GITHUB_ACTIONS") != "true"
                or not os.environ.get("GITHUB_RUN_ID")
                or not os.environ.get("GITHUB_RUN_ATTEMPT")
                or os.environ.get("LOOMERA_PHASE722_TEST_REDIS") != "1"):
            self.fail("Phase 7.22 requires explicit disposable GitHub CI grant")
        self.fixture_id = uuid4().hex
        self.cache = cache_for(self.fixture_id)
        self.raw = redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=2, socket_timeout=6,
        )
        self.assertTrue(self.raw.ping())
        self.touched = set()

    def tearDown(self):
        try:
            # Known fixture keys ONLY. No scan, flush, global cleanup, wildcard.
            if self.touched:
                self.raw.delete(*sorted(self.touched))
        finally:
            self.raw.close()

    def keys(self, mobile=MOBILE, ip_tag=IP, now_ts=1050):
        logical = (
            f"record:app_login:{mobile}",
            f"resend:app_login:{mobile}",
            f"rate:mobile:app_login_{mobile}:{now_ts // 3600}",
            f"rate:ip:{ip_tag}:{now_ts // 3600}",
        )
        physical = tuple(str(self.cache.make_key(k)) for k in logical)
        self.touched.update(physical)
        return physical

    def issue(self, *, cache=None, client=None, mobile=MOBILE,
              ip_tag=IP, now_ts=1050, code=FAKE_CODE, **changes):
        kwargs = {
            "fixture_id": self.fixture_id,
            "mobile": mobile,
            "ip_tag": ip_tag,
            "now_ts": now_ts,
            "code_digest": digest(code, mobile),
        }
        kwargs.update(changes)
        self.keys(mobile=mobile, ip_tag=ip_tag, now_ts=now_ts)
        return attempt_synthetic_atomic_issue(
            self.cache if cache is None else cache,
            self.raw if client is None else client,
            **kwargs,
        )

    def no_grant(self, result):
        self.assertIsInstance(result, SyntheticIssueEvidence)
        for field in (
            "real_otp_issued", "real_otp_consumed",
            "real_authentication_allowed", "real_session_created",
            "production_cutover_authorized",
            "live_issuance_or_rate_atomicity_fixed",
            "historical_legacy_race_fixed", "multihost_fencing_proven",
            "cross_store_consistency_proven",
        ):
            self.assertIs(getattr(result, field), False, field)
        for sensitive in (MOBILE, IP, FAKE_CODE, digest(), self.fixture_id):
            self.assertNotIn(sensitive, repr(result))

    def expire_challenge_and_cooldown(self, *, mobile=MOBILE, ip_tag=IP, now_ts=1050):
        record_key, resend_key, _, _ = self.keys(mobile, ip_tag, now_ts)
        # Simulate cache expiration under a single disposable test Redis.
        for key in (record_key, resend_key):
            if self.raw.exists(key):
                self.assertTrue(self.raw.pexpire(key, 10))
        time.sleep(0.05)
        self.assertEqual(self.raw.exists(record_key), 0)
        self.assertEqual(self.raw.exists(resend_key), 0)

    def test_all_four_keys_commit_atomically_real_wire_and_ttl(self):
        result = self.issue()
        self.assertEqual(result.status, "synthetic_issued")
        self.assertTrue(result.synthetic_record_created)
        self.assertTrue(result.mutation_confirmed)
        self.assertEqual(result.mobile_requests_remaining, MOBILE_LIMIT - 1)
        self.assertEqual(result.ip_requests_remaining, IP_LIMIT - 1)
        self.no_grant(result)
        record_key, resend_key, mobile_key, ip_key = self.keys()
        self.assertEqual([self.raw.type(key) for key in (
            record_key, resend_key, mobile_key, ip_key,
        )], [b"string"] * 4)
        record = self.cache.get(f"record:app_login:{MOBILE}")
        self.assertEqual(record["code_hash"], digest())
        self.assertTrue(_legacy_record_valid(
            record, f"record:app_login:{MOBILE}", 1050,
        ))
        self.assertEqual(record["delivery"]["mode"], "simulated")
        self.assertEqual(self.cache.client.decode(self.raw.get(record_key)), record)
        self.assertEqual(self.cache.get(f"resend:app_login:{MOBILE}"), 1050)
        self.assertEqual(self.cache.client.decode(self.raw.get(mobile_key)), 1)
        self.assertEqual(self.cache.client.decode(self.raw.get(ip_key)), 1)
        self.assertEqual(self.raw.get(mobile_key), b"1")
        self.assertEqual(self.raw.get(ip_key), b"1")
        for key, max_ms in zip(
            (record_key, resend_key, mobile_key, ip_key),
            (RECORD_TTL * 1000, RESEND_TTL * 1000,
             RATE_TTL * 1000, RATE_TTL * 1000),
        ):
            self.assertTrue(0 < self.raw.pttl(key) <= max_ms)

    def test_existing_challenge_and_resend_never_advance_quota(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        record_key, resend_key, mobile_key, ip_key = self.keys()
        before = tuple(self.raw.get(k) for k in (record_key, resend_key, mobile_key, ip_key))
        rejected = self.issue(code="654321")
        self.assertEqual(rejected.status, "challenge_already_pending")
        self.no_grant(rejected)
        self.assertEqual(tuple(self.raw.get(k) for k in (
            record_key, resend_key, mobile_key, ip_key,
        )), before)

        # A hypothetical consumed challenge leaves cooldown enforced.
        self.assertEqual(self.raw.delete(record_key), 1)
        cooldown = self.issue(code="654321")
        self.assertEqual(cooldown.status, "resend_cooldown_active")
        self.assertIsNone(self.raw.get(record_key))
        self.assertEqual(self.raw.get(mobile_key), before[2])
        self.assertEqual(self.raw.get(ip_key), before[3])
        self.no_grant(cooldown)

    def test_resend_after_expiration_preserves_rate_ttl_and_mobile_limit(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        _, _, mobile_key, ip_key = self.keys()
        initial_mobile_ttl = self.raw.pttl(mobile_key)
        initial_ip_ttl = self.raw.pttl(ip_key)
        self.expire_challenge_and_cooldown()
        second = self.issue(now_ts=1051, code="654321")
        self.assertEqual(second.status, "synthetic_issued")
        self.assertEqual(second.mobile_requests_remaining, 0)
        self.assertEqual(second.ip_requests_remaining, IP_LIMIT - 2)
        self.assertEqual(self.cache.client.decode(self.raw.get(mobile_key)), 2)
        self.assertEqual(self.cache.client.decode(self.raw.get(ip_key)), 2)
        self.assertTrue(0 < self.raw.pttl(mobile_key) <= initial_mobile_ttl)
        self.assertTrue(0 < self.raw.pttl(ip_key) <= initial_ip_ttl)
        self.no_grant(second)
        self.expire_challenge_and_cooldown(now_ts=1051)
        denied = self.issue(now_ts=1052, code="111111")
        self.assertEqual(denied.status, "mobile_rate_limited")
        self.assertEqual(denied.mobile_requests_remaining, 0)
        self.assertEqual(self.cache.client.decode(self.raw.get(mobile_key)), 2)
        self.assertEqual(self.cache.client.decode(self.raw.get(ip_key)), 2)
        self.assertIsNone(self.raw.get(self.keys(now_ts=1052)[0]))
        self.no_grant(denied)

    def test_three_distinct_mobiles_exhaust_shared_ip_quota(self):
        mobiles = (MOBILE,) + OTHER_MOBILES
        shared_ip_key = self.keys()[3]
        for index, mobile in enumerate(mobiles[:IP_LIMIT]):
            accepted = self.issue(mobile=mobile)
            self.assertEqual(accepted.status, "synthetic_issued")
            self.assertEqual(accepted.ip_requests_remaining, IP_LIMIT - index - 1)
            self.no_grant(accepted)
        self.assertEqual(self.cache.client.decode(self.raw.get(shared_ip_key)), IP_LIMIT)
        denied = self.issue(mobile=mobiles[IP_LIMIT])
        self.assertEqual(denied.status, "ip_rate_limited")
        self.assertEqual(denied.ip_requests_remaining, 0)
        self.assertIsNone(self.raw.get(self.keys(mobile=mobiles[IP_LIMIT])[0]))
        self.assertEqual(self.cache.client.decode(self.raw.get(shared_ip_key)), IP_LIMIT)
        self.no_grant(denied)

    def compete(self, spec):
        barrier = Barrier(2, timeout=20)

        def contender(mobile, ip_tag, code):
            client = redis.Redis.from_url(
                REDIS_URL, socket_connect_timeout=2, socket_timeout=8,
            )
            try:
                separate_cache = cache_for(self.fixture_id)
                return self.issue(
                    cache=separate_cache, client=client,
                    mobile=mobile, ip_tag=ip_tag, code=code,
                    on_watched_read=lambda: barrier.wait(timeout=20),
                )
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(contender, *entry) for entry in spec]
            return [f.result(timeout=20) for f in futures]

    def test_two_workers_same_mobile_same_ip_only_one_issuance(self):
        results = self.compete(((MOBILE, IP, "123456"), (MOBILE, IP, "654321")))
        self.assertEqual(
            sorted(x.status for x in results),
            ["concurrent_modification_conflict", "synthetic_issued"],
        )
        self.assertEqual(sum(x.mutation_confirmed for x in results), 1)
        self.assertEqual(sum(x.synthetic_record_created for x in results), 1)
        _, _, mobile_key, ip_key = self.keys()
        self.assertEqual(self.cache.client.decode(self.raw.get(mobile_key)), 1)
        self.assertEqual(self.cache.client.decode(self.raw.get(ip_key)), 1)
        self.assertIn(
            self.cache.get(f"record:app_login:{MOBILE}")["code_hash"],
            {digest("123456"), digest("654321")},
        )
        for row in results:
            self.no_grant(row)

    def test_two_different_mobiles_one_shared_ip_only_one_quota_increment(self):
        results = self.compete((
            (MOBILE, IP, FAKE_CODE),
            (OTHER_MOBILES[0], IP, FAKE_CODE),
        ))
        self.assertEqual(
            sorted(x.status for x in results),
            ["concurrent_modification_conflict", "synthetic_issued"],
        )
        self.assertEqual(sum(x.mutation_confirmed for x in results), 1)
        self.assertEqual(self.cache.client.decode(self.raw.get(self.keys()[3])), 1)
        existing = sum(self.cache.get(f"record:app_login:{mobile}") is not None
                       for mobile in (MOBILE, OTHER_MOBILES[0]))
        self.assertEqual(existing, 1)
        for row in results:
            self.no_grant(row)

    def test_test_only_consumer_compatible_with_phase721_legacy_record(self):
        accepted = self.issue()
        self.assertEqual(accepted.status, "synthetic_issued")
        record_key, resend_key, mobile_key, ip_key = self.keys()
        with self.raw.pipeline(transaction=True) as pipe:
            pipe.watch(record_key)
            raw = pipe.get(record_key)
            row = self.cache.client.decode(raw)
            self.assertTrue(_legacy_record_valid(
                row, f"record:app_login:{MOBILE}", 1050,
            ))
            self.assertEqual(row["code_hash"], digest())
            pipe.multi()
            pipe.delete(record_key)
            self.assertTrue(_confirmed_delete(pipe.execute()))
        self.assertIsNone(self.raw.get(record_key))
        self.assertEqual(self.issue().status, "resend_cooldown_active")
        self.assertEqual(self.raw.get(mobile_key), b"1")
        self.assertEqual(self.raw.get(ip_key), b"1")
        # A synthetic expiry permits a new, different generation.
        self.assertTrue(self.raw.pexpire(resend_key, 10))
        time.sleep(.05)
        replacement = self.issue(now_ts=1051, code="654321")
        self.assertEqual(replacement.status, "synthetic_issued")
        fresh = self.cache.get(f"record:app_login:{MOBILE}")
        self.assertEqual(fresh["code_hash"], digest("654321"))
        self.assertNotEqual(fresh["code_hash"], digest())
        self.assertTrue(_legacy_record_valid(
            fresh, f"record:app_login:{MOBILE}", 1051,
        ))
        self.assertEqual(self.raw.get(mobile_key), b"2")
        self.assertEqual(self.raw.get(ip_key), b"2")
        self.no_grant(replacement)

    def test_byte_identical_reissue_of_a_watched_rate_key_aborts(self):
        _, _, mobile_key, ip_key = self.keys()
        # Seed one prior synthetic record/cooldown/rate generation, then
        # expire the record and resend to test a subsequent issue.
        self.assertEqual(self.issue().status, "synthetic_issued")
        self.expire_challenge_and_cooldown()
        before = self.raw.get(mobile_key)
        before_ip = self.raw.get(ip_key)
        def rewrite_identical_bytes():
            self.assertTrue(self.raw.set(mobile_key, before, keepttl=True))
        result = self.issue(now_ts=1051, code="654321",
                            on_watched_read=rewrite_identical_bytes)
        self.assertEqual(result.status, "concurrent_modification_conflict")
        self.assertIsNone(self.raw.get(self.keys()[0]))
        self.assertEqual(self.raw.get(mobile_key), before)
        self.assertEqual(self.raw.get(ip_key), before_ip)
        self.no_grant(result)

    def test_unexpected_types_and_ttl_fail_closed_without_partial_writes(self):
        rec, cool, mobile_key, ip_key = self.keys()
        self.raw.hset(mobile_key, "invalid", "type")
        self.raw.pexpire(mobile_key, 120000)
        denied = self.issue()
        self.assertEqual(denied.status, "invalid_rate_state")
        self.assertIsNone(self.raw.get(rec))
        self.assertIsNone(self.raw.get(cool))
        self.no_grant(denied)

        self.raw.delete(mobile_key)
        self.raw.set(mobile_key, b"true", ex=100)
        self.assertEqual(self.issue().status, "invalid_rate_state")
        self.raw.delete(mobile_key)
        self.raw.set(mobile_key, b"999", ex=100)
        self.assertEqual(self.issue().status, "invalid_rate_state")
        self.raw.delete(mobile_key)

        self.raw.set(rec, b"test-only-invalid", ex=120)
        self.assertEqual(self.issue().status, "challenge_already_pending")
        self.raw.persist(rec)
        self.assertEqual(self.issue().status, "invalid_existing_record")
        self.raw.delete(rec)
        self.raw.hset(cool, "invalid", "type")
        self.raw.pexpire(cool, 30000)
        self.assertEqual(self.issue().status, "invalid_cooldown")
        self.raw.delete(cool)
        self.raw.set(cool, b"bad", ex=30)
        self.assertEqual(self.issue().status, "invalid_cooldown")
        self.assertIsNone(self.raw.get(rec))
        self.assertIsNone(self.raw.get(ip_key))

    def test_hour_partition_uses_distinct_rate_keys(self):
        self.assertEqual(self.issue(now_ts=3599).status, "synthetic_issued")
        self.expire_challenge_and_cooldown(now_ts=3599)
        fresh = self.issue(now_ts=3600, code="654321")
        self.assertEqual(fresh.status, "synthetic_issued")
        self.assertEqual(fresh.mobile_requests_remaining, MOBILE_LIMIT - 1)
        self.assertEqual(fresh.ip_requests_remaining, IP_LIMIT - 1)
        self.assertEqual(self.raw.get(self.keys(now_ts=3599)[2]), b"1")
        self.assertEqual(self.raw.get(self.keys(now_ts=3600)[2]), b"1")
        self.no_grant(fresh)

    def test_unknown_exec_response_never_proves_issuance(self):
        def no_exec(_pipe, *args, **kwargs):
            return [True, False, True, True]
        with patch.object(Pipeline, "execute", no_exec):
            result = self.issue()
        self.assertEqual(result.status, "issue_unconfirmed")
        self.assertFalse(result.mutation_confirmed)
        self.assertFalse(result.synthetic_record_created)
        self.no_grant(result)
        self.assertEqual([self.raw.exists(k) for k in self.keys()], [0] * 4)

    def test_commit_then_lose_response_cannot_authorize_any_real_otp(self):
        actual_execute = Pipeline.execute
        def commit_then_timeout(pipe, *args, **kwargs):
            actual_execute(pipe, *args, **kwargs)
            raise TimeoutError("synthetic ambiguous EXEC response")
        with patch.object(Pipeline, "execute", commit_then_timeout):
            result = self.issue()
        self.assertEqual(result.status, "backend_unavailable")
        self.assertFalse(result.mutation_confirmed)
        self.no_grant(result)
        self.assertEqual([self.raw.exists(k) for k in self.keys()], [1] * 4)
        self.assertEqual(self.issue().status, "challenge_already_pending")

    def test_remote_backend_wrong_db_untrusted_identity_denied_before_io(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE722_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.issue()
        for fake_cache in (
            cache_for(uuid4().hex),
            cache_for(self.fixture_id, url="redis://remote.invalid:6414/15"),
            cache_for(self.fixture_id, url="redis://127.0.0.1:6379/15"),
        ):
            with self.assertRaises(RuntimeError):
                self.issue(cache=fake_cache)
        wrong_db = redis.Redis.from_url("redis://127.0.0.1:6414/14")
        with self.assertRaises(RuntimeError):
            self.issue(client=wrong_db)
        for bad in (
            {"fixture_id": "unsafe"},
            {"mobile": "+989123456789"},
            {"ip_tag": "192.0.2.1"},
            {"ip_tag": True},
            {"now_ts": True},
            {"code_digest": "plaintext"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.issue(**bad)
        with self.assertRaises(TypeError):
            self.issue(on_watched_read="not-callable")
        self.assertEqual([self.raw.exists(k) for k in self.keys()], [0] * 4)

    def test_scope_keys_match_real_django_redis_versioned_names(self):
        physical = validate_synthetic_scope(
            self.cache, self.raw, fixture_id=self.fixture_id,
            mobile=MOBILE, ip_tag=IP, now_ts=1050,
            code_digest=digest(),
        )
        self.assertEqual(physical, self.keys())
        self.assertEqual(len(set(physical)), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
