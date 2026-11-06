"""Phase 7.7: no live auth wiring + test-only Redis contract (no Redis needed).

These source-anchored checks run in Fast checks; real Redis EVAL and process
races have a separate isolated CI job.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization import otp_atomic_redis_rehearsal as rehearsal

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/globalization/PHASE7_7_REDIS_ATOMIC_OTP_CONTRACT.json"
EXIT = ROOT / "docs/globalization/PHASE7_7_EXIT_MATRIX.json"
LIVE_PATHS = (
    "apps/api/v1/auth_otp.py",
    "apps/api/v1/auth_views.py",
    "apps/accounts/views.py",
    "apps/accounts/models.py",
)


class Phase77RedisContractTests(SimpleTestCase):
    def test_no_production_login_or_session_path_imports_experimental_consumer(self):
        for path in LIVE_PATHS:
            content = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("otp_atomic_redis_rehearsal", content)
                self.assertNotIn("SyntheticRedisOtpRehearsal", content)

    def test_script_atomic_delete_budget_and_no_global_redis_cleanup(self):
        script = rehearsal.ATOMIC_CONSUME_SCRIPT
        self.assertIn("redis.call('HMGET', KEYS[1]", script)
        self.assertIn("redis.call('HINCRBY', KEYS[1], 'attempts', 1)", script)
        self.assertIn("if redis.call('DEL', KEYS[1]) ~= 1 then", script)
        self.assertIn("return {'consumed', '0'}", script)
        self.assertIn("expires_at <= now", script)
        self.assertIn("redis.call('EXISTS', KEYS[1])", rehearsal.ATOMIC_SEED_SCRIPT)
        for forbidden in ("FLUSHDB", "FLUSHALL", "KEYS *", "SCAN 0"):
            self.assertNotIn(forbidden, script + rehearsal.ATOMIC_SEED_SCRIPT)

    def test_test_only_client_guard_and_no_auth_dependencies(self):
        source = inspect.getsource(rehearsal)
        self.assertIn('LOOMERA_PHASE77_TEST_REDIS', source)
        self.assertIn("db != 15", source)
        self.assertIn("localhost", source)
        for dangerous in (
            "django.contrib.auth", "login(request", "request.session",
            "from apps.api", "from apps.accounts", ".objects.",
            "send_otp_sms(", "transaction.atomic(", "cache.get(",
        ):
            with self.subTest(dangerous=dangerous):
                self.assertNotIn(dangerous, source)

    def test_contract_anchors_match_actual_unmodified_legacy_otp_consumers(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["phase"], "7.7")
        self.assertEqual(contract["implementation"]["test_redis_database"], 15)
        self.assertFalse(contract["implementation"]["production_login_integration"])
        self.assertFalse(contract["implementation"]["production_otp_record_compatibility"])
        self.assertFalse(contract["implementation"]["script_constant_time_digest_compare_proven"])
        for item in contract["source_anchors"]:
            with self.subTest(path=item["path"], anchor=item["anchor"]):
                self.assertIn(
                    item["anchor"],
                    (ROOT / item["path"]).read_text(encoding="utf-8"),
                )

    def test_exit_requires_security_review_and_real_data_remains_blocked(self):
        matrix = json.loads(EXIT.read_text(encoding="utf-8"))
        self.assertEqual(matrix["phase"], "7.7")
        self.assertFalse(matrix["production_runtime_consumer_wired"])
        self.assertFalse(matrix["legacy_otp_cache_serialization_migrated"])
        self.assertFalse(matrix["real_account_or_otp_snapshot_used"])
        self.assertFalse(matrix["production_cutover_authorized"])
        self.assertEqual(matrix["deployment"], "NONE")
        self.assertIn("BLOCKED", matrix["release_gate"])
