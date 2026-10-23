"""Phase 3 slice 3.1: request locale and bidirectional shell regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.http import HttpResponse
from django.template import engines
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import translation

from loomera.globalization.context_processors import deployment_locale
from loomera.globalization.locale import (
    DeploymentLocaleContext,
    get_deployment_locale_context,
    resolve_request_locale,
)
from loomera.globalization.middleware import DeploymentLocaleMiddleware


ENABLED = (("en", "English"), ("ar", "العربية"), ("fa", "فارسی"))


@override_settings(
    LOOMERA_DEFAULT_LANGUAGE="en",
    LOOMERA_ENABLED_LANGUAGES=["en", "ar", "fa"],
    LANGUAGES=ENABLED,
)
class DeploymentLocaleResolutionTests(SimpleTestCase):
    def tearDown(self):
        translation.deactivate_all()

    @staticmethod
    def _request(*, accept="", session=None, cookie=None, path="/health/"):
        request = RequestFactory().get(path, HTTP_ACCEPT_LANGUAGE=accept)
        request.session = dict(session or {})
        if cookie is not None:
            request.COOKIES[settings.LANGUAGE_COOKIE_NAME] = cookie
        return request

    def test_precedence_session_then_cookie_then_header_then_default(self):
        choices = [
            ({}, "ar"),
            ({"accept": "fa,en;q=0.5"}, "fa"),
            ({"accept": "fa", "cookie": "ar"}, "ar"),
            ({"accept": "fa", "cookie": "ar", "session": {"loomera_language": "en"}}, "en"),
            ({"accept": "fa", "cookie": "not-a-locale", "session": {"loomera_language": "xx"}}, "fa"),
        ]
        for kwargs, expected in choices:
            with self.subTest(kwargs=kwargs):
                request = self._request(**kwargs)
                # No accepted signal means the configured default wins.
                if not kwargs:
                    expected = "en"
                self.assertEqual(resolve_request_locale(request), expected)
                self.assertNotIn("loomera_language", request.session) if not kwargs.get("session") else None

    def test_weighted_accept_language_region_and_disabled_choices(self):
        cases = (
            ("fa-IR,ar;q=0.8,en;q=0.4", "fa"),
            ("en-US;q=0.7,ar-SA;q=0.9", "ar"),
            ("en;q=0,ar;q=0.6", "ar"),
            ("*;q=1,fr;q=0.8", "en"),
            ("fr;q=0.9,fa;q=0.2", "fa"),
            ("fa;q=1.01,en;q=0.3", "en"),
            ("fa;q=broken,ar;q=0.2", "ar"),
            ("ar;q=0,en;q=0", "en"),
            ("EN-us,fa;q=0.5", "en"),
        )
        for header, expected in cases:
            with self.subTest(header=header):
                self.assertEqual(
                    resolve_request_locale(self._request(accept=header)), expected
                )

    def test_disabled_session_and_cookie_cannot_select_language(self):
        with override_settings(
            LOOMERA_DEFAULT_LANGUAGE="fa",
            LOOMERA_ENABLED_LANGUAGES=["fa"],
            LANGUAGES=(("fa", "فارسی"),),
        ):
            req = self._request(
                accept="en-US,ar;q=0.9",
                cookie="ar",
                session={"loomera_language": "en"},
            )
            self.assertEqual(resolve_request_locale(req), "fa")
            self.assertEqual(get_deployment_locale_context(req).direction, "rtl")

    def test_locale_has_no_query_string_or_identity_privilege_override(self):
        req = self._request(path="/health/?language=ar&next=/admin/", accept="en")
        req.user = SimpleNamespace(is_authenticated=True, locale="ar")
        self.assertEqual(resolve_request_locale(req), "en")
        self.assertEqual(req.session, {})
        self.assertNotIn(settings.LANGUAGE_COOKIE_NAME, req.COOKIES)

    def test_middleware_activates_locale_for_request_and_preserves_django_response_rules(self):
        for requested, expected in (("en", "en"), ("ar", "ar"), ("fa", "fa")):
            with self.subTest(requested=requested):
                req = self._request(accept=requested)
                observed = {}

                def view(request):
                    observed["language"] = translation.get_language()
                    observed["context"] = get_deployment_locale_context(request)
                    return HttpResponse("ok")

                response = DeploymentLocaleMiddleware(view)(req)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(req.LANGUAGE_CODE, expected)
                self.assertEqual(observed["language"], expected)
                self.assertEqual(observed["context"].language_code, expected)
                self.assertEqual(response["Content-Language"], expected)
                self.assertEqual(
                    observed["context"].direction,
                    "rtl" if expected in ("fa", "ar") else "ltr",
                )

    def test_language_context_is_immutable_and_derived_only_from_enabled_locale(self):
        req = self._request(accept="ar")
        context = deployment_locale(req)
        self.assertEqual(set(context), {"deployment_locale"})
        value = context["deployment_locale"]
        self.assertIsInstance(value, DeploymentLocaleContext)
        self.assertEqual(value.language_code, "ar")
        self.assertEqual(value.direction, "rtl")
        self.assertTrue(value.is_rtl)
        self.assertEqual(value.enabled_languages, ("en", "ar", "fa"))
        with self.assertRaises(AttributeError):
            value.direction = "ltr"

    def test_no_unapproved_locale_activation_without_enabled_default(self):
        with override_settings(
            LOOMERA_DEFAULT_LANGUAGE="ar",
            LOOMERA_ENABLED_LANGUAGES=["en"],
        ):
            with self.assertRaises(ValueError):
                resolve_request_locale(self._request(accept="en"))

    def test_locale_selection_never_writes_session_or_cookie(self):
        req = self._request(
            accept="ar",
            cookie="fa",
            session={"loomera_language": "en", "auth_data": "keep"},
        )
        before_session = req.session.copy()
        before_cookie = req.COOKIES.copy()
        self.assertEqual(resolve_request_locale(req), "en")
        self.assertEqual(req.session, before_session)
        self.assertEqual(req.COOKIES, before_cookie)


class DeploymentLocaleShellTests(SimpleTestCase):
    @staticmethod
    def _source(path):
        return (Path(settings.BASE_DIR) / "templates" / path).read_text(
            encoding="utf-8"
        )

    @staticmethod
    def _context(locale):
        return {
            "deployment_locale": DeploymentLocaleContext(
                locale, "rtl" if locale in ("fa", "ar") else "ltr",
                ("fa", "en", "ar"),
            )
        }

    def test_both_shared_document_shells_support_all_three_languages(self):
        for path in ("base.html", "dashboard_template.html"):
            source = self._source(path)
            head = next(line for line in source.splitlines() if "<html " in line)
            self.assertIn("deployment_locale.language_code", head)
            self.assertIn("deployment_locale.direction", head)
            for locale in ("fa", "en", "ar"):
                with self.subTest(path=path, language=locale):
                    output = engines["django"].from_string(head).render(
                        self._context(locale)
                    )
                    self.assertIn(f'lang="{locale}"', output)
                    self.assertIn(
                        f'dir="{"ltr" if locale == "en" else "rtl"}"', output
                    )
            without_request = engines["django"].from_string(head).render({})
            self.assertIn('lang="fa"', without_request)
            self.assertIn('dir="rtl"', without_request)

    def test_dormant_email_layouts_accept_explicit_locale_without_request_context(self):
        for name in (
            "email/loomera_email_base_rtl.html",
            "email/loomera_minimal_transactional.html",
        ):
            src = self._source(name)
            self.assertIn("deployment_locale.direction", src)
            for locale in ("fa", "en", "ar"):
                with self.subTest(name=name, locale=locale):
                    rendered = render_to_string(
                        name, {
                            **self._context(locale),
                            "headline": "Subject",
                            "body_html": "Body",
                        }
                    )
                    direction = "ltr" if locale == "en" else "rtl"
                    self.assertIn(f'lang="{locale}" dir="{direction}"', rendered)
                    self.assertIn(f"direction:{direction};", rendered)
            legacy = render_to_string(name, {"headline": "Subject", "body_html": "Body"})
            self.assertIn('lang="fa" dir="rtl"', legacy)
            self.assertIn("direction:rtl;", legacy)

    def test_template_processor_is_explicit_and_compatibility_middleware_order_preserved(self):
        processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
        self.assertEqual(
            processors.count("loomera.globalization.context_processors.deployment_locale"),
            1,
        )
        stack = settings.MIDDLEWARE
        self.assertNotIn("django.middleware.locale.LocaleMiddleware", stack)
        self.assertEqual(
            stack.count("loomera.globalization.middleware.DeploymentLocaleMiddleware"),
            1,
        )
        self.assertLess(
            stack.index("django.contrib.sessions.middleware.SessionMiddleware"),
            stack.index("loomera.globalization.middleware.DeploymentLocaleMiddleware"),
        )
        self.assertLess(
            stack.index("django.contrib.auth.middleware.AuthenticationMiddleware"),
            stack.index("loomera.globalization.middleware.DeploymentLocaleMiddleware"),
        )
        self.assertLess(
            stack.index("django.middleware.csrf.CsrfViewMiddleware"),
            stack.index("loomera.globalization.middleware.DeploymentLocaleMiddleware"),
        )

    def test_legacy_fa_default_and_product_business_settings_stay_unchanged(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.LOOMERA_DEFAULT_LANGUAGE, "fa")
        self.assertEqual(tuple(settings.LOOMERA_ENABLED_LANGUAGES), ("fa",))
        self.assertEqual(tuple(settings.LANGUAGES), (("fa", "فارسی"),))
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        context = deployment_locale(RequestFactory().get("/health/"))
        self.assertEqual(context["deployment_locale"].language_code, "fa")
        self.assertEqual(context["deployment_locale"].direction, "rtl")
