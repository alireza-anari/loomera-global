from __future__ import annotations

import ast
from contextlib import ExitStack
from io import BytesIO
import hashlib
from dataclasses import FrozenInstanceError, fields, replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.template import engines
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from PIL import Image

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
            "BRAND_LOGO_GLYPH_STATIC_PATH": base.BRAND_LOGO_GLYPH_STATIC_PATH,
            "BRAND_APP_ICON_STATIC_PATH": base.BRAND_APP_ICON_STATIC_PATH,
            "BRAND_LOGO_HEADER_STATIC_PATH": base.BRAND_LOGO_HEADER_STATIC_PATH,
            "BRAND_LOGO_PRIMARY_STATIC_PATH": base.BRAND_LOGO_PRIMARY_STATIC_PATH,
            "BRAND_FAVICON_SVG_STATIC_PATH": base.BRAND_FAVICON_SVG_STATIC_PATH,
            "BRAND_FAVICON_ICO_STATIC_PATH": base.BRAND_FAVICON_ICO_STATIC_PATH,
            "BRAND_FAVICON_16_STATIC_PATH": base.BRAND_FAVICON_16_STATIC_PATH,
            "BRAND_FAVICON_32_STATIC_PATH": base.BRAND_FAVICON_32_STATIC_PATH,
            "BRAND_FAVICON_48_STATIC_PATH": base.BRAND_FAVICON_48_STATIC_PATH,
            "BRAND_APPLE_TOUCH_ICON_STATIC_PATH": base.BRAND_APPLE_TOUCH_ICON_STATIC_PATH,
            "BRAND_MASK_ICON_STATIC_PATH": base.BRAND_MASK_ICON_STATIC_PATH,
            "BRAND_WEBMANIFEST_STATIC_PATH": base.BRAND_WEBMANIFEST_STATIC_PATH,
            "BRAND_SOCIAL_IMAGE_STATIC_PATH": base.BRAND_SOCIAL_IMAGE_STATIC_PATH,
            "BRAND_QUICK_LINK_MIRROR_LABEL_ART_STATIC_PATH": base.BRAND_QUICK_LINK_MIRROR_LABEL_ART_STATIC_PATH,
            "BRAND_QUICK_LINK_BUSINESS_CARD_FRONT_ART_STATIC_PATH": base.BRAND_QUICK_LINK_BUSINESS_CARD_FRONT_ART_STATIC_PATH,
            "BRAND_QUICK_LINK_BUSINESS_CARD_BACK_ART_STATIC_PATH": base.BRAND_QUICK_LINK_BUSINESS_CARD_BACK_ART_STATIC_PATH,
            "BRAND_QUICK_LINK_TABLE_STAND_ART_STATIC_PATH": base.BRAND_QUICK_LINK_TABLE_STAND_ART_STATIC_PATH,
            "BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH": base.BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH,
            "BRAND_LOGIN_HERO_STATIC_PATH": base.BRAND_LOGIN_HERO_STATIC_PATH,
            "BRAND_CUSTOMER_SIGNUP_HERO_STATIC_PATH": base.BRAND_CUSTOMER_SIGNUP_HERO_STATIC_PATH,
            "BRAND_STYLIST_SIGNUP_HERO_STATIC_PATH": base.BRAND_STYLIST_SIGNUP_HERO_STATIC_PATH,
            "BRAND_MANAGER_SIGNUP_HERO_STATIC_PATH": base.BRAND_MANAGER_SIGNUP_HERO_STATIC_PATH,
            "BRAND_SOCIAL_IMAGE_WIDTH": base.BRAND_SOCIAL_IMAGE_WIDTH,
            "BRAND_SOCIAL_IMAGE_HEIGHT": base.BRAND_SOCIAL_IMAGE_HEIGHT,
        },
        sort_keys=True,
    )
)
"""


class ProductionSettingsHygieneTests(SimpleTestCase):
    def _import_base_settings(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for setting_name in (*GLOBAL_DEPLOYMENT_SETTING_NAMES, *BRAND_ASSET_SETTING_NAMES):
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

    def test_brand_static_path_contract_trims_valid_relative_path_and_rejects_invalid_values(self):
        values = self._loaded_values(
            BRAND_LOGO_GLYPH_STATIC_PATH=" custom/branding/glyph.svg "
        )
        self.assertEqual(
            values["BRAND_LOGO_GLYPH_STATIC_PATH"],
            "custom/branding/glyph.svg",
        )

        invalid_values = (
            "",
            "/branding/logo.png",
            "https://cdn.example.com/logo.png",
            "branding\\logo.png",
            "branding/logo.png?version=1",
            "branding/logo.png#mark",
            "branding/../logo.png",
            "branding/./logo.png",
            "C:/branding/logo.png",
        )
        for invalid_value in invalid_values:
            with self.subTest(value=invalid_value):
                self._assert_invalid_configuration(
                    "BRAND_LOGO_GLYPH_STATIC_PATH",
                    BRAND_LOGO_GLYPH_STATIC_PATH=invalid_value,
                )

    def test_quick_link_art_settings_use_exact_defaults_and_existing_validator(self):
        values = self._loaded_values()
        settings_path = Path(settings.BASE_DIR) / "loomera" / "settings" / "base.py"
        tree = ast.parse(settings_path.read_text(encoding="utf-8"))
        definitions = {
            node.targets[0].id: node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in QUICK_LINK_ART_SETTING_DEFAULTS
        }
        self.assertEqual(set(definitions), set(QUICK_LINK_ART_SETTING_DEFAULTS))

        for name, default in QUICK_LINK_ART_SETTING_DEFAULTS.items():
            with self.subTest(setting=name):
                self.assertEqual(values[name], default)
                call = definitions[name]
                self.assertIsInstance(call, ast.Call)
                self.assertIsInstance(call.func, ast.Name)
                self.assertEqual(call.func.id, "_read_brand_static_path")
                self.assertEqual(
                    [ast.literal_eval(arg) for arg in call.args],
                    [name, default],
                )
                self.assertEqual(
                    self._loaded_values(**{name: "  buyer/quick-links/alternate.png  "})[name],
                    "buyer/quick-links/alternate.png",
                )

    def test_each_quick_link_art_setting_rejects_all_invalid_static_paths(self):
        invalid_values = (
            "",
            "   ",
            "/absolute/artwork.png",
            "C:/absolute/artwork.png",
            r"branding\\quick-links\\artwork.png",
            "https://cdn.example.test/artwork.png",
            "branding/quick-links/artwork.png?rev=1",
            "branding/quick-links/artwork.png#label",
            "branding/../artwork.png",
            "branding/./artwork.png",
        )
        for name in QUICK_LINK_ART_SETTING_DEFAULTS:
            for invalid in invalid_values:
                with self.subTest(setting=name, value=invalid):
                    self._assert_invalid_configuration(name, **{name: invalid})

    def test_qr_glyph_setting_default_and_trimmed_override(self):
        name = "BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH"
        self.assertEqual(
            self._loaded_values()[name],
            "branding/logo/loomera-glyph-mark-square-transparent-512.png",
        )
        self.assertEqual(
            self._loaded_values(**{name: "  buyer/qr/glyph.png  "})[name],
            "buyer/qr/glyph.png",
        )

    def test_qr_glyph_setting_rejects_invalid_static_paths(self):
        name = "BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH"
        for value in (
            "", "   ", "/glyph.png", "C:/glyph.png", r"buyer\glyph.png",
            "https://buyer.test/glyph.png", "buyer/glyph.png?v=1",
            "buyer/glyph.png#mark", "buyer/../glyph.png", "buyer/./glyph.png",
        ):
            with self.subTest(value=value):
                self._assert_invalid_configuration(name, **{name: value})


    def test_auth_hero_settings_use_exact_defaults_and_existing_validator(self):
        values = self._loaded_values()
        settings_path = Path(settings.BASE_DIR) / "loomera" / "settings" / "base.py"
        tree = ast.parse(settings_path.read_text(encoding="utf-8"))
        definitions = {
            node.targets[0].id: node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in AUTH_ARTWORK_SETTING_DEFAULTS
        }
        self.assertEqual(set(definitions), set(AUTH_ARTWORK_SETTING_DEFAULTS))
        for name, default in AUTH_ARTWORK_SETTING_DEFAULTS.items():
            with self.subTest(setting=name):
                self.assertEqual(values[name], default)
                call = definitions[name]
                self.assertIsInstance(call, ast.Call)
                self.assertIsInstance(call.func, ast.Name)
                self.assertEqual(call.func.id, "_read_brand_static_path")
                self.assertEqual(
                    [ast.literal_eval(arg) for arg in call.args],
                    [name, default],
                )
                self.assertEqual(
                    self._loaded_values(**{name: "  buyer/auth/alternate-hero.png  "})[name],
                    "buyer/auth/alternate-hero.png",
                )

    def test_auth_hero_settings_reject_invalid_static_paths(self):
        invalid_values = (
            "", "   ", "/absolute/hero.png", "C:/hero.png",
            r"buyer\\auth\\hero.png", "https://buyer.test/hero.png",
            "buyer/hero.png?rev=1", "buyer/hero.png#anchor",
            "buyer/../hero.png", "buyer/./hero.png",
        )
        for name in AUTH_ARTWORK_SETTING_DEFAULTS:
            for invalid in invalid_values:
                with self.subTest(setting=name, value=invalid):
                    self._assert_invalid_configuration(name, **{name: invalid})

    def test_brand_social_image_dimensions_must_be_positive_integers(self):
        values = self._loaded_values(
            BRAND_SOCIAL_IMAGE_WIDTH="1600",
            BRAND_SOCIAL_IMAGE_HEIGHT="900",
        )
        self.assertEqual(values["BRAND_SOCIAL_IMAGE_WIDTH"], 1600)
        self.assertEqual(values["BRAND_SOCIAL_IMAGE_HEIGHT"], 900)

        for setting_name in (
            "BRAND_SOCIAL_IMAGE_WIDTH",
            "BRAND_SOCIAL_IMAGE_HEIGHT",
        ):
            for invalid_value in ("0", "-1", "not-an-integer"):
                with self.subTest(setting=setting_name, value=invalid_value):
                    self._assert_invalid_configuration(
                        setting_name,
                        **{setting_name: invalid_value},
                    )



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


from loomera.branding import assets as brand_asset_config_module
from loomera.branding import colors as brand_color_config_module
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
from loomera.branding.colors import (
    DeploymentBrandColorConfig,
    get_deployment_brand_color_config,
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
    "LOOMERA_CALENDAR_PRODID",
    "LOOMERA_CALENDAR_NAME",
    "BRAND_DISPLAY_NAME_FA",
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
    "BRAND_QUICK_LINK_MIRROR_LABEL_ART_STATIC_PATH",
    "BRAND_QUICK_LINK_BUSINESS_CARD_FRONT_ART_STATIC_PATH",
    "BRAND_QUICK_LINK_BUSINESS_CARD_BACK_ART_STATIC_PATH",
    "BRAND_QUICK_LINK_TABLE_STAND_ART_STATIC_PATH",
    "BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH",
    "BRAND_LOGIN_HERO_STATIC_PATH",
    "BRAND_CUSTOMER_SIGNUP_HERO_STATIC_PATH",
    "BRAND_STYLIST_SIGNUP_HERO_STATIC_PATH",
    "BRAND_MANAGER_SIGNUP_HERO_STATIC_PATH",
    "BRAND_SOCIAL_IMAGE_WIDTH",
    "BRAND_SOCIAL_IMAGE_HEIGHT",
)

AUTH_ARTWORK_SETTING_DEFAULTS = {
    "BRAND_LOGIN_HERO_STATIC_PATH": "branding/auth/login-desktop-hero.png",
    "BRAND_CUSTOMER_SIGNUP_HERO_STATIC_PATH": "branding/auth/customer-signup-hero.png",
    "BRAND_STYLIST_SIGNUP_HERO_STATIC_PATH": "branding/auth/stylist-signup-hero.png",
    "BRAND_MANAGER_SIGNUP_HERO_STATIC_PATH": "branding/auth/manager-signup-hero.png",
}


QUICK_LINK_ART_SETTING_DEFAULTS = {
    "BRAND_QUICK_LINK_MIRROR_LABEL_ART_STATIC_PATH": "branding/quick-links/mirror-label-print-art.png",
    "BRAND_QUICK_LINK_BUSINESS_CARD_FRONT_ART_STATIC_PATH": "branding/quick-links/business-card-front.png",
    "BRAND_QUICK_LINK_BUSINESS_CARD_BACK_ART_STATIC_PATH": "branding/quick-links/business-card-back.png",
    "BRAND_QUICK_LINK_TABLE_STAND_ART_STATIC_PATH": "branding/quick-links/table-stand.png",
}

QUICK_LINK_ART_BUYER_PATHS = {
    "BRAND_QUICK_LINK_MIRROR_LABEL_ART_STATIC_PATH": "buyer/quick-links/mirror-label-print-art.png",
    "BRAND_QUICK_LINK_BUSINESS_CARD_FRONT_ART_STATIC_PATH": "buyer/quick-links/business-card-front.png",
    "BRAND_QUICK_LINK_BUSINESS_CARD_BACK_ART_STATIC_PATH": "buyer/quick-links/business-card-back.png",
    "BRAND_QUICK_LINK_TABLE_STAND_ART_STATIC_PATH": "buyer/quick-links/table-stand.png",
}

BRAND_COLOR_SETTING_NAMES = (
    "BRAND_PRIMARY_COLOR",
    "BRAND_PRIMARY_HOVER_COLOR",
    "BRAND_PRIMARY_ACTIVE_COLOR",
    "BRAND_PRIMARY_SOFT_COLOR",
    "BRAND_SECONDARY_COLOR",
    "BRAND_ACCENT_COLOR",
    "BRAND_BACKGROUND_COLOR",
    "BRAND_SURFACE_COLOR",
    "BRAND_TEXT_PRIMARY_COLOR",
    "BRAND_TEXT_ON_PRIMARY_COLOR",
    "BRAND_BROWSER_THEME_DARK_COLOR",
)

BRAND_COLOR_DEFAULTS = {
    "BRAND_PRIMARY_COLOR": "#735CBE",
    "BRAND_PRIMARY_HOVER_COLOR": "#886FD6",
    "BRAND_PRIMARY_ACTIVE_COLOR": "#57526E",
    "BRAND_PRIMARY_SOFT_COLOR": "#EEE8FA",
    "BRAND_SECONDARY_COLOR": "#9B80E0",
    "BRAND_ACCENT_COLOR": "#A7C8A1",
    "BRAND_BACKGROUND_COLOR": "#FCFBFE",
    "BRAND_SURFACE_COLOR": "#FFFFFF",
    "BRAND_TEXT_PRIMARY_COLOR": "#2E2A3C",
    "BRAND_TEXT_ON_PRIMARY_COLOR": "#FFFFFF",
    "BRAND_BROWSER_THEME_DARK_COLOR": "#16131F",
}

BRAND_COLOR_SETTINGS_IMPORT_SCRIPT = r"""
import json
from loomera.settings import base

