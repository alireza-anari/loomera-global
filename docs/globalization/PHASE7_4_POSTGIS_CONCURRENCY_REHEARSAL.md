# Phase 7.4 — PostgreSQL UNIQUE / CAS / rollback rehearsal (synthetic only)

**Status:** actual PostgreSQL/PostGIS **test database** evidence for the
future E.164 shadow storage design, not an authorization to migrate.
Baseline: `7c2b72a33d597c8ef84d7cc17fd6c9011954be7b`,
Phase 7.3 post-merge CI `42231103463`: all three jobs succeeded.

This builds on the **pure in-memory** Phase 7.3 lock demonstration. Phase
7.4 actually sends SQL to an isolated PostGIS 16 test database created
by the Django test runner. It **never modifies the account table**,
any persistent application model, OTP/session cache, real data, migration
file, third-party provider or production deployment.

## Test isolation and entrypoint

The dedicated CI step runs in the existing PostGIS workflow's container,
after the earlier Phase 5.2 isolated migration/rollback rehearsal:

```sh
python manage.py test apps.accounts.test_phase7_postgis_shadow --failfast --noinput
```

The test runner must provision a database whose name starts with `test_`.
Tests fail if the backend is not PostgreSQL/PostGIS or PostGIS is absent.
Every test creates a **test-owned SQL table** called
`loomera_phase74_synthetic_phone_shadow` in that isolated database,
inserts exactly three fictional users (two active, one inactive), and
drops the table in `tearDown`, even on assertion failures. Django's
test-database teardown adds another isolation boundary. No SQL DDL
is added to Django migrations or `CustomUser`.

The test-owned table approximates a separately approved *future*
storage contract:

- `account_id BIGINT PRIMARY KEY`
- `mobile_number VARCHAR(11) NOT NULL UNIQUE` (legacy remains)
- `is_active BOOLEAN NOT NULL`
- `canonical_mobile_e164 VARCHAR(16) NULL UNIQUE` — covers **active
  and inactive** identities; multiple NULL rows are permitted
- `phone_identity_revision INTEGER NOT NULL DEFAULT 0` with a
  nonnegative CHECK
- candidate E.164 shape CHECK; this is **syntax**, not phone
  allocation, carrier ownership or deliverability verification.

This schema is *not* installed on any application table. It is a
narrow, controlled experiment, not a tested migration for the full
real-world account model.

## Database behaviors tested

- Multiple unclaimed/NULL shadow rows coexist. A non-NULL canonical
  value cannot be claimed twice **even if the first owner is inactive**.
- Revision-checked SQL UPDATE includes immutable legacy mobile and
  `is_active`, a NULL-shadow precondition, and a version compare.
  Returning zero rows on stale-version or wrong source means no write.
- Real SQL UNIQUE/CHECK violations are caught after a transactional
  rollback and yield only fixed outcome codes.
- An injected failure after a successful write rolls back the outer
  transaction; a later duplicate write within a two-row batch rolls
  back the **entire** batch, including earlier updates.
- Clearing a shadow requires the matching source and revision, increments
  the revision, and leaves legacy mobile and active status unmodified.
- Two **independent PostgreSQL backend sessions** compete on the same
  row: only one revision claim succeeds. Two sessions compete on
  different rows for the same canonical number: only one succeeds due
  to the actual UNIQUE index. Two disjoint claims both succeed.
- The test asserts that `CustomUser` still has no canonical shadow
  field. Legacy authentication, phone parsing and SMS.ir are not changed.

This proves genuine single-database, multiple-connection PostgreSQL
transaction and uniqueness behavior **only for these synthetic tests**.
It is stronger than a Python `RLock` rehearsal but does not verify
parallel deployed workers, real tables, cross-service race conditions,
actual account deletion/reactivation, long-running migrations, crash
recovery or operational rollback.

**Important security distinction:** SQL UNIQUE guards collision, not
ownership. The test helper intentionally allows a conflicting candidate
in one scenario so PostgreSQL itself must reject it. A real application
must first validate that a candidate belongs to the **same legacy user**
and that the active/role/deletion policy authorizes the operation.
Passing the database constraint by itself does *not* prove identity safety.

## Approved future migration sequencing — still blocked

1. Obtain independently authorized, isolated representative phone data
   and full ID/active/inactive/deleted inventory. Reconcile every
   invalid identifier or alias collision under data-owner policy.
   Real numbers are personal data: **never upload them to GitHub,
   CI logs or this chat**.
2. Get a separate review and approval of nullable shadow field type,
   unique-index semantics across all accounts, monotonic revision,
   precise E.164/national-plan validation, index deployment approach,
   backwards-compatible API policy and historical OTP/session bridging.
3. On an **approved ephemeral restored snapshot**, rehearse actual
   Django migration up/down, indexed batch backfill, fail-closed
   concurrent signup/deletion/reactivation, cross-process retries,
   and availability/lock latency. Run auth and API E2E without exposing
   PII in reports. Sign off all account and cache-key invariants.
4. Define operator stop thresholds, backup integrity, RPO/RTO and
   rollback choreography. Preserve the old username as truth until
   separately authorized cutover. A real rollback cannot be inferred
   from this test's shadow-clearing SQL.
5. Only then consider a separately reviewed model/migration PR.
   No automated deployment, actual shadow backfill or data rewrite is
   permitted by Phase 7.4.

The Phase 7 release gate remains **BLOCKED**: no approved real
snapshot, reconciliation, foreign phone numbering-plan verification,
database migration, full OTP session/replay proof, external clients
and Phase 3 manual accessibility signoff.
