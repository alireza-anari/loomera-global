"""Phase 5.1: canonical calendar adapters and non-destructive IANA timezone seam."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import migrations
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import translation

from apps.salons.models import Salon
from loomera.globalization.calendar_time import (
    LEGACY_BOOKING_TIMEZONE,
    AmbiguousBusinessTimeError,
    CalendarDateError,
    NonexistentBusinessTimeError,
    business_local_to_utc,
    calendar_date_parts,
    format_calendar_date,
    get_business_timezone,
    parse_calendar_date,
    resolve_calendar,
    utc_to_business_local,
    validate_iana_timezone_name,
)

ROOT = Path(__file__).resolve().parents[2]


class Phase5CalendarBoundaryTests(SimpleTestCase):
    def test_one_canonical_date_round_trips_between_gregorian_and_jalali(self):
        day = date(2024, 3, 20)
        self.assertEqual(calendar_date_parts(day, calendar="gregorian"), (2024, 3, 20))
        self.assertEqual(calendar_date_parts(day, calendar="jalali"), (1403, 1, 1))
        self.assertEqual(format_calendar_date(day, calendar="gregorian"), "2024-03-20")
        self.assertEqual(format_calendar_date(day, calendar="jalali"), "1403-01-01")
        self.assertEqual(
            parse_calendar_date("۱۴۰۳/۰۱/۰۱", calendar="jalali"), day
        )
        self.assertEqual(
            parse_calendar_date("٢٠٢٤/٠٣/٢٠", calendar="gregorian"), day
        )
        self.assertEqual(
            parse_calendar_date("2024-03-20", calendar="gregorian"), day
        )

    def test_default_calendar_uses_config_not_request_language(self):
        day = date(2024, 3, 20)
        with override_settings(LOOMERA_DEFAULT_CALENDAR="gregorian"):
            for language in ("fa", "en", "ar"):
                with translation.override(language):
                    self.assertEqual(resolve_calendar(), "gregorian")
                    self.assertEqual(format_calendar_date(day), "2024-03-20")
        with override_settings(LOOMERA_DEFAULT_CALENDAR="jalali"):
            with translation.override("en"):
                self.assertEqual(resolve_calendar(), "jalali")
                self.assertEqual(format_calendar_date(day), "1403-01-01")

    def test_calendar_input_validation_never_guesses_calendar(self):
        for invalid, calendar in (
            ("2025-02-29", "gregorian"),
            ("1403-13-01", "jalali"),
            ("2024/03-20", "gregorian"),
            ("2024-03-20 extra", "gregorian"),
            (" 2024-03-20", "gregorian"),
            ("", "gregorian"),
            ("2024-00-10", "gregorian"),
        ):
            with self.subTest(value=invalid, calendar=calendar):
                with self.assertRaises(CalendarDateError):
                    parse_calendar_date(invalid, calendar=calendar)
        with self.assertRaises(ValueError):
            resolve_calendar("auto")
        with self.assertRaises(ValueError):
            resolve_calendar("persian")
        with self.assertRaises(ValueError):
            format_calendar_date(date(2024, 3, 20), separator="*")
        with self.assertRaises(TypeError):
            calendar_date_parts(datetime(2024, 3, 20))

    def test_explicit_valid_timezone_and_invalid_timezone_validation(self):
        for valid in ("Europe/Berlin", "Asia/Tehran", "UTC", "America/New_York"):
            with self.subTest(tz=valid):
                validate_iana_timezone_name(valid)
                self.assertEqual(
                    get_business_timezone(SimpleNamespace(timezone_name=valid)).key,
                    valid,
                )
        for invalid in ("", "Berlin", "Invalid/BusinessZone", " Europe/Berlin", "UTC "):
            with self.subTest(tz=invalid):
                with self.assertRaises(ValidationError):
                    validate_iana_timezone_name(invalid)
        with self.assertRaises(ValidationError):
            get_business_timezone(SimpleNamespace(timezone_name="Invalid/BusinessZone"))

    def test_blank_legacy_business_is_pinned_to_tehran_even_on_global_installation(self):
        self.assertEqual(LEGACY_BOOKING_TIMEZONE, "Asia/Tehran")
        with override_settings(LOOMERA_DEFAULT_TIMEZONE="America/New_York"):
            self.assertEqual(
                get_business_timezone(SimpleNamespace(timezone_name="")).key,
                "Asia/Tehran",
            )
            self.assertEqual(get_business_timezone(SimpleNamespace()).key, "Asia/Tehran")
            instant = business_local_to_utc(
                date(2026, 6, 1),
                time(12, 0),
                SimpleNamespace(timezone_name=""),
            )
            self.assertEqual(instant, datetime(2026, 6, 1, 8, 30, tzinfo=timezone.utc))

    def test_berlin_winter_and_summer_local_times_preserve_utc_instants(self):
        berlin = SimpleNamespace(timezone_name="Europe/Berlin")
        winter = business_local_to_utc(date(2026, 1, 15), time(9), berlin)
        summer = business_local_to_utc(date(2026, 7, 15), time(9), berlin)
        self.assertEqual(winter, datetime(2026, 1, 15, 8, tzinfo=timezone.utc))
        self.assertEqual(summer, datetime(2026, 7, 15, 7, tzinfo=timezone.utc))
        for expected in (winter, summer):
            with self.subTest(date=expected.date()):
                self.assertEqual(
                    utc_to_business_local(expected, berlin).hour, 9
                )

    def test_dst_gap_and_overlap_fail_closed_instead_of_guessing_fold(self):
        berlin = SimpleNamespace(timezone_name="Europe/Berlin")
        with self.assertRaises(NonexistentBusinessTimeError):
            business_local_to_utc(date(2026, 3, 29), time(2, 30), berlin)
        with self.assertRaises(AmbiguousBusinessTimeError):
            business_local_to_utc(date(2026, 10, 25), time(2, 30), berlin)
        self.assertEqual(
            business_local_to_utc(date(2026, 10, 25), time(3, 30), berlin),
            datetime(2026, 10, 25, 2, 30, tzinfo=timezone.utc),
        )

    def test_naive_instants_and_aware_wall_time_cannot_cross_boundary(self):
        berlin = SimpleNamespace(timezone_name="Europe/Berlin")
        with self.assertRaises(TypeError):
            utc_to_business_local(datetime(2026, 1, 1, 10), berlin)
        with self.assertRaises(TypeError):
            business_local_to_utc(
                date(2026, 1, 1), time(10, tzinfo=ZoneInfo("UTC")), berlin
            )
        with self.assertRaises(TypeError):
            business_local_to_utc(datetime(2026, 1, 1, 10), time(10), berlin)

    def test_schema_change_is_additive_and_does_not_transform_any_appointments(self):
        migration = import_module("apps.salons.migrations.0006_salon_timezone_name")
        operations = migration.Migration.operations
        self.assertEqual(migration.Migration.dependencies, [
            ("salons", "0005_salon_city_zone_label"),
        ])
        self.assertEqual(len(operations), 1)
        self.assertIsInstance(operations[0], migrations.AddField)
        self.assertEqual(operations[0].model_name, "salon")
        self.assertEqual(operations[0].name, "timezone_name")
        self.assertEqual(operations[0].field.default, "")
        self.assertTrue(operations[0].field.blank)
        field = Salon._meta.get_field("timezone_name")
        self.assertEqual(field.max_length, 64)
        self.assertEqual(field.default, "")
        self.assertIn(validate_iana_timezone_name, field.validators)

    def test_legacy_booking_methods_still_use_existing_timezone_until_cutover(self):
        source = (ROOT / "apps/orders/models.py").read_text(encoding="utf-8")
        self.assertIn("timezone.get_current_timezone()", source)
        self.assertNotIn("get_business_timezone(", source)
        self.assertNotIn("business_local_to_utc(", source)
        config = (ROOT / "loomera/settings/base.py").read_text(encoding="utf-8")
        self.assertIn('TIME_ZONE = "Asia/Tehran"', config)
        self.assertIn("USE_TZ = True", config)


class Phase5AppointmentNoRewriteTests(TestCase):
    def test_optional_timezone_update_preserves_existing_date_time_and_booking_keys(self):
        from apps.accounts.models import CustomUser, Customer, SalonManager, Stylist
        from apps.orders.models import Order, OrderDetail
        from apps.services.models import Services

        def user(number):
            return CustomUser.objects.create(
                mobile_number=number, name="Test", family="Customer", is_active=True
            )

        manager = SalonManager.objects.create(
            user=user("09125008871"), is_active=True
        )
        salon = Salon.objects.create(
            salon_name="Legacy venue", salon_manager=manager, is_active=True
        )
        customer = Customer.objects.create(user=user("09125008872"))
        stylist = Stylist.objects.create(
            user=user("09125008873"), is_active=True, expert="Test"
        )
        service = Services.objects.create(
            service_name="Existing service",
            slug="phase5-existing-service",
            is_active=True,
            is_platform_catalog=True,
            duration_minutes=30,
            base_price=100000,
        )
        order = Order.objects.create(
            customer=customer,
            salon=salon,
            status="confirmed",
            is_finally=True,
            total_amount=100000,
        )
        detail = OrderDetail.objects.create(
            order=order,
            salon=salon,
            stylist=stylist,
            service=service,
            price=100000,
            date=date(2026, 6, 1),
            time=time(10, 15),
            end_time=time(10, 45),
        )
        original = (
            detail.pk, detail.date, detail.time, detail.end_time,
            detail.order_id, detail.salon_id,
        )
        self.assertEqual(salon.timezone_name, "")
        self.assertEqual(get_business_timezone(salon).key, "Asia/Tehran")
        salon.timezone_name = "Europe/Berlin"
        salon.full_clean(exclude=["slug"])
        salon.save(update_fields=["timezone_name"])
        detail.refresh_from_db()
        salon.refresh_from_db()
        self.assertEqual(
            (
                detail.pk, detail.date, detail.time, detail.end_time,
                detail.order_id, detail.salon_id,
            ),
            original,
        )
        self.assertEqual(salon.timezone_name, "Europe/Berlin")
        self.assertEqual(get_business_timezone(salon).key, "Europe/Berlin")


class Phase5ReadOnlyAuditTests(TestCase):
    def setUp(self):
        from apps.accounts.models import CustomUser, SalonManager

        manager = SalonManager.objects.create(
            user=CustomUser.objects.create(
                mobile_number="09125008884", name="Audit", family="Manager", is_active=True
            ),
            is_active=True,
        )
        self.salon = Salon.objects.create(
            salon_name="Audit fixture", salon_manager=manager, is_active=True
        )

    def test_audit_is_aggregate_only_and_never_writes_salon_records(self):
        import json
        from io import StringIO
        from django.core.management import call_command

        before = (self.salon.timezone_name, self.salon.pk)
        output = StringIO()
        call_command("audit_calendar_timezone", "--json", stdout=output)
        report = json.loads(output.getvalue().strip())
        self.assertEqual(report["salons_total"], 1)
        self.assertEqual(report["salons_legacy_unset_timezone"], 1)
        self.assertEqual(report["salons_with_explicit_timezone"], 0)
        self.assertEqual(report["appointments_total"], 0)
        self.assertEqual(report["appointments_missing_date_or_time"], 0)
        self.assertEqual(report["invalid_explicit_timezone_count"], 0)
        self.assertEqual(report["writes_performed"], 0)
        self.salon.refresh_from_db()
        self.assertEqual((self.salon.timezone_name, self.salon.pk), before)
        self.assertNotIn("09125008884", output.getvalue())

        self.salon.timezone_name = "Europe/Berlin"
        self.salon.save(update_fields=["timezone_name"])
        output = StringIO()
        call_command("audit_calendar_timezone", "--json", stdout=output)
        report = json.loads(output.getvalue().strip())
        self.assertEqual(report["salons_legacy_unset_timezone"], 0)
        self.assertEqual(report["salons_with_explicit_timezone"], 1)
        self.assertEqual(report["explicit_timezones_distinct"], 1)

    def test_audit_flags_bad_zone_inserted_bypassing_form_validation(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError

        Salon.objects.filter(pk=self.salon.pk).update(timezone_name="Not/ARealZone")
        with self.assertRaises(CommandError):
            call_command(
                "audit_calendar_timezone", "--json", "--fail-on-invalid",
                stdout=StringIO(),
            )
        self.salon.refresh_from_db()
        self.assertEqual(self.salon.timezone_name, "Not/ARealZone")