names = (
    "BRAND_PRIMARY_COLOR",
    "BRAND_PRIMARY_HOVER_COLOR",
    "BRAND_PRIMARY_ACTIVE_COLOR",
    "BRAND_PRIMARY_SOFT_COLOR",
    "BRAND_SECONDARY_COLOR",
    "BRAND_ACCENT_COLOR",
    "BRAND_BACKGROUND_COLOR",
    "BRAND_SURFACE_COLOR",
    "BRAND_TEXT_PRIMARY_COLOR",
    "BRAND_TEXT_ON_PRIMARY_COLOR",
    "BRAND_BROWSER_THEME_DARK_COLOR",
)
print(
    "LOOMERA_BRAND_COLORS_JSON="
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
        "calendar_prodid",
        "calendar_name",
        "display_name_fa",
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
        self.assertEqual(
            config.default_from_email,
            "Loomera <no-reply@loomera.local>",
        )
        self.assertEqual(config.support_email, "support@loomera.local")
        self.assertEqual(config.partner_email, "partners@loomera.local")
        self.assertEqual(config.marketing_email, "hello@loomera.local")
        self.assertEqual(config.calendar_prodid, "-//Loomera//Appointment//FA")
        self.assertEqual(config.calendar_name, "Loomera Appointment")
        self.assertEqual(config.display_name_fa, "لومرا")

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
            (
                "DeploymentBrandConfig",
                "get_deployment_brand_config",
            ),
        )
        self.assertEqual(
            {name for name in vars(DeploymentBrandConfig) if not name.startswith("_")},
            set(self.expected_field_names),
        )

    @override_settings(
        BRAND_NAME="Acme",
        BRAND_DISPLAY_NAME="Acme Global",
        BRAND_DISPLAY_NAME_FA="آرورا",
        BRAND_DOMAIN="example.com",
        PUBLIC_BASE_URL="https://www.example.com",
        SITE_URL="https://app.example.com",
        LOOMERA_EMAIL_SENDER_NAME="Acme Mail",
        DEFAULT_FROM_EMAIL="Acme Mail <no-reply@example.com>",
        LOOMERA_SUPPORT_EMAIL="support@example.com",
        LOOMERA_PARTNER_EMAIL="partners@example.com",
        LOOMERA_MARKETING_EMAIL="hello@example.com",
        LOOMERA_CALENDAR_PRODID="-//Aurora Corp//Booking//EN",
        LOOMERA_CALENDAR_NAME="Aurora Appointments",
    )
    def test_overridden_brand_settings_are_reflected_without_runtime_inference(self):
        language_code = settings.LANGUAGE_CODE
        time_zone = settings.TIME_ZONE
        default_language = settings.LOOMERA_DEFAULT_LANGUAGE
        default_country = settings.LOOMERA_DEFAULT_COUNTRY
        default_currency = settings.LOOMERA_DEFAULT_CURRENCY
        default_timezone = settings.LOOMERA_DEFAULT_TIMEZONE
        sms_provider = settings.SMS_PROVIDER
        payment_provider = settings.PAYMENT_PROVIDER
        messaging_allowed_providers = tuple(settings.MESSAGING_ALLOWED_PROVIDERS)

        config = get_deployment_brand_config()

        self.assertEqual(config.name, "Acme")
        self.assertEqual(config.display_name, "Acme Global")
        self.assertEqual(config.display_name_fa, "آرورا")
        self.assertEqual(config.domain, "example.com")
        self.assertEqual(config.public_base_url, "https://www.example.com")
        self.assertEqual(config.site_url, "https://app.example.com")
        self.assertEqual(config.email_sender_name, "Acme Mail")
        self.assertEqual(
            config.default_from_email,
            "Acme Mail <no-reply@example.com>",
        )
        self.assertEqual(config.support_email, "support@example.com")
        self.assertEqual(config.partner_email, "partners@example.com")
        self.assertEqual(config.marketing_email, "hello@example.com")
        self.assertEqual(config.calendar_prodid, "-//Aurora Corp//Booking//EN")
        self.assertEqual(config.calendar_name, "Aurora Appointments")

        self.assertEqual(settings.LANGUAGE_CODE, language_code)
        self.assertEqual(settings.TIME_ZONE, time_zone)
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, default_language)
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, default_country)
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, default_currency)
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, default_timezone)
        self.assertEqual(settings.SMS_PROVIDER, sms_provider)
        self.assertEqual(settings.PAYMENT_PROVIDER, payment_provider)
        self.assertEqual(
            tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
            messaging_allowed_providers,
        )

    def test_accessor_returns_a_fresh_snapshot_per_call(self):
        first = get_deployment_brand_config()
        second = get_deployment_brand_config()

        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_accessor_reads_only_the_thirteen_resolved_django_settings(self):
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
        self.assertNotIn("LANGUAGE_CODE", source)
        self.assertNotIn("LOOMERA_DEFAULT_LANGUAGE", source)
        self.assertNotIn("LOOMERA_DEFAULT_COUNTRY", source)
        self.assertNotIn("LOOMERA_DEFAULT_CURRENCY", source)
        self.assertNotIn("LOOMERA_DEFAULT_TIMEZONE", source)
        self.assertNotIn("MAP_PROVIDER", source)
        self.assertNotIn("SMS_PROVIDER", source)
        self.assertNotIn("PAYMENT_PROVIDER", source)
        self.assertNotIn("MESSAGING_ALLOWED_PROVIDERS", source)

    def test_brand_boundary_runtime_consumers_are_explicitly_approved(self):
        project_root = Path(settings.BASE_DIR)
        config_path = project_root / "loomera" / "branding" / "config.py"
        test_path = project_root / "apps" / "main" / "test_production_settings_hygiene.py"
        occurrences: list[str] = []

        for root_name in ("apps", "loomera"):
            for path in (project_root / root_name).rglob("*.py"):
                if path in {config_path, test_path} or path.name.startswith("test_"):
                    continue
                source = path.read_text(encoding="utf-8")
                if (
                    "DeploymentBrandConfig" in source
                    or "get_deployment_brand_config" in source
                ):
                    occurrences.append(path.relative_to(project_root).as_posix())

        self.assertCountEqual(
            occurrences,
            [
                "apps/api/v1/views.py",
                "apps/articles/views.py",
                "apps/help_center/ai.py",
                "apps/main/seo.py",
                "apps/notifications/delivery.py",
                "apps/orders/notification_delivery.py",
                "apps/orders/quick_link_print_templates.py",
                "apps/orders/views.py",
                "loomera/branding/context_processors.py",
            ],
        )


class ReportsPdfDeploymentBrandIdentityTests(SimpleTestCase):
    """Active FPDF export uses deployment identity without changing report data."""

    @staticmethod
    def _report_source():
        return (
            Path(settings.BASE_DIR) / "apps" / "dashboards" / "reports_components.py"
        ).read_text(encoding="utf-8")

    def test_pdf_source_reads_fresh_brand_and_asset_snapshots(self):
        source = self._report_source()
        self.assertIn("get_deployment_brand_config()", source)
        self.assertIn("get_deployment_brand_asset_config()", source)
        self.assertIn("logo_header_path", source)
        self.assertNotIn("loomera.ir  |  صفحه", source)
        self.assertNotIn('pdf.set_author("Loomera")', source)
        self.assertNotIn('or "گزارش Loomera"', source)
        self.assertNotIn('or "مجموعه Loomera"', source)
        self.assertIn('filename = f"loomera-salon-report-{salon.id}.pdf"', source)
        self.assertIn("def build_reports_csv_response(request, salon):", source)

    def test_pdf_identity_resolves_default_and_sequential_buyers(self):
        from apps.dashboards import reports_components as report_module

        instances = []

        class FakeFPDF:
            def __init__(self, *args, **kwargs):
                self.w = 210
                self.l_margin = 12
                self.r_margin = 12
                self.calls = []
                instances.append(self)

            def __getattr__(self, name):
                def record(*args, **kwargs):
                    self.calls.append((name, args, kwargs))
                return record

            def page_no(self):
                return 1

            def output(self):
                return b"%PDF-stub"

        with ExitStack() as stack:
            stack.enter_context(patch.object(
                report_module, "_report_pdf_dependencies", return_value=FakeFPDF,
            ))
            stack.enter_context(patch.object(
                report_module, "_report_pdf_font_paths",
                return_value=("regular.woff2", "bold.woff2"),
            ))
            resolver = stack.enter_context(patch.object(
                report_module, "_static_file_path",
                side_effect=lambda asset_path: f"/bundled/{asset_path}",
            ))
            for helper in (
                "_pdf_section_title",
                "_pdf_kpi_grid",
                "_pdf_status_breakdown",
                "_pdf_rank_list",
                "_pdf_detail_rows",
            ):
                stack.enter_context(patch.object(report_module, helper))

            for latin, domain, asset_path in (
                ("Loomera", "loomera.local", "branding/logo/loomera-logo-header.png"),
                ("Aurora", "aurora.example", "buyer/aurora/logo.png"),
                ("Second Buyer", "second.example", "buyer/second/logo.png"),
            ):
                with self.subTest(brand=latin):
                    with override_settings(
                        BRAND_DISPLAY_NAME=latin,
                        BRAND_DOMAIN=domain,
                        BRAND_LOGO_HEADER_STATIC_PATH=asset_path,
                    ):
                        result = report_module._build_reports_pdf_bytes(
                            {"workspace": {}, "filter_summary": {}},
                            SimpleNamespace(salon_name=""),
                        )
                        self.assertEqual(result, b"%PDF-stub")
                        pdf = instances[-1]
                        pdf.footer()
                        self.assertIn(("set_title", (f"گزارش {latin}",), {}), pdf.calls)
                        self.assertIn(("set_author", (latin,), {}), pdf.calls)
                        self.assertTrue(any(
                            name == "cell" and f"گزارش عملکرد مجموعه {latin}" in args
                            for name, args, _ in pdf.calls
                        ))
                        self.assertTrue(any(
                            name == "cell" and f"{domain}  |  صفحه ۱" in args
                            for name, args, _ in pdf.calls
                        ))
                        self.assertTrue(any(
                            name == "image" and args[0] == f"/bundled/{asset_path}"
                            for name, args, _ in pdf.calls
                        ))
                        self.assertEqual(resolver.call_args.args, (asset_path,))


class CalendarRuntimeBrandIdentityTests(SimpleTestCase):
    @staticmethod
    def _views_source_and_tree():
        path = Path(settings.BASE_DIR) / "apps" / "orders" / "views.py"
        source = path.read_text(encoding="utf-8")
        return source, ast.parse(source, filename=str(path))

    def test_calendar_runtime_uses_brand_boundary_without_direct_setting_reads(self):
        source, tree = self._views_source_and_tree()
        forbidden_settings = {
            "BRAND_DISPLAY_NAME",
            "BRAND_DOMAIN",
            "LOOMERA_CALENDAR_PRODID",
            "LOOMERA_CALENDAR_NAME",
        }
        direct_reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "settings"
            and node.attr in forbidden_settings
        }
        getattr_reads = {
            node.args[1].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "settings"
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in forbidden_settings
        }
        self.assertEqual(direct_reads | getattr_reads, set())

        imports = [
            alias
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "loomera.branding.config"
            for alias in node.names
            if alias.name == "get_deployment_brand_config"
        ]
        self.assertEqual(len(imports), 1)
        self.assertIsNone(imports[0].asname)

        for field_name in (
            "display_name",
            "name",
            "domain",
            "calendar_prodid",
            "calendar_name",
        ):
            self.assertIn(f"deployment_brand.{field_name}", source)

        self.assertNotIn("loomera-appointment", source)

    def test_calendar_runtime_resolves_one_fresh_snapshot_per_surface(self):
        _, tree = self._views_source_and_tree()
        detail_view = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AppointmentDetailView"
        )
        detail_method = next(
            node
            for node in detail_view.body
            if isinstance(node, ast.FunctionDef) and node.name == "get_context_data"
        )
        ics_view = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AppointmentICSView"
        )
        ics_method = next(
            node
            for node in ics_view.body
            if isinstance(node, ast.FunctionDef) and node.name == "get"
        )

        def accessor_calls(node):
            return [
                call
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "get_deployment_brand_config"
            ]

        self.assertEqual(len(accessor_calls(detail_method)), 1)
        self.assertEqual(len(accessor_calls(ics_method)), 1)
        self.assertEqual(
            len(
                [
                    call
                    for call in ast.walk(tree)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "get_deployment_brand_config"
                ]
            ),
            2,
        )
        module_level_calls = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "get_deployment_brand_config"
        ]
        self.assertEqual(module_level_calls, [])

    def test_calendar_brand_token_is_machine_safe_and_deployment_neutral(self):
        from apps.orders.views import _calendar_brand_token

        self.assertEqual(_calendar_brand_token("Loomera"), "loomera")
        self.assertEqual(_calendar_brand_token("Aurora"), "aurora")
        self.assertEqual(_calendar_brand_token(""), "brand")
        self.assertEqual(_calendar_brand_token("###"), "brand")


