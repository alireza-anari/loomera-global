"""Phase 7.16 real Redis Lua epoch token fixture tests, localhost 6397 only."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_epoch_witness_rehearsal import (
    SyntheticLocalEpochWitness, witness_path,
)
from loomera.globalization.otp_epoch_redis_rehearsal import (
    PREFIX, EPOCH_SCRIPT, SyntheticEpochRedisFence, SyntheticEpochWrite,
)

URL = "redis://127.0.0.1:6397/15"


class Phase716EpochRedisTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get("LOOMERA_PHASE716_TEST_REDIS"), "1")
        self.assertEqual(os.environ.get("LOOMERA_PHASE716_TEST_WITNESS"), "1")
        self.assertEqual(os.environ.get("LOOMERA_PHASE716_ACTIVE_LEADER"), "original")
        self.client = redis.Redis.from_url(URL, socket_timeout=5)
        self.assertTrue(self.client.ping())
        self.id, self.wid, self.a = uuid4().hex, uuid4().hex, uuid4().hex
        self.witness = SyntheticLocalEpochWitness(
            fixture_id=self.wid, path=witness_path(self.wid),
        )
        self.assertEqual(self.witness.initialize_fixture(token=self.a).status, "initialized")
        self.gate = SyntheticEpochRedisFence(
            self.client, fixture_id=self.id, node="original", witness=self.witness,
        )
        self.keys = (PREFIX+self.id+":fence", PREFIX+self.id+":counter")

    def tearDown(self):
        try:
            self.gate.cleanup_owned_fixture()
        finally:
            self.client.close()
            self.witness.cleanup_owned_fixture()

    def seed(self):
        self.assertEqual(
            self.gate.initialize_fixture(token=self.a),
            SyntheticEpochWrite("initialized", 1, 0),
        )

    def write(self, seq=0, token=None, epoch=1):
        return self.gate.write_fixture_marker(
            owner="original", epoch=epoch, token=token or self.a,
            expected_sequence=seq,
        )

    def test_seed_is_not_auth(self):
        self.seed()
        r = self.gate.inspect(owner="original", epoch=1, token=self.a)
        self.assertEqual(r, SyntheticEpochWrite("active", 1, 0))
        for field in (
            "authenticated", "session_created", "otp_reissue_allowed",
            "can_resume", "safe_to_retry", "production_cutover_authorized",
            "legacy_fallback_authorized", "cross_store_atomicity_proven",
        ):
            self.assertFalse(getattr(r, field), field)

    def test_missing_fixture_is_not_autoseeded_by_attach(self):
        self.assertEqual(
            self.gate.inspect(owner="original", epoch=1, token=self.a).status,
            "both_lost",
        )
        self.assertEqual(self.client.exists(*self.keys), 0)

    def test_seed_grant_is_explicit(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE716_ALLOW_SEED": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.initialize_fixture(token=self.a)

    def test_repeated_seed_does_not_reset_state_or_ttl(self):
        self.seed()
        self.write()
        ttl = [self.client.pttl(x) for x in self.keys]
        self.assertEqual(self.gate.initialize_fixture(token=self.a).status,
                         "already_initialized")
        self.assertEqual(self.gate.inspect(owner="original", epoch=1, token=self.a).sequence, 1)
        for k, ms in zip(self.keys, ttl):
            self.assertLessEqual(self.client.pttl(k), ms)

    def test_write_requires_extra_grant(self):
        self.seed()
        with patch.dict(os.environ, {"LOOMERA_PHASE716_ALLOW_TEST_WRITE": "0"}):
            self.assertEqual(self.write().status, "mutation_not_granted")
        self.assertEqual(self.client.hget(self.keys[1], "sequence"), b"0")

    def test_epoch_and_sequence_cas_are_atomic(self):
        self.seed()
        self.assertEqual(self.write(), SyntheticEpochWrite("written", 1, 1))
        self.assertEqual(self.write(seq=0).status, "stale_sequence")
        self.assertEqual(self.write(seq=1), SyntheticEpochWrite("written", 1, 2))

    def test_wrong_redis_token_fenced_inside_lua(self):
        self.seed()
        other = uuid4().hex
        reply = self.client.eval(
            EPOCH_SCRIPT, 2, *self.keys, "write", self.id,
            "original", 1, other, 0,
        )
        self.assertEqual(reply[0], b"fenced")
        self.assertEqual(self.client.hget(self.keys[1], "sequence"), b"0")

    def test_future_redis_epoch_fenced_inside_lua(self):
        self.seed()
        reply = self.client.eval(
            EPOCH_SCRIPT, 2, *self.keys, "write", self.id,
            "original", 2, self.a, 0,
        )
        self.assertEqual(reply[0], b"fenced")

    def test_witness_rotation_blocks_old_adapter_but_not_raw_master(self):
        self.seed()
        b = uuid4().hex
        self.assertEqual(self.witness.rotate_to_promoted(
            expected_epoch=1, expected_token=self.a, next_token=b,
        ).status, "rotated")
        self.assertEqual(self.write().status, "stale_token")
        self.assertEqual(self.client.hget(self.keys[1], "sequence"), b"0")
        # Known weakness: raw Redis still sees old local epoch/token.
        reply = self.client.eval(
            EPOCH_SCRIPT, 2, *self.keys, "write", self.id,
            "original", 1, self.a, 0,
        )
        self.assertEqual(reply[0], b"written")
        self.assertEqual(reply[2], 1)
        self.assertFalse(self.gate.inspect(owner="original", epoch=1, token=self.a).authenticated)

    def test_loss_of_witness_denies_both_read_and_write(self):
        self.seed()
        self.witness.cleanup_owned_fixture()
        self.assertEqual(self.write().status, "witness_untrusted")
        self.assertEqual(
            self.gate.inspect(owner="original", epoch=1, token=self.a).status,
            "witness_untrusted",
        )
        self.assertFalse(Path(witness_path(self.wid)).exists())

    def test_witness_terminal_halt_blocks_write(self):
        self.seed()
        self.assertEqual(self.witness.halt(
            expected_epoch=1, expected_token=self.a, reason="leader_ambiguity",
        ).status, "halted")
        self.assertEqual(self.write().status, "witness_halted")

    def test_wrong_owner_role_env_is_denied(self):
        self.seed()
        with patch.dict(os.environ, {"LOOMERA_PHASE716_ACTIVE_LEADER": "promoted"}):
            self.assertEqual(self.write().status, "not_selected")
        with patch.dict(os.environ, {"LOOMERA_PHASE716_ACTIVE_LEADER": ""}):
            self.assertEqual(self.write().status, "leader_untrusted")

    def test_missing_reference_key_fails_closed(self):
        self.seed()
        self.client.delete(self.keys[0])
        self.assertEqual(
            self.gate.inspect(owner="original", epoch=1, token=self.a).status,
            "fence_lost",
        )
        self.assertEqual(self.write().status, "fence_lost")

    def test_missing_counter_key_fails_closed(self):
        self.seed()
        self.client.delete(self.keys[1])
        self.assertEqual(self.write().status, "counter_lost")

    def test_noncanonical_epoch_and_missing_ttl_are_corrupt(self):
        self.seed()
        self.client.hset(self.keys[0], "epoch", "01")
        self.assertEqual(self.write().status, "corrupt")
        self.client.hset(self.keys[0], "epoch", "1")
        self.client.persist(self.keys[0])
        self.assertEqual(self.write().status, "corrupt")

    def test_witness_and_redis_token_divergence_denied(self):
        self.seed()
        self.client.hset(self.keys[0], "token", uuid4().hex)
        self.assertEqual(self.write().status, "corrupt")

    def test_replayed_sequence_race_one_winner(self):
        self.seed()
        barrier = Barrier(3, timeout=15)

        def writer():
            cli = redis.Redis.from_url(URL, socket_timeout=5)
            gate = SyntheticEpochRedisFence(
                cli, fixture_id=self.id, node="original", witness=self.witness,
            )
            try:
                barrier.wait(timeout=15)
                return gate.write_fixture_marker(
                    owner="original", epoch=1, token=self.a, expected_sequence=0,
                )
            finally:
                cli.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(writer)
            b = pool.submit(writer)
            barrier.wait(timeout=15)
            results = [a.result(timeout=15), b.result(timeout=15)]
        self.assertEqual(sorted(r.status for r in results),
                         ["stale_sequence", "written"])
        self.assertEqual(self.client.hget(self.keys[1], "sequence"), b"1")

    def test_lost_postcommit_reply_is_denial(self):
        self.seed()

        class CommitThenTimeout:
            def __init__(self, actual):
                self.actual = actual
                self.connection_pool = actual.connection_pool

            def info(self, *args, **kwargs):
                return self.actual.info(*args, **kwargs)

            def eval(self, *args):
                self.actual.eval(*args)
                raise redis.exceptions.TimeoutError("test-only lost response")

        result = SyntheticEpochRedisFence(
            CommitThenTimeout(self.client), fixture_id=self.id,
            node="original", witness=self.witness,
        ).write_fixture_marker(
            owner="original", epoch=1, token=self.a, expected_sequence=0,
        )
        self.assertEqual(result.status, "backend_unavailable")
        self.assertFalse(result.safe_to_retry)
        self.assertEqual(self.gate.inspect(owner="original", epoch=1, token=self.a).sequence, 1)

    def test_invalid_result_and_timeout_fail_closed(self):
        self.seed()
        for response in (
            None, True, ["written", "1", 1], ["written", True, 1],
            ["login", 1, 1], ["written", -1, 0], ["written", 1],
        ):
            class Bad:
                def __init__(self, actual):
                    self.connection_pool = actual.connection_pool
                    self.actual = actual

                def info(self, *args, **kwargs):
                    return self.actual.info(*args, **kwargs)

                def eval(self, *args):
                    return response

            with self.subTest(response=response):
                r = SyntheticEpochRedisFence(
                    Bad(self.client), fixture_id=self.id, node="original",
                    witness=self.witness,
                ).inspect(owner="original", epoch=1, token=self.a)
                self.assertEqual(r.status, "backend_unavailable")

    def test_wrong_local_endpoint_and_credentials_denied(self):
        for url, node in (
            ("redis://127.0.0.1:6379/15", "original"),
            ("redis://127.0.0.1:6397/14", "original"),
            ("redis://localhost:6397/15", "original"),
            ("redis://127.0.0.1:6398/15", "original"),
            ("redis://u:p@127.0.0.1:6397/15", "original"),
        ):
            cli = redis.Redis.from_url(url)
            try:
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    SyntheticEpochRedisFence(
                        cli, fixture_id=self.id, node=node, witness=self.witness,
                    )
            finally:
                cli.close()

    def test_strict_fixture_tokens_and_epochs(self):
        for token in ("bad", "A"*32, None, 1):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.gate.inspect(owner="original", epoch=1, token=token)
        for epoch in (0, -1, True, None, "1", 1_000_000_000):
            with self.subTest(epoch=epoch), self.assertRaises(ValueError):
                self.gate.write_fixture_marker(
                    owner="original", epoch=epoch, token=self.a, expected_sequence=0,
                )
        for seq in (-1, True, None, "0", 1_000_000_000):
            with self.subTest(seq=seq), self.assertRaises(ValueError):
                self.gate.write_fixture_marker(
                    owner="original", epoch=1, token=self.a, expected_sequence=seq,
                )

    def test_guards_rechecked_and_cleanup_is_exact_keys(self):
        other = PREFIX+uuid4().hex+":fence"
        self.client.setex(other, 60, "other synthetic")
        try:
            with patch.dict(os.environ, {"LOOMERA_PHASE716_TEST_REDIS": "0"}):
                with self.assertRaises(RuntimeError):
                    self.gate.inspect(owner="original", epoch=1, token=self.a)
            self.seed()
            self.gate.cleanup_owned_fixture()
            self.assertEqual(self.client.exists(*self.keys), 0)
            self.assertEqual(self.client.get(other), b"other synthetic")
        finally:
            self.client.delete(other)


if __name__ == "__main__":
    unittest.main()
