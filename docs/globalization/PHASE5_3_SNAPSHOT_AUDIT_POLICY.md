# Phase 5.3 — Authorized Snapshot Audit and Historical Booking Cutover Policy

**Status:** implementation candidate. This stage adds a privacy-preserving snapshot audit and safeguards for future authorized data analysis, **not** a live-data audit, timezone cutover, migration, or deployment. No actual user/customer data was accessed. It cannot authorize a release.

## Verified base and why Phase 5.3 is necessary

- Target `main` base: `f51515384ba42dca55cf7ce16fa48e03589223de`; Phase 5.2 post-merge CI `42178943567` passed all three jobs, including a real PostGIS **synthetic-data** migration rehearsal.
- Phase 5.2 `audit_phase5_timezone_cutover` uses a fixed 1–50,000-record cap. For larger snapshots it correctly reports `scan_complete=false`; the first N rows are **not** representative proof of a full-dataset reconciliation.
- The old appointment schema stores a canonical Gregorian `OrderDetail.date` and separate naive local `time`/`end_time`/`occupied_until` fields, historically interpreted in `Asia/Tehran`. `Salon.timezone_name` is newly stored metadata; it does **not** prove a historical reservation was made in that zone.
- Neither locale nor business address can establish the original timezone; existing live booking, reminder, cancel/no-show, ICS and old Saturday=1 through Friday=7 weekday semantics remain unchanged.

## Authorized snapshot-only read path

`python manage.py audit_phase5_snapshot` is a new opt-in command that refuses all access unless **all** of the following are true:

1. A trained operator has created a **sanitized, representative, authorized, isolated PostGIS clone** with a database name beginning `phase5_snapshot_` or `test_`; it is not the actual Production or staging database.
2. The process has the explicitly set variable `LOOMERA_PHASE5_ISOLATED_SANITIZED_SNAPSHOT=I_CONFIRM_ISOLATED_SANITIZED_COPY` and receives the `--acknowledge-isolated-sanitized-copy` flag. These are deliberate acknowledgments, **not** proof of authorization or an access-control substitute.
3. Django is using `django.contrib.gis.db.backends.postgis` and the command is invoked outside any already-active transaction.
4. The database confirms `REPEATABLE READ READ ONLY` for the entire scan. PostgreSQL rejects SQL writes in this transaction. The command never runs migrations, INSERT/UPDATE/DELETE, or changes application settings.

### Example only — not executed

The authorized operator must separately provide sandboxed credentials/configuration through an approved secrets workflow. Do not paste database URLs or credentials into GitHub or chat logs. The underlying database must be an independently verified sanitized clone.

```bash
# Executed only by an authorized operator on a dedicated sanitized clone:
export LOOMERA_PHASE5_ISOLATED_SANITIZED_SNAPSHOT=I_CONFIRM_ISOLATED_SANITIZED_COPY
python manage.py audit_phase5_snapshot \
  --acknowledge-isolated-sanitized-copy \
  --json \
  --max-appointments 100000 \
  --batch-size 500
unset LOOMERA_PHASE5_ISOLATED_SANITIZED_SNAPSHOT
```

The command uses ascending primary-key **keyset pagination** internally, up to 1,000,000 records per explicitly bounded run and at most 5,000 rows per page. One transaction-level repeatable-read snapshot is used for both `count()` and all page reads. It compares every historical appointment start time against legacy Tehran and any **proposed** salon IANA zone. It also aggregates missing end/occupied time, end/occupied-at-or-before-start (possible overnight/rollover), reminder-timestamp presence, DST gap/overlap, and maximum absolute candidate UTC delta.

**Output is aggregate-only:** no primary keys, names, phone numbers, addresses, individual dates, appointment times, salon timezones, or raw reminder instants. A report has exact `total_appointments_in_snapshot`, `appointments_examined`, `scan_complete`, fixed classification counters, known error counters, and `writes_performed=0`. `--fail-on-incomplete-or-risk` can reject an incomplete or risky scan. The flag never grants release clearance.

If the cap is lower than the stable count, `scan_complete=false` and `scan_incomplete` is added. Missing, repeated or out-of-order pages fail closed. If even one count cannot be reconciled, report validity is denied.

**No false positive go-live:** Every report, even an empty or risk-free snapshot, retains `human_review_required=true`, `cutover_authorized=false`, `production_migration_authorized=false`, and reason `historical_timezone_provenance_unverified`. The risk count is an aggregate of *overlapping categories* and is not necessarily a count of distinct appointments.

## Historical reservation timezone policy (proposed, not activated)

| Class | Policy before a separate approved cutover |
|---|---|
| Existing reservation with blank salon zone | Preserve original date/time and its Tehran interpretation; no inference based on present locale or location |
| Existing reservation with newly entered explicit zone | Treat new zone as metadata only; do not reinterpret existing dates, reminder instants, ICS or cancellation/no-show windows |
| Explicit candidate zone changes UTC | Flag for authorized case review; never auto-rewrite appointment or financial deadlines |
| DST nonexistent/repeated business wall clock | Stop automatic conversion; require a documented policy and an explicit resolution by authorized owner |
| End/occupied time equal or earlier than start | Flag potential overnight/date rollover; do not assume the missing next-day date |
| New reservation after future cutover | Must explicitly store the effective booking timezone/provenance or equivalent immutable versioned semantics **before** live business-zone calculation; not implemented here |
| Rollback after timezone metadata has been set | Backup `Salon.timezone_name` first; reversing migration `0006` drops that column and therefore destroys populated metadata |
| Stored weekday and schedule | Do not renumber; Phase 6 owns a separate migration and compatibility plan |

## Still-blocked manual and data gates

A **representative** copy must eventually be supplied through separately authorized and privacy-reviewed access. This PR neither creates such access nor claims that synthetic fixtures represent production booking distributions. Actual counts, exceptional cases, financial timing reconciliation, reminder/ICS parity, live provider behavior, and rollback drills remain unknown.

A later decision requires a signed data lineage/representativeness statement, scan completeness evidence, private resolution of all flagged cases, before/after instant comparison under old and new booking rules, PostGIS rollback after metadata backup, explicit owner signoff, and Phase 3 browser/keyboard/true 400% zoom/NVDA/VoiceOver acceptance. No Production deployment is allowed here.

## CI gates for this PR

- `apps.salons.test_phase5_snapshot_audit`: reject missing authorization, wrong engine or DB name, nested transaction; verify keyset completeness, page corruption/duplicates, no PII, overnight/reminder aggregates, zero-risk still not authorized.
- `apps.salons.test_phase5_postgis_migration`: run the Phase 5.2 synthetic forward/back migration **plus** a new full PostGIS snapshot test that checks database-confirmed read-only isolation, unchanged booking/reminder persistence, explicit-zone risk detection, bounded incomplete scans and fail-on-risk behavior.
- Maintain all existing Fast checks, Chromium, and PostGIS jobs on the exact PR head, independently inspect changed files and preserve `main` pin.
- Verify all post-merge CI jobs again; do not claim Phase 5 overall release approval.

**Phase 5.3 completes only preparation for approved snapshot evidence, not an audit of real data.**
