# Phase 7.17 — three independent Redis vote witnesses and write-gateway failure preflight

**Synthetic-only, GitHub-hosted disposable laboratory. No Production OTP, account, phone, user, password-reset grant, real session, customer cache, migration, rollout, or deployment.**

Baseline main: db76ca191a03a7a591bb33a57bfbd99b155fdb5f. Phase 7.16 post-merge GitHub Actions run 42399854027 independently succeeded in Fast, Redis, Chromium, and PostGIS.

## Motivation and security conclusion

Phase 7.16 showed that rotating a local SQLite epoch/token can make the test adapter reject a stale token while the old, writable Redis primary still accepts a raw command using the old token. Phase 7.17 advances the experiment from **one local SQLite witness to three separate Redis processes**, each with independent disposable AOF storage, and observes a two-of-three vote for one candidate in an isolated epoch. A restricted Python write gateway checks this majority before executing a local Redis Lua epoch/sequence CAS.

**This does NOT solve live fencing.** All five Redis processes run on **one GitHub runner**, and three independent Redis processes with single-use Lua vote records are not a genuine Raft/Paxos, authenticated membership, durable cross-site quorum, independent witness lease, or deployable security authority. Checking remote votes and then invoking EVAL on the chosen data Redis is a time-of-check/time-of-use race; an untrusted raw Redis client or legacy writer can bypass the Python gateway entirely. The test deliberately proves that the old primary still accepts a stale raw EVAL even after a two-witness majority recognizes the promoted data node.

The only legitimate release verdict is **BLOCKED** until independently reviewed infrastructure can deny all unauthorized raw writes, validate durable quorum epochs, repair the live OTP replay gap, and safely coordinate actual account/session transactions.

## Layer A: one irreversible vote per test witness

Module: loomera/globalization/otp_quorum_voter_rehearsal.py.

Three real Redis 7.4-alpine server processes are started on loopback ports **6405, 6406, 6407**, logical DB15, with separate ephemeral AOF volumes. Each vote is a single-key Lua atomic transition, on **that particular Redis process only**:

- prepare: ready / epoch 1 / owner original / token A, 10-minute TTL, exactly one 32-hex random synthetic fixture identifier;
- proposal: vote for epoch 2 / promoted / token B **once**; an attempted re-vote for token C is a fixed conflicting_vote denial. A repeated vote for B returns already_voted, not an additional grant;
- terminal stop: voted / epoch 2 → halted / epoch 3; never revives or extends TTL;
- absent/wrong-type/corrupt/unavailable key returns denial, not auto-seeding, login, retry, real session, or production recovery.

Every operation requires LOOMERA_PHASE717_TEST_REDIS=1, the exact localhost voter port and DB15, and the correct node label. Creating, voting and halting each require **separate explicit CI-only flags**. No account identifiers, actual OTP values, session cookies, phone numbers, or credentials are involved. A successful Lua response is a *test observation*, not cryptographically authentic leadership evidence.

## Layer B: three-observation bounded quorum policy

Module: loomera/globalization/otp_quorum_evidence_policy.py.

Takes exactly one typed observation from each of fixed voters a/b/c in fixed order. Requires 2 or 3 matching, epoch-2, promoted-candidate votes and rejects conflicting candidate claims or any terminal voter halt, even if two other votes exist. One voted witness with two unreachable peers is **majority_unavailable**; two matching votes plus one missing peer are only **synthetic_majority_observed_only**. Malformed, out-of-order, duplicated, impossible states, noncanonical tokens, boolean epochs, wrong owner or candidate are rejected.

All decisions keep authenticated=False, session_created=False, otp_consume_allowed=False, can_issue_otp=False, can_write_production=False, raw_old_primary_fenced=False, consensus_safety_proven=False and legacy_fallback_authorized=False. The policy does not grant production permissions on any input.

**Assumptions and impossibility boundary:** a fixed one-election voting rule can show quorum intersection for this single test epoch *provided that each voter remains trustworthy, immutable, independent and durable*. It does not implement a replicated state machine, durable globally ordered leader logs, mutual authentication, lease expiry, crash-safe reconfiguration, distributed fsync proof, split-brain raw writer isolation, network policy, or multi-host fault tolerance. Those are not implied by a two-of-three count.

## Layer C: test-only majority-gated data Redis Lua counter

Module: loomera/globalization/otp_quorum_write_gateway_rehearsal.py.

Two separate data Redis processes use localhost ports **6403, 6404**, DB15, with their own AOF volumes and ephemeral data fixture namespace. They run initial source→replica replication over an independently detachable Docker bridge. Existing CI Redis on **6379 is NEVER accessed or restarted**.

