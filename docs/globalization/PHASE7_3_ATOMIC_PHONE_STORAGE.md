# Phase 7.3 — Canonical E.164 shadow storage, uniqueness and concurrency contract

**Status: future schema specification + synthetic in-memory rehearsal only.**
Pinned starting `fefa8b357da914b198512a1991aaab171fe95848`
and independently successful Phase 7.2 post-merge CI run
`42221139759`. **No database field/index/migration, account
write, login or OTP change, deployment, or approval to use live data.**

The machine-readable **proposed** contract is
`docs/globalization/PHASE7_3_STORAGE_CONTRACT.json`.
The pre-existing 11-character unique
`CustomUser.mobile_number` remains the sole legacy
`USERNAME_FIELD`, and SMS.ir / public API authentication
continue to use their historical Iranian mobile representation.

## Why a shadow field, not an in-place conversion

Current legacy `09xxxxxxxxx` is 11 characters; E.164 may
use a plus sign and 15 digits (16 chars). An in-place rewrite can truncate
values, make the old username unresolvable, invalidate OTP challenges,
and accidentally connect an inactive or previously deleted account.

A possible future approved **expand-only** Django model would introduce:

| Attribute | Proposed representation, NOT present in the model |
| --- | --- |
| Canonical shadow | nullable `CharField(max_length=16)` |
| Source of truth during expand | existing `mobile_number` unchanged |
| Format | validated E.164 candidate; carrier/country plan check is separate |
| Uniqueness | database-verified unique **non-null** canonical values |
| Inactive users | same uniqueness scope, no partial index on active only |
| Deleted/anonymized placeholders | owner-reviewed state; never auto-claim or recycle |
| Concurrency revision | monotonic nonnegative `phone_identity_revision` |
| Rollback | nullable shadow can be cleared with version check, not rekeyed |

The exact future Django constraint/index syntax, deployed PostgreSQL
version, online index creation strategy, locking and null semantics
must be reviewed separately. An application-side `.exists()`
check **alone** is not a uniqueness guarantee; an actual database
UNIQUE index is mandatory before accepting parallel writes. Null may
remain unclaimed during the expand phase; until cutover a missing shadow
must never cause implicit fallback to the wrong account.

**Stored phone number identity and contact/delivery number are different
concepts.** A syntactically valid E.164 identifier is not independently
validated for national allocation, ownership or SMS reachability.

## What Phase 7.3 implements and proves

New pure module:
`loomera/globalization/phone_shadow_reservation.py`.

`OfflinePhoneShadowReservation` loads only explicitly
supplied finite legacy rows with exact fields:
`account_id, mobile_number, is_active`. It refuses
duplicate account IDs, duplicate canonical identities, invalid/placeholder
or non-ASCII legacy usernames and malformed active states. Every
shadow claim requires an exact existing account ID, literal legacy
username, active/inactive flag, expected row version, and an E.164
candidate matching the *same* source account.

The synthetic simulator provides:

- `claim_one` and `claim_batch`: a
  compare-and-swap rehearsal protected by one in-memory lock. It validates
  **all** rows before any batch changes and rejects a stale version,
  wrong account, invalid E.164, reused candidate or attempted change in
  legacy username / active state.
- `rollback_one`: clears only the simulated shadow on
  an exact version match, then increments the revision. It never changes
  the legacy login value or status. It is **not** a real DB rollback.
- `audit`: only aggregate counts and explicit
  `false` release/uniqueness flags; it contains no phone, account ID,
  hash, authorization reference, or raw source row.

Dedicated synthetic tests cover a 3-account roster including an inactive
account, strict source rejection, wrong-account and replay denial,
all-or-nothing multi-row batches, stale version conflicts, reversible
shadow changes, and simultaneous threads attempting overlapping claims.
Phase 7.2 source-to-shadow verification is also cross-checked.

**Crucial limitation:** an in-memory `RLock` proves
atomic behavior **only inside one Python process in the test**.
It cannot prove multi-worker, database transaction, stale read,
distributed cache, crash or concurrent signup behavior. Even passing
every test keeps `live_database_uniqueness_verified=false` and
`multi_process_race_safety_verified=false`.

## Required future database transaction contract (not implemented)

A separate security-reviewed implementation must:

1. Run a complete explicitly authorized sensitive export and Phase 7.1/
   7.2 aggregate collision analysis, with independent data-owner signoff.
   Preserve deleted/inactive identities and their deletion audit policy;
   do not ignore them when assessing uniqueness.
2. Expand the schema in a **separate** reviewed migration, keeping the
   old username, current session and OTP cache semantics intact.
   Deploy a canonical unique non-null index whose actual PostgreSQL
   behavior is rehearsed, and a version column. No nullable shadow is
   ever authoritative until explicitly approved.
3. Implement every claim in one database transaction, using a row lock
   or versioned SQL compare-and-swap AND the database unique index.
   On a stale revision, conflicting candidate or IntegrityError:
   fail closed without half-written account state, auto-merge or
   silently selecting a different user.
4. Backfill only in bounded, observable and idempotent chunks with
   reconciliation after each chunk, stable ID/legacy/active-state
   snapshots, durable checkpoints, concurrency probes and a stop switch.
   Do not skip invalid, inactive, administrative or deleted identities
   without separately signed disposition.
5. Validate real web password login, signup, password reset, API/web OTP
   request/verify, cooldown and rate-limit namespaces, old session TTLs,
   active-user lookup, permissions, all roles and external clients
   before enabling any versioned canonical lookup or write.
6. To roll back prior to contract removal, disable canonical reads/writes
   and use the unmodified legacy field. Only an approved, independently
   tested runbook may repair or clear real shadow values, using row
   version guards and the immutable authorized snapshot. Define and
   sign off backup, RPO/RTO, account-lockout and rollback thresholds.
   Never apply non-idempotent number conversions twice.

## Stop conditions and release status

Fail on any shared candidate (including inactive or deleted accounts),
invalid legacy field, ownership ambiguity, changed ID/status/password
authentication assumptions, stale revision, partial batch result,
unverified database unique index, unverified multi-process race behavior,
missing session/OTP bridge, incomplete mobile-client compatibility or
missing data-owner authorization. The `7.3` exit-matrix remains
**blocked** for actual canonical cutover.

Real phone exports are **personal data**. Never upload them to this
conversation or commit them to GitHub, and do not use Production account
records in this rehearsal. The existing Phase 7.1 / 7.2 operator-gated
offline scanners remain the only file-based preview tools; this phase
introduces no file-reading or external process action.
