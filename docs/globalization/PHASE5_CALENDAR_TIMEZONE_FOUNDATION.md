# Phase 5.1 — Canonical Calendar and Business Timezone Foundation

**Status:** implementation candidate pending exact-head CI and independent PR review. **Not the Phase 5 release exit**; no Production deployment, automatic appointment conversion, or legacy weekday migration.

## Existing data and compatibility baseline

Pinned starting target `main`: `4681d747c05be4d98fc716c233b466dd0ddae3bc`.

- `OrderDetail.date` is already a canonical Gregorian `DateField`, while `time`, `end_time` and `occupied_until` are separately stored wall-clock `TimeField` values. They do **not** store an IANA timezone or a UTC timestamp.
- Django `USE_TZ=True` and `TIME_ZONE="Asia/Tehran"` still govern existing booking methods and Celery schedule defaults. Changing the runtime zone at this step is forbidden because existing appointment instants and local dates would be reinterpreted.
- `SalonOpeningHours.day_of_week` persists **Saturday=1 through Friday=7**, and cannot be renumbered silently. Phase 6 owns that migration.
- Instant-based timestamps such as `Order.reminder_due_at` and `OrderDetail.no_show_dispute_until` use timezone-aware `DateTimeField` semantics.
- `PHASE5_TIME_SEMANTICS_INVENTORY.json` contains the field and scheduled-job classification based on current source evidence.

## Implemented, opt-in boundaries

1. `loomera.globalization.calendar_time` contains canonical Gregorian date adapters: explicit `gregorian` or `jalali` input/output, strict validation, optional deployed calendar setting, and normalization of Arabic/Persian numerals. Output uses stable `YYYY-MM-DD` or `YYYY/MM/DD` ASCII-numeral representation. **The existing calendar UI and datepicker are not switched here.** Calendar choice is never inferred from language.
2. `Salon.timezone_name` is an optional `CharField(max_length=64, blank=True, default="")` with a validator against Python `zoneinfo` IANA identifiers. A migration adds only this column (no data copying or `RunPython`); the Django admin shows it for review. Existing rows remain blank and preserve their historical Tehran meaning, independently of `LOOMERA_DEFAULT_TIMEZONE`. A non-empty invalid value raises an error rather than silently falling back. Explicit timezone metadata **does not yet alter booking rules**.
3. Read-only strict `get_business_timezone`, `business_local_to_utc`, and `utc_to_business_local` make IANA interpretation explicit. DST gaps and overlaps fail closed: business-local times that map to zero or multiple UTC instants are rejected. This is a boundary for future gated integration, not an active booking flow change.
4. `python manage.py audit_calendar_timezone --json` reports aggregate counts of legacy/explicit/invalid zones and appointment-date/time coverage without writing data or exposing business IDs. `--fail-on-invalid` fails on invalid explicit IANA zone values. Run it on authorized data snapshots before any cutover.
5. Django tests cover Gregorian/Jalali round trips, locale-independent calendar selection, IANA validation, winter/summer offsets, DST gaps/folds, original appointment field equality when the salon timezone metadata changes, migration shape and read-only audit behavior.

## Scheduled work classifications

- **Deployment-local:** scheduler bundle's `timezone.localdate()` daily metrics and configured Celery beat timezone (`Asia/Tehran`). These are not business-local schedules.
- **Instant-based:** reminder dispatch checks `reminder_due_at <= timezone.now()`; no-show expiry checks `no_show_dispute_until <= timezone.now()`; story expiry, abandoned checkouts and operational-data cleanup use instant-based `timezone.now()` cutoffs.
- **Business wall-clock still legacy:** opening-hours windows, booking selection and day-of-week indexing. No refactor in this batch.

## Release and migration controls

This PR **must not** set the new timezone field for existing salons automatically, recalculate date/time columns, change `TIME_ZONE` or `CELERY_TIMEZONE`, change booking cancellation/reminder formulas, mutate persisted weekdays, or presume a DST resolution policy. A timezone field value is metadata, not proof of a converted booking timeline.

Before a future Phase 5.2 active booking integration or production migration, require an authorized full-data profile (including missing dates/times, out-of-hours/overnight bookings and DST gaps/folds), paired before/after fixtures and UTC-instant reconciliation, explicit onboarding/default-timezone policy, reversal/runbook, reminder/no-show/ICS acceptance, and human review for ambiguous wall-clock records. Automatic zone assignment from language, address or map provider is forbidden.

Phase 3 manual browser/true 400% zoom, keyboard and screen-reader gates remain **BLOCKED_MANUAL_ACCEPTANCE**; Production deployment remains **NOT_PERFORMED**.

## Merge gates

- `makemigrations --check --dry-run` and migration-system tests must pass.
- Phase 5.1 Django boundary, audit and persisted-order tests pass in GitHub CI.
- Existing financial, authorization, booking and Chromium smoke regressions stay green.
- Review exact changed-file list; confirm the migration is a single `AddField` and no existing time fields or business logic changed.
- SHA-guarded squash merge only after exact-head CI success, followed by post-merge `main` CI verification.
