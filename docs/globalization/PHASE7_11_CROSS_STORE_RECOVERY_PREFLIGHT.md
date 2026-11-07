# Phase 7.11 — OTP cross-store uncertainty and terminal recovery quarantine

**Synthetic-only security rehearsal.** Baseline main SHA 919f6a5a8f50592543cc961587662f50da3e3ea3 (Phase 7.10); its post-merge CI run 42378631455 passed Fast, Redis, Chromium and PostGIS. This phase neither authenticates users nor accesses live accounts, cache records, Django sessions, OTP codes, phone numbers, password resets or deployment environments.

## Motivation: still-open live security issues

Phase 7.10 confirmed that atomic Redis consumption and an isolated single-key would_admit claim cannot make the actual Django account/session transition atomic. A Redis consume can complete while its client response is lost; an account can be deactivated before session creation; and a session-store write can commit despite returning a timeout. None justifies an automatic OTP retry, creation of a second session grant, fallback to the legacy verifier or an assumption of successful login.

The live API OTP verifier in apps/api/v1/auth_otp.py still reads, compares and deletes separately and can treat cache.delete returning False as success. **The live replay race remains unfixed.** The real Redis legacy serialized STRING/SHA-1 digest is incompatible with the synthetic HASH/SHA256-style challenge models. Neither Phase 7.10 nor Phase 7.11 is a deployable authentication architecture.

## Layer A: pure offline cross-store recovery policy

Module: loomera/globalization/otp_cross_store_recovery_policy.py.

SyntheticCrossStoreEvidence requires bounded integer generations, fixed enum labels and exact booleans covering:
- Redis read health, version marker integrity and expected/observed generation.
- Challenge state and *acknowledged* atomic consumption.
- Active/deleting/missing/ambiguous account and claimed authoritative account snapshot.
- Session-write status including timeout, duplicate and uncertain commit, plus claimed authoritative session snapshot.
- Completed historical password-reset-grant drain, trusted inventory, confirmed quarantine and emergency halt.

Each uncertainty yields a fixed denial reason; malformed or truthy-but-not-boolean evidence is rejected. Even when all caller-supplied claims are green, the result is manual_review_only. Its flags are always manual_reconciliation_required=True, authenticated=False, session_created=False, safe_to_retry_otp=False, safe_to_retry_session_write=False, production_recovery_authorized=False and legacy_fallback_authorized=False. No actual account, session, cache or network interaction occurs.

The flags are **unverified claims**, not independent proof of a real account lock, idempotent session write, committed Redis transaction, exhaustive inventory or owner approval.

## Layer B: isolated Redis 7.4 quarantine rehearsal

Module: loomera/globalization/otp_recovery_quarantine_rehearsal.py.

Require LOOMERA_PHASE711_TEST_REDIS=1, a random 32-character lowercase hexadecimal fixture key under loomera:phase711:synthetic-only: and unauthenticated localhost port 6379 DB15. Constructor and every operation validate the grant and client connection. Scripts access only KEYS[1]. No Redis SCAN, global flush, real identifiers, OTP, secrets, account lookup, session IDs or external provider integrations.

Single-key Lua EVAL rehearses only these **test states**:

1. Seed: observing, generation 1, challenge none and a fixed 10-minute TTL.
2. Record a purely synthetic consumption: an immutable consumed tombstone, without any OTP code verification or session handoff.
3. Quarantine: observing to quarantined by generation CAS, with an immutable fixed cause: Redis timeout, post-commit timeout, session-store timeout, ambiguous session claim, account deactivation, generation mismatch or operator stop. Increments the generation, retains tombstone, refuses retries, reason overwrite, re-seed or reverting to observing. Quarantine is also allowed before consumption to deny uncertain issuance.
4. Halt: observing or quarantined to halted by generation CAS, preserving the original reason if any. Cannot return to observing, reactivate, restore consumed challenges or enable legacy OTP acceptance.
5. Inspect: read-only health check of mode, generation, reason and TTL. Diagnostic only and never an authentication or retry grant.

Two independent Redis clients race on synthetic consume and quarantine. Halt/quarantine interleaving cannot reopen observing. A response lost *after* Redis commits yields backend_unavailable, not automatic retry, login or recovery. Missing/expired marker, invalid replies, corrupted state, wrong Redis type and bad namespace deny recovery. Test cleanup deletes only the exact owned fixture key.

**The 10-minute TTL is disposable CI isolation, NOT a durable incident marker.** This experiment does not prove Redis Cluster failover, replica promotion, persistence, production startup semantics, database transactions, account deactivation ordering, session-store idempotency or real Redis/Django session recovery. One Redis Lua EVAL cannot establish a transaction across PostgreSQL and a Django session store.

## Verification

Fast CI adds 22 tests in apps/accounts/test_phase7_otp_cross_store_recovery.py: all denial reasons, input and privacy guards, live auth no-wiring and explicit blocked release matrix.

The existing Redis 7.4 service job adds 25 tests from tests/phase7_otp_recovery_quarantine_test.py, enabled only by LOOMERA_PHASE711_TEST_REDIS=1. They cover once-only seed/consume, generation CAS, immutable quarantine cause, quarantine before/after consume, terminal halt, independent Redis clients racing, post-commit lost replies, corrupt or missing data, expiry, strict test isolation and exact-key cleanup. The prior Phase 7.7–7.10 tests and all Fast, Chromium and PostGIS jobs remain mandatory.

## STOP conditions before any real rollout

1. Account/data owner, privacy, security and session-store owners must authorize exhaustive real-world inventory, account lifecycle behavior and reset-grant drain. Do not export private account records, OTP values, phones, session cookies or cache hashes into CI/GitHub/ChatGPT.
2. Design a *durable*, monotone, version-pinned routing marker with startup/expiry/Redis failover semantics. No legacy fallback on marker loss, timeout or partial issuance.
3. Separately review and fix the live API two-worker get/compare/delete and delete(False) replay risk; ensure constant-time production-format compatible verification, atomic attempts, TTL, cooldown, resend and limits.
4. Prove authoritative account locking and deactivation checks, real Django session idempotency, cross-store timeout recovery, session deletion and account/receipt binding. Synthetic caller-supplied flags are not proof.
5. Document owner-approved incident quarantine, forward recovery and audit trail. A lost Redis response never becomes permission to replay or create a session. A halt is not automatic rollback to legacy verification.
6. Obtain independent security, owner, operator, mobile-client and Phase 3 accessibility acceptance and explicit deployment approval.

**Release gate BLOCKED.** Live OTP/session behavior, migrations and Production remain unchanged.
