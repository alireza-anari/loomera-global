"""Phase 7.14 Redis 7.4 two-node fixture adapter tests (CI private Docker only)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_replica_promotion_rehearsal import (
    PREFIX, SyntheticMarkerObservation, SyntheticPromotedMarkerFence,
)

MASTER_URL = "redis://127.0.0.1:6393/15"
REPLICA_URL = "redis://127.0.0.1:6394/15"


class Phase714RedisPromotionFixtureTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE714_TEST_REDIS") != "1":
            self.fail("Phase 7.14 isolated Docker fixture grant required")
        if os.environ.get("LOOMERA_PHASE714_ACTIVE_LEADER") != "original":
            self.fail("unit tests must precede promotion")
        self.master = redis.Redis.from_url(MASTER_URL, socket_timeout=5)
        self.assertTrue(self.master.ping())
        self.id = uuid4().hex
        self.keys = (
            PREFIX + self.id + ":reference",
            PREFIX + self.id + ":volatile",
        )
        self.gate = SyntheticPromotedMarkerFence(
            self.master, fixture_id=self.id, node="original",
        )

    def tearDown(self):
        try:
            self.gate.cleanup_owned_fixture()
        finally:
            self.master.close()

    def init(self):
        self.assertEqual(
            self.gate.initialize_fixture_for_test(),
            SyntheticMarkerObservation("initialized", 1),
        )

    def other(self):
        client = redis.Redis.from_url(MASTER_URL, socket_timeout=5)
        gate = SyntheticPromotedMarkerFence(
            client, fixture_id=self.id, node="original",
        )
        return client, gate

    def test_initial_seed_is_not_authentication(self):
        self.init()
        self.assertEqual(
            self.gate.inspect_on_selected_primary(),
            SyntheticMarkerObservation("observing", 1),
        )
        r = self.gate.inspect_on_selected_primary()
        for field in (
            "authenticated", "session_created", "can_resume",
            "can_seed_on_restart", "safe_to_retry",
            "legacy_fallback_authorized", "production_recovery_authorized",
        ):
            self.assertFalse(getattr(r, field), field)

    def test_missing_marker_never_implies_seed(self):
        self.assertEqual(
            self.gate.inspect_on_selected_primary().status, "both_lost",
        )
        self.assertEqual(self.master.exists(*self.keys), 0)

    def test_fixture_seed_has_explicit_grant(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE714_ALLOW_TEST_SEED": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.initialize_fixture_for_test()
        self.assertEqual(self.master.exists(*self.keys), 0)

    def test_repeated_seed_does_not_reset_ttl_or_generation(self):
        self.init()
        before = [self.master.hgetall(key) for key in self.keys]
        ttls = [self.master.pttl(key) for key in self.keys]
        self.assertEqual(
            self.gate.initialize_fixture_for_test().status,
            "already_initialized",
        )
        self.assertEqual(before, [self.master.hgetall(key) for key in self.keys])
        for key, ms in zip(self.keys, ttls):
            self.assertGreater(ms, 0)
            self.assertLessEqual(self.master.pttl(key), ms)

    def test_selected_master_checks_actual_role(self):
        self.assertEqual(self.master.info("replication")["role"], "master")
        self.assertEqual(
            self.gate.inspect_on_selected_primary().status, "both_lost",
        )

    def test_replica_cannot_claim_primary_role(self):
        replica = redis.Redis.from_url(REPLICA_URL, socket_timeout=5)
        try:
            r = SyntheticPromotedMarkerFence(
                replica, fixture_id=self.id, node="promoted",
            )
            with patch.dict(os.environ, {"LOOMERA_PHASE714_ACTIVE_LEADER": "promoted"}):
                self.assertEqual(r.inspect_on_selected_primary().status, "not_master")
                self.assertFalse(r.inspect_on_selected_primary().can_resume)
        finally:
            replica.close()

    def test_original_cannot_write_when_test_runner_leader_is_promoted(self):
        self.init()
        with patch.dict(os.environ, {"LOOMERA_PHASE714_ACTIVE_LEADER": "promoted"}):
            r = self.gate.quarantine(
                expected_generation=1, cause="replica_stale",
            )
            self.assertEqual(r.status, "not_active_leader")
            self.assertFalse(r.authenticated)
        self.assertEqual(self.gate.inspect_on_selected_primary().status, "observing")

    def test_unset_leader_denies_even_when_redis_says_master(self):
        self.init()
        with patch.dict(os.environ, {"LOOMERA_PHASE714_ACTIVE_LEADER": ""}):
            self.assertEqual(
                self.gate.inspect_on_selected_primary().status,
                "leader_untrusted",
            )
        self.assertEqual(self.gate.inspect_on_selected_primary().status, "observing")

    def test_unrecognized_leader_denies(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE714_ACTIVE_LEADER": "either"}):
            self.assertEqual(
                self.gate.inspect_on_selected_primary().status,
                "leader_untrusted",
            )

    def test_quarantine_is_monotone_and_reason_immutable(self):
        self.init()
        self.assertEqual(
            self.gate.quarantine(expected_generation=1, cause="replica_stale"),
            SyntheticMarkerObservation("quarantined", 2, "replica_stale"),
        )
        self.assertEqual(
            self.gate.quarantine(expected_generation=2, cause="client_timeout"),
            SyntheticMarkerObservation("already_quarantined", 2, "replica_stale"),
        )

    def test_halt_is_terminal(self):
        self.init()
        self.assertEqual(
            self.gate.halt(expected_generation=1),
            SyntheticMarkerObservation("halted", 2),
        )
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=2, cause="operator_stop",
            ).status, "already_halted",
        )

    def test_stale_generation_cannot_write(self):
        self.init()
        self.assertEqual(
            self.gate.quarantine(
                expected_generation=2, cause="reference_diverged",
            ).status, "stale_generation",
        )
        self.assertEqual(self.gate.inspect_on_selected_primary().generation, 1)

    def test_missing_one_key_denies(self):
        self.init()
        self.master.delete(self.keys[0])
        self.assertEqual(self.gate.inspect_on_selected_primary().status, "reference_lost")
        self.assertEqual(
            self.gate.halt(expected_generation=1).status, "reference_lost",
        )

    def test_divergent_epoch_is_split_brain(self):
        self.init()
        self.master.hset(self.keys[1], "generation", "3")
        self.assertEqual(self.gate.inspect_on_selected_primary().status, "split_brain")

    def test_wrong_redis_type_fails_closed(self):
        self.master.setex(self.keys[0], 60, "wrong-type")
        self.master.setex(self.keys[1], 60, "wrong-type")
        self.assertEqual(
            self.gate.inspect_on_selected_primary().status,
            "backend_unavailable",
        )

    def test_corrupt_generation_fails_closed(self):
        self.init()
        self.master.hset(self.keys[0], "generation", "01")
        self.assertEqual(self.gate.inspect_on_selected_primary().status, "corrupt")

    def test_two_workers_can_quarantine_once(self):
        self.init()
        barrier = Barrier(3, timeout=15)

        def contender(cause):
            client, gate = self.other()
            try:
                barrier.wait(timeout=15)
                return gate.quarantine(expected_generation=1, cause=cause)
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(contender, "client_timeout")
            b = pool.submit(contender, "replica_stale")
            barrier.wait(timeout=15)
            results = [a.result(timeout=15), b.result(timeout=15)]
        self.assertEqual(
            sorted(result.status for result in results),
            ["already_quarantined", "quarantined"],
        )
        winner = next(r for r in results if r.status == "quarantined")
        self.assertEqual(self.gate.inspect_on_selected_primary().cause, winner.cause)

    def test_lost_postcommit_reply_is_denial_not_retry(self):
        self.init()

        class CommitThenTimeout:
            def __init__(self, actual):
                self.actual = actual
                self.connection_pool = actual.connection_pool

            def info(self, *args, **kwargs):
                return self.actual.info(*args, **kwargs)

            def eval(self, *args):
                self.actual.eval(*args)
                raise redis.exceptions.TimeoutError("synthetic lost response")

        unknown = SyntheticPromotedMarkerFence(
            CommitThenTimeout(self.master), fixture_id=self.id,
            node="original",
        ).quarantine(expected_generation=1, cause="lost_write_reply")
        self.assertEqual(unknown.status, "backend_unavailable")
        self.assertFalse(unknown.can_resume)
        self.assertFalse(unknown.safe_to_retry)
        self.assertEqual(self.gate.inspect_on_selected_primary().status, "quarantined")

    def test_malformed_replies_deny(self):
        for bad in (
            None, True, [], ["halted", 2], ["halted", "2", "none"],
            ["halted", True, "none"], ["halted", -1, "none"],
            ["would_login", 2, "none"], ["halted", 2, "email"],
        ):
            class BadReply:
                def __init__(self, actual):
                    self.connection_pool = actual.connection_pool
                    self.actual = actual

                def info(self, *args, **kwargs):
                    return self.actual.info(*args, **kwargs)

                def eval(self, *args):
                    return bad

            with self.subTest(bad=bad):
                result = SyntheticPromotedMarkerFence(
                    BadReply(self.master), fixture_id=self.id,
                    node="original",
                ).inspect_on_selected_primary()
                self.assertEqual(result.status, "backend_unavailable")
                self.assertFalse(result.production_recovery_authorized)

    def test_missing_redis_health_is_denial(self):
        class Broken:
            def __init__(self, actual):
                self.connection_pool = actual.connection_pool

            def info(self, *args, **kwargs):
                raise redis.exceptions.ConnectionError("fixture offline")

        gate = SyntheticPromotedMarkerFence(
            Broken(self.master), fixture_id=self.id, node="original",
        )
        self.assertEqual(gate.inspect_on_selected_primary().status, "backend_unavailable")

    def test_wrong_port_or_db_is_rejected(self):
        for url, node in (
            ("redis://127.0.0.1:6379/15", "original"),
            ("redis://127.0.0.1:6393/14", "original"),
            ("redis://localhost:6393/15", "original"),
            ("redis://127.0.0.1:6394/15", "original"),
            ("redis://127.0.0.1:6393/15", "promoted"),
            ("redis://u:p@127.0.0.1:6393/15", "original"),
            ("redis://remote.invalid:6393/15", "original"),
        ):
            client = redis.Redis.from_url(url)
            try:
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    SyntheticPromotedMarkerFence(
                        client, fixture_id=self.id, node=node,
                    )
            finally:
                client.close()

    def test_environment_guard_is_checked_each_operation(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE714_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.inspect_on_selected_primary()

    def test_only_synthetic_lowercase_fixture_ids(self):
        for bad in ("user", "A" * 32, uuid4().hex + ":phone", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                SyntheticPromotedMarkerFence(
                    self.master, fixture_id=bad, node="original",
                )

    def test_invalid_generations_and_causes_rejected(self):
        for bad in (0, -1, 1_000_000_001, True, "1", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.gate.quarantine(expected_generation=bad, cause="client_timeout")
        for bad in ("none", "secret", None, True, 5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.gate.quarantine(expected_generation=1, cause=bad)

    def test_cleanup_only_two_exact_fixture_keys(self):
        other = PREFIX + uuid4().hex + ":reference"
        self.master.setex(other, 60, "unrelated fixture")
        try:
            self.init()
            self.gate.cleanup_owned_fixture()
            self.assertEqual(self.master.exists(*self.keys), 0)
            self.assertEqual(self.master.get(other), b"unrelated fixture")
        finally:
            self.master.delete(other)


if __name__ == "__main__":
    unittest.main()
