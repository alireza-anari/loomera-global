"""Phase 7.12: disposable *two-key* Redis marker divergence rehearsal.

NO durable production marker: both keys live on ONE Redis 7.4 standalone,
expire after ten minutes, and cannot survive a server outage reliably.
No real account, OTP, session, SMS, DB, authentication, or recovery grant.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

PREFIX = "loomera:phase712:synthetic-only:"
_TOKEN = re.compile(r"[0-9a-f]{32}\Z")
_CAUSES = frozenset({
    "none", "client_timeout", "lost_write_reply",
    "reference_diverged", "replica_stale", "session_uncertain",
    "account_deactivated", "operator_stop",
})
_STATUSES = frozenset({
    "initialized", "already_initialized", "partial_lost",
    "observing", "quarantined", "halted", "already_quarantined",
    "already_halted", "reference_lost", "volatile_lost",
    "both_lost", "split_brain", "corrupt", "stale_generation",
    "backend_unavailable",
})

# Both fixture keys are on the same disposable Redis server. The pairing
# detects selective loss and divergence, not disaster-proof persistence.
INITIALIZE_SCRIPT = r"""
local r = redis.call('EXISTS', KEYS[1])
local v = redis.call('EXISTS', KEYS[2])
if r == 1 and v == 1 then return {'already_initialized', 0, 'none'} end
if r ~= v then return {'partial_lost', 0, 'none'} end
redis.call('HSET', KEYS[1], 'mode', 'observing', 'generation', '1',
    'fingerprint', ARGV[1], 'cause', 'none')
redis.call('HSET', KEYS[2], 'mode', 'observing', 'generation', '1',
    'fingerprint', ARGV[1], 'cause', 'none')
redis.call('PEXPIRE', KEYS[1], 600000)
redis.call('PEXPIRE', KEYS[2], 600000)
return {'initialized', 1, 'none'}
"""

FENCE_SCRIPT = r"""
local r = redis.call('EXISTS', KEYS[1])
local v = redis.call('EXISTS', KEYS[2])
if r == 0 and v == 0 then return {'both_lost', 0, 'none'} end
if r == 0 then return {'reference_lost', 0, 'none'} end
if v == 0 then return {'volatile_lost', 0, 'none'} end
local a = redis.call('HMGET', KEYS[1],
    'mode', 'generation', 'fingerprint', 'cause')
local b = redis.call('HMGET', KEYS[2],
    'mode', 'generation', 'fingerprint', 'cause')
local g = tonumber(a[2])
local h = tonumber(b[2])
if not g or not h or g < 1 or g > 1000000000
    or h < 1 or h > 1000000000
    or tostring(g) ~= a[2] or tostring(h) ~= b[2]
    or not a[1] or not b[1] or not a[3] or not b[3]
    or not a[4] or not b[4]
    or redis.call('PTTL', KEYS[1]) <= 0
    or redis.call('PTTL', KEYS[2]) <= 0 then
    return {'corrupt', 0, 'none'}
end
local mode = a[1]
local cause = a[4]
local function cause_ok(x)
    return x == 'none' or x == 'client_timeout'
        or x == 'lost_write_reply' or x == 'reference_diverged'
        or x == 'replica_stale' or x == 'session_uncertain'
        or x == 'account_deactivated' or x == 'operator_stop'
end
if (mode ~= 'observing' and mode ~= 'quarantined' and mode ~= 'halted')
    or not cause_ok(cause)
    or (mode == 'observing' and cause ~= 'none')
    or (mode == 'quarantined' and cause == 'none') then
    return {'corrupt', 0, 'none'}
end
if a[1] ~= b[1] or a[2] ~= b[2]
    or a[3] ~= b[3] or a[4] ~= b[4]
    or a[3] ~= ARGV[1] then
    return {'split_brain', 0, 'none'}
end
if ARGV[2] == 'inspect' then return {mode, g, cause} end
if ARGV[2] ~= 'quarantine' and ARGV[2] ~= 'halt' then
    return {'corrupt', 0, 'none'}
end
if mode == 'halted' then return {'already_halted', g, cause} end
if ARGV[2] == 'quarantine' and mode == 'quarantined' then
    return {'already_quarantined', g, cause}