class SharedBrandColorConfigurationBoundaryTests(SimpleTestCase):
    expected_field_names = (
        "primary_color",
        "primary_hover_color",
        "primary_active_color",
        "primary_soft_color",
        "secondary_color",
        "accent_color",
        "background_color",
        "surface_color",
        "text_primary_color",
        "text_on_primary_color",
        "browser_theme_dark_color",
    )

    def _import_brand_color_settings(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        for setting_name in BRAND_COLOR_SETTING_NAMES:
            environment.pop(setting_name, None)
        environment.update(
            {
                "SECRET_KEY": "test-only-brand-color-settings",
                "DATABASE_URL": "sqlite:///brand-color-settings.sqlite3",
                "DEBUG": "False",
                "ALLOWED_HOSTS": "localhost,127.0.0.1",
                "CSRF_TRUSTED_ORIGINS": "http://localhost,http://127.0.0.1",
                "ONLINE_PAYMENT_ENABLED": "False",
                "PAYMENT_MODE": "mock",
                **overrides,
            }
        )
        return subprocess.run(
            [sys.executable, "-c", BRAND_COLOR_SETTINGS_IMPORT_SCRIPT],
            cwd=settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def _loaded_color_values(self, **overrides: str) -> dict[str, str]:
        result = self._import_brand_color_settings(**overrides)
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        for line in result.stdout.splitlines():
            if line.startswith("LOOMERA_BRAND_COLORS_JSON="):
                return json.loads(line.removeprefix("LOOMERA_BRAND_COLORS_JSON="))
        self.fail(f"Brand color payload missing from subprocess output: {result.stdout}")

    def _assert_invalid_color(self, setting_name: str, value: str) -> None:
        result = self._import_brand_color_settings(**{setting_name: value})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn(setting_name, result.stderr)

    @staticmethod
    def _template_context() -> dict[str, object]:
        return {
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
            "deployment_brand_colors": get_deployment_brand_color_config(),
        }

    def test_exact_eleven_compatibility_defaults_and_snapshot(self):
        self.assertEqual(self._loaded_color_values(), BRAND_COLOR_DEFAULTS)
        config = get_deployment_brand_color_config()
        self.assertIsInstance(config, DeploymentBrandColorConfig)
        self.assertEqual(
            tuple(getattr(config, field_name) for field_name in self.expected_field_names),
            tuple(BRAND_COLOR_DEFAULTS.values()),
        )

    def test_settings_trim_normalize_and_reject_non_hex_or_injection_values(self):
        self.assertEqual(
            self._loaded_color_values(BRAND_PRIMARY_COLOR="  #a1b2c3  ")[
                "BRAND_PRIMARY_COLOR"
            ],
            "#A1B2C3",
        )
        invalid_values = (
            "",
            "   ",
            "#123",
            "#12345678",
            "rgb(1, 2, 3)",
            "hsl(1 2% 3%)",
            "red",
            "var(--brand-primary)",
            "url(https://example.com/x)",
            "https://example.com/#123456",
            "123456",
            "#12345G",
            "#123456;body{display:none}",
            "#123456\n",
            "\n#123456",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                self._assert_invalid_color("BRAND_PRIMARY_COLOR", value)

    def test_snapshot_is_frozen_slotted_and_public_module_api_is_exact(self):
        config = get_deployment_brand_color_config()
        with self.assertRaises(FrozenInstanceError):
            config.primary_color = "#000000"
        self.assertFalse(hasattr(config, "__dict__"))
        self.assertEqual(
            tuple(field.name for field in fields(DeploymentBrandColorConfig)),
            self.expected_field_names,
        )
        self.assertEqual(
            brand_color_config_module.__all__,
            ("DeploymentBrandColorConfig", "get_deployment_brand_color_config"),
        )

    def test_accessor_returns_fresh_uncached_snapshots(self):
        first = get_deployment_brand_color_config()
        second = get_deployment_brand_color_config()
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_accessor_reads_exactly_eleven_resolved_settings_without_other_context(self):
        colors_path = Path(settings.BASE_DIR) / "loomera" / "branding" / "colors.py"
        source = colors_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(colors_path))
        setting_reads = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "_settings"
        }
        self.assertEqual(setting_reads, set(BRAND_COLOR_SETTING_NAMES))
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
            "LOOMERA_DEFAULT_LANGUAGE",
            "LOOMERA_DEFAULT_COUNTRY",
            "LOOMERA_DEFAULT_CURRENCY",
            "LOOMERA_DEFAULT_TIMEZONE",
            "LOOMERA_DEFAULT_CALENDAR",
            "MAP_PROVIDER",
            "SMS_PROVIDER",
            "PAYMENT_PROVIDER",
            "MESSAGING_ALLOWED_PROVIDERS",
        ):
            self.assertNotIn(forbidden, source)
        for default in set(BRAND_COLOR_DEFAULTS.values()):
            self.assertNotIn(default, source)

    def test_rgb_helpers_are_deterministic_css_ready_triplets(self):
        config = get_deployment_brand_color_config()
        self.assertEqual(
            (
                config.primary_rgb,
                config.primary_hover_rgb,
                config.primary_active_rgb,
                config.primary_soft_rgb,
                config.secondary_rgb,
                config.accent_rgb,
                config.background_rgb,
                config.surface_rgb,
                config.text_primary_rgb,
                config.text_on_primary_rgb,
            ),
            (
                "115 92 190",
                "136 111 214",
                "87 82 110",
                "238 232 250",
                "155 128 224",
                "167 200 161",
                "252 251 254",
                "255 255 255",
                "46 42 60",
                "255 255 255",
            ),
        )

    def test_default_metadata_and_runtime_bridge_preserve_core_loomera_palette(self):
        context = self._template_context()
        head = render_to_string("partials/brand/head_assets.html", context)
        page = render_to_string(
            "base.html",
            {**context, "hide_navbar": True, "hide_footer": True},
        )
        self.assertIn(
            'name="theme-color" media="(prefers-color-scheme: light)" content="#FCFBFE"',
            head,
        )
        self.assertIn(
            'name="theme-color" media="(prefers-color-scheme: dark)" content="#16131F"',
            head,
        )
        self.assertIn('name="msapplication-TileColor" content="#735CBE"', head)
        self.assertIn('color="#735CBE"', head)
        expected_declarations = (
            "--lm-primary: #735CBE;",
            "--lm-primary-hover: #886FD6;",
            "--lm-primary-active: #57526E;",
            "--lm-primary-soft: #EEE8FA;",
            "--lm-secondary: #9B80E0;",
            "--lm-accent: #A7C8A1;",
            "--lm-bg: #FCFBFE;",
            "--lm-app-surface: #FCFBFE;",
            "--lm-dashboard-surface: #FCFBFE;",
            "--lm-surface: #FFFFFF;",
            "--lm-card-surface: #FFFFFF;",
            "--lm-surface-raised: #FFFFFF;",
            "--lm-surface-elevated: #FFFFFF;",
            "--lm-sheet-surface: #FFFFFF;",
            "--lm-dashboard-panel: #FFFFFF;",
            "--lm-text-primary: #2E2A3C;",
            "--lm-text-on-primary: #FFFFFF;",
            "--lm-primary-rgb: 115 92 190;",
            "--lm-primary-hover-rgb: 136 111 214;",
            "--lm-primary-active-rgb: 87 82 110;",
            "--lm-primary-soft-rgb: 238 232 250;",
            "--lm-secondary-rgb: 155 128 224;",
            "--lm-accent-rgb: 167 200 161;",
            "--lm-bg-rgb: 252 251 254;",
            "--lm-surface-rgb: 255 255 255;",
            "--lm-text-primary-rgb: 46 42 60;",
            "--lm-text-on-primary-rgb: 255 255 255;",
            "--lm-border-selected: #735CBE;",
            "--lm-info: #735CBE;",
            "--lm-info-soft: #EEE8FA;",
            "--lm-selection: #EEE8FA;",
            "--lm-selected: #EEE8FA;",
        )
        self.assertIn('id="deployment-brand-color-tokens"', page)
        for declaration in expected_declarations:
            self.assertIn(declaration, page)

        base_source = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("|safe", base_source)
        self.assertNotIn("browser_theme_dark_color", base_source)
        self.assertIn('html:not([data-theme="dark"])', base_source)

    @override_settings(
        BRAND_PRIMARY_COLOR="#112233",
        BRAND_PRIMARY_HOVER_COLOR="#223344",
        BRAND_PRIMARY_ACTIVE_COLOR="#334455",
        BRAND_PRIMARY_SOFT_COLOR="#445566",
        BRAND_SECONDARY_COLOR="#556677",
        BRAND_ACCENT_COLOR="#667788",
        BRAND_BACKGROUND_COLOR="#778899",
        BRAND_SURFACE_COLOR="#8899AA",
        BRAND_TEXT_PRIMARY_COLOR="#99AABB",
        BRAND_TEXT_ON_PRIMARY_COLOR="#AABBCC",
        BRAND_BROWSER_THEME_DARK_COLOR="#0B0C0D",
    )
    def test_alternate_palette_wires_metadata_hex_rgb_and_preserves_other_boundaries(self):
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
        identity = get_deployment_brand_config()
        assets = get_deployment_brand_asset_config()
        context = self._template_context()
        head = render_to_string("partials/brand/head_assets.html", context)
        page = render_to_string(
            "base.html",
            {**context, "hide_navbar": True, "hide_footer": True},
        )

        self.assertIn('content="#778899"', head)
        self.assertIn('content="#0B0C0D"', head)
        self.assertIn('name="msapplication-TileColor" content="#112233"', head)
        self.assertIn('color="#112233"', head)
        expected = (
            "--lm-primary: #112233;",
            "--lm-primary-hover: #223344;",
            "--lm-primary-active: #334455;",
            "--lm-primary-soft: #445566;",
            "--lm-secondary: #556677;",
            "--lm-accent: #667788;",
            "--lm-bg: #778899;",
            "--lm-surface: #8899AA;",
            "--lm-text-primary: #99AABB;",
            "--lm-text-on-primary: #AABBCC;",
            "--lm-primary-rgb: 17 34 51;",
            "--lm-primary-hover-rgb: 34 51 68;",
            "--lm-primary-active-rgb: 51 68 85;",
            "--lm-primary-soft-rgb: 68 85 102;",
            "--lm-secondary-rgb: 85 102 119;",
            "--lm-accent-rgb: 102 119 136;",
            "--lm-bg-rgb: 119 136 153;",
            "--lm-surface-rgb: 136 153 170;",
            "--lm-text-primary-rgb: 153 170 187;",
            "--lm-text-on-primary-rgb: 170 187 204;",
            "--lm-border-selected: #112233;",
            "--lm-info: #112233;",
            "--lm-info-soft: #445566;",
            "--lm-selection: #445566;",
            "--lm-selected: #445566;",
        )
        for declaration in expected:
            self.assertIn(declaration, page)

        self.assertEqual(get_deployment_brand_config(), identity)
        self.assertEqual(get_deployment_brand_asset_config(), assets)
        self.assertEqual(settings.LANGUAGE_CODE, runtime_values["language_code"])
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, runtime_values["default_language"])
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, runtime_values["default_country"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, runtime_values["default_currency"])
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, runtime_values["default_timezone"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, runtime_values["default_calendar"])
        self.assertEqual(settings.SMS_PROVIDER, runtime_values["sms_provider"])
        self.assertEqual(settings.PAYMENT_PROVIDER, runtime_values["payment_provider"])
        self.assertEqual(
            tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
            runtime_values["messaging_allowed_providers"],
        )
        self.assertEqual(settings.AUTH_USER_MODEL, runtime_values["auth_user_model"])

    def test_color_boundary_runtime_consumer_is_only_shared_template_context(self):
        project_root = Path(settings.BASE_DIR)
        colors_path = project_root / "loomera" / "branding" / "colors.py"
        test_path = project_root / "apps" / "main" / "test_production_settings_hygiene.py"
        occurrences: list[str] = []
        for root_name in ("apps", "loomera"):
            for path in (project_root / root_name).rglob("*.py"):
                if path in {colors_path, test_path} or path.name.startswith("test_"):
                    continue
                source = path.read_text(encoding="utf-8")
                if (
                    "DeploymentBrandColorConfig" in source
                    or "get_deployment_brand_color_config" in source
                ):
                    occurrences.append(path.relative_to(project_root).as_posix())
        self.assertEqual(occurrences, ["loomera/branding/context_processors.py"])


class HomepagePersianBrandIdentityTests(SimpleTestCase):
    """The homepage's Persian name is deployment-scoped, not a literal or locale guess."""

    @staticmethod
    def _home_source():
        return (
            Path(settings.BASE_DIR) / "templates" / "pages" / "home.html"
        ).read_text(encoding="utf-8")

    @staticmethod
    def _render_home():
        return render_to_string(
            "pages/home.html",
            {
                "deployment_brand": get_deployment_brand_config(),
                "deployment_brand_assets": get_deployment_brand_asset_config(),
                "deployment_brand_colors": get_deployment_brand_color_config(),
            },
        )

    def test_homepage_has_exactly_twelve_persian_brand_bindings(self):
        source = self._home_source()
        self.assertEqual(source.count("{{ deployment_brand.display_name_fa }}"), 12)
        self.assertNotIn("لومرا", source)
        for stable_reference in (
            'data-page="loomera-home"',
            'id="loomera-intro-video-dialog"',
            "images/home/home-hero-v8.webp",
            "images/home/audience-customer.webp",
            "images/home/audience-stylist.webp",
            "images/home/audience-manager.webp",
            "images/home/customer-experience-v8.webp",
            "images/home/stylist-experience-v8.webp",
            "images/home/manager-experience-v8.webp",
            "videos/loomera-intro-poster.webp",
            "videos/loomera-intro-web.mp4",
        ):
            self.assertIn(stable_reference, source)

    def test_default_homepage_keeps_farsi_loomera_copy(self):
        self.assertEqual(get_deployment_brand_config().display_name_fa, "لومرا")
        rendered = self._render_home()
        self.assertIn("<title>لومرا | زیبایی، ساده‌تر</title>", rendered)
        self.assertIn('alt="مشتری لومرا"', rendered)
        self.assertIn("معرفی لومرا و نحوه کار با پلتفرم", rendered)

    def test_two_buyers_can_choose_independent_persian_names(self):
        for latin, persian in (
            ("Aurora", "آرورا"),
            ("Second Buyer", "نیلوفر"),
        ):
            with self.subTest(latin=latin, persian=persian):
                with override_settings(
                    BRAND_DISPLAY_NAME=latin,
                    BRAND_DISPLAY_NAME_FA=persian,
                ):
                    config = get_deployment_brand_config()
                    self.assertEqual(config.display_name, latin)
                    self.assertEqual(config.display_name_fa, persian)
                    rendered = self._render_home()
                    self.assertIn(
                        f"<title>{persian} | زیبایی، ساده‌تر</title>",
                        rendered,
                    )
                    self.assertIn(f'alt="مشتری {persian}"', rendered)
                    self.assertIn(
                        f"معرفی {persian} و نحوه کار با پلتفرم",
                        rendered,
                    )
                    self.assertNotIn("مشتری لومرا", rendered)

    @override_settings(BRAND_DISPLAY_NAME="Aurora")
    def test_latin_display_name_does_not_implicitly_change_persian_name(self):
        self.assertEqual(get_deployment_brand_config().display_name_fa, "لومرا")
        self.assertIn(
            "<title>لومرا | زیبایی، ساده‌تر</title>",
            self._render_home(),
        )

    @override_settings(BRAND_DISPLAY_NAME_FA="آرورا & <جدید>")
    def test_homepage_escapes_persian_brand_value_as_html(self):
        rendered = self._render_home()
        self.assertIn(
            "<title>آرورا &amp; &lt;جدید&gt; | زیبایی، ساده‌تر</title>",
            rendered,
        )
        self.assertIn('alt="مشتری آرورا &amp; &lt;جدید&gt;"', rendered)
        self.assertNotIn("آرورا & <جدید>", rendered)


