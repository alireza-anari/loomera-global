"""Phase 7.8 Fast-check source and release gates; no Redis required."""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization import otp_cache_wire_rehearsal as wire

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_8_EXIT_MATRIX.json"
LIVE_PATHS = (
    "apps/api/v1/auth_otp.py",
    "apps/api/v1/auth_views.py",
    "apps/accounts/views.py",
    "apps/accounts/models.py",
)


class Phase78WireContractTests(SimpleTestCase):
    def test_no_live_auth_import_of_wire_preflight(self):
        for path in LIVE_PATHS:
            with self.subTest(path=path):
                src = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("otp_cache_wire_rehearsal", src)
                self.assertNotIn("inspect_synthetic_legacy_wire", src)

    def test_read_only_preflight_has_no_write_or_user_auth_dependencies(self):
        source = inspect.getsource(wire)
        self.assertIn('LOOMERA_PHASE78_TEST_REDIS', source)
        self.assertIn("db != 15", source)
        self.assertIn('getattr(cache, "_server", None)', source)
        self.assertIn("cache.get(logical_key)", source)
        for forbidden in (
            "cache.set(", "cache.delete(", "redis_client.set(",
            "redis_client.delete(", "redis_client.eval(",
            "flushdb(", "flushall(", "django.contrib.auth",
            "login(request", "request.session", ".objects.",
        ):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)

    def test_production_legacy_race_still_explicitly_unfixed(self):
        src = (ROOT / "apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        self.assertIn("record = _cache_get(key)", src)
        self.assertIn("secrets.compare_digest(expected_hash, submitted_hash)", src)
        self.assertIn("_cache_delete(", src)
        self.assertIn("cache.delete(key)", src)
        self.assertIn("return True", src)

    def test_exit_evidence_keeps_release_blocked(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.8")
        self.assertEqual(matrix["baseline_main_sha"], "23c23cccf0192f39b1746e1dccd4632025cbd3cc")
        for field in (
            "production_runtime_wired", "production_cache_serialization_migrated",
            "legacy_race_fixed", "production_cutover_authorized",
            "real_accounts_read", "deployment_performed",
        ):
            self.assertFalse(matrix[field], field)
        self.assertIn("BLOCKED", matrix["release_gate"])
