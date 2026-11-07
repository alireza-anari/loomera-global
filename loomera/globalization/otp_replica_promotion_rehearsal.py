"""Phase 7.14: disposable two-container Redis promotion marker model.

This harness is NOT a production leader election or durable fencing design:
LOOMERA_PHASE714_ACTIVE_LEADER is an untrusted *test runner* configuration,
not a consensus-backed, independent, authenticated leader lease. Raw Redis
commands can bypass the harness before old-primary reconfiguration.
"""
from __future__ import annotations

import os
import re
from typing import Any

from loomera.globalization.otp_restart_marker_rehearsal import (
    FENCE_SCRIPT,
    INITIALIZE_SCRIPT,
    SyntheticMarkerObservation,
    _CAUSES,
    _STATUSES,
)

PREFIX = "loomera:phase714:synthetic-replica-only:"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_PORTS = {"original": 6393, "promoted": 6394}


def _fixture_guard(client: Any, fixture_id: str, node: str) -> None:
    if os.environ.get("LOOMERA_PHASE714_TEST_REDIS") != "1":
        raise RuntimeError("explicit Phase 7.14 disposable test grant required")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("random lowercase test fixture id required")
    if type(node) is not str or node not in _PORTS:
        raise ValueError("fixed isolated Redis node required")
    try:
        opts = client.connection_pool.connection_kwargs
        host, port, db = opts.get("host"), opts.get("port"), opts.get("db")
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis test client") from exc
    if (
        host != "127.0.0.1" or type(port) is not int or port != _PORTS[node]
        or type(db) is not int or db != 15
        or opts.get("username") is not None or opts.get("password") is not None
        or opts.get("ssl") not in (None, False)
        or opts.get("unix_socket_path") is not None
    ):
        raise RuntimeError("only synthetic localhost 6393/6394 DB15 allowed")


def _generation(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 1_000_000_000:
        raise ValueError("synthetic generation outside allowed bounds")


class SyntheticPromotedMarkerFence:
    """Test-only writer adapter which refuses a non-selected/replica endpoint."""

    def __init__(self, client: Any, *, fixture_id: str, node: str):
        _fixture_guard(client, fixture_id, node)
        self._client, self._id, self._node = client, fixture_id, node
        self._keys = (
            PREFIX + fixture_id + ":reference",
            PREFIX + fixture_id + ":volatile",
        )

    def _leader_status(self) -> str | None:
        _fixture_guard(self._client, self._id, self._node)
        # Unset/invalid test runner leader is *never* inferred from Redis role.
        leader = os.environ.get("LOOMERA_PHASE714_ACTIVE_LEADER")
        if leader not in _PORTS:
            return "leader_untrusted"
        if leader != self._node:
            return "not_active_leader"
        try:
            info = self._client.info(section="replication")
            if type(info) is not dict or info.get("role") != "master":
                return "not_master"
        except Exception:
            return "backend_unavailable"
        return None

    def _eval(self, script: str, *args: Any) -> SyntheticMarkerObservation:
        status = self._leader_status()
        if status is not None:
            return SyntheticMarkerObservation(status)
        try:
            result = self._client.eval(script, 2, *self._keys, *args)
            if type(result) not in (list, tuple) or len(result) != 3:
                return SyntheticMarkerObservation("backend_unavailable")
            status, generation, cause = result
            if type(status) is bytes:
                status = status.decode("ascii")
            if type(cause) is bytes:
                cause = cause.decode("ascii")
            if (
                type(status) is not str or status not in _STATUSES
                or type(generation) is not int or not 0 <= generation <= 1_000_000_000
                or type(cause) is not str or cause not in _CAUSES
            ):
                return SyntheticMarkerObservation("backend_unavailable")
            return SyntheticMarkerObservation(status, generation, cause)
        except Exception:
            # A successful promotion/write might have lost its reply.
            return SyntheticMarkerObservation("backend_unavailable")

    def initialize_fixture_for_test(self) -> SyntheticMarkerObservation:
        if os.environ.get("LOOMERA_PHASE714_ALLOW_TEST_SEED") != "1":
            raise RuntimeError("explicit seed-only phase required")
        return self._eval(INITIALIZE_SCRIPT, self._id)

    def inspect_on_selected_primary(self) -> SyntheticMarkerObservation:
        return self._eval(FENCE_SCRIPT, self._id, "inspect", 0, "none")

    def quarantine(self, *, expected_generation: int,
                   cause: str) -> SyntheticMarkerObservation:
        _generation(expected_generation)
        if type(cause) is not str or cause not in _CAUSES or cause == "none":
            raise ValueError("fixed synthetic quarantine cause required")
        return self._eval(FENCE_SCRIPT, self._id, "quarantine", expected_generation, cause)

    def halt(self, *, expected_generation: int) -> SyntheticMarkerObservation:
        _generation(expected_generation)
        return self._eval(FENCE_SCRIPT, self._id, "halt", expected_generation, "none")

    def cleanup_owned_fixture(self) -> None:
        _fixture_guard(self._client, self._id, self._node)
        # Cleanup runs only in the initial/pre-promotion fixture-test stage.
        # A live session or a replica can never be accessed through this class.
        self._client.delete(*self._keys)