class SharedBrandTemplateContextTests(SimpleTestCase):
    context_processor_path = "loomera.branding.context_processors.deployment_brand"

    def test_context_processor_returns_all_three_fresh_branding_snapshots(self):
        first = deployment_brand(object())
        second = deployment_brand(object())

        self.assertEqual(
            set(first),
            {"deployment_brand", "deployment_brand_assets", "deployment_brand_colors"},
        )
        self.assertIsInstance(first["deployment_brand"], DeploymentBrandConfig)
        self.assertIsInstance(
            first["deployment_brand_assets"],
            DeploymentBrandAssetConfig,
        )
        self.assertIsInstance(
            first["deployment_brand_colors"],
            DeploymentBrandColorConfig,
        )
        self.assertEqual(first["deployment_brand"].display_name, "Loomera")
        self.assertEqual(first["deployment_brand"].display_name_fa, "لومرا")
        self.assertEqual(first["deployment_brand_colors"].primary_color, "#735CBE")
        self.assertIsNot(first["deployment_brand"], second["deployment_brand"])
        self.assertIsNot(
            first["deployment_brand_assets"],
            second["deployment_brand_assets"],
        )
        self.assertIsNot(
            first["deployment_brand_colors"],
            second["deployment_brand_colors"],
        )

    def test_context_processor_is_registered_once_and_has_no_direct_context_reads(self):
        processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
        self.assertEqual(processors.count(self.context_processor_path), 1)

        processor_path = (
            Path(settings.BASE_DIR) / "loomera" / "branding" / "context_processors.py"
        )
        source = processor_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(processor_path))

        self.assertEqual(brand_context_processor_module.__all__, ("deployment_brand",))
        self.assertNotIn("django.conf", source)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import environ", source)
        self.assertNotIn(".objects", source)
        self.assertNotIn("apps.accounts", source)
        self.assertNotIn("booking", source.lower())
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
        rendered = render_to_string(
            "base.html",
            {
                "deployment_brand": get_deployment_brand_config(),
                "deployment_brand_assets": get_deployment_brand_asset_config(),
                "deployment_brand_colors": get_deployment_brand_color_config(),
                "hide_navbar": True,
                "hide_footer": True,
            },
        )

        self.assertIn("<title>Aurora</title>", rendered)
        self.assertIn('<meta property="og:title" content="Aurora">', rendered)
        self.assertIn('<meta name="twitter:title" content="Aurora">', rendered)
        self.assertIn('<meta name="application-name" content="Aurora">', rendered)
        self.assertIn('<meta name="apple-mobile-web-app-title" content="Aurora">', rendered)
        self.assertIn('<meta property="og:site_name" content="Aurora">', rendered)

        self.assertEqual(settings.LANGUAGE_CODE, runtime_values["language_code"])
        self.assertEqual(
            settings.LOOMERA_DEFAULT_LANGUAGE, runtime_values["default_language"]
        )
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, runtime_values["default_country"])
        self.assertEqual(
            settings.LOOMERA_DEFAULT_CURRENCY, runtime_values["default_currency"]
        )
        self.assertEqual(
            settings.LOOMERA_DEFAULT_TIMEZONE, runtime_values["default_timezone"]
        )
        self.assertEqual(settings.SMS_PROVIDER, runtime_values["sms_provider"])
        self.assertEqual(settings.PAYMENT_PROVIDER, runtime_values["payment_provider"])
        self.assertEqual(
            tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
            runtime_values["messaging_allowed_providers"],
        )
        self.assertEqual(settings.AUTH_USER_MODEL, runtime_values["auth_user_model"])

    def test_compatibility_brand_locale_descriptions_assets_and_colors_remain_unchanged(self):
        rendered = render_to_string(
            "base.html",
            {
                "deployment_brand": get_deployment_brand_config(),
                "deployment_brand_assets": get_deployment_brand_asset_config(),
                "deployment_brand_colors": get_deployment_brand_color_config(),
                "hide_navbar": True,
                "hide_footer": True,
            },
        )
        self.assertIn("<title>Loomera</title>", rendered)
        self.assertIn('<html lang="fa" dir="rtl">', rendered)
        self.assertIn('<meta property="og:locale" content="fa_IR">', rendered)

        project_root = Path(settings.BASE_DIR)
        base_source = (project_root / "templates" / "base.html").read_text(
            encoding="utf-8"
        )
        head_source = (
            project_root / "templates" / "partials" / "brand" / "head_assets.html"
        ).read_text(encoding="utf-8")
        settings_source = (
            project_root / "loomera" / "settings" / "base.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "Loomera، پلتفرم انتخاب و رزرو خدمات زیبایی، aesthetic treatments، ماساژ و wellness با تجربه‌ای آرام، دقیق و قابل‌اعتماد.",
            rendered,
        )
        self.assertIn(
            "{{ deployment_brand.display_name }}، پلتفرم انتخاب و رزرو خدمات زیبایی",
            base_source,
        )
        self.assertEqual(
            base_source.count("انتخاب روشن‌تر و رزرو آرام‌تر خدمات زیبایی و تندرستی."),
            2,
        )
        for value in ("#FCFBFE", "#16131F", "#735CBE"):
            self.assertIn(value, rendered)
        for asset_url in (
            "/static/branding/favicon/favicon.svg",
            "/static/branding/favicon/favicon.ico",
            "/static/branding/favicon/favicon-16x16.png",
            "/static/branding/favicon/favicon-32x32.png",
            "/static/branding/favicon/favicon-48x48.png",
            "/static/branding/favicon/apple-touch-icon.png",
            "/static/branding/favicon/safari-pinned-tab.svg",
            "/static/branding/favicon/site.webmanifest",
            "/static/branding/logo/loomera-logo-square.png",
        ):
            self.assertIn(asset_url, rendered)
        self.assertIn('<meta property="og:image:width" content="1254">', rendered)
        self.assertIn('<meta property="og:image:height" content="1254">', rendered)
        for forbidden_setting in (
            "BRAND_COLOR",
            "BRAND_THEME_COLOR",
            "BRAND_MASK_COLOR",
        ):
            self.assertNotIn(forbidden_setting, settings_source)


    def test_shared_shell_and_search_metadata_render_default_and_sequential_buyer_names(self):
        dashboard_source = (
            Path(settings.BASE_DIR) / "templates" / "dashboard_template.html"
        ).read_text(encoding="utf-8")
        dashboard_head = dashboard_source.split("<head>", 1)[1].split("</head>", 1)[0]

        for brand_name in ("Loomera", "Buyer Studio", "Second Buyer"):
            with override_settings(BRAND_DISPLAY_NAME=brand_name):
                brand_context = {
                    "deployment_brand": get_deployment_brand_config(),
                    "deployment_brand_assets": get_deployment_brand_asset_config(),
                    "deployment_brand_colors": get_deployment_brand_color_config(),
                }
                public_html = render_to_string(
                    "base.html",
                    {**brand_context, "hide_navbar": True, "hide_footer": True},
                )
                dashboard_head_html = engines["django"].from_string(
                    "{% load static %}\n" + dashboard_head
                ).render(brand_context)
                search_html = render_to_string("pages/search.html", brand_context)

                with self.subTest(brand=brand_name):
                    self.assertIn(
                        f'<meta name="description" content="{brand_name}، پلتفرم انتخاب و رزرو خدمات زیبایی، aesthetic treatments، ماساژ و wellness با تجربه‌ای آرام، دقیق و قابل‌اعتماد.">',
                        public_html,
                    )
                    self.assertIn(
                        f'<meta name="description" content="داشبورد مدیریت {brand_name} برای پیگیری نوبت‌ها، خدمات، تیم و مجموعه.">',
                        dashboard_head_html,
                    )
                    self.assertIn(
                        f'<meta property="og:title" content="داشبورد {brand_name}">',
                        dashboard_head_html,
                    )
                    self.assertIn(
                        f'<meta name="twitter:title" content="داشبورد {brand_name}">',
                        dashboard_head_html,
                    )
                    self.assertIn(
                        f'<meta property="og:description" content="مدیریت ساده‌تر و دقیق‌تر مجموعه در {brand_name}.">',
                        dashboard_head_html,
                    )
                    self.assertIn(
                        f'<meta name="twitter:description" content="مدیریت ساده‌تر و دقیق‌تر مجموعه در {brand_name}.">',
                        dashboard_head_html,
                    )
                    self.assertIn(
                        f'<title>جستجوی مجموعه و خدمات زیبایی | {brand_name}</title>',
                        search_html,
                    )
                    self.assertIn(
                        f'<meta name="description" content="جستجوی مجموعه‌ها، خدمات و متخصصان زیبایی در {brand_name} با فیلتر قیمت، امتیاز، تخفیف و زمان آزاد.">',
                        search_html,
                    )
                    self.assertIn('<html lang="fa" dir="rtl">', public_html)
                    self.assertIn('<meta property="og:locale" content="fa_IR">', public_html)


