# Phase 6.1 — Weekday compatibility boundary and consumer inventory

**Status:** implementation-stage boundary, not a weekday schema migration or release approval.
Pinned original main: `2c255fa6cc376518600f4abd3a5b9927dc2f1a9c` (Phase 5.3 merged;
post-merge GitHub Actions run `42181717757` passed Fast checks, Chromium,
and synthetic PostGIS jobs). Source `alireza-anari/loomera` remains read-only.

## Why persisted weekday identity needs its own phase

`SalonOpeningHours.day_of_week` is a persisted *business identifier*:
Saturday=1, Sunday=2, Monday=3, Tuesday=4, Wednesday=5, Thursday=6,
Friday=7. Python `date.weekday()` uses Monday=0..Sunday=6, while
`date.isoweekday()` uses Monday=1..Sunday=7. Those systems must not be
interchanged with calendar UI first-day-of-week or with Jalali/Gregorian
date presentation. The model's Persian labels, `db_table`, stored values,
queries, dates and opening/closed rules remain unchanged.

## 6.1 implementation

- `loomera/globalization/weekdays.py`: bidirectional *strict* ISO/legacy
  mapping, compatibility date lookup, independent presentation-only
  ISO day ordering and display-week start. Invalid identifiers and booleans
  are rejected rather than coerced; booking date lookup retains historical
  acceptance of both `date` and `datetime`.
- Existing primary customer availability, stylist schedule/leave,
  dashboard-today opening-hours, and appointment-planner reads use the
  shared lookup, yielding the same 1..7 values as previous formulas.
- `apps/dashboards/layout.WEEKDAY_TO_OPENING_DAY` remains available and
  unchanged for callers not migrated in 6.1.
- A database-free Django regression suite verifies the seven mappings,
  1,461 consecutive days (including leap dates), unchanged model
  metadata/Persian labels, exact existing consumer parity, and
  language/calendar independence. CI runs this suite as a dedicated step.

## Consumer inventory and migration boundary

| Area | Existing evidence / owner | Phase 6.1 handling |
| --- | --- | --- |
| Stored salon opening hours | `apps/salons/models.py`, `SalonOpeningHours.DAY_CHOICES`, initial migration | **No schema or stored values changed** |
| Customer availability and booking windows | `apps/orders/booking_utils.py`, `_salon_day_key` and opening-hours filtering | Use common legacy-compatible date lookup |
| Stylist staff schedule and leave | `apps/stylists/dashboard_services.py`, `_salon_day_number` | Use common legacy-compatible date lookup |
| Dashboard current-day hours | `apps/dashboards/layout.py`, `get_today_hours_label` | Use common lookup; retain old mapping constant |
| Appointment planner opening-hour lookup | `apps/dashboards/appointment_management.py` | Use common lookup |
| Other manager forms/calendar endpoints | `apps/dashboards/views.py` (`EditStylistDayScheduleView`, `get_calendar_data`, schedule forms, API day keys) | **Not migrated**; requires endpoint-level contract tests |
| Salon details and display | `apps/salons/views.py` / `templates/pages/detail_salon.html` | **Not migrated**; values and localized labels unchanged |
| Daily/weekly reports and Jalali display | `apps/dashboards/views.py`, `apps/dashboards/jalali_utils.py` | **Not migrated**; calendar rendering is separate |
| Demo fixtures / onboarding tests | `apps/main/management/commands/seed_local_demo_data.py`, dashboard tests | **No fixture rewrite**; inventory for future compatibility checks |

This inventory is an initial, targeted source review, **not proof that every
dynamic, JavaScript or API weekday consumer has been enumerated**.
Before Phase 6.2, search the entire current tree, record all runtime
consumers, API payload expectations, JavaScript calendar boundaries and
database snapshots, then demand equivalent schedule results.

## Blocked migration and release gates

No change to `SalonOpeningHours.day_of_week` numbering, schema migration,
SQL write, reindex, week-start UI, dates, timezone, bookings, reminders,
ICS, no-show windows, payments, or Production deployment. Phase 5.3's
representative authorized dataset, historical timezone provenance,
business-zone cutover and owner signoff are still missing. Phase 3
manual browser/zoom/keyboard/screen-reader acceptance is still blocked.

A future dedicated canonical weekday migration requires an approved ISO
or named-enum decision, a *reversible* full-data transformation proposal,
before/after booking+opening-hour equivalence, backward API/JS compatibility,
representative sanitized PostGIS rehearsal and explicit owner signoff.
Do not infer permission to perform that migration from Phase 6.1 tests.
