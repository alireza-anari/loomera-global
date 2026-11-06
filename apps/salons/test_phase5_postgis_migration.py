"""Phase 5.2: actual spatial PostgreSQL migration rollback/forward rehearsal.

Run ONLY against an ephemeral, isolated PostGIS CI test database.
No production data is used. Django's test runner creates the database.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone as std_utc
from io import StringIO
import json

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import CustomUser, Customer, SalonManager, Stylist
from apps.orders.models import Order, OrderDetail
from apps.salons.models import Salon, SalonOpeningHours
from apps.services.models import Services

OLD = ("salons", "0005_salon_city_zone_label")
NEW = ("salons", "0006_salon_timezone_name")


class Phase5PostGISMigrationRehearsal(TransactionTestCase):
    """No simulated SQL backend: a real GeoDjango schema and SQL transitions."""

    def _column_present(self) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS(
                  SELECT 1 FROM information_schema.columns
                  WHERE table_name = %s AND column_name = %s
                )
                """,
                [Salon._meta.db_table, "timezone_name"],
            )
            return bool(cursor.fetchone()[0])

    def _snapshot(self, detail_id):
        # Existing persisted snapshots and foreign keys must survive the migration.
        record = OrderDetail.objects.get(pk=detail_id)
        return {
            "detail_id": record.id,
            "date": record.date,
            "time": record.time,
            "end_time": record.end_time,
            "occupied_until": record.occupied_until,
            "duration": record.scheduled_duration_minutes,
            "buffer": record.buffer_minutes,
            "salon_id": record.salon_id,
            "order_id": record.order_id,
            "service_id": record.service_id,
            "stylist_id": record.stylist_id,
        }

    def _fixture(self):
        def user(n):
            return CustomUser.objects.create(
                mobile_number=n, name="Phase5", family="Fixture", is_active=True
            )

        manager = SalonManager.objects.create(
            user=user("09128887711"), is_active=True
        )
        salon = Salon.objects.create(
            salon_name="Ephemeral PostGIS salon",
            salon_manager=manager,
            is_active=True,
            timezone_name="",
        )
        customer = Customer.objects.create(user=user("09128887712"))
        stylist = Stylist.objects.create(
            user=user("09128887713"), is_active=True, expert="Test"
        )
        service = Services.objects.create(
            service_name="Ephemeral Phase5 service",
            slug="phase5-postgis-service",
            is_active=True,
            is_platform_catalog=True,
            duration_minutes=60,
            base_price=100000,
        )
        order = Order.objects.create(
            customer=customer,
            salon=salon,
            status="confirmed",
            is_finally=True,
            total_amount=100000,
            reminder_due_at=datetime(
                2026, 7, 15, 6, tzinfo=std_utc.utc
            ),
        )
        detail = OrderDetail.objects.create(
            order=order,
            salon=salon,
            stylist=stylist,
            service=service,
            price=100000,
            date=date(2026, 7, 15),
            time=time(10, 15),
            end_time=time(11, 15),
            occupied_until=time(11, 25),
            scheduled_duration_minutes=60,
            buffer_minutes=10,
        )
        hours = SalonOpeningHours.objects.create(
            salon=salon,
            day_of_week=1,
            open_time=time(9),
            close_time=time(18),
            is_closed=False,
        )
        return salon, order, detail, hours

    def test_real_postgis_schema_downgrade_and_forward_preserve_appointment(self):
        if not connection.settings_dict["ENGINE"].endswith(".postgis"):
            self.fail("PostGIS integration test must run on spatial PostgreSQL")
        with connection.cursor() as cursor:
            cursor.execute("SELECT PostGIS_Version()")
            version = cursor.fetchone()[0]
        self.assertTrue(version)
        self.assertTrue(self._column_present())

        salon, order, detail, hours = self._fixture()
        before = self._snapshot(detail.pk)
        before_reminder = Order.objects.get(pk=order.pk).reminder_due_at
        before_hours = list(
            SalonOpeningHours.objects.filter(pk=hours.pk)
            .values_list("day_of_week", "open_time", "close_time")
        )
        self.assertEqual(salon.timezone_name, "")

        # Exercise database backwards + forwards migration on the isolated
        # spatial database, not merely static AddField introspection.
        try:
            MigrationExecutor(connection).migrate([OLD])
            self.assertFalse(self._column_present())
            self.assertEqual(self._snapshot(detail.pk), before)
            MigrationExecutor(connection).migrate([NEW])
            self.assertTrue(self._column_present())
            self.assertEqual(self._snapshot(detail.pk), before)
            salon.refresh_from_db()
            self.assertEqual(salon.timezone_name, "")
            self.assertEqual(
                Order.objects.get(pk=order.pk).reminder_due_at,
                before_reminder,
            )
            self.assertEqual(
                list(SalonOpeningHours.objects.filter(pk=hours.pk)
                     .values_list("day_of_week", "open_time", "close_time")),
                before_hours,
            )

            # The proposed timezone must remain metadata, not a rewrite of the
            # already-booked 10:15 wall clock or its stored UTC reminder.
            salon.timezone_name = "Europe/Berlin"
            salon.save(update_fields=["timezone_name"])
            self.assertEqual(self._snapshot(detail.pk), before)
            self.assertEqual(
                Order.objects.get(pk=order.pk).reminder_due_at,
                before_reminder,
            )

            with CaptureQueriesContext(connection) as read_log:
                audit_output = StringIO()
                call_command(
                    "audit_phase5_timezone_cutover", "--json",
                    "--max-appointments", "20",
                    stdout=audit_output,
                )
            report = json.loads(audit_output.getvalue().strip())
            self.assertEqual(report["appointments_examined"], 1)
            self.assertTrue(report["scan_complete"])
            self.assertEqual(report["classifications"]["explicit_zone_shift"], 1)
            self.assertTrue(report["human_review_required"])
            self.assertFalse(report["cutover_authorized"])
            self.assertEqual(report["writes_performed"], 0)
            self.assertNotIn("Ephemeral PostGIS salon", audit_output.getvalue())
            self.assertNotIn("09128887711", audit_output.getvalue())
            for query in read_log:
                sql = query["sql"].lstrip().upper()
                # Django's PostgreSQL iterator uses server-side cursors:
                # DECLARE .. FOR SELECT, FETCH and CLOSE are read-only.
                self.assertTrue(
                    sql.startswith("SELECT")
                    or (sql.startswith("DECLARE ") and " FOR SELECT " in sql)
                    or sql.startswith("FETCH ")
                    or sql.startswith("CLOSE "),
                    query["sql"][:140],
                )
        finally:
            # Keep the ephemeral test DB on the latest migration even if an
            # assertion above fails; never hide the original failure.
            MigrationExecutor(connection).migrate([NEW])
