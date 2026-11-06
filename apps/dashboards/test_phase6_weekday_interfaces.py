"""Phase 6.2: dashboard/API weekday interfaces without a spatial database."""
from __future__ import annotations

import inspect
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.dashboards import views
from apps.salons.forms import SalonOpeningHoursForm
from apps.salons.models import SalonOpeningHours
from loomera.globalization.weekdays import (
    legacy_opening_day_from_date,
    saturday_first_form_index_from_date,
)

ROOT = Path(__file__).resolve().parents[2]


class Phase6DashboardWeekdayInterfaces(SimpleTestCase):
    def test_saturday_first_form_index_matches_legacy_raw_formula_for_four_years(self):
        start = date(2020, 1, 1)
        for offset in range(1461):
            day = start + timedelta(days=offset)
            expected = (day.weekday() + 2) % 7
            self.assertEqual(saturday_first_form_index_from_date(day), expected)
            self.assertEqual(saturday_first_form_index_from_date(day) + 1,
                             legacy_opening_day_from_date(day))
        self.assertEqual(saturday_first_form_index_from_date(date(2026, 11, 7)), 0)
        self.assertEqual(saturday_first_form_index_from_date(date(2026, 11, 6)), 6)
        self.assertEqual(
            saturday_first_form_index_from_date(datetime(2026, 11, 7, 23)), 0
        )
        for invalid in (None, "2026-11-07", 1):
            with self.assertRaises(TypeError):
                saturday_first_form_index_from_date(invalid)

    def test_manager_calendar_api_preserves_closed_day_payload_for_all_weekdays(self):
        request_factory = RequestFactory()
        handler = inspect.unwrap(views.get_calendar_data)
        salon = SimpleNamespace(pk=17)
        monday = date(2026, 11, 2)
        for offset, expected in enumerate((3, 4, 5, 6, 7, 1, 2)):
            day = monday + timedelta(days=offset)
            request = request_factory.get(
                "/dashboards/api/calendar-data/salon/17/", {"date": day.isoformat()}
            )
            with (
                patch.object(views, "_redirect_to_required_onboarding",
                             return_value=None),
                patch.object(views, "get_object_or_404", return_value=salon),
                patch.object(views.SalonOpeningHours.objects, "filter") as lookup,
            ):
                lookup.return_value.first.return_value = SimpleNamespace(is_closed=True)
                response = handler(request, salon_id=17)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    json.loads(response.content),
                    {
                        "salonIsOpen": False,
                        "message": "مجموعه در این روز تعطیل است.",
                        "appointments": [],
                    },
                )
                self.assertEqual(lookup.call_args.kwargs["salon"], salon)
                self.assertEqual(
                    lookup.call_args.kwargs["day_of_week"], expected,
                    msg=f"calendar API mapping drifted on {day.isoformat()}",
                )
                lookup.return_value.first.assert_called_once_with()

    def test_calendar_api_rejects_malformed_day_without_querying_opening_hours(self):
        handler = inspect.unwrap(views.get_calendar_data)
        request = RequestFactory().get("/dashboards/api/calendar-data/salon/17/",
                                       {"date": "2026-11-07;DROP"})
        with (
            patch.object(views, "_redirect_to_required_onboarding",
                         return_value=None),
            patch.object(views.SalonOpeningHours.objects, "filter") as lookup,
        ):
            response = handler(request, salon_id=17)
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", json.loads(response.content))
        lookup.assert_not_called()

    def test_manager_day_schedule_and_time_off_lookups_still_query_stored_1_to_7(self):
        edit_view = views.EditStylistDayScheduleView()
        time_off_view = views.AddTimeOffView()
        salon = SimpleNamespace(pk=17)
        start = date(2026, 11, 2)
        for offset, expected in enumerate((3, 4, 5, 6, 7, 1, 2)):
            day = start + timedelta(days=offset)
            with patch.object(views.SalonOpeningHours.objects, "filter") as lookup:
                lookup.return_value.first.return_value = None
                self.assertIsNone(edit_view._get_salon_hours_for_day(salon, day))
                self.assertEqual(lookup.call_args.kwargs["day_of_week"], expected)
                self.assertFalse(lookup.call_args.kwargs["is_closed"])
                self.assertIsNone(time_off_view._get_salon_hours_for_day(day, salon))
                self.assertEqual(lookup.call_args.kwargs["day_of_week"], expected)
                self.assertEqual(time_off_view._get_time_options(day, salon), [])
                self.assertEqual(lookup.call_args.kwargs["day_of_week"], expected)

    def test_weekly_shift_cards_and_onboarding_fields_keep_distinct_wire_keys(self):
        opening = [
            SimpleNamespace(day_of_week=value, is_closed=(value == 7),
                            open_time=time(9), close_time=time(17))
            for value in range(1, 8)
        ]
        salon = SimpleNamespace(opening_hours=SimpleNamespace(all=lambda: opening))
        cards, open_days = views.SetRegularShiftsView()._build_day_cards(salon)
        self.assertEqual([card["index"] for card in cards], list(range(7)))
        self.assertEqual([card["label"] for card in cards],
                         list(views.PERSIAN_WEEKDAY_NAMES))
        self.assertEqual(open_days, 6)
        self.assertTrue(cards[0]["is_open"])
        self.assertFalse(cards[6]["is_open"])
        self.assertEqual(
            [identifier for identifier, _ in SalonOpeningHoursForm.days],
            list(range(1, 8)),
        )
        form = SalonOpeningHoursForm()
        for day in range(1, 8):
            for key in ("active", "open_time", "close_time"):
                self.assertIn(f"day_{day}_{key}", form.fields)

    def test_runtime_calls_are_centralized_but_legacy_wires_are_not_reinterpreted(self):
        source = (ROOT / "apps/dashboards/views.py").read_text(encoding="utf-8")
        self.assertNotIn("((date_obj.weekday() + 2) % 7) + 1", source)
        self.assertNotIn("(booking.date.weekday() + 2) % 7", source)
        self.assertNotIn("(current_date.weekday() + 2) % 7", source)
        self.assertIn("day_of_week_model = legacy_opening_day_from_date(selected_date)",
                      source)
        self.assertIn("weekday_index = saturday_first_form_index_from_date(booking.date)",
                      source)
        self.assertIn("persian_weekday_index = saturday_first_form_index_from_date(current_date)",
                      source)
        self.assertIn("JALALI_WEEKDAY_MAP = {", source)  # compatibility for existing imports
        self.assertIn("day_of_week=day_num,", source)  # persisted onboarding keys unchanged
        self.assertIn('request.POST.get(f"day-{i}-shifts")', source)
        self.assertIn("item.day_of_week - 1: item", source)
        self.assertNotIn("RunPython(", (ROOT / "loomera/globalization/weekdays.py").read_text())
