"""Phase 7.9 real Redis isolated VERSION GATE; not an OTP/login adapter.

Requires explicitly opted-in disposable localhost Redis DB15. Exactly one
random fixture key per test, never any real accounts, phone numbers or codes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_versioned_gate_rehearsal import (
    SYNTHETIC_PREFIX,
    SyntheticGateDecision,
    SyntheticOtpVersionGate,
)

REDIS_URL = "redis://127.0.0.1:6379/15"


class Phase79RedisGateTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE79_TEST_REDIS") != "1":
            self.fail("Explicit Phase 7.9 disposable Redis grant required")
        self.client = redis.Redis.from_url(REDIS_URL, socket_timeout=6)
        self.assertTrue(self.client.ping())
        self.key = SYNTHETIC_PREFIX + uuid4().hex
        self.gate = SyntheticOtpVersionGate(self.client, key=self.key)

    def tearDown(self):
        try:
            self.gate.synthetic_cleanup()
        finally:
            self.client.close()

    def seed(self, *, api=0, web=0, reset=0, until=1100):
        return self.gate.seed(
            api_pending=api, web_pending=web, reset_pending=reset,
            drain_until_ts=until, now_ts=1000,
        )

    def test_seed_does_not_overwrite_or_extend_existing_gate(self):
        self.assertEqual(self.seed(api=2), SyntheticGateDecision("seeded", 1))
        before = self.client.hgetall(self.key)
        old_ttl = self.client.pttl(self.key)
        self.assertEqual(self.seed(api=0), SyntheticGateDecision("already_exists", 0))
        self.assertEqual(self.client.hgetall(self.key), before)
        self.assertLessEqual(self.client.pttl(self.key), old_ttl)
        self.assertGreater(self.client.pttl(self.key), 0)

    def test_three_independent_pending_sources_block_activation(self):
        self.seed(api=1, web=1, reset=1)
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=1, now_ts=1200).status,
            "pending_drain",
        )
        self.assertEqual(
            self.gate.reconcile(
                expected_epoch=1, api_pending=0, web_pending=1, reset_pending=1
            ).status, "reconciled",
        )
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=2, now_ts=1200).status,
            "pending_drain",
        )
        self.assertEqual(
            self.gate.reconcile(
                expected_epoch=2, api_pending=0, web_pending=0, reset_pending=1
            ).status, "reconciled",
        )
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=3, now_ts=1200).status,
            "pending_drain",
        )
        self.assertEqual(
            self.gate.reconcile(
                expected_epoch=3, api_pending=0, web_pending=0, reset_pending=0
            ), SyntheticGateDecision("reconciled", 4),
        )
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=4, now_ts=1200),
            SyntheticGateDecision("simulated_v2", 5),
        )

    def test_even_zero_pending_requires_drain_deadline(self):
        self.seed(until=1140)
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=1, now_ts=1139).status,
            "drain_window_active",
        )
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=1, now_ts=1140).status,
            "simulated_v2",
        )

    def test_stale_epoch_reconciliation_rejected_without_mutation(self):
        self.seed(api=3)
        self.assertEqual(
            self.gate.reconcile(
                expected_epoch=1, api_pending=2, web_pending=0, reset_pending=0,
            ).epoch, 2,
        )
        before = self.client.hgetall(self.key)
        self.assertEqual(
            self.gate.reconcile(
                expected_epoch=1, api_pending=0, web_pending=0, reset_pending=0,
            ).status, "stale_epoch",
        )
        self.assertEqual(self.client.hgetall(self.key), before)

    def test_pending_counters_can_only_decrease(self):
        self.seed(api=1, web=0, reset=0)
        self.assertEqual(
            self.gate.reconcile(
                expected_epoch=1, api_pending=2, web_pending=0, reset_pending=0,
            ).status, "increased_pending",
        )
        self.assertEqual(self.client.hget(self.key, "epoch"), b"1")

    def test_two_clients_cannot_both_activate_same_generation(self):
        self.seed()
        barrier = Barrier(3, timeout=20)

        def contender():
            other = redis.Redis.from_url(REDIS_URL, socket_timeout=6)
            try:
                gate = SyntheticOtpVersionGate(other, key=self.key)
                barrier.wait(timeout=20)
                return gate.activate_simulation(
                    expected_epoch=1, now_ts=1150,
                ).status
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(contender)
            b = pool.submit(contender)
            barrier.wait(timeout=20)
            outcomes = sorted((a.result(timeout=20), b.result(timeout=20)))
        self.assertEqual(outcomes, ["invalid_state", "simulated_v2"])
        self.assertEqual(self.client.hget(self.key, "epoch"), b"2")

    def test_would_issue_is_only_counter_never_a_user_or_otp(self):
        self.seed()
        self.assertEqual(
            self.gate.would_issue(expected_epoch=1).status, "invalid_state",
        )
        activation = self.gate.activate_simulation(expected_epoch=1, now_ts=1150)
        self.assertEqual(activation.status, "simulated_v2")
        decision = self.gate.would_issue(expected_epoch=2)
        self.assertEqual(decision, SyntheticGateDecision("would_issue", 2))
        self.assertFalse(decision.authenticated)
        self.assertFalse(decision.production_enabled)
        self.assertFalse(decision.legacy_fallback_allowed)
        self.assertEqual(self.client.hget(self.key, "would_issue_count"), b"1")
        self.assertEqual(
            sorted(self.client.hkeys(self.key)),
            sorted((
                b"mode", b"epoch", b"api_pending", b"web_pending",
                b"reset_pending", b"drain_until", b"would_issue_count",
            )),
        )

    def test_halt_is_terminal_and_no_legacy_fallback_even_after_issue(self):
        self.seed()
        self.gate.activate_simulation(expected_epoch=1, now_ts=1150)
        self.gate.would_issue(expected_epoch=2)
        self.assertEqual(
            self.gate.halt(expected_epoch=2),
            SyntheticGateDecision("halted", 3),
        )
        self.assertEqual(self.gate.halt(expected_epoch=3).status, "already_halted")
        self.assertEqual(self.gate.would_issue(expected_epoch=3).status, "invalid_state")
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=3, now_ts=1200).status,
            "invalid_state",
        )
        self.assertEqual(self.seed().status, "already_exists")
        self.assertEqual(self.client.hget(self.key, "mode"), b"halted")

    def test_missing_or_expired_gate_fails_closed(self):
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=1, now_ts=1150).status,
            "missing",
        )
        self.seed()
        self.client.pexpire(self.key, 1)
        time.sleep(0.02)
        self.assertEqual(self.gate.would_issue(expected_epoch=1).status, "missing")

    def test_corrupt_version_or_wrong_storage_type_fails_closed(self):
        self.seed()
        self.client.hset(self.key, "epoch", "unparseable")
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=1, now_ts=1150).status,
            "corrupt",
        )
        self.client.delete(self.key)
        self.client.set(self.key, "not-a-gate")
        self.assertEqual(
            self.gate.activate_simulation(expected_epoch=1, now_ts=1150).status,
            "backend_unavailable",
        )

    def test_response_lost_after_atomic_change_never_claims_activation(self):
        self.seed()

        class CommitThenDisconnect:
            def __init__(self, actual):
                self.connection_pool = actual.connection_pool
                self.actual = actual

            def eval(self, *args):
                self.actual.eval(*args)
                raise redis.exceptions.TimeoutError("synthetic lost response")

        adapter = SyntheticOtpVersionGate(
            CommitThenDisconnect(self.client), key=self.key,
        )
        result = adapter.activate_simulation(expected_epoch=1, now_ts=1150)
        self.assertEqual(result.status, "backend_unavailable")
        self.assertFalse(result.authenticated)
        self.assertFalse(result.production_enabled)
        self.assertEqual(self.client.hget(self.key, "mode"), b"v2_simulated")
        self.assertEqual(self.gate.halt(expected_epoch=2).status, "halted")

    def test_malformed_script_response_is_never_a_grant(self):
        for raw in (
            [b"simulated_v2", b"bad"],
            [b"simulated_v2", b"1"],
            [b"forged_success", b"2"],
            [b"would_issue", b"123456789012345"],
            True,
        ):
            class ForgedClient:
                def __init__(self, real):
                    self.connection_pool = real.connection_pool

                def eval(self, *args):
                    return raw

            fake = SyntheticOtpVersionGate(ForgedClient(self.client), key=self.key)
            result = fake.activate_simulation(expected_epoch=1, now_ts=1150)
            if raw == [b"simulated_v2", b"1"]:
                # This is a structurally valid script response, but by design
                # even "simulated_v2" never authenticates or enables prod.
                self.assertEqual(result.status, "simulated_v2")
            else:
                self.assertEqual(result.status, "backend_unavailable")
            self.assertFalse(result.authenticated)
            self.assertFalse(result.production_enabled)

    def test_explicit_local_db15_namespace_and_environment_required(self):
        for url in (
            "redis://127.0.0.1:6379/14",
            "redis://remote.example:6379/15",
            "redis://user:password@127.0.0.1:6379/15",
        ):
            with self.subTest(url=url):
                other = redis.Redis.from_url(url)
                with self.assertRaises(RuntimeError):
                    SyntheticOtpVersionGate(other, key=self.key)
                other.close()
        with self.assertRaises(ValueError):
            SyntheticOtpVersionGate(self.client, key="loomera:api-auth-otp:record:app_login")
        with patch.dict(os.environ, {"LOOMERA_PHASE79_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.gate.would_issue(expected_epoch=1)

    def test_invalid_inputs_rejected_without_redis_mutation(self):
        for value in (True, -1, 10001, "0"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.gate.seed(
                        api_pending=value, web_pending=0, reset_pending=0,
                        drain_until_ts=1100, now_ts=1000,
                    )
        with self.assertRaises(ValueError):
            self.gate.seed(
                api_pending=0, web_pending=0, reset_pending=0,
                drain_until_ts=100000, now_ts=1000,
            )
        self.assertFalse(self.client.exists(self.key))

    def test_cleanup_never_removes_other_fixture_keys(self):
        sentinel = SYNTHETIC_PREFIX + uuid4().hex
        self.client.setex(sentinel, 60, "other fixture")
        try:
            self.seed()
            self.gate.synthetic_cleanup()
            self.assertFalse(self.client.exists(self.key))
            self.assertEqual(self.client.get(sentinel), b"other fixture")
        finally:
            self.client.delete(sentinel)


if __name__ == "__main__":
    unittest.main()
