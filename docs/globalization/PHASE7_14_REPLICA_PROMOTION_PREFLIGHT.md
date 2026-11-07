# Phase 7.14 — Real, isolated Redis replica promotion and old-primary rejoin

**Scope: synthetic security preflight ONLY. No live OTP verification, real account, phone, session, password-reset, cache, login, data migration, production configuration or deployment.**

Baseline main: a57022631afe8e3034d9688eec784e6910a0ad2b. Phase 7.13 independently verified post-merge CI run 42389751515 succeeded in all Fast / Redis / Chromium / PostGIS jobs.

## Objective and precise limits

Phase 7.13 actually stopped/restarted one standalone Redis Docker process with AOF. That proved survival of disposable test markers under two chosen process restarts, **not replica promotion**.

Phase 7.14 takes a real next step: create **two Redis 7.4-alpine Docker containers** in a dedicated temporary bridge network, each with its own temporary named Docker AOF volume and localhost-only published port. Start Redis replication, write synthetic markers on the original primary, observe a replica synchronization ACK and compare exact marker snapshots, stop the original primary, explicitly promote the replica using Redis REPLICAOF NO ONE, verify the promoted primary's marker states and monotone CAS. Start the old primary again, detect that it incorrectly returns as a master until told otherwise, and explicitly make it follow the new primary read-only.

This is **real manual promotion/rejoin**, not automatic Sentinel/Cluster failover, true multi-host failover, a network partition, or a consensus-leader election. Both containers share one GitHub runner host and both markers share each Redis instance's failure domain. The independent volumes do not form an authoritative, independent durable lease. AOF and Redis WAIT do not alone prove crash-proof, cross-backend transactional safety.

## Two-layer safety model

### Layer A — pure, typed offline promotion review

Module: loomera/globalization/otp_replica_promotion_policy.py.

The policy rejects unknown or ambiguous topology, missing leader, stale or advanced marker epoch, missing replication ACK, fingerprint or quarantine cause mismatch, unacknowledged writes, old writable primary, absent writer guard, unsettled session ledger, missing owner signoff and missing independent durable lease. Every enum is allowlisted, every generation is a bounded exact integer, and every boolean is type-exact.

Even when the caller asserts a completely healthy promotion, old-primary read-only status, independently verified durable lease and owner signoff, the outcome is **manual_review_only**. All authentication, session, retry, cutover, legacy fallback and real-fencing-proof flags remain false. These are synthetic assertions, not proof of a signed durable leader lease or real account session consistency.

### Layer B — test-scoped Redis primary adapter

Module: loomera/globalization/otp_replica_promotion_rehearsal.py.

Reuses the single-standalone-instance atomic paired-marker Lua scripts from Phase 7.12. Only accepts explicit LOOMERA_PHASE714_TEST_REDIS=1, unique random lowercase-hex fixture IDs, fake namespace loomera:phase714:synthetic-replica-only:, unauthenticated 127.0.0.1:6393/15 or 127.0.0.1:6394/15, and the caller's fixed node label. Each adapter operation validates the environment and client connection. Fixture creation also requires a separate LOOMERA_PHASE714_ALLOW_TEST_SEED=1 that is removed immediately after the initial prepare stage.

To attempt a Lua EVAL, the adapter requires LOOMERA_PHASE714_ACTIVE_LEADER to explicitly match the node **and** verifies Redis currently advertises the master role. Wrong/missing active-leader selection returns a denial, as does contacting a replica. It never creates a user session, authenticates an OTP, issues a new OTP, invokes a real account model or grants a Production rollback.

**Security limitation:** LOOMERA_PHASE714_ACTIVE_LEADER is provided by the CI test runner and is NOT externally authenticated, consensus-backed, monotonically committed or independent of Redis; malicious/misconfigured clients and raw Redis commands can bypass this local adapter. This is **not** a legitimate production leader-fencing design.

## CI drill: actual two-node replication, promotion and rejoin

Script: tests/phase7_redis_replica_promotion_ci.sh, run only inside GitHub Actions with the explicit fixture grant.

