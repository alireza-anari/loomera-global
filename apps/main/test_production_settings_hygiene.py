from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
import json
import os
from pathlib import Path
import subprocess
import sys

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from loomera.globalization import config as globalization_config_module
from loomera.globalization.config import (
    DeploymentGlobalizationConfig,
    get_deployment_globalization_config,
)
from loomera.globalization import providers as provider_config_module
from loomera.globalization.providers import (
    DeploymentProviderConfig,
    get_deployment_provider_config,
)

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


class SharedGlobalizationConfigurationBoundaryTests(SimpleTestCase):
    expected_field_names = (
        "default_language",
        "enabled_languages",
        "default_country",
        "default_currency",
        "default_timezone",
        "default_calendar",
    )

    def test_default_snapshot_contains_all_compatibility_values(self):
        config = get_deployment_globalization_config()

        self.assertIsInstance(config, DeploymentGlobalizationConfig)
        self.assertEqual(config.default_language, "fa")
        self.assertEqual(config.enabled_languages, ("fa",))
        self.assertIsInstance(config.enabled_languages, tuple)
        self.assertEqual(config.default_country, "IR")
        self.assertEqual(config.default_currency, "")
        self.assertEqual(config.default_timezone, "Asia/Tehran")
        self.assertEqual(config.default_calendar, "jalali")

    def test_snapshot_is_immutable_and_has_no_extra_domain_surface(self):
        config = get_deployment_globalization_config()

        with self.assertRaises(FrozenInstanceError):
            config.default_language = "en"

        self.assertEqual(
            tuple(field.name for field in fields(DeploymentGlobalizationConfig)),
            self.expected_field_names,
        )
        self.assertEqual(
            globalization_config_module.__all__,
            (
                "DeploymentGlobalizationConfig",
                "get_deployment_globalization_config",
            ),
        )
        self.assertEqual(
            {name for name in vars(DeploymentGlobalizationConfig) if not name.startswith("_")},
            set(self.expected_field_names),
        )

    @override_settings(
        LOOMERA_DEFAULT_LANGUAGE="en",
        LOOMERA_ENABLED_LANGUAGES=["fa", "en"],
        LOOMERA_DEFAULT_COUNTRY="US",
        LOOMERA_DEFAULT_CURRENCY="USD",
        LOOMERA_DEFAULT_TIMEZONE="UTC",
        LOOMERA_DEFAULT_CALENDAR="gregorian",
    )
    def test_valid_overridden_settings_are_reflected_without_runtime_activation(self):
        config = get_deployment_globalization_config()

        self.assertEqual(config.default_language, "en")
        self.assertEqual(config.enabled_languages, ("fa", "en"))
        self.assertEqual(config.default_country, "US")
        self.assertEqual(config.default_currency, "USD")
        self.assertEqual(config.default_timezone, "UTC")
        self.assertEqual(config.default_calendar, "gregorian")
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")

    def test_accessor_returns_fresh_snapshots_without_mutating_settings_list(self):
        enabled_languages = ["fa", "en"]

        with override_settings(
            LOOMERA_DEFAULT_LANGUAGE="fa",
            LOOMERA_ENABLED_LANGUAGES=enabled_languages,
            LOOMERA_DEFAULT_COUNTRY="IR",
            LOOMERA_DEFAULT_CURRENCY="",
            LOOMERA_DEFAULT_TIMEZONE="Asia/Tehran",
            LOOMERA_DEFAULT_CALENDAR="jalali",
        ):
            first = get_deployment_globalization_config()
            second = get_deployment_globalization_config()

            self.assertIsNot(first, second)
            self.assertEqual(first, second)
            self.assertEqual(enabled_languages, ["fa", "en"])
            self.assertIs(settings.LOOMERA_ENABLED_LANGUAGES, enabled_languages)
            self.assertEqual(first.enabled_languages, ("fa", "en"))
            self.assertIsNot(first.enabled_languages, enabled_languages)

    def test_accessor_reads_only_the_six_validated_django_settings(self):
        config_path = Path(settings.BASE_DIR) / "loomera" / "globalization" / "config.py"
        source = config_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(config_path))

        setting_reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "_settings"
        }

        self.assertEqual(setting_reads, set(GLOBAL_DEPLOYMENT_SETTING_NAMES))
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import environ", source)
        self.assertNotIn("loomera.settings.base", source)
        self.assertNotIn("ImproperlyConfigured", source)


