# Phase 7.28 — restricted, cooperating PostGIS → Redis synthetic write path

**CI-only security rehearsal. Not production code, a deployable gateway, or a release approval.**

Baseline main: 6dd5b13cbe4b9db41b72430091431a98f46b1861.
Phase 7.27 postmerge CI 42519141297 had four successful jobs.

## Why this phase

Phase 7.27 proved with real PostgreSQL and real Redis that a voluntarily consulted PostgreSQL lease cannot stop a permitted raw Redis socket. It also physically proved that Redis 7.4 ACL SETUSER off rejects fresh credentials but does **not** immediately revoke an already authenticated TCP connection. This phase tests the narrowest useful improvement without making a false global claim: an isolated Redis ACL allowlist plus a single **cooperating** Python/SQL gateway.

The new UNWIRED module otp_restricted_writer_gateway_rehearsal uses PostgreSQL lease and global operation ledger from Phase 7.26. A caller has to supply a typed old/promoted epoch, a synthetic 32-hex operation ID and a 64-hex fingerprint. A SQL SELECT FOR UPDATE lease check and UNIQUE operation insert occur inside an outer PostgreSQL transaction which remains open across a Redis SET NX. That stops *cooperating* SQL promotion from overtaking an inflight gateway write. Duplicate or conflicting SQL operations do not mutate Redis; stale, missing and terminal SQL state also deny the gateway. This is not a distributed transaction.

## Real, isolated security perimeter

The existing GitHub PostGIS service provisions a Django test_ database. A dedicated short-lived Redis 7.4-alpine AOF container uses only 127.0.0.1:6428, DB15, a run-specific random 32-hex fixture prefix and distinct Docker volume. The shell refuses missing CI approvals, occupied ports or pre-existing named resources. An EXIT trap cleans up only the exact owned container and volume. No production Redis, accounts, phones, codes, sessions, SMS, migrations or application settings are touched.

The Redis default user is disabled. In the ordinary fixture state, the old legacy account has only read commands and cannot SET or EVAL; a single gateway account has only prefix-scoped read/write permissions. There is intentionally also a privileged fixture-only administrator with ACL/CLIENT privileges: it **can write raw Redis without PostgreSQL** and therefore disproves complete enforcement. A separate adversarial test temporarily enables an additional prefix-scoped write account, confirms ACL off leaves its *already connected* socket able to EVAL, then requires CLIENT KILL USER to end that one-node stale route. Fresh credentials fail after ACL off. This temporary test grant is never an operational production configuration.

## Failure and ambiguity matrix

- PostgreSQL lease/operation locks serialize cooperating operations; separately connected PostgreSQL sessions race promotion with an inflight real Redis SET and observe the expected order.
- A read-only legacy socket cannot SET/EVAL; gateway calls with wrong Redis host, port, DB, user, invalid ID or revoked CI grant reject before I/O.
- ACL off followed by CLIENT KILL USER can stop the **specific local** gateway connection. It does not provide multihost credential revocation, prevent privileged users, or guarantee full control of privileged network paths.
- Redis SET NX prevents overwriting a marker whose SQL claim was rolled back or whose acknowledgement was lost; such an ambiguous retry raises an error and leaves both stores unchanged on subsequent attempt. The marker **remains orphaned**. This is deliberate fail-closed behavior, not reconciliation.
- An outer PostgreSQL rollback after Redis SET (or a test-injected lost reply after a physical write) leaves a Redis marker but no SQL operation row. Conversely a successful SQL claim followed by deletion of the Redis marker is observed but is not automatically repaired. Exactly-once external delivery cannot be inferred from these tests.
- Missing PostgreSQL schema or lease denies gateway writes without an automatic Redis-only fallback. A privileged fixture admin can still raw EVAL even while PostgreSQL is terminal halted.

All tests use only fixture strings and prefix-scoped keys; no FLUSH, SCAN, migration or actual SMS operation. The phase retains and re-runs all prior Fast, Redis, Chromium and PostGIS work.

## Production decision

**BLOCKED.** A real mandatory service boundary must independently control every ingress (legacy, privileged, stale TCP, host bypass, other Redis servers), bind operation provenance to trusted identities, define bounded failover and recovery, implement a durable transactional outbox and safe SMS dispatch/receipt policy, handle account and session atomicity, and undergo privacy, security, owner and operations signoff. This exercise does not meet those requirements. Do not wire the module, ACLs, port or test infrastructure into live auth.