- Isolated primary at 127.0.0.1:6393/15 and isolated replica at 127.0.0.1:6394/15; each uses Redis 7.4, AOF appendonly yes / appendfsync always, RDB save disabled and its own named Docker volume. Ports 6393 and 6394 must be free. The ordinary CI Redis service at 6379 is never stopped or reconfigured.
- Create a unique per-run Docker network and two uniquely named containers/volumes. Run 25 Redis fixture tests (no users or OTP values).
- Prepare three 10-minute expiring synthetic paired markers: observing generation 1, quarantined generation 2 with fixed cause, and halted generation 2. Verify original Redis master role and replica slave role with live replication link. Call Redis WAIT 1, then compare the exact synthetic marker contents on both nodes; verify the replica refuses a direct write.
- Stop the original primary via docker stop and confirm its loopback port is no longer available. **Explicitly** promote the replica using REPLICAOF NO ONE; verify it reports master role. A new Python process checks all three markers and then rehearses monotone quarantine, terminal halt, original cause preservation, and rejection of stale generation. Fixture-seed privilege is absent.
- Restart the old primary, then explicitly verify it advertises master role despite the promoted replica also being a master. This is an **exposed split-brain gap** in raw Redis without consensus fencing. The fixture adapter refuses the old endpoint because the test runner selected the promoted node, but direct clients can still write to the stale master. Do not claim this proves stale writers are safely fenced in production.
- Explicitly reattach the old primary with REPLICAOF new-primary 6379; verify it is a connected, read-only slave, and confirm that live Redis refuses an HSET on that former primary. Independently compare all fixture markers with the promoted master's snapshot. Only after the real promotion and rejoin, inject missing and stale marker data in this disposable Redis instance and require fail-closed outcomes.
- An EXIT trap removes only the two named Docker containers, their two volumes and the one named Docker bridge. It does not flush/delete global Redis or real databases.

Four distinct Python driver stages: prepare, after-promotion, before-rejoin, after-rejoin. **There is no live deployment route for this driver or adapter.**

## Verification

Fast CI adds 31 Django SimpleTestCase guards in apps/accounts/test_phase7_otp_replica_promotion.py. These cover every denial reason, malformed evidence, no-live-wiring and an explicitly BLOCKED release matrix.

The existing Redis CI job adds 25 tests in tests/phase7_replica_promotion_fixture_test.py, then the real multi-stage Docker promotion/rejoin drill in tests/phase7_replica_promotion_drill.py. All earlier Phase 7.7–7.13 Redis tests, Fast checks, Chromium and PostGIS remain mandatory.

## Stop conditions for any production cutover

1. **Fix the known live security issue separately.** apps/api/v1/auth_otp.py still reads, compares and deletes OTP records in distinct operations, with a delete(False) risk under races. There is no production-format-compatible atomic compare/consume, rate/cooldown or account/session atomicity proof in this PR. Real Django-Redis legacy STRING/SHA-1 values must not be passed to synthetic Redis HASH/SHA256 scripts.
2. Design and independently verify a **durable, authoritative leader lease/generation** that cannot be forged by a local environment variable, reset on Redis loss or shared across one Redis failure domain. Explicitly fence stale clients and raw writes before and during promotion. A manually demoted old primary is not evidence of automatic fencing.
3. Conduct approved **multi-host** Sentinel or Redis Cluster failover tests with real network partitions, old-leader resurrection, AOF truncation, replica promotion, quorum/lease behavior, epoch regression, durable audit evidence and recovery from lost Redis acknowledgments.
4. Independently validate real account lifecycle locks, Django session idempotency and invalidation, no double login, password reset grant drain, historical client compatibility, rate limits and rollback prohibition. Synthetic flags from these phases are not authoritative.
5. Obtain account/data owner, privacy, session-store owner, mobile, security, operations and accessibility review and a deployment-specific signed authorization. No real OTP/account/session data should ever enter CI or the repo.

**Release status: BLOCKED.** Successful isolated promotion is useful test evidence, not proof of production failover safety or permission to deploy.