class SharedProviderConfigurationBoundaryTests(SimpleTestCase):
    expected_field_names = (
        "map_provider",
        "sms_provider",
        "payment_provider",
        "messaging_allowed_providers",
    )

    def test_default_snapshot_preserves_current_provider_compatibility_values(self):
        config = get_deployment_provider_config()

        self.assertIsInstance(config, DeploymentProviderConfig)
        self.assertEqual(config.map_provider, "mapir")
        self.assertEqual(config.sms_provider, "disabled")
        self.assertEqual(config.payment_provider, "zibal")
        self.assertEqual(config.messaging_allowed_providers, ())
        self.assertIsInstance(config.messaging_allowed_providers, tuple)

    def test_map_provider_uses_existing_mapir_fallback_when_setting_is_absent_or_empty(self):
        self.assertFalse(hasattr(settings, "MAP_PROVIDER"))
        self.assertEqual(get_deployment_provider_config().map_provider, "mapir")

        with override_settings(MAP_PROVIDER=""):
            self.assertEqual(get_deployment_provider_config().map_provider, "mapir")

    def test_snapshot_is_frozen_and_exposes_exact_contract_surface(self):
        config = get_deployment_provider_config()

        with self.assertRaises(FrozenInstanceError):
            config.map_provider = "neshan"

        self.assertEqual(
            tuple(field.name for field in fields(DeploymentProviderConfig)),
            self.expected_field_names,
        )
        self.assertEqual(
            provider_config_module.__all__,
            (
                "DeploymentProviderConfig",
                "get_deployment_provider_config",
            ),
        )
        self.assertEqual(
            {name for name in vars(DeploymentProviderConfig) if not name.startswith("_")},
            set(self.expected_field_names),
        )

    @override_settings(
        MAP_PROVIDER=" NESHAN ",
        SMS_PROVIDER="twilio",
        PAYMENT_PROVIDER="stripe",
        MESSAGING_ALLOWED_PROVIDERS=["telegram", "bale"],
    )
    def test_overridden_provider_settings_are_reflected_without_globalization_inference(self):
        config = get_deployment_provider_config()

        self.assertEqual(config.map_provider, "neshan")
        self.assertEqual(config.sms_provider, "twilio")
        self.assertEqual(config.payment_provider, "stripe")
        self.assertEqual(config.messaging_allowed_providers, ("telegram", "bale"))

        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, "IR")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, "Asia/Tehran")
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")

    def test_accessor_returns_fresh_snapshots_without_mutating_messaging_settings_list(self):
        allowed_providers = ["telegram", "bale"]

        with override_settings(
            MAP_PROVIDER="mapir",
            SMS_PROVIDER="disabled",
            PAYMENT_PROVIDER="zibal",
            MESSAGING_ALLOWED_PROVIDERS=allowed_providers,
        ):
            first = get_deployment_provider_config()
            second = get_deployment_provider_config()

            self.assertIsNot(first, second)
            self.assertEqual(first, second)
            self.assertEqual(allowed_providers, ["telegram", "bale"])
            self.assertIs(settings.MESSAGING_ALLOWED_PROVIDERS, allowed_providers)
            self.assertEqual(first.messaging_allowed_providers, ("telegram", "bale"))
            self.assertIsNot(first.messaging_allowed_providers, allowed_providers)

    def test_accessor_reads_only_provider_django_settings_and_no_environment_or_domain_context(self):
        providers_path = Path(settings.BASE_DIR) / "loomera" / "globalization" / "providers.py"
        source = providers_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(providers_path))

        direct_setting_reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "_settings"
        }
        getattr_setting_reads = {
            node.args[1].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "_settings"
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        }

        self.assertEqual(
            direct_setting_reads | getattr_setting_reads,
            {
                "MAP_PROVIDER",
                "SMS_PROVIDER",
                "PAYMENT_PROVIDER",
                "MESSAGING_ALLOWED_PROVIDERS",
            },
        )
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import environ", source)
        self.assertNotIn("loomera.settings.base", source)
        self.assertNotIn("LOOMERA_DEFAULT_COUNTRY", source)
        self.assertNotIn("LOOMERA_DEFAULT_CURRENCY", source)
        self.assertNotIn("LOOMERA_DEFAULT_TIMEZONE", source)
        self.assertNotIn("LANGUAGE_CODE", source)
        self.assertNotIn("TIME_ZONE", source)
        self.assertNotIn("PHONE", source.upper())


from loomera.branding import assets as brand_assets_module
from loomera.branding import config as brand_config_module
from loomera.branding import context_processors as brand_context_processor_module
from loomera.branding.assets import (
    DeploymentBrandAssetConfig,
    get_deployment_brand_asset_config,
)
from loomera.branding.config import (
    DeploymentBrandConfig,
    get_deployment_brand_config,
)
from loomera.branding.context_processors import deployment_brand

BRAND_DEPLOYMENT_SETTING_NAMES = (
    "BRAND_NAME",
    "BRAND_DISPLAY_NAME",
    "BRAND_DOMAIN",
    "PUBLIC_BASE_URL",
    "SITE_URL",
    "LOOMERA_EMAIL_SENDER_NAME",
    "DEFAULT_FROM_EMAIL",
    "LOOMERA_SUPPORT_EMAIL",
    "LOOMERA_PARTNER_EMAIL",
    "LOOMERA_MARKETING_EMAIL",
)

