from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.main.management.commands.build_release_archive import (
    forbidden_release_reason,
)
from apps.main.seo import build_service_schema


class BuildReleaseArchiveTests(SimpleTestCase):
    def test_environment_secret_files_are_forbidden(self):
        forbidden_paths = (
            ".env",
            ".env.local",
            ".env.staging",
            ".env.production",
            "config/.env",
            "config/.env.secret",
        )

        for path in forbidden_paths:
            with self.subTest(path=path):
                self.assertIsNotNone(forbidden_release_reason(path))

    def test_env_example_is_allowed(self):
        self.assertIsNone(forbidden_release_reason(".env.example"))

    def test_python_cache_artifacts_are_forbidden(self):
        forbidden_paths = (
            "__pycache__/module.cpython-313.pyc",
            "apps/orders/__pycache__/views.cpython-313.pyc",
            "apps/orders/views.pyc",
            "apps/orders/views.pyo",
        )

        for path in forbidden_paths:
            with self.subTest(path=path):
                self.assertIsNotNone(forbidden_release_reason(path))

    def test_database_dump_and_nested_archive_are_forbidden(self):
        forbidden_paths = (
            "backup.sql",
            "database.dump",
            "local.sqlite3",
            "exports/project.zip",
            "exports/project.tar.gz",
        )

        for path in forbidden_paths:
            with self.subTest(path=path):
                self.assertIsNotNone(forbidden_release_reason(path))

    def test_normal_project_files_are_allowed(self):
        allowed_paths = (
            "manage.py",
            "requirements.txt",
            "apps/orders/views.py",
            "static/branding/share/loomera-social-preview-v1.png",
            "templates/base.html",
        )

        for path in allowed_paths:
            with self.subTest(path=path):
                self.assertIsNone(forbidden_release_reason(path))

    def test_release_artifacts_directory_is_ignored(self):
        project_root = Path(settings.BASE_DIR)

        gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")

        liaraignore = (project_root / ".liaraignore").read_text(encoding="utf-8")

        self.assertIn(
            "/release_artifacts/",
            gitignore.splitlines(),
        )
        self.assertIn(
            "release_artifacts/",
            liaraignore.splitlines(),
        )


class MachineReadableBrandIdentityWiringTests(SimpleTestCase):
    @override_settings(
        LOOMERA_PUBLIC_APP_VERSION="2026.10",
        LOOMERA_PUBLIC_BUILD_ID="build-25",
        LOOMERA_API_VERSION="v1-test",
        LANGUAGE_CODE="fa",
    )
    def test_api_v1_meta_uses_one_deployment_brand_snapshot_without_changing_other_metadata(self):
        deployment_brand = SimpleNamespace(
            name="Acme",
            display_name="Acme Booking",
        )

        with patch(
            "apps.api.v1.views.get_deployment_brand_config",
            return_value=deployment_brand,
        ) as get_brand:
            response = self.client.get(reverse("api:v1:meta"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        application = payload["data"]["application"]

        self.assertEqual(application["name"], "Acme Booking")
        self.assertEqual(application["brand"], "Acme")
        self.assertEqual(application["version"], "2026.10")
        self.assertEqual(application["build"], "build-25")
        self.assertEqual(payload["data"]["api"]["version"], "v1-test")
        self.assertEqual(payload["data"]["api"]["base_path"], "/api/v1/")
        self.assertEqual(payload["data"]["localization"]["default_language"], "fa")
        self.assertIs(payload["data"]["localization"]["rtl"], True)
        self.assertIn("time_utc", payload["data"]["server"])
        get_brand.assert_called_once_with()

    def test_machine_readable_consumers_do_not_read_brand_settings_directly(self):
        project_root = Path(settings.BASE_DIR)
        api_source = (project_root / "apps" / "api" / "v1" / "views.py").read_text(
            encoding="utf-8"
        )
        seo_source = (project_root / "apps" / "main" / "seo.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("BRAND_NAME", api_source)
        self.assertNotIn("BRAND_DISPLAY_NAME", api_source)
        self.assertNotIn("BRAND_DISPLAY_NAME", seo_source)
        self.assertNotIn("from django.conf import settings", seo_source)

    def test_service_schema_uses_one_deployment_brand_snapshot_for_provider_identity(self):
        deployment_brand = SimpleNamespace(
            name="Acme",
            display_name="Acme Booking",
        )
        request = SimpleNamespace(
            build_absolute_uri=lambda path: f"https://example.test{path}"
        )
        service = SimpleNamespace(
            service_name="Haircut",
            effective_seo_description="Service description",
            get_absolute_url=lambda: "/services/haircut/",
            service_image=None,
        )

        with patch(
            "apps.main.seo.get_deployment_brand_config",
            return_value=deployment_brand,
        ) as get_brand:
            schema = json.loads(build_service_schema(request, service))

        self.assertEqual(
            schema["provider"],
            {
                "@type": "Organization",
                "name": "Acme Booking",
            },
        )
        self.assertEqual(schema["@context"], "https://schema.org")
        self.assertEqual(schema["@type"], "Service")
        self.assertEqual(schema["name"], "Haircut")
        self.assertEqual(schema["description"], "Service description")
        self.assertEqual(schema["url"], "https://example.test/services/haircut/")
        get_brand.assert_called_once_with()
