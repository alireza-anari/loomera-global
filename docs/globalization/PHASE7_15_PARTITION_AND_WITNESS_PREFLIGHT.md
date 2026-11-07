# Phase 7.15 — Real Redis network partition, two writable masters and single-host witness halt

**Synthetic-only security preflight; NO Production change, account/user/OTP code/phone, real Django session, session write, migration or deployment.**

Baseline main SHA 76b1f66af61f318add4fb940beb9a072de757f63. Its independently verified Phase 7.14 post-merge CI run 42391560806 passed Fast, Redis, Chromium and PostGIS.

## Why Phase 7.15 is needed

Phase 7.14 demonstrated two disposable Redis 7.4 containers with manual replica promotion, but **the original primary was stopped** during promotion. When it restarted, it advertised master until explicit demotion. That is evidence of a stale-writer, split-brain problem—not proof of safe production fencing. Phase 7.15 tests an even more adversarial case: **the original primary keeps running and accepting writes throughout a real replication-network partition, while the replica is manually promoted to another writable master**.

A local SQLite file outside Redis provides an *experimental terminal-stop witness*. It is NOT a production leader lease: it runs on the **same CI host** as Redis, is not signed or backed by multiple independent voting machines, and its read followed by a separate Redis EVAL is a time-of-check/time-of-use (TOCTOU) race. **Raw Redis writes can bypass it.** This phase deliberately proves the problem rather than claiming it is solved.

## Layer A — fully offline partition evidence (no I/O)

Module: loomera/globalization/otp_partition_evidence_policy.py.

Fixed typed enums for Redis link, original and promoted node roles, witness health/mode, both marker copies, acknowledgment of writes and expected/observed generations; exact bool flags for post-partition inventory, real multi-host quorum, old writer consensus fencing, real data absence, owner signoff.

A dual-master view, missing/ambiguous witness, halted witness, stale/future epoch, divergent marker, uncertain write ACK, missing quorum or ownership all produce explicit denial reasons. **All-green caller-supplied claims still return manual_review_only.** Every result has login_allowed=False, otp_consume_allowed=False, otp_reissue_allowed=False, write_on_either_master_allowed=False, marker_reseed_allowed=False, session_retry_allowed=False, legacy_fallback_allowed=False, production_cutover_allowed=False, old_primary_fenced_proven=False and real_quorum_proven=False.

These fields are synthetic caller claims, not independently attested facts from real accounts, sessions, a consensus service or multi-datacenter network.

## Layer B — disposable local SQLite witness

Module: loomera/globalization/otp_partition_witness_rehearsal.py.

Requires LOOMERA_PHASE715_WITNESS_TEST=1, a random 32-digit lowercase hexadecimal ID, a precisely matched path /tmp/loomera-phase715-synthetic-<ID>.sqlite3, and rejects symlinks. Initial creation requires an **additional** LOOMERA_PHASE715_ALLOW_TEST_SEED=1, present only in the fixture setup step. Read/attach never creates missing files; missing/corrupt/unavailable returns a denial. A single-host SQLite BEGIN IMMEDIATE transaction checks and increments a monotone generation from observing/1 to **terminal halted/2**, with immutable reason. Concurrent halts cannot both win. After the stop it never reopens; even process reconnection or re-synchronization of Redis does not change it.

Why this is **NOT a durable production leader authority**: one local disk on the same GitHub runner as two Docker Redis instances, no cross-machine quorum, no lease expiry semantics, no independently authenticated clients, no network fencing, and no atomic transaction spanning SQLite and Redis. Successful SQLite COMMIT does not make an earlier raw Redis write impossible. The witness provides synthetic *audit evidence of a stop*, nothing more.

## Layer C — Redis fixture adapter (not live auth)

Module: loomera/globalization/otp_partition_redis_rehearsal.py.

Reuses the synthetic two-key Lua marker scripts from Phase 7.12 but uses an entirely separate namespace loomera:phase715:synthetic-partition-only: and port guard for unauthenticated 127.0.0.1:6395/15 or 127.0.0.1:6396/15 only. Explicit LOOMERA_PHASE715_TEST_REDIS=1 and matching fixed node label required. Adapter reads the witness before an operation, demands test-selected active leader plus Redis master role, and disallows mutation without LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION=1 (only during prepare). Absent/corrupt/halted witness denies access. Response flags are always no authentication/session/retry/Production or legacy fallback.

