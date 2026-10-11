from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

TRANSACTIONAL_SMS_SETTING_NAMES = (
    "SMSIR_VERIFY_URL",
    "SMSIR_TRANSACTIONAL_TEMPLATES_ENABLED",
    "SMSIR_BOOKING_CREATED_TEMPLATE_ID",
    "SMSIR_STYLIST_NEW_BOOKING_TEMPLATE_ID",
    "SMSIR_BOOKING_CONFIRMED_TEMPLATE_ID",
    "SMSIR_BOOKING_CANCELLED_TEMPLATE_ID",
    "SMSIR_BOOKING_REMINDER_TEMPLATE_ID",
    "SMSIR_BOOKING_RESCHEDULED_TEMPLATE_ID",
)

GLOBAL_DEPLOYMENT_SETTING_NAMES = (
    "LOOMERA_DEFAULT_LANGUAGE",
    "LOOMERA_ENABLED_LANGUAGES",
    "LOOMERA_DEFAULT_COUNTRY",
    "LOOMERA_DEFAULT_CURRENCY",
    "LOOMERA_DEFAULT_TIMEZONE",
    "LOOMERA_DEFAULT_CALENDAR",
)

SETTINGS_IMPORT_SCRIPT = r"""
import json
from loomera.settings import base

print(
    "LOOMERA_SETTINGS_JSON="
    + json.dumps(
        {
            "LOOMERA_DEFAULT_LANGUAGE": base.LOOMERA_DEFAULT_LANGUAGE,
            "LOOMERA_ENABLED_LANGUAGES": base.LOOMERA_ENABLED_LANGUAGES,
            "LOOMERA_DEFAULT_COUNTRY": base.LOOMERA_DEFAULT_COUNTRY,
            "LOOMERA_DEFAULT_CURRENCY": base.LOOMERA_DEFAULT_CURRENCY,
            "LOOMERA_DEFAULT_TIMEZONE": base.LOOMERA_DEFAULT_TIMEZONE,
            "LOOMERA_DEFAULT_CALENDAR": base.LOOMERA_DEFAULT_CALENDAR,
            "LANGUAGE_CODE": base.LANGUAGE_CODE,
            "TIME_ZONE": base.TIME_ZONE,
        },
        sort_keys=True,
    )
)
"""


