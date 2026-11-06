"""Phase 6.1: exhaustive legacy weekday identity and read-only compatibility."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from django.utils import translation

from apps.salons.models import SalonOpeningHours
from loomera.globalization.calendar_time import parse_calendar_date
from loomera.globalization.weekdays import (
    iso_to_legacy_weekday,
    legacy_opening_day_from_date,
    legacy_to_iso_weekday,
    ordered_iso_weekdays,
    start_of_display_week,
)

ROOT = Path(__file__).resolve().parents[2]


class Phase6WeekdayBoundaryTests(SimpleTestCase):
    def test_all_seven_legacy_and_iso_day_identifiers_are_bijective(self):
        expected_legacy_to_iso = (6, 7, 1, 2, 3, 4, 5)
        for legacy_day, iso_day in enumerate(expected_legacy_to_iso, start=1):
            with self.subTest(legacy=legacy_day):
                self.assertEqual(legacy_to_iso_weekday(legacy_day), iso_day)
                self.assertEqual(iso_to_legacy_weekday(iso_day), legacy_day)
        self.assertEqual(
            [iso_to_legacy_weekday(iso) for iso in range(1, 8)],
            [3, 4, 5, 6, 7, 1, 2],
        )

    def test_actual_calendar_dates_match_saturday_first_persisted_contract(self):
        monday = date(2026, 11, 2)
        expected = (3, 4, 5, 6, 7, 1, 2)
        for offset, legacy_day in enumerate(expected):
            day = monday + timedelta(days=offset)
            with self.subTest(day=day):
                self.assertEqual(legacy_opening_day_from_date(day), legacy_day)
                self.assertEqual(legacy_to_iso_weekday(legacy_day), day.isoweekday())
        self.assertEqual(legacy_opening_day_from_date(datetime(2026, 11, 7, 23)), 1)

    def test_existing_booking_staff_and_dashboard_mapping_remain_equivalent(self):
        from apps.orders.booking_utils import _salon_day_key
        from apps.stylists.dashboard_services import _salon_day_number
        from apps.dashboards.layout import WEEKDAY_TO_OPENING_DAY
        from apps.dashboards.appointment_management import legacy_opening_day_from_date as planner_day

        self.assertEqual(WEEKDAY_TO_OPENING_DAY, {5: 1, 6: 2, 0: 3, 1: 4, 2: 5, 3: 6, 4: 7})
        base = date(2020, 1, 1)
        # Rehearse 4 years including leap days and all week rotations.
        for offset in range(1461):
            day = base + timedelta(days=offset)
            expected = ((day.weekday() + 2) % 7) + 1
            self.assertEqual(_salon_day_key(day), expected)
            self.assertEqual(_salon_day_number(day), expected)
            self.assertEqual(planner_day(day), expected)
            self.assertEqual(WEEKDAY_TO_OPENING_DAY[day.weekday()], expected)

    def test_legacy_model_choices_and_table_semantics_are_untouched(self):
        self.assertEqual(
            [value for value, _ in SalonOpeningHours.DAY_CHOICES], list(range(1, 8))
        )
        self.assertEqual(SalonOpeningHours._meta.db_table, "s_salon_opening_hours")
        self.assertEqual(
            [SalonOpeningHours(day_of_week=day).get_day_of_week_display()
             for day in range(1, 8)],
            ["شنبه", "یکشنبه", "دوشنبه", "سه شنبه", "چهارشنبه", "پنج شنبه", "جمعه"],
        )

    def test_calendar_selection_and_language_cannot_relabel_stored_weekdays(self):
        canonical = date(2024, 3, 20)
        self.assertEqual(parse_calendar_date("1403-01-01", calendar="jalali"), canonical)
        for language in ("fa", "en", "ar"):
            with self.subTest(language=language), translation.override(language):
                for selected_calendar in ("gregorian", "jalali"):
                    with override_settings(LOOMERA_DEFAULT_CALENDAR=selected_calendar):
                        self.assertEqual(legacy_opening_day_from_date(canonical), 5)

    def test_first_day_of_display_week_is_independent_of_persisted_identity(self):
        saturday = date(2026, 11, 7)
        self.assertEqual(legacy_opening_day_from_date(saturday), 1)
        self.assertEqual(ordered_iso_weekdays(first_day_iso=1), (1, 2, 3, 4, 5, 6, 7))
        self.assertEqual(ordered_iso_weekdays(first_day_iso=6), (6, 7, 1, 2, 3, 4, 5))
        self.assertEqual(ordered_iso_weekdays(first_day_iso=7), (7, 1, 2, 3, 4, 5, 6))
        self.assertEqual(start_of_display_week(saturday, first_day_iso=1), date(2026, 11, 2))
        self.assertEqual(start_of_display_week(saturday, first_day_iso=6), saturday)
        self.assertEqual(start_of_display_week(saturday, first_day_iso=7), date(2026, 11, 1))
        self.assertEqual(legacy_opening_day_from_date(saturday), 1)

    def test_invalid_days_fail_closed_instead_of_wrapping_or_coercing(self):
        for converter in (legacy_to_iso_weekday, iso_to_legacy_weekday):
            for invalid in (0, 8, -1, 99):
                with self.subTest(converter=converter.__name__, value=invalid):
                    with self.assertRaises(ValueError):
                        converter(invalid)
            for invalid in (True, False, 1.0, "1", None):
                with self.subTest(converter=converter.__name__, value=invalid):
                    with self.assertRaises(TypeError):
                        converter(invalid)
        for invalid in (0, 8):
            with self.assertRaises(ValueError):
                ordered_iso_weekdays(first_day_iso=invalid)
            with self.assertRaises(ValueError):
                start_of_display_week(date(2026, 11, 7), first_day_iso=invalid)
        for invalid in ("2026-11-07", None, 6):
            with self.assertRaises(TypeError):
                legacy_opening_day_from_date(invalid)
        with self.assertRaises(TypeError):
            start_of_display_week(datetime(2026, 11, 7))

    def test_new_boundary_neither_writes_database_nor_reinterprets_booking_clock(self):
        source = (ROOT / "loomera/globalization/weekdays.py").read_text(encoding="utf-8")
        self.assertNotIn("objects.", source)
        self.assertNotIn("timezone_name", source)
        for path in ("apps/orders/booking_utils.py",
                     "apps/stylists/dashboard_services.py",
                     "apps/dashboards/layout.py",
                     "apps/dashboards/appointment_management.py"):
            self.assertIn("legacy_opening_day_from_date(", (ROOT / path).read_text(encoding="utf-8"))
        self.assertFalse((ROOT / "apps/salons/migrations/0007_salon_weekday.py").exists())
