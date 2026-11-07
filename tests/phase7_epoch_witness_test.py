"""Phase 7.16 single-host SQLite witness rotation, loss and monotone CAS."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from loomera.globalization.otp_epoch_witness_rehearsal import (
    SyntheticLeaderEpoch, SyntheticLocalEpochWitness, witness_path,
)


class Phase716EpochWitnessTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get("LOOMERA_PHASE716_TEST_WITNESS"), "1")
        self.id = uuid4().hex
        self.path = witness_path(self.id)
        self.witness = SyntheticLocalEpochWitness(fixture_id=self.id, path=self.path)
        self.a = uuid4().hex
        self.b = uuid4().hex

    def tearDown(self):
        self.witness.cleanup_owned_fixture()

    def seed(self):
        self.assertEqual(
            self.witness.initialize_fixture(token=self.a),
            SyntheticLeaderEpoch("initialized", 1, "original", self.a),
        )

    def rotate(self):
        return self.witness.rotate_to_promoted(
            expected_epoch=1, expected_token=self.a, next_token=self.b,
        )

    def test_missing_witness_does_not_create_itself(self):
        self.assertEqual(self.witness.inspect().status, "unavailable")
        self.assertFalse(Path(self.path).exists())

    def test_explicit_fixture_seed_needs_grant(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE716_ALLOW_SEED": "0"}):
            with self.assertRaises(RuntimeError):
                self.witness.initialize_fixture(token=self.a)
        self.assertFalse(Path(self.path).exists())

    def test_seed_is_observation_not_login(self):
        self.seed()
        result = self.witness.inspect()
        self.assertEqual(result, SyntheticLeaderEpoch("active", 1, "original", self.a))
        for flag in (
            "authenticated", "session_created", "otp_reissue_allowed", "can_resume",
            "can_reseed_after_loss", "safe_to_retry", "external_consensus_proven",
            "legacy_fallback_authorized", "production_cutover_authorized",
        ):
            self.assertFalse(getattr(result, flag), flag)

    def test_repeated_seed_preserves_original_token(self):
        self.seed()
        result = self.witness.initialize_fixture(token=self.b)
        self.assertEqual(result.status, "already_initialized")
        self.assertEqual(result.token, self.a)

    def test_rotation_increments_and_replaces_token(self):
        self.seed()
        self.assertEqual(self.rotate(), SyntheticLeaderEpoch("rotated", 2, "promoted", self.b))
        self.assertEqual(self.witness.inspect(), SyntheticLeaderEpoch("active", 2, "promoted", self.b))

    def test_reuse_old_token_denied_after_rotation(self):
        self.seed()
        self.rotate()
        self.assertEqual(
            self.witness.rotate_to_promoted(
                expected_epoch=1, expected_token=self.a, next_token=uuid4().hex,
            ).status, "already_promoted",
        )
        self.assertEqual(self.witness.inspect().token, self.b)

    def test_wrong_old_token_denied(self):
        self.seed()
        self.assertEqual(
            self.witness.rotate_to_promoted(
                expected_epoch=1, expected_token=self.b, next_token=uuid4().hex,
            ).status, "stale_token",
        )

    def test_stale_and_future_epoch_denied(self):
        self.seed()
        for epoch in (2, 3):
            with self.subTest(epoch=epoch):
                self.assertEqual(
                    self.witness.rotate_to_promoted(
                        expected_epoch=epoch, expected_token=self.a, next_token=self.b,
                    ).status, "stale_token",
                )
        self.assertEqual(self.witness.inspect().epoch, 1)

    def test_token_reuse_for_new_epoch_forbidden(self):
        self.seed()
        with self.assertRaises(ValueError):
            self.witness.rotate_to_promoted(
                expected_epoch=1, expected_token=self.a, next_token=self.a,
            )

    def test_two_rotators_only_one_wins(self):
        self.seed()
        bar = Barrier(3, timeout=15)

        def contender(token):
            w = SyntheticLocalEpochWitness(fixture_id=self.id, path=self.path)
            bar.wait(timeout=15)
            return w.rotate_to_promoted(
                expected_epoch=1, expected_token=self.a, next_token=token,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(contender, self.b)
            f2 = pool.submit(contender, uuid4().hex)
            bar.wait(timeout=15)
            results = [f1.result(timeout=15), f2.result(timeout=15)]
        self.assertEqual(
            sorted(r.status for r in results), ["already_promoted", "rotated"],
        )
        self.assertEqual(self.witness.inspect().epoch, 2)

    def test_read_after_rotation_by_fresh_connection(self):
        self.seed()
        self.rotate()
        fresh = SyntheticLocalEpochWitness(fixture_id=self.id, path=self.path)
        self.assertEqual(fresh.inspect().token, self.b)
        self.assertEqual(fresh.inspect().owner, "promoted")

    def test_stop_is_terminal_after_rotation(self):
        self.seed()
        self.rotate()
        stopped = self.witness.halt(
            expected_epoch=2, expected_token=self.b, reason="leader_ambiguity",
        )
        self.assertEqual(
            stopped,
            SyntheticLeaderEpoch("halted", 3, "promoted", self.b, "leader_ambiguity"),
        )
        self.assertEqual(self.witness.inspect().status, "halted")
        self.assertEqual(
            self.witness.halt(
                expected_epoch=3, expected_token=self.b, reason="operator_stop",
            ).status, "already_halted",
        )
        self.assertEqual(
            self.witness.rotate_to_promoted(
                expected_epoch=3, expected_token=self.b, next_token=uuid4().hex,
            ).status, "halted",
        )

    def test_halt_rejects_stale_token(self):
        self.seed()
        self.rotate()
        self.assertEqual(
            self.witness.halt(
                expected_epoch=1, expected_token=self.a, reason="operator_stop",
            ).status, "stale_token",
        )
        self.assertEqual(self.witness.inspect().status, "active")

    def test_corrupt_owner_fails_closed(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE leader SET owner='attacker'")
        self.assertEqual(self.witness.inspect().status, "corrupt")
        self.assertEqual(self.rotate().status, "corrupt")

    def test_corrupt_epoch_fails_closed(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE leader SET epoch=0")
        self.assertEqual(self.witness.inspect().status, "corrupt")

    def test_missing_row_fails_closed(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM leader")
        self.assertEqual(self.witness.inspect().status, "missing")
        self.assertEqual(self.rotate().status, "missing")

    def test_deleted_witness_does_not_auto_recreate(self):
        self.seed()
        self.witness.cleanup_owned_fixture()
        self.assertEqual(self.witness.inspect().status, "unavailable")
        self.assertFalse(Path(self.path).exists())

    def test_untrusted_id_or_path_rejected(self):
        for bad in ("customer", "A"*32, None, self.id+":otp"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                witness_path(bad)
        with self.assertRaises(ValueError):
            SyntheticLocalEpochWitness(fixture_id=self.id, path="/tmp/live.db")

    def test_unknown_seed_and_rotation_tokens_rejected(self):
        for bad in (None, "password", "A"*32, True, 1234):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.witness.initialize_fixture(token=bad)
        self.seed()
        for bad in (None, "password", True, "A"*32):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.witness.rotate_to_promoted(
                    expected_epoch=1, expected_token=bad, next_token=self.b,
                )

    def test_boolean_or_out_of_range_epochs_rejected(self):
        for bad in (True, -1, 0, None, "1", 1_000_000_000):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.witness.rotate_to_promoted(
                    expected_epoch=bad, expected_token=self.a, next_token=self.b,
                )

    def test_wrong_reason_not_accepted(self):
        for bad in ("none", "login", None, 1, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.witness.halt(
                    expected_epoch=1, expected_token=self.a, reason=bad,
                )

    def test_symlink_denied_without_touching_target(self):
        target = "/tmp/loomera-phase716-synthetic-" + uuid4().hex + ".sqlite3"
        Path(target).write_text("unrelated")
        try:
            os.symlink(target, self.path)
            with self.assertRaises(RuntimeError):
                self.witness.inspect()
        finally:
            os.unlink(self.path)
            Path(target).unlink()

    def test_backend_error_denies(self):
        self.seed()
        with patch.object(self.witness, "_connect", side_effect=sqlite3.OperationalError("broken")):
            self.assertEqual(self.witness.rotate_to_promoted(
                expected_epoch=1, expected_token=self.a, next_token=self.b,
            ).status, "backend_unavailable")

    def test_cleanup_does_not_touch_other_fixture(self):
        other_id = uuid4().hex
        other_path = witness_path(other_id)
        Path(other_path).write_text("other synthetic")
        try:
            self.seed()
            self.witness.cleanup_owned_fixture()
            self.assertFalse(Path(self.path).exists())
            self.assertEqual(Path(other_path).read_text(), "other synthetic")
        finally:
            Path(other_path).unlink()


if __name__ == "__main__":
    unittest.main()
