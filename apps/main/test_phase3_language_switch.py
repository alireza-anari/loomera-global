"""Phase 3 slice 3.2: POST-only locale persistence and selector/catalog guards."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.test import Client, SimpleTestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from loomera.globalization.locale import (
    LANGUAGE_SESSION_KEY,
    DeploymentLocaleContext,
)


ENABLED = (("en", "English"), ("ar", "العربية"), ("fa", "فارسی"))


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    LOOMERA_DEFAULT_LANGUAGE="en",
    LOOMERA_ENABLED_LANGUAGES=["en", "ar", "fa"],
    LANGUAGES=ENABLED,
)
class DeploymentLanguageSelectionTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("set_deployment_language")

    def tearDown(self):
        translation.deactivate_all()

    def test_valid_selection_persists_session_and_cookie_through_next_request(self):
        client = Client()
        response = client.post(
            self.url, {"language": "ar", "next": "/services/?tab=1"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/services/?tab=1")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "ar")
        self.assertEqual(client.cookies[settings.LANGUAGE_COOKIE_NAME].value, "ar")
        self.assertTrue(client.cookies[settings.LANGUAGE_COOKIE_NAME]["httponly"])
        self.assertEqual(
            client.cookies[settings.LANGUAGE_COOKIE_NAME]["path"],
            settings.LANGUAGE_COOKIE_PATH,
        )
        page = client.get("/health/", HTTP_ACCEPT_LANGUAGE="fa")
        self.assertEqual(page["Content-Language"], "ar")
        self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "ar")

        second = client.post(self.url, {"language": "fa", "next": "/"})
        self.assertEqual(second.status_code, 302)
        self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "fa")
        self.assertEqual(client.cookies[settings.LANGUAGE_COOKIE_NAME].value, "fa")
        self.assertEqual(client.get("/health/")["Content-Language"], "fa")

    def test_invalid_and_disabled_language_never_mutate_existing_preference(self):
        client = Client()
        selected = client.post(self.url, {"language": "fa"})
        self.assertEqual(selected.status_code, 302)
        self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "fa")
        for invalid in ("", "xx", "fr", "en-US", "fa; q=1", "a" * 40):
            with self.subTest(language=invalid):
                failed = client.post(self.url, {"language": invalid})
                self.assertEqual(failed.status_code, 400)
                self.assertNotIn("Location", failed)
                self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "fa")
                self.assertEqual(
                    client.cookies[settings.LANGUAGE_COOKIE_NAME].value, "fa"
                )
                self.assertNotIn(settings.LANGUAGE_COOKIE_NAME, failed.cookies)

        with override_settings(
            LOOMERA_DEFAULT_LANGUAGE="fa",
            LOOMERA_ENABLED_LANGUAGES=["fa"],
            LANGUAGES=(("fa", "فارسی"),),
        ):
            disabled = client.post(self.url, {"language": "en"})
            self.assertEqual(disabled.status_code, 400)
            self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "fa")

    def test_switch_does_not_touch_unrelated_session_or_identity(self):
        client = Client()
        current = client.session
        current["workspace_id"] = 91
        current["user_custom"] = {"choice": 2}
        current.save()
        response = client.post(self.url, {"language": "en"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.session["workspace_id"], 91)
        self.assertEqual(client.session["user_custom"], {"choice": 2})
        self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "en")

    def test_only_safe_root_relative_return_urls_are_allowed(self):
        client = Client()
        for bad in (
            "https://evil.example/phish",
            "//evil.example/phish",
            "http://testserver/absolute",
            "javascript:alert(1)",
            "next/page/",
            r"/\evil.example",
            "",
        ):
            with self.subTest(next=bad):
                response = client.post(
                    self.url, {"language": "en", "next": bad}
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], "/")
        response = client.post(
            self.url,
            {"language": "ar", "next": "/accounts/login/?next=%2Fservices%2F"},
        )
        self.assertEqual(
            response["Location"], "/accounts/login/?next=%2Fservices%2F"
        )

    def test_csrf_and_post_only_are_enforced(self):
        client = Client(enforce_csrf_checks=True)
        get_response = client.get(self.url)
        self.assertEqual(get_response.status_code, 405)
        no_csrf = client.post(self.url, {"language": "ar"})
        self.assertEqual(no_csrf.status_code, 403)
        self.assertNotIn(LANGUAGE_SESSION_KEY, client.session)
        client.cookies[settings.CSRF_COOKIE_NAME] = "a" * 32
        with_csrf = client.post(
            self.url,
            {"language": "ar", "next": "/"},
            HTTP_X_CSRFTOKEN="a" * 32,
        )
        self.assertEqual(with_csrf.status_code, 302)
        self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "ar")

    @override_settings(
        LANGUAGE_COOKIE_SECURE=True,
        LANGUAGE_COOKIE_SAMESITE="Strict",
        LANGUAGE_COOKIE_PATH="/",
    )
    def test_language_cookie_obeys_deployment_security_settings(self):
        response = Client().post(
            self.url, {"language": "en"}
        )
        self.assertEqual(response.status_code, 302)
        cookie = response.cookies[settings.LANGUAGE_COOKIE_NAME]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/")
        self.assertEqual(cookie["max-age"], str(settings.LANGUAGE_COOKIE_AGE))

    def test_anonymous_selection_and_multi_deployment_constraints(self):
        client = Client()
        self.assertEqual(client.post(self.url, {"language": "en"}).status_code, 302)
        self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "en")
        with override_settings(
            LOOMERA_DEFAULT_LANGUAGE="fa",
            LOOMERA_ENABLED_LANGUAGES=["fa"],
            LANGUAGES=(("fa", "فارسی"),),
        ):
            self.assertEqual(client.get("/health/")["Content-Language"], "fa")
            self.assertEqual(
                client.post(self.url, {"language": "ar"}).status_code, 400
            )
            self.assertEqual(
                client.post(self.url, {"language": "fa"}).status_code, 302
            )
            self.assertEqual(client.session[LANGUAGE_SESSION_KEY], "fa")


class DeploymentLanguageSwitcherPresentationTests(SimpleTestCase):
    @staticmethod
    def _partial(locale, enabled, variant="mobile", next_url="/services/"):
        return render_to_string(
            "partials/shell/language_switcher.html",
            {
                "deployment_locale": DeploymentLocaleContext(
                    locale, "rtl" if locale in ("fa", "ar") else "ltr", enabled
                ),
                "language_switcher_variant": variant,
                "request": SimpleNamespace(get_full_path=lambda: next_url),
            },
        )

    def test_one_enabled_locale_keeps_existing_shell_ui_identical(self):
        rendered = self._partial("fa", ("fa",))
        self.assertNotIn("<form", rendered)
        self.assertNotIn("data-deployment-language-switcher", rendered)

    def test_three_locales_have_local_names_unique_id_and_selected_state(self):
        enabled = ("en", "ar", "fa")
        for locale in enabled:
            with self.subTest(language=locale):
                result = self._partial(locale, enabled, variant="desktop")
                self.assertIn('method="post"', result)
                self.assertIn('action="/language/"', result)
                self.assertIn('name="language"', result)
                self.assertIn('name="next" value="/services/"', result)
                self.assertIn('id="lm-language-desktop"', result)
                self.assertEqual(result.count(' selected'), 1)
                self.assertIn(f'value="{locale}" selected', result)
                for label in ("English", "العربية", "فارسی"):
                    self.assertIn(label, result)
                self.assertIn('dir="auto"', result)

    def test_no_unsafe_html_from_next_parameter(self):
        rendered = self._partial(
            "en", ("en", "fa"), next_url='/?next=" onclick="alert(1)'
        )
        self.assertIn("&quot; onclick=&quot;", rendered)
        self.assertNotIn('value="/?next=" onclick="alert(1)"', rendered)

    def test_public_mobile_desktop_and_partner_shells_include_one_switcher(self):
        templates = (
            ("partials/shell/mobile_app_header.html", "mobile"),
            ("partials/shell/desktop_site_header.html", "desktop"),
            ("dashboard_template.html", "dashboard"),
        )
        for path, variant in templates:
            with self.subTest(path=path):
                source = (
                    Path(settings.BASE_DIR) / "templates" / path
                ).read_text(encoding="utf-8")
                expected = (
                    '{% include "partials/shell/language_switcher.html" '
                    f'with language_switcher_variant="{variant}" %}}'
                )
                self.assertIn(expected, source)
                self.assertEqual(source.count("language_switcher.html"), 1)

    def test_actual_translated_system_labels_load_from_compiled_catalogs(self):
        expected = {
            "en": ("Language", "Apply language"),
            "fa": ("زبان", "تأیید زبان"),
            "ar": ("اللغة", "تطبيق اللغة"),
        }
        self.assertEqual(
            tuple(Path(p).resolve() for p in settings.LOCALE_PATHS),
            (Path(settings.BASE_DIR, "locale").resolve(),),
        )
        for lang, (label, apply) in expected.items():
            with self.subTest(language=lang):
                folder = Path(settings.BASE_DIR, "locale", lang, "LC_MESSAGES")
                self.assertTrue((folder / "django.po").is_file())
                self.assertTrue((folder / "django.mo").is_file())
                with translation.override(lang):
                    self.assertEqual(translation.gettext("Language"), label)
                    self.assertEqual(translation.gettext("Apply language"), apply)

    def test_language_switching_does_not_mutate_business_defaults(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
