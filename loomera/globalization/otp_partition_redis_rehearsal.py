"""Phase 7.15 disposable Redis partition and local witness denial adapter.

Only 127.0.0.1:{6395,6396}/15 + a separate synthetic SQLite file.
The witness check and Redis EVAL are NOT a distributed atomic transaction:
a concurrent fence can race the check; raw Redis writes bypass both checks.
This module MUST NEVER be imported into live authentication or sessions.
"""
from __future__ import annotations

import os
import re
from typing import Any

from loomera.globalization.otp_partition_witness_rehearsal import (
    SyntheticLocalPartitionWitness,
)
from loomera.globalization.otp_restart_marker_rehearsal import (
    FENCE_SCRIPT, INITIALIZE_SCRIPT,
    SyntheticMarkerObservation, _CAUSES, _STATUSES,
)

PREFIX = "loomera:phase715:synthetic-partition-only:"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_PORTS = {"original": 6395, "promoted": 6396}
_STATUS = _STATUSES | frozenset({
    "witness_halted", "witness_untrusted", "not_active_leader",
    "leader_untrusted", "not_master", "fixture_write_not_granted",
})


def _guard(client: Any, fixture_id: str, node: str) -> None:
    if os.environ.get("LOOMERA_PHASE715_TEST_REDIS") != "1":
        raise RuntimeError("explicit Phase 7.15 isolated Redis test grant required")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("random lowercase fixture id required")
    if type(node) is not str or node not in _PORTS:
        raise ValueError("fixed synthetic node required")
    try:
        opts = client.connection_pool.connection_kwargs
        host, port, db = opts.get("host"), opts.get("port"), opts.get("db")
    except (TypeError, AttributeError) as exc:
        raise RuntimeError("unverifiable synthetic Redis client") from exc
    if (
        host != "127.0.0.1" or type(port) is not int or port != _PORTS[node]
        or type(db) is not int or db != 15
        or opts.get("username") is not None or opts.get("password") is not None
        or opts.get("ssl") not in (None, False)
        or opts.get("unix_socket_path") is not None
    ):
        raise RuntimeError("only isolated loopback Redis 6395/6396 DB15")


class SyntheticPartitionMarkerFence:
    """Diagnostic-only; a local SQLite witness is no substitute for consensus."""

    def __init__(self, client: Any, *, fixture_id: str, node: str,
                 witness: SyntheticLocalPartitionWitness):
        _guard(client, fixture_id, node)
        if type(witness) is not SyntheticLocalPartitionWitness:
            raise TypeError("explicit synthetic witness required")
        self._client = client
        self._id = fixture_id
        self._node = node
        self._witness = witness
        self._keys = (
            PREFIX + fixture_id + ":reference",
            PREFIX + fixture_id + ":volatile",
        )

    def _deny_reason(self) -> str | None:
        _guard(self._client, self._id, self._node)
        witness = self._witness.inspect()
        if witness.status == "halted":
            return "witness_halted"
        if witness.status != "observing":
            return "witness_untrusted"
        leader = os.environ.get("LOOMERA_PHASE715_ACTIVE_LEADER")
        if leader not in _PORTS:
            return "leader_untrusted"
        if self._node != leader:
            return "not_active_leader"
        try:
            role = self._client.info(section="replication")
            if type(role) is not dict or role.get("role") != "master":
                return "not_master"
        except Exception:
            return "backend_unavailable"
        return None

    def _eval(self, script: str, *args: Any) -> SyntheticMarkerObservation:
        reason = self._deny_reason()
        if reason:
            return SyntheticMarkerObservation(reason)
        try:
            response = self._client.eval(script, 2, *self._keys, *args)
            if type(response) not in (list, tuple) or len(response) != 3:
                return SyntheticMarkerObservation("backend_unavailable")
            status, generation, cause = response
            if type(status) is bytes:
                status = status.decode("ascii")
            if type(cause) is bytes:
                cause = cause.decode("ascii")
            if (
                type(status) is not str or status not in _STATUS
                or type(generation) is not int or not 0 <= generation <= 1_000_000_000
                or type(cause) is not str or cause not in _CAUSES
            ):
                return SyntheticMarkerObservation("backend_unavailable")
            return SyntheticMarkerObservation(status, generation, cause)
        except Exception:
            return SyntheticMarkerObservation("backend_unavailable")

    def initialize_disposable_fixture_for_test(self) -> SyntheticMarkerObservation:
        if os.environ.get("LOOMERA_PHASE715_ALLOW_TEST_SEED") != "1":
            raise RuntimeError("initial test fixture creation only")
        return self._eval(INITIALIZE_SCRIPT, self._id)

    def inspect(self) -> SyntheticMarkerObservation:
        return self._eval(FENCE_SCRIPT, self._id, "inspect", 0, "none")

    def quarantine(self, *, expected_generation: int,
                   cause: str) -> SyntheticMarkerObservation:
        if type(expected_generation) is not int or not 1 <= expected_generation < 1_000_000_000:
            raise ValueError("bounded generation required")
        if type(cause) is not str or cause not in _CAUSES or cause == "none":
            raise ValueError("synthetic cause required")
        reason = self._deny_reason()
        if reason:
            return SyntheticMarkerObservation(reason)
        if os.environ.get("LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION") != "1":
            return SyntheticMarkerObservation("fixture_write_not_granted")
        return self._eval(FENCE_SCRIPT, self._id, "quarantine", expected_generation, cause)

    def halt(self, *, expected_generation: int) -> SyntheticMarkerObservation:
        if type(expected_generation) is not int or not 1 <= expected_generation < 1_000_000_000:
            raise ValueError("bounded generation required")
        reason = self._deny_reason()
        if reason:
            return SyntheticMarkerObservation(reason)
        if os.environ.get("LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION") != "1":
            return SyntheticMarkerObservation("fixture_write_not_granted")
        return self._eval(FENCE_SCRIPT, self._id, "halt", expected_generation, "none")

    def cleanup_owned_fixture(self) -> None:
        _guard(self._client, self._id, self._node)
        if os.environ.get("LOOMERA_PHASE715_ALLOW_TEST_SEED") != "1":
            raise RuntimeError("fixture cleanup only during setup tests")
        self._client.delete(*self._keys)
