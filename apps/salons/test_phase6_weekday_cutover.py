"""Phase 6.4: offline weekday shadow parity, provenance gates and rollback stops."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.salons.management.commands import audit_weekday_cutover_files as audit
from loomera.globalization.weekday_cutover_audit import (
    WeekdayCutoverInputError,
    compare_weekday_shadow,
)
from loomera.globalization.weekdays import legacy_to_iso_weekday


def synthetic_rows():
    source = []
    shadow = []
    for salon in (11, 22):
        for legacy in range(1, 8):
            closed = legacy == 7
            row = {
                "row_id": salon * 10 + legacy,
                "salon_id": salon,
                "day_of_week": legacy,
                "is_closed": closed,
                "open_time": None if closed else "09:00",
                "close_time": None if closed else "17:00",
                "timezone_name": "Asia/Tehran" if salon == 11 else "Europe/Berlin",
            }
            source.append(row)
            shadow.append({**row, "iso_weekday": legacy_to_iso_weekday(legacy)})
    return source, shadow


def compare(source, shadow, **overrides):
    params = {
        "expected_rows": 14,
        "expected_salons": 2,
        "sample_start": date(2024, 1, 1),
        "sample_days": 1461,
        "timezone_provenance_verified": True,
    }
    params.update(overrides)
    return compare_weekday_shadow(source, shadow, **params)


class OfflineWeekdayShadowTests(SimpleTestCase):
    def test_full_four_year_parity_and_permutation_after_reorder(self):
        before, after = synthetic_rows()
        report = compare(list(reversed(before)), list(reversed(after)))
        self.assertTrue(report["structural_parity_verified"])
        self.assertEqual(report["stop_reasons"], [])
        self.assertEqual(report["calendar_probe_count"], 2 * 1461)
        self.assertEqual(report["calendar_mismatched_probes"], 0)
        self.assertEqual(report["source_rows"], 14)
        self.assertEqual(report["shadow_rows"], 14)
        self.assertEqual(report["source_issues"]["missing_legacy_days"], 0)
        self.assertEqual(report["shadow_issues"]["missing_iso_days"], 0)
        self.assertFalse(report["cutover_authorized"])
        self.assertFalse(report["migration_approved"])
        self.assertFalse(report["rollback_approved"])
        self.assertFalse(report["production_deployment_authorized"])
        self.assertEqual(report["database_reads"], 0)
        self.assertEqual(report["writes_performed"], 0)
        rendered = json.dumps(report)
        for secret in ("Asia/Tehran", "Europe/Berlin", '"row_id"', "09:00"):
            self.assertNotIn(secret, rendered)

    def test_detects_single_day_iso_shift_and_calendar_probes(self):
        before, after = synthetic_rows()
        after[0]["iso_weekday"] = 7
        report = compare(before, after)
        self.assertFalse(report["structural_parity_verified"])
        self.assertEqual(report["shadow_issues"]["invalid_or_mismatched_iso_days"], 1)
        self.assertGreater(report["calendar_mismatched_probes"], 0)
        self.assertIn("calendar_schedule_parity_mismatch", report["stop_reasons"])

    def test_detects_closed_time_timezone_and_opening_window_drift(self):
        for column, value in (
            ("is_closed", True),
            ("open_time", "08:00"),
            ("close_time", "19:00"),
            ("timezone_name", "Europe/Paris"),
        ):
            before, after = synthetic_rows()
            after[0][column] = value
            with self.subTest(column=column):
                report = compare(before, after)
                self.assertEqual(report["modified_legacy_field_rows"], 1)
                self.assertGreater(report["calendar_mismatched_probes"], 0)
                self.assertIn("legacy_field_drift", report["stop_reasons"])

    def test_missing_extra_and_duplicate_identity_are_hard_stops(self):
        for kind in ("missing", "extra", "duplicate_id", "duplicate_day"):
            before, after = synthetic_rows()
            if kind == "missing":
                after.pop()
            elif kind == "extra":
                after.append({**after[0], "row_id": 999})
            elif kind == "duplicate_id":
                after[1]["row_id"] = after[0]["row_id"]
            else:
                after[1]["day_of_week"] = after[0]["day_of_week"]
                after[1]["iso_weekday"] = after[0]["iso_weekday"]
            report = compare(before, after)
            with self.subTest(kind=kind):
                self.assertFalse(report["structural_parity_verified"])
                self.assertTrue(report["stop_reasons"])

    def test_closed_day_times_invalid_weekdays_and_unknown_timezone_fail(self):
        for field, value in (
            ("day_of_week", 0),
            ("day_of_week", 8),
            ("day_of_week", True),
            ("day_of_week", "1"),
            ("iso_weekday", 0),
            ("iso_weekday", True),
            ("timezone_name", ""),
            ("timezone_name", "No/Such_IANA_Zone"),
            ("open_time", "25:00"),
            ("open_time", "17:00"),
        ):
            before, after = synthetic_rows()
            after[0][field] = value
            with self.subTest(field=field, value=value):
                self.assertFalse(compare(before, after)["structural_parity_verified"])
        before, after = synthetic_rows()
        after[6]["open_time"] = "09:00"  # closed Friday with stale time
        self.assertFalse(compare(before, after)["structural_parity_verified"])

    def test_missing_days_and_wrong_count_never_pass(self):
        before, after = synthetic_rows()
        before.pop()
        after.pop()
        report = compare(before, after, expected_rows=13)
        self.assertFalse(report["structural_parity_verified"])
        self.assertGreater(report["source_issues"]["missing_legacy_days"], 0)
        self.assertGreater(report["shadow_issues"]["missing_iso_days"], 0)
        self.assertIn("legacy_source_integrity_blockers", report["stop_reasons"])

    def test_unverified_provenance_and_short_horizon_block_even_clean_rows(self):
        before, after = synthetic_rows()
        unverified = compare(before, after, timezone_provenance_verified=False)
        self.assertIn("timezone_provenance_unverified", unverified["stop_reasons"])
        short = compare(before, after, sample_days=7)
        self.assertIn("representative_year_boundary_rehearsal_incomplete",
                      short["stop_reasons"])

    def test_strict_input_rows_and_bounded_date_probe_budget(self):
        before, after = synthetic_rows()
        with self.assertRaises(WeekdayCutoverInputError):
            compare(before, after, sample_days=True)
        with self.assertRaises(WeekdayCutoverInputError):
            compare(before, after, expected_salons=True)
        with self.assertRaises(WeekdayCutoverInputError):
            compare(before, after, expected_salons=10000)
        for field in ("customer_mobile", "notes", "email"):
            bad = [dict(row) for row in after]
            bad[0][field] = "sensitive"
            with self.subTest(field=field):
                with self.assertRaises(WeekdayCutoverInputError):
                    compare(before, bad)
        with self.assertRaises(WeekdayCutoverInputError):
            compare([], after)

    def test_days_replay_month_and_year_boundaries_both_zones(self):
        source, shadow = synthetic_rows()
        for start in (date(2024, 2, 26), date(2026, 12, 26)):
            report = compare(source, shadow, sample_start=start, sample_days=370)
            self.assertEqual(report["calendar_mismatched_probes"], 0)
            self.assertTrue(report["structural_parity_verified"])


def encoded(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


class OfflineWeekdayFilesCommandTests(SimpleTestCase):
    def _files(self, folder, *, modify_manifest=None):
        source_rows, shadow_rows = synthetic_rows()
        before = encoded({
            "schema_version": 1, "representation": "legacy_saturday_1",
            "rows": source_rows,
        })
        after = encoded({
            "schema_version": 1, "representation": "legacy_with_iso_shadow",
            "rows": shadow_rows,
        })
        manifest = {
            "schema_version": 1,
            "source_kind": "operator_authorized_sanitized_offline_copy",
            "authorization_reference": "SYNTHETIC_CI_FIXTURE",
            "source_sha256": hashlib.sha256(before).hexdigest(),
            "shadow_sha256": hashlib.sha256(after).hexdigest(),
            "expected_rows": 14,
            "expected_salons": 2,
            "sample_start": "2024-01-01",
            "sample_days": 1461,
            "timezone_provenance": "operator_verified",
            "contains_customer_pii": False,
            "operation": "shadow_iso_weekday_preview_only",
        }
        if modify_manifest:
            modify_manifest(manifest)
        root = Path(folder)
        for filename, content in (
            ("source.json", before), ("shadow.json", after),
            ("manifest.json", encoded(manifest)),
        ):
            (root / filename).write_bytes(content)
        return dict(
            manifest=str(root / "manifest.json"),
            source=str(root / "source.json"),
            shadow=str(root / "shadow.json"),
            acknowledge_offline_sanitized_copy=True,
            as_json=True,
        )

    def test_command_fails_before_opening_any_file_without_dual_acknowledgment(self):
        with TemporaryDirectory() as folder:
            opts = self._files(folder)
            with patch.dict(os.environ, {audit.MARKER: ""}):
                with patch.object(Path, "read_bytes", side_effect=AssertionError(
                    "file must not be opened without authorization"
                )):
                    with self.assertRaises(CommandError):
                        call_command("audit_weekday_cutover_files", **opts)
            with patch.dict(os.environ, {audit.MARKER: audit.MARKER_VALUE}):
                opts["acknowledge_offline_sanitized_copy"] = False
                with patch.object(Path, "read_bytes", side_effect=AssertionError(
                    "file must not be opened without CLI acknowledgment"
                )):
                    with self.assertRaises(CommandError):
                        call_command("audit_weekday_cutover_files", **opts)

    def test_command_accepts_synthetic_offline_files_but_never_approves_cutover(self):
        with TemporaryDirectory() as folder:
            opts = self._files(folder)
            output = StringIO()
            with patch.dict(os.environ, {audit.MARKER: audit.MARKER_VALUE}):
                call_command("audit_weekday_cutover_files", stdout=output, **opts)
            report = json.loads(output.getvalue())
            self.assertTrue(report["structural_parity_verified"])
            self.assertTrue(report["byte_checksums_matched"])
            self.assertFalse(report["file_access_authorization_independently_verified"])
            self.assertFalse(report["migration_approved"])
            self.assertFalse(report["cutover_authorized"])
            self.assertEqual(report["writes_performed"], 0)
            self.assertNotIn("SYNTHETIC_CI_FIXTURE", output.getvalue())

    def test_tampered_byte_checksum_and_unexpected_fields_are_rejected(self):
        with TemporaryDirectory() as folder:
            opts = self._files(folder)
            (Path(folder) / "shadow.json").write_bytes(b"{}")
            output = StringIO()
            with patch.dict(os.environ, {audit.MARKER: audit.MARKER_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_weekday_cutover_files", stdout=output, **opts)
            self.assertEqual(output.getvalue(), "")
        with TemporaryDirectory() as folder:
            opts = self._files(folder, modify_manifest=lambda m: m.update(
                customer_mobile="0912..."
            ))
            with patch.dict(os.environ, {audit.MARKER: audit.MARKER_VALUE}):
                with self.assertRaises(CommandError):
                    call_command("audit_weekday_cutover_files", **opts)

    def test_manifest_mismatched_record_count_and_unverified_zone_stop(self):
        for modify in (
            lambda m: m.update(expected_rows=13),
            lambda m: m.update(timezone_provenance="unverified"),
            lambda m: m.update(sample_days=7),
        ):
            with TemporaryDirectory() as folder:
                opts = self._files(folder, modify_manifest=modify)
                output = StringIO()
                with patch.dict(os.environ, {audit.MARKER: audit.MARKER_VALUE}):
                    with self.assertRaises(CommandError):
                        call_command("audit_weekday_cutover_files", stdout=output, **opts)
                report = json.loads(output.getvalue())
                self.assertFalse(report["structural_parity_verified"])
                self.assertTrue(report["stop_reasons"])

    def test_duplicate_json_keys_are_denied_without_echoing_input(self):
        with TemporaryDirectory() as folder:
            opts = self._files(folder)
            payload = b'{"schema_version":1,"schema_version":1}'
            (Path(folder) / "manifest.json").write_bytes(payload)
            with patch.dict(os.environ, {audit.MARKER: audit.MARKER_VALUE}):
                with self.assertRaises(CommandError) as raised:
                    call_command("audit_weekday_cutover_files", **opts)
            self.assertNotIn("schema_version", str(raised.exception))

    def test_offline_tool_has_no_database_code_or_sql(self):
        from loomera.globalization import weekday_cutover_audit
        import inspect
        source = inspect.getsource(weekday_cutover_audit)
        command = inspect.getsource(audit)
        for text in (source, command):
            self.assertNotIn("django.db", text)
            self.assertNotIn(".objects.", text)
            self.assertNotIn("cursor.execute(", text)
            self.assertNotIn("RunSQL(", text)
            self.assertNotIn("RunPython(", text)