class ProductionSettingsHygieneTests(SimpleTestCase):
    def _import_base_settings(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for setting_name in GLOBAL_DEPLOYMENT_SETTING_NAMES:
            env.pop(setting_name, None)

        env.update(
            {
                "SECRET_KEY": "test-only-production-settings-hygiene",
                "DATABASE_URL": "sqlite:///production-settings-hygiene.sqlite3",
                "DEBUG": "False",
                "ALLOWED_HOSTS": "localhost,127.0.0.1",
                "CSRF_TRUSTED_ORIGINS": "http://localhost,http://127.0.0.1",
                "ONLINE_PAYMENT_ENABLED": "False",
                "PAYMENT_MODE": "mock",
                **overrides,
            }
        )

        return subprocess.run(
            [sys.executable, "-c", SETTINGS_IMPORT_SCRIPT],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _loaded_values(self, **overrides: str) -> dict[str, object]:
        result = self._import_base_settings(**overrides)
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        for line in result.stdout.splitlines():
            if line.startswith("LOOMERA_SETTINGS_JSON="):
                return json.loads(line.removeprefix("LOOMERA_SETTINGS_JSON="))
        self.fail(f"Settings payload missing from subprocess output: {result.stdout}")

    def _assert_invalid_configuration(self, expected_setting: str, **overrides: str) -> None:
        result = self._import_base_settings(**overrides)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn(expected_setting, result.stderr)

    def test_transactional_sms_settings_are_defined_exactly_once(self):
        settings_path = Path(settings.BASE_DIR) / "loomera" / "settings" / "base.py"
        source = settings_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(settings_path))

        assignment_counts = {
            setting_name: 0 for setting_name in TRANSACTIONAL_SMS_SETTING_NAMES
        }

        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue

            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id in assignment_counts:
                    assignment_counts[target.id] += 1

        expected_counts = {
            setting_name: 1 for setting_name in TRANSACTIONAL_SMS_SETTING_NAMES
        }

        self.assertEqual(assignment_counts, expected_counts)

    def test_global_deployment_defaults_preserve_current_runtime_defaults(self):
        values = self._loaded_values()

        self.assertEqual(values["LOOMERA_DEFAULT_LANGUAGE"], "fa")
        self.assertEqual(values["LOOMERA_ENABLED_LANGUAGES"], ["fa"])
        self.assertEqual(values["LOOMERA_DEFAULT_COUNTRY"], "IR")
        self.assertEqual(values["LOOMERA_DEFAULT_CURRENCY"], "")
        self.assertEqual(values["LOOMERA_DEFAULT_TIMEZONE"], "Asia/Tehran")
        self.assertEqual(values["LOOMERA_DEFAULT_CALENDAR"], "jalali")
        self.assertIn(
            values["LOOMERA_DEFAULT_LANGUAGE"], values["LOOMERA_ENABLED_LANGUAGES"]
        )
        self.assertEqual(values["LANGUAGE_CODE"], "fa")
        self.assertEqual(values["TIME_ZONE"], "Asia/Tehran")

    def test_language_contract_trims_normalizes_and_requires_enabled_default(self):
        values = self._loaded_values(
            LOOMERA_DEFAULT_LANGUAGE=" EN ",
            LOOMERA_ENABLED_LANGUAGES=" fa , EN ",
        )
        self.assertEqual(values["LOOMERA_DEFAULT_LANGUAGE"], "en")
        self.assertEqual(values["LOOMERA_ENABLED_LANGUAGES"], ["fa", "en"])

        self._assert_invalid_configuration(
            "LOOMERA_DEFAULT_LANGUAGE",
            LOOMERA_DEFAULT_LANGUAGE="en",
            LOOMERA_ENABLED_LANGUAGES="fa",
        )
        self._assert_invalid_configuration(
            "LOOMERA_DEFAULT_LANGUAGE",
            LOOMERA_DEFAULT_LANGUAGE="",
        )

    def test_enabled_languages_reject_empty_entries_and_normalized_duplicates(self):
        invalid_values = ("", "fa,", "fa,,en", "fa, FA")
        for invalid_value in invalid_values:
            with self.subTest(value=invalid_value):
                self._assert_invalid_configuration(
                    "LOOMERA_ENABLED_LANGUAGES",
                    LOOMERA_ENABLED_LANGUAGES=invalid_value,
                )

    def test_country_contract_normalizes_and_validates_ascii_alpha2_shape(self):
        values = self._loaded_values(LOOMERA_DEFAULT_COUNTRY=" us ")
        self.assertEqual(values["LOOMERA_DEFAULT_COUNTRY"], "US")

        for invalid_value in ("", "USA", "U1", "ای"):
            with self.subTest(value=invalid_value):
                self._assert_invalid_configuration(
                    "LOOMERA_DEFAULT_COUNTRY",
                    LOOMERA_DEFAULT_COUNTRY=invalid_value,
                )

    def test_currency_contract_allows_empty_and_normalizes_configured_code(self):
        self.assertEqual(self._loaded_values()["LOOMERA_DEFAULT_CURRENCY"], "")
        self.assertEqual(
            self._loaded_values(LOOMERA_DEFAULT_CURRENCY=" usd ")[
                "LOOMERA_DEFAULT_CURRENCY"
            ],
            "USD",
        )

        for invalid_value in ("US", "USDD", "U1D", "یورو"):
            with self.subTest(value=invalid_value):
                self._assert_invalid_configuration(
                    "LOOMERA_DEFAULT_CURRENCY",
                    LOOMERA_DEFAULT_CURRENCY=invalid_value,
                )

    def test_timezone_contract_accepts_iana_zone_and_rejects_unknown_zone(self):
        values = self._loaded_values(LOOMERA_DEFAULT_TIMEZONE=" UTC ")
        self.assertEqual(values["LOOMERA_DEFAULT_TIMEZONE"], "UTC")

        for invalid_value in ("", "Mars/Olympus"):
            with self.subTest(value=invalid_value):
                self._assert_invalid_configuration(
                    "LOOMERA_DEFAULT_TIMEZONE",
                    LOOMERA_DEFAULT_TIMEZONE=invalid_value,
                )

    def test_calendar_contract_normalizes_and_restricts_supported_values(self):
        values = self._loaded_values(LOOMERA_DEFAULT_CALENDAR=" GREGORIAN ")
        self.assertEqual(values["LOOMERA_DEFAULT_CALENDAR"], "gregorian")

        self._assert_invalid_configuration(
            "LOOMERA_DEFAULT_CALENDAR",
            LOOMERA_DEFAULT_CALENDAR="solar",
        )

    def test_global_deployment_settings_do_not_replace_django_runtime_settings(self):
        values = self._loaded_values(
            LOOMERA_DEFAULT_LANGUAGE="en",
            LOOMERA_ENABLED_LANGUAGES="fa,en",
            LOOMERA_DEFAULT_COUNTRY="US",
            LOOMERA_DEFAULT_CURRENCY="USD",
            LOOMERA_DEFAULT_TIMEZONE="UTC",
            LOOMERA_DEFAULT_CALENDAR="gregorian",
        )

        self.assertEqual(values["LOOMERA_DEFAULT_LANGUAGE"], "en")
        self.assertEqual(values["LOOMERA_DEFAULT_TIMEZONE"], "UTC")
        self.assertEqual(values["LANGUAGE_CODE"], "fa")
        self.assertEqual(values["TIME_ZONE"], "Asia/Tehran")