class SharedBrandAssetConfigurationTests(SimpleTestCase):
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
        "quick_link_mirror_label_art_path",
        "quick_link_business_card_front_art_path",
        "quick_link_business_card_back_art_path",
        "quick_link_table_stand_art_path",
        "quick_link_qr_glyph_path",
        "login_hero_path",
        "customer_signup_hero_path",
        "stylist_signup_hero_path",
        "manager_signup_hero_path",
        "social_image_width",
        "social_image_height",
    )

    def _template_context(self) -> dict[str, object]:
        return {
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
            "deployment_brand_colors": get_deployment_brand_color_config(),
        }

    def test_default_snapshot_preserves_exact_loomera_asset_compatibility_values(self):
        config = get_deployment_brand_asset_config()

        self.assertIsInstance(config, DeploymentBrandAssetConfig)
        self.assertEqual(config.logo_glyph_path, "branding/logo/loomera-glyph-mark.png")
        self.assertEqual(config.app_icon_path, "branding/logo/loomera-app-icon.png")
        self.assertEqual(config.logo_header_path, "branding/logo/loomera-logo-header.png")
        self.assertEqual(config.logo_primary_path, "branding/logo/loomera-logo-primary.png")
        self.assertEqual(config.favicon_svg_path, "branding/favicon/favicon.svg")
        self.assertEqual(config.favicon_ico_path, "branding/favicon/favicon.ico")
        self.assertEqual(config.favicon_16_path, "branding/favicon/favicon-16x16.png")
        self.assertEqual(config.favicon_32_path, "branding/favicon/favicon-32x32.png")
        self.assertEqual(config.favicon_48_path, "branding/favicon/favicon-48x48.png")
        self.assertEqual(
            config.apple_touch_icon_path,
            "branding/favicon/apple-touch-icon.png",
        )
        self.assertEqual(config.mask_icon_path, "branding/favicon/safari-pinned-tab.svg")
        self.assertEqual(config.webmanifest_path, "branding/favicon/site.webmanifest")
        self.assertEqual(config.social_image_path, "branding/logo/loomera-logo-square.png")
        self.assertEqual(config.quick_link_mirror_label_art_path, "branding/quick-links/mirror-label-print-art.png")
        self.assertEqual(config.quick_link_business_card_front_art_path, "branding/quick-links/business-card-front.png")
        self.assertEqual(config.quick_link_business_card_back_art_path, "branding/quick-links/business-card-back.png")
        self.assertEqual(config.quick_link_table_stand_art_path, "branding/quick-links/table-stand.png")
        self.assertEqual(config.quick_link_qr_glyph_path, "branding/logo/loomera-glyph-mark-square-transparent-512.png")
        self.assertEqual(config.login_hero_path, "branding/auth/login-desktop-hero.png")
        self.assertEqual(config.customer_signup_hero_path, "branding/auth/customer-signup-hero.png")
        self.assertEqual(config.stylist_signup_hero_path, "branding/auth/stylist-signup-hero.png")
        self.assertEqual(config.manager_signup_hero_path, "branding/auth/manager-signup-hero.png")
        self.assertEqual(config.social_image_width, 1254)
        self.assertEqual(config.social_image_height, 1254)

    def test_all_twenty_four_settings_are_defined_once_with_the_expected_validators(self):
        settings_path = Path(settings.BASE_DIR) / "loomera" / "settings" / "base.py"
        tree = ast.parse(
            settings_path.read_text(encoding="utf-8"),
            filename=str(settings_path),
        )
        expected_path_settings = set(BRAND_ASSET_SETTING_NAMES[:-2])
        expected_dimension_settings = set(BRAND_ASSET_SETTING_NAMES[-2:])
        assignment_calls: dict[str, str] = {}

        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id not in BRAND_ASSET_SETTING_NAMES:
                continue
            self.assertIsInstance(node.value, ast.Call)
            self.assertIsInstance(node.value.func, ast.Name)
            self.assertNotIn(target.id, assignment_calls)
            assignment_calls[target.id] = node.value.func.id

        self.assertEqual(set(assignment_calls), set(BRAND_ASSET_SETTING_NAMES))
        for setting_name in expected_path_settings:
            self.assertEqual(assignment_calls[setting_name], "_read_brand_static_path")
        for setting_name in expected_dimension_settings:
            self.assertEqual(
                assignment_calls[setting_name],
                "_read_positive_brand_dimension",
            )

    def test_snapshot_is_frozen_and_exposes_exact_public_contract(self):
        config = get_deployment_brand_asset_config()

        with self.assertRaises(FrozenInstanceError):
            config.logo_glyph_path = "other/logo.svg"

        self.assertEqual(
            tuple(field.name for field in fields(DeploymentBrandAssetConfig)),
            self.expected_field_names,
        )
        self.assertEqual(len(fields(DeploymentBrandAssetConfig)), 24)
        self.assertEqual(
            brand_asset_config_module.__all__,
            (
                "DeploymentBrandAssetConfig",
                "get_deployment_brand_asset_config",
            ),
        )

    def test_accessor_returns_a_fresh_snapshot_per_call(self):
        first = get_deployment_brand_asset_config()
        second = get_deployment_brand_asset_config()

        self.assertIsNot(first, second)
        self.assertEqual(first, second)

    def test_accessor_reads_exactly_the_twenty_four_resolved_asset_settings(self):
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
        self.assertEqual(len(setting_reads), 24)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("import environ", source)
        self.assertNotIn("loomera.settings.base", source)
        self.assertNotIn("request", source.lower())
        self.assertNotIn(".objects", source)
        self.assertNotIn("apps.accounts", source)
        self.assertNotIn("salon", source.lower())
        # Asset names may include "business_card"; runtime dependencies may not.
        # Keep this boundary limited to the approved imports and constructor.
        imported_modules = [
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
        ]
        self.assertCountEqual(
            imported_modules, ("__future__", "dataclasses", "django.conf")
        )
        self.assertFalse(
            any(isinstance(node, ast.Import) for node in tree.body)
        )
        self.assertEqual(
            [
                node.targets[0].id
                for node in tree.body
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ],
            ["__all__"],
        )

        accessor = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_deployment_brand_asset_config"
        )
        self.assertEqual(
            (
                len(accessor.args.posonlyargs),
                len(accessor.args.args),
                len(accessor.args.kwonlyargs),
                accessor.args.vararg,
                accessor.args.kwarg,
            ),
            (0, 0, 0, None, None),
        )
        self.assertEqual(
            {
                node.id
                for node in ast.walk(accessor)
                if isinstance(node, ast.Name)
            },
            {"DeploymentBrandAssetConfig", "_settings"},
        )
        calls = [
            node for node in ast.walk(accessor) if isinstance(node, ast.Call)
        ]
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0].func, ast.Name)
        self.assertEqual(calls[0].func.id, "DeploymentBrandAssetConfig")

    def test_asset_boundary_runtime_consumers_are_explicitly_approved(self):
        project_root = Path(settings.BASE_DIR)
        assets_path = project_root / "loomera" / "branding" / "assets.py"
        test_path = project_root / "apps" / "main" / "test_production_settings_hygiene.py"
        occurrences: list[str] = []

        for root_name in ("apps", "loomera"):
            for path in (project_root / root_name).rglob("*.py"):
                if path in {assets_path, test_path} or path.name.startswith("test_"):
                    continue
                source = path.read_text(encoding="utf-8")
                if (
                    "DeploymentBrandAssetConfig" in source
                    or "get_deployment_brand_asset_config" in source
                ):
                    occurrences.append(path.relative_to(project_root).as_posix())

        self.assertCountEqual(
            occurrences,
            [
                "apps/orders/quick_link_print_templates.py",
                "apps/orders/quick_link_qr.py",
                "apps/orders/management/commands/quick_link_readiness_check.py",
                "loomera/branding/context_processors.py",
            ],
        )

    def test_default_logo_variants_use_compatibility_assets_and_alt_rules(self):
        context = self._template_context()
        expected_by_variant = {
            "glyph": "/static/branding/logo/loomera-glyph-mark.png",
            "app-icon": "/static/branding/logo/loomera-app-icon.png",
            "header": "/static/branding/logo/loomera-logo-header.png",
            "compact": "/static/branding/logo/loomera-logo-header.png",
            "full": "/static/branding/logo/loomera-logo-primary.png",
        }

        for variant, expected_url in expected_by_variant.items():
            with self.subTest(variant=variant):
                rendered = render_to_string(
                    "partials/brand/logo.html",
                    {**context, "logo_variant": variant},
                )
                self.assertIn(f'src="{expected_url}"', rendered)
                self.assertIn('alt="Loomera"', rendered)

        explicit_alt = render_to_string(
            "partials/brand/logo.html",
            {**context, "logo_variant": "full", "alt_text": "Buyer mark"},
        )
        self.assertIn('alt="Buyer mark"', explicit_alt)
        self.assertNotIn('alt="Loomera"', explicit_alt)

        with override_settings(BRAND_DISPLAY_NAME="Aurora"):
            fallback_alt = render_to_string(
                "partials/brand/logo.html",
                {
                    "deployment_brand": get_deployment_brand_config(),
                    "deployment_brand_assets": get_deployment_brand_asset_config(),
                    "deployment_brand_colors": get_deployment_brand_color_config(),
                    "logo_variant": "glyph",
                },
            )
        self.assertIn('alt="Aurora"', fallback_alt)

    @override_settings(
        BRAND_LOGO_GLYPH_STATIC_PATH="buyer/brand/glyph.svg",
        BRAND_APP_ICON_STATIC_PATH="buyer/brand/app-icon.png",
        BRAND_LOGO_HEADER_STATIC_PATH="buyer/brand/header.png",
        BRAND_LOGO_PRIMARY_STATIC_PATH="buyer/brand/primary.png",
        BRAND_FAVICON_SVG_STATIC_PATH="buyer/favicon/icon.svg",
        BRAND_FAVICON_ICO_STATIC_PATH="buyer/favicon/icon.ico",
        BRAND_FAVICON_16_STATIC_PATH="buyer/favicon/icon-16.png",
        BRAND_FAVICON_32_STATIC_PATH="buyer/favicon/icon-32.png",
        BRAND_FAVICON_48_STATIC_PATH="buyer/favicon/icon-48.png",
        BRAND_APPLE_TOUCH_ICON_STATIC_PATH="buyer/favicon/apple-touch.png",
        BRAND_MASK_ICON_STATIC_PATH="buyer/favicon/mask.svg",
        BRAND_WEBMANIFEST_STATIC_PATH="buyer/favicon/site.webmanifest",
        BRAND_SOCIAL_IMAGE_STATIC_PATH="buyer/brand/social.png",
        BRAND_SOCIAL_IMAGE_WIDTH=1600,
        BRAND_SOCIAL_IMAGE_HEIGHT=900,
    )
    def test_alternate_asset_settings_render_without_locale_provider_auth_or_booking_inference(self):
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
        context = self._template_context()
        head = render_to_string("partials/brand/head_assets.html", context)

        for expected_url in (
            "/static/buyer/favicon/icon.svg",
            "/static/buyer/favicon/icon.ico",
            "/static/buyer/favicon/icon-16.png",
            "/static/buyer/favicon/icon-32.png",
            "/static/buyer/favicon/icon-48.png",
            "/static/buyer/favicon/apple-touch.png",
            "/static/buyer/favicon/mask.svg",
            "/static/buyer/favicon/site.webmanifest",
            "/static/buyer/brand/social.png",
        ):
            self.assertIn(expected_url, head)
        self.assertIn('<meta property="og:image:width" content="1600">', head)
        self.assertIn('<meta property="og:image:height" content="900">', head)
        self.assertIn('<meta property="og:locale" content="fa_IR">', head)
        for value in ("#FCFBFE", "#16131F", "#735CBE"):
            self.assertIn(value, head)

        expected_logo_urls = {
            "glyph": "/static/buyer/brand/glyph.svg",
            "app-icon": "/static/buyer/brand/app-icon.png",
            "header": "/static/buyer/brand/header.png",
            "full": "/static/buyer/brand/primary.png",
        }
        for variant, expected_url in expected_logo_urls.items():
            with self.subTest(variant=variant):
                rendered = render_to_string(
                    "partials/brand/logo.html",
                    {**context, "logo_variant": variant},
                )
                self.assertIn(f'src="{expected_url}"', rendered)

        self.assertEqual(settings.LANGUAGE_CODE, runtime_values["language_code"])
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, runtime_values["default_language"])
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, runtime_values["default_country"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, runtime_values["default_currency"])
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, runtime_values["default_timezone"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, runtime_values["default_calendar"])
        self.assertEqual(settings.SMS_PROVIDER, runtime_values["sms_provider"])
        self.assertEqual(settings.PAYMENT_PROVIDER, runtime_values["payment_provider"])
        self.assertEqual(
            tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
            runtime_values["messaging_allowed_providers"],
        )
        self.assertEqual(settings.AUTH_USER_MODEL, runtime_values["auth_user_model"])

    def test_manifest_and_default_brand_static_assets_preserve_target_compatibility(self):
        project_root = Path(settings.BASE_DIR)
        manifest_path = project_root / "static" / "branding" / "favicon" / "site.webmanifest"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["name"], "Loomera")
        self.assertEqual(manifest["short_name"], "Loomera")
        self.assertEqual(
            manifest["description"],
            "Discovery and booking for beauty, aesthetic treatments, massage, and wellness.",
        )
        self.assertEqual(manifest["theme_color"], "#735CBE")
        self.assertEqual(manifest["background_color"], "#FCFBFE")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(
            manifest["icons"],
            [
                {
                    "src": "/static/branding/favicon/android-chrome-192x192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/branding/favicon/android-chrome-512x512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/branding/favicon/maskable-icon-512x512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        )

        assets = get_deployment_brand_asset_config()
        for relative_path in (
            assets.logo_glyph_path,
            assets.app_icon_path,
            assets.logo_header_path,
            assets.logo_primary_path,
            assets.favicon_svg_path,
            assets.favicon_ico_path,
            assets.favicon_16_path,
            assets.favicon_32_path,
            assets.favicon_48_path,
            assets.apple_touch_icon_path,
            assets.mask_icon_path,
            assets.webmanifest_path,
            assets.social_image_path,
            assets.quick_link_mirror_label_art_path,
            assets.quick_link_business_card_front_art_path,
            assets.quick_link_business_card_back_art_path,
            assets.quick_link_table_stand_art_path,
            assets.login_hero_path,
            assets.customer_signup_hero_path,
            assets.stylist_signup_hero_path,
            assets.manager_signup_hero_path,
        ):
            self.assertTrue(
                (project_root / "static" / relative_path).is_file(),
                msg=f"Missing default brand static asset: {relative_path}",
            )


class MachineReadableBrandIdentityWiringTests(SimpleTestCase):
    @staticmethod
    def _runtime_context() -> dict[str, object]:
        return {
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

    def _assert_runtime_context_unchanged(self, before: dict[str, object]) -> None:
        self.assertEqual(settings.LANGUAGE_CODE, before["language_code"])
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, before["default_language"])
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, before["default_country"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, before["default_currency"])
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, before["default_timezone"])
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, before["default_calendar"])
        self.assertEqual(settings.SMS_PROVIDER, before["sms_provider"])
        self.assertEqual(settings.PAYMENT_PROVIDER, before["payment_provider"])
        self.assertEqual(
            tuple(settings.MESSAGING_ALLOWED_PROVIDERS),
            before["messaging_allowed_providers"],
        )
        self.assertEqual(settings.AUTH_USER_MODEL, before["auth_user_model"])

    def test_api_v1_meta_preserves_default_loomera_brand_identity(self):
        from django.urls import reverse

        response = self.client.get(reverse("api:v1:meta"), secure=True)

        self.assertEqual(response.status_code, 200)
        application = response.json()["data"]["application"]
        self.assertEqual(application["name"], "Loomera")
        self.assertEqual(application["brand"], "Loomera")

    @override_settings(
        LOOMERA_PUBLIC_APP_VERSION="2026.10",
        LOOMERA_PUBLIC_BUILD_ID="build-25",
        LOOMERA_API_VERSION="v1-test",
        LANGUAGE_CODE="fa",
    )
    def test_api_v1_meta_uses_one_brand_snapshot_and_preserves_other_metadata(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from django.urls import reverse

        deployment_brand = SimpleNamespace(name="Acme", display_name="Acme Booking")
        runtime_context = self._runtime_context()

        with patch(
            "apps.api.v1.views.get_deployment_brand_config",
            return_value=deployment_brand,
        ) as get_brand:
            response = self.client.get(reverse("api:v1:meta"), secure=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["application"]["name"], "Acme Booking")
        self.assertEqual(payload["application"]["brand"], "Acme")
        self.assertEqual(payload["application"]["version"], "2026.10")
        self.assertEqual(payload["application"]["build"], "build-25")
        self.assertEqual(payload["api"]["version"], "v1-test")
        self.assertEqual(payload["api"]["base_path"], "/api/v1/")
        self.assertEqual(payload["localization"]["default_language"], "fa")
        self.assertIs(payload["localization"]["rtl"], True)
        self.assertIn("time_utc", payload["server"])
        get_brand.assert_called_once_with()
        self._assert_runtime_context_unchanged(runtime_context)

    def test_service_schema_preserves_default_loomera_provider_identity(self):
        from types import SimpleNamespace

        from apps.main.seo import build_service_schema

        request = SimpleNamespace(
            build_absolute_uri=lambda path: f"https://example.test{path}"
        )
        service = SimpleNamespace(
            service_name="Haircut",
            effective_seo_description="Service description",
            get_absolute_url=lambda: "/services/haircut/",
            service_image=None,
        )

        schema = json.loads(build_service_schema(request, service))

        self.assertEqual(
            schema["provider"],
            {"@type": "Organization", "name": "Loomera"},
        )

    def test_service_schema_uses_one_brand_snapshot_and_preserves_schema_and_image_behavior(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        from apps.main.seo import build_service_schema

        deployment_brand = SimpleNamespace(name="Acme", display_name="Acme Booking")
        runtime_context = self._runtime_context()
        request = SimpleNamespace(
            build_absolute_uri=lambda path: f"https://example.test{path}"
        )
        service = SimpleNamespace(
            service_name="Haircut",
            effective_seo_description="Service description",
            get_absolute_url=lambda: "/services/haircut/",
            service_image=SimpleNamespace(url="/media/haircut.jpg"),
        )

        with patch(
            "apps.main.seo.get_deployment_brand_config",
            return_value=deployment_brand,
        ) as get_brand:
            schema = json.loads(build_service_schema(request, service))

        self.assertEqual(schema["@context"], "https://schema.org")
        self.assertEqual(schema["@type"], "Service")
        self.assertEqual(schema["name"], "Haircut")
        self.assertEqual(schema["description"], "Service description")
        self.assertEqual(schema["url"], "https://example.test/services/haircut/")
        self.assertEqual(
            schema["provider"],
            {"@type": "Organization", "name": "Acme Booking"},
        )
        self.assertEqual(schema["image"], "https://example.test/media/haircut.jpg")
        get_brand.assert_called_once_with()
        self._assert_runtime_context_unchanged(runtime_context)

    def test_machine_readable_consumers_do_not_read_brand_settings_directly(self):
        project_root = Path(settings.BASE_DIR)
        api_source = (project_root / "apps" / "api" / "v1" / "views.py").read_text(
            encoding="utf-8"
        )
        seo_source = (project_root / "apps" / "main" / "seo.py").read_text(
            encoding="utf-8"
        )

        for forbidden in ("BRAND_NAME", "BRAND_DISPLAY_NAME"):
            self.assertNotIn(forbidden, api_source)
            self.assertNotIn(forbidden, seo_source)
        self.assertNotIn("from django.conf import settings", seo_source)


class SharedShellBrandLiteralCleanupTests(SimpleTestCase):
    @staticmethod
    def _template_context() -> dict[str, object]:
        return {
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
            "dashboard_header": {
                "salon_name": "Test Salon",
                "manager_name": "Test Manager",
            },
            "dashboard_sidebar_sections": [],
        }

    def test_shared_shell_preserves_default_loomera_compatibility_branding(self):
        context = self._template_context()
        splash = render_to_string("partials/brand/loader_splash.html", context)
        sidebar = render_to_string("partials/dashboard/sidebar.html", context)

        self.assertIn('<p class="lm-splash__title">Loomera</p>', splash)
        self.assertIn('alt="Loomera"', splash)
        self.assertIn('aria-label="ناوبری پنل مدیریت Loomera"', sidebar)
        self.assertEqual(sidebar.count('alt="Loomera"'), 2)

    @override_settings(BRAND_DISPLAY_NAME="Aurora")
    def test_shared_shell_uses_alternate_deployment_brand_display_name(self):
        context = self._template_context()
        splash = render_to_string("partials/brand/loader_splash.html", context)
        sidebar = render_to_string("partials/dashboard/sidebar.html", context)

        self.assertIn('<p class="lm-splash__title">Aurora</p>', splash)
        self.assertIn('alt="Aurora"', splash)
        self.assertIn('aria-label="ناوبری پنل مدیریت Aurora"', sidebar)
        self.assertEqual(sidebar.count('alt="Aurora"'), 2)


class HelpAIOpenRouterBrandIdentityTests(SimpleTestCase):
    def test_openrouter_headers_use_one_fresh_snapshot_per_construction(self):
        from apps.help_center import ai
        from loomera.branding.config import get_deployment_brand_config

        cases = (
            ("Loomera", "https://brand.example", "https://help.example",
             {"X-Title": "Loomera Help Assistant", "HTTP-Referer": "https://help.example"}),
            ("Aurora", "https://brand.example", "",
             {"X-Title": "Aurora Help Assistant", "HTTP-Referer": "https://brand.example"}),
            ("Aurora", "", "", {"X-Title": "Aurora Help Assistant"}),
            ("", "", "", {}),
        )
        with patch.object(ai, "get_deployment_brand_config",
                          wraps=get_deployment_brand_config, create=True) as get_brand:
            for index, (name, brand_url, help_url, expected) in enumerate(cases, start=1):
                with self.subTest(name=name, help_url=help_url), override_settings(
                    BRAND_DISPLAY_NAME=name, PUBLIC_BASE_URL=brand_url,
                    HELP_AI_SITE_URL=help_url, OPENROUTER_API_KEY="test-key",
                    HELP_AI_MODEL="test-model", HELP_AI_TIMEOUT_SECONDS=9,
                ):
                    provider = ai.OpenRouterProvider()
                    self.assertEqual(provider.extra_headers, expected)
                    self.assertEqual(get_brand.call_count, index)
                    self.assertEqual(provider.provider_name, "openrouter")
                    self.assertEqual(provider.endpoint,
                                     "https://openrouter.ai/api/v1/chat/completions")
                    self.assertEqual((provider.api_key, provider.model, provider.timeout),
                                     ("test-key", "test-model", 9))
                    self.assertEqual(provider.extra_payload, {"provider": {
                        "zdr": True, "data_collection": "deny", "allow_fallbacks": True,
                    }})
            get_brand.assert_called_with()

    def test_openrouter_uses_returned_snapshot_and_other_providers_are_isolated(self):
        from apps.help_center import ai

        with override_settings(HELP_AI_SITE_URL="", BRAND_DISPLAY_NAME="Setting Name",
                               PUBLIC_BASE_URL="https://setting.example"), patch.object(
            ai, "get_deployment_brand_config", create=True,
            return_value=SimpleNamespace(display_name="Aurora",
                                         public_base_url="https://snapshot.example"),
        ) as get_brand:
            provider = ai.OpenRouterProvider()
            self.assertEqual(provider.extra_headers, {
                "X-Title": "Aurora Help Assistant", "HTTP-Referer": "https://snapshot.example",
            })
            get_brand.assert_called_once_with()
            get_brand.reset_mock()
            ai.GroqProvider()
            ai.CustomProvider()
            ai.DisabledProvider()
            get_brand.assert_not_called()

    def test_brand_accessor_is_local_to_openrouter_and_settings_reads_are_removed(self):
        tree = ast.parse((Path(settings.BASE_DIR) / "apps/help_center/ai.py")
                         .read_text(encoding="utf-8"))
        provider = next(node for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == "OpenRouterProvider")
        constructor = next(node for node in provider.body
                           if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "get_deployment_brand_config"]
        self.assertEqual(len(calls), 1)
        snapshot = next(node for node in constructor.body
                        if isinstance(node, ast.Assign) and node.value is calls[0])
        self.assertEqual(ast.dump(snapshot.targets[0]),
                         ast.dump(ast.Name(id="deployment_brand", ctx=ast.Store())))
        self.assertEqual(constructor.decorator_list, [])
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                self.assertFalse(node.value.id == "settings" and
                                 node.attr in {"BRAND_DISPLAY_NAME", "PUBLIC_BASE_URL"})
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "getattr" and len(node.args) >= 2:
                    target, name = node.args[:2]
                    self.assertFalse(isinstance(target, ast.Name) and target.id == "settings"
                                     and isinstance(name, ast.Constant)
                                     and name.value in {"BRAND_DISPLAY_NAME", "PUBLIC_BASE_URL"})


class ArticlePublisherBrandIdentityTests(SimpleTestCase):
    def _schema_nodes(self):
        path = Path(settings.BASE_DIR) / "apps/articles/views.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        view = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "ArticleDetailView")
        method = next(node for node in view.body
                      if isinstance(node, ast.FunctionDef) and node.name == "get_context_data")
        schema = next(node for node in method.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "article_schema"
                              for target in node.targets))
        return tree, method, schema

    def test_publisher_uses_display_name_from_one_fresh_local_snapshot(self):
        tree, method, schema = self._schema_nodes()
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "get_deployment_brand_config"]
        self.assertEqual(len(calls), 1)
        snapshot = next(node for node in method.body if isinstance(node, ast.Assign)
                        and node.value is calls[0])
        self.assertEqual(ast.dump(snapshot.targets[0]),
                         ast.dump(ast.Name(id="deployment_brand", ctx=ast.Store())))
        self.assertLess(method.body.index(snapshot), method.body.index(schema))
        self.assertEqual(calls[0].args, [])
        self.assertEqual(calls[0].keywords, [])
        self.assertEqual(method.decorator_list, [])
        imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)
                   and node.module == "loomera.branding.config"]
        self.assertTrue(any(alias.name == "get_deployment_brand_config"
                            and alias.asname is None
                            for node in imports for alias in node.names))
        publisher = next(value for key, value in zip(schema.value.keys, schema.value.values)
                         if isinstance(key, ast.Constant) and key.value == "publisher")
        accessor = Mock(side_effect=[SimpleNamespace(display_name="Loomera", name="Other"),
                                    SimpleNamespace(display_name="Aurora", name="Other")])
        program = ast.fix_missing_locations(ast.Module(body=[snapshot], type_ignores=[]))
        namespace = {"get_deployment_brand_config": accessor}
        for expected in ("Loomera", "Aurora"):
            exec(compile(program, "article-snapshot", "exec"), namespace)
            actual = eval(compile(ast.Expression(body=publisher), "article-publisher", "eval"),
                          namespace)
            self.assertEqual(actual, {"@type": "Organization", "name": expected})
        self.assertEqual(accessor.call_count, 2)

    def test_publisher_does_not_read_brand_display_setting_directly(self):
        tree, _, _ = self._schema_nodes()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                self.assertFalse(node.value.id == "settings"
                                 and node.attr == "BRAND_DISPLAY_NAME")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "getattr" and len(node.args) >= 2:
                    target, name = node.args[:2]
                    self.assertFalse(isinstance(target, ast.Name) and target.id == "settings"
                                     and isinstance(name, ast.Constant)
                                     and name.value == "BRAND_DISPLAY_NAME")


