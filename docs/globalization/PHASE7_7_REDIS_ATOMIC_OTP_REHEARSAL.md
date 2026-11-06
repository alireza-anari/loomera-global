# Phase 7.7 — Atomic Redis OTP consume: independent-worker, test-only evidence

**Mode: isolated Redis Lua rehearsal with synthetic accounts, no live authentication integration.**
Starting `main` is `7be5cb8b04ea88d003e93bff2aa5db8411a99924`,
with independently successful Phase 7.6 post-merge run `42248490290`.
This milestone does **not** change live OTP login, signup, password reset,
Django cache keying, sessions, resend limits, SMS delivery, models,
migration files or real user data. It is not a Production deployment.

## Security finding in the legacy path

The current API `verify_api_otp_code` in
`apps/api/v1/auth_otp.py` uses three separate operations:
`cache.get`, hash comparison, then `cache.delete`. Two independent
workers can potentially read the *same* challenge before either
delete executes. A `cache.delete` returning `False` is also not the
same as independently verified consumption. These behaviors were
not established as safe by the sequential tests in Phase 7.6.

There is **no production switch** in Phase 7.7. Existing behavior is
left untouched until compatibility and a security review authorize a
separate implementation.

## New experimental atomic protocol

`loomera/globalization/otp_atomic_redis_rehearsal.py` defines a
**test-only** Redis HASH challenge with fields:
`purpose, legacy_mobile, code_digest, expires_at, attempts,
max_attempts`. It is **not** the serialized format used by
`django-redis` today, and it is **not** a drop-in replacement for
live verification. The demo digest uses a deliberately non-production
fixed synthetic HMAC key; real production secrets must never use it.

Two Redis Lua scripts are tested:

- **Seed:** an atomic `EXISTS / HSET / PEXPIRE` procedure refuses
  to overwrite any existing challenge. Duplicate requests cannot
  restart the attempt budget or extend the TTL.
- **Consume:** one `EVAL` reads the purpose, literal
  `09xxxxxxxxx` legacy mobile, digest, expiration and attempt
  budget; validates binding, increments an incorrect attempt
  atomically without extending TTL, and deletes expired/exhausted
  challenges. A correct digest yields `consumed` **only** when
  `DEL` returns exactly `1` within that same Redis script.

These commands execute atomically on one Redis server. They
demonstrate a single consumption winner for that **synthetic HASH**.
Redis Lua string equality here has **not been independently proven
constant-time**; a live design must address timing, code secrecy,
algorithm choice, transport security, Redis clustering and privacy.

Every Python result is a fixed reason/status and a bounded attempt
count: no mobile, code, hash, account ID, session ID or Redis key is
returned, and even `consumed` sets `authenticated=False`.
Unexpected script results, connection loss, timeout and an
ambiguous response **after Redis has committed a deletion** all
produce `backend_unavailable` and cannot establish login.

## Isolation and reproducibility

CI adds a **fourth** independent job with an ephemeral local
`redis:7.4-alpine` service and pinned `redis==5.2.1` Python client.
It runs:

```sh
LOOMERA_PHASE77_TEST_REDIS=1 \
  python -m unittest discover -s tests -p 'phase7_redis_atomic_test.py' -v
```

The test module refuses to run without that explicit variable.
The experimental adapter additionally verifies the client connects
to **localhost:6379, logical Redis DB 15** and that the operation
key is within `loomera:phase77:synthetic-only:` plus a random
32-character hexadecimal identifier. It does not use real phone
numbers, flush any Redis database, or contact external services.
Tests delete only their generated fixture key during teardown.

The tests cover:

- a single valid consume followed by missing/replay and wrong-code
  attempt budgets, expiry, wrong mobile/purpose, invalid records;
- duplicate seed with stable TTL/attempt budget and binding of
  synthetic legacy mobile to a single purpose;
- two independent Redis clients in threads: exactly one winner;
- **two separately spawned Python worker processes** on distinct
  clients: exactly one winner for the same challenge;
- simultaneous invalid attempts with no lost increment, followed
  by exhaustion and denial;
- response lost after the Redis script consumed the code, explicit
  unconfirmed-delete and malformed reply simulation, and network
  failures: no accidental success;
- refusal to connect to Redis DB 14, a remote host, a wrong key
  prefix or without the explicit test-only environment grant.

The existing Fast checks, Chromium smoke and PostGIS migration
rehearsals stay required. A small Fast-check contract suite verifies
that the test adapter has **not** been imported into live web/API
authentication paths and that the release flags remain blocked.

## What passing these tests does NOT prove

- It does **not** prove atomicity of the currently deployed
  `django-redis` pickled-record OTP flow; it is a different wire
  format and key. It does **not** fix the legacy GET/compare/DELETE
  race or the false-return/delete fallback in Production.
- It does **not** prove safety during Redis cluster failover,
  read-replica lag, scripts that cross Redis Cluster hash slots,
  network partitions, clock skew, TLS failures, session creation
  that races against account deactivation, concurrent signup,
  or availability under load.
- It does **not** prove correctness of the historical web OTP
  plaintext session or password-reset grants, purpose-specific
  cooldowns, API per-mobile/IP hour limits, carrier allocation,
  mobile clients, or deletion/anonymization policy.
- It has no real account IDs, phone exports or login side
  effects. **No user/account migration and no Production cutover
  is authorized by an all-green CI run.**

## Required follow-up before real security changes

1. Review a versioned, account-owner-approved transition of the
   *actual* API challenge storage format, preserving in-flight
   challenges and historical keys until their TTLs have drained.
2. Design one atomic backend primitive covering the **real**
   code comparison, attempts, expiration and consume plus
   required cooldown/rate namespaces. Explicitly decide how
   cache delete returning `False`, timeout-after-commit, Redis
   unavailable, retry and a verified code for an inactive
   account are handled. All failures must be safe.
3. Verify server-side hash comparison timing and transport,
   OTP privacy, purpose separation, secret rotation, cluster
   compatibility and cross-process authentication/session
   creation on an approved environment.
4. Conduct authorized historical OTP, password-reset and user
   snapshot reconciliation, with data-owner and security signoff
   and a reversible rollout/rollback runbook.
5. Obtain the remaining mobile-client and Phase 3 manual
   accessibility acceptance before real deployment.

**Status: Redis synthetic atomic-consume rehearsal only.**
The actual account, web OTP, API OTP and production release gates
remain **BLOCKED**.
