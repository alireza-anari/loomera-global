"""Phase 7.9 isolated Redis version gate rehearsal; never a live OTP adapter.

Single-key Redis Lua transitions are atomic on one disposable local server.
No OTP, user, mobile, session or authentication state is stored in this gate.
Modes are SIMULATION ONLY. A Redis timeout after execution is ambiguous and
therefore never reported as successful or retried automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

SYNTHETIC_PREFIX = "loomera:phase79:synthetic-only:"
_SYNTHETIC_KEY = re.compile(r"loomera:phase79:synthetic-only:[0-9a-f]{32}\Z")
_ALLOWED_STATUSES = frozenset({
    "seeded", "already_exists", "reconciled", "stale_epoch", "increased_pending",
    "invalid_state", "pending_drain", "drain_window_active", "simulated_v2",
    "would_issue", "halted", "already_halted", "missing", "corrupt",
    "backend_unavailable", "issue_limit",
})

SEED_SCRIPT = r"""
if redis.call('EXISTS', KEYS[1]) ~= 0 then
    return {'already_exists', '0'}
end
redis.call('HSET', KEYS[1], 'mode', 'observe', 'epoch', '1',
    'api_pending', ARGV[1], 'web_pending', ARGV[2],
    'reset_pending', ARGV[3], 'drain_until', ARGV[4],
    'would_issue_count', '0')
redis.call('PEXPIRE', KEYS[1], ARGV[5])
return {'seeded', '1'}
"""

# Reconciliation updates ONLY counts; it does not authorize a cutover.
# Stale writers are rejected by the monotonic epoch and counts cannot rise.
RECONCILE_SCRIPT = r"""
local item = redis.call('HMGET', KEYS[1], 'mode', 'epoch',
    'api_pending', 'web_pending', 'reset_pending')
if not item[1] then return {'missing', '0'} end
local epoch = tonumber(item[2])
local a = tonumber(item[3])
local w = tonumber(item[4])
local r = tonumber(item[5])
if not epoch or not a or not w or not r
    or epoch < 1 or a < 0 or w < 0 or r < 0 then
    return {'corrupt', '0'}
end
if item[1] ~= 'observe' then return {'invalid_state', tostring(epoch)} end
if epoch ~= tonumber(ARGV[1]) then return {'stale_epoch', tostring(epoch)} end
local aa, ww, rr = tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])
if not aa or not ww or not rr or aa > a or ww > w or rr > r then
    return {'increased_pending', tostring(epoch)}
end
redis.call('HSET', KEYS[1], 'api_pending', aa,
    'web_pending', ww, 'reset_pending', rr)
epoch = redis.call('HINCRBY', KEYS[1], 'epoch', 1)
return {'reconciled', tostring(epoch)}
"""

ACTIVATE_SCRIPT = r"""
local item = redis.call('HMGET', KEYS[1], 'mode', 'epoch',
    'api_pending', 'web_pending', 'reset_pending', 'drain_until')
if not item[1] then return {'missing', '0'} end
local epoch = tonumber(item[2])
local a, w, r, until_ts = tonumber(item[3]), tonumber(item[4]),
    tonumber(item[5]), tonumber(item[6])
if not epoch or not a or not w or not r or not until_ts
    or epoch < 1 or a < 0 or w < 0 or r < 0 or until_ts <= 0 then
    return {'corrupt', '0'}
end
if item[1] ~= 'observe' then return {'invalid_state', tostring(epoch)} end
if epoch ~= tonumber(ARGV[1]) then return {'stale_epoch', tostring(epoch)} end
if a ~= 0 or w ~= 0 or r ~= 0 then
    return {'pending_drain', tostring(epoch)}
end
if tonumber(ARGV[2]) < until_ts then
    return {'drain_window_active', tostring(epoch)}
end
redis.call('HSET', KEYS[1], 'mode', 'v2_simulated')
epoch = redis.call('HINCRBY', KEYS[1], 'epoch', 1)
return {'simulated_v2', tostring(epoch)}
"""

# Would-issue is only a counter: it NEVER creates an OTP or allows login.
WOULD_ISSUE_SCRIPT = r"""
local item = redis.call('HMGET', KEYS[1], 'mode', 'epoch',
    'would_issue_count')
if not item[1] then return {'missing', '0'} end
local epoch, issued = tonumber(item[2]), tonumber(item[3])
if not epoch or not issued or epoch < 1 or issued < 0 then
    return {'corrupt', '0'}
end
if item[1] ~= 'v2_simulated' then
    return {'invalid_state', tostring(epoch)}
end
if epoch ~= tonumber(ARGV[1]) then return {'stale_epoch', tostring(epoch)} end
if issued >= 10000 then return {'issue_limit', tostring(epoch)} end
redis.call('HINCRBY', KEYS[1], 'would_issue_count', 1)
return {'would_issue', tostring(epoch)}
"""

# Stop is terminal, not a downgrade to legacy. Old challenges cannot revive.
HALT_SCRIPT = r"""
local item = redis.call('HMGET', KEYS[1], 'mode', 'epoch')
if not item[1] then return {'missing', '0'} end
local epoch = tonumber(item[2])
if not epoch or epoch < 1 then return {'corrupt', '0'} end
if item[1] == 'halted' then return {'already_halted', tostring(epoch)} end
if item[1] ~= 'observe' and item[1] ~= 'v2_simulated' then
    return {'invalid_state', tostring(epoch)}
