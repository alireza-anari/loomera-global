# Phase 6.3 — Weekday source audit and reversible migration **proposal**

**State:** read-only inventory + ISO migration planning, not migration approval.
Base `80b52653c06e062a1f2ae2a3eea39c7bc162374b` (Phase 6.2 merged, all three post-merge CI jobs successful
in [run 42198333630](https://github.com/alireza-anari/loomera-global/actions/runs/42198333630)).
The historical `apps/main/phase6_closure.py` is an older local quality-audit
artifact; it is **not** this globalization Phase 6.

## Scope actually implemented

- An explicit, anchored candidate review inventory:
  `docs/globalization/PHASE6_3_WEEKDAY_CONSUMER_INVENTORY.json`.
  Targets persisted values, booking availability, manager day API, schedule
  forms, input names, display-only Jalali/week starts, JS labels/Friday styling,
  and fixtures. Anchors are validated in CI. Static scan is deliberately not
  advertised as a complete dynamic behavior proof.
- Read-only pure `preview_legacy_weekday_rows(rows)` for an **already
  authorized sanitized iterable of (salon_id, day_of_week)**, with only
  aggregate counts. Invalid day IDs, invalid salon refs, duplicate
  `(salon, day)` rows, and zero-row submissions fail the structural gate.
  Neither DB reads nor writes are provided. A clean result is **not**
  permission to migrate: snapshot provenance and owner signoff are distinct.
- `python manage.py audit_weekday_source --json` scans runtime Python,
  JavaScript and HTML source for candidate weekday references. It intentionally
  excludes tests/migrations and prints path names and counts, not raw code or
  salon records. New candidate files still require manual classification.
- The appointment planner's existing Saturday week-start is now explicitly
  `start_of_display_week(day, first_day_iso=6)`. This is a presentation
  choice only. All seven stored weekday IDs and booking/closed rules remain
  unchanged. Four years of synthetic parity (including leap days) are tested.

## Reviewed identities and consumer risks

| Semantic domain | Existing wire/owner | Phase 6.3 conclusion |
| --- | --- | --- |
| Persisted opening hours | `SalonOpeningHours.day_of_week` / `s_salon_opening_hours` | Saturday 1…Friday 7 remains authoritative |
| Public availability | `apps/orders/booking_utils.py` and indirect API v1 services | Shared legacy lookup; no API payload change |
| Manager calendar & time off | `apps/dashboards/views.py` | Seven-day lookups preserved from Phase 6.2 |
| Regular shift request | `day-0-shifts`…`day-6-shifts` | Zero-based Saturday-first form **not** a DB field |
| Onboarding & business details | `apps/salons/forms.py`, profile template, `apps/salons/views.py` | 1…7 form keys and ordered display preserved |
| Planner weekly presentation | `apps/dashboards/appointment_management.py` | Explicit Saturday presentation start, unchanged date set |
| Jalali weekly report | `ScheduledShiftsView` / `jdatetime.date.weekday()` | Saturday-first display, not stored weekday |
| Client JavaScript labels | `static/js/jalali*.js`, `pages/manual_booking.js` | `Date.getDay()` Sunday=0 for labels only |
| Booking date-strip styling | `static/js/select_datetime.js` | Friday `getDay()===5` is a **visual legacy holiday highlight**; **not** an availability block |
| Local demo fixture | `apps/main/management/commands/seed_local_demo_data.py` | Stored Saturday-first numbering; no fixture rewrite |

**Integrity finding:** the model defines no unique constraint for
`(salon, day_of_week)`. Existing duplicate days must be detected in an
authorized snapshot and reconciled with the owner; never guess which row
wins or silently deduplicate.

## Proposed canonical representation — not yet signed off

**Preferred design for review:** ISO 8601 numeric weekdays, Monday=1,
Tuesday=2, Wednesday=3, Thursday=4, Friday=5, Saturday=6, Sunday=7.
This is a *proposal* only. The current stored Saturday=1…Friday=7 field
remains unchanged; no field/SQL/data migration was added in this PR.

### Prerequisites (hard stops)

1. Obtain explicitly authorized, access-controlled *sanitized* snapshot
   with stable business/row IDs, `day_of_week`, closed flag, opening
   windows and timezone provenance. Record SHA/checksum, scope and owner;
   never submit customer/booking PII to a generic report.
2. Run aggregate preflight on rows and independently compare SQL counts.
   Fail on missing/invalid IDs, 0/8/bool weekdays, duplicate
   `(salon_id, day_of_week)` pairs, missing/ambiguous opening hours and
   unsupported business timezones. For non-empty snapshots, check all
   source records are accounted for.
3. Decide a cutover contract and versioned client expectations for
   manager HTML forms, APIs, mobile consumers, JS and fixtures.
   Authenticated consumer E2E and representative PostGIS rehearsal must
   prove no day shift, including DST and year boundaries.
4. Obtain explicit owner approval of canonical representation, a
   rollback runbook, deployment window and failure thresholds.
   Complete Phase 5 timezone provenance and Phase 3 manual access audits.

### Forward / reverse proposal (no execution)

- **Expand:** add a separate nullable `iso_weekday` field with an
  explicitly documented version marker (not this PR). Keep legacy
  `day_of_week` as the source of truth during compatibility rollout.
- **Reconcile and backfill:** in short bounded batches with checkpoints,
  fill `iso_weekday=legacy_to_iso_weekday(day_of_week)`. Ensure
  1:1 mapping, aggregate checksums/distributions, per-row version state,
  no orphan/duplicate pairs and exactly identical open/closed/date-slot
  interpretations. Stop on ANY mismatch. In-place `UPDATE` on the
  existing integer field is **not** approved.
- **Dual-read / guarded writes:** during a separately approved phase,
  compare legacy and ISO projections, preserve old form/API contracts,
  make new writes version-aware and recheck consistency under concurrent
  updates. Do not silently select the ISO value when the two disagree.
- **Cutover:** only after every consumer is compatible, signed acceptance,
  PostGIS snapshot rehearsal, backward-client strategy and operator gate.
  Contract removals and database constraints are separate PRs.
- **Rollback:** before contract removal, disable new canonical reads,
  use intact legacy column as source of truth and remove/repair only
  approved shadow data. After cutover, explicitly map ISO→legacy
  with version checks and compare every record to approved snapshot;
  never run a non-idempotent conversion twice. A rollback without
  preserved semantics and accepted backup is **not** safe.

### Evidence this PR actually provides

- 1,461-day synthetic weekday + opening/closed parity;
- 1,461-day unchanged Saturday planner start and isolated Monday/Sunday
  display preference;
- aggregate preflight for duplicates, invalid IDs and empty input;
- static anchored inventory & source candidate scanner regression;
- existing CI Chromium and synthetic PostGIS checks, plus a new Python
  regression step.

**Blocked:** no approved snapshot, real-data reconciliation, consented
data migration, full browser/screen-reader manual signoff or Production
deployment. The next step is reviewer-owned data provenance and a
release-gated decision, **not** running SQL against live booking data.
