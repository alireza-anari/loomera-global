# Phase 7.9 — Versioned OTP transition and terminal-halt rehearsal

**Security preflight only. Synthetic aggregate metadata and an isolated Redis gate; no live OTP, migration, login, user lookup, session creation or deployment.**

Baseline `main`: `6fcbcd1cdd6d63ebc54153b0a9e288ffd3069cac` (Phase 7.8). Its independently checked post-merge CI run `42270130840` completed all Fast/Chromium/PostGIS/Redis jobs successfully.

## Why this phase is necessary

Phase 7.8 demonstrated that real API OTP challenges are Django-Redis **serialized Redis STRING** values with Django `salted_hmac` default SHA-1 hex digests, whereas the Phase 7.7 Redis Lua experiment consumes a distinct **HASH** with an experimental SHA-256 digest. The live API path still does `get → compare → delete` in separate operations and may ignore a false delete return. It is not safe to route an in-flight legacy challenge to the new experimental script or to accept both versions simultaneously.

This task does not change that live behavior. It rehearses version-gating invariants **without accepting any OTP** or introducing a deployable feature flag.

## Layer A: pure offline drain review

`loomera/globalization/otp_transition_plan.py` accepts only typed, aggregate counters and booleans; it deliberately has no account IDs, phone numbers, codes, cache keys, session IDs or provider integrations. Inputs must cover:

- Full legacy cache **and** web/session/password-reset inventory and healthy cache reads. An empty but incomplete inventory is blocked.
- A separately established freeze on **all legacy OTP writers**, including API resend and active web/reset flows. An unfrozen writer is blocked.
- Zero pending API challenges, signup sessions, reset grants, and unknown historical formats.
- Elapsed time from the last legacy issue event through the **longest applicable legacy lifetime**, plus a bounded clock-skew margin (minimum 30 seconds). No default short API TTL may stand in for longer web sessions.
- Exactly typed non-negative counts and bounded timestamps; malformed, uncertain, or future-clock evidence is rejected or blocks.

Possible results are `inventory_untrusted`, `backend_unavailable`, `writers_not_frozen`, `unknown_legacy_formats`, `api_legacy_pending`, `web_signup_pending`, `password_reset_pending`, `clock_inconsistent`, `drain_window_active`, and `simulation_ready`. **Even `simulation_ready` has `production_cutover_authorized=False`**, and its flags are only caller-supplied synthetic evidence, not proof of exhaustiveness or ownership approval.

## Layer B: Redis 7.4 synthetic version gate

`loomera/globalization/otp_versioned_gate_rehearsal.py` uses **one random 32-character fixture key** under `loomera:phase79:synthetic-only:`, strict `LOOMERA_PHASE79_TEST_REDIS=1`, and unauthenticated `localhost:6379/15`. Each operation independently rechecks the grant and client connection; tests clean up only their exact key. No scan, global flush, real OTP storage, mobile/account fields, or external service calls.

The single-key Lua EVAL protocol makes transitions atomic **on the disposable standalone Redis server only**:

| State | Allowed synthetic operations | Stop condition |
|---|---|---|
| `observe` | One-time seed; CAS monotonic decrement of pending counters | Cannot activate while any counter is nonzero, deadline remains, or epoch is stale |
| `v2_simulated` | No OTP creation. A bounded `would_issue_count` only | No legacy fallback; duplicate activation refused |
| `halted` | Terminal, immutable emergency stop | No reactivation, issuance, or return to legacy acceptance |

Each atomic mutation uses an epoch compare-and-swap. Two independent Redis clients cannot both activate one generation. Seed never overwrites existing state or extends TTL. Counts cannot increase through reconciliation. If Redis expires, returns an invalid reply, fails, or loses the reply **after a committed change**, the Python decision is fail-closed; it never infers a successful auth or retries blindly.

The rehearsal gate expires after 10 minutes to isolate CI fixtures, **not** to establish a recommended Production transition design. A future approved live implementation requires durable generation/rollback markers and a documented startup state before enabling either verifier. It must not use this short-lived fixture scheme. The `reconcile` caller in tests is synthetic: it does **not** verify ownership of the claimed drain evidence.

## Verification

Fast CI runs `apps.accounts.test_phase7_otp_versioned_plan` for aggregate drain, strict types, missing inventory, historical session blockers, TTL and clock margins, release blockers, and no-live-auth wiring.

The existing Redis service job additionally runs:

```sh
LOOMERA_PHASE79_TEST_REDIS=1 python -m unittest discover -s tests -p 'phase7_versioned_gate_test.py' -v
```

This exercises: idempotent seed with preserved TTL, every pending source, CAS stale epoch, monotonically decreasing counters, exact drain deadline, two-client activation race, simulated issue counting, halt without downgrade, key loss/expiry, corrupted state, ambiguous post-commit response, malformed replies, strict namespace/DB15/environment guard, bounded inputs, and fixture-local cleanup. The original Phase 7.7 and Phase 7.8 tests remain required. The Fast, Chromium and PostGIS checks are not weakened.

## Real transition: STOP conditions and separate authorization

**No live cutover or rollback to the legacy verifier is authorized by this phase.** Required before any runtime implementation:

1. Account/data owner and security team approve the inventory scopes, operational change window, and proof of freezing *all* old OTP writers and in-flight web/reset sessions.
2. Establish a durable versioned server-side routing marker with strict new-issuance/verification affinity: never allow an OTP to be accepted by both legacy and new verifier; no default fallback on missing/invalid markers, cache uncertainty, timeouts, or Redis cluster failover.
3. Engineer and review production-safe cryptographic verification, atomic attempt counters and consume, cooldown/rate limits, key rotation, clock source, and single-user session handoff; keep inactive-user and concurrent signup denial safe.
4. Rehearse representative, **authorized** historical cache/session snapshots and client compatibility, reversible migration, incident halt, recovery from partial issuance, and rollback policy. **Once new challenges are issued, emergency stop is not the same as re-enabling legacy acceptance.**
5. Obtain formal security signoff, owner acceptance, mobile-client and Phase 3 accessibility acceptance, full CI/regression, and explicit deployment approval.

**Status: Phase 7.9 synthetic preflight only. Production release gate BLOCKED.**
