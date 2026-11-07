# Phase 7.16 — synthetic epoch/owner/token fencing contract and stale-master bypass drill

**OFFLINE / DISPOSABLE CI TEST ONLY. No production OTP, live account, phone, session, SMS, Redis cluster, migration, flag change, deployment or real credential.**

Baseline main SHA: 9263d8057dba1c3296dd031c68cfeecc2fb74676. Phase 7.15 post-merge CI run 42394108914 independently passed Fast, Redis, Chromium and PostGIS.

## Objective

Phase 7.15 proved that two Redis instances can continue accepting **different raw writes** during a real replication-network partition, and that a separate SQLite terminal stop could deny test-adapter requests. Phase 7.16 introduces an explicitly versioned *synthetic* **(epoch, owner, random 32-hex fencing token)** contract, a single-host SQLite CAS prototype for rotating the leader, and Redis Lua CAS for requiring an exact local epoch, owner and token on a specific fixture key. It demonstrates **both** the protection offered by the constrained test adapter and the unsafe bypass on a stale Redis primary.

The verdict MUST be negative for real-world safety: SQLite and Redis are independent stores; a SQLite read followed by Redis EVAL has an unavoidable time-of-check/time-of-use window. Redis Lua is atomic only on one server. A previous leader's Redis can keep accepting old tokens until its write path is truly fenced by an independent mechanism. A local SQLite file is NOT a multi-host quorum or authenticated distributed lease; neither SQLite nor environment variables can confer Production login privileges.

## Layer A — pure evidence contract

loomera/globalization/otp_epoch_fence_policy.py validates exact typed input: witness health, owner, candidate owner, expected and observed epochs (strict bounded ints, never bool), unique synthetic lowercase 32-hex token observations, Redis marker state and role, dual-master risk, old-primary writability, prior-write acknowledgement, claimed cross-store atomicity, claimed multi-host quorum and absence of real data.

Every missing/malformed/stale/future/forged token, outdated owner, untrusted Redis marker, dual master, writable old primary, uncertain write ACK, unproven independent quorum and non-atomic cross-store check explicitly denies. Even a completely green **caller-provided** set of claims yields at most synthetic_fixture_only_manual_review and NEVER grants authentication, issuance, consume, retry, session creation, legacy fallback, production cutover or proof of consensus.

## Layer B — single-host SQLite epoch witness (NOT a lease service)

loomera/globalization/otp_epoch_witness_rehearsal.py requires LOOMERA_PHASE716_TEST_WITNESS=1, a random hex fixture ID, and the exact local file /tmp/loomera-phase716-synthetic-<32hex>.sqlite3. Creation additionally requires LOOMERA_PHASE716_ALLOW_SEED=1 only during test preparation. Reads and rotations use SQLite rw-only mode and never auto-create missing or deleted files. Symlinks are denied; cleanup removes only that fixture's file and SQLite sidecars.

BEGIN IMMEDIATE transactions serialize synthetic state:
- explicit initial seed at epoch 1, owner original, token A;
- CAS rotate to epoch 2, owner promoted, **new unique** token B, denying wrong/stale tokens, competing rotations and attempted downgrade;
- terminal halt at epoch 3 with immutable reason when the dual-master condition is observed, denying later rotation or recovery;
- corrupted, missing and inaccessible file must fail closed.

**Limitation:** one SQLite file on the same ephemeral CI runner is not a second independent failure domain, signed quorum, clock-safe lease or production durable authority. Its token is purely synthetic test data, not a real authentication secret.

## Layer C — isolated Redis Lua local CAS

loomera/globalization/otp_epoch_redis_rehearsal.py is restricted to unauthenticated 127.0.0.1:6397/15 (original) or 127.0.0.1:6398/15 (promoted), LOOMERA_PHASE716_TEST_REDIS=1, random fixture IDs and the namespace loomera:phase716:synthetic-epoch-only:. It requires an explicit CI selected owner, actual Redis master role, and an active, matching SQLite witness. Initial fixture creation, test writes and test-only adoption are each separately authorized by LOOMERA_PHASE716_ALLOW_SEED, LOOMERA_PHASE716_ALLOW_TEST_WRITE and LOOMERA_PHASE716_ALLOW_TEST_ADOPT respectively.

