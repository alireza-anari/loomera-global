"""Phase 3.14: security-minded recovery and OTP presentation tests.

Database-free Django rendering tests; not browser visual or SMS acceptance.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation

from apps.accounts.forms import RememberPasswordForm, VerifyRegisterForm
from loomera.branding.config import get_deployment_brand_config
from loomera.branding.assets import get_deployment_brand_asset_config
from loomera.branding.colors import get_deployment_brand_color_config


class RecoveryOtpPresentationTests(SimpleTestCase):
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

    def tearDown(self):
        translation.deactivate_all()

    def test_recovery_brand_security_copy_is_localized_but_brand_is_dynamic(self):
        page = self.source("templates/accounts/remember_password.html")
        self.assertIn('{% trans "امنیت حساب" %} {{ deployment_brand.display_name }}', page)
        self.assertNotIn("امنیت حساب {{ deployment_brand.display_name }}", page)
        for language, expected in (
            ("fa", "امنیت حساب"), ("en", "Account security"), ("ar", "أمان الحساب"),
        ):
            with self.subTest(language=language), translation.override(language):
                brand = get_deployment_brand_config().display_name
                html = render_to_string(
                    "accounts/remember_password.html",
                    self.context(RememberPasswordForm()),
                )
                self.assertIn(f"{expected} {brand}", html)
                self.assertIn('name="mobile_number"', html)
                self.assertIn('method="post"', html)

    def test_recovery_help_text_is_escaped_as_untrusted_text(self):
        form = RememberPasswordForm()
        form.fields["mobile_number"].help_text = '<img src=x onerror=alert(1)>'
        html = render_to_string("accounts/remember_password.html", self.context(form))
        source = self.source("templates/accounts/remember_password.html")
        self.assertIn("{{ field.help_text }}", source)
        self.assertNotIn("field.help_text|safe", source)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)

    def test_recovery_invalid_submission_remains_alert_and_csrf_protected(self):
        form = RememberPasswordForm(data={})
        self.assertFalse(form.is_valid())
        html = render_to_string("accounts/remember_password.html", self.context(form))
        self.assertIn('name="mobile_number"', html)
        self.assertIn('method="post"', html)
        self.assertIn('data-auth-form', html)
        self.assertIn('role="alert"', self.source("templates/accounts/remember_password.html"))
        self.assertIn("{% csrf_token %}", self.source("templates/accounts/remember_password.html"))
        self.assertIn('el.name === "mobile_number"', html)

    def test_verify_code_field_describes_hint_and_error_with_correct_aria_state(self):
        invalid = VerifyRegisterForm(data={})
        self.assertFalse(invalid.is_valid())
        html = render_to_string("accounts/verify.html", self.context(invalid))
        self.assertIn('aria-invalid="true"', html)
        self.assertIn('aria-describedby="verify-otp-help verify-otp-error"', html)
        self.assertIn('id="verify-otp-help"', html)
        self.assertIn('id="verify-otp-error" role="alert"', html)
        self.assertIn('name="active_code"', html)

    def test_verify_pristine_field_does_not_reference_missing_error(self):
        html = render_to_string(
            "accounts/verify.html", self.context(VerifyRegisterForm())
        )
        self.assertIn('aria-invalid="false"', html)
        self.assertIn('aria-describedby="verify-otp-help"', html)
        self.assertNotIn('id="verify-otp-error"', html)
        self.assertIn('autocomplete="one-time-code"', html)

    def test_verify_ltr_arrow_css_is_bounded_to_active_page(self):
        page = self.source("templates/accounts/verify.html")
        css = self.source("static/css/components/bidirectional_verify_recovery.css")
        self.assertTrue(finders.find("css/components/bidirectional_verify_recovery.css"))
        self.assertIn("{% block head %}", page)
        self.assertEqual(page.count("bidirectional_verify_recovery.css"), 1)
        self.assertEqual(page.count("lm-verify-back-icon"), 1)
        self.assertEqual(page.count("lm-verify-next-icon"), 1)
        self.assertIn('html[dir="ltr"] [data-auth-flow="verify"]', css)
        self.assertIn('transform: scaleX(-1)', css)
        self.assertNotIn('html[dir="rtl"]', css)
        self.assertNotIn("!important", css)
        self.assertEqual(css.count("{"), css.count("}"))

    def test_otp_security_input_contract_and_navigation_are_untouched(self):
        page = self.source("templates/accounts/verify.html")
        for fragment in (
            "{% csrf_token %}", 'method="post"', 'name="active_code"',
            'inputmode="numeric"', 'autocomplete="one-time-code"',
            'maxlength="8"', 'dir="ltr"', 'type="text"',
            "event.target.value.replace(/[^\\d]/g, '').slice(0, 8)",
            "codeInput.focus()", "{% url verify_back_url as localized_verify_back_href %}",
        ):
            self.assertIn(fragment, page)
        self.assertEqual(page.count("localized_verify_back_href|default"), 2)
        for key, value in (
            ("LANGUAGE_CODE", "fa"),
            ("LOOMERA_DEFAULT_CALENDAR", "jalali"),
            ("TIME_ZONE", "Asia/Tehran"),
        ):
            self.assertEqual(getattr(settings, key), value)

    def test_recovery_mobile_direction_only_applies_to_trusted_field(self):
        page = self.source("templates/accounts/remember_password.html")
        self.assertIn('el.name === "mobile_number"', page)
        self.assertIn('el.setAttribute("dir", "ltr")', page)
        self.assertIn("type === \"hidden\"", page)
        self.assertIn("type === \"checkbox\"", page)
        self.assertIn("type === \"radio\"", page)
        self.assertIn('querySelectorAll("input, select, textarea")', page)