end
if epoch ~= tonumber(ARGV[1]) then return {'stale_epoch', tostring(epoch)} end
redis.call('HSET', KEYS[1], 'mode', 'halted')
epoch = redis.call('HINCRBY', KEYS[1], 'epoch', 1)
return {'halted', tostring(epoch)}
"""


@dataclass(frozen=True, slots=True)
class SyntheticGateDecision:
    status: str
    epoch: int = 0
    authenticated: bool = False
    production_enabled: bool = False
    legacy_fallback_allowed: bool = False


def _strict_int(value: int, *, lower: int, upper: int) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError("invalid bounded synthetic gate input")


def _guard(client: Any, key: str) -> None:
    if os.environ.get("LOOMERA_PHASE79_TEST_REDIS") != "1":
        raise RuntimeError("Phase 7.9 requires explicitly enabled fixture mode")
    if type(key) is not str or _SYNTHETIC_KEY.fullmatch(key) is None:
        raise ValueError("unapproved synthetic Redis key")
    try:
        conn = client.connection_pool.connection_kwargs
        host, port, db = conn.get("host"), conn.get("port", 6379), conn.get("db")
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("unverifiable Redis client") from exc
    if (
        host not in {"localhost", "127.0.0.1"}
        or type(port) is not int or port != 6379
        or type(db) is not int or db != 15
        or conn.get("password") is not None
        or conn.get("username") is not None
    ):
        raise RuntimeError("only disposable unauthenticated localhost Redis DB15 allowed")


class SyntheticOtpVersionGate:
    """Test-only single-key state machine: observe -> simulated_v2 -> halted."""

    def __init__(self, client: Any, *, key: str):
        _guard(client, key)
        self._client, self._key = client, key

    def _run(self, script: str, *args: int) -> SyntheticGateDecision:
        _guard(self._client, self._key)
        try:
            raw = self._client.eval(script, 1, self._key, *args)
            if not isinstance(raw, (tuple, list)) or len(raw) != 2:
                return SyntheticGateDecision("backend_unavailable")
            status, epoch = raw
            if isinstance(status, bytes):
                status = status.decode("ascii")
            if isinstance(epoch, bytes):
                epoch = epoch.decode("ascii")
            if (
                type(status) is not str or status not in _ALLOWED_STATUSES
                or type(epoch) is not str or not epoch.isascii()
                or not epoch.isdigit() or len(epoch) > 10
                or int(epoch) > 1_000_000_000
            ):
                return SyntheticGateDecision("backend_unavailable")
            return SyntheticGateDecision(status, int(epoch))
        except Exception:
            return SyntheticGateDecision("backend_unavailable")

    def seed(self, *, api_pending: int, web_pending: int, reset_pending: int,
             drain_until_ts: int, now_ts: int) -> SyntheticGateDecision:
        for value in (api_pending, web_pending, reset_pending):
            _strict_int(value, lower=0, upper=10000)
        _strict_int(now_ts, lower=1, upper=4_102_444_800)
        _strict_int(drain_until_ts, lower=now_ts, upper=now_ts + 86400)
        return self._run(
            SEED_SCRIPT, api_pending, web_pending, reset_pending,
            drain_until_ts, 600000,
        )

    def reconcile(self, *, expected_epoch: int, api_pending: int,
                  web_pending: int, reset_pending: int) -> SyntheticGateDecision:
        _strict_int(expected_epoch, lower=1, upper=1_000_000_000)
        for value in (api_pending, web_pending, reset_pending):
            _strict_int(value, lower=0, upper=10000)
        return self._run(
            RECONCILE_SCRIPT, expected_epoch,
            api_pending, web_pending, reset_pending,
        )

    def activate_simulation(self, *, expected_epoch: int,
                            now_ts: int) -> SyntheticGateDecision:
        _strict_int(expected_epoch, lower=1, upper=1_000_000_000)
        _strict_int(now_ts, lower=1, upper=4_102_444_800)
        return self._run(ACTIVATE_SCRIPT, expected_epoch, now_ts)

    def would_issue(self, *, expected_epoch: int) -> SyntheticGateDecision:
        _strict_int(expected_epoch, lower=1, upper=1_000_000_000)
        return self._run(WOULD_ISSUE_SCRIPT, expected_epoch)

    def halt(self, *, expected_epoch: int) -> SyntheticGateDecision:
        _strict_int(expected_epoch, lower=1, upper=1_000_000_000)
        return self._run(HALT_SCRIPT, expected_epoch)

    def synthetic_cleanup(self) -> None:
        _guard(self._client, self._key)
        self._client.delete(self._key)
