"""Real Redis 7.4 synthetic-only Phase 7.10 atomic challenge and handoff tests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_v2_atomic_handoff_rehearsal import (
    KEY_PREFIX,
    SyntheticOtpHandoffResult,
    SyntheticOtpV2HandoffRehearsal,
)

URL = "redis://127.0.0.1:6379/15"
DIGEST = "a" * 64  # deliberately fake: no OTP code or real account
WRONG_DIGEST = "b" * 64
PURPOSE = "app_login"
SUBJECT = "fixture_subject_a"


class Phase710RealRedisHandoff(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE710_TEST_REDIS") != "1":
            self.fail("explicit disposable Phase 7.10 Redis fixture opt-in required")
        self.client = redis.Redis.from_url(URL, socket_timeout=6)
        self.assertTrue(self.client.ping())
        self.key = KEY_PREFIX + uuid4().hex
        self.unit = SyntheticOtpV2HandoffRehearsal(self.client, key=self.key)

    def tearDown(self):
        try:
            self.unit.cleanup_owned_fixture()
        finally:
            self.client.close()

    def ready(self):
        self.assertEqual(self.unit.bootstrap(), SyntheticOtpHandoffResult("created", 1))
        self.assertEqual(
            self.unit.activate(expected_generation=1),
            SyntheticOtpHandoffResult("activated", 2),
        )

    def issue(self, *, ttl=30):
        return self.unit.issue(
            expected_generation=2, purpose=PURPOSE, subject=SUBJECT,
            synthetic_digest=DIGEST, ttl_seconds=ttl,
        )

    def verify(self, *, digest=DIGEST, purpose=PURPOSE, subject=SUBJECT):
        return self.unit.verify(
            expected_generation=2, purpose=purpose, subject=subject,
            synthetic_digest=digest,
        )

    def admit(self, *, active=True, eligible=True, purpose=PURPOSE, subject=SUBJECT):
        return self.unit.would_admit(
            expected_generation=2, purpose=purpose, subject=subject,
            synthetic_active=active, synthetic_session_eligible=eligible,
        )

    def test_complete_synthetic_handshake_never_authenticates(self):
        self.ready()
        self.assertEqual(self.issue(), SyntheticOtpHandoffResult("issued", 2))
        self.assertEqual(self.verify(), SyntheticOtpHandoffResult("consumed", 2))
        result = self.admit()
        self.assertEqual(result, SyntheticOtpHandoffResult("would_admit", 2))
        self.assertFalse(result.authenticated)
        self.assertFalse(result.session_created)
        self.assertFalse(result.production_cutover_authorized)
        self.assertFalse(result.legacy_fallback_authorized)
        self.assertEqual(self.client.hget(self.key, "challenge"), b"consumed")
        self.assertIsNone(self.client.hget(self.key, "digest"))
        self.assertEqual(self.client.hget(self.key, "admitted"), b"1")

    def test_duplicate_bootstrap_and_issue_do_not_reset_challenge_or_ttl(self):
        self.ready()
        self.assertEqual(self.issue().status, "issued")
        data = self.client.hgetall(self.key)
        ttl = self.client.pttl(self.key)
        self.assertEqual(self.unit.bootstrap().status, "already_exists")
        self.assertEqual(self.issue().status, "already_issued")
        self.assertEqual(self.client.hgetall(self.key), data)
        self.assertLessEqual(self.client.pttl(self.key), ttl)

    def test_before_activation_cannot_issue_or_consume(self):
        self.unit.bootstrap()
        self.assertEqual(
            self.unit.issue(
                expected_generation=1, purpose=PURPOSE, subject=SUBJECT,
                synthetic_digest=DIGEST,
            ).status, "wrong_mode",
        )
        self.assertEqual(
            self.unit.verify(
                expected_generation=1, purpose=PURPOSE, subject=SUBJECT,
                synthetic_digest=DIGEST,
            ).status, "wrong_mode",
        )
        self.assertEqual(self.client.hget(self.key, "challenge"), b"none")

    def test_stale_generation_rejected_for_all_operations(self):
        self.ready()
        self.assertEqual(
            self.unit.issue(
                expected_generation=1, purpose=PURPOSE, subject=SUBJECT,
                synthetic_digest=DIGEST,
            ).status, "stale_generation",
        )
        self.issue()
        self.assertEqual(
            self.unit.verify(
                expected_generation=1, purpose=PURPOSE, subject=SUBJECT,
                synthetic_digest=DIGEST,
            ).status, "stale_generation",
        )
        self.assertEqual(
            self.unit.halt(expected_generation=1).status, "stale_generation",
        )
        self.assertEqual(self.client.hget(self.key, "challenge"), b"issued")

    def test_wrong_subject_and_purpose_do_not_consume_or_increment(self):
        self.ready()
        self.issue()
        self.assertEqual(
            self.verify(subject="fixture_subject_b").status, "binding_mismatch",
        )
        self.assertEqual(
            self.verify(purpose="other_purpose").status, "binding_mismatch",
        )
        self.assertEqual(self.client.hget(self.key, "attempts"), b"0")
        self.assertEqual(self.verify().status, "consumed")

    def test_wrong_digest_has_atomic_attempt_budget_and_tombstone(self):
        self.ready()
        self.issue()
        self.assertEqual(
            self.verify(digest=WRONG_DIGEST),
            SyntheticOtpHandoffResult("invalid_digest", 2, 2),
        )
        self.assertEqual(
            self.verify(digest=WRONG_DIGEST),
            SyntheticOtpHandoffResult("invalid_digest", 2, 1),
        )
        self.assertEqual(
            self.verify(digest=WRONG_DIGEST).status, "exhausted",
        )
        self.assertEqual(self.verify().status, "exhausted")
        self.assertIsNone(self.client.hget(self.key, "digest"))

    def test_expired_challenge_cannot_consume_or_admit(self):
        self.ready()
        self.issue()
        self.client.hset(self.key, "expires_at", 1)  # local fixture only
        self.assertEqual(self.verify().status, "expired")
        self.assertEqual(self.verify().status, "expired")
        self.assertEqual(self.admit().status, "no_challenge")

    def test_consumed_challenge_cannot_be_replayed_or_reissued(self):
        self.ready()
        self.issue()
        self.assertEqual(self.verify().status, "consumed")
        self.assertEqual(self.verify().status, "already_consumed")
        self.assertEqual(self.issue().status, "already_issued")
        self.assertEqual(self.client.hget(self.key, "challenge"), b"consumed")

    def test_parallel_clients_only_one_consumes_valid_digest(self):
        self.ready()
        self.issue()
        barrier = Barrier(3, timeout=15)

        def contender():
            other = redis.Redis.from_url(URL, socket_timeout=6)
            try:
                unit = SyntheticOtpV2HandoffRehearsal(other, key=self.key)
                barrier.wait(timeout=15)
                return unit.verify(
                    expected_generation=2, purpose=PURPOSE, subject=SUBJECT,
                    synthetic_digest=DIGEST,
                ).status
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(contender), pool.submit(contender)
            barrier.wait(timeout=15)
            self.assertEqual(
                sorted([a.result(timeout=15), b.result(timeout=15)]),
                ["already_consumed", "consumed"],
            )

    def test_parallel_clients_only_one_would_admit_session(self):
        self.ready()
        self.issue()
        self.verify()
        barrier = Barrier(3, timeout=15)

        def contender():
            other = redis.Redis.from_url(URL, socket_timeout=6)
            try:
                unit = SyntheticOtpV2HandoffRehearsal(other, key=self.key)
                barrier.wait(timeout=15)
                return unit.would_admit(
                    expected_generation=2, purpose=PURPOSE, subject=SUBJECT,
                    synthetic_active=True, synthetic_session_eligible=True,
                ).status
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(contender), pool.submit(contender)
            barrier.wait(timeout=15)
            self.assertEqual(
                sorted([a.result(timeout=15), b.result(timeout=15)]),
                ["already_admitted", "would_admit"],
            )

    def test_inactive_or_unfit_session_cannot_admit(self):
        self.ready()
        self.issue()
        self.verify()
        self.assertEqual(self.admit(active=False).status, "inactive_subject")
        self.assertEqual(self.admit(eligible=False).status, "session_ineligible")
        self.assertEqual(self.client.hget(self.key, "admitted"), b"0")
        self.assertEqual(self.admit(active=True, eligible=True).status, "would_admit")

    def test_session_receipt_is_short_lived_even_after_consume(self):
        self.ready()
        self.issue()
        self.verify()
        self.client.hset(self.key, "receipt_until", 1)
        self.assertEqual(self.admit().status, "receipt_expired")
        self.assertEqual(self.client.hget(self.key, "admitted"), b"0")

    def test_no_admission_before_consume_or_without_legacy_binding(self):
        self.ready()
        self.issue()
        self.assertEqual(self.admit().status, "no_challenge")
        self.verify()
        self.assertEqual(
            self.admit(subject="fixture_subject_b").status, "binding_mismatch",
        )
        self.assertEqual(
            self.admit(purpose="other_purpose").status, "binding_mismatch",
        )
        self.assertEqual(self.admit().status, "would_admit")

    def test_terminal_halt_blocks_new_verify_issue_and_admit(self):
        self.ready()
        self.issue()
        self.verify()
        self.assertEqual(
            self.unit.halt(expected_generation=2),
            SyntheticOtpHandoffResult("halted", 3),
        )
        self.assertEqual(self.admit().status, "wrong_mode")
        self.assertEqual(self.verify().status, "wrong_mode")
        self.assertEqual(self.issue().status, "wrong_mode")
        self.assertEqual(self.unit.halt(expected_generation=3).status, "already_halted")
        self.assertEqual(self.unit.bootstrap().status, "already_exists")
        self.assertEqual(self.client.hget(self.key, "mode"), b"halted")

    def test_halt_versus_verify_race_never_admits_after_halt(self):
        self.ready()
        self.issue()
        barrier = Barrier(3, timeout=15)

        def verify_other():
            other = redis.Redis.from_url(URL, socket_timeout=6)
            try:
                barrier.wait(timeout=15)
                return SyntheticOtpV2HandoffRehearsal(other, key=self.key).verify(
                    expected_generation=2, purpose=PURPOSE, subject=SUBJECT,
                    synthetic_digest=DIGEST,
                ).status
            finally:
                other.close()

        def halt_other():
            other = redis.Redis.from_url(URL, socket_timeout=6)
            try:
                barrier.wait(timeout=15)
                return SyntheticOtpV2HandoffRehearsal(other, key=self.key).halt(
                    expected_generation=2,
                ).status
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(verify_other), pool.submit(halt_other)
            barrier.wait(timeout=15)
            self.assertIn(a.result(timeout=15), ("consumed", "wrong_mode"))
            self.assertEqual(b.result(timeout=15), "halted")
        self.assertEqual(self.client.hget(self.key, "mode"), b"halted")
        self.assertEqual(
            self.unit.would_admit(
                expected_generation=3, purpose=PURPOSE, subject=SUBJECT,
                synthetic_active=True, synthetic_session_eligible=True,
            ).status, "wrong_mode",
        )

    def test_missing_wrong_type_and_corrupt_record_fail_closed(self):
        self.assertEqual(
            self.unit.verify(
                expected_generation=2, purpose=PURPOSE, subject=SUBJECT,
                synthetic_digest=DIGEST,
            ).status, "missing",
        )
        self.client.set(self.key, "not-a-hash")
        self.assertEqual(self.unit.bootstrap().status, "already_exists")
        self.assertEqual(self.unit.activate(expected_generation=1).status, "backend_unavailable")
        self.client.delete(self.key)
        self.unit.bootstrap()
        self.client.hset(self.key, "generation", "broken")
        self.assertEqual(self.unit.activate(expected_generation=1).status, "corrupt")

    def test_lost_response_after_consumption_never_grants_session(self):
        self.ready()
        self.issue()

        class CommitThenTimeout:
            def __init__(self, actual):
                self.actual = actual
                self.connection_pool = actual.connection_pool

            def eval(self, *args):
                self.actual.eval(*args)
                raise redis.exceptions.TimeoutError("simulated lost response")

        ambiguous = SyntheticOtpV2HandoffRehearsal(
            CommitThenTimeout(self.client), key=self.key,
        ).verify(expected_generation=2, purpose=PURPOSE, subject=SUBJECT,
                 synthetic_digest=DIGEST)
        self.assertEqual(ambiguous.status, "backend_unavailable")
        self.assertFalse(ambiguous.authenticated)
        self.assertEqual(self.verify().status, "already_consumed")
        # A real system must not promote an unacknowledged consumption to login.
        self.assertEqual(self.client.hget(self.key, "admitted"), b"0")
        self.assertEqual(self.unit.halt(expected_generation=2).status, "halted")

    def test_malformed_backend_response_never_authenticates(self):
        for raw in (None, True, ["consumed", 2], ["consumed", "2", 0],
                    ["root", 2, 0], ["would_admit", 2, 10]):
            class BadReply:
                def __init__(self, actual):
                    self.connection_pool = actual.connection_pool

                def eval(self, *args):
                    return raw

            unit = SyntheticOtpV2HandoffRehearsal(BadReply(self.client), key=self.key)
            result = unit.verify(expected_generation=2, purpose=PURPOSE,
                                 subject=SUBJECT, synthetic_digest=DIGEST)
            self.assertEqual(result.status, "backend_unavailable")
            self.assertFalse(result.session_created)
            self.assertFalse(result.authenticated)

    def test_fixture_ttl_expiry_defaults_to_denial_not_legacy_fallback(self):
        self.unit.bootstrap()
        self.client.pexpire(self.key, 1)
        # Do not sleep; delete only the exact fixture and test missing state.
        self.client.delete(self.key)
        self.assertEqual(self.unit.activate(expected_generation=1).status, "missing")
        self.assertEqual(self.unit.halt(expected_generation=1).status, "missing")

    def test_isolation_grant_db15_and_random_fixture_key(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE710_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.unit.bootstrap()
        with self.assertRaises(ValueError):
            SyntheticOtpV2HandoffRehearsal(self.client, key="prod:api:otp")
        for url in (
            "redis://127.0.0.1:6379/14",
            "redis://remote.example:6379/15",
            "redis://u:p@127.0.0.1:6379/15",
        ):
            other = redis.Redis.from_url(url)
            with self.assertRaises(RuntimeError):
                SyntheticOtpV2HandoffRehearsal(other, key=self.key)
            other.close()

    def test_rejects_unbounded_or_nonsynthetic_inputs_before_io(self):
        self.ready()
        for value in ("2", True, -1, 0, 1_000_000_001):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.unit.activate(expected_generation=value)
        for bad in ("plaintext", "f" * 40, "f" * 65, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.unit.issue(expected_generation=2, purpose=PURPOSE,
                                    subject=SUBJECT, synthetic_digest=bad)
        for bad in (True, "True", None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.unit.would_admit(
                        expected_generation=2, purpose=PURPOSE, subject=SUBJECT,
                        synthetic_active=bad, synthetic_session_eligible=True,
                    )
        with self.assertRaises(ValueError):
            self.unit.issue(expected_generation=2, purpose=PURPOSE,
                            subject=SUBJECT, synthetic_digest=DIGEST, ttl_seconds=0)
        with self.assertRaises(ValueError):
            self.unit.issue(expected_generation=2, purpose="password_reset",
                            subject=SUBJECT, synthetic_digest=DIGEST)
        self.assertEqual(self.client.hget(self.key, "challenge"), b"none")

    def test_cleanup_is_key_scoped_not_database_flush(self):
        other_key = KEY_PREFIX + uuid4().hex
        self.client.setex(other_key, 60, "other fixture")
        try:
            self.ready()
            self.unit.cleanup_owned_fixture()
            self.assertIsNone(self.client.get(self.key))
            self.assertEqual(self.client.get(other_key), b"other fixture")
        finally:
            self.client.delete(other_key)


if __name__ == "__main__":
    unittest.main()
