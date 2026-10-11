from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from loomera.branding import config as brand_config_module
from loomera.branding.config import (
    DeploymentBrandConfig,
    get_deployment_brand_config,
)

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
        self.assertEqual(
            config.default_from_email,
            "Loomera <no-reply@loomera.local>",
        )
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
        language_code = settings.LANGUAGE_CODE
        default_language = settings.LOOMERA_DEFAULT_LANGUAGE
        default_country = settings.LOOMERA_DEFAULT_COUNTRY
        default_currency = settings.LOOMERA_DEFAULT_CURRENCY
        default_timezone = settings.LOOMERA_DEFAULT_TIMEZONE
        sms_provider = settings.SMS_PROVIDER
        payment_provider = settings.PAYMENT_PROVIDER

        config = get_deployment_brand_config()

        self.assertEqual(config.name, "Acme")
        self.assertEqual(config.display_name, "Acme Global")
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

        self.assertEqual(settings.LANGUAGE_CODE, language_code)
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, default_language)
        self.assertEqual(settings.LOOMERA_DEFAULT_COUNTRY, default_country)
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, default_currency)
        self.assertEqual(settings.LOOMERA_DEFAULT_TIMEZONE, default_timezone)
        self.assertEqual(settings.SMS_PROVIDER, sms_provider)
        self.assertEqual(settings.PAYMENT_PROVIDER, payment_provider)

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
        self.assertNotIn("LANGUAGE_CODE", source)
        self.assertNotIn("LOOMERA_DEFAULT_LANGUAGE", source)
        self.assertNotIn("LOOMERA_DEFAULT_COUNTRY", source)
        self.assertNotIn("LOOMERA_DEFAULT_CURRENCY", source)
        self.assertNotIn("LOOMERA_DEFAULT_TIMEZONE", source)
        self.assertNotIn("MAP_PROVIDER", source)
        self.assertNotIn("SMS_PROVIDER", source)
        self.assertNotIn("PAYMENT_PROVIDER", source)
        self.assertNotIn("MESSAGING_ALLOWED_PROVIDERS", source)
