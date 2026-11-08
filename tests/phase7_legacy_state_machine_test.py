"""Phase 7.21 real Redis 7.4 + pinned Django-Redis serialized OTP state machine.

All records are ephemeral fake app_login dictionaries on loopback 6413 DB15.
No real API view, authentication, SMS, DB, or session path is imported.
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
    settings.configure(SECRET_KEY="phase721-only-ci-salted-hmac-not-production")

import redis
from redis.client import Pipeline
from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache

from loomera.globalization.otp_legacy_state_machine_rehearsal import (
    PREFIX, REDIS_URL, SyntheticOtpTransition,
    apply_synthetic_otp_transition, validate_scope,
)

MOBILE = "09123456789"  # fabricated test-only value
LOGICAL = f"record:app_login:{MOBILE}"
GOOD_CODE = "123456"
BAD_CODE = "000000"


def digest(code=GOOD_CODE):
    return salted_hmac(
        "loomera.api.auth.otp", f"app_login:{MOBILE}:{code}",
    ).hexdigest()


def legacy_record(code=GOOD_CODE, **extra):
    return {
        "purpose": "app_login",
        "mobile_number": MOBILE,
        "code_hash": digest(code),
        "created_at": 1000,
        "expires_at": 1120,
        "attempts": 0,
        "max_attempts": 5,
        "verified": False,
        "delivery": {"channel": "sms", "mode": "simulated",
                     "sent": False, "provider": "none"},
        **extra,
    }


def cache_for(fixture_id, *, url=REDIS_URL):
    return RedisCache(url, {
        "KEY_PREFIX": PREFIX + fixture_id,
        "VERSION": 1,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    })


class Phase721TrueSerializedStateMachineTests(unittest.TestCase):
    def setUp(self):
        if (os.environ.get("GITHUB_ACTIONS") != "true"
                or not os.environ.get("GITHUB_RUN_ID")
                or not os.environ.get("GITHUB_RUN_ATTEMPT")
                or os.environ.get("LOOMERA_PHASE721_TEST_REDIS") != "1"):
            self.fail("explicit disposable Phase 7.21 CI grant required")
        self.raw = redis.Redis.from_url(
            REDIS_URL, socket_connect_timeout=2, socket_timeout=5,
        )
        self.assertTrue(self.raw.ping())
        self.fixture_id = uuid4().hex
        self.cache = cache_for(self.fixture_id)
        self.key = str(self.cache.make_key(LOGICAL))
        self.known_keys = [self.key]

    def tearDown(self):
        try:
            # Only exact fixture-created keys; never SCAN/FLUSH or remove others.
            if self.known_keys:
                self.raw.delete(*self.known_keys)
        finally:
            self.raw.close()

    def seed(self, value=None, *, timeout=120):
        self.assertTrue(self.cache.set(
            LOGICAL,
            legacy_record() if value is None else value,
            timeout=timeout,
        ))

    def run_transition(self, *, cache=None, raw=None, **kwargs):
        params = {
            "fixture_id": self.fixture_id,
            "logical_key": LOGICAL,
            "submitted_digest": digest(),
            "now_ts": 1050,
        }
        params.update(kwargs)
        return apply_synthetic_otp_transition(
            self.cache if cache is None else cache,
            self.raw if raw is None else raw,
            **params,
        )

    def assert_no_real_grant(self, result):
        self.assertIsInstance(result, SyntheticOtpTransition)
        for field in (
            "real_authentication_allowed", "real_session_created",
            "real_otp_issued_or_consumed", "production_cutover_authorized",
            "historical_legacy_race_fixed", "atomic_issuance_or_rates_proven",
            "durable_multihost_fencing_proven",
            "cross_store_consistency_proven",
        ):
            self.assertIs(getattr(result, field), False, field)
        for secret in (
            MOBILE, GOOD_CODE, BAD_CODE, digest(), self.key,
            "phase721-only-ci-salted-hmac-not-production",
        ):
            self.assertNotIn(secret, repr(result))

    def test_correct_code_deletes_real_pickled_string_once(self):
        self.seed()
        self.assertEqual(self.raw.type(self.key), b"string")
        before = self.raw.get(self.key)
        self.assertIsInstance(before, bytes)
        self.assertEqual(self.cache.client.decode(before), legacy_record())
        first = self.run_transition()
        self.assertEqual(first.status, "synthetic_single_winner")
        self.assertTrue(first.mutation_confirmed)
        self.assertTrue(first.synthetic_challenge_consumed)
        self.assertIsNone(first.attempts_remaining)
        self.assert_no_real_grant(first)
        self.assertEqual(self.raw.type(self.key), b"none")
        second = self.run_transition()
        self.assertEqual(second.status, "missing")
        self.assertFalse(second.mutation_confirmed)
        self.assert_no_real_grant(second)

    def test_wrong_digest_increments_actual_django_cache_record_without_ttl_reset(self):
        self.seed()
        before = self.raw.pttl(self.key)
        self.assertGreater(before, 0)
        first = self.run_transition(submitted_digest=digest(BAD_CODE))
        self.assertEqual(first.status, "synthetic_invalid_attempt")
        self.assertTrue(first.mutation_confirmed)
        self.assertEqual(first.attempts_remaining, 4)
        self.assertFalse(first.synthetic_challenge_consumed)
        self.assert_no_real_grant(first)
        self.assertEqual(self.cache.get(LOGICAL)["attempts"], 1)
        self.assertEqual(self.cache.get(LOGICAL)["delivery"],
                         legacy_record()["delivery"])
        self.assertEqual(self.raw.type(self.key), b"string")
        after = self.raw.pttl(self.key)
        self.assertTrue(0 < after <= before, (before, after))
        time.sleep(.05)
        second = self.run_transition(submitted_digest=digest(BAD_CODE))
        self.assertEqual(second.status, "synthetic_invalid_attempt")
        self.assertEqual(second.attempts_remaining, 3)
        self.assertEqual(self.cache.get(LOGICAL)["attempts"], 2)
        self.assertLess(self.raw.pttl(self.key), before)
        self.assert_no_real_grant(second)

    def test_final_wrong_attempt_deletes_and_exhausts_challenge(self):
        self.seed(legacy_record(attempts=4))
        end = self.run_transition(submitted_digest=digest(BAD_CODE))
        self.assertEqual(end.status, "synthetic_exhausted")
        self.assertEqual(end.attempts_remaining, 0)
        self.assertTrue(end.mutation_confirmed)
        self.assertFalse(end.synthetic_challenge_consumed)
        self.assertIsNone(self.cache.get(LOGICAL))
        self.assert_no_real_grant(end)
        self.assertEqual(self.run_transition().status, "missing")

    def test_strict_one_attempt_budget_never_issues_extra_chance(self):
        self.seed(legacy_record(max_attempts=1))
        self.assertEqual(
            self.run_transition(submitted_digest=digest(BAD_CODE)).status,
            "synthetic_exhausted",
        )
        self.assertEqual(self.run_transition().status, "missing")

    def test_correct_code_after_failed_attempts_consumes_once(self):
        self.seed()
        self.assertEqual(self.run_transition(
            submitted_digest=digest(BAD_CODE)).attempts_remaining, 4)
        self.assertEqual(self.run_transition(
            submitted_digest=digest(BAD_CODE)).attempts_remaining, 3)
        good = self.run_transition()
        self.assertEqual(good.status, "synthetic_single_winner")
        self.assert_no_real_grant(good)
        self.assertIsNone(self.cache.get(LOGICAL))
        self.assertEqual(self.run_transition().status, "missing")

    def contenders(self, code_by_index):
        barrier = Barrier(2, timeout=20)
        def contender(code):
            client = redis.Redis.from_url(
                REDIS_URL, socket_connect_timeout=2, socket_timeout=6,
            )
            try:
                separate_cache = cache_for(self.fixture_id)
                return self.run_transition(
                    cache=separate_cache, raw=client,
                    submitted_digest=digest(code),
                    on_watched_read=lambda: barrier.wait(timeout=20),
                )
            finally:
                client.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(contender, code) for code in code_by_index]
            return [f.result(timeout=20) for f in futures]

    def test_two_correct_workers_one_consumes_other_conflicts(self):
        self.seed()
        results = self.contenders((GOOD_CODE, GOOD_CODE))
        self.assertEqual(
            sorted(r.status for r in results),
            ["concurrent_modification_conflict", "synthetic_single_winner"],
        )
        self.assertEqual(sum(r.synthetic_challenge_consumed for r in results), 1)
        self.assertEqual(sum(r.mutation_confirmed for r in results), 1)
        self.assertIsNone(self.cache.get(LOGICAL))
        for row in results:
            self.assert_no_real_grant(row)

    def test_two_wrong_workers_increment_once_with_optimistic_conflict(self):
        self.seed()
        before = self.raw.pttl(self.key)
        results = self.contenders((BAD_CODE, BAD_CODE))
        self.assertEqual(
            sorted(r.status for r in results),
            ["concurrent_modification_conflict", "synthetic_invalid_attempt"],
        )
        self.assertEqual(sum(r.mutation_confirmed for r in results), 1)
        self.assertEqual(self.cache.get(LOGICAL)["attempts"], 1)
        self.assertLessEqual(self.raw.pttl(self.key), before)
        self.assertEqual([r.attempts_remaining for r in results
                          if r.mutation_confirmed], [4])
        for row in results:
            self.assert_no_real_grant(row)

    def test_correct_and_wrong_worker_race_never_both_commit(self):
        self.seed()
        results = self.contenders((GOOD_CODE, BAD_CODE))
        self.assertEqual(sum(r.mutation_confirmed for r in results), 1)
        self.assertEqual(
            sum(r.status == "concurrent_modification_conflict" for r in results), 1,
        )
        self.assertEqual(
            sum(r.status in ("synthetic_single_winner", "synthetic_invalid_attempt")
                for r in results), 1,
        )
        if self.raw.type(self.key) == b"none":
            self.assertEqual(
                sum(r.status == "synthetic_single_winner" for r in results), 1,
            )
        else:
            self.assertEqual(self.cache.get(LOGICAL)["attempts"], 1)
            self.assertEqual(
                sum(r.status == "synthetic_invalid_attempt" for r in results), 1,
            )
        for row in results:
            self.assert_no_real_grant(row)

    def test_last_wrong_and_correct_race_never_both_commit(self):
        self.seed(legacy_record(attempts=4))
        results = self.contenders((GOOD_CODE, BAD_CODE))
        self.assertEqual(sum(r.mutation_confirmed for r in results), 1)
        self.assertEqual(
            sum(r.status == "concurrent_modification_conflict" for r in results), 1,
        )
        self.assertEqual(
            sum(r.status in ("synthetic_single_winner", "synthetic_exhausted")
                for r in results), 1,
        )
        self.assertIsNone(self.cache.get(LOGICAL))
        for row in results:
            self.assert_no_real_grant(row)

    def test_same_byte_aba_reissue_fences_wrong_attempt_and_correct_consume(self):
        for submitted in (digest(), digest(BAD_CODE)):
            with self.subTest(submitted=submitted == digest()):
                self.seed()
                same_raw = self.raw.get(self.key)
                def reissue():
                    self.assertTrue(self.raw.set(self.key, same_raw, px=120000))
                result = self.run_transition(
                    submitted_digest=submitted, on_watched_read=reissue,
                )
                self.assertEqual(
                    result.status, "concurrent_modification_conflict",
                )
                self.assertFalse(result.mutation_confirmed)
                self.assertEqual(self.raw.get(self.key), same_raw)
                self.assertEqual(self.cache.get(LOGICAL)["attempts"], 0)
                self.assert_no_real_grant(result)

    def test_replaced_generation_not_consumed_or_charged_old_attempt(self):
        for submitted in (digest(), digest(BAD_CODE)):
            with self.subTest(valid_old=(submitted == digest())):
                self.seed()
                def reissue():
                    self.seed(legacy_record(code="654321", max_attempts=3))
                result = self.run_transition(
                    submitted_digest=submitted, on_watched_read=reissue,
                )
                self.assertEqual(
                    result.status, "concurrent_modification_conflict",
                )
                newer = self.cache.get(LOGICAL)
                self.assertEqual(newer["code_hash"], digest("654321"))
                self.assertEqual(newer["attempts"], 0)
                self.assertEqual(newer["max_attempts"], 3)
                self.assert_no_real_grant(result)
                current = self.run_transition(
                    submitted_digest=digest("654321"),
                )
                self.assertEqual(current.status, "synthetic_single_winner")
                self.assert_no_real_grant(current)

    def test_invalid_records_types_and_permanent_ttl_never_mutate(self):
        for value in (
            legacy_record(attempts=5),
            legacy_record(attempts=True),
            legacy_record(attempts=-1),
            legacy_record(max_attempts=True),
            legacy_record(max_attempts=11),
            legacy_record(expires_at=1049),
            legacy_record(created_at=1051),
            legacy_record(verified=True),
            legacy_record(purpose="password_reset"),
            legacy_record(mobile_number="09123456780"),
            legacy_record(code_hash="not-a-digest"),
            {"purpose": "app_login"},
            "wrong payload type",
        ):
            with self.subTest(description=str(type(value))):
                self.seed(value)
                original = self.raw.get(self.key)
                result = self.run_transition()
                self.assertEqual(result.status, "invalid_record")
                self.assertFalse(result.mutation_confirmed)
                self.assertEqual(self.raw.get(self.key), original)
                self.assert_no_real_grant(result)

        self.seed()
        self.assertTrue(self.raw.persist(self.key))
        result = self.run_transition()
        self.assertEqual(result.status, "invalid_ttl")
        self.assertFalse(result.mutation_confirmed)
        self.assert_no_real_grant(result)
        self.raw.delete(self.key)
        self.raw.hset(self.key, mapping={"purpose": "app_login"})
        self.raw.pexpire(self.key, 120000)
        result = self.run_transition()
        self.assertEqual(result.status, "wrong_type")
        self.assertEqual(self.raw.type(self.key), b"hash")
        self.assert_no_real_grant(result)

    def test_corrupt_wire_missing_record_and_short_ttl_never_mutate(self):
        self.assertEqual(self.run_transition().status, "missing")
        self.raw.set(self.key, b"not a valid pickled object", ex=60)
        result = self.run_transition()
        self.assertEqual(result.status, "invalid_wire")
        self.assert_no_real_grant(result)
        self.raw.delete(self.key)
        self.seed(timeout=1)
        original = self.raw.get(self.key)
        self.assertEqual(self.run_transition(now_ts=1050).status,
                         "synthetic_single_winner")
        self.assertIsNotNone(original)
        self.assert_no_real_grant(result)

    def test_lost_exec_response_never_returns_success_or_retry(self):
        for code in (GOOD_CODE, BAD_CODE):
            with self.subTest(valid_code=code == GOOD_CODE):
                self.seed()
                original_execute = Pipeline.execute
                def commit_then_lose_response(pipe, *args, **kwargs):
                    original_execute(pipe, *args, **kwargs)
                    raise TimeoutError("synthetic uncertain EXEC response")
                with patch.object(Pipeline, "execute",
                                  commit_then_lose_response):
                    result = self.run_transition(
                        submitted_digest=digest(code),
                    )
                self.assertEqual(result.status, "backend_unavailable")
                self.assertFalse(result.mutation_confirmed)
                self.assert_no_real_grant(result)
                if code == GOOD_CODE:
                    self.assertIsNone(self.cache.get(LOGICAL))
                else:
                    self.assertEqual(self.cache.get(LOGICAL)["attempts"], 1)

    def test_rate_resend_records_untouched_by_single_record_machine(self):
        self.seed()
        for logical, value in (
            (f"resend:app_login:{MOBILE}", 1000),
            ("rate:mobile:synthetic:1000", 3),
        ):
            self.assertTrue(self.cache.set(logical, value, timeout=120))
            self.known_keys.append(str(self.cache.make_key(logical)))
        first = self.run_transition(submitted_digest=digest(BAD_CODE))
        self.assertEqual(first.status, "synthetic_invalid_attempt")
        self.assertEqual(self.cache.get(f"resend:app_login:{MOBILE}"), 1000)
        self.assertEqual(self.cache.get("rate:mobile:synthetic:1000"), 3)
        good = self.run_transition()
        self.assertEqual(good.status, "synthetic_single_winner")
        self.assertEqual(self.cache.get(f"resend:app_login:{MOBILE}"), 1000)
        self.assertEqual(self.cache.get("rate:mobile:synthetic:1000"), 3)
        self.assert_no_real_grant(good)

    def test_scope_remote_wrong_db_wrong_namespace_denied_before_io(self):
        self.seed()
        with patch.dict(os.environ, {"LOOMERA_PHASE721_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.run_transition()
        for fake_cache in (
            cache_for(uuid4().hex),
            cache_for(self.fixture_id, url="redis://remote.invalid:6413/15"),
            cache_for(self.fixture_id, url="redis://127.0.0.1:6379/15"),
        ):
            with self.assertRaises(RuntimeError):
                self.run_transition(cache=fake_cache)
        bad_db = redis.Redis.from_url("redis://127.0.0.1:6413/14")
        with self.assertRaises(RuntimeError):
            self.run_transition(raw=bad_db)
        with self.assertRaises(ValueError):
            self.run_transition(fixture_id="not-random")
        with self.assertRaises(ValueError):
            self.run_transition(logical_key="record:password_reset:09123456789")
        with self.assertRaises(ValueError):
            self.run_transition(submitted_digest="plaintext")
        with self.assertRaises(ValueError):
            self.run_transition(now_ts=True)
        with self.assertRaises(TypeError):
            self.run_transition(on_watched_read="not-callable")
        self.assertIsNotNone(self.raw.get(self.key))

    def test_scope_returns_exact_django_redis_physical_key(self):
        self.seed()
        self.assertEqual(
            validate_scope(self.cache, self.raw, fixture_id=self.fixture_id,
                           logical_key=LOGICAL),
            self.key,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
