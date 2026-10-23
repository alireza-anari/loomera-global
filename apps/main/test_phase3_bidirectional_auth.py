"""Phase 3 slice 3.4 — auth form bidirectional presentation contract.

Source-level and template-engine regression guards, not browser screenshot QA.
"""

from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template import engines
from django.test import SimpleTestCase

from loomera.globalization.locale import DeploymentLocaleContext


class BidirectionalAuthPresentationTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def test_all_four_active_auth_forms_load_scoped_css_after_page_css(self):
        self.assertTrue(finders.find("css/components/bidirectional_auth.css"))
        for name, page in (
            ("login", "login"),
            ("register", "signup"),
            ("customer_signup", "signup"),
            ("stylist_signup", "signup"),
        ):
            with self.subTest(form=name):
                source = self.source(f"templates/accounts/{name}.html")
                self.assertTrue(source.startswith('{% extends "base.html" %}'))
                self.assertIn('{% block head %}', source)
                self.assertEqual(source.count("css/components/bidirectional_auth.css"), 1)
                self.assertLess(
                    source.index(f"css/pages/{page}.css"),
                    source.index("css/components/bidirectional_auth.css"),
                )
                self.assertIn("deployment_brand.display_name", source)
                self.assertIn('{% csrf_token %}', source)
                self.assertIn('method="post"', source)

    def test_scoped_styles_only_activate_for_ltr_and_keep_rtl_defaults(self):
        css = self.source("static/css/components/bidirectional_auth.css")
        self.assertIn('html[dir="ltr"]', css)
        self.assertNotIn('html[dir="rtl"]', css)
        self.assertNotIn("!important", css)
        self.assertNotIn("@import", css)
        self.assertEqual(css.count("{"), css.count("}"))
        for page in ("login", "signup"):
            legacy = self.source(f"static/css/pages/{page}.css")
            self.assertIn(".lm-", legacy)
            self.assertIn("right:", legacy)
        self.assertNotIn("direction: rtl", css)

    def test_ltr_login_card_has_mobile_safe_desktop_mirror_with_same_width(self):
        css = self.source("static/css/components/bidirectional_auth.css")
        login = self.source("static/css/pages/login.css")
        self.assertIn('@media (min-width: 1024px)', css)
        self.assertIn('@media (min-width: 1440px)', css)
        self.assertIn('html[dir="ltr"] .lm-login-visual-panel', css)
        self.assertIn("right: auto;", css)
        self.assertIn("left: clamp(2.5rem, 6vw, 7rem);", css)
        self.assertIn("left: clamp(4rem, 8vw, 8.75rem);", css)
        self.assertIn("width: clamp(31rem, 33vw, 35rem);", login)
        self.assertIn("width: clamp(32rem, 34vw, 36rem);", login)

    def test_ltr_signup_cards_mirror_with_shared_non_destructive_margins(self):
        css = self.source("static/css/components/bidirectional_auth.css")
        signup = self.source("static/css/pages/signup.css")
        self.assertIn('html[dir="ltr"] .lm-signup-frame', css)
        self.assertIn("justify-content: flex-start;", css)
        self.assertIn('html[dir="ltr"] .lm-signup-panel', css)
        self.assertIn("margin-right: auto;", css)
        self.assertIn("margin-left: clamp(1.75rem, 4.5vw, 5rem);", css)
        self.assertIn("margin-left: clamp(3rem, 6vw, 6.5rem);", css)
        self.assertIn("margin-right: clamp(1.75rem,4.5vw,5rem);", signup)

    def test_ltr_softener_mirrors_without_changing_brand_asset_contract(self):
        css = self.source("static/css/components/bidirectional_auth.css")
        self.assertIn(".lm-login-visual-background-softener", css)
        self.assertIn(".lm-signup-background-softener", css)
        self.assertIn("background: linear-gradient(", css)
        for name, variable in (
            ("login", "login_hero_path"),
            ("register", "manager_signup_hero_path"),
            ("customer_signup", "customer_signup_hero_path"),
            ("stylist_signup", "stylist_signup_hero_path"),
        ):
            with self.subTest(name=name):
                source = self.source(f"templates/accounts/{name}.html")
                self.assertIn(f"deployment_brand_assets.{variable}", source)

    def test_auth_forward_arrows_mirror_without_mirroring_password_icons(self):
        css = self.source("static/css/components/bidirectional_auth.css")
        self.assertIn("(.lm-login-submit, .lm-signup-submit) .fa-arrow-left", css)
        self.assertIn("transform: scaleX(-1);", css)
        self.assertNotIn(".fa-eye", css)
        self.assertNotIn(".fa-mobile-screen-button", css)
        for name in ("login", "customer_signup", "stylist_signup"):
            source = self.source(f"templates/accounts/{name}.html")
            self.assertIn('fa-arrow-left', source)
            self.assertIn('class="toggle-password', source)

    def test_mobile_and_password_input_contracts_are_preserved(self):
        for name in ("login", "register", "customer_signup", "stylist_signup"):
            with self.subTest(name=name):
                source = self.source(f"templates/accounts/{name}.html")
                self.assertIn('name="mobile_number"', source)
                self.assertIn('dir="ltr"', source)
                self.assertIn('inputmode="numeric"', source)
                self.assertIn('autocomplete="tel"', source)
                self.assertIn('type="password"', source)
                self.assertIn('data-input="id_password', source)
                self.assertIn("document.querySelectorAll('.toggle-password')", source)
                self.assertIn("e.target.value.replace(/[^\\d]/g, '')", source)

    def test_validation_password_strength_and_terms_controls_unchanged(self):
        for name in ("register", "customer_signup", "stylist_signup"):
            with self.subTest(name=name):
                source = self.source(f"templates/accounts/{name}.html")
                self.assertIn('name="agree_to_terms"', source)
                self.assertIn("form.non_field_errors", source)
                self.assertIn("form.password1.errors", source)
                self.assertIn("form.password2.errors", source)
                self.assertIn("autocomplete=\"new-password\"", source)
                self.assertIn('method="post"', source)
        for name in ("register", "stylist_signup"):
            source = self.source(f"templates/accounts/{name}.html")
            self.assertIn("data-strength-bar", source)
        self.assertIn('novalidate', self.source("templates/accounts/login.html"))
        self.assertIn('name="next"', self.source("templates/accounts/login.html"))

    def test_existing_root_html_locale_and_form_input_direction_are_independent(self):
        base = self.source("templates/base.html")
        html = next(line for line in base.splitlines() if "<html " in line)
        self.assertIn("deployment_locale.language_code", html)
        self.assertIn("deployment_locale.direction", html)
        for language, direction in (("fa", "rtl"), ("en", "ltr"), ("ar", "rtl")):
            with self.subTest(language=language):
                result = engines["django"].from_string(html).render({
                    "deployment_locale": DeploymentLocaleContext(
                        language, direction, ("fa", "en", "ar")
                    )
                })
                self.assertIn(f'lang="{language}"', result)
                self.assertIn(f'dir="{direction}"', result)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
