"""Phase 7.15 Redis 7.4 isolated fixture guard + external SQLite halt tests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_partition_witness_rehearsal import (
    SyntheticLocalPartitionWitness, SyntheticWitnessState, fixture_witness_path,
)
from loomera.globalization.otp_partition_redis_rehearsal import (
    PREFIX, SyntheticPartitionMarkerFence, SyntheticMarkerObservation,
)

SOURCE = "redis://127.0.0.1:6395/15"
FOLLOWER = "redis://127.0.0.1:6396/15"


class Phase715PartitionRedisFixtureTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE715_TEST_REDIS") != "1":
            self.fail("disposable test Redis grant required")
        if os.environ.get("LOOMERA_PHASE715_ACTIVE_LEADER") != "original":
            self.fail("fixture unit tests must precede network partition")
        self.client = redis.Redis.from_url(SOURCE, socket_timeout=5)
        self.assertTrue(self.client.ping())
        self.id = uuid4().hex
        self.wid = uuid4().hex
        self.witness = SyntheticLocalPartitionWitness(
            fixture_id=self.wid, path=fixture_witness_path(self.wid),
        )
        self.assertEqual(
            self.witness.initialize_test_fixture(),
            SyntheticWitnessState("initialized", 1),
        )
        self.gate = SyntheticPartitionMarkerFence(
            self.client, fixture_id=self.id, node="original", witness=self.witness,
        )
        self.keys = (
            PREFIX + self.id + ":reference",
            PREFIX + self.id + ":volatile",
        )

    def tearDown(self):
        try:
            self.gate.cleanup_owned_fixture()
        finally:
            self.client.close()
            self.witness.cleanup_owned_fixture()

    def seed(self):
        self.assertEqual(
            self.gate.initialize_disposable_fixture_for_test(),
            SyntheticMarkerObservation("initialized", 1),
        )

    def test_fixture_init_and_observation_never_login(self):
        self.seed()
        r = self.gate.inspect()
        self.assertEqual(r, SyntheticMarkerObservation("observing", 1))
        for attr in (
            "authenticated", "session_created", "can_resume",
            "can_seed_on_restart", "safe_to_retry",
            "legacy_fallback_authorized", "production_recovery_authorized",
        ):
            self.assertFalse(getattr(r, attr), attr)

    def test_no_autoseed_on_missing_marker(self):
        self.assertEqual(self.gate.inspect().status, "both_lost")
        self.assertEqual(self.client.exists(*self.keys), 0)

    def test_seed_needs_explicit_grant(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE715_ALLOW_TEST_SEED": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.initialize_disposable_fixture_for_test()

    def test_repeated_seed_preserves_ttl(self):
        self.seed()
        ttl = [self.client.pttl(k) for k in self.keys]
        self.assertEqual(
            self.gate.initialize_disposable_fixture_for_test().status,
            "already_initialized",
        )
        for k, old in zip(self.keys, ttl):
            self.assertLessEqual(self.client.pttl(k), old)

    def test_atomic_quarantine_and_terminal_halt(self):
        self.seed()
        self.assertEqual(
            self.gate.quarantine(expected_generation=1, cause="replica_stale"),
            SyntheticMarkerObservation("quarantined", 2, "replica_stale"),
        )
        self.assertEqual(
            self.gate.halt(expected_generation=2),
            SyntheticMarkerObservation("halted", 3, "replica_stale"),
        )
        self.assertEqual(self.gate.inspect().status, "halted")

    def test_local_witness_halt_blocks_observation(self):
        self.seed()
        self.witness.halt(expected_generation=1, reason="dual_master")
        self.assertEqual(self.gate.inspect().status, "witness_halted")

    def test_local_witness_halt_blocks_redis_mutations(self):
        self.seed()
        self.witness.halt(expected_generation=1, reason="network_partition")
        result = self.gate.quarantine(expected_generation=1, cause="replica_stale")
        self.assertEqual(result.status, "witness_halted")
        self.assertFalse(result.safe_to_retry)
        self.assertEqual(self.client.hget(self.keys[0], "generation"), b"1")

    def test_missing_witness_blocks_operations_without_recreating(self):
        self.seed()
        self.witness.cleanup_owned_fixture()
        self.assertEqual(self.gate.inspect().status, "witness_untrusted")
        self.assertEqual(
            self.gate.halt(expected_generation=1).status, "witness_untrusted",
        )
        self.assertFalse(Path(fixture_witness_path(self.wid)).exists())

    def test_corrupted_witness_blocks_operations(self):
        self.seed()
        import sqlite3
        with sqlite3.connect(fixture_witness_path(self.wid)) as db:
            db.execute("UPDATE witness SET generation=0")
        self.assertEqual(self.gate.inspect().status, "witness_untrusted")

    def test_unknown_leader_blocks(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE715_ACTIVE_LEADER": ""}):
            self.assertEqual(self.gate.inspect().status, "leader_untrusted")

    def test_other_endpoint_blocks_even_if_redis_master(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE715_ACTIVE_LEADER": "promoted"}):
            self.assertEqual(self.gate.inspect().status, "not_active_leader")

    def test_current_replica_not_eligible_for_mutation(self):
        replica = redis.Redis.from_url(FOLLOWER, socket_timeout=5)
        try:
            gate = SyntheticPartitionMarkerFence(
                replica, fixture_id=self.id, node="promoted",
                witness=self.witness,
            )
            with patch.dict(os.environ, {"LOOMERA_PHASE715_ACTIVE_LEADER": "promoted"}):
                self.assertEqual(gate.inspect().status, "not_master")
        finally:
            replica.close()

    def test_mutation_needs_extra_fixture_grant(self):
        self.seed()
        with patch.dict(os.environ, {"LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION": "0"}):
            self.assertEqual(
                self.gate.quarantine(
                    expected_generation=1, cause="replica_stale",
                ).status, "fixture_write_not_granted",
            )
        self.assertEqual(self.gate.inspect().status, "observing")

    def test_stale_generation_denies(self):
        self.seed()
        self.assertEqual(
            self.gate.halt(expected_generation=2).status, "stale_generation",
        )

    def test_key_loss_denies_without_repair(self):
        self.seed()
        self.client.delete(self.keys[0])
        self.assertEqual(self.gate.inspect().status, "reference_lost")

    def test_bad_namespace_and_db_guard(self):
        for url, node in (
            ("redis://127.0.0.1:6379/15", "original"),
            ("redis://localhost:6395/15", "original"),
            ("redis://127.0.0.1:6395/14", "original"),
            ("redis://127.0.0.1:6396/15", "original"),
            ("redis://u:p@127.0.0.1:6395/15", "original"),
        ):
            other = redis.Redis.from_url(url)
            try:
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    SyntheticPartitionMarkerFence(
                        other, fixture_id=self.id, node=node,
                        witness=self.witness,
                    )
            finally:
                other.close()

    def test_unknown_fixture_id_and_missing_witness_denied(self):
        for invalid in ("otp", "A" * 32, None, self.id + ":user"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                SyntheticPartitionMarkerFence(
                    self.client, fixture_id=invalid, node="original",
                    witness=self.witness,
                )
        with self.assertRaises(TypeError):
            SyntheticPartitionMarkerFence(
                self.client, fixture_id=self.id, node="original", witness=None,
            )

    def test_env_grant_rechecked_each_call(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE715_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.inspect()

    def test_invalid_generation_and_cause_denied(self):
        for value in (0, -1, None, True, "1", 1_000_000_000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.gate.quarantine(expected_generation=value, cause="replica_stale")
        for value in ("none", "bad", None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.gate.quarantine(expected_generation=1, cause=value)

    def test_two_workers_atomic_quarantine(self):
        self.seed()
        barrier = Barrier(3, timeout=15)

        def worker(reason):
            cli = redis.Redis.from_url(SOURCE, socket_timeout=5)
            gate = SyntheticPartitionMarkerFence(
                cli, fixture_id=self.id, node="original", witness=self.witness,
            )
            try:
                barrier.wait(timeout=15)
                return gate.quarantine(expected_generation=1, cause=reason)
            finally:
                cli.close()

        with ThreadPoolExecutor(max_workers=2) as ex:
            a = ex.submit(worker, "client_timeout")
            b = ex.submit(worker, "replica_stale")
            barrier.wait(timeout=15)
            outcomes = [a.result(timeout=15), b.result(timeout=15)]
        self.assertEqual(
            sorted(x.status for x in outcomes), ["already_quarantined", "quarantined"],
        )

    def test_cleanup_only_fixture_owned_keys(self):
        other = PREFIX + uuid4().hex + ":reference"
        self.client.setex(other, 60, "other synthetic")
        try:
            self.seed()
            self.gate.cleanup_owned_fixture()
            self.assertEqual(self.client.exists(*self.keys), 0)
            self.assertEqual(self.client.get(other), b"other synthetic")
        finally:
            self.client.delete(other)


if __name__ == "__main__":
    unittest.main()