BRAND_ASSET_SETTING_NAMES = (
    "BRAND_LOGO_GLYPH_STATIC_PATH",
    "BRAND_APP_ICON_STATIC_PATH",
    "BRAND_LOGO_HEADER_STATIC_PATH",
    "BRAND_LOGO_PRIMARY_STATIC_PATH",
    "BRAND_FAVICON_SVG_STATIC_PATH",
    "BRAND_FAVICON_ICO_STATIC_PATH",
    "BRAND_FAVICON_16_STATIC_PATH",
    "BRAND_FAVICON_32_STATIC_PATH",
    "BRAND_FAVICON_48_STATIC_PATH",
    "BRAND_APPLE_TOUCH_ICON_STATIC_PATH",
    "BRAND_MASK_ICON_STATIC_PATH",
    "BRAND_WEBMANIFEST_STATIC_PATH",
    "BRAND_SOCIAL_IMAGE_STATIC_PATH",
    "BRAND_SOCIAL_IMAGE_WIDTH",
    "BRAND_SOCIAL_IMAGE_HEIGHT",
)

BRAND_ASSET_DEFAULTS = {
    "BRAND_LOGO_GLYPH_STATIC_PATH": "branding/logo/loomera-glyph-mark.png",
    "BRAND_APP_ICON_STATIC_PATH": "branding/logo/loomera-app-icon.png",
    "BRAND_LOGO_HEADER_STATIC_PATH": "branding/logo/loomera-logo-header.png",
    "BRAND_LOGO_PRIMARY_STATIC_PATH": "branding/logo/loomera-logo-primary.png",
    "BRAND_FAVICON_SVG_STATIC_PATH": "branding/favicon/favicon.svg",
    "BRAND_FAVICON_ICO_STATIC_PATH": "branding/favicon/favicon.ico",
    "BRAND_FAVICON_16_STATIC_PATH": "branding/favicon/favicon-16x16.png",
    "BRAND_FAVICON_32_STATIC_PATH": "branding/favicon/favicon-32x32.png",
    "BRAND_FAVICON_48_STATIC_PATH": "branding/favicon/favicon-48x48.png",
    "BRAND_APPLE_TOUCH_ICON_STATIC_PATH": "branding/favicon/apple-touch-icon.png",
    "BRAND_MASK_ICON_STATIC_PATH": "branding/favicon/safari-pinned-tab.svg",
    "BRAND_WEBMANIFEST_STATIC_PATH": "branding/favicon/site.webmanifest",
    "BRAND_SOCIAL_IMAGE_STATIC_PATH": "branding/logo/loomera-logo-square.png",
    "BRAND_SOCIAL_IMAGE_WIDTH": 1254,
    "BRAND_SOCIAL_IMAGE_HEIGHT": 1254,
}

BRAND_ASSET_SETTINGS_IMPORT_SCRIPT = r"""
import json
from loomera.settings import base

names = (
    "BRAND_LOGO_GLYPH_STATIC_PATH",
    "BRAND_APP_ICON_STATIC_PATH",
    "BRAND_LOGO_HEADER_STATIC_PATH",
    "BRAND_LOGO_PRIMARY_STATIC_PATH",
    "BRAND_FAVICON_SVG_STATIC_PATH",
    "BRAND_FAVICON_ICO_STATIC_PATH",
    "BRAND_FAVICON_16_STATIC_PATH",
    "BRAND_FAVICON_32_STATIC_PATH",
    "BRAND_FAVICON_48_STATIC_PATH",
    "BRAND_APPLE_TOUCH_ICON_STATIC_PATH",
    "BRAND_MASK_ICON_STATIC_PATH",
    "BRAND_WEBMANIFEST_STATIC_PATH",
    "BRAND_SOCIAL_IMAGE_STATIC_PATH",
    "BRAND_SOCIAL_IMAGE_WIDTH",
    "BRAND_SOCIAL_IMAGE_HEIGHT",
)
print(
    "LOOMERA_BRAND_ASSETS_JSON="
    + json.dumps({name: getattr(base, name) for name in names}, sort_keys=True)
)
"""


