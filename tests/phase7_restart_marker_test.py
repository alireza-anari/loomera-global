"""Phase 7.12 real Redis 7.4 disposable two-marker restart/reconnect drill.

Reconnect means new client attached to same Redis server, NOT an actual server
restart, persistence test, cluster failover or replica promotion.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_restart_marker_rehearsal import (
    PREFIX, SyntheticMarkerObservation, SyntheticRestartMarkerFence,
)

URL = "redis://127.0.0.1:6379/15"


class Phase712MarkerReattachRedisTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE712_TEST_REDIS") != "1":
            self.fail("Phase 7.12 disposable fixture opt-in required")
        self.client = redis.Redis.from_url(URL, socket_timeout=6)
        self.assertTrue(self.client.ping())
        self.id = uuid4().hex
        self.keys = (PREFIX + self.id + ":reference", PREFIX + self.id + ":volatile")
        self.gate = SyntheticRestartMarkerFence(self.client, fixture_id=self.id)

    def tearDown(self):
        try:
            self.gate.cleanup_owned_fixture()
        finally:
            self.client.close()

    def init(self):
        self.assertEqual(
            self.gate.initialize_disposable_fixture_for_test(),
            SyntheticMarkerObservation("initialized", 1),
        )

    def other(self):
        client = redis.Redis.from_url(URL, socket_timeout=6)
        return client, SyntheticRestartMarkerFence(client, fixture_id=self.id)

    def test_explicit_fixture_init_is_not_auth(self):
        self.init()
        r = self.gate.inspect_after_reconnect()
        self.assertEqual(r, SyntheticMarkerObservation("observing", 1))
        for attr in (
            "authenticated", "session_created", "can_resume",
            "can_seed_on_restart", "safe_to_retry",
            "legacy_fallback_authorized", "production_recovery_authorized",
        ):
            self.assertFalse(getattr(r, attr), attr)

    def test_fresh_attach_does_not_initialize_missing_markers(self):
        client, reconnect = self.other()
        try:
            self.assertEqual(reconnect.inspect_after_reconnect().status, "both_lost")
            self.assertEqual(
                reconnect.quarantine(
                    expected_generation=1, cause="client_timeout",
                ).status, "both_lost",
            )
            self.assertEqual(reconnect.halt(expected_generation=1).status, "both_lost")
            self.assertFalse(self.client.exists(*self.keys))
        finally:
            client.close()

    def test_init_is_once_only_and_does_not_extend_ttl(self):
        self.init()
        before = [self.client.hgetall(key) for key in self.keys]
        ttls = [self.client.pttl(key) for key in self.keys]
        self.assertEqual(
            self.gate.initialize_disposable_fixture_for_test().status,
            "already_initialized",
        )
        self.assertEqual(before, [self.client.hgetall(key) for key in self.keys])
        for key, ttl in zip(self.keys, ttls):
            self.assertGreater(ttl, 0)
            self.assertLessEqual(self.client.pttl(key), ttl)

    def test_new_independent_client_can_observe_without_reseeding(self):
        self.init()
        client, reconnect = self.other()
        try:
            r = reconnect.inspect_after_reconnect()
            self.assertEqual(r.status, "observing")
            self.assertEqual(r.generation, 1)
            self.assertFalse(r.can_resume)
            self.assertEqual(self.client.exists(*self.keys), 2)
        finally:
            client.close()

    def test_reconnect_after_quarantine_remains_stopped(self):
        self.init()
        self.gate.quarantine(expected_generation=1, cause="lost_write_reply")
        client, reconnect = self.other()
        try:
            self.assertEqual(
                reconnect.inspect_after_reconnect(),
                SyntheticMarkerObservation("quarantined", 2, "lost_write_reply"),
            )
            self.assertEqual(
                reconnect.quarantine(
                    expected_generation=1, cause="replica_stale",
                ).status, "already_quarantined",
            )
            self.assertFalse(reconnect.inspect_after_reconnect().can_resume)
        finally:
            client.close()

    def test_reconnect_after_terminal_halt_still_halted(self):
        self.init()
        self.gate.halt(expected_generation=1)
        client, reconnect = self.other()
        try:
            self.assertEqual(reconnect.inspect_after_reconnect().status, "halted")
            self.assertEqual(reconnect.halt(expected_generation=2).status, "already_halted")
            self.assertEqual(
                reconnect.quarantine(
                    expected_generation=2, cause="client_timeout",
                ).status, "already_halted",
            )
        finally:
            client.close()

    def test_reference_loss_denies_instead_of_rebuilding(self):
        self.init()
        self.client.delete(self.keys[0])
        self.assertEqual(self.gate.inspect_after_reconnect().status, "reference_lost")
        self.assertEqual(
            self.gate.quarantine(expected_generation=1, cause="replica_stale").status,
            "reference_lost",
        )
        self.assertEqual(self.client.exists(*self.keys), 1)

    def test_volatile_loss_denies_instead_of_rebuilding(self):
        self.init()
        self.client.delete(self.keys[1])
        self.assertEqual(self.gate.inspect_after_reconnect().status, "volatile_lost")
        self.assertEqual(self.gate.halt(expected_generation=1).status, "volatile_lost")
        self.assertEqual(self.client.exists(*self.keys), 1)

    def test_reference_expiry_denies_without_sleeping(self):
        self.init()
        self.client.delete(self.keys[0])
        self.assertEqual(self.gate.inspect_after_reconnect().status, "reference_lost")
        self.assertFalse(self.gate.inspect_after_reconnect().can_seed_on_restart)

    def test_volatile_expiry_denies_without_sleeping(self):
        self.init()
        self.client.delete(self.keys[1])
        self.assertEqual(self.gate.inspect_after_reconnect().status, "volatile_lost")
        self.assertFalse(self.gate.inspect_after_reconnect().safe_to_retry)

    def test_both_lost_is_not_silent_rebootstrap(self):
        self.init()
        self.client.delete(*self.keys)
        r = self.gate.inspect_after_reconnect()
        self.assertEqual(r.status, "both_lost")
        self.assertFalse(r.can_seed_on_restart)
        self.assertEqual(self.client.exists(*self.keys), 0)
        # Only a separate explicit test fixture creation method can seed.
        self.assertEqual(self.gate.inspect_after_reconnect().status, "both_lost")

    def test_partial_loss_blocks_fixture_initialization(self):
        self.init()
        self.client.delete(self.keys[1])
        r = self.gate.initialize_disposable_fixture_for_test()
        self.assertEqual(r.status, "partial_lost")
        self.assertEqual(self.client.exists(*self.keys), 1)

    def test_stale_replica_generation_simulation_is_detected(self):
        self.init()
        self.client.hset(self.keys[1], "generation", "0")
        r = self.gate.inspect_after_reconnect()
        self.assertEqual(r.status, "corrupt")
        self.assertFalse(r.can_resume)

    def test_valid_but_regressed_replica_epoch_is_split_brain(self):
        self.init()
        self.gate.quarantine(expected_generation=1, cause="replica_stale")
        self.client.hset(self.keys[1], "generation", "1")
        self.assertEqual(self.gate.inspect_after_reconnect().status, "split_brain")

    def test_future_replica_epoch_is_split_brain(self):
        self.init()
        self.client.hset(self.keys[1], "generation", "3")
        self.assertEqual(self.gate.inspect_after_reconnect().status, "split_brain")

    def test_mode_conflict_between_reference_and_volatile_denies(self):
        self.init()
        self.client.hset(self.keys[1], mapping={
            "mode": "quarantined", "cause": "replica_stale",
        })
        self.assertEqual(self.gate.inspect_after_reconnect().status, "split_brain")

    def test_fingerprint_mismatch_denies(self):
        self.init()
        self.client.hset(self.keys[1], "fingerprint", uuid4().hex)
        self.assertEqual(self.gate.inspect_after_reconnect().status, "split_brain")

    def test_reference_fingerprint_mismatch_to_fixture_denies(self):
        self.init()
        other = uuid4().hex
        for key in self.keys:
            self.client.hset(key, "fingerprint", other)
        self.assertEqual(self.gate.inspect_after_reconnect().status, "split_brain")

    def test_divergent_quarantine_causes_deny(self):
        self.init()
        self.gate.quarantine(expected_generation=1, cause="client_timeout")
        self.client.hset(self.keys[1], "cause", "lost_write_reply")
        self.assertEqual(self.gate.inspect_after_reconnect().status, "split_brain")

    def test_invalid_mode_is_corrupt_not_auto_repaired(self):
        self.init()
        self.client.hset(self.keys[0], "mode", "v2_live")
        self.assertEqual(self.gate.inspect_after_reconnect().status, "corrupt")
        self.assertEqual(self.client.hget(self.keys[0], "mode"), b"v2_live")

    def test_unknown_cause_is_corrupt(self):
        self.init()
        self.client.hset(self.keys[0], "cause", "secret")
        self.assertEqual(self.gate.inspect_after_reconnect().status, "corrupt")

    def test_noncanonical_epoch_is_corrupt(self):
        self.init()
        self.client.hset(self.keys[0], "generation", "01")
        self.assertEqual(self.gate.inspect_after_reconnect().status, "corrupt")

    def test_missing_fixture_ttl_is_rejected(self):
        self.init()
        self.client.persist(self.keys[0])
        self.assertEqual(self.gate.inspect_after_reconnect().status, "corrupt")

    def test_wrong_redis_key_type_is_fail_closed(self):
        self.client.setex(self.keys[0], 60, "wrong type")
        self.client.setex(self.keys[1], 60, "wrong type")
        self.assertEqual(self.gate.inspect_after_reconnect().status, "backend_unavailable")
        self.assertEqual(self.client.get(self.keys[0]), b"wrong type")

    def test_atomic_quarantine_changes_both_without_ttl_extension(self):
        self.init()
        old_ttls = [self.client.pttl(key) for key in self.keys]
        result = self.gate.quarantine(expected_generation=1, cause="client_timeout")
        self.assertEqual(
            result, SyntheticMarkerObservation("quarantined", 2, "client_timeout"),
        )
        for key, old in zip(self.keys, old_ttls):
            self.assertEqual(self.client.hget(key, "generation"), b"2")
            self.assertEqual(self.client.hget(key, "mode"), b"quarantined")
            self.assertLessEqual(self.client.pttl(key), old)

    def test_immutable_quarantine_cause_survives_duplicate_request(self):
        self.init()
        self.gate.quarantine(expected_generation=1, cause="session_uncertain")
        duplicate = self.gate.quarantine(
            expected_generation=2, cause="account_deactivated",
        )
        self.assertEqual(
            duplicate,
            SyntheticMarkerObservation("already_quarantined", 2, "session_uncertain"),
        )
        self.assertEqual(self.gate.inspect_after_reconnect().cause, "session_uncertain")

    def test_stale_generation_cannot_mutate_pair(self):
        self.init()
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=2, cause="client_timeout",
            ).status, "stale_generation",
        )
        self.assertEqual(self.gate.inspect_after_reconnect().status, "observing")
        self.assertEqual(self.gate.inspect_after_reconnect().generation, 1)

    def test_halt_directly_from_observation_is_terminal(self):
        self.init()
        r = self.gate.halt(expected_generation=1)
        self.assertEqual(r, SyntheticMarkerObservation("halted", 2))
        self.assertEqual(self.gate.inspect_after_reconnect().status, "halted")
        self.assertEqual(self.gate.halt(expected_generation=2).status, "already_halted")

    def test_halt_after_quarantine_preserves_original_cause(self):
        self.init()
        self.gate.quarantine(expected_generation=1, cause="lost_write_reply")
        result = self.gate.halt(expected_generation=2)
        self.assertEqual(
            result, SyntheticMarkerObservation("halted", 3, "lost_write_reply"),
        )
        self.assertEqual(self.gate.inspect_after_reconnect().cause, "lost_write_reply")

    def test_two_clients_race_to_quarantine_only_one_wins(self):
        self.init()
        barrier = Barrier(3, timeout=15)

        def contender(reason):
            client, gate = self.other()
            try:
                barrier.wait(timeout=15)
                return gate.quarantine(expected_generation=1, cause=reason)
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as ex:
            a = ex.submit(contender, "client_timeout")
            b = ex.submit(contender, "session_uncertain")
            barrier.wait(timeout=15)
            results = [a.result(timeout=15), b.result(timeout=15)]
        self.assertEqual(
            sorted(x.status for x in results),
            ["already_quarantined", "quarantined"],
        )
        winner = next(x for x in results if x.status == "quarantined")
        self.assertEqual(self.gate.inspect_after_reconnect().cause, winner.cause)

    def test_two_clients_race_halt_vs_quarantine_no_reopen(self):
        self.init()
        barrier = Barrier(3, timeout=15)

        def contender(action):
            client, gate = self.other()
            try:
                barrier.wait(timeout=15)
                if action == "halt":
                    return gate.halt(expected_generation=1).status
                return gate.quarantine(
                    expected_generation=1, cause="replica_stale",
                ).status
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as ex:
            a = ex.submit(contender, "halt")
            b = ex.submit(contender, "quarantine")
            barrier.wait(timeout=15)
            statuses = {a.result(timeout=15), b.result(timeout=15)}
        self.assertTrue(statuses.intersection({"halted", "quarantined"}))
        self.assertIn(self.gate.inspect_after_reconnect().status,
                      ("quarantined", "halted"))

    def test_lost_quarantine_reply_is_never_a_recovery_grant(self):
        self.init()

        class CommittedThenTimeout:
            def __init__(self, actual):
                self.actual = actual
                self.connection_pool = actual.connection_pool

            def eval(self, *args):
                self.actual.eval(*args)
                raise redis.exceptions.TimeoutError("test-only lost reply")

        uncertain = SyntheticRestartMarkerFence(
            CommittedThenTimeout(self.client), fixture_id=self.id,
        ).quarantine(expected_generation=1, cause="lost_write_reply")
        self.assertEqual(uncertain.status, "backend_unavailable")
        self.assertFalse(uncertain.can_resume)
        self.assertFalse(uncertain.safe_to_retry)
        self.assertEqual(self.gate.inspect_after_reconnect().status, "quarantined")

    def test_lost_halt_reply_still_never_reactivates(self):
        self.init()

        class CommittedThenTimeout:
            def __init__(self, actual):
                self.actual = actual
                self.connection_pool = actual.connection_pool

            def eval(self, *args):
                self.actual.eval(*args)
                raise redis.exceptions.TimeoutError("test-only lost reply")

        uncertain = SyntheticRestartMarkerFence(
            CommittedThenTimeout(self.client), fixture_id=self.id,
        ).halt(expected_generation=1)
        self.assertEqual(uncertain.status, "backend_unavailable")
        self.assertFalse(uncertain.production_recovery_authorized)
        self.assertEqual(self.gate.inspect_after_reconnect().status, "halted")

    def test_invalid_reply_never_produces_auth_grant(self):
        for raw in (
            None, True, [], ["quarantined", 2],
            ["quarantined", "2", "client_timeout"],
            ["quarantined", 2, "secret"], ["would_authenticate", 2, "none"],
            ["halted", True, "none"], ["halted", -1, "none"],
        ):
            class FakeReply:
                def __init__(self, actual):
                    self.connection_pool = actual.connection_pool

                def eval(self, *args):
                    return raw

            with self.subTest(raw=raw):
                r = SyntheticRestartMarkerFence(
                    FakeReply(self.client), fixture_id=self.id,
                ).inspect_after_reconnect()
                self.assertEqual(r.status, "backend_unavailable")
                self.assertFalse(r.authenticated)

    def test_explicit_opt_in_namespace_and_db15_guard(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE712_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.inspect_after_reconnect()
        for bad in ("prod:otp", "A" * 32, uuid4().hex + ":secret"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    SyntheticRestartMarkerFence(self.client, fixture_id=bad)
        for url in (
            "redis://127.0.0.1:6379/14",
            "redis://remote.example:6379/15",
            "redis://u:p@127.0.0.1:6379/15",
        ):
            client = redis.Redis.from_url(url)
            try:
                with self.assertRaises(RuntimeError):
                    SyntheticRestartMarkerFence(client, fixture_id=self.id)
            finally:
                client.close()

    def test_invalid_generation_and_cause_rejected_before_io(self):
        self.init()
        for bad in (0, -1, True, "1", 1_000_000_001, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.gate.quarantine(expected_generation=bad, cause="client_timeout")
        for bad in ("none", "production_credential", "", None, 2, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.gate.quarantine(expected_generation=1, cause=bad)
        self.assertEqual(self.gate.inspect_after_reconnect().status, "observing")

    def test_cleanup_only_two_exact_keys_not_all_db15(self):
        other = PREFIX + uuid4().hex + ":reference"
        self.client.setex(other, 60, "other synthetic fixture")
        try:
            self.init()
            self.gate.cleanup_owned_fixture()
            self.assertEqual(self.client.exists(*self.keys), 0)
            self.assertEqual(self.client.get(other), b"other synthetic fixture")
        finally:
            self.client.delete(other)


if __name__ == "__main__":
    unittest.main()
