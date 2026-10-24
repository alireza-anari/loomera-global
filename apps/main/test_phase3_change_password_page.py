"""Phase 3 slice 3.11: active password-change template and client copy."""

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation

from apps.accounts.forms import ChangePasswordForm
from apps.accounts.views import _format_remaining_otp_attempts
from loomera.branding.config import get_deployment_brand_config
from loomera.branding.assets import get_deployment_brand_asset_config
from loomera.branding.colors import get_deployment_brand_color_config
from loomera.globalization.interactive_messages import MESSAGE_IDS


EXPECTED = (
    ("fa", "تغییر رمز عبور", "رمز عبور جدید", "ثبت رمز جدید",
     "نمایش رمز عبور جدید", "بازگشت به ورود"),
    ("en", "Change password", "New password", "Save new password",
     "Show new password", "Back to sign in"),
    ("ar", "تغيير كلمة المرور", "كلمة المرور الجديدة", "حفظ كلمة المرور الجديدة",
     "إظهار كلمة المرور الجديدة", "العودة إلى تسجيل الدخول"),
)


class ChangePasswordLocalizedPageTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @staticmethod
    def context(require_current_password=False):
        return {
            "form": ChangePasswordForm(
                require_current_password=require_current_password
            ),
            "requires_current_password": require_current_password,
            "password_return_url": reverse("accounts:login"),
            "user_mobile": "09123456789",
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
            "deployment_brand_colors": get_deployment_brand_color_config(),
        }

    def tearDown(self):
        translation.deactivate_all()

    def test_three_locale_real_template_render_uses_compiled_page_catalogs(self):
        for language, heading, field, submit, toggle, back in EXPECTED:
            with self.subTest(language=language), translation.override(language):
                html = render_to_string(
                    "accounts/change_password.html",
                    self.context(require_current_password=False),
                )
                for expected in (heading, field, submit, toggle, back):
                    self.assertIn(expected, html)
                self.assertIn('id="changePasswordForm"', html)
                self.assertIn('name="password1"', html)
                self.assertIn('name="password2"', html)
                self.assertIn('autocomplete="new-password"', html)
                self.assertIn('name="current_password"', self.source("templates/accounts/change_password.html"))
                self.assertIn(reverse("accounts:login"), html)

    def test_current_password_mode_remains_gated_by_original_view_flag(self):
        src = self.source("templates/accounts/change_password.html")
        self.assertIn("{% if requires_current_password %}", src)
        self.assertIn('id="currentPassword"', src)
        self.assertIn('autocomplete="current-password"', src)
        for language, back in (
            ("fa", "بازگشت به تنظیمات"),
            ("en", "Back to settings"),
            ("ar", "العودة إلى الإعدادات"),
        ):
            with self.subTest(language=language), translation.override(language):
                html = render_to_string(
                    "accounts/change_password.html",
                    self.context(require_current_password=True),
                )
                self.assertIn(back, html)
                self.assertIn('name="current_password"', html)
                self.assertIn('id="currentPassword"', html)
                self.assertIn('name="password1"', html)
                self.assertIn('name="password2"', html)
                self.assertIn(reverse("accounts:remember_password"), html)

    def test_template_preserves_csrf_password_names_and_security_controls(self):
        src = self.source("templates/accounts/change_password.html")
        self.assertIn("{% load static i18n %}", src)
        self.assertIn("{% csrf_token %}", src)
        self.assertIn('method="post"', src)
        self.assertIn('id="changePasswordForm"', src)
        for key in ("current_password", "password1", "password2"):
            self.assertIn('name="' + key + '"', src)
        self.assertEqual(src.count("data-password-toggle"), 4)  # 3 buttons + JS selector
        self.assertEqual(src.count("data-password-strength-bar"), 4)
        self.assertIn('aria-pressed="false"', src)
        self.assertIn("input.focus({ preventScroll: true })", src)
        self.assertIn("form.password1.errors.0", src)
        self.assertIn("form.password2.errors.0", src)
        self.assertIn("form.non_field_errors", src)

    def test_password_strength_scoring_and_validation_conditions_are_unchanged(self):
        src = self.source("templates/accounts/change_password.html")
        for condition in (
            "value.length >= 8",
            "/[A-Za-zآ-ی]/.test(value) && /\\d/.test(value)",
            "value.length >= 12 || /[^A-Za-z0-9آ-ی]/.test(value)",
            "password1 !== password2",
            "password1.length < 8",
            'event.preventDefault()',
        ):
            self.assertIn(condition, src)
        self.assertIn("strengthBars.forEach(function(bar, index)", src)
        self.assertIn('icon.className = shouldShow', src)
        self.assertIn('toggleButton.setAttribute("aria-pressed"', src)
        self.assertIn('window.LoomeraFeedback?.error?.(', src)

    def test_seven_trusted_password_ui_keys_resolve_in_three_catalogs(self):
        password_keys = {
            "password.strength.strong",
            "password.strength.acceptable",
            "password.strength.guidance",
            "password.show",
            "password.hide",
            "password.mismatch",
            "password.too_short",
        }
        self.assertEqual(len(MESSAGE_IDS), 41)
        self.assertEqual(
            {key for key in MESSAGE_IDS if key.startswith("password.")},
            password_keys,
        )
        for language in ("fa", "en", "ar"):
            with self.subTest(language=language), translation.override(language):
                for key in password_keys:
                    actual = translation.gettext(MESSAGE_IDS[key])
                    self.assertTrue(actual, key)
                    if language != "en":
                        self.assertNotEqual(actual, MESSAGE_IDS[key])
                self.assertEqual(
                    translation.gettext(MESSAGE_IDS["password.strength.strong"]),
                    {"fa": "رمز عبور قوی است.", "en": "Strong password.",
                     "ar": "كلمة المرور قوية."}[language],
                )

    def test_client_message_keys_are_used_for_strength_toggle_and_errors(self):
        template = self.source("templates/accounts/change_password.html")
        for key in MESSAGE_IDS:
            if key.startswith("password."):
                self.assertIn('"' + key + '"', template)
        self.assertIn("window.LoomeraI18n?.text?.(key, fallback)", template)
        self.assertIn("strengthHint.textContent =", template)
        self.assertNotIn("strengthHint.innerHTML", template)
        self.assertIn("passwordPageText(", template)
        browser = self.source("static/js/interactive_i18n.js")
        self.assertIn("(feedback|validation|submit|password|booking)", browser)
        self.assertIn("Object.freeze(messages)", browser)
        self.assertIn("approved.has(value.trim())", browser)
        feedback = self.source("static/js/feedback.js")
        self.assertIn("isTrustedMessage?.(text)", feedback)

    def test_persian_page_text_fallback_matches_original_sources(self):
        src = self.source("templates/accounts/change_password.html")
        for literal in (
            "رمز قوی است.",
            "رمز قابل قبول است؛ بهتر است قوی‌تر شود.",
            "حداقل ۸ کاراکتر؛ استفاده از عدد، حروف و نشانه‌ها رمز را قوی‌تر می‌کند.",
            "رمز عبور و تکرار آن مطابقت ندارند",
            "رمز عبور باید حداقل ۸ کاراکتر باشد",
            "مخفی کردن رمز عبور",
            "نمایش رمز عبور",
        ):
            self.assertIn(literal, src)
        with translation.override("fa"):
            html = render_to_string(
                "accounts/change_password.html",
                self.context(require_current_password=True),
            )
            self.assertIn("رمز عبور فعلی", html)
            self.assertIn("تغییر رمز عبور", html)
            self.assertIn("ثبت رمز جدید", html)

    def test_change_password_form_security_policy_is_unchanged(self):
        form_source = self.source("apps/accounts/forms.py")
        view_source = self.source("apps/accounts/views.py")
        self.assertIn("class ChangePasswordForm(forms.Form):", form_source)
        self.assertIn('self.fields["current_password"].required = require_current_password', form_source)
        self.assertIn("password1 and len(password1) < 8", form_source)
        self.assertIn("validate_password(password1)", form_source)
        self.assertIn("if password1 and password2 and password1 != password2", form_source)
        self.assertIn('user.check_password(data["current_password"])', view_source)
        self.assertIn('user.set_password(data["password1"])', view_source)
        self.assertIn('user.save(update_fields=["password", "active_code"])', view_source)
        self.assertIn("logout(request)", view_source)

    def test_otp_arabic_six_form_compiled_catalog_survives_changes(self):
        for lang, count, expected in (
            ("fa", 2, "کد وارد شده اشتباه است. 2 تلاش دیگر باقی مانده است."),
            ("en", 1, "The code is incorrect. 1 attempt remains."),
            ("en", 3, "The code is incorrect. 3 attempts remain."),
            ("ar", 2, "رمز التحقق غير صحيح. تبقت محاولتان."),
            ("ar", 7, "رمز التحقق غير صحيح. تبقت 7 محاولات."),
            ("ar", 11, "رمز التحقق غير صحيح. تبقت 11 محاولة."),
        ):
            with self.subTest(language=lang, count=count), translation.override(lang):
                self.assertEqual(_format_remaining_otp_attempts(count), expected)
        for lang in ("fa", "en", "ar"):
            root = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            self.assertTrue((root / "django.mo").is_file())
            self.assertIn("msgid_plural", (root / "django.po").read_text(encoding="utf-8"))

    def test_no_auth_backend_or_deployment_default_changes(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        self.assertIn("{% url 'accounts:remember_password' %}",
                      self.source("templates/accounts/change_password.html"))
