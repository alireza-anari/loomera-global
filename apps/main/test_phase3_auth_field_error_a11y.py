"""Phase 3.15: active auth field-error accessibility across login/signup.

Template rendering tests remain database-free.  All error messages here are
synthetic form presentation inputs, not database-backed validation execution.
"""
import re
from pathlib import Path

from django.conf import settings
from django.forms.utils import ErrorDict
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation

from apps.accounts.forms import (
    LoginUserForm,
    RegisterUserForm,
    CustomerSignupForm,
    StylistSignupForm,
)
from loomera.branding.config import get_deployment_brand_config
from loomera.branding.assets import get_deployment_brand_asset_config
from loomera.branding.colors import get_deployment_brand_color_config


FORMS = {
    "login": (LoginUserForm, ("mobile_number", "password")),
    "register": (
        RegisterUserForm,
        ("name", "family", "mobile_number", "password1", "password2", "agree_to_terms"),
    ),
    "customer_signup": (
        CustomerSignupForm,
        ("name", "family", "mobile_number", "password1", "password2", "agree_to_terms"),
    ),
    "stylist_signup": (
        StylistSignupForm,
        ("name", "family", "expert", "mobile_number", "password1", "password2", "agree_to_terms"),
    ),
}


class AuthFieldErrorAccessibilityTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @staticmethod
    def context(form):
        return {
            "form": form,
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
            "deployment_brand_colors": get_deployment_brand_color_config(),
        }

    @staticmethod
    def with_field_errors(form, fields):
        # Inject presentation errors without invoking ModelForm validation/DB.
        form._errors = ErrorDict()
        form.cleaned_data = {}
        for field in fields:
            form.add_error(field, "Test <script>alert(1)</script> & invalid")
        return form

    @staticmethod
    def input_tag(html, name):
        matches = re.findall(
            r'<input\b[^>]*\bname="' + re.escape(name) + r'"[^>]*>',
            html,
        )
        assert len(matches) == 1, (name, len(matches))
        return matches[0]

    def tearDown(self):
        translation.deactivate_all()

    def test_all_fields_are_marked_valid_in_pristine_render(self):
        for language in ("fa", "en", "ar"):
            with translation.override(language):
                for page, (form_type, fields) in FORMS.items():
                    with self.subTest(locale=language, page=page):
                        html = render_to_string(
                            f"accounts/{page}.html", self.context(form_type())
                        )
                        for field in fields:
                            tag = self.input_tag(html, field)
                            self.assertIn('aria-invalid="false"', tag)
                            self.assertNotIn(f"id_{field}-error", tag)
                            self.assertNotIn(f'id="id_{field}-error"', html)
                        self.assertIn("deployment_brand", self.source(f"templates/accounts/{page}.html"))

    def test_every_failed_field_is_connected_to_its_rendered_error(self):
        for language in ("fa", "en", "ar"):
            with translation.override(language):
                for page, (form_type, fields) in FORMS.items():
                    with self.subTest(locale=language, page=page):
                        html = render_to_string(
                            f"accounts/{page}.html",
                            self.context(self.with_field_errors(form_type(), fields)),
                        )
                        for field in fields:
                            tag = self.input_tag(html, field)
                            self.assertIn('aria-invalid="true"', tag)
                            self.assertIn(f'id_{field}-error', tag)
                            self.assertEqual(
                                html.count(f'id="id_{field}-error" role="alert"'), 1
                            )
                        self.assertNotIn("<script>alert(1)</script>", html)
                        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_password_hints_remain_attached_with_and_without_server_errors(self):
        for page in ("register", "customer_signup", "stylist_signup"):
            form_type, fields = FORMS[page]
            with self.subTest(page=page):
                for failed in (False, True):
                    form = form_type()
                    if failed:
                        form = self.with_field_errors(form, ("password1",))
                    html = render_to_string(f"accounts/{page}.html", self.context(form))
                    tag = self.input_tag(html, "password1")
                    self.assertIn('id="id_password1-hint"', html)
                    self.assertIn(
                        'aria-describedby="id_password1-hint'
                        + (" id_password1-error" if failed else "")
                        + '"', tag,
                    )
                    self.assertEqual(html.count('id="id_password1-hint"'), 1)

    def test_all_field_error_references_match_exact_single_ids_in_sources(self):
        for page, (_, fields) in FORMS.items():
            src = self.source(f"templates/accounts/{page}.html")
            with self.subTest(page=page):
                for field in fields:
                    self.assertEqual(src.count(f'id="id_{field}-error"'), 1)
                    self.assertEqual(src.count(f"form.{field}.errors.0"), 1)
                    self.assertIn('aria-describedby="id_password1-hint' if field == "password1" else f'aria-describedby="id_{field}-error"', src)
                    self.assertIn(f"form.{field}.errors", src)
                self.assertEqual(src.count("role=\"alert\""), len(fields) + 1)

    def test_security_and_identity_contracts_remain_unchanged(self):
        for page, (_, fields) in FORMS.items():
            src = self.source(f"templates/accounts/{page}.html")
            with self.subTest(page=page):
                self.assertIn("{% csrf_token %}", src)
                self.assertIn('method="post"', src)
                self.assertIn('name="mobile_number"', src)
                self.assertIn('autocomplete="tel"', src)
                self.assertIn('dir="ltr"', src)
                self.assertIn("deployment_brand.display_name", src)
                self.assertIn("document.querySelectorAll('.toggle-password')", src)
                self.assertIn("e.target.value.replace(/[^\\d]/g, '')", src)
                if page != "login":
                    for field in ("password1", "password2", "agree_to_terms"):
                        self.assertIn(f'name="{field}"', src)
                    self.assertIn("{% url 'accounts:terms_of_use' %}", src)
                    self.assertIn("{% url 'accounts:privacy_policy' %}", src)
                    self.assertIn("form.password1.errors", src)
                    self.assertIn("form.password2.errors", src)
                    self.assertIn("data-password-hint", src)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")

    def test_validation_and_password_logic_are_not_rewritten(self):
        src = self.source("apps/accounts/forms.py")
        self.assertIn('if len(mobile_number) != 11 or not mobile_number.startswith("09"):', src)
        self.assertIn("validate_password(", src)
        self.assertIn("if password1 and password2 and password1 != password2:", src)
        self.assertIn("required=True", src)
        for page in ("register", "customer_signup", "stylist_signup"):
            script = self.source(f"templates/accounts/{page}.html")
            self.assertIn("password.addEventListener('input'", script)
            self.assertIn("i18n.language === 'fa'", script)
            self.assertNotIn("innerHTML", script)
