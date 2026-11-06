# Phase 6.2 — Dashboard/API and JavaScript weekday contracts

**Status:** implementation and regression tests for remaining identified manager
day lookups, **not** a persisted-weekday migration or Production approval.

Pinned base: `b891b981289150ef878ca754c49001f1abba6021` (Phase
6.1 merged; post-merge CI `42189229126` passed all three jobs).

## Important: three different weekday identities must remain distinct

| Interface | Identity | Example: Saturday | Persistence |
| --- | --- | --- | --- |
| `SalonOpeningHours.day_of_week` | legacy Saturday=1..Friday=7 | `1` | **Persisted** |
| Regular shift form `day-{i}-shifts` | Saturday-first zero-based 0..6 | `day-0-shifts` | Request form key only |
| Python `date.isoweekday()` | ISO Monday=1..Sunday=7 | `6` | Canonical conversion input only |
| Python `date.weekday()` | Monday=0..Sunday=6 | `5` | Framework convention only |
| JavaScript `Date.getDay()` | Sunday=0..Saturday=6 | `6` | Display-only in manual booking |
| Jalali `jdatetime.date.weekday()` | Saturday-first 0..6 | `0` | Jalali week/display only |

**Never** feed a JavaScript, ISO or zero-based form index into the stored
`SalonOpeningHours` field without explicit conversion. A calendar's
presentation week start can vary independently of appointment date identity.

## Verified source interfaces and Phase 6.2 changes

- **Calendar manager API**: `apps/dashboards/views.py:get_calendar_data`
  (route `dashboards:api_get_calendar_data`) checks the same stored opening
  day and returns unchanged `salonIsOpen`/`appointments` response keys.
  A seven-date RequestFactory+mock regression verifies closed-day payload
  and mapping without running private or production data queries.
- **Manager day shift editing**: `EditStylistDayScheduleView` and
  `AddTimeOffView` (hours lookup and option generation) now call
  `legacy_opening_day_from_date`. Mocked queryset regressions cover all
  seven days, including closed/absent day lookups.
- **Regular shifts**: `SetRegularShiftsView` POST keeps
  `day-0-shifts`.. `day-6-shifts`, the 0-based Saturday-first contract.
  Its future-booking collision check and shift-creation loop now use the
  explicit `saturday_first_form_index_from_date` compatibility helper,
  rather than reimplementing the old arithmetic. Its day-card indexes,
  validation ranges, and opening-hours map remain untouched.
- **Onboarding**: `SalonProfileCreatorStep3View`,
  `SalonOpeningHoursForm.days`, and
  `templates/dashboards/salon_profile_creator_step3.html` still use
  `day_1_*..`day_7_*` for **persisted** identities.
- **JavaScript**: `static/js/pages/set_regular_shifts.js` reads each
  rendered hidden `day-{index}-shifts` field and writes comma-delimited
  time windows without remapping its name. Node regression guards this,
  plus the seven-day onboarding template contract.
  `static/js/pages/manual_booking.js` uses JS Sunday-first `getDay()`
  for a label; it does **not** send that value as stored opening-day ID.
  `static/js/pages/edit_day_schedule.js` formats a Gregorian date as
  Jalali with `Intl.DateTimeFormat`, not a persisted weekday value.
- **Other weekday consumers reviewed**:
  `apps/dashboards/views.py:ScheduledShiftsView` uses
  `jdatetime.date.weekday()` to generate a Saturday-first Jalali display
  week; `apps/dashboards/jalali_utils.py` uses Python weekday to select
  names. Neither is a database identifier.
  `apps/salons/views.py` sorts `SalonOpeningHours` by stored key.
  `apps/dashboards/layout.py`, `appointment_management.py`,
  `apps/orders/booking_utils.py` and
  `apps/stylists/dashboard_services.py` were converted in Phase 6.1.

## Regression and release limits

The no-spatial-DB suite includes 1,461 consecutive dates (all seven days,
leap day), actual manager calendar JSON output for closed days, valid/invalid
route inputs, mocked schedule and time-off ORM filters, regular-shift card
indexes and onboarding field identifiers. Node tests guard template-to-JS
field serialization. These are targeted automated interface tests, **not**
a complete authenticated browser E2E, full representative DB rehearsal,
or proof that every dynamically generated UI consumer has been enumerated.

No `SalonOpeningHours.day_of_week` migration, fixture rewrite, API payload
rename, week-start change, business-timezone activation, booking/notification/
ICS timing adjustment, payment change, or Production/staging deployment.
The default legacy map `JALALI_WEEKDAY_MAP` remains available for
backward compatibility. Business data must not be auto-reinterpreted.

**Still blocked:** approved canonical weekday migration and reversible
historical-data plan; representative authorized sanitized PostGIS snapshot,
timezone provenance and signoff from Phase 5; Phase 3 visual, keyboard,
true 400% zoom, NVDA/VoiceOver manual acceptance; Production release.
