"""Phase 6.3: pure weekday preflight, display parity and source coverage."""
from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.dashboards.appointment_management import _calendar_week_start
from loomera.globalization.weekday_rehearsal import (
    discover_weekday_sources,
    preview_legacy_weekday_rows,
)
from loomera.globalization.weekdays import (
    iso_to_legacy_weekday,
    legacy_opening_day_from_date,
    legacy_to_iso_weekday,
    start_of_display_week,
)

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/globalization/PHASE6_3_WEEKDAY_CONSUMER_INVENTORY.json"


class Phase63WeekdayPreflightTests(SimpleTestCase):
    def test_iso_proposal_roundtrip_preserves_open_closed_schedule_for_four_years(self):
        # Fully synthetic data; no real salon or appointment reads.
        rules_by_legacy_day = {
            day: {"closed": day == 7, "opens": f"{day + 7:02d}:00",
                  "closes": f"{day + 15:02d}:00"}
            for day in range(1, 8)
        }
        rules_by_iso_day = {
            legacy_to_iso_weekday(legacy): value
            for legacy, value in rules_by_legacy_day.items()
        }
        self.assertEqual(len(rules_by_iso_day), 7)
        start = date(2020, 1, 1)
        for offset in range(1461):
            value = start + timedelta(days=offset)
            expected = rules_by_legacy_day[legacy_opening_day_from_date(value)]
            self.assertEqual(rules_by_iso_day[value.isoweekday()], expected)
        for iso in range(1, 8):
            self.assertEqual(
                iso_to_legacy_weekday(legacy_to_iso_weekday(iso)), iso
            )

    def test_read_only_preview_preserves_histograms_and_reports_no_identifiers(self):
        rows = [(salon, day) for salon in (11, 22) for day in range(1, 8)]
        result = preview_legacy_weekday_rows(iter(rows))
        self.assertTrue(result.structurally_clean)
        self.assertEqual(result.total_rows, 14)
        self.assertEqual(result.valid_day_rows, 14)
        self.assertEqual(result.legacy_counts_saturday_first, (2,) * 7)
        self.assertEqual(result.iso_counts_monday_first, (2,) * 7)
        self.assertNotIn("11", str(result))
        self.assertNotIn("22", str(result))

    def test_preview_fails_closed_on_invalid_days_refs_and_duplicate_keys(self):
        cases = (
            ([(5, 1), (5, 1)], "duplicate_salon_day_rows"),
            ([(5, 0), (5, 8)], "invalid_day_rows"),
            ([(5, True)], "invalid_day_rows"),
            ([(5, "1")], "invalid_day_rows"),
            ([(0, 1), (None, 2)], "invalid_salon_reference_rows"),
        )
        for rows, field in cases:
            with self.subTest(rows=rows):
                result = preview_legacy_weekday_rows(rows)
                self.assertFalse(result.structurally_clean)
                self.assertGreater(getattr(result, field), 0)
        self.assertFalse(preview_legacy_weekday_rows([]).structurally_clean)
        for malformed in ((1,), (1, 2, 3), "not-a-tuple", None):
            with self.subTest(malformed=malformed):
                with self.assertRaises(TypeError):
                    preview_legacy_weekday_rows([malformed])

    def test_display_first_day_is_independent_from_stored_business_weekday(self):
        base = date(2020, 1, 1)
        for offset in range(1461):
            day = base + timedelta(days=offset)
            old_start = day - timedelta(days=(day.weekday() + 2) % 7)
            self.assertEqual(_calendar_week_start(day), old_start)
            self.assertEqual(start_of_display_week(day, first_day_iso=6), old_start)
            self.assertEqual(start_of_display_week(day, first_day_iso=1).weekday(), 0)
            self.assertEqual(start_of_display_week(day, first_day_iso=7).weekday(), 6)
            self.assertEqual(legacy_opening_day_from_date(day), ((day.weekday() + 2) % 7) + 1)

    def test_inventory_manifest_anchors_real_files_and_explicitly_stays_partial(self):
        manifest = json.loads(INVENTORY.read_text(encoding="utf-8"))
        self.assertEqual(manifest["phase"], "6.3")
        self.assertFalse(manifest.get("semantically_exhaustive", False))
        self.assertEqual(manifest["weekday_contracts"]["iso_proposal"],
                         "Monday=1..Sunday=7, NOT APPROVED")
        entries = manifest["reviewed_anchors"]
        self.assertGreaterEqual(len(entries), 25)
        self.assertEqual(len(entries), len({
            (entry["path"], entry["classification"], entry["anchor"])
            for entry in entries
        }))
        for entry in entries:
            path = ROOT / entry["path"]
            with self.subTest(path=entry["path"], kind=entry["classification"]):
                self.assertTrue(path.is_file())
                self.assertIn(entry["anchor"], path.read_text(encoding="utf-8"))

    def test_scanner_detects_candidates_but_skips_tests_and_migrations(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in ("apps/example", "apps/example/migrations", "static/js"):
                (root / directory).mkdir(parents=True)
            (root / "apps/example/views.py").write_text(
                "def x(day): return day.weekday()\n", encoding="utf-8"
            )
            (root / "apps/example/test_views.py").write_text(
                "day_of_week\n", encoding="utf-8"
            )
            (root / "apps/example/migrations/0001.py").write_text(
                "day_of_week\n", encoding="utf-8"
            )
            (root / "static/js/calendar.js").write_text(
                "value.getDay()\n", encoding="utf-8"
            )
            self.assertEqual(
                discover_weekday_sources(root),
                (("apps/example/views.py", 1), ("static/js/calendar.js", 1)),
            )
        scanned = dict(discover_weekday_sources(ROOT))
        self.assertIn("apps/dashboards/views.py", scanned)
        self.assertIn("apps/salons/models.py", scanned)
        self.assertIn("static/js/select_datetime.js", scanned)

    def test_management_source_audit_does_not_touch_database_or_emit_records(self):
        output = StringIO()
        call_command("audit_weekday_source", as_json=True, stdout=output)
        report = json.loads(output.getvalue())
        self.assertGreater(report["candidate_source_files"], 0)
        self.assertEqual(report["database_access"], False)
        self.assertEqual(report["writes_performed"], 0)
        self.assertIs(report["inventory_semantics_complete"], False)
        self.assertTrue(all("/" in path for path in report["candidate_paths"]))
        import inspect
        from loomera.globalization import weekday_rehearsal
        source = inspect.getsource(weekday_rehearsal)
        self.assertNotIn("django.db", source)
        self.assertNotIn("objects.", source)
