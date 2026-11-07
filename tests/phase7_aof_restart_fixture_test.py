"""Phase 7.13 isolated Redis 7.4 AOF fixture safety and mutation tests.

Run only after tests/phase7_redis_process_restart_ci.sh starts a separate
Redis Docker container on 127.0.0.1:6392 with appendonly yes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_aof_process_restart_rehearsal import (
    PREFIX, SyntheticAofProcessRestartFence, SyntheticMarkerObservation,
)

URL = "redis://127.0.0.1:6392/15"


class Phase713AofFixtureTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE713_TEST_REDIS") != "1":
            self.fail("explicit test-only grant required")
        self.client = redis.Redis.from_url(URL, socket_timeout=4)
        self.assertTrue(self.client.ping())
        self.id = uuid4().hex
        self.keys = (
            PREFIX + self.id + ":reference",
            PREFIX + self.id + ":volatile",
        )
        self.gate = SyntheticAofProcessRestartFence(self.client, fixture_id=self.id)

    def tearDown(self):
        try:
            self.gate.cleanup_owned_fixture()
        finally:
            self.client.close()

    def initialize(self):
        self.assertEqual(
            self.gate.initialize_disposable_fixture_for_test(),
            SyntheticMarkerObservation("initialized", 1),
        )

    def other(self):
        c = redis.Redis.from_url(URL, socket_timeout=4)
        return c, SyntheticAofProcessRestartFence(c, fixture_id=self.id)

    def test_explicit_init_is_never_login(self):
        self.initialize()
        r = self.gate.inspect_after_process_restart()
        self.assertEqual(r, SyntheticMarkerObservation("observing", 1))
        for attr in (
            "authenticated", "session_created", "can_resume",
            "can_seed_on_restart", "safe_to_retry",
            "legacy_fallback_authorized", "production_recovery_authorized",
        ):
            self.assertFalse(getattr(r, attr), attr)

    def test_read_uninitialized_is_missing_and_does_not_boot(self):
        self.assertEqual(
            self.gate.inspect_after_process_restart().status, "both_lost",
        )
        self.assertEqual(self.client.exists(*self.keys), 0)

    def test_initializer_needs_separate_seed_grant(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE713_ALLOW_TEST_SEED": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.initialize_disposable_fixture_for_test()
        self.assertEqual(self.client.exists(*self.keys), 0)

    def test_reinitialization_does_not_extend_existing_ttl(self):
        self.initialize()
        before = [self.client.hgetall(key) for key in self.keys]
        ttl = [self.client.pttl(key) for key in self.keys]
        self.assertEqual(
            self.gate.initialize_disposable_fixture_for_test().status,
            "already_initialized",
        )
        self.assertEqual(before, [self.client.hgetall(key) for key in self.keys])
        for key, ms in zip(self.keys, ttl):
            self.assertGreater(ms, 0)
            self.assertLessEqual(self.client.pttl(key), ms)

    def test_quarantine_is_fenced_and_cause_immutable(self):
        self.initialize()
        self.assertEqual(
            self.gate.quarantine(expected_generation=1, cause="client_timeout"),
            SyntheticMarkerObservation("quarantined", 2, "client_timeout"),
        )
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=2, cause="account_deactivated",
            ),
            SyntheticMarkerObservation("already_quarantined", 2, "client_timeout"),
        )

    def test_quarantine_retains_ttl_and_changes_both(self):
        self.initialize()
        ttl = [self.client.pttl(key) for key in self.keys]
        self.gate.quarantine(expected_generation=1, cause="lost_write_reply")
        for key, old in zip(self.keys, ttl):
            self.assertEqual(self.client.hget(key, "mode"), b"quarantined")
            self.assertEqual(self.client.hget(key, "generation"), b"2")
            self.assertLessEqual(self.client.pttl(key), old)

    def test_halt_is_terminal(self):
        self.initialize()
        self.assertEqual(self.gate.halt(expected_generation=1).status, "halted")
        self.assertEqual(self.gate.halt(expected_generation=2).status, "already_halted")
        self.assertEqual(
            self.gate.quarantine(expected_generation=2, cause="operator_stop").status,
            "already_halted",
        )
        self.assertFalse(self.gate.inspect_after_process_restart().can_resume)

    def test_halt_after_quarantine_retains_cause_and_bumps_generation(self):
        self.initialize()
        self.gate.quarantine(expected_generation=1, cause="session_uncertain")
        self.assertEqual(
            self.gate.halt(expected_generation=2),
            SyntheticMarkerObservation("halted", 3, "session_uncertain"),
        )
        self.assertEqual(self.gate.inspect_after_process_restart().generation, 3)

    def test_stale_generation_does_not_change_mode(self):
        self.initialize()
        self.assertEqual(
            self.gate.quarantine(expected_generation=2, cause="replica_stale").status,
            "stale_generation",
        )
        self.assertEqual(self.gate.inspect_after_process_restart().status, "observing")

    def test_new_client_can_read_without_reseed(self):
        self.initialize()
        client, other = self.other()
        try:
            self.assertEqual(
                other.inspect_after_process_restart(),
                SyntheticMarkerObservation("observing", 1),
            )
            self.assertFalse(other.inspect_after_process_restart().can_resume)
        finally:
            client.close()

    def test_missing_reference_does_not_resurrect(self):
        self.initialize()
        self.client.delete(self.keys[0])
        self.assertEqual(
            self.gate.inspect_after_process_restart().status, "reference_lost",
        )
        self.assertEqual(
            self.gate.initialize_disposable_fixture_for_test().status,
            "partial_lost",
        )
        self.assertEqual(self.client.exists(*self.keys), 1)

    def test_missing_volatile_does_not_resurrect(self):
        self.initialize()
        self.client.delete(self.keys[1])
        self.assertEqual(
            self.gate.inspect_after_process_restart().status, "volatile_lost",
        )
        self.assertEqual(self.gate.halt(expected_generation=1).status, "volatile_lost")

    def test_split_brain_generation_does_not_heal(self):
        self.initialize()
        self.client.hset(self.keys[1], "generation", "3")
        self.assertEqual(self.gate.inspect_after_process_restart().status, "split_brain")
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=1, cause="reference_diverged",
            ).status, "split_brain",
        )

    def test_corrupt_noncanonical_epoch_is_denied(self):
        self.initialize()
        self.client.hset(self.keys[0], "generation", "01")
        self.assertEqual(self.gate.inspect_after_process_restart().status, "corrupt")

    def test_missing_ttl_denied_even_with_matching_values(self):
        self.initialize()
        self.client.persist(self.keys[0])
        self.assertEqual(self.gate.inspect_after_process_restart().status, "corrupt")

    def test_wrong_key_type_denied_no_overwrite(self):
        self.client.setex(self.keys[0], 120, "not-a-hash")
        self.client.setex(self.keys[1], 120, "not-a-hash")
        self.assertEqual(
            self.gate.inspect_after_process_restart().status, "backend_unavailable",
        )
        self.assertEqual(self.client.get(self.keys[0]), b"not-a-hash")

    def test_two_client_quarantine_cas_one_winner(self):
        self.initialize()
        barrier = Barrier(3, timeout=12)

        def worker(cause):
            client, gate = self.other()
            try:
                barrier.wait(timeout=12)
                return gate.quarantine(expected_generation=1, cause=cause)
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as ex:
            a = ex.submit(worker, "replica_stale")
            b = ex.submit(worker, "session_uncertain")
            barrier.wait(timeout=12)
            results = [a.result(timeout=12), b.result(timeout=12)]
        self.assertEqual(
            sorted(x.status for x in results),
            ["already_quarantined", "quarantined"],
        )
        winner = next(x for x in results if x.status == "quarantined")
        self.assertEqual(self.gate.inspect_after_process_restart().cause, winner.cause)

    def test_lost_write_reply_is_not_a_grant(self):
        self.initialize()

        class CommitThenTimeout:
            def __init__(self, actual):
                self.connection_pool = actual.connection_pool
                self.actual = actual

            def eval(self, *args):
                self.actual.eval(*args)
                raise redis.exceptions.TimeoutError("fixture-only post-commit timeout")

        uncertain = SyntheticAofProcessRestartFence(
            CommitThenTimeout(self.client), fixture_id=self.id,
        ).quarantine(expected_generation=1, cause="lost_write_reply")
        self.assertEqual(uncertain.status, "backend_unavailable")
        self.assertFalse(uncertain.authenticated)
        self.assertFalse(uncertain.can_resume)
        self.assertEqual(self.gate.inspect_after_process_restart().status, "quarantined")

    def test_malformed_eval_replies_denied(self):
        for bad in (
            None, True, [], ["halted", 2], ["halted", "2", "none"],
            ["halted", True, "none"], ["halted", -1, "none"],
            ["would_login", 2, "none"], ["halted", 2, "email_address"],
        ):
            class FakeReply:
                def __init__(self, actual):
                    self.connection_pool = actual.connection_pool

                def eval(self, *args):
                    return bad

            with self.subTest(reply=bad):
                result = SyntheticAofProcessRestartFence(
                    FakeReply(self.client), fixture_id=self.id,
                ).inspect_after_process_restart()
                self.assertEqual(result.status, "backend_unavailable")
                self.assertFalse(result.production_recovery_authorized)

    def test_disconnected_backend_maps_to_denial(self):
        class Broken:
            def __init__(self, actual):
                self.connection_pool = actual.connection_pool

            def eval(self, *args):
                raise redis.exceptions.ConnectionError("deliberate fixture outage")

        result = SyntheticAofProcessRestartFence(
            Broken(self.client), fixture_id=self.id,
        ).inspect_after_process_restart()
        self.assertEqual(result.status, "backend_unavailable")
        self.assertFalse(result.safe_to_retry)

    def test_invalid_generation_or_cause_rejected(self):
        self.initialize()
        for invalid in (0, -1, 1_000_000_001, True, "1", None):
            with self.subTest(generation=invalid):
                with self.assertRaises(ValueError):
                    self.gate.quarantine(
                        expected_generation=invalid, cause="client_timeout",
                    )
        for invalid in ("none", "token", True, None, 1):
            with self.subTest(cause=invalid):
                with self.assertRaises(ValueError):
                    self.gate.quarantine(expected_generation=1, cause=invalid)
        self.assertEqual(self.gate.inspect_after_process_restart().status, "observing")

    def test_disallow_main_redis_port_usernames_and_other_database(self):
        for url in (
            "redis://127.0.0.1:6379/15",
            "redis://127.0.0.1:6392/14",
            "redis://localhost:6392/15",
            "redis://u:p@127.0.0.1:6392/15",
            "redis://remote.example:6392/15",
        ):
            client = redis.Redis.from_url(url)
            try:
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    SyntheticAofProcessRestartFence(client, fixture_id=self.id)
            finally:
                client.close()

    def test_grant_and_namespace_checked_on_every_call(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE713_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.inspect_after_process_restart()
        for invalid in ("email", "A" * 32, uuid4().hex + ":session", ""):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                SyntheticAofProcessRestartFence(self.client, fixture_id=invalid)

    def test_cleanup_is_exact_two_keys_not_database_flush(self):
        other = PREFIX + uuid4().hex + ":reference"
        self.client.setex(other, 60, "unrelated fixture")
        try:
            self.initialize()
            self.gate.cleanup_owned_fixture()
            self.assertEqual(self.client.exists(*self.keys), 0)
            self.assertEqual(self.client.get(other), b"unrelated fixture")
        finally:
            self.client.delete(other)


if __name__ == "__main__":
    unittest.main()
