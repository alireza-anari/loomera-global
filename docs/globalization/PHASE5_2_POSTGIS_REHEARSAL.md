# Phase 5.2 — PostGIS Rehearsal and Timezone Cutover Risk Audit

**Status:** merged PR #122 at `f51515384ba42dca55cf7ce16fa48e03589223de`. Exact-head and post-merge CI run `42178943567` passed all three jobs. This step prepares an **ephemeral synthetic-data rehearsal**, not a migration of real Loomera appointments. PostGIS CI success does **not** authorize timezone cutover or Production deployment.

## Base and boundaries

- Pinned starting `main`: `45ac12a1dcd1a7c40aef9f3001c2e5ca5c260f74` (Phase 5.1, CI run `42110830260` successful).
- Existing `OrderDetail.date` is a canonical Gregorian `DateField`; `time`, `end_time`, and `occupied_until` remain separate local wall-clock `TimeField` values.
- Existing booking methods, cancellation windows, ICS event exports, reminders and no-show workflows continue to use their historical semantics. `TIME_ZONE` and `CELERY_TIMEZONE` stay `Asia/Tehran`.
- `Salon.timezone_name` remains **optional metadata**. An explicit zone must never trigger automatic reinterpretation of existing bookings. Blank still means legacy Tehran in the new boundary.
- Persisted salon weekday numbering remains Saturday=1 ... Friday=7 (Phase 6 owns any transition).
- No source repository modifications; no Production or staging deployment.

## Workstream A — True spatial CI migration rehearsal, synthetic data only

`.github/workflows/ci.yml` adds an independent GitHub Actions job with an ephemeral `postgis/postgis:16-3.4` PostgreSQL/PostGIS service. It installs the same pinned Python application dependencies and GIS system libraries as the current CI, then calls:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.salons.test_phase5_postgis_migration --failfast --noinput
```

Django's test runner creates its own test database. `Phase5PostGISMigrationRehearsal` checks that the PostGIS extension is active, creates a **synthetic** salon, opening-hour row, customer, order, and appointment, and snapshots appointment identity/foreign keys, Gregorian date and all wall-clock/occupied-through time fields, duration, buffer, reminder UTC instant, and persisted legacy weekday. The rehearsal uses Django `MigrationExecutor` to reverse `salons.0006` to `0005`, confirm the optional timezone column is absent while appointment values remain unchanged, then reapply `0006`, verify the original booking values and blank legacy fallback, and confirm changing an **explicit timezone metadata field** does not modify the appointment or reminder snapshots.

A `finally` block restores the synthetic database to the latest schema even when the test assertion fails. This confirms actual spatial SQL execution in CI only. It cannot establish real-data migration safety, production extension permissions, or unexpected legacy record shapes.

## Workstream B — bounded, read-only cutover audit

New command:

```bash
python manage.py audit_phase5_timezone_cutover --json --max-appointments 5000
```

This orders `OrderDetail` rows by primary key, reads only `date`, `time`, `end_time`, and `salon__timezone_name`, and inspects at most `N + 1` rows (maximum configured N is 50,000). Only aggregate statistics are printed; no names, user IDs, appointment IDs, phone numbers or timestamps are included in the JSON. The report contains `scan_complete`, `appointments_examined`, fixed classification counts, possible UTC shift magnitude, overnight/equal-end counts, and an explicit `cutover_authorized=false` and `writes_performed=0`.

Risk classes: missing start date/time; invalid explicit zone; legacy or candidate DST gap/fold; a candidate UTC instant differing from historical Tehran; and end time less than/equal to start (possible overnight/date rollover ambiguity). A changed instant is **a human-review candidate, never an instruction to change records**. `--fail-on-risk` makes incomplete scans and identified risks fail closed. A clean report is **not** automatic permission to cut over; a complete snapshot analysis plus independent approval is still required.

This is a **current-state inventory**. If business timezone metadata was entered after historical booking creation, it does not prove the timezone at the time of booking. More sophisticated timestamp provenance or cutover fields may be necessary before changing live logic.

## Workstream C — release gates and rollback

| Gate | Evidence in Phase 5.2 | State |
|---|---|---|
| GIS-backed schema reverse/forward | Ephemeral PostGIS GitHub CI | **Verified on synthetic data: CI 42178943567** |
| Synthetic appointment and reminder integrity | Exact before/after synthetic snapshots | **Verified on synthetic data: CI 42178943567** |
| Bounded read-only audit and fail-closed behavior | Python unit tests + GitHub CI | **Verified: CI 42178943567** |
| Real authorized legacy dataset scan and signed-off completeness | No real dataset connected | **BLOCKED** |
| Night/overnight, DST gap/fold and stored instant reconciliation on a sanitized copy | Only synthetic DST/unit fixtures | **BLOCKED** |
| Pre-rollback backup of `Salon.timezone_name` after any explicit assignment | Required; reversing `0006` drops this column | **BLOCKED** |
| Operator permission, rollback drill, owner acceptance and Phase 3 manual accessibility gates | No approval or manual evidence | **BLOCKED** |
| Timezone-aware live booking, ICS, reminder and weekday cutover | Outside this PR; no writes | **NOT PERFORMED** |
| Production deployment | No authorization | **NOT PERFORMED** |

### Safe future operating procedure (not executed)

1. Obtain explicit permission and use a read-only access path to a **sanitized, representative** PostGIS snapshot. Keep original appointment date/time, booking status, timestamps and salon timezone metadata together for analysis; do not export customer identifiers into CI/logs.
2. Verify migration history and PostGIS extension/versions, backup the database, verify the backup can be restored. In particular, a schema rollback after `timezone_name` has been populated would **erase this new metadata** unless it was backed up and restored.
3. Run both aggregate audit commands on the snapshot:
   ```bash
   python manage.py audit_calendar_timezone --json --fail-on-invalid
   python manage.py audit_phase5_timezone_cutover --json --max-appointments 50000 --fail-on-risk
   ```
   A nonzero exit may be expected from review-required data; do not suppress it or claim an all-clear.
4. Quantify any truncated scans, timezone categories, missing date/time, DST gaps/folds, date-rollover records, UTC deltas, reminder and ICS differences; reconcile individual cases **privately** with authorized reviewers. No automatic timezone inference from language, country, city, maps or telephone prefix.
5. On a **separate throwaway PostGIS clone**, rehearse forward and reverse schema migration, and compare canonical appointments, financial deadlines, reminder instants, booking windows and current weekday identifiers against a signed baseline.
6. Require named owner approval, explicit policy for new versus legacy booking creation, handling of DST repeated/absent times, an additive rollback plan preserving explicit timezone metadata, and a separate PR before changing any live behavior.
7. Do not deploy or apply migrations to Production as part of this phase. The user must separately authorize Production activity.

Phase 3 manual acceptance remains `BLOCKED_MANUAL_ACCEPTANCE`. **This PR cannot close Phase 5 as a whole**, regardless of CI outcome.
