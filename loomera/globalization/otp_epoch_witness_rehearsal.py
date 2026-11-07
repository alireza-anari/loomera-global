"""Phase 7.16 SINGLE-HOST SQLite epoch witness (test-only, NOT consensus).

Local SQLite BEGIN IMMEDIATE transactions serialize synthetic leader rotation.
This does NOT atomically fence a write to a separate Redis process. Do not
import into login/session code, use real identities, or deploy this witness.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3

_HEX = re.compile(r"[0-9a-f]{32}\Z")
_OWNERS = frozenset({"original", "promoted"})
_REASONS = frozenset({"leader_ambiguity", "witness_lost", "operator_stop"})


@dataclass(frozen=True, slots=True)
class SyntheticLeaderEpoch:
    status: str
    epoch: int = 0
    owner: str = "none"
    token: str = "none"
    reason: str = "none"
    authenticated: bool = False
    session_created: bool = False
    otp_reissue_allowed: bool = False
    can_resume: bool = False
    can_reseed_after_loss: bool = False
    safe_to_retry: bool = False
    external_consensus_proven: bool = False
    legacy_fallback_authorized: bool = False
    production_cutover_authorized: bool = False


def witness_path(fixture_id: str) -> str:
    if type(fixture_id) is not str or _HEX.fullmatch(fixture_id) is None:
        raise ValueError("random synthetic 32-hex witness id required")
    return "/tmp/loomera-phase716-synthetic-" + fixture_id + ".sqlite3"


def _token(value: str) -> None:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise ValueError("synthetic 32-hex fencing token required")


def _epoch(value: int) -> None:
    if type(value) is not int or not 1 <= value < 1_000_000_000:
        raise ValueError("bounded exact synthetic epoch required")


class SyntheticLocalEpochWitness:
    """Monotone original→promoted→halted state on ONE CI host, no leases."""

    def __init__(self, *, fixture_id: str, path: str):
        desired = witness_path(fixture_id)
        if type(path) is not str or path != desired:
            raise ValueError("exact synthetic witness path required")
        self._path = path
        self._guard()

    def _guard(self) -> None:
        if os.environ.get("LOOMERA_PHASE716_TEST_WITNESS") != "1":
            raise RuntimeError("Phase 7.16 local witness fixture grant required")
        if Path(self._path).is_symlink():
            raise RuntimeError("symlinked witness forbidden")

    def _connect(self, *, create: bool):
        self._guard()
        mode = "rwc" if create else "rw"
        return sqlite3.connect("file:" + self._path + "?mode=" + mode,
                               uri=True, isolation_level=None, timeout=5)

    @staticmethod
    def _decode(row, status: str | None = None) -> SyntheticLeaderEpoch:
        if row is None:
            return SyntheticLeaderEpoch("missing")
        if type(row) is not tuple or len(row) != 5:
            return SyntheticLeaderEpoch("corrupt")
        mode, epoch, owner, token, reason = row
        if (
            type(mode) is not str or mode not in ("active", "halted")
            or type(epoch) is not int or not 1 <= epoch <= 1_000_000_000
            or type(owner) is not str or owner not in _OWNERS
            or type(token) is not str or _HEX.fullmatch(token) is None
            or type(reason) is not str or reason not in {"none", *_REASONS}
            or (mode == "active" and reason != "none")
            or (mode == "halted" and reason == "none")
        ):
            return SyntheticLeaderEpoch("corrupt")
        return SyntheticLeaderEpoch(status or mode, epoch, owner, token, reason)

    def initialize_fixture(self, *, token: str) -> SyntheticLeaderEpoch:
        self._guard()
        if os.environ.get("LOOMERA_PHASE716_ALLOW_SEED") != "1":
            raise RuntimeError("explicit prepare-stage seed grant required")
        _token(token)
        try:
            with closing(self._connect(create=True)) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("CREATE TABLE IF NOT EXISTS leader("
                           "id INTEGER PRIMARY KEY CHECK(id=1), "
                           "mode TEXT NOT NULL, epoch INTEGER NOT NULL, "
                           "owner TEXT NOT NULL, token TEXT NOT NULL, "
                           "reason TEXT NOT NULL)")
                row = db.execute("SELECT mode, epoch, owner, token, reason "
                                 "FROM leader WHERE id=1").fetchone()
                if row is not None:
                    db.execute("COMMIT")
                    return self._decode(row, "already_initialized")
                db.execute("INSERT INTO leader(id, mode, epoch, owner, token, reason) "
                           "VALUES(1, 'active', 1, 'original', ?, 'none')",
                           (token,))
                db.execute("COMMIT")
                return SyntheticLeaderEpoch("initialized", 1, "original", token)
        except sqlite3.Error:
            return SyntheticLeaderEpoch("backend_unavailable")

    def inspect(self) -> SyntheticLeaderEpoch:
        try:
            with closing(self._connect(create=False)) as db:
                row = db.execute("SELECT mode, epoch, owner, token, reason "
                                 "FROM leader WHERE id=1").fetchone()
                return self._decode(row)
        except sqlite3.Error:
            return SyntheticLeaderEpoch("unavailable")

    def rotate_to_promoted(
        self, *, expected_epoch: int, expected_token: str, next_token: str,
    ) -> SyntheticLeaderEpoch:
        _epoch(expected_epoch)
        _token(expected_token)
        _token(next_token)
        if next_token == expected_token:
            raise ValueError("new synthetic leader must have a new token")
        try:
            with closing(self._connect(create=False)) as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT mode, epoch, owner, token, reason "
                                 "FROM leader WHERE id=1").fetchone()
                state = self._decode(row)
                if state.status != "active":
                    db.execute("ROLLBACK")
                    return state
                if state.owner != "original":
                    db.execute("ROLLBACK")
                    return SyntheticLeaderEpoch("already_promoted", state.epoch,
                                                state.owner, state.token)
                if state.epoch != expected_epoch or state.token != expected_token:
                    db.execute("ROLLBACK")
                    return SyntheticLeaderEpoch("stale_token", state.epoch,
                                                state.owner, state.token)
                db.execute("UPDATE leader SET epoch=?, owner='promoted', token=? "
                           "WHERE id=1", (expected_epoch + 1, next_token))
                db.execute("COMMIT")
                return SyntheticLeaderEpoch("rotated", expected_epoch + 1,
                                            "promoted", next_token)
        except sqlite3.Error:
            return SyntheticLeaderEpoch("backend_unavailable")

    def halt(self, *, expected_epoch: int, expected_token: str,
             reason: str) -> SyntheticLeaderEpoch:
        _epoch(expected_epoch)
        _token(expected_token)
        if type(reason) is not str or reason not in _REASONS:
            raise ValueError("fixed synthetic stop reason required")
        try:
            with closing(self._connect(create=False)) as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT mode, epoch, owner, token, reason "
                                 "FROM leader WHERE id=1").fetchone()
                state = self._decode(row)
                if state.status == "halted":
                    db.execute("ROLLBACK")
                    return SyntheticLeaderEpoch("already_halted", state.epoch,
                                                state.owner, state.token, state.reason)
                if state.status != "active":
                    db.execute("ROLLBACK")
                    return state
                if state.epoch != expected_epoch or state.token != expected_token:
                    db.execute("ROLLBACK")
                    return SyntheticLeaderEpoch("stale_token", state.epoch,
                                                state.owner, state.token)
                db.execute("UPDATE leader SET mode='halted', epoch=?, reason=? "
                           "WHERE id=1", (expected_epoch + 1, reason))
                db.execute("COMMIT")
                return SyntheticLeaderEpoch("halted", expected_epoch + 1,
                                            state.owner, state.token, reason)
        except sqlite3.Error:
            return SyntheticLeaderEpoch("backend_unavailable")

    def cleanup_owned_fixture(self) -> None:
        self._guard()
        for path in (self._path, self._path + "-wal", self._path + "-shm"):
            if Path(path).is_symlink():
                raise RuntimeError("refusing to delete symlink")
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