end
if tonumber(ARGV[3]) ~= g then return {'stale_generation', g, cause} end
if g >= 1000000000 then return {'corrupt', 0, 'none'} end
if ARGV[2] == 'quarantine' then
    if mode ~= 'observing' then return {'corrupt', 0, 'none'} end
    if not cause_ok(ARGV[4]) or ARGV[4] == 'none' then
        return {'corrupt', 0, 'none'}
    end
    mode = 'quarantined'
    cause = ARGV[4]
else
    mode = 'halted'
end
local next = g + 1
redis.call('HSET', KEYS[1], 'mode', mode,
    'generation', tostring(next), 'cause', cause)
redis.call('HSET', KEYS[2], 'mode', mode,
    'generation', tostring(next), 'cause', cause)
-- NO PEXPIRE here; mutation must never extend a fixture lifetime.
return {mode, next, cause}
"""


@dataclass(frozen=True, slots=True)
class SyntheticMarkerObservation:
    status: str
    generation: int = 0
    cause: str = "none"
    authenticated: bool = False
    session_created: bool = False
    can_resume: bool = False
    can_seed_on_restart: bool = False
    safe_to_retry: bool = False
    legacy_fallback_authorized: bool = False
    production_recovery_authorized: bool = False


def _guard(client: Any, fixture_id: str) -> None:
    if os.environ.get("LOOMERA_PHASE712_TEST_REDIS") != "1":
        raise RuntimeError("explicit disposable Phase 7.12 fixture grant required")
    if type(fixture_id) is not str or _TOKEN.fullmatch(fixture_id) is None:
        raise ValueError("random lowercase hexadecimal fixture identifier required")
    try:
        opts = client.connection_pool.connection_kwargs
        host, port, db = opts.get("host"), opts.get("port", 6379), opts.get("db")
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis connection") from exc
    if (
        host not in {"localhost", "127.0.0.1"}
        or type(port) is not int or port != 6379
        or type(db) is not int or db != 15
        or opts.get("username") is not None
        or opts.get("password") is not None
    ):
        raise RuntimeError("only disposable unauthenticated localhost Redis DB15 allowed")


def _generation(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 1_000_000_000:
        raise ValueError("bounded fixture generation required")


class SyntheticRestartMarkerFence:
    """Never seeds on attach; test initialization is an explicit separate call."""

    def __init__(self, client: Any, *, fixture_id: str):
        _guard(client, fixture_id)
        self._client = client
        self._id = fixture_id
        self._keys = (
            PREFIX + fixture_id + ":reference",
            PREFIX + fixture_id + ":volatile",
        )

    def _execute(self, script: str, *args: Any) -> SyntheticMarkerObservation:
        _guard(self._client, self._id)
        try:
            reply = self._client.eval(script, 2, *self._keys, *args)
            if not isinstance(reply, (list, tuple)) or len(reply) != 3:
                return SyntheticMarkerObservation("backend_unavailable")
            status, generation, cause = reply
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
            # A successful Redis write may have lost its response. Never infer
            # a grant, automatically retry, or silently recreate missing keys.
            return SyntheticMarkerObservation("backend_unavailable")

    def initialize_disposable_fixture_for_test(self) -> SyntheticMarkerObservation:
        """CI fixture creation, NEVER a cold-start or incident recovery path."""
        return self._execute(INITIALIZE_SCRIPT, self._id)

    def inspect_after_reconnect(self) -> SyntheticMarkerObservation:
        """Pure observation: does not seed, reset TTL or repair either key."""
        return self._execute(FENCE_SCRIPT, self._id, "inspect", 0, "none")

    def quarantine(self, *, expected_generation: int,
                   cause: str) -> SyntheticMarkerObservation:
        _generation(expected_generation)
        if type(cause) is not str or cause not in _CAUSES or cause == "none":
            raise ValueError("fixed synthetic quarantine cause required")
        return self._execute(
            FENCE_SCRIPT, self._id, "quarantine", expected_generation, cause,
        )

    def halt(self, *, expected_generation: int) -> SyntheticMarkerObservation:
        _generation(expected_generation)
        return self._execute(
            FENCE_SCRIPT, self._id, "halt", expected_generation, "none",
        )

    def cleanup_owned_fixture(self) -> None:
        _guard(self._client, self._id)
        self._client.delete(*self._keys)