class SharedBrandConfigurationBoundaryTests(SimpleTestCase):
    expected_field_names = (
        "name",
        "display_name",
        "domain",
        "public_base_url",
        "site_url",
        "email_sender_name",
        "default_from_email",
        "support_email",
        "partner_email",
        "marketing_email",
    )

    def test_default_snapshot_preserves_current_brand_compatibility_values(self):
        config = get_deployment_brand_config()

        self.assertIsInstance(config, DeploymentBrandConfig)
        self.assertEqual(config.name, "Loomera")
        self.assertEqual(config.display_name, "Loomera")
        self.assertEqual(config.domain, "loomera.local")
        self.assertEqual(config.public_base_url, "")
        self.assertEqual(config.site_url, "")
        self.assertEqual(config.email_sender_name, "Loomera")
        self.assertEqual(config.default_from_email, "Loomera <no-reply@loomera.local>")
        self.assertEqual(config.support_email, "support@loomera.local")
        self.assertEqual(config.partner_email, "partners@loomera.local")
        self.assertEqual(config.marketing_email, "hello@loomera.local")

    def test_snapshot_is_frozen_and_exposes_exact_contract_surface(self):
        config = get_deployment_brand_config()

        with self.assertRaises(FrozenInstanceError):
            config.name = "Other"

        self.assertEqual(
            tuple(field.name for field in fields(DeploymentBrandConfig)),
            self.expected_field_names,
        )
        self.assertEqual(
            brand_config_module.__all__,
            ("DeploymentBrandConfig", "get_deployment_brand_config"),
        )
        self.assertEqual(
            {name for name in vars(DeploymentBrandConfig) if not name.startswith("_")},
            set(self.expected_field_names),
        )

    @override_settings(
        BRAND_NAME="Acme",
        BRAND_DISPLAY_NAME="Acme Global",
        BRAND_DOMAIN="example.com",
        PUBLIC_BASE_URL="https://www.example.com",
        SITE_URL="https://app.example.com",
        LOOMERA_EMAIL_SENDER_NAME="Acme Mail",
        DEFAULT_FROM_EMAIL="Acme Mail <no-reply@example.com>",
        LOOMERA_SUPPORT_EMAIL="support@example.com",
        LOOMERA_PARTNER_EMAIL="partners@example.com",
        LOOMERA_MARKETING_EMAIL="hello@example.com",
    )
    def test_overridden_brand_settings_are_reflected_without_runtime_inference(self):
        runtime_values = {
            "language_code": settings.LANGUAGE_CODE,
            "time_zone": settings.TIME_ZONE,
            "default_language": settings.LOOMERA_DEFAULT_LANGUAGE,
            "default_country": settings.LOOMERA_DEFAULT_COUNTRY,
            "default_currency": settings.LOOMERA_DEFAULT_CURRENCY,
            "default_timezone": settings.LOOMERA_DEFAULT_TIMEZONE,
            "sms_provider": settings.SMS_PROVIDER,
            "payment_provider": settings.PAYMENT_PROVIDER,
            "messaging_allowed_providers": tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
        }

        config = get_deployment_brand_config()

        self.assertEqual(config.name, "Acme")
        self.assertEqual(config.display_name, "Acme Global")
        self.assertEqual(config.domain, "example.com")
        self.assertEqual(config.public_base_url, "https://www.example.com")
        self.assertEqual(config.site_url, "https://app.example.com")
        self.assertEqual(config.email_sender_name, "Acme Mail")
        self.assertEqual(config.default_from_email, "Acme Mail <no-reply@example.com>")
        self.assertEqual(config.support_email, "support@example.com")
        self.assertEqual(config.partner_email, "partners@example.com")
        self.assertEqual(config.marketing_email, "hello@example.com")

        self.assertEqual(settings.LANGUAGE_CODE, runtime_values["language_code"])
        self.assertEqual(settings.TIME_ZONE, runtime_values["time_zone"])
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, runtime_values["default_language"])
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, runtime_values["default_country"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, runtime_values["default_currency"])
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, runtime_values["default_timezone"])
        self.assertEqual(settings.SMS_PROVIDER, runtime_values["sms_provider"])
        self.assertEqual(settings.PAYMENT_PROVIDER, runtime_values["payment_provider"])
        self.assertEqual(
            tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
            runtime_values["messaging_allowed_providers"],
        )

    def test_accessor_returns_a_fresh_snapshot_per_call(self):
        first = get_deployment_brand_config()
        second = get_deployment_brand_config()
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_accessor_reads_only_the_ten_resolved_django_settings(self):
        config_path = Path(settings.BASE_DIR) / "loomera" / "branding" / "config.py"
        source = config_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(config_path))
        setting_reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "_settings"
        }
        self.assertEqual(setting_reads, set(BRAND_DEPLOYMENT_SETTING_NAMES))
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import environ", source)
        self.assertNotIn("loomera.settings.base", source)
        for forbidden in (
            "LANGUAGE_CODE",
            "LOOMERA_DEFAULT_LANGUAGE",
            "LOOMERA_DEFAULT_COUNTRY",
            "LOOMERA_DEFAULT_CURRENCY",
            "LOOMERA_DEFAULT_TIMEZONE",
            "MAP_PROVIDER",
            "SMS_PROVIDER",
            "PAYMENT_PROVIDER",
            "MESSAGING_ALLOWED_PROVIDERS",
        ):
            self.assertNotIn(forbidden, source)

    def test_brand_boundary_runtime_consumer_is_only_shared_template_context(self):
        project_root = Path(settings.BASE_DIR)
        config_path = project_root / "loomera" / "branding" / "config.py"
        test_path = project_root / "apps" / "main" / "test_production_settings_hygiene.py"
        occurrences: list[str] = []
        for root_name in ("apps", "loomera"):
            for path in (project_root / root_name).rglob("*.py"):
                if path in {config_path, test_path} or path.name.startswith("test_"):
                    continue
                source = path.read_text(encoding="utf-8")
                if "DeploymentBrandConfig" in source or "get_deployment_brand_config" in source:
                    occurrences.append(str(path.relative_to(project_root)))
        self.assertEqual(occurrences, ["loomera/branding/context_processors.py"])


