"""Phase 7.23 integrated REAL Redis 7.4 issue/consume/retry/outage preflight.

Extends the Phase 7.22 container while still alive (6414/15). Uses exactly
the issuer's physical Django-Redis 5.4 STRING keys, not an unrelated shadow.
No real OTP, SMS, Django account, session or Production cache access.
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
    settings.configure(SECRET_KEY="phase723-only-synthetic-test-secret-not-production")

import redis
from redis.client import Pipeline
from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache

from loomera.globalization.otp_legacy_issue_rate_rehearsal import (
    PREFIX, REDIS_URL, attempt_synthetic_atomic_issue,
    validate_synthetic_scope,
)
from loomera.globalization.otp_legacy_integrated_recovery_rehearsal import (
    SyntheticIntegratedVerifyEvidence, attempt_synthetic_integrated_verify,
)

MOBILE = "09123456789"
IP_TAG = "synthetic_ip_01"
CODE = "123456"
WRONG = "000000"


def digest(code=CODE):
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
        REDIS_URL, socket_connect_timeout=1, socket_timeout=3,
    )


class Phase723IntegratedIssueConsumeRecoveryTests(unittest.TestCase):
    def setUp(self):
        if (os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("LOOMERA_PHASE722_TEST_REDIS") != "1"
                or os.environ.get("LOOMERA_PHASE723_TEST_REDIS") != "1"
                or not os.environ.get("GITHUB_RUN_ID")
                or not os.environ.get("GITHUB_RUN_ATTEMPT")):
            self.fail("Phase 7.23 requires explicit disposable CI-only grant")
        self.fixture = uuid4().hex
        self.cache = new_cache(self.fixture)
        self.raw = new_client()
        self.assertTrue(self.raw.ping())
        self.keys = validate_synthetic_scope(
            self.cache, self.raw, fixture_id=self.fixture,
            mobile=MOBILE, ip_tag=IP_TAG, now_ts=1050,
            code_digest=digest(),
        )

    def tearDown(self):
        try:
            # Exact known keys from THIS test only, never scan or flush.
            self.raw.delete(*self.keys)
        finally:
            self.raw.close()

    def issue(self, *, code=CODE, client=None, cache=None,
              now_ts=1050, on_watched_read=None):
        return attempt_synthetic_atomic_issue(
            self.cache if cache is None else cache,
            self.raw if client is None else client,
            fixture_id=self.fixture, mobile=MOBILE, ip_tag=IP_TAG,
            now_ts=now_ts, code_digest=digest(code),
            on_watched_read=on_watched_read,
        )

    def verify(self, *, code=CODE, client=None, cache=None,
               now_ts=1050, on_watched_read=None):
        return attempt_synthetic_integrated_verify(
            self.cache if cache is None else cache,
            self.raw if client is None else client,
            fixture_id=self.fixture, mobile=MOBILE, ip_tag=IP_TAG,
            now_ts=now_ts, submitted_digest=digest(code),
            on_watched_read=on_watched_read,
        )

    def no_auth(self, result):
        self.assertIsInstance(result, SyntheticIntegratedVerifyEvidence)
        for flag in (
            "automatic_retry_authorized", "real_authentication_allowed",
            "real_session_created", "real_otp_issued_or_consumed",
            "production_cutover_authorized", "live_races_fixed",
            "multihost_fencing_proven", "cross_store_consistency_proven",
        ):
            self.assertFalse(getattr(result, flag), flag)
        for value in (MOBILE, IP_TAG, CODE, WRONG, digest(), self.fixture):
            self.assertNotIn(value, repr(result))

    def assert_counters(self, mobile_count, ip_count):
        self.assertEqual(self.raw.get(self.keys[2]), str(mobile_count).encode())
        self.assertEqual(self.raw.get(self.keys[3]), str(ip_count).encode())

    def test_issue_then_correct_consume_keeps_cooldown_and_exact_quotas(self):
        issued = self.issue()
        self.assertEqual(issued.status, "synthetic_issued")
        record = self.cache.get(f"record:app_login:{MOBILE}")
        self.assertEqual(record["code_hash"], digest())
        before_ttls = [self.raw.pttl(key) for key in self.keys]
        self.assertTrue(all(ttl > 0 for ttl in before_ttls))
        consumed = self.verify()
        self.assertEqual(consumed.status, "synthetic_single_winner")
        self.assertTrue(consumed.synthetic_record_consumed)
        self.assertTrue(consumed.mutation_confirmed)
        self.no_auth(consumed)
        self.assertIsNone(self.raw.get(self.keys[0]))
        self.assertEqual(self.verify().status, "missing")
        self.assertEqual(self.issue(code="654321").status, "resend_cooldown_active")
        self.assert_counters(1, 1)
        self.assertTrue(all(
            0 < self.raw.pttl(k) <= before_ttls[i]
            for i, k in enumerate(self.keys[1:], start=1)
        ))

    def test_wrong_attempt_and_correct_consume_preserve_rates_and_ttl(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        before = self.raw.pttl(self.keys[0])
        wrong = self.verify(code=WRONG)
        self.assertEqual(wrong.status, "synthetic_invalid_attempt")
        self.assertEqual(wrong.attempts_remaining, 4)
        self.assertFalse(wrong.synthetic_record_consumed)
        self.no_auth(wrong)
        record = self.cache.get(f"record:app_login:{MOBILE}")
        self.assertEqual(record["attempts"], 1)
        self.assertTrue(0 < self.raw.pttl(self.keys[0]) <= before)
        self.assert_counters(1, 1)
        valid = self.verify()
        self.assertEqual(valid.status, "synthetic_single_winner")
        self.no_auth(valid)
        self.assertEqual(self.verify().status, "missing")
        self.assert_counters(1, 1)

    def test_last_wrong_attempt_exhausts_and_resend_still_blocked(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        self.cache.set(
            f"record:app_login:{MOBILE}",
            {**self.cache.get(f"record:app_login:{MOBILE}"), "attempts": 4},
            timeout=100,
        )
        final = self.verify(code=WRONG)
        self.assertEqual(final.status, "synthetic_exhausted")
        self.assertEqual(final.attempts_remaining, 0)
        self.assertFalse(final.synthetic_record_consumed)
        self.no_auth(final)
        self.assertEqual(self.verify().status, "missing")
        self.assertEqual(self.issue(code="654321").status, "resend_cooldown_active")
        self.assert_counters(1, 1)

    def test_two_verifiers_from_same_issued_record_have_one_winner(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        barrier = Barrier(2, timeout=20)
        def contend():
            c = new_client()
            try:
                return self.verify(
                    client=c, cache=new_cache(self.fixture),
                    on_watched_read=lambda: barrier.wait(timeout=20),
                )
            finally:
                c.close()
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(contend) for _ in range(2)]
            results = [f.result(timeout=25) for f in futures]
        self.assertEqual(
            sorted(r.status for r in results),
            ["concurrent_modification_conflict", "synthetic_single_winner"],
        )
        self.assertEqual(sum(r.synthetic_record_consumed for r in results), 1)
        self.assertIsNone(self.raw.get(self.keys[0]))
        self.assert_counters(1, 1)
        for row in results:
            self.no_auth(row)

    def test_issuer_watch_on_absent_record_and_verifier_cannot_grant(self):
        seen = []
        def during_issuer_watch():
            seen.append(self.verify())
        issued = self.issue(on_watched_read=during_issuer_watch)
        self.assertEqual(issued.status, "synthetic_issued")
        self.assertEqual([r.status for r in seen], ["missing"])
        self.no_auth(seen[0])
        self.assertEqual(self.verify().status, "synthetic_single_winner")
        self.assert_counters(1, 1)

    def test_reissue_racing_stale_watched_verification_aborts_old_code(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        def rotate():
            # Simulate the old challenge's retirement and persisted cooldown
            # expiry during an already WATCHed verification. Test-only.
            self.assertEqual(self.raw.delete(self.keys[0]), 1)
            self.assertTrue(self.raw.pexpire(self.keys[1], 10))
            time.sleep(.04)
            self.assertEqual(
                self.issue(code="654321", now_ts=1051).status,
                "synthetic_issued",
            )
        stale = self.verify(on_watched_read=rotate)
        self.assertEqual(stale.status, "concurrent_modification_conflict")
        self.assertFalse(stale.mutation_confirmed)
        self.no_auth(stale)
        self.assertEqual(
            self.cache.get(f"record:app_login:{MOBILE}")["code_hash"],
            digest("654321"),
        )
        self.assert_counters(2, 2)
        self.assertEqual(
            self.verify(code=CODE, now_ts=1051).status,
            "synthetic_invalid_attempt",
        )
        self.assertEqual(
            self.verify(code="654321", now_ts=1051).status,
            "synthetic_single_winner",
        )
        self.assertIsNone(self.raw.get(self.keys[0]))
        self.assert_counters(2, 2)

    def test_same_byte_reissued_record_detected_even_with_old_digest(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        original = self.raw.get(self.keys[0])
        def identical_set():
            self.assertTrue(self.raw.set(
                self.keys[0], original, keepttl=True,
            ))
        result = self.verify(on_watched_read=identical_set)
        self.assertEqual(result.status, "concurrent_modification_conflict")
        self.assertFalse(result.mutation_confirmed)
        self.no_auth(result)
        self.assertEqual(self.raw.get(self.keys[0]), original)
        self.assert_counters(1, 1)

    def test_lost_issue_ack_never_reissues_or_double_charges_on_retry(self):
        real_execute = Pipeline.execute
        def commit_then_lost_ack(pipe, *args, **kwargs):
            real_execute(pipe, *args, **kwargs)
            raise TimeoutError("synthetic issue ack lost after EXEC")
        with patch.object(Pipeline, "execute", commit_then_lost_ack):
            unknown = self.issue()
        self.assertEqual(unknown.status, "backend_unavailable")
        self.assertFalse(unknown.mutation_confirmed)
        self.assertFalse(unknown.real_otp_issued)
        self.assertIsNotNone(self.raw.get(self.keys[0]))
        self.assert_counters(1, 1)
        # An explicit retry faces an existing challenge and does not charge
        # a second time; this is NOT a general idempotency guarantee.
        self.assertEqual(self.issue().status, "challenge_already_pending")
        self.assert_counters(1, 1)
        self.assertEqual(self.verify().status, "synthetic_single_winner")

    def test_lost_consume_ack_does_not_grant_session_even_if_deleted(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        execute = Pipeline.execute
        def commit_and_hide_ack(pipe, *args, **kwargs):
            execute(pipe, *args, **kwargs)
            raise TimeoutError("synthetic consumed but ACK missing")
        with patch.object(Pipeline, "execute", commit_and_hide_ack):
            unknown = self.verify()
        self.assertEqual(unknown.status, "backend_unavailable")
        self.assertFalse(unknown.mutation_confirmed)
        self.no_auth(unknown)
        self.assertEqual(self.verify().status, "missing")
        self.assertIsNone(self.raw.get(self.keys[0]))
        self.assert_counters(1, 1)

    def test_lost_wrong_attempt_ack_must_not_auto_retry(self):
        self.assertEqual(self.issue().status, "synthetic_issued")
        execute = Pipeline.execute
        def commit_and_hide_ack(pipe, *args, **kwargs):
            execute(pipe, *args, **kwargs)
            raise TimeoutError("synthetic wrong attempt committed, ACK missing")
        with patch.object(Pipeline, "execute", commit_and_hide_ack):
            unknown = self.verify(code=WRONG)
        self.assertEqual(unknown.status, "backend_unavailable")
        self.assertFalse(unknown.automatic_retry_authorized)
        self.no_auth(unknown)
        self.assertEqual(
            self.cache.get(f"record:app_login:{MOBILE}")["attempts"], 1,
        )
        # A manually repeated wrong code is a *new* charged attempt. This
        # deliberately exposes the lack of idempotency keys in legacy OTP.
        repeat = self.verify(code=WRONG)
        self.assertEqual(repeat.status, "synthetic_invalid_attempt")
        self.assertEqual(repeat.attempts_remaining, 3)
        self.assertEqual(
            self.cache.get(f"record:app_login:{MOBILE}")["attempts"], 2,
        )
        self.no_auth(repeat)

    def test_invalid_wire_ttl_and_scope_fail_closed(self):
        self.assertEqual(self.verify().status, "missing")
        self.assertEqual(self.issue().status, "synthetic_issued")
        self.raw.set(self.keys[0], b"not a valid django-redis pickle", ex=60)
        self.assertEqual(self.verify().status, "invalid_wire")
        self.assertEqual(self.issue().status, "invalid_existing_record")
        self.raw.persist(self.keys[0])
        self.assertEqual(self.verify().status, "invalid_ttl")
        self.raw.delete(self.keys[0])
        with patch.dict(os.environ, {"LOOMERA_PHASE723_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.verify()
        wrong_db = redis.Redis.from_url("redis://127.0.0.1:6414/14")
        with self.assertRaises(RuntimeError):
            self.verify(client=wrong_db)
        with self.assertRaises(ValueError):
            self.verify(now_ts=True)
        with self.assertRaises(TypeError):
            self.verify(on_watched_read="untrusted")
        self.assert_counters(1, 1)

    def test_physical_test_container_shutdown_fail_closed_and_aof_resume(self):
        """Stop our exact named Docker fixture, verify outage, restart AOF.

        Only possible with GitHub CI + exact test-owned container and label;
        no remote server, production container, host network, or wildcards.
        """
        expected = (
            f"loomera-p722-{os.environ['GITHUB_RUN_ID']}-"
            f"{os.environ['GITHUB_RUN_ATTEMPT']}-redis"
        )
        actual = os.environ.get("LOOMERA_PHASE723_CONTAINER")
        self.assertEqual(actual, expected)
        labels = subprocess.check_output(
            ["docker", "inspect", "--format", "{{json .Config.Labels}}", expected],
            timeout=15, text=True,
        )
        self.assertEqual(json.loads(labels).get("loomera.phase723"), "synthetic")
        self.assertEqual(self.issue().status, "synthetic_issued")
        stored_before = self.raw.get(self.keys[0])
        self.assertIsInstance(stored_before, bytes)
        self.assert_counters(1, 1)
        subprocess.run(["docker", "stop", expected], check=True, timeout=30,
                       capture_output=True)
        try:
            denied_verify = self.verify()
            denied_issue = self.issue(code="654321")
            self.assertEqual(denied_verify.status, "backend_unavailable")
            self.no_auth(denied_verify)
            self.assertEqual(denied_issue.status, "backend_unavailable")
            self.assertFalse(denied_issue.mutation_confirmed)
            self.assertFalse(denied_issue.real_otp_issued)
        finally:
            subprocess.run(["docker", "start", expected], check=True,
                           timeout=30, capture_output=True)
        for _ in range(80):
            try:
                if self.raw.ping():
                    break
            except redis.exceptions.RedisError:
                pass
            time.sleep(.1)
        else:
            self.fail("test-only Redis did not recover after Docker restart")
        self.assertEqual(self.raw.get(self.keys[0]), stored_before)
        self.assert_counters(1, 1)
        # AOF restart is a single-node recovery rehearsal, NOT failover.
        self.assertEqual(self.verify().status, "synthetic_single_winner")
        self.assertEqual(self.verify().status, "missing")
        self.assertEqual(self.issue(code="654321").status, "resend_cooldown_active")
        self.assert_counters(1, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
