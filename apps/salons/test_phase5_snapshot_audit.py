"""Phase 5.3: isolated sanitized snapshot gate and aggregate scan, no DB."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import patch
import json

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.salons.management.commands.audit_phase5_snapshot import (
    SNAPSHOT_MARKER,
    SNAPSHOT_MARKER_VALUE,
    validate_isolated_snapshot_access,
)
from loomera.globalization.snapshot_audit import (
    SnapshotAuditIntegrityError,
    scan_appointment_snapshot,
)


class SnapshotAuditGateTests(SimpleTestCase):
    def _valid(self, **kwargs):
        values = {
            "engine": "django.contrib.gis.db.backends.postgis",
            "database_name": "phase5_snapshot_sanitized_local",
            "marker": SNAPSHOT_MARKER_VALUE,
            "acknowledged": True,
            "in_atomic_block": False,
        }
        values.update(kwargs)
        return values

    def test_default_environment_and_missing_user_approval_fail_closed(self):
        for changes in (
            {"marker": None},
            {"marker": "yes"},
            {"acknowledged": False},
            {"engine": "django.db.backends.sqlite3"},
            {"engine": "django.db.backends.postgresql"},
            {"database_name": "loomera"},
            {"database_name": "loomera_production"},
            {"database_name": "staging"},
            {"in_atomic_block": True},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(CommandError):
                    validate_isolated_snapshot_access(**self._valid(**changes))
        validate_isolated_snapshot_access(**self._valid())
        validate_isolated_snapshot_access(
            **self._valid(database_name="test_loomera_phase5")
        )

    def test_snapshot_marker_is_not_an_account_secret_or_cutover_approval(self):
        self.assertEqual(SNAPSHOT_MARKER, "LOOMERA_PHASE5_ISOLATED_SANITIZED_SNAPSHOT")
        self.assertEqual(SNAPSHOT_MARKER_VALUE, "I_CONFIRM_ISOLATED_SANITIZED_COPY")

    def test_command_refuses_access_before_any_database_query(self):
        from apps.salons.management.commands import audit_phase5_snapshot as module

        mocked_connection = SimpleNamespace(
            settings_dict={
                "ENGINE": "django.contrib.gis.db.backends.postgis",
                "NAME": "phase5_snapshot_sanitized",
            },
            in_atomic_block=False,
        )
        with (
            patch.object(module, "connection", mocked_connection),
            patch.dict("os.environ", {SNAPSHOT_MARKER: ""}),
        ):
            with self.assertRaises(CommandError):
                module.Command().handle(
                    acknowledge_isolated_sanitized_copy=True
                )


class SnapshotAuditAggregationTests(SimpleTestCase):
    def _rows(self):
        return [
            (10, date(2026, 1, 15), time(10), time(11), time(11, 15), "", None),
            (20, date(2026, 7, 15), time(10), time(11), time(11, 15),
             "Europe/Berlin", datetime(2026, 7, 15, 8, tzinfo=timezone.utc)),
            (30, date(2026, 3, 29), time(2, 30), time(3, 30), None,
             "Europe/Berlin", None),
            (40, date(2026, 5, 1), time(9), time(8), time(8, 30), "", None),
        ]

    def _scanner(self, rows):
        calls = []

        def page(last_pk, batch_size):
            calls.append((last_pk, batch_size))
            return [r for r in rows if r[0] > last_pk][:batch_size]

        return page, calls

    def test_complete_keyset_scan_reports_safe_aggregates_without_ids(self):
        fetch, calls = self._scanner(self._rows())
        report = scan_appointment_snapshot(
            fetch_page=fetch, total_records=4,
            max_records=10, batch_size=2,
        )
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["appointments_examined"], 4)
        self.assertEqual(report["total_appointments_in_snapshot"], 4)
        self.assertEqual(calls, [(0, 2), (20, 2)])
        self.assertEqual(report["classifications"]["legacy_tehran"], 2)
        self.assertEqual(report["classifications"]["explicit_zone_shift"], 1)
        self.assertEqual(report["classifications"]["candidate_dst_gap"], 1)
        self.assertEqual(report["largest_candidate_utc_shift_minutes"], 90)
        self.assertEqual(report["overnight_or_zero_duration_count"], 1)
        self.assertEqual(report["missing_end_time_count"], 0)
        self.assertEqual(report["missing_occupied_until_count"], 1)
        self.assertEqual(report["occupied_until_not_after_start_count"], 1)
        self.assertEqual(report["appointments_with_reminder_timestamp_count"], 1)
        self.assertEqual(report["blocking_appointment_count"], 2)
        self.assertEqual(report["potential_review_risks_count"], 4)
        self.assertFalse(report["cutover_authorized"])
        self.assertFalse(report["production_migration_authorized"])
        self.assertTrue(report["human_review_required"])
        self.assertEqual(report["writes_performed"], 0)
        output = json.dumps(report)
        for value in ("Europe/Berlin", "2026-07-15", "Phase5", "customer", "10:00"):
            self.assertNotIn(value, output)

    def test_bounded_scan_is_explicitly_incomplete(self):
        fetch, calls = self._scanner(self._rows())
        report = scan_appointment_snapshot(
            fetch_page=fetch, total_records=4,
            max_records=2, batch_size=2,
        )
        self.assertFalse(report["scan_complete"])
        self.assertEqual(report["appointments_examined"], 2)
        self.assertIn("scan_incomplete", report["review_reasons"])
        self.assertEqual(calls, [(0, 2)])
        self.assertFalse(report["cutover_authorized"])

    def test_empty_and_no_risk_scans_still_require_owner_signoff(self):
        for records in (
            [],
            [(1, date(2026, 1, 15), time(10), time(11), time(11, 15), "", None)],
        ):
            fetch, _ = self._scanner(records)
            report = scan_appointment_snapshot(
                fetch_page=fetch, total_records=len(records),
                max_records=10, batch_size=2,
            )
            self.assertTrue(report["scan_complete"])
            self.assertEqual(report["blocking_appointment_count"], 0)
            self.assertEqual(report["potential_review_risks_count"], 0)
            self.assertTrue(report["human_review_required"])
            self.assertIn(
                "historical_timezone_provenance_unverified", report["review_reasons"]
            )
            self.assertFalse(report["cutover_authorized"])

    def test_missing_time_and_end_time_are_not_hidden(self):
        rows = [
            (1, None, time(10), None, None, "", None),
            (2, date(2026, 1, 1), time(10), None, None, "", None),
        ]
        fetch, _ = self._scanner(rows)
        report = scan_appointment_snapshot(
            fetch_page=fetch, total_records=2,
            max_records=10, batch_size=1,
        )
        self.assertEqual(report["classifications"]["missing_start"], 1)
        self.assertEqual(report["missing_end_time_count"], 2)
        self.assertIn("missing_end_time", report["review_reasons"])

    def test_rejects_page_corruption_duplicates_and_missing_rows(self):
        valid = self._rows()[0]
        for rows in (
            [],
            [(0, *valid[1:])],
            [(10, *valid[1:]), (10, *valid[1:])],
            [(10, date(2026, 1, 15), time(10))],
        ):
            with self.subTest(rows=rows):
                def fetch(last_pk, size, rows=rows):
                    return rows[:size]
                with self.assertRaises(SnapshotAuditIntegrityError):
                    scan_appointment_snapshot(
                        fetch_page=fetch, total_records=2,
                        max_records=10, batch_size=2,
                    )

    def test_rejects_excess_page_size_and_invalid_limits(self):
        fetch, _ = self._scanner(self._rows())
        for max_records, batch_size, total in (
            (0, 2, 4), (1_000_001, 2, 4),
            (10, 0, 4), (10, 5001, 4), (10, 2, -1),
            (True, 2, 4), (10, True, 4),
        ):
            with self.subTest(max_records=max_records, batch_size=batch_size, total=total):
                with self.assertRaises(ValueError):
                    scan_appointment_snapshot(
                        fetch_page=fetch, total_records=total,
                        max_records=max_records, batch_size=batch_size,
                    )
        with self.assertRaises(SnapshotAuditIntegrityError):
            scan_appointment_snapshot(
                fetch_page=lambda last, n: self._rows()[:n+1],
                total_records=4, max_records=10, batch_size=1,
            )