class SharedEmailSenderIdentityTests(SimpleTestCase):
    def _exercise(self, consumer, *, sender, email="person@example.com",
                  channel="email", opted_out=False, send_error=None,
                  snapshot_sender=None):
        from apps.notifications import delivery as notifications
        from apps.orders import notification_delivery as orders
        from loomera.branding.config import get_deployment_brand_config

        module = notifications if consumer == "notifications" else orders
        user = SimpleNamespace(email=email, mobile_number="09123456789")
        customer = SimpleNamespace(notify_appointment_email=not opted_out,
                                   notify_appointment_sms=True)
        item = SimpleNamespace(
            pk=7, order_id=8, title="Subject", body="Body", meta={"existing": True},
            target_user_id=1, target_user=user, customer_id=1, customer=customer,
            stylist_id=None, stylist=None, audience_role="customer",
            recipient=SimpleNamespace(user=user, notification=SimpleNamespace(
                title="Subject", body="Body")),
            attempt_count=0, status="queued", provider="", sent_at=None,
            failed_at=None, last_error="", save=Mock(),
        )
        with ExitStack() as stack:
            stack.enter_context(override_settings(DEFAULT_FROM_EMAIL=sender,
                                                   SMS_PROVIDER="disabled"))
            get_brand = stack.enter_context(patch.object(
                module, "get_deployment_brand_config",
                wraps=get_deployment_brand_config, create=True))
            if snapshot_sender is not None:
                get_brand.return_value = replace(
                    get_deployment_brand_config(), default_from_email=snapshot_sender)
            send = stack.enter_context(patch.object(module, "send_mail",
                                                    side_effect=send_error))
            if send_error is not None:
                stack.enter_context(self.assertLogs(module.logger, level="ERROR"))
            if consumer == "notifications":
                attempt = stack.enter_context(patch.object(
                    notifications.NotificationDeliveryAttempt.objects, "create"))
                result = (module.deliver_email if channel == "email"
                          else module.deliver_sms)(item)
                reason = attempt.call_args.kwargs["error_message"]
                status = result.status
                count = result.attempt_count
            else:
                query = stack.enter_context(patch.object(
                    orders.AppointmentNotification.objects, "select_related"))
                query.return_value.get.return_value = item
                result = (module.deliver_email_notification if channel == "email"
                          else module.deliver_sms_notification)(item)
                reason = result.meta.get("reason", "")
                status = result.delivery_status
                count = result.meta.get("attempt_count", 0)
                self.assertTrue(result.meta["existing"])
            return status, reason, count, send, get_brand

    def test_both_consumers_use_fresh_default_and_alternate_senders(self):
        for consumer in ("notifications", "orders"):
            for sender in ("Loomera <no-reply@loomera.local>",
                           "  Aurora <mail@example.com>  "):
                with self.subTest(consumer=consumer, sender=sender):
                    status, _, count, send, get_brand = self._exercise(
                        consumer, sender=sender)
                    self.assertEqual(status, "sent")
                    self.assertEqual(count, 1)
                    self.assertEqual(send.call_args.kwargs, {
                        "subject": "Subject", "message": "Body",
                        "from_email": sender.strip(),
                        "recipient_list": ["person@example.com"],
                        "fail_silently": False,
                    })
                    get_brand.assert_called_once_with()

    def test_sender_comes_from_returned_snapshot(self):
        for consumer in ("notifications", "orders"):
            with self.subTest(consumer=consumer):
                status, _, _, send, get_brand = self._exercise(
                    consumer, sender="settings@example.com",
                    snapshot_sender="snapshot@example.com")
                self.assertEqual(status, "sent")
                self.assertEqual(send.call_args.kwargs["from_email"],
                                 "snapshot@example.com")
                get_brand.assert_called_once_with()

    def test_empty_sender_preserves_pending_setup(self):
        for consumer in ("notifications", "orders"):
            with self.subTest(consumer=consumer):
                status, reason, count, send, get_brand = self._exercise(
                    consumer, sender="  ")
                self.assertEqual((status, reason),
                                 ("pending_setup", "missing_default_from_email"))
                self.assertEqual(count, 1 if consumer == "notifications" else 0)
                send.assert_not_called()
                get_brand.assert_called_once_with()

    def test_missing_email_does_not_resolve_sender(self):
        for consumer in ("notifications", "orders"):
            with self.subTest(consumer=consumer):
                status, reason, _, send, get_brand = self._exercise(
                    consumer, sender="mail@example.com", email="")
                self.assertEqual((status, reason), ("pending_setup", "missing_email"))
                send.assert_not_called()
                get_brand.assert_not_called()

    def test_order_email_opt_out_does_not_resolve_sender(self):
        status, reason, count, send, get_brand = self._exercise(
            "orders", sender="mail@example.com", opted_out=True)
        self.assertEqual((status, reason, count),
                         ("skipped", "customer_email_opt_out", 0))
        send.assert_not_called()
        get_brand.assert_not_called()

    def test_failed_send_uses_one_snapshot_and_records_attempt(self):
        for consumer in ("notifications", "orders"):
            with self.subTest(consumer=consumer):
                status, _, count, send, get_brand = self._exercise(
                    consumer, sender="mail@example.com",
                    send_error=RuntimeError("transport failure"))
                self.assertEqual((status, count), ("failed", 1))
                send.assert_called_once()
                get_brand.assert_called_once_with()

    def test_sms_paths_do_not_resolve_brand_identity(self):
        for consumer in ("notifications", "orders"):
            with self.subTest(consumer=consumer):
                status, reason, _, send, get_brand = self._exercise(
                    consumer, sender="mail@example.com", channel="sms")
                self.assertEqual((status, reason),
                                 ("pending_setup", "provider_disabled"))
                send.assert_not_called()
                get_brand.assert_not_called()

    def test_email_consumers_do_not_read_sender_setting_directly(self):
        for path in ("apps/notifications/delivery.py",
                     "apps/orders/notification_delivery.py"):
            tree = ast.parse((Path(settings.BASE_DIR) / path).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    self.assertFalse(node.value.id == "settings" and
                                     node.attr == "DEFAULT_FROM_EMAIL", path)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id == "getattr" and len(node.args) >= 2:
                        target, name = node.args[:2]
                        self.assertFalse(
                            isinstance(target, ast.Name) and target.id == "settings"
                            and isinstance(name, ast.Constant)
                            and name.value == "DEFAULT_FROM_EMAIL", path)


class SharedHeaderFooterBrandIdentityTests(SimpleTestCase):
    def _template_source(self, relative_path: str) -> str:
        return (
            Path(settings.BASE_DIR) / "templates" / relative_path
        ).read_text(encoding="utf-8")

    def test_shared_home_labels_use_template_brand_context_without_literal_or_new_accessor(self):
        for relative_path in (
            "partials/shell/desktop_site_header.html",
            "partials/shell/mobile_app_header.html",
        ):
            with self.subTest(template=relative_path):
                source = self._template_source(relative_path)
                self.assertNotIn('aria-label="Loomera home"', source)
                self.assertIn(
                    'aria-label="{{ deployment_brand.display_name }} home"',
                    source,
                )
                self.assertEqual(
                    source.count('{% include "partials/brand/logo.html"'),
                    1,
                )
                self.assertNotIn("get_deployment_brand_config", source)

    def test_footer_uses_shared_display_name_and_preserves_persian_tagline(self):
        source = self._template_source("partials/footer.html")

        self.assertNotIn("© {{ now|default:'' }} Loomera", source)
        self.assertIn(
            "© {{ now|default:'' }} {{ deployment_brand.display_name }}",
            source,
        )
        self.assertIn("برای انتخابی روشن‌تر و رزروی آرام‌تر", source)
        self.assertNotIn("get_deployment_brand_config", source)

    def test_footer_renders_alternate_deployment_brand_without_template_edit(self):
        rendered = render_to_string(
            "partials/footer.html",
            {
                "now": "2026",
                "deployment_brand": SimpleNamespace(display_name="Aurora"),
            },
        )

        self.assertIn("© 2026 Aurora", rendered)
        self.assertNotIn("Loomera", rendered)
        self.assertIn("برای انتخابی روشن‌تر و رزروی آرام‌تر", rendered)


class PasswordRecoveryBrandIdentityTests(SimpleTestCase):
    @staticmethod
    def _source(relative_path: str) -> str:
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_active_recovery_template_uses_shared_brand_boundary(self):
        source = self._source("templates/accounts/remember_password.html")

        self.assertEqual(
            source.count('{% include "partials/brand/logo.html"'),
            1,
        )
        self.assertIn(
            '{% include "partials/brand/logo.html" with variant="full" size="lg" %}',
            source,
        )
        self.assertIn(
            "امنیت حساب {{ deployment_brand.display_name }}",
            source,
        )
        self.assertIn('<a href="/" class="inline-flex items-center">', source)
        self.assertNotIn("branding/logo/loomera-logo-horizontal-transparent.png", source)
        self.assertNotIn('alt="Loomera"', source)
        self.assertNotIn("امنیت حساب Loomera", source)
        self.assertNotIn("Loomera", source)
        self.assertNotIn("لومرا", source)
        self.assertNotIn("{% load static %}", source)

    def test_accounts_view_remains_outside_brand_accessor_boundary(self):
        source = self._source("apps/accounts/views.py")

        self.assertNotIn("get_deployment_brand_config", source)


class LoginBrandIdentityTests(SimpleTestCase):
    @staticmethod
    def _source(relative_path: str) -> str:
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_active_login_template_uses_shared_deployment_brand_identity(self):
        source = self._source("templates/accounts/login.html")
        include = (
            '{% include "partials/brand/logo.html" with '
            'logo_variant="glyph" logo_size="sm" %}'
        )

        self.assertEqual(source.count('{% include "partials/brand/logo.html"'), 1)
        self.assertIn(include, source)
        self.assertIn(
            "{% block title %}ورود به {{ deployment_brand.display_name }}{% endblock %}",
            source,
        )
        self.assertIn(
            'aria-label="صفحه اصلی {{ deployment_brand.display_name }}"',
            source,
        )
        self.assertIn("<span>{{ deployment_brand.display_name }}</span>", source)
        self.assertIn(
            '<span class="lm-login-title-brand">{{ deployment_brand.display_name }}</span>',
            source,
        )
        self.assertEqual(source.count("deployment_brand.display_name"), 4)
        self.assertNotIn("branding/logo/loomera-glyph-mark.png", source)
        self.assertNotIn("صفحه اصلی Loomera", source)
        self.assertNotIn("ورود به لومرا", source)
        self.assertNotIn("Loomera", source)
        self.assertNotIn("لومرا", source)
        self.assertEqual(source.count("{% static deployment_brand_assets.login_hero_path %}"), 1)
        self.assertIn("{% load static %}", source)
        self.assertIn("bg-loomera-bg", source)
        self.assertIn("text-loomera-textPrimary", source)

    def test_accounts_view_remains_outside_brand_accessor_boundary(self):
        source = self._source("apps/accounts/views.py")

        self.assertNotIn("get_deployment_brand_config", source)


class QuickLinkPrintBrandIdentityTests(SimpleTestCase):
    @staticmethod
    def _source_and_tree():
        path = Path(settings.BASE_DIR) / "apps" / "orders" / "quick_link_print_templates.py"
        source = path.read_text(encoding="utf-8")
        return source, ast.parse(source, filename=str(path))

    def test_source_uses_existing_brand_boundaries_without_fixed_print_identity(self):
        source, tree = self._source_and_tree()
        imported = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module in {"loomera.branding.config", "loomera.branding.assets"}
            for alias in node.names
        }
        self.assertIn("get_deployment_brand_config", imported)
        self.assertIn("get_deployment_brand_asset_config", imported)
        self.assertIn("logo_header_path", source)
        self.assertNotIn(
            "branding/logo/loomera-logo-horizontal-rtl-transparent-360.png",
            source,
        )
        self.assertNotIn("branding/logo/loomera-symbol-transparent-160.png", source)
        self.assertNotIn("PRINT_TEMPLATE_SYMBOL", source)
        self.assertNotIn("https://loomera.ir", source)
        self.assertNotIn('"loomera.ir"', source)
        self.assertNotIn("'loomera.ir'", source)
        self.assertNotIn("from django.conf import settings", source)
        self.assertNotIn("settings.PUBLIC_BASE_URL", source)
        self.assertNotIn("settings.SITE_URL", source)

        accessor_names = {
            "get_deployment_brand_config",
            "get_deployment_brand_asset_config",
        }
        module_snapshots = []
        for node in tree.body:
            value = None
            if isinstance(node, ast.Assign):
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in accessor_names
            ):
                module_snapshots.append(value.func.id)
        self.assertEqual(module_snapshots, [])

    def test_helpers_resolve_fresh_overrides_after_module_import(self):
        from apps.orders import quick_link_print_templates as print_templates

        with override_settings(
            BRAND_DOMAIN="example.test",
            PUBLIC_BASE_URL="https://booking.example.test",
            SITE_URL="https://site.example.test",
            BRAND_LOGO_HEADER_STATIC_PATH="branding/custom/example-header.png",
        ):
            self.assertEqual(
                print_templates._deployment_print_logo_path(),
                "branding/custom/example-header.png",
            )
            self.assertEqual(
                print_templates._deployment_print_public_base_url(),
                "https://booking.example.test",
            )
            self.assertEqual(
                print_templates._deployment_print_display_host(),
                "booking.example.test",
            )

    def test_public_base_fallback_order_and_hostname_only(self):
        from apps.orders import quick_link_print_templates as print_templates

        with override_settings(
            BRAND_DOMAIN="example.test",
            PUBLIC_BASE_URL="",
            SITE_URL="https://site.example.test/base",
        ):
            self.assertEqual(
                print_templates._deployment_print_public_base_url(),
                "https://site.example.test/base",
            )
            self.assertEqual(
                print_templates._deployment_print_display_host(),
                "site.example.test",
            )

        with override_settings(
            BRAND_DOMAIN="example.test",
            PUBLIC_BASE_URL="",
            SITE_URL="",
        ):
            self.assertEqual(
                print_templates._deployment_print_public_base_url(),
                "https://example.test",
            )
            self.assertEqual(
                print_templates._deployment_print_display_host(),
                "example.test",
            )

    def test_request_host_and_disallowed_host_fallback_semantics_are_preserved(self):
        from django.core.exceptions import DisallowedHost
        from apps.orders import quick_link_print_templates as print_templates

        with override_settings(
            BRAND_DOMAIN="example.test",
            PUBLIC_BASE_URL="",
            SITE_URL="",
        ):
            request = SimpleNamespace(get_host=lambda: "request.example.test")
            self.assertEqual(
                print_templates._deployment_print_public_base_url(request),
                "https://request.example.test",
            )
            local_request = SimpleNamespace(get_host=lambda: "localhost:8000")
            self.assertEqual(
                print_templates._deployment_print_public_base_url(local_request),
                "https://example.test",
            )

            def disallowed_host():
                raise DisallowedHost

            rejected_request = SimpleNamespace(get_host=disallowed_host)
            self.assertEqual(
                print_templates._deployment_print_public_base_url(rejected_request),
                "https://example.test",
            )