class SharedBrandAssetConfigurationBoundaryTests(SimpleTestCase):
    expected_field_names = (
        "logo_glyph_path",
        "app_icon_path",
        "logo_header_path",
        "logo_primary_path",
        "favicon_svg_path",
        "favicon_ico_path",
        "favicon_16_path",
        "favicon_32_path",
        "favicon_48_path",
        "apple_touch_icon_path",
        "mask_icon_path",
        "webmanifest_path",
        "social_image_path",
        "social_image_width",
        "social_image_height",
    )

    def _import_brand_asset_settings(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for setting_name in BRAND_ASSET_SETTING_NAMES:
            env.pop(setting_name, None)
        env.update(
            {
                "SECRET_KEY": "test-only-brand-asset-settings",
                "DATABASE_URL": "sqlite:///brand-asset-settings.sqlite3",
                "DEBUG": "False",
                "ALLOWED_HOSTS": "localhost,127.0.0.1",
                "CSRF_TRUSTED_ORIGINS": "http://localhost,http://127.0.0.1",
                "ONLINE_PAYMENT_ENABLED": "False",
                "PAYMENT_MODE": "mock",
                **overrides,
            }
        )
        return subprocess.run(
            [sys.executable, "-c", BRAND_ASSET_SETTINGS_IMPORT_SCRIPT],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _loaded_asset_values(self, **overrides: str) -> dict[str, object]:
        result = self._import_brand_asset_settings(**overrides)
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        for line in result.stdout.splitlines():
            if line.startswith("LOOMERA_BRAND_ASSETS_JSON="):
                return json.loads(line.removeprefix("LOOMERA_BRAND_ASSETS_JSON="))
        self.fail(f"Brand asset payload missing from subprocess output: {result.stdout}")

    def _assert_invalid_asset_setting(self, setting_name: str, value: str) -> None:
        result = self._import_brand_asset_settings(**{setting_name: value})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn(setting_name, result.stderr)

    def test_exact_fifteen_setting_defaults_and_snapshot_are_loomera_compatible(self):
        self.assertEqual(self._loaded_asset_values(), BRAND_ASSET_DEFAULTS)
        config = get_deployment_brand_asset_config()
        self.assertIsInstance(config, DeploymentBrandAssetConfig)
        self.assertEqual(
            tuple(getattr(config, field_name) for field_name in self.expected_field_names),
            (
                "branding/logo/loomera-glyph-mark.png",
                "branding/logo/loomera-app-icon.png",
                "branding/logo/loomera-logo-header.png",
                "branding/logo/loomera-logo-primary.png",
                "branding/favicon/favicon.svg",
                "branding/favicon/favicon.ico",
                "branding/favicon/favicon-16x16.png",
                "branding/favicon/favicon-32x32.png",
                "branding/favicon/favicon-48x48.png",
                "branding/favicon/apple-touch-icon.png",
                "branding/favicon/safari-pinned-tab.svg",
                "branding/favicon/site.webmanifest",
                "branding/logo/loomera-logo-square.png",
                1254,
                1254,
            ),
        )

    def test_snapshot_is_frozen_and_public_api_is_exact(self):
        config = get_deployment_brand_asset_config()
        with self.assertRaises(FrozenInstanceError):
            config.logo_glyph_path = "branding/other.png"
        self.assertEqual(
            tuple(field.name for field in fields(DeploymentBrandAssetConfig)),
            self.expected_field_names,
        )
        self.assertEqual(
            brand_assets_module.__all__,
            ("DeploymentBrandAssetConfig", "get_deployment_brand_asset_config"),
        )
        self.assertEqual(
            {name for name in vars(DeploymentBrandAssetConfig) if not name.startswith("_")},
            set(self.expected_field_names),
        )

    def test_accessor_returns_fresh_uncached_snapshots(self):
        first = get_deployment_brand_asset_config()
        second = get_deployment_brand_asset_config()
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_accessor_reads_exactly_the_fifteen_approved_django_settings(self):
        assets_path = Path(settings.BASE_DIR) / "loomera" / "branding" / "assets.py"
        source = assets_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(assets_path))
        setting_reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "_settings"
        }
        self.assertEqual(setting_reads, set(BRAND_ASSET_SETTING_NAMES))
        for forbidden in (
            "os.environ",
            "import environ",
            "loomera.settings.base",
            "ImproperlyConfigured",
            ".objects",
            "request",
            "salon",
            "business",
            "cache",
            "LANGUAGE_CODE",
            "LOOMERA_DEFAULT_COUNTRY",
            "MAP_PROVIDER",
            "SMS_PROVIDER",
            "PAYMENT_PROVIDER",
        ):
            self.assertNotIn(forbidden, source)
        for default in BRAND_ASSET_DEFAULTS.values():
            if isinstance(default, str):
                self.assertNotIn(default, source)

    def test_static_path_contract_accepts_trimmed_relative_path(self):
        values = self._loaded_asset_values(
            BRAND_LOGO_GLYPH_STATIC_PATH="  buyer/brand/glyph.svg  "
        )
        self.assertEqual(values["BRAND_LOGO_GLYPH_STATIC_PATH"], "buyer/brand/glyph.svg")

    def test_static_path_contract_rejects_invalid_explicit_values(self):
        invalid_values = (
            "",
            "   ",
            "/branding/logo.png",
            "https://cdn.example.com/logo.png",
            "file://branding/logo.png",
            "C:/branding/logo.png",
            r"branding\logo.png",
            "branding/logo.png?version=1",
            "branding/logo.png#fragment",
            "./branding/logo.png",
            "branding/../logo.png",
            "branding/./logo.png",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                self._assert_invalid_asset_setting("BRAND_LOGO_GLYPH_STATIC_PATH", value)

    def test_social_image_dimensions_must_be_positive_integers(self):
        values = self._loaded_asset_values(
            BRAND_SOCIAL_IMAGE_WIDTH="1600",
            BRAND_SOCIAL_IMAGE_HEIGHT="900",
        )
        self.assertEqual(values["BRAND_SOCIAL_IMAGE_WIDTH"], 1600)
        self.assertEqual(values["BRAND_SOCIAL_IMAGE_HEIGHT"], 900)
        for setting_name in ("BRAND_SOCIAL_IMAGE_WIDTH", "BRAND_SOCIAL_IMAGE_HEIGHT"):
            for value in ("0", "-1", "1.5", "not-a-number"):
                with self.subTest(setting=setting_name, value=value):
                    self._assert_invalid_asset_setting(setting_name, value)


class SharedBrandTemplateContextTests(SimpleTestCase):
    context_processor_path = "loomera.branding.context_processors.deployment_brand"

    @staticmethod
    def _context() -> dict[str, object]:
        return {
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
        }

    def test_context_processor_returns_fresh_identity_and_asset_snapshots(self):
        first = deployment_brand(object())
        second = deployment_brand(object())
        self.assertEqual(set(first), {"deployment_brand", "deployment_brand_assets"})
        self.assertIsInstance(first["deployment_brand"], DeploymentBrandConfig)
        self.assertIsInstance(first["deployment_brand_assets"], DeploymentBrandAssetConfig)
        self.assertEqual(first["deployment_brand"].display_name, "Loomera")
        self.assertEqual(first["deployment_brand_assets"].social_image_width, 1254)
        self.assertIsNot(first["deployment_brand"], second["deployment_brand"])
        self.assertIsNot(first["deployment_brand_assets"], second["deployment_brand_assets"])

    def test_context_processor_is_registered_once_and_has_no_direct_context_reads(self):
        processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
        self.assertEqual(processors.count(self.context_processor_path), 1)
        processor_path = Path(settings.BASE_DIR) / "loomera" / "branding" / "context_processors.py"
        source = processor_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(processor_path))
        self.assertEqual(brand_context_processor_module.__all__, ("deployment_brand",))
        for forbidden in ("django.conf", "os.environ", "import environ", ".objects", "apps.accounts", "booking"):
            self.assertNotIn(forbidden, source.lower() if forbidden == "booking" else source)
        self.assertEqual(
            [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
                and node.id == "request"
                and isinstance(node.ctx, ast.Load)
            ],
            [],
        )

    @override_settings(BRAND_DISPLAY_NAME="Aurora")
    def test_alternate_brand_is_rendered_in_core_shell_metadata_without_inference(self):
        runtime_values = {
            "language_code": settings.LANGUAGE_CODE,
            "default_language": settings.LOOMERA_DEFAULT_LANGUAGE,
            "default_country": settings.LOOMERA_DEFAULT_COUNTRY,
            "default_currency": settings.LOOMERA_DEFAULT_CURRENCY,
            "default_timezone": settings.LOOMERA_DEFAULT_TIMEZONE,
            "sms_provider": settings.SMS_PROVIDER,
            "payment_provider": settings.PAYMENT_PROVIDER,
            "messaging_allowed_providers": tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
            "auth_user_model": settings.AUTH_USER_MODEL,
        }
        context = self._context()
        context.update({"hide_navbar": True, "hide_footer": True})
        rendered = render_to_string("base.html", context)
        for expected in (
            "<title>Aurora</title>",
            '<meta property="og:title" content="Aurora">',
            '<meta name="twitter:title" content="Aurora">',
            '<meta name="application-name" content="Aurora">',
            '<meta name="apple-mobile-web-app-title" content="Aurora">',
            '<meta property="og:site_name" content="Aurora">',
        ):
            self.assertIn(expected, rendered)
        self.assertEqual(settings.LANGUAGE_CODE, runtime_values["language_code"])
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, runtime_values["default_language"])
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, runtime_values["default_country"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, runtime_values["default_currency"])
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, runtime_values["default_timezone"])
        self.assertEqual(settings.SMS_PROVIDER, runtime_values["sms_provider"])
        self.assertEqual(settings.PAYMENT_PROVIDER, runtime_values["payment_provider"])
        self.assertEqual(tuple(settings.MESSAGING_ALLOWED_PROVIDERS), runtime_values["messaging_allowed_providers"])
        self.assertEqual(settings.AUTH_USER_MODEL, runtime_values["auth_user_model"])

    def test_default_head_asset_output_matches_existing_loomera_urls_dimensions_and_metadata(self):
        rendered = render_to_string("partials/brand/head_assets.html", self._context())
        for path in (
            "branding/favicon/favicon.svg",
            "branding/favicon/favicon.ico",
            "branding/favicon/favicon-16x16.png",
            "branding/favicon/favicon-32x32.png",
            "branding/favicon/favicon-48x48.png",
            "branding/favicon/apple-touch-icon.png",
            "branding/favicon/safari-pinned-tab.svg",
            "branding/favicon/site.webmanifest",
            "branding/logo/loomera-logo-square.png",
        ):
            self.assertIn(f"/static/{path}", rendered)
        self.assertIn('<meta property="og:image:width" content="1254">', rendered)
        self.assertIn('<meta property="og:image:height" content="1254">', rendered)
        self.assertIn('<meta property="og:locale" content="fa_IR">', rendered)
        self.assertIn('<meta property="og:type" content="website">', rendered)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', rendered)
        self.assertIn('<meta name="color-scheme" content="light dark">', rendered)
        for color in ("#FCFBFE", "#16131F", "#735CBE"):
            self.assertIn(color, rendered)

    def test_logo_variants_use_the_correct_asset_field_and_alt_contract(self):
        variants = {
            "glyph": "branding/logo/loomera-glyph-mark.png",
            "app-icon": "branding/logo/loomera-app-icon.png",
            "header": "branding/logo/loomera-logo-header.png",
            "compact": "branding/logo/loomera-logo-header.png",
            "full": "branding/logo/loomera-logo-primary.png",
        }
        for variant, path in variants.items():
            with self.subTest(variant=variant):
                context = self._context()
                context["logo_variant"] = variant
                rendered = render_to_string("partials/brand/logo.html", context)
                self.assertIn(f'/static/{path}', rendered)
                self.assertIn('alt="Loomera"', rendered)

        context = self._context()
        context.update({"logo_variant": "full", "alt_text": "Explicit buyer alt"})
        rendered = render_to_string("partials/brand/logo.html", context)
        self.assertIn('alt="Explicit buyer alt"', rendered)
        self.assertNotIn('alt="Loomera"', rendered)

        with override_settings(BRAND_DISPLAY_NAME="Aurora"):
            context = self._context()
            context["logo_variant"] = "full"
            rendered = render_to_string("partials/brand/logo.html", context)
            self.assertIn('alt="Aurora"', rendered)

    @override_settings(
        BRAND_LOGO_GLYPH_STATIC_PATH="buyer/logo/glyph.svg",
        BRAND_APP_ICON_STATIC_PATH="buyer/logo/app.png",
        BRAND_LOGO_HEADER_STATIC_PATH="buyer/logo/header.svg",
        BRAND_LOGO_PRIMARY_STATIC_PATH="buyer/logo/primary.svg",
        BRAND_FAVICON_SVG_STATIC_PATH="buyer/favicon/favicon.svg",
        BRAND_FAVICON_ICO_STATIC_PATH="buyer/favicon/favicon.ico",
        BRAND_FAVICON_16_STATIC_PATH="buyer/favicon/16.png",
        BRAND_FAVICON_32_STATIC_PATH="buyer/favicon/32.png",
        BRAND_FAVICON_48_STATIC_PATH="buyer/favicon/48.png",
        BRAND_APPLE_TOUCH_ICON_STATIC_PATH="buyer/favicon/apple.png",
        BRAND_MASK_ICON_STATIC_PATH="buyer/favicon/mask.svg",
        BRAND_WEBMANIFEST_STATIC_PATH="buyer/favicon/site.webmanifest",
        BRAND_SOCIAL_IMAGE_STATIC_PATH="buyer/social/card.png",
        BRAND_SOCIAL_IMAGE_WIDTH=1600,
        BRAND_SOCIAL_IMAGE_HEIGHT=900,
    )
    def test_alternate_static_asset_settings_render_without_runtime_inference(self):
        runtime_values = {
            "language_code": settings.LANGUAGE_CODE,
            "default_language": settings.LOOMERA_DEFAULT_LANGUAGE,
            "default_country": settings.LOOMERA_DEFAULT_COUNTRY,
            "default_currency": settings.LOOMERA_DEFAULT_CURRENCY,
            "default_timezone": settings.LOOMERA_DEFAULT_TIMEZONE,
            "default_calendar": settings.LOOMERA_DEFAULT_CALENDAR,
            "sms_provider": settings.SMS_PROVIDER,
            "payment_provider": settings.PAYMENT_PROVIDER,
            "messaging_allowed_providers": tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
            "auth_user_model": settings.AUTH_USER_MODEL,
        }
        context = self._context()
        head = render_to_string("partials/brand/head_assets.html", context)
        self.assertIn('/static/buyer/favicon/favicon.svg', head)
        self.assertIn('/static/buyer/favicon/site.webmanifest', head)
        self.assertIn('/static/buyer/social/card.png', head)
        self.assertIn('<meta property="og:image:width" content="1600">', head)
        self.assertIn('<meta property="og:image:height" content="900">', head)
        for variant, path in (
            ("glyph", "buyer/logo/glyph.svg"),
            ("app-icon", "buyer/logo/app.png"),
            ("header", "buyer/logo/header.svg"),
            ("full", "buyer/logo/primary.svg"),
        ):
            variant_context = dict(context)
            variant_context["logo_variant"] = variant
            self.assertIn(f"/static/{path}", render_to_string("partials/brand/logo.html", variant_context))
        self.assertEqual(settings.LANGUAGE_CODE, runtime_values["language_code"])
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, runtime_values["default_language"])
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, runtime_values["default_country"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, runtime_values["default_currency"])
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, runtime_values["default_timezone"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, runtime_values["default_calendar"])
        self.assertEqual(settings.SMS_PROVIDER, runtime_values["sms_provider"])
        self.assertEqual(settings.PAYMENT_PROVIDER, runtime_values["payment_provider"])
        self.assertEqual(tuple(settings.MESSAGING_ALLOWED_PROVIDERS), runtime_values["messaging_allowed_providers"])
        self.assertEqual(settings.AUTH_USER_MODEL, runtime_values["auth_user_model"])

    def test_compatibility_brand_locale_descriptions_assets_colors_and_manifest_remain_unchanged(self):
        context = self._context()
        context.update({"hide_navbar": True, "hide_footer": True})
        rendered = render_to_string("base.html", context)
        self.assertIn("<title>Loomera</title>", rendered)
        self.assertIn('<html lang="fa" dir="rtl">', rendered)
        self.assertIn('<meta property="og:locale" content="fa_IR">', rendered)
        project_root = Path(settings.BASE_DIR)
        base_source = (project_root / "templates" / "base.html").read_text(encoding="utf-8")
        head_source = (project_root / "templates" / "partials" / "brand" / "head_assets.html").read_text(encoding="utf-8")
        logo_source = (project_root / "templates" / "partials" / "brand" / "logo.html").read_text(encoding="utf-8")
        settings_source = (project_root / "loomera" / "settings" / "base.py").read_text(encoding="utf-8")
        manifest = json.loads((project_root / "static" / "branding" / "favicon" / "site.webmanifest").read_text(encoding="utf-8"))
        self.assertIn(
            "Loomera، پلتفرم انتخاب و رزرو خدمات زیبایی، aesthetic treatments، ماساژ و wellness با تجربه‌ای آرام، دقیق و قابل‌اعتماد.",
            base_source,
        )
        self.assertEqual(base_source.count("انتخاب روشن‌تر و رزرو آرام‌تر خدمات زیبایی و تندرستی."), 2)
        for value in ("#FCFBFE", "#16131F", "#735CBE"):
            self.assertIn(value, head_source)
        for field_name in (
            "favicon_svg_path",
            "favicon_ico_path",
            "favicon_16_path",
            "favicon_32_path",
            "favicon_48_path",
            "apple_touch_icon_path",
            "mask_icon_path",
            "webmanifest_path",
            "social_image_path",
            "social_image_width",
            "social_image_height",
        ):
            self.assertIn(f"deployment_brand_assets.{field_name}", head_source)
        for field_name in ("logo_glyph_path", "app_icon_path", "logo_header_path", "logo_primary_path"):
            self.assertIn(f"deployment_brand_assets.{field_name}", logo_source)
        self.assertIn("deployment_brand.display_name", logo_source)
        for forbidden_setting in (
            "BRAND_COLOR",
            "BRAND_THEME_COLOR",
            "BRAND_BACKGROUND_COLOR",
            "BRAND_MASK_COLOR",
        ):
            self.assertNotIn(forbidden_setting, settings_source)
        self.assertEqual(manifest["name"], "Loomera")
        self.assertEqual(manifest["short_name"], "Loomera")
        self.assertEqual(manifest["theme_color"], "#735CBE")
        self.assertEqual(manifest["background_color"], "#FCFBFE")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(len(manifest["icons"]), 3)
