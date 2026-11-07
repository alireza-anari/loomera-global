"""Phase 7.11 real Redis 7.4, synthetic-only recovery quarantine races."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_recovery_quarantine_rehearsal import (
    PREFIX, SyntheticQuarantineResult, SyntheticRecoveryQuarantine,
)

URL = "redis://127.0.0.1:6379/15"


class Phase711RecoveryRedisTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE711_TEST_REDIS") != "1":
            self.fail("disposable Phase 7.11 Redis opt-in required")
        self.client = redis.Redis.from_url(URL, socket_timeout=6)
        self.assertTrue(self.client.ping())
        self.key = PREFIX + uuid4().hex
        self.gate = SyntheticRecoveryQuarantine(self.client, key=self.key)

    def tearDown(self):
        try:
            self.gate.cleanup_owned_fixture()
        finally:
            self.client.close()

    def seed(self):
        self.assertEqual(self.gate.seed(), SyntheticQuarantineResult("seeded", 1))

    def consumed(self):
        self.seed()
        self.assertEqual(
            self.gate.record_synthetic_consume(expected_generation=1),
            SyntheticQuarantineResult("recorded", 1),
        )

    def client_gate(self):
        client = redis.Redis.from_url(URL, socket_timeout=6)
        return client, SyntheticRecoveryQuarantine(client, key=self.key)

    def test_seed_is_not_an_authentication(self):
        self.seed()
        result = self.gate.inspect()
        self.assertEqual(result, SyntheticQuarantineResult("observing", 1))
        self.assertFalse(result.authenticated)
        self.assertFalse(result.session_created)
        self.assertFalse(result.safe_to_retry)
        self.assertFalse(result.production_recovery_authorized)
        self.assertFalse(result.legacy_fallback_authorized)

    def test_missing_gate_never_recovers_or_authorizes(self):
        self.assertEqual(self.gate.inspect().status, "missing")
        self.assertEqual(
            self.gate.record_synthetic_consume(expected_generation=1).status,
            "missing",
        )
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=1, reason="redis_timeout",
            ).status, "missing",
        )
        self.assertEqual(self.gate.halt(expected_generation=1).status, "missing")

    def test_seed_is_once_only_and_preserves_fixture_ttl(self):
        self.seed()
        before = self.client.hgetall(self.key)
        ttl = self.client.pttl(self.key)
        self.assertEqual(self.gate.seed().status, "already_seeded")
        self.assertEqual(self.client.hgetall(self.key), before)
        self.assertLessEqual(self.client.pttl(self.key), ttl)
        self.assertGreater(ttl, 0)

    def test_record_consumption_is_a_single_immutable_tombstone(self):
        self.consumed()
        self.assertEqual(
            self.gate.record_synthetic_consume(expected_generation=1).status,
            "already_recorded",
        )
        self.assertEqual(self.client.hget(self.key, "challenge"), b"consumed")

    def test_stale_epoch_does_not_mutate_challenge(self):
        self.seed()
        self.assertEqual(
            self.gate.record_synthetic_consume(expected_generation=2).status,
            "stale_generation",
        )
        self.assertEqual(self.client.hget(self.key, "challenge"), b"none")
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=2, reason="redis_timeout",
            ).status, "stale_generation",
        )
        self.assertEqual(self.gate.inspect().status, "observing")

    def test_quarantine_after_consumed_is_monotone_and_reason_bound(self):
        self.consumed()
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=1, reason="session_store_timeout",
            ),
            SyntheticQuarantineResult("quarantined", 2, "session_store_timeout"),
        )
        self.assertEqual(
            self.gate.inspect(),
            SyntheticQuarantineResult("quarantined", 2, "session_store_timeout"),
        )
        self.assertEqual(
            self.gate.record_synthetic_consume(expected_generation=2).status,
            "wrong_mode",
        )
        self.assertEqual(self.client.hget(self.key, "challenge"), b"consumed")

    def test_quarantine_before_consumption_denies_late_consume(self):
        self.seed()
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=1, reason="redis_timeout",
            ).status, "quarantined",
        )
        self.assertEqual(
            self.gate.record_synthetic_consume(expected_generation=2).status,
            "wrong_mode",
        )
        self.assertEqual(self.client.hget(self.key, "challenge"), b"none")

    def test_duplicate_quarantine_does_not_override_original_reason_or_ttl(self):
        self.consumed()
        first = self.gate.quarantine(
            expected_generation=1, reason="post_commit_timeout",
        )
        ttl = self.client.pttl(self.key)
        repeated = self.gate.quarantine(
            expected_generation=2, reason="account_deactivated",
        )
        self.assertEqual(first.status, "quarantined")
        self.assertEqual(
            repeated, SyntheticQuarantineResult(
                "already_quarantined", 2, "post_commit_timeout",
            ),
        )
        self.assertLessEqual(self.client.pttl(self.key), ttl)

    def test_halt_directly_from_observation_is_terminal(self):
        self.seed()
        self.assertEqual(
            self.gate.halt(expected_generation=1),
            SyntheticQuarantineResult("halted", 2),
        )
        self.assertEqual(self.gate.inspect().status, "halted")
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=2, reason="operator_stop",
            ).status, "already_halted",
        )
        self.assertEqual(
            self.gate.record_synthetic_consume(expected_generation=2).status,
            "wrong_mode",
        )
        self.assertEqual(self.gate.seed().status, "already_seeded")

    def test_halt_after_quarantine_is_terminal_and_retains_cause(self):
        self.consumed()
        self.gate.quarantine(
            expected_generation=1, reason="session_claim_ambiguous",
        )
        self.assertEqual(
            self.gate.halt(expected_generation=2),
            SyntheticQuarantineResult("halted", 3, "session_claim_ambiguous"),
        )
        self.assertEqual(self.gate.halt(expected_generation=3).status, "already_halted")
        self.assertEqual(self.gate.inspect().reason, "session_claim_ambiguous")
        self.assertEqual(self.client.hget(self.key, "generation"), b"3")

    def test_two_redis_connections_race_to_quarantine_one_wins(self):
        self.consumed()
        barrier = Barrier(3, timeout=15)

        def contender(reason):
            client, gate = self.client_gate()
            try:
                barrier.wait(timeout=15)
                return gate.quarantine(
                    expected_generation=1, reason=reason,
                )
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(contender, "redis_timeout")
            b = executor.submit(contender, "account_deactivated")
            barrier.wait(timeout=15)
            results = [a.result(timeout=15), b.result(timeout=15)]

        self.assertEqual(sorted(x.status for x in results),
                         ["already_quarantined", "quarantined"])
        winner = next(x for x in results if x.status == "quarantined")
        self.assertEqual(self.gate.inspect().reason, winner.reason)
        self.assertEqual(self.gate.inspect().generation, 2)
        self.assertEqual(self.client.hget(self.key, "challenge"), b"consumed")

    def test_two_redis_connections_race_to_record_once(self):
        self.seed()
        barrier = Barrier(3, timeout=15)

        def contender():
            client, gate = self.client_gate()
            try:
                barrier.wait(timeout=15)
                return gate.record_synthetic_consume(expected_generation=1).status
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(contender)
            b = executor.submit(contender)
            barrier.wait(timeout=15)
            self.assertEqual(
                sorted([a.result(timeout=15), b.result(timeout=15)]),
                ["already_recorded", "recorded"],
            )

    def test_halt_vs_quarantine_race_never_reopens_observation(self):
        self.consumed()
        barrier = Barrier(3, timeout=15)

        def contender(action):
            client, gate = self.client_gate()
            try:
                barrier.wait(timeout=15)
                if action == "halt":
                    return gate.halt(expected_generation=1).status
                return gate.quarantine(
                    expected_generation=1, reason="session_store_timeout",
                ).status
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(contender, "halt")
            b = executor.submit(contender, "quarantine")
            barrier.wait(timeout=15)
            statuses = {a.result(timeout=15), b.result(timeout=15)}
        self.assertTrue(statuses.intersection({"halted", "quarantined"}))
        self.assertIn(self.gate.inspect().status, {"halted", "quarantined"})
        self.assertNotEqual(self.gate.inspect().status, "observing")

    def test_timeout_after_consumption_is_not_retry_authorization(self):
        self.seed()

        class CommitThenTimeout:
            def __init__(self, real):
                self.real = real
                self.connection_pool = real.connection_pool

            def eval(self, *args):
                self.real.eval(*args)
                raise redis.exceptions.TimeoutError("synthetic post-commit timeout")

        ambiguous = SyntheticRecoveryQuarantine(
            CommitThenTimeout(self.client), key=self.key,
        ).record_synthetic_consume(expected_generation=1)
        self.assertEqual(ambiguous.status, "backend_unavailable")
        self.assertFalse(ambiguous.safe_to_retry)
        self.assertFalse(ambiguous.session_created)
        self.assertEqual(self.gate.inspect().status, "observing")
        self.assertEqual(self.client.hget(self.key, "challenge"), b"consumed")
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=1, reason="post_commit_timeout",
            ).status, "quarantined",
        )

    def test_timeout_after_quarantine_never_reissues_or_releases(self):
        self.consumed()

        class CommitThenTimeout:
            def __init__(self, real):
                self.real = real
                self.connection_pool = real.connection_pool

            def eval(self, *args):
                self.real.eval(*args)
                raise redis.exceptions.TimeoutError("synthetic lost quarantine reply")

        ambiguous = SyntheticRecoveryQuarantine(
            CommitThenTimeout(self.client), key=self.key,
        ).quarantine(expected_generation=1, reason="session_store_timeout")
        self.assertEqual(ambiguous.status, "backend_unavailable")
        self.assertFalse(ambiguous.legacy_fallback_authorized)
        self.assertFalse(ambiguous.authenticated)
        self.assertEqual(self.gate.inspect().status, "quarantined")
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=2, reason="redis_timeout",
            ).reason, "session_store_timeout",
        )

    def test_unavailable_backend_maps_to_denial(self):
        class Broken:
            def __init__(self, real):
                self.connection_pool = real.connection_pool

            def eval(self, *args):
                raise redis.exceptions.ConnectionError("synthetic outage")

        status = SyntheticRecoveryQuarantine(
            Broken(self.client), key=self.key,
        ).seed()
        self.assertEqual(status.status, "backend_unavailable")
        self.assertFalse(status.authenticated)
        self.assertFalse(status.safe_to_retry)

    def test_malformed_responses_never_claim_recovery(self):
        for reply in (None, True, [], [b"halted", 2],
                      ["halted", "2", "none"], [b"unexpected", 2, b"none"],
                      ["halted", 2, "secret"], ["halted", True, "none"],
                      ["halted", -1, "none"]):
            class BadReply:
                def __init__(self, real):
                    self.connection_pool = real.connection_pool

                def eval(self, *args):
                    return reply

            with self.subTest(reply=reply):
                r = SyntheticRecoveryQuarantine(
                    BadReply(self.client), key=self.key,
                ).inspect()
                self.assertEqual(r.status, "backend_unavailable")
                self.assertFalse(r.production_recovery_authorized)

    def test_corrupted_state_is_detected_without_repair(self):
        self.seed()
        self.client.hset(self.key, "generation", "oops")
        self.assertEqual(self.gate.inspect().status, "corrupt")
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=1, reason="redis_timeout",
            ).status, "corrupt",
        )
        self.assertEqual(self.client.hget(self.key, "generation"), b"oops")

    def test_unknown_or_missing_reason_is_corrupt(self):
        self.seed()
        self.client.hset(self.key, "reason", "unknown")
        # The read-only Lua audit rejects an unknown reason as corrupt.
        self.assertEqual(self.gate.inspect().status, "corrupt")
        self.client.hset(self.key, "reason", "none")
        self.gate.quarantine(expected_generation=1, reason="redis_timeout")
        self.client.hset(self.key, "reason", "none")
        self.assertEqual(self.gate.inspect().status, "corrupt")

    def test_wrong_redis_type_fails_closed_without_overwriting(self):
        self.client.setex(self.key, 50, "not-a-hash")
        self.assertEqual(self.gate.seed().status, "already_seeded")
        self.assertEqual(self.gate.inspect().status, "backend_unavailable")
        self.assertEqual(self.client.get(self.key), b"not-a-hash")

    def test_lost_marker_or_expired_gate_never_reconstructs(self):
        self.consumed()
        self.client.delete(self.key)
        self.assertEqual(self.gate.inspect().status, "missing")
        self.assertEqual(self.gate.halt(expected_generation=1).status, "missing")

    def test_fixture_without_ttl_cannot_be_trusted(self):
        self.seed()
        self.client.persist(self.key)
        self.assertEqual(self.gate.inspect().status, "corrupt")
        self.assertFalse(self.gate.inspect().safe_to_retry)

    def test_db15_env_and_fixture_namespace_are_strict(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE711_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.inspect()
        for key in ("loomera:api-auth-otp:record:xyz",
                    "loomera:phase711:synthetic-only:bad",
                    PREFIX + uuid4().hex.upper()):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    SyntheticRecoveryQuarantine(self.client, key=key)
        for url in ("redis://127.0.0.1:6379/14",
                    "redis://notlocalhost.example:6379/15",
                    "redis://u:p@127.0.0.1:6379/15"):
            other = redis.Redis.from_url(url)
            try:
                with self.assertRaises(RuntimeError):
                    SyntheticRecoveryQuarantine(other, key=self.key)
            finally:
                other.close()

    def test_invalid_generation_or_reason_rejected_before_io(self):
        self.seed()
        for value in (0, -1, 1_000_000_001, True, "1", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.gate.quarantine(
                        expected_generation=value, reason="redis_timeout",
                    )
        for value in ("none", "user_identifier", None, True, 5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.gate.quarantine(expected_generation=1, reason=value)
        self.assertEqual(self.gate.inspect().status, "observing")

    def test_cleanup_is_owned_key_only_not_database_flush(self):
        other = PREFIX + uuid4().hex
        self.client.setex(other, 60, "unrelated synthetic fixture")
        try:
            self.consumed()
            self.gate.cleanup_owned_fixture()
            self.assertIsNone(self.client.get(self.key))
            self.assertEqual(self.client.get(other), b"unrelated synthetic fixture")
        finally:
            self.client.delete(other)


if __name__ == "__main__":
    unittest.main()
