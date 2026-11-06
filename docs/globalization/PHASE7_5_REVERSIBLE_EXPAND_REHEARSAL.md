# Phase 7.5 — Reversible E.164 shadow expansion and bounded backfill rehearsal

**Scope:** genuine Django historical migration *operations* on a newly
created, **test-only** PostgreSQL/PostGIS table with synthetic identities.
Baseline `f642452b765ee0de3e3805fcdac681773de7b37e`; Phase 7.4
post-merge run `42235949726`: Fast checks, Chromium and PostGIS all green.

**No production migration is created.** No `apps/accounts/migrations/` file,
`CustomUser` column, legacy login, API/web OTP, session, SMS provider or
real account data is modified. No application routing uses the test table.

## What is actually executed

The dedicated test module
`apps/accounts/test_phase7_postgis_expand.py` uses
`django.db.migrations.CreateModel`, `AddField` and reversible `RunSQL`
operations, with historical `ProjectState` snapshots and a real
`connection.schema_editor()`. It is **not** a migration checked into the
Django application graph and it does not call `MigrationExecutor` against
real account tables.

1. Django's test runner creates an isolated database named `test_*`
   on PostGIS. The test refuses any other engine/database and checks the
   spatial extension.
2. A single test-owned table, `loomera_phase75_phone_shadow_fixture`,
   is created with an account ID primary key, existing 11-character
   unique legacy mobile and active status. Three synthetic accounts
   (two active, one inactive) are inserted.
3. `AddField` adds a nullable unique `canonical_mobile_e164` (16 chars,
   including the leading `+`), followed by
   `phone_identity_revision` (positive integer, initially zero).
   **Django's field default backfills existing rows, but is not a
   permanent PostgreSQL DEFAULT here.** Direct SQL inserts after expansion
   must explicitly supply revision `0`; future ORM and other writers need
   an independently reviewed common revision-initialization contract.
   A reversible SQL CHECK constrains ASCII E.164 *syntax*.
4. A **complete preflight** rejects any missing/extra account, malformed
   or non-ASCII legacy stored identifier or candidate collision before
   the first backfill UPDATE. Operator-approved source provenance is
   still required for real data; this test uses synthetic fixtures only.
5. Backfill uses bounded per-chunk `transaction.atomic()`, with a
   compare-and-swap condition including original account ID, legacy
   number, active status, revision 0 and NULL shadow. A successful row
   receives revision 1. Repeated exact assignments at revision 1 are
   treated as no-ops; any other prior value or revision fails closed.
   The database unique constraint remains the final arbiter of races.
6. Injected failures demonstrate **all-or-nothing per chunk**.
   A previously committed chunk remains intact when a later chunk
   fails. Re-running safely skips exactly matching committed rows and
   completes the remainder. No implicit account merge, last-writer-wins
   rewrite, or best-effort skip is permitted.
7. The backward operations are run in reverse order only if no
   canonical claims remain: CHECK dropped, revision removed, then the
   nullable shadow removed. A claimed shadow is a hard stop to schema
   shrink. A **test-only** version-checked shadow clear demonstrates a
   reversible round trip; it is explicitly not an authorized operational
   rollback procedure.

Each test tears down the synthetic table. The test runner independently
discards the entire `test_*` database. There are no new permanent
application model fields and no entries in `django_migrations` for the
synthetic app. The CI step runs *after* the Phase 7.4 real PostgreSQL
concurrent-CAS and UNIQUE tests.

## Failure-mode evidence

- Nullable expansion preserves all original account IDs, login values,
  active flags, including the inactive user, and creates a unique index
  spanning inactive and active rows.
- Bounded two-chunk backfill commits only expected candidates; its
  result is aggregate metadata, not account records or phone values.
- A simulated restart resumes after a committed chunk without
  incrementing revisions twice.
- An exception halfway through a chunk rolls back every write in that
  chunk. The previous committed checkpoint remains durable.
- Unrecognized legacy placeholders, unexpected records, preexisting
  foreign/wrong shadows and stale revisions block progress rather than
  rewriting or guessing.
- Reverse operation stops while claims exist. After an *explicitly
  synthetic* version-checked clear, backwards and forwards schema
  operations preserve the exact original legacy IDs/numbers/active
  states. Rollback drops shadow history, **not** the legacy username.

The tests are meaningful PostgreSQL DDL and transaction checks, but
they do **not** prove: a migration applied to `CustomUser`, real table
index-build time/locks, real data backfill feasibility, concurrent
signup/deletion/reactivation across deployed services, non-IR numbering
plan validity, historical OTP challenge continuity, old-session
security, or production availability. An operation being reversible
on three synthetic rows does not authorize irreversible account changes.

## Conditions for any future migration PR

Prior to even proposing the genuine `CustomUser` expand migration:

- Obtain independently authorized, isolated and protected *representative*
  account data; phones remain **personal information** even without
  names or addresses. Never put real exports into GitHub, ChatGPT,
  public CI, logs or PR descriptions.
- Reconcile active, inactive, deleted and historically reused identities,
  invalid stored numbers, collisions, original-deletion references,
  role relationships and old sessions under the data owner's policy.
- Select and review the real nullable shadow column, index plan,
  online DDL/lock behavior, positive revision semantics, batch
  checkpoints and **permission-aware** account lookup/ownership rules.
- Test a real app migration forward/backward and bounded backfill on
  a separately approved isolated restored snapshot, with genuine
  cross-worker writes, commit/rollback, backup and RPO/RTO rehearsal.
- Prove no OTP/cache-key replay, no loss of request/verify throttling,
  no account takeover, preservation of old password and session flows
  and compatibility of third-party/mobile clients.
- Obtain explicit security, privacy, account-owner, operator and manual
  accessibility approvals before any cutover or production release.

**Phase 7.5 exit:** technical **synthetic-only rehearsal**.
Actual schema migration, real-data backfill and canonical login remain
**BLOCKED**. No production deployment is performed.