Only the **promoted** test gateway (never original) may call a Lua EVAL on the promoted data server after observing at least two matching witness votes and verifying the target Redis role is master. It uses the existing Phase 7.16 synthetic two-key Lua epoch/owner/token and expected-sequence CAS on a fresh Phase 7.17 key prefix, not the real OTP/session storage format. Setup, synthetic adoption and later write operations have distinct test-only grants. Each result denies authentication, real issuance, session creation, retry and Production permission.

**Crucial weakness explicitly tested:** a raw Redis connection to the old primary bypasses this Python gateway. Since that server still holds epoch 1 / original / token A during a data-network partition, its local Lua CAS accepts token A. This demonstrates that a *majority read* outside the Redis transaction does not physically fence stale raw writers. No change to the real Redis ACL, firewall, live auth, Django session, or application routing is performed.

## Actual isolated five-process Docker experiment

Script: tests/phase7_redis_quorum_ci.sh. Driver: tests/phase7_quorum_failure_drill.py.

1. The CI job verifies every selected port is unused, creates **two data containers and three witness containers**, five disposable AOF volumes and two disposable Docker bridges. Only data nodes join the replication-only bridge. All Redis endpoints publish exclusively to 127.0.0.1; protected mode is disabled **only inside these disposable laboratory containers**. The ordinary CI Redis service on port 6379 is untouched.
2. Seed all three witnesses with epoch 1 / token A and a paired synthetic data marker on the original primary. Verify source→replica role and link, Redis WAIT 1 ACK and exact marker snapshots; no candidate majority exists. Revoke seed authority.
3. Physically detach the replica's replication-only bridge, close its former upstream socket, require link down, require **WAIT 1=0** for a new synthetic source probe, manually promote the replica, then verify it does not contain the fresh source probe. Both data nodes now advertise master.
4. Two witnesses atomically vote for epoch 2 / token B, third is still ready. Conflicting token C attempts are rejected. Gateway denies the old node. The promoted gateway adopts the new epoch locally via EVAL and commits exactly one synthetic sequence write.
5. **Negative assertion:** direct EVAL against the un-reconfigured old master still commits with epoch 1 / token A; the two data copies disagree. This prevents any claim of solved stale-primary fencing.
6. Shut down two of the three witness processes. The gateway now returns majority_unavailable and denies further test writes. Yet a raw old-primary write is still accepted. Restart only those two disposable witnesses.
7. Restore the data replication bridge and **explicitly** reattach the old data master as read-only replica; verify exact synthetic marker convergence and direct HSET refusal. Two witnesses enter terminal halted epoch 3; subsequent gateway requests are denied even though Redis data has converged.

The EXIT trap deletes only those five run-specific containers, their five volumes, the two temporary bridges and associated test resources. Never run this script on customer or shared operational hosts.

## Test coverage and exit criteria

Fast CI adds **28** Django SimpleTestCase safety tests for strict quorum evidence validation, no-live-wiring and release blockers.

Redis CI adds **31** true Redis fixture tests across independent voter processes, including one-vote-per-node CAS races, competing candidates, halts, corrupt/missing markers, lost replies, exact cleanup and gateway denial. The real multi-stage integration drill is additional. All older Fast checks, synthetic Redis phases 7.7–7.16, Chromium keyboard smoke and PostGIS migration rehearsal remain mandatory. Exactly 10 new/change files: CI, three modules, one Fast tests file, two Redis test/drill files, one shell script, JSON exit matrix and this document.

## Non-negotiable release blockers

**Status: BLOCKED** until all of the following exist and are independently reviewed:

- An **actual multi-host authenticated consensus** and externally enforceable epoch/lease authority, with durable quorum, voter identity, reconfiguration, compaction, recovery, timing and fault guarantees; this lab is not Raft/Paxos or a durable production quorum.
- **Write-side enforcement** in real data access, independent of the caller's voluntary Python gateway. Real network isolation, Redis ACL permissions, credential rotation, stale connection termination, and raw/legacy write bypasses must be reviewed and tested *under partition and clock/persistence faults*; client-side checks cannot create transactional fencing.
- Separate production-compatible repair of live apps/api/v1/auth_otp.py, which still follows cache get→compare→delete and ignores delete(False), allowing possible concurrent replay. The Django-Redis pickled STRING/SHA-1 legacy value is incompatible with synthetic HASH / generation tokens; do NOT deploy this experiment as a fix.
- Actual account lifecycle locking, password reset grant drain, session store idempotency and expiration, uncertain commit reconciliation, no double-login and rollback/cutover semantics. Real user data must never enter synthetic CI.
- Signed account/session/security/privacy/mobile/operations/deployment approvals, multi-host Sentinel/Cluster recovery rehearsal and separate controlled Production rollout authorization.

This phase deliberately makes progress in **testable failure evidence**, not live availability or Production readiness.
