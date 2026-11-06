"""Phase 5.2 read-only date/time cutover risk checks, without spatial DB."""
from __future__ import annotations

from datetime import date, time
from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from loomera.globalization.timezone_rehearsal import inspect_appointment_wall_clock
from apps.salons.management.commands import audit_phase5_timezone_cutover as audit


class TimezoneCutoverClassifierTests(SimpleTestCase):
    def test_unset_timezone_keeps_tehran_meaning(self):
        result = inspect_appointment_wall_clock(date(2026, 6, 1), time(10), time(11), "")
        self.assertEqual(result.classification, "legacy_tehran")
        self.assertEqual(result.utc_delta_minutes, 0)
        self.assertFalse(result.overnight_or_zero_duration)

    def test_explicit_berlin_winter_and_summer_propose_different_utc_shifts(self):
        winter = inspect_appointment_wall_clock(
            date(2026, 1, 15), time(10), time(11), "Europe/Berlin"
        )
        summer = inspect_appointment_wall_clock(
            date(2026, 7, 15), time(10), time(11), "Europe/Berlin"
        )
        self.assertEqual(winter.classification, "explicit_zone_shift")
        self.assertEqual(winter.utc_delta_minutes, 150)
        self.assertEqual(summer.classification, "explicit_zone_shift")
        self.assertEqual(summer.utc_delta_minutes, 90)

    def test_explicit_same_zone_keeps_instant(self):
        result = inspect_appointment_wall_clock(
            date(2026, 6, 1), time(10), time(11), "Asia/Tehran"
        )
        self.assertEqual(result.classification, "explicit_zone_same_instant")
        self.assertEqual(result.utc_delta_minutes, 0)

    def test_candidate_dst_gap_and_overlap_require_human_policy(self):
        gap = inspect_appointment_wall_clock(
            date(2026, 3, 29), time(2, 30), time(3, 30), "Europe/Berlin"
        )
        overlap = inspect_appointment_wall_clock(
            date(2026, 10, 25), time(2, 30), time(3, 30), "Europe/Berlin"
        )
        self.assertEqual(gap.classification, "candidate_dst_gap")
        self.assertEqual(overlap.classification, "candidate_dst_overlap")

    def test_missing_fields_invalid_zone_and_overnight_are_reported_not_rewritten(self):
        self.assertEqual(
            inspect_appointment_wall_clock(None, time(8), time(9), ""),
            inspect_appointment_wall_clock(date(2026, 1, 1), None, time(9), ""),
        )
        self.assertEqual(
            inspect_appointment_wall_clock(
                date(2026, 1, 1), time(8), time(9), "Invalid/Timezone"
            ).classification, "invalid_iana_zone"
        )
        for end in (time(8), time(7)):
            with self.subTest(end=end):
                result = inspect_appointment_wall_clock(
                    date(2026, 1, 1), time(8), end, ""
                )
                self.assertTrue(result.overnight_or_zero_duration)

    def test_legacy_dst_overlap_is_not_treated_as_a_unique_instant(self):
        # Tehran historically observed DST; an overlap can exist for older dates.
        record = inspect_appointment_wall_clock(
            date(2021, 9, 21), time(23, 30), time(23, 45), ""
        )
        self.assertIn(
            record.classification,
            ("legacy_tehran", "legacy_dst_gap", "legacy_dst_overlap"),
        )
        # No assumption that a timezone label resolves a non-unique instant.

    def test_finite_scan_and_delta_summary(self):
        rows = [
            (date(2026, 6, 1), time(10), time(11), ""),
            (date(2026, 7, 15), time(10), time(11), "Europe/Berlin"),
            (date(2026, 3, 29), time(2, 30), time(3, 30), "Europe/Berlin"),
            (date(2026, 6, 1), time(10), time(9), ""),
        ]
        report = audit.audit_appointments(iter(rows), max_appointments=4)
        self.assertEqual(report["appointments_examined"], 4)
        self.assertTrue(report["scan_complete"])
        self.assertEqual(report["classifications"]["legacy_tehran"], 2)
        self.assertEqual(report["classifications"]["explicit_zone_shift"], 1)
        self.assertEqual(report["classifications"]["candidate_dst_gap"], 1)
        self.assertEqual(report["overnight_or_zero_duration_count"], 1)
        self.assertEqual(report["largest_candidate_utc_shift_minutes"], 90)
        self.assertTrue(report["human_review_required"])
        self.assertFalse(report["cutover_authorized"])
        self.assertEqual(report["writes_performed"], 0)
        truncated = audit.audit_appointments(iter(rows), max_appointments=2)
        self.assertEqual(truncated["appointments_examined"], 2)
        self.assertFalse(truncated["scan_complete"])
        self.assertTrue(truncated["human_review_required"])

    def test_cli_uses_only_reads_and_never_exposes_identifiers(self):
        qs = MagicMock()
        qs.iterator.return_value = iter([
            (date(2026, 6, 1), time(10), time(11), ""),
        ])
        manager = MagicMock()
        manager.order_by.return_value.values_list.return_value.__getitem__.return_value = qs
        output = StringIO()
        with patch.object(audit, "OrderDetail", SimpleNamespace(objects=manager)):
            audit.Command(stdout=output).handle(
                json=True, max_appointments=10, fail_on_risk=False
            )
        result = json.loads(output.getvalue())
        self.assertEqual(result["appointments_examined"], 1)
        self.assertFalse(result["human_review_required"])
        self.assertEqual(result["scan_limit"], 10)
        self.assertNotIn("customer", output.getvalue())
        manager.create.assert_not_called()
        manager.update.assert_not_called()
        manager.delete.assert_not_called()
        qs.iterator.assert_called_once_with(chunk_size=500)

    def test_cli_fail_on_risk_and_reject_invalid_limit(self):
        q = MagicMock()
        q.iterator.return_value = iter([
            (date(2026, 6, 1), time(10), time(11), "Europe/Berlin"),
        ])
        mgr = MagicMock()
        mgr.order_by.return_value.values_list.return_value.__getitem__.return_value = q
        with patch.object(audit, "OrderDetail", SimpleNamespace(objects=mgr)):
            with self.assertRaises(CommandError):
                audit.Command(stdout=StringIO()).handle(
                    json=True, max_appointments=10, fail_on_risk=True
                )
        with self.assertRaises(CommandError):
            audit.Command(stdout=StringIO()).handle(
                json=True, max_appointments=0, fail_on_risk=False
            )
        with self.assertRaises(CommandError):
            audit.Command(stdout=StringIO()).handle(
                json=True, max_appointments=50001, fail_on_risk=False
            )
