"""Phase 7.13: test-only Redis AOF process-restart marker fence.

Uses Phase 7.12's already exercised Lua two-key CAS scripts, but is STRICTLY
scoped to a separate Redis 7.4 Docker container on 127.0.0.1:6392/15 with its
own short-lived Docker volume. Both markers share one failure domain and TTL.
This is NOT production durability, failover, OTP verification, or a login.
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

PREFIX = "loomera:phase713:synthetic-aof-only:"
_TOKEN = re.compile(r"[0-9a-f]{32}\Z")


def _guard(client: Any, fixture_id: str) -> None:
    if os.environ.get("LOOMERA_PHASE713_TEST_REDIS") != "1":
        raise RuntimeError("Phase 7.13 disposable AOF Redis grant required")
    if type(fixture_id) is not str or _TOKEN.fullmatch(fixture_id) is None:
        raise ValueError("random synthetic lowercase fixture ID required")
    try:
        opts = client.connection_pool.connection_kwargs
        host, port, db = opts.get("host"), opts.get("port"), opts.get("db")
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis fixture connection") from exc
    if (
        host != "127.0.0.1"
        or type(port) is not int or port != 6392
        or type(db) is not int or db != 15
        or opts.get("username") is not None
        or opts.get("password") is not None
        or opts.get("ssl") not in (None, False)
        or opts.get("unix_socket_path") is not None
    ):
        raise RuntimeError("only isolated unauthenticated 127.0.0.1:6392/15 allowed")


def _generation(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 1_000_000_000:
        raise ValueError("invalid synthetic generation")


class SyntheticAofProcessRestartFence:
    """No implicit create, repair, resume or authorization on process restart."""

    def __init__(self, client: Any, *, fixture_id: str):
        _guard(client, fixture_id)
        self._client = client
        self._id = fixture_id
        self._keys = (
            PREFIX + fixture_id + ":reference",
            PREFIX + fixture_id + ":volatile",
        )

    def _eval(self, script: str, *args: Any) -> SyntheticMarkerObservation:
        _guard(self._client, self._id)
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
                type(status) is not str or status not in _STATUSES
                or type(generation) is not int or not 0 <= generation <= 1_000_000_000
                or type(cause) is not str or cause not in _CAUSES
            ):
                return SyntheticMarkerObservation("backend_unavailable")
            return SyntheticMarkerObservation(status, generation, cause)
        except Exception:
            # AOF might already contain a write whose response was lost.
            # Read-only observation remains diagnostic, never safe to replay.
            return SyntheticMarkerObservation("backend_unavailable")

    def initialize_disposable_fixture_for_test(self) -> SyntheticMarkerObservation:
        if os.environ.get("LOOMERA_PHASE713_ALLOW_TEST_SEED") != "1":
            raise RuntimeError("separate explicit test-setup grant required")
        return self._eval(INITIALIZE_SCRIPT, self._id)

    def inspect_after_process_restart(self) -> SyntheticMarkerObservation:
        return self._eval(FENCE_SCRIPT, self._id, "inspect", 0, "none")

    def quarantine(self, *, expected_generation: int,
                   cause: str) -> SyntheticMarkerObservation:
        _generation(expected_generation)
        if type(cause) is not str or cause not in _CAUSES or cause == "none":
            raise ValueError("fixed test-only quarantine cause required")
        return self._eval(FENCE_SCRIPT, self._id, "quarantine", expected_generation, cause)

    def halt(self, *, expected_generation: int) -> SyntheticMarkerObservation:
        _generation(expected_generation)
        return self._eval(FENCE_SCRIPT, self._id, "halt", expected_generation, "none")

    def cleanup_owned_fixture(self) -> None:
        _guard(self._client, self._id)
        self._client.delete(*self._keys)