class QuickLinkPrintArtworkAssetTests(SimpleTestCase):
    @staticmethod
    def _print_module():
        # Import first: overrides must be observed on subsequent runtime calls.
        from apps.orders import quick_link_print_templates

        return quick_link_print_templates

    @staticmethod
    def _write_png(path, size, color, *, dpi=None):
        save_kwargs = {"format": "PNG"}
        if dpi is not None:
            save_kwargs["dpi"] = (dpi, dpi)
        Image.new("RGBA", size, color).save(path, **save_kwargs)

    def test_alternate_paths_reach_each_loader_and_dependency_validation(self):
        print_templates = self._print_module()
        mirror = print_templates.get_booking_quick_link_print_template_spec("mirror_label")
        card = print_templates.get_booking_quick_link_print_template_spec("business_card")
        stand = print_templates.get_booking_quick_link_print_template_spec("table_stand")
        buyer_paths = list(QUICK_LINK_ART_BUYER_PATHS.values())
        colors = (
            (10, 20, 30, 0),
            (40, 50, 60, 255),
            (70, 80, 90, 255),
            (100, 110, 120, 255),
        )

        with TemporaryDirectory() as directory:
            files = {}
            for i, (relative_path, size, color) in enumerate(
                zip(
                    buyer_paths,
                    (
                        (mirror.width, mirror.height),
                        (card.width, card.height),
                        (card.width, card.height),
                        (stand.width, stand.height),
                    ),
                    colors,
                )
            ):
                file_path = Path(directory) / f"art-{i}.png"
                self._write_png(
                    file_path, size, color, dpi=300 if i == 3 else None
                )
                files[relative_path] = file_path

            observed = []
            def resolve(relative_path):
                observed.append(relative_path)
                if relative_path in files:
                    return str(files[relative_path])
                if relative_path in (
                    settings.BRAND_LOGO_HEADER_STATIC_PATH,
                    print_templates.PRINT_TEMPLATE_FONT_REGULAR,
                    print_templates.PRINT_TEMPLATE_FONT_BOLD,
                    print_templates.PRINT_TEMPLATE_FONT_BLACK,
                ):
                    return "packaged/static-asset"
                return None

            with override_settings(**QUICK_LINK_ART_BUYER_PATHS), patch.object(
                print_templates.finders, "find", side_effect=resolve
            ):
                assets = get_deployment_brand_asset_config()
                self.assertEqual(
                    (
                        assets.quick_link_mirror_label_art_path,
                        assets.quick_link_business_card_front_art_path,
                        assets.quick_link_business_card_back_art_path,
                        assets.quick_link_table_stand_art_path,
                    ),
                    tuple(buyer_paths),
                )
                self.assertEqual(
                    print_templates._load_mirror_label_art(mirror).getpixel((0, 0)),
                    colors[0],
                )
                self.assertEqual(
                    print_templates._load_business_card_art(
                        side="front", spec=card
                    ).getpixel((0, 0)),
                    colors[1],
                )
                self.assertEqual(
                    print_templates._load_business_card_art(
                        side="back", spec=card
                    ).getpixel((0, 0)),
                    colors[2],
                )
                self.assertEqual(
                    print_templates._load_table_stand_art(stand).getpixel((0, 0)),
                    colors[3],
                )
                self.assertEqual(
                    print_templates.validate_booking_quick_link_print_template_dependencies(),
                    (),
                )

            for buyer_path in buyer_paths:
                self.assertIn(buyer_path, observed)
            for default_path in QUICK_LINK_ART_SETTING_DEFAULTS.values():
                self.assertNotIn(default_path, observed)

    def test_missing_buyer_artwork_is_reported_and_never_uses_default(self):
        print_templates = self._print_module()
        mirror = print_templates.get_booking_quick_link_print_template_spec("mirror_label")
        card = print_templates.get_booking_quick_link_print_template_spec("business_card")
        stand = print_templates.get_booking_quick_link_print_template_spec("table_stand")
        missing_paths = tuple(QUICK_LINK_ART_BUYER_PATHS.values())
        observed = []

        def resolve(relative_path):
            observed.append(relative_path)
            return None if relative_path in missing_paths else "packaged/static-asset"

        with override_settings(**QUICK_LINK_ART_BUYER_PATHS), patch.object(
            print_templates.finders, "find", side_effect=resolve
        ):
            self.assertEqual(
                print_templates.validate_booking_quick_link_print_template_dependencies(),
                missing_paths,
            )
            for missing_path, loader in (
                (missing_paths[0], lambda: print_templates._load_mirror_label_art(mirror)),
                (missing_paths[1], lambda: print_templates._load_business_card_art(side="front", spec=card)),
                (missing_paths[2], lambda: print_templates._load_business_card_art(side="back", spec=card)),
                (missing_paths[3], lambda: print_templates._load_table_stand_art(stand)),
            ):
                with self.subTest(path=missing_path):
                    with self.assertRaisesRegex(
                        ImproperlyConfigured, missing_path
                    ):
                        loader()

        for default_path in QUICK_LINK_ART_SETTING_DEFAULTS.values():
            self.assertNotIn(default_path, observed)

    def test_wrong_dimensions_are_rejected_for_all_four_artworks(self):
        print_templates = self._print_module()
        mirror = print_templates.get_booking_quick_link_print_template_spec("mirror_label")
        card = print_templates.get_booking_quick_link_print_template_spec("business_card")
        stand = print_templates.get_booking_quick_link_print_template_spec("table_stand")
        cases = (
            ("mirror", mirror, lambda: print_templates._load_mirror_label_art(mirror)),
            ("front", card, lambda: print_templates._load_business_card_art(side="front", spec=card)),
            ("back", card, lambda: print_templates._load_business_card_art(side="back", spec=card)),
            ("stand", stand, lambda: print_templates._load_table_stand_art(stand)),
        )
        with TemporaryDirectory() as directory:
            for name, spec, loader in cases:
                with self.subTest(artwork=name):
                    path = Path(directory) / f"{name}.png"
                    self._write_png(
                        path,
                        (spec.width + 1, spec.height),
                        (1, 2, 3, 0),
                        dpi=300,
                    )
                    with override_settings(**QUICK_LINK_ART_BUYER_PATHS), patch.object(
                        print_templates.finders, "find", return_value=str(path)
                    ):
                        with self.assertRaises(ImproperlyConfigured):
                            loader()

    def test_mirror_transparency_and_table_stand_dpi_guards_remain_enforced(self):
        print_templates = self._print_module()
        mirror = print_templates.get_booking_quick_link_print_template_spec("mirror_label")
        stand = print_templates.get_booking_quick_link_print_template_spec("table_stand")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "art.png"
            self._write_png(path, (mirror.width, mirror.height), (1, 2, 3, 255))
            with override_settings(**QUICK_LINK_ART_BUYER_PATHS), patch.object(
                print_templates.finders, "find", return_value=str(path)
            ):
                with self.assertRaises(ImproperlyConfigured):
                    print_templates._load_mirror_label_art(mirror)

            for dpi, accepted in ((None, False), (290, False), (297, True), (303, True), (310, False)):
                with self.subTest(dpi=dpi):
                    self._write_png(
                        path, (stand.width, stand.height), (1, 2, 3, 255), dpi=dpi
                    )
                    with override_settings(**QUICK_LINK_ART_BUYER_PATHS), patch.object(
                        print_templates.finders, "find", return_value=str(path)
                    ):
                        if accepted:
                            self.assertEqual(
                                print_templates._load_table_stand_art(stand).size,
                                (1311, 1819),
                            )
                        else:
                            with self.assertRaises(ImproperlyConfigured):
                                print_templates._load_table_stand_art(stand)

    def test_no_fixed_artwork_paths_or_snapshot_at_module_import(self):
        print_templates = self._print_module()
        source = (Path(settings.BASE_DIR) / "apps" / "orders" /
                  "quick_link_print_templates.py").read_text(encoding="utf-8")
        for path in QUICK_LINK_ART_SETTING_DEFAULTS.values():
            self.assertNotIn(path, source)
        for legacy_name in (
            "PRINT_TEMPLATE_MIRROR_LABEL_ART",
            "PRINT_TEMPLATE_BUSINESS_CARD_FRONT_ART",
            "PRINT_TEMPLATE_BUSINESS_CARD_BACK_ART",
            "PRINT_TEMPLATE_TABLE_STAND_ART",
        ):
            self.assertFalse(hasattr(print_templates, legacy_name))
        self.assertNotIn("from django.conf import settings", source)