Each Redis server has two synthetic hash keys, fence and counter, with one 10-minute test-only TTL. One EVAL validates both keys, epoch, owner, token, fixture fingerprint, bounded counter and remaining TTL and atomically checks expected sequence and increments a synthetic counter. Concurrent contenders using one expected sequence cannot both commit on the **same Redis node**. Lost replies are backend_unavailable, not safe-to-retry. The promotion adoption script changes epoch/owner/token on the **promoted Redis only** after the local SQLite witness has rotated.

**Security limitations:** Neither the initial SQLite precheck nor Redis master-role read participates in that Lua transaction. A local Redis role check can be stale, the SQLite token can rotate between inspection and write, and raw clients can bypass the adapter. The old partitioned master remains writable with its prior epoch and token; this phase **explicitly tests that raw bypass succeeds**. There is no distributed transaction or proof that a real OTP session can be safely granted. Returned SyntheticEpochWrite is always non-authorizing.

## Actual CI network-partition/rejoin drill

tests/phase7_redis_epoch_fencing_ci.sh creates two dedicated Redis 7.4-alpine containers, two AOF volumes and separate client + replication-only Docker bridges; publishes only loopback ports 6397/6398; preserves the existing CI Redis service on 6379. Names include the GitHub run ID and attempt; the EXIT trap deletes only the exact named resources and synthetic SQLite file.

Three separate Python driver stages in tests/phase7_epoch_fencing_drill.py:

1. **Prepare** — start real Redis replication, create local SQLite witness epoch 1/A and original Redis fence keys epoch 1/A, commit one synthetic marker write, verify WAIT 1 acknowledgement and exact replica state parity. Fixture seed/write grants are then revoked.
2. **During partition** — physically detach the replication-only Docker bridge, close the old upstream replication socket, check master_link_status down, require WAIT 1=0 on a new test probe and verify the promoted replica never received that fresh write. Promote the replica with REPLICAOF NO ONE while old master remains alive. The local SQLite witness atomically rotates to epoch 2/B. The old adapter rejects A, but a **direct EVAL against the still-writable old Redis master accepts A and its old epoch**. This proves local-witness checks do NOT reliably fence raw stale writers. On the newly promoted Redis, adoption from A to B is a local CAS, and B can record only another synthetic counter. Two nodes now have diverged epochs/tokens. The witness then enters irreversible halted epoch 3; both test adapters deny all further writes.
3. **After rejoin** — explicitly reattach the old primary as a read-only replica, compare exact synthetic Redis snapshots, verify it refuses direct HSET, and confirm the external witness remains halted. Deletion of the test-only witness must cause further inspection to deny rather than reconstruct the marker or auto-resume.

This experiment uses **manual** promotion/rejoin and two containers on one GitHub runner. Not multi-host Sentinel/Cluster or security-reviewed leader consensus. The test grants to create initial fixtures or mutate/adopt markers are never exposed to live web code.

## Verification, rollback and unresolved release blockers

Fast CI: 29 Django policy/release tests in apps/accounts/test_phase7_otp_epoch_fence.py. Redis CI: 24 SQLite witness tests plus 22 real Redis epoch/sequence CAS tests, followed by the actual two-master drill. Previous Phase 7.7–7.15 Redis checks, Fast, Chromium and PostGIS still run. Exactly 11 changed files including CI and documentation.

**Production release: BLOCKED.** Require independently approved architectural design of a durable multi-host quorum-backed fencing authority, cryptographically or otherwise unforgeably bound to writers, and *write-side* enforcement against raw/legacy Redis clients even during partition, lost witness, stale role and lease/token rotation. Atomicity cannot be claimed while Redis writes remain possible on the old primary. Test real Sentinel/Cluster across distinct failure domains and persistence, failover, disk, quorum, split-brain and callback failure scenarios.

Separately address the **existing live API OTP verifier's get→compare→delete two-worker replay risk and delete(False) interpretation**. Its legacy Django Redis pickled STRING/SHA-1 format is incompatible with the synthetic HASH/tokens here. Require separate security/owner signoff on production-compatible atomic OTP verification, attempt/expiry/rate/resend guards, authoritative account lifecycle and deletion locks, real Django session idempotency and uncertain-write reconciliation. No real data in GitHub/CI. Obtain privacy, account, session, mobile, security, operations, accessibility and deployment approvals; **this PR does not deploy**.

**Status: Phase 7.16 synthetic only; demonstrates unresolved stale-master bypass; release BLOCKED.**
