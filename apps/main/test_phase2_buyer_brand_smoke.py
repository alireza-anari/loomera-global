"""Phase 2 buyer-brand acceptance smoke and legacy email-layout reference audit.

This suite is deliberately database-free and does not attempt a deployment,
browser session, outbound message, migration, or Phase 3 locale activation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings

from loomera.branding.assets import get_deployment_brand_asset_config
from loomera.branding.colors import get_deployment_brand_color_config
from loomera.branding.config import get_deployment_brand_config
from loomera.branding.context_processors import deployment_brand
from apps.main.seo import build_service_schema


BUYER_SETTINGS = {
    "BRAND_NAME": "Aurora",
    "BRAND_DISPLAY_NAME": "Aurora Booking",
    "BRAND_DISPLAY_NAME_FA": "آرورا",
    "BRAND_DOMAIN": "aurora.example",
    "PUBLIC_BASE_URL": "https://www.aurora.example",
    "SITE_URL": "https://app.aurora.example",
    "LOOMERA_EMAIL_SENDER_NAME": "Aurora Mail",
    "DEFAULT_FROM_EMAIL": "Aurora Mail <hello@aurora.example>",
    "LOOMERA_SUPPORT_EMAIL": "support@aurora.example",
    "LOOMERA_PARTNER_EMAIL": "partners@aurora.example",
    "LOOMERA_MARKETING_EMAIL": "hello@aurora.example",
    "LOOMERA_CALENDAR_PRODID": "-//Aurora//Appointment//EN",
    "LOOMERA_CALENDAR_NAME": "Aurora Appointments",
    "BRAND_LOGO_PRIMARY_STATIC_PATH": "buyer/brand/logo.svg",
    "BRAND_FAVICON_SVG_STATIC_PATH": "buyer/brand/favicon.svg",
    "BRAND_WEBMANIFEST_STATIC_PATH": "buyer/brand/site.webmanifest",
    "BRAND_SOCIAL_IMAGE_STATIC_PATH": "buyer/brand/social.png",
    "BRAND_RECOVERY_LOGO_STATIC_PATH": "buyer/brand/recovery.svg",
    "BRAND_PRIMARY_COLOR": "#123456",
    "BRAND_BACKGROUND_COLOR": "#FDFEFF",
    "BRAND_BROWSER_THEME_DARK_COLOR": "#111122",
}


class Phase2BuyerBrandSmokeTests(SimpleTestCase):
    """Coordinated source/runtime contract smoke, not production acceptance."""

    def test_default_then_buyer_then_default_identity_isolated_across_consumers(self):
        default_brand = get_deployment_brand_config()
        default_assets = get_deployment_brand_asset_config()
        default_colors = get_deployment_brand_color_config()
        self.assertEqual(default_brand.display_name, "Loomera")
        self.assertEqual(default_brand.display_name_fa, "لومرا")
        self.assertEqual(default_brand.default_from_email, "Loomera <no-reply@loomera.local>")
        self.assertEqual(
            default_assets.recovery_logo_path,
            "branding/logo/loomera-logo-horizontal-transparent.png",
        )
        self.assertEqual(default_colors.primary_color, "#735CBE")
        baseline_runtime = (
            settings.LANGUAGE_CODE,
            settings.TIME_ZONE,
            settings.LOOMERA_DEFAULT_CALENDAR,
            settings.AUTH_USER_MODEL,
            settings.PAYMENT_PROVIDER,
        )
        with override_settings(**BUYER_SETTINGS):
            request = RequestFactory().get("/")
            context = deployment_brand(request)
            brand = context["deployment_brand"]
            assets = context["deployment_brand_assets"]
            colors = context["deployment_brand_colors"]

            self.assertIsNot(brand, default_brand)
            self.assertEqual((brand.name, brand.display_name, brand.display_name_fa),
                             ("Aurora", "Aurora Booking", "آرورا"))
            self.assertEqual(brand.domain, "aurora.example")
            self.assertEqual(brand.public_base_url, "https://www.aurora.example")
            self.assertEqual(brand.site_url, "https://app.aurora.example")
            self.assertEqual(brand.email_sender_name, "Aurora Mail")
            self.assertEqual(brand.default_from_email, "Aurora Mail <hello@aurora.example>")
            self.assertEqual(brand.support_email, "support@aurora.example")
            self.assertEqual(brand.partner_email, "partners@aurora.example")
            self.assertEqual(brand.marketing_email, "hello@aurora.example")
            self.assertEqual(brand.calendar_prodid, "-//Aurora//Appointment//EN")
            self.assertEqual(brand.calendar_name, "Aurora Appointments")
            self.assertEqual(assets.logo_primary_path, "buyer/brand/logo.svg")
            self.assertEqual(assets.recovery_logo_path, "buyer/brand/recovery.svg")
            self.assertEqual(colors.primary_color, "#123456")

            logo = render_to_string(
                "partials/brand/logo.html",
                {**context, "logo_variant": "full"},
            )
            head = render_to_string("partials/brand/head_assets.html", context)
            self.assertIn('src="/static/buyer/brand/logo.svg"', logo)
            self.assertIn('alt="Aurora Booking"', logo)
            self.assertIn('content="Aurora Booking"', head)
            self.assertIn('href="/static/buyer/brand/favicon.svg"', head)
            self.assertIn('href="/static/buyer/brand/site.webmanifest"', head)
            self.assertIn('content="#123456"', head)
            self.assertIn('content="#FDFEFF"', head)
            self.assertIn('content="#111122"', head)
            self.assertIn('content="fa_IR"', head)

            request = SimpleNamespace(
                build_absolute_uri=lambda value: f"https://www.aurora.example{value}"
            )
            service = SimpleNamespace(
                service_name="Cut",
                effective_seo_description="Test",
                get_absolute_url=lambda: "/services/cut/",
                service_image=None,
            )
            schema = json.loads(build_service_schema(request, service))
            self.assertEqual(schema["provider"]["name"], "Aurora Booking")
            self.assertEqual(schema["url"], "https://www.aurora.example/services/cut/")
            self.assertEqual(
                (
                    settings.LANGUAGE_CODE,
                    settings.TIME_ZONE,
                    settings.LOOMERA_DEFAULT_CALENDAR,
                    settings.AUTH_USER_MODEL,
                    settings.PAYMENT_PROVIDER,
                ),
                baseline_runtime,
            )
        self.assertEqual(get_deployment_brand_config(), default_brand)
        self.assertEqual(get_deployment_brand_asset_config(), default_assets)
        self.assertEqual(get_deployment_brand_color_config(), default_colors)

    def test_buyer_packaged_static_assets_are_discoverable_with_no_default_manifest_rewrite(self):
        files = {
            "buyer/brand/logo.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>",
            "buyer/brand/favicon.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>",
            "buyer/brand/recovery.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>",
            "buyer/brand/social.png": "fixture-placeholder",
            "buyer/brand/site.webmanifest": json.dumps(
                {"name": "Aurora Booking", "short_name": "Aurora"},
            ),
        }
        with TemporaryDirectory() as directory:
            for name, body in files.items():
                path = Path(directory) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
            with override_settings(
                **BUYER_SETTINGS,
                STATICFILES_DIRS=[directory],
            ):
                for name in files:
                    with self.subTest(path=name):
                        self.assertEqual(
                            Path(finders.find(name)).resolve(),
                            (Path(directory) / name).resolve(),
                        )
                brand_assets = get_deployment_brand_asset_config()
                manifest = json.loads(
                    (Path(directory) / brand_assets.webmanifest_path).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(manifest["name"], "Aurora Booking")
                self.assertEqual(manifest["short_name"], "Aurora")
                self.assertEqual(
                    render_to_string(
                        "partials/brand/logo.html",
                        {
                            **deployment_brand(RequestFactory().get("/")),
                            "logo_variant": "full",
                        },
                    ).count("/static/buyer/brand/logo.svg"),
                    1,
                )
        default_manifest = (
            Path(settings.BASE_DIR) / "static/branding/favicon/site.webmanifest"
        )
        self.assertEqual(json.loads(default_manifest.read_text(encoding="utf-8"))["name"], "Loomera")

    def test_buyer_environment_values_import_without_code_edits(self):
        # This imports real environment-backed settings in fresh subprocesses;
        # template rendering is exercised separately above via override_settings.
        code = (
            "import json\n"
            "from loomera.settings import base\n"
            "print('PHASE2_BUYER_SMOKE='+json.dumps({\n"
            "'name':base.BRAND_NAME,\n"
            "'latin':base.BRAND_DISPLAY_NAME,\n"
            "'persian':base.BRAND_DISPLAY_NAME_FA,\n"
            "'domain':base.BRAND_DOMAIN,\n"
            "'site':base.SITE_URL,\n"
            "'from':base.DEFAULT_FROM_EMAIL,\n"
            "'logo':base.BRAND_LOGO_PRIMARY_STATIC_PATH,\n"
            "'recovery':base.BRAND_RECOVERY_LOGO_STATIC_PATH,\n"
            "'primary':base.BRAND_PRIMARY_COLOR,\n"
            "'calendar':base.LOOMERA_CALENDAR_PRODID,\n"
            "}, ensure_ascii=False))\n"
        )
        for scenario, overrides in (
            ("default", {}),
            ("buyer", BUYER_SETTINGS),
        ):
            with self.subTest(scenario=scenario):
                env = os.environ.copy()
                for key in BUYER_SETTINGS:
                    env.pop(key, None)
                env.update(
                    {
                        "SECRET_KEY": "ci-only-phase2-brand-smoke",
                        "DATABASE_URL": "sqlite:///phase2-smoke.sqlite3",
                        "DEBUG": "False",
                        "ALLOWED_HOSTS": "localhost",
                        "CSRF_TRUSTED_ORIGINS": "http://localhost",
                        "ONLINE_PAYMENT_ENABLED": "False",
                        "PAYMENT_MODE": "mock",
                        **{key: str(val) for key, val in overrides.items()},
                    }
                )
                completed = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=settings.BASE_DIR,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr[-2000:])
                payloads = [
                    line.removeprefix("PHASE2_BUYER_SMOKE=")
                    for line in completed.stdout.splitlines()
                    if line.startswith("PHASE2_BUYER_SMOKE=")
                ]
                self.assertEqual(len(payloads), 1)
                payload = json.loads(payloads[0])
                if scenario == "default":
                    self.assertEqual(payload["latin"], "Loomera")
                    self.assertEqual(payload["persian"], "لومرا")
                    self.assertEqual(payload["recovery"], "branding/logo/loomera-logo-horizontal-transparent.png")
                else:
                    self.assertEqual(payload["name"], "Aurora")
                    self.assertEqual(payload["latin"], "Aurora Booking")
                    self.assertEqual(payload["persian"], "آرورا")
                    self.assertEqual(payload["domain"], "aurora.example")
                    self.assertEqual(payload["site"], "https://app.aurora.example")
                    self.assertEqual(payload["from"], "Aurora Mail <hello@aurora.example>")
                    self.assertEqual(payload["logo"], "buyer/brand/logo.svg")
                    self.assertEqual(payload["recovery"], "buyer/brand/recovery.svg")
                    self.assertEqual(payload["primary"], "#123456")
                    self.assertEqual(payload["calendar"], "-//Aurora//Appointment//EN")


class LegacyEmailLayoutStaticReferenceAuditTests(SimpleTestCase):
    """Classify exact, statically referenced HTML layout names across runtime source."""

    def test_no_runtime_source_statically_references_the_two_legacy_email_layouts(self):
        project = Path(settings.BASE_DIR)
        layouts = (
            "loomera_email_base_rtl",
            "loomera_minimal_transactional",
        )
        reference_paths = []
        for root in ("apps", "loomera", "templates", "middlewares"):
            for path in (project / root).rglob("*"):
                if path.suffix not in {".py", ".html"}:
                    continue
                relative = path.relative_to(project)
                if "migrations" in relative.parts or "__pycache__" in relative.parts:
                    continue
                if path.name.startswith("test") or "tests" in relative.parts:
                    continue
                if relative.as_posix() in {
                    "templates/email/loomera_email_base_rtl.html",
                    "templates/email/loomera_minimal_transactional.html",
                }:
                    continue
                contents = path.read_text(encoding="utf-8")
                if any(name in contents for name in layouts):
                    reference_paths.append(relative.as_posix())
        self.assertEqual(
            sorted(reference_paths), [],
            msg="A legacy HTML email layout gained a static consumer; "
                "review its rendering context before declaring it unused.",
        )
