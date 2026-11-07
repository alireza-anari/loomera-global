"""Phase 7.15 disposable SQLite witness prototype for Redis partition drills.

An independent FILE on one GitHub runner, not a distributed quorum, lease,
consensus service, cryptographic attestation, or production fencing mechanism.
Every decision denies authentication and automatic OTP/session retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3

_ID = re.compile(r"[0-9a-f]{32}\Z")
_REASONS = frozenset({"network_partition", "dual_master", "replica_ambiguous", "operator_stop"})


@dataclass(frozen=True, slots=True)
class SyntheticWitnessState:
    status: str
    generation: int = 0
    reason: str = "none"
    authenticated: bool = False
    session_created: bool = False
    can_resume: bool = False
    can_reseed: bool = False
    safe_to_retry: bool = False
    external_consensus_proven: bool = False
    production_cutover_authorized: bool = False
    legacy_fallback_authorized: bool = False


def fixture_witness_path(fixture_id: str) -> str:
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("random synthetic witness fixture ID required")
    return "/tmp/loomera-phase715-synthetic-" + fixture_id + ".sqlite3"


class SyntheticLocalPartitionWitness:
    """Single-host, SQLite transaction/CAS observation ONLY, never real leader grant."""

    def __init__(self, *, fixture_id: str, path: str):
        self._expected_path = fixture_witness_path(fixture_id)
        if type(path) is not str or path != self._expected_path:
            raise ValueError("dedicated temporary synthetic witness path required")
        self._path = path
        self._guard()

    def _guard(self):
        if os.environ.get("LOOMERA_PHASE715_WITNESS_TEST") != "1":
            raise RuntimeError("explicit disposable witness test grant required")
        if Path(self._path).is_symlink():
            raise RuntimeError("symlink witness forbidden")

    def _connect(self, *, create: bool):
        self._guard()
        mode = "rwc" if create else "rw"
        return sqlite3.connect(
            "file:" + self._path + "?mode=" + mode,
            uri=True, timeout=3, isolation_level=None,
        )

    def initialize_test_fixture(self) -> SyntheticWitnessState:
        self._guard()
        if os.environ.get("LOOMERA_PHASE715_ALLOW_TEST_SEED") != "1":
            raise RuntimeError("explicit prepare-only witness seed required")
        try:
            with closing(self._connect(create=True)) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS witness("
                    "id INTEGER PRIMARY KEY CHECK(id=1), "
                    "mode TEXT NOT NULL, generation INTEGER NOT NULL, "
                    "reason TEXT NOT NULL)"
                )
                row = db.execute(
                    "SELECT mode, generation, reason FROM witness WHERE id=1"
                ).fetchone()
                if row is not None:
                    db.execute("COMMIT")
                    return self._decode(row, "already_initialized")
                db.execute(
                    "INSERT INTO witness(id, mode, generation, reason) "
                    "VALUES (1, 'observing', 1, 'none')"
                )
                db.execute("COMMIT")
                return SyntheticWitnessState("initialized", 1)
        except sqlite3.Error:
            return SyntheticWitnessState("backend_unavailable")

    @staticmethod
    def _decode(row, status=None):
        if row is None:
            return SyntheticWitnessState("witness_missing")
        if (
            type(row) is not tuple or len(row) != 3
            or row[0] not in ("observing", "halted")
            or type(row[1]) is not int
            or not 1 <= row[1] <= 1_000_000_000
            or row[2] not in {"none", *_REASONS}
            or (row[0] == "observing" and row[2] != "none")
            or (row[0] == "halted" and row[2] == "none")
        ):
            return SyntheticWitnessState("witness_corrupt")
        return SyntheticWitnessState(status or row[0], row[1], row[2])

    def inspect(self) -> SyntheticWitnessState:
        try:
            with closing(self._connect(create=False)) as db:
                row = db.execute(
                    "SELECT mode, generation, reason FROM witness WHERE id=1"
                ).fetchone()
                return self._decode(row)
        except sqlite3.Error:
            return SyntheticWitnessState("witness_unavailable")

    def halt(self, *, expected_generation: int, reason: str) -> SyntheticWitnessState:
        if type(expected_generation) is not int or not 1 <= expected_generation < 1_000_000_000:
            raise ValueError("bounded exact generation required")
        if type(reason) is not str or reason not in _REASONS:
            raise ValueError("fixed synthetic partition incident required")
        try:
            with closing(self._connect(create=False)) as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT mode, generation, reason FROM witness WHERE id=1"
                ).fetchone()
                current = self._decode(row)
                if current.status in ("witness_corrupt", "witness_missing"):
                    db.execute("ROLLBACK")
                    return current
                if current.status == "halted":
                    db.execute("ROLLBACK")
                    return SyntheticWitnessState("already_halted", current.generation, current.reason)
                if current.generation != expected_generation:
                    db.execute("ROLLBACK")
                    return SyntheticWitnessState("stale_generation", current.generation)
                updated = db.execute(
                    "UPDATE witness SET mode='halted', generation=?, reason=? "
                    "WHERE id=1 AND mode='observing' AND generation=?",
                    (expected_generation + 1, reason, expected_generation),
                )
                if updated.rowcount != 1:
                    db.execute("ROLLBACK")
                    return SyntheticWitnessState("backend_unavailable")
                db.execute("COMMIT")
                return SyntheticWitnessState("halted", expected_generation + 1, reason)
        except sqlite3.Error:
            # A commit could have persisted before the client lost its reply.
            return SyntheticWitnessState("backend_unavailable")

    def cleanup_owned_fixture(self) -> None:
        self._guard()
        # Only the precisely matching synthetic local file + SQLite sidecars.
        for path in (self._path, self._path + "-wal", self._path + "-shm"):
            if Path(path).is_symlink():
                raise RuntimeError("refusing to remove a symlink")
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
