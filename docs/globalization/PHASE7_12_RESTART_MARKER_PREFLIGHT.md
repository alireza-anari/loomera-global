# Phase 7.12 — Restart evidence, marker divergence and fail-closed reattach

**Scope: OFFLINE/SYNTHETIC-ONLY SECURITY PREFLIGHT. No live authentication, Redis cluster restart, real account/session lookup, OTP verification, schema migration, real credential, deployment or production transition.**

Baseline main SHA: b491b3c0bdf895475c8e191248ed908375695205 (Phase 7.11). Its independently verified post-merge CI run 42385191044 succeeded in all Fast/Redis/Chromium/PostGIS jobs.

## Why this phase exists

Phases 7.10 and 7.11 rehearsed Redis atomic challenge consume, a simulated session claim, quarantine and terminal halt. Their markers **expire in ten minutes** to keep the CI Redis service isolated. The presence of a marker before a network timeout is not proof that it remains authoritative after a server restart or failover. A promoted stale replica can present an older generation, and complete eviction can make it appear safe to start over. That would be unsafe for real OTPs.

Phase 7.12 does NOT solve persistence or automatic recovery. It defines a fail-closed contract, tests selective loss and divergent versions against a standalone Redis test fixture, and records the remaining production blockers.

## Layer A — pure offline startup/restart assessment

Module: loomera/globalization/otp_restart_evidence_policy.py.

The function assesses only caller-supplied synthetic enums, exact booleans and strictly bounded generation numbers:
- Redis health; verified/missing/stale/corrupt/unreadable reference and volatile markers;
- Expected, reference and observed volatile generations; synthetic fingerprint and mode alignment;
- Claimed topology and independent verification, session ledger status and uncertainty;
- Claimed owner inventory completeness, freeze of legacy OTP writers, password-reset grant drain and owner signoff.

Malformed inputs are rejected. A missing or conflicting marker, a lower observed epoch, a future/unverified epoch, incompatible mode, lost fingerprint, unclear Redis topology, unsettled session ledger or incomplete owner signoff **always denies automatic restart**. A halted/quarantined state never returns to observation. Even all-green *claimed* evidence yields only manual_review_only.

Every output has can_authenticate=False, can_reissue_otp=False, can_resume_issuance=False, can_recreate_missing_marker=False, can_retry_session_write=False, legacy_fallback_authorized=False and production_cutover_authorized=False. An all-green synthetic snapshot is not independent evidence of a genuine durable marker or proof that a real Django session can be safely created.

## Layer B — two-key synthetic Redis divergence and reconnect

Module: loomera/globalization/otp_restart_marker_rehearsal.py.

Strict namespace: loomera:phase712:synthetic-only: with one random 32-character lowercase hexadecimal fixture ID and exact key suffixes reference and volatile. Requires LOOMERA_PHASE712_TEST_REDIS=1, unauthenticated localhost port 6379 DB15. Every operation verifies the same client connection and guard. Cleanup deletes precisely the two fixture-owned keys and never scans or flushes Redis.

A standalone Redis Lua EVAL checks both markers under one atomic invocation, including the current generation, fixed fingerprint, mode, failure cause and positive TTL. The explicit **test fixture initializer**, callable only under the test grant, creates both keys with a fixed ten-minute expiry. This initializer is **not** an application bootstrap, an incident recovery API or a recommended future production primitive. It can create a new test fixture after total expiry if deliberately called; such a call must NEVER be used as real restart recovery.

The ordinary inspect_after_reconnect method does not create, extend, heal or reset anything. It yields:
- observing, quarantined or halted only for two matching, syntactically valid keys;
- reference_lost, volatile_lost or both_lost for missing keys, without re-bootstrap;
- split_brain or corrupt for mismatched generation, fingerprint, mode/cause, expired or invalid state;
- backend_unavailable for Redis errors and invalid replies.

Quarantine and halt operate through one *two-key* compare-and-swap, bump generation monotonically, preserve the initial quarantine cause, never extend TTL and never return to observation. Two independent clients can race; only one initial transition wins. A lost response after a committed transition reports backend_unavailable with no automatic retry or authentication. An inspect after reconnect remains a diagnostic observation and NEVER grants login, OTP reissue or safe session write.

**Critical limitation:** Both keys are on the **same Redis instance and share its failure domain**. This is NOT an independently durable checkpoint, a real Redis process restart, Redis Sentinel/Cluster or replica promotion. Two-key EVAL atomicity on this local standalone instance does not establish persistence under failover or transactional atomicity across Redis, PostgreSQL and Django sessions. Fixture expiry is intentionally short and incompatible with durable production recovery. No real data is used.

## Verification

Fast CI adds 27 Django SimpleTestCase tests from apps/accounts/test_phase7_otp_restart_evidence.py for all failure reasons, invalid and truthy-coerced input, release blockers, no live-auth wiring and the existing API verification race.

The existing Redis 7.4 service job adds 37 integration tests:

    LOOMERA_PHASE712_TEST_REDIS=1 python -m unittest discover -s tests -p 'phase7_restart_marker_test.py' -v

Coverage includes explicit test-only fixture initialization, reattach with a new independent Redis client, no auto-rebuild after loss, selective and total key loss, injected generation regression/advance, mismatched fingerprint/mode/cause, missing TTL and wrong-type state, two-client CAS races, immutable halt, lost response after commit, malformed backend replies, strict localhost DB15 guard and exact-key cleanup. These are **injected faults and client reconnects**, not a real Redis restart or promotion test.

All existing Phase 7.7–7.11 Redis checks, Fast checks, Chromium smoke and PostGIS tests remain required.

## Production go/no-go: BLOCKED

1. Obtain explicit security, account/data owner, privacy, session-store owner, operator and mobile-client approvals before collecting any real account, OTP, phone or session evidence. Never upload such sensitive data to repository or chat.
2. Independently design and test a truly durable, integrity-protected, persistent generation and immutable quarantine marker across actual Redis failover, server restart, replica promotion, full marker eviction, partial write and startup. Decide how a service fails closed when the independent reference is inaccessible; do not trust another copy in the same failure domain.
3. A production implementation must prohibit accidental bootstrap after marker loss, prove monotone fencing and version-specific issued-challenge affinity, and keep halted generations terminal. **Never fall back to the legacy verifier** merely because a marker has disappeared.
4. Separately fix the real API get → compare → delete two-worker replay race and the delete(False) success interpretation, with production-format-compatible, timing-safe code verification and atomic attempts, expiry, resend, rate limits and cooldown. The live serialized legacy STRING/SHA-1 format cannot be routed directly to these synthetic HASH scripts.
5. Prove authoritative account active/deletion checks, receipt-purpose/version affinity, Django session idempotency, no double login, timeout-after-commit behavior and safe resolution of cross-store ambiguity under operator-approved procedures. One Redis EVAL cannot enforce multi-backend atomicity.
6. Conduct actual authorized restart/cluster/replica promotion drills, explicit manual access and Phase 3 accessibility acceptance, a signed incident forward-recovery runbook, and separate deployment approval. Green synthetic CI is not a production authorization.

**Status: Phase 7.12 synthetic preflight only. Live authentication race UNFIXED. Production release gate BLOCKED.**
