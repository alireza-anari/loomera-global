"""Phase 7.15 isolated temporary SQLite witness transaction/epoch tests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from loomera.globalization.otp_partition_witness_rehearsal import (
    SyntheticLocalPartitionWitness, SyntheticWitnessState, fixture_witness_path,
)


class Phase715LocalWitnessTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE715_WITNESS_TEST") != "1":
            self.fail("explicit fixture grant required")
        self.id = uuid4().hex
        self.path = fixture_witness_path(self.id)
        self.witness = SyntheticLocalPartitionWitness(
            fixture_id=self.id, path=self.path,
        )

    def tearDown(self):
        self.witness.cleanup_owned_fixture()

    def init(self):
        self.assertEqual(
            self.witness.initialize_test_fixture(),
            SyntheticWitnessState("initialized", 1),
        )

    def test_uninitialized_is_unavailable_without_autoseeding(self):
        self.assertEqual(self.witness.inspect().status, "witness_unavailable")
        self.assertFalse(Path(self.path).exists())

    def test_initialization_requires_separate_grant(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE715_ALLOW_TEST_SEED": "0"}):
            with self.assertRaises(RuntimeError):
                self.witness.initialize_test_fixture()
        self.assertFalse(Path(self.path).exists())

    def test_seed_once_preserves_epoch_and_mode(self):
        self.init()
        self.assertEqual(
            self.witness.initialize_test_fixture(),
            SyntheticWitnessState("already_initialized", 1),
        )
        self.assertEqual(self.witness.inspect(), SyntheticWitnessState("observing", 1))

    def test_halt_is_monotone_and_no_login(self):
        self.init()
        result = self.witness.halt(
            expected_generation=1, reason="network_partition",
        )
        self.assertEqual(
            result, SyntheticWitnessState("halted", 2, "network_partition"),
        )
        self.assertFalse(result.authenticated)
        self.assertFalse(result.can_reseed)
        self.assertFalse(result.external_consensus_proven)
        self.assertFalse(result.production_cutover_authorized)

    def test_stop_is_terminal_and_reason_is_immutable(self):
        self.init()
        self.witness.halt(expected_generation=1, reason="dual_master")
        self.assertEqual(
            self.witness.halt(expected_generation=2, reason="operator_stop"),
            SyntheticWitnessState("already_halted", 2, "dual_master"),
        )

    def test_stale_generation_cannot_change_mode(self):
        self.init()
        result = self.witness.halt(
            expected_generation=2, reason="replica_ambiguous",
        )
        self.assertEqual(result, SyntheticWitnessState("stale_generation", 1))
        self.assertEqual(self.witness.inspect().status, "observing")

    def test_second_independent_connection_sees_persisted_halt(self):
        self.init()
        self.witness.halt(expected_generation=1, reason="dual_master")
        attached = SyntheticLocalPartitionWitness(
            fixture_id=self.id, path=self.path,
        )
        self.assertEqual(
            attached.inspect(),
            SyntheticWitnessState("halted", 2, "dual_master"),
        )

    def test_two_threads_race_halt_only_one_wins(self):
        self.init()
        barrier = Barrier(3, timeout=15)

        def worker(reason):
            separate = SyntheticLocalPartitionWitness(
                fixture_id=self.id, path=self.path,
            )
            barrier.wait(timeout=15)
            return separate.halt(expected_generation=1, reason=reason)

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(worker, "dual_master")
            b = pool.submit(worker, "network_partition")
            barrier.wait(timeout=15)
            outcomes = [a.result(timeout=15), b.result(timeout=15)]
        self.assertEqual(
            sorted(x.status for x in outcomes), ["already_halted", "halted"],
        )
        winner = next(x for x in outcomes if x.status == "halted")
        self.assertEqual(self.witness.inspect().reason, winner.reason)

    def test_wrong_expected_generation_rejected(self):
        for value in (0, -1, True, None, "1", 1_000_000_000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.witness.halt(expected_generation=value, reason="dual_master")

    def test_untrusted_reasons_rejected(self):
        for value in ("none", "password", None, True, 1, ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.witness.halt(expected_generation=1, reason=value)

    def test_invalid_ids_and_path_rejected(self):
        for value in ("user", "A" * 32, uuid4().hex + ":otp", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fixture_witness_path(value)
        with self.assertRaises(ValueError):
            SyntheticLocalPartitionWitness(
                fixture_id=self.id, path="/tmp/unrelated.sqlite3",
            )

    def test_flag_guard_rechecked_each_call(self):
        self.init()
        with patch.dict(os.environ, {"LOOMERA_PHASE715_WITNESS_TEST": "0"}):
            with self.assertRaises(RuntimeError):
                self.witness.inspect()

    def test_symlink_file_rejected(self):
        real = "/tmp/loomera-phase715-synthetic-" + uuid4().hex + ".sqlite3"
        Path(real).write_text("unrelated")
        try:
            os.symlink(real, self.path)
            with self.assertRaises(RuntimeError):
                self.witness.inspect()
        finally:
            os.unlink(self.path)
            Path(real).unlink()

    def test_corrupt_unknown_mode_denied(self):
        self.init()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE witness SET mode='live'")
        self.assertEqual(self.witness.inspect().status, "witness_corrupt")

    def test_corrupt_reason_denied(self):
        self.init()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE witness SET reason='unknown'")
        self.assertEqual(self.witness.inspect().status, "witness_corrupt")

    def test_corrupt_generation_denied(self):
        self.init()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE witness SET generation=0")
        self.assertEqual(self.witness.inspect().status, "witness_corrupt")

    def test_missing_row_denied(self):
        self.init()
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM witness")
        self.assertEqual(self.witness.inspect().status, "witness_missing")
        self.assertEqual(
            self.witness.halt(expected_generation=1, reason="dual_master").status,
            "witness_missing",
        )

    def test_file_disappearance_does_not_reseed(self):
        self.init()
        self.witness.cleanup_owned_fixture()
        self.assertEqual(self.witness.inspect().status, "witness_unavailable")
        self.assertFalse(Path(self.path).exists())

    def test_backend_error_does_not_authorize(self):
        self.init()
        with patch.object(self.witness, "_connect", side_effect=sqlite3.OperationalError("fault")):
            result = self.witness.halt(expected_generation=1, reason="dual_master")
            self.assertEqual(result.status, "backend_unavailable")
            self.assertFalse(result.safe_to_retry)

    def test_cleanup_exact_file_preserves_other_fixture(self):
        other_id = uuid4().hex
        other_path = fixture_witness_path(other_id)
        Path(other_path).write_text("another synthetic file")
        try:
            self.init()
            self.witness.cleanup_owned_fixture()
            self.assertFalse(Path(self.path).exists())
            self.assertEqual(Path(other_path).read_text(), "another synthetic file")
        finally:
            Path(other_path).unlink()

    def test_reopen_does_not_require_seed_authority(self):
        self.init()
        self.witness.halt(expected_generation=1, reason="operator_stop")
        with patch.dict(os.environ, {"LOOMERA_PHASE715_ALLOW_TEST_SEED": "0"}):
            attached = SyntheticLocalPartitionWitness(
                fixture_id=self.id, path=self.path,
            )
            self.assertEqual(attached.inspect().status, "halted")
            self.assertFalse(attached.inspect().external_consensus_proven)


if __name__ == "__main__":
    unittest.main()
