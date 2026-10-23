"""Phase 3.13 — active authentication password client copy and a11y.

Database-free guards for reviewed gettext reuse and unchanged auth contracts.
Actual inline script behavior is tested separately using Node VM.
"""
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation

from loomera.branding.config import get_deployment_brand_config
from loomera.branding.assets import get_deployment_brand_asset_config
from loomera.branding.colors import get_deployment_brand_color_config
from loomera.globalization.interactive_messages import MESSAGE_IDS, interactive_messages

PAGES = ("login", "register", "customer_signup", "stylist_signup")
LOCALES = {
    "en": ("Show password", "Hide password", "Strong password."),
    "ar": ("إظهار كلمة المرور", "إخفاء كلمة المرور", "كلمة المرور قوية."),
    "fa": ("نمایش رمز عبور", "مخفی کردن رمز عبور", "رمز عبور قوی است."),
}


class AuthPasswordClientLocalizationTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @staticmethod
    def context():
        return {
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
            "deployment_brand_colors": get_deployment_brand_color_config(),
        }

    def tearDown(self):
        translation.deactivate_all()

    def test_all_active_auth_forms_have_aria_state_and_targets(self):
        for name in PAGES:
            src = self.source(f"templates/accounts/{name}.html")
            with self.subTest(page=name):
                count = 1 if name == "login" else 2
                self.assertEqual(src.count('aria-pressed="false"'), count)
                self.assertEqual(src.count('aria-controls="id_password'), count)
                self.assertEqual(src.count("this.setAttribute('aria-pressed'"), 1)
                self.assertIn("authPasswordText('password.show'", src)
                self.assertIn("authPasswordText('password.hide'", src)
                self.assertIn("document.querySelectorAll('.toggle-password')", src)
                self.assertIn("icon.classList.toggle('fa-eye-slash')", src)
                self.assertIn('aria-label="{% trans', src)

    def test_existing_form_security_and_phone_rules_unchanged(self):
        for name in PAGES:
            src = self.source(f"templates/accounts/{name}.html")
            with self.subTest(page=name):
                self.assertIn("{% csrf_token %}", src)
                self.assertIn('method="post"', src)
                self.assertIn('name="mobile_number"', src)
                self.assertIn('dir="ltr"', src)
                self.assertIn('autocomplete="tel"', src)
                self.assertIn('type="password"', src)
                self.assertIn("replace(/[^\\d]/g, '')", src)
                self.assertIn("deployment_brand.display_name", src)
                self.assertIn("i18n.language === 'fa'", src)
        for name in PAGES[1:]:
            src = self.source(f"templates/accounts/{name}.html")
            self.assertIn('name="agree_to_terms"', src)
            self.assertIn('name="password1"', src)
            self.assertIn('name="password2"', src)

    def test_signup_modes_reuse_curated_keys_not_untrusted_strings(self):
        for name in PAGES[1:]:
            source = self.source(f"templates/accounts/{name}.html")
            with self.subTest(page=name):
                self.assertIn("'password.strength.guidance'", source)
                self.assertIn("hint.textContent = authPasswordText(", source)
                self.assertIn("password.addEventListener('input'", source)
                self.assertIn("v.length >= 8" if name == "customer_signup" else "score >= 3", source)
        self.assertIn("'password.too_short'", self.source("templates/accounts/customer_signup.html"))
        for name in ("register", "stylist_signup"):
            source = self.source(f"templates/accounts/{name}.html")
            self.assertIn("'password.strength.strong'", source)
            self.assertIn("'password.strength.acceptable'", source)
            self.assertIn("if (/[A-Za-zآ-ی]/.test(", source)
        self.assertEqual(len(MESSAGE_IDS), 41)
        for key in (
            "password.show", "password.hide", "password.strength.guidance",
            "password.strength.strong", "password.strength.acceptable",
            "password.too_short",
        ):
            self.assertIn(key, MESSAGE_IDS)
        self.assertNotIn("signup.", str(MESSAGE_IDS))

    def test_compiled_catalog_supports_all_three_auth_locales(self):
        for language, (show, hide, strong) in LOCALES.items():
            with translation.override(language):
                with self.subTest(language=language):
                    self.assertEqual(translation.gettext("Show password"), show)
                    self.assertEqual(translation.gettext("Hide password"), hide)
                    self.assertEqual(translation.gettext("Strong password."), strong)
                    self.assertNotEqual(translation.gettext("At least 8 characters; numbers, letters and symbols make it stronger."), "")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")

    def test_rendered_forms_keep_pre_script_accessibility_label(self):
        for language in ("fa", "en", "ar"):
            with translation.override(language):
                for name in PAGES:
                    with self.subTest(language=language, page=name):
                        html = render_to_string(f"accounts/{name}.html", self.context())
                        self.assertIn('aria-pressed="false"', html)
                        self.assertIn('aria-controls="id_password', html)
                        self.assertIn('type="password"', html)
                        self.assertIn('name="mobile_number"', html)
                        self.assertIn(translation.gettext("نمایش یا پنهان‌کردن رمز عبور"), html)