class QuickLinkQRGlyphBoundaryTests(SimpleTestCase):
    default_path = "branding/logo/loomera-glyph-mark-square-transparent-512.png"
    public_url = "https://buyer.example/booking/quick/test-token/"

    @staticmethod
    def _qr_module():
        from apps.orders import quick_link_qr
        return quick_link_qr

    def _generate(self):
        qr = self._qr_module()
        link = SimpleNamespace(
            pk=17, salon=SimpleNamespace(salon_name="Buyer Salon"), salon_id=8,
            placement=qr.BookingQuickLink.Placement.TABLE_STAND,
            archived_at=None, is_active=True, expires_at=None, payload={},
            mode=qr.BookingQuickLink.Mode.SERVICE,
        )
        with patch.object(qr, "build_quick_link_url", return_value=self.public_url):
            return qr.generate_booking_quick_link_qr(request=object(), quick_link=link)

    def test_default_glyph_and_snapshot_compatibility(self):
        first = get_deployment_brand_asset_config()
        second = get_deployment_brand_asset_config()
        self.assertEqual(first.quick_link_qr_glyph_path, self.default_path)
        self.assertIsNot(first, second)
        self.assertEqual(len(fields(first)), 24)
        with self.assertRaises(FrozenInstanceError):
            first.quick_link_qr_glyph_path = "buyer/other.png"
        generated = self._generate()
        self.assertEqual(generated.glyph_static_path, self.default_path)
        self.assertEqual(generated.filename, "loomera-buyer-salon-stand-link-17.png")
        self.assertEqual(generated.content_type, "image/png")

    def test_sequential_buyer_pngs_change_center_without_changing_qr_geometry(self):
        qr = self._qr_module()  # Import before overrides: no import-time snapshot.
        baseline = self._generate()
        with TemporaryDirectory() as directory:
            for index, color in enumerate(((231, 19, 47), (13, 187, 73))):
                with self.subTest(color=color):
                    path = Path(directory) / f"glyph-{index}.png"
                    Image.new("RGBA", (64, 64), (*color, 255)).save(path)
                    selected = f"buyer/qr/glyph-{index}.png"
                    with override_settings(BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH=selected):
                        snapshot = get_deployment_brand_asset_config()
                        self.assertEqual(snapshot.quick_link_qr_glyph_path, selected)
                        with patch.object(qr.finders, "find", return_value=str(path)) as find:
                            generated = self._generate()
                        find.assert_called_once_with(selected)
                    self.assertEqual(generated.glyph_static_path, selected)
                    self.assertEqual(generated.url, self.public_url)
                    for field in (
                        "width", "height", "box_size", "border_modules",
                        "error_correction", "content_type", "filename", "warnings",
                    ):
                        self.assertEqual(getattr(generated, field), getattr(baseline, field))
                    self.assertLessEqual(generated.logo_width_ratio, qr.BOOKING_QUICK_LINK_QR_LOGO_RATIO)
                    with Image.open(BytesIO(generated.content)) as output:
                        self.assertEqual(output.format, "PNG")
                        self.assertEqual(output.getpixel((output.width // 2, output.height // 2)), color)
                        self.assertEqual(output.getpixel((0, 0)), (255, 255, 255))
                        with Image.open(BytesIO(baseline.content)) as original:
                            # The outer quarter is outside the unchanged center backing.
                            self.assertEqual(
                                output.crop((0, 0, output.width, output.height // 4)).tobytes(),
                                original.crop((0, 0, original.width, original.height // 4)).tobytes(),
                            )
        self.assertEqual(get_deployment_brand_asset_config().quick_link_qr_glyph_path, self.default_path)

    def test_missing_or_invalid_buyer_glyph_never_falls_back(self):
        qr = self._qr_module()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / "corrupt.png"
            corrupt.write_bytes(b"not a raster image")
            jpeg = root / "wrong-format.png"
            Image.new("RGB", (64, 64), "red").save(jpeg, format="JPEG")
            empty = root / "empty.png"
            Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(empty)
            for resolved in (None, str(root / "missing.png"), str(corrupt), str(jpeg), str(empty)):
                with self.subTest(resolved=resolved):
                    with override_settings(BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH="buyer/qr/invalid.png"):
                        with patch.object(qr.finders, "find", return_value=resolved) as find:
                            with self.assertRaises(ImproperlyConfigured):
                                self._generate()
                        find.assert_called_once_with("buyer/qr/invalid.png")

    def test_readiness_checks_configured_png_and_reports_unreadable_images(self):
        from apps.orders.management.commands.quick_link_readiness_check import Command
        qr = self._qr_module()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "glyph.png"
            for valid in (True, False):
                with self.subTest(valid=valid):
                    if valid:
                        Image.new("RGBA", (64, 64), (17, 199, 61, 255)).save(path)
                    else:
                        path.write_bytes(b"corrupt")
                    with override_settings(BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH="buyer/qr/check.png"):
                        with patch.object(qr.finders, "find", return_value=str(path)) as find:
                            findings = Command()._dependency_findings()
                        find.assert_called_once_with("buyer/qr/check.png")
                    glyph = next(item for item in findings if item.code == "qr-glyph")
                    self.assertEqual(glyph.level, "PASS" if valid else "FAIL")
                    self.assertIn("buyer/qr/check.png", glyph.message)
            with override_settings(BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH="buyer/qr/missing.png"):
                with patch.object(qr.finders, "find", return_value=None):
                    findings = Command()._dependency_findings()
            self.assertEqual(next(item.level for item in findings if item.code == "qr-glyph"), "FAIL")

    def test_qr_and_readiness_do_not_snapshot_brand_configuration(self):
        for relative in (
            "apps/orders/quick_link_qr.py",
            "apps/orders/management/commands/quick_link_readiness_check.py",
        ):
            source = (Path(settings.BASE_DIR) / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            self.assertNotIn(self.default_path, source)
            self.assertNotIn("BOOKING_QUICK_LINK_QR_GLYPH", source)
            self.assertNotIn("os.environ", source)
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = node.value
                    self.assertFalse(any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "get_deployment_brand_asset_config"
                        for call in ast.walk(value)
                    ))

    def test_print_integration_still_consumes_shared_qr_generator(self):
        path = Path(settings.BASE_DIR) / "apps/orders/quick_link_print_templates.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        self.assertTrue(any(
            isinstance(node, ast.ImportFrom) and node.module == "quick_link_qr"
            and any(alias.name == "generate_booking_quick_link_qr" for alias in node.names)
            for node in tree.body
        ))
        consumer = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_qr_image"
        )
        self.assertTrue(any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "generate_booking_quick_link_qr"
            for node in ast.walk(consumer)
        ))


class AuthenticationArtworkDeploymentBoundaryTests(SimpleTestCase):
    template_assets = (
        ("accounts/login.html", "login_hero_path", "branding/auth/login-desktop-hero.png"),
        ("accounts/customer_signup.html", "customer_signup_hero_path", "branding/auth/customer-signup-hero.png"),
        ("accounts/stylist_signup.html", "stylist_signup_hero_path", "branding/auth/stylist-signup-hero.png"),
        ("accounts/register.html", "manager_signup_hero_path", "branding/auth/manager-signup-hero.png"),
    )
    signup_templates = (
        "accounts/customer_signup.html",
        "accounts/stylist_signup.html",
        "accounts/register.html",
    )

    @staticmethod
    def _brand_context():
        return {
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
            "deployment_brand_colors": get_deployment_brand_color_config(),
        }

    def test_defaults_render_existing_artwork_and_signup_glyph(self):
        snapshot = get_deployment_brand_asset_config()
        self.assertEqual(len(fields(snapshot)), 24)
        self.assertEqual(snapshot.logo_glyph_path, "branding/logo/loomera-glyph-mark.png")
        for template_name, field, default in self.template_assets:
            with self.subTest(template=template_name):
                self.assertEqual(getattr(snapshot, field), default)
                self.assertTrue((Path(settings.BASE_DIR) / "static" / default).is_file())
                rendered = render_to_string(template_name, self._brand_context())
                self.assertIn(f'src="/static/{default}"', rendered)
                if template_name in self.signup_templates:
                    self.assertIn(
                        'src="/static/branding/logo/loomera-glyph-mark.png"',
                        rendered,
                    )

    def test_sequential_buyer_overrides_render_from_fresh_snapshots(self):
        first = get_deployment_brand_asset_config()
        for brand in ("buyer-one", "buyer-two"):
            overrides = {
                "BRAND_LOGIN_HERO_STATIC_PATH": f"{brand}/auth/login.webp",
                "BRAND_CUSTOMER_SIGNUP_HERO_STATIC_PATH": f"{brand}/auth/customer.png",
                "BRAND_STYLIST_SIGNUP_HERO_STATIC_PATH": f"{brand}/auth/stylist.png",
                "BRAND_MANAGER_SIGNUP_HERO_STATIC_PATH": f"{brand}/auth/manager.png",
                "BRAND_LOGO_GLYPH_STATIC_PATH": f"{brand}/brand/glyph.svg",
            }
            with override_settings(**overrides):
                snapshot = get_deployment_brand_asset_config()
                self.assertIsNot(snapshot, first)
                for template_name, field, default in self.template_assets:
                    with self.subTest(brand=brand, template=template_name):
                        setting_for_field = {
                            "login_hero_path": "BRAND_LOGIN_HERO_STATIC_PATH",
                            "customer_signup_hero_path": "BRAND_CUSTOMER_SIGNUP_HERO_STATIC_PATH",
                            "stylist_signup_hero_path": "BRAND_STYLIST_SIGNUP_HERO_STATIC_PATH",
                            "manager_signup_hero_path": "BRAND_MANAGER_SIGNUP_HERO_STATIC_PATH",
                        }
                        expected_path = overrides[setting_for_field[field]]
                        self.assertEqual(getattr(snapshot, field), expected_path)
                        rendered = render_to_string(template_name, self._brand_context())
                        self.assertIn(f'src="/static/{expected_path}"', rendered)
                        self.assertNotIn(f'src="/static/{default}"', rendered)
                        if template_name in self.signup_templates:
                            self.assertIn(
                                f'src="/static/{brand}/brand/glyph.svg"',
                                rendered,
                            )
        restored = get_deployment_brand_asset_config()
        for _, field, default in self.template_assets:
            self.assertEqual(getattr(restored, field), default)

    def test_auth_templates_do_not_embed_fixed_loomera_artwork_paths(self):
        root = Path(settings.BASE_DIR) / "templates"
        for template_name, field, default in self.template_assets:
            with self.subTest(template=template_name):
                source = (root / template_name).read_text(encoding="utf-8")
                self.assertIn(
                    "{% static deployment_brand_assets." + field + " %}",
                    source,
                )
                self.assertNotIn("{% static '" + default + "' %}", source)
                if template_name in self.signup_templates:
                    self.assertIn(
                        "{% static deployment_brand_assets.logo_glyph_path %}",
                        source,
                    )
                    self.assertNotIn(
                        "{% static 'branding/logo/loomera-glyph-mark.png' %}",
                        source,
                    )

    def test_signup_templates_use_dynamic_display_identity_without_fixed_labels(self):
        roles = (
            ("accounts/customer_signup.html", "مشتری"),
            ("accounts/stylist_signup.html", "متخصص"),
            ("accounts/register.html", "مدیر مجموعه"),
        )
        root = Path(settings.BASE_DIR) / "templates"
        for template_name, role in roles:
            with self.subTest(template=template_name):
                source = (root / template_name).read_text(encoding="utf-8")
                self.assertIn(
                    "{% block title %}ثبت‌نام " + role
                    + " | {{ deployment_brand.display_name }}{% endblock %}",
                    source,
                )
                self.assertIn(
                    'aria-label="صفحه اصلی {{ deployment_brand.display_name }}"',
                    source,
                )
                self.assertIn("<span>{{ deployment_brand.display_name }}</span>", source)
                self.assertEqual(source.count("deployment_brand.display_name"), 3)
                self.assertNotIn("<span>Loomera</span>", source)
                self.assertNotIn('aria-label="صفحه اصلی Loomera"', source)
                self.assertNotIn(f"ثبت‌نام {role} | لومرا", source)
                self.assertIn(
                    '<img src="{% static deployment_brand_assets.logo_glyph_path %}" '
                    'alt="" class="lm-signup-brand-logo" loading="eager" decoding="async">',
                    source,
                )
                self.assertIn("{% csrf_token %}", source)

    def test_signup_display_name_renders_default_and_sequential_buyer_overrides(self):
        default_name = get_deployment_brand_config().display_name
        self.assertEqual(default_name, "Loomera")
        roles = (
            ("accounts/customer_signup.html", "مشتری"),
            ("accounts/stylist_signup.html", "متخصص"),
            ("accounts/register.html", "مدیر مجموعه"),
        )

        for brand_name in ("Loomera", "Buyer Studio", "Second Buyer"):
            with override_settings(BRAND_DISPLAY_NAME=brand_name):
                self.assertEqual(get_deployment_brand_config().display_name, brand_name)
                for template_name, role in roles:
                    with self.subTest(brand=brand_name, template=template_name):
                        rendered = render_to_string(template_name, self._brand_context())
                        self.assertIn(f"ثبت‌نام {role} | {brand_name}", rendered)
                        self.assertIn(f'aria-label="صفحه اصلی {brand_name}"', rendered)
                        self.assertIn(f"<span>{brand_name}</span>", rendered)
                        self.assertIn(
                            'src="/static/branding/logo/loomera-glyph-mark.png"',
                            rendered,
                        )
                        if brand_name != "Loomera":
                            self.assertNotIn("<span>Loomera</span>", rendered)
                            self.assertNotIn('aria-label="صفحه اصلی Loomera"', rendered)

        self.assertEqual(get_deployment_brand_config().display_name, default_name)
        for template_name, role in roles:
            with self.subTest(restored_template=template_name):
                rendered = render_to_string(template_name, self._brand_context())
                self.assertIn(f"ثبت‌نام {role} | {default_name}", rendered)