**Critical:** Checking SQLite before EVAL is not an atomic cross-store fence; even an apparently valid SQLite witness could change after the check. A direct Redis client ignores these checks. Production must use authenticated, independently committed leader epochs with write-side enforcement that is proven across leader transitions; this adapter is not that design.

## CI drill: actual isolated replication network outage

Script: tests/phase7_redis_network_partition_ci.sh. GitHub Actions only, explicitly granted, one dedicated run.

- Starts two Redis 7.4-alpine containers on localhost-only published ports 6395 and 6396, each with its own disposable AOF volume, appendonly yes and appendfsync always. The original CI Redis service on port 6379 remains untouched.
- Creates **two distinct disposable Docker bridges**: a client-access bridge that stays connected and a dedicated *replication-only* bridge with unique DNS aliases. Only the latter is disconnected. Docker container and Volume names are scoped to run ID/attempt.
- Establishes master→replica replication across the replication bridge, verifies Redis master/slave roles and link-up, writes three synthetic markers (observing, quarantined, halted), obtains Redis WAIT 1 ACK and compares exact hash snapshots and positive TTL on both nodes.
- Removes the **replica's replication-only network attachment** while leaving both processes and their client access alive. Confirms its replication link goes down. Explicitly promotes the replica with REPLICAOF NO ONE. Both **actual** Redis nodes now say master and accept raw writes; the test writes two different artificial strings under the same synthetic key, then directly advances a synthetic marker on the promoted branch to show divergent generation. This is a positive demonstration of the **raw Redis split-brain vulnerability**.
- The fixture's single-host SQLite witness detects this lab condition from the outside and commits halted generation 2. Both adapter endpoints then deny further test writes and inspection, even though raw Redis writes remain possible. A denied adapter request is NOT proof of raw-write fencing.
- Reattaches the replication bridge and **explicitly** demotes the old master to follow the promoted node as read-only replica. Asserts the old node refuses a direct HSET, that exact synthetic marker data converges, and that the original forked synthetic key now contains the promoted master's value. The SQLite witness remains **terminal halted**; the adapter refuses to automatically resume.
- EXIT trap deletes only those named two containers, two volumes, two Docker bridges and the exact synthetic SQLite fixture. The GitHub runner is disposable; this must NOT be run against customer services.

The driver uses **three different Python process stages** (prepare, during-partition, after-rejoin). It must never import or modify actual OTP, account or Django session code.

## Test and release criteria

Fast CI includes 28 offline Django SimpleTestCase tests in apps/accounts/test_phase7_otp_partition.py, covering every denial reason, invalid evidence, forbidden auth/session wiring and the known still-unfixed live replay race.

Redis CI adds 21 single-host SQLite concurrency and failure tests, 21 Redis adapter and witness-denial tests, plus the real Docker multi-stage partition and recovery drill. Previous Phase 7.7–7.14 Redis tests, Fast, Chromium and PostGIS remain required. No additional CI job or Production environment is created.

**Production release gate remains BLOCKED**, regardless of successful CI:

1. Design and independently review a durable, integrity-protected **multi-host quorum-backed leader authority**, with nonforgeable fencing tokens and *write-side* enforcement in the actual Redis/OTP storage path; prove stale raw writers cannot bypass it. Redis on one CI runner plus local SQLite is **not** that authority.
2. Conduct authorized Sentinel/Cluster, automatic failover and network partition tests across real failure domains, including lost AOF writes, stale promotion, lease expiry, clock irregularities, split brain and both raw/legacy writers.
3. Repair the actual API OTP verifier separately: its cache get→compare→delete race can double-verify a code and delete(False) handling is unsafe. The real legacy serialized Django Redis STRING/SHA-1 digest is incompatible with synthetic Redis HASH scripts. Obtain owner/security approval for production-format atomic consume, rates, TTL and resend changes.
4. Prove real account active/deletion locking, version affinity, historical password-reset grant drain, actual Django session idempotency/invalidation, no replay or double login, timeout-after-commit handling, multi-backend atomicity/compensation and legacy-client compatibility.
5. Obtain formal privacy, account, session-store, mobile, security, accessibility and operations owner reviews, signed runbook and separate deployment authorization. Never export customer OTP, phone or session data to GitHub or chat.

**Phase status: synthetic two-master failure preflight only. No live fix and NO Production cutover authorization.**
