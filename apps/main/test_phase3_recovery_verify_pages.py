"""Phase 3 slice 3.10: active OTP verification and recovery page translations.

Tests intentionally exercise compiled gettext and real template/form rendering,
without a database, production HTTP requests or SMS delivery.
"""

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation

from apps.accounts.forms import RememberPasswordForm, VerifyRegisterForm
from apps.accounts.views import _build_verification_context, _format_remaining_otp_attempts
from loomera.branding.config import get_deployment_brand_config
from loomera.branding.assets import get_deployment_brand_asset_config
from loomera.branding.colors import get_deployment_brand_color_config


class VerificationAndRecoveryPageLocaleTests(SimpleTestCase):
    @staticmethod
    def source(relative):
        return (Path(settings.BASE_DIR) / relative).read_text(encoding="utf-8")

    @staticmethod
    def brand():
        return {
            "deployment_brand": get_deployment_brand_config(),
            "deployment_brand_assets": get_deployment_brand_asset_config(),
            "deployment_brand_colors": get_deployment_brand_color_config(),
        }

    def tearDown(self):
        translation.deactivate_all()

    def test_active_verify_page_has_translations_and_preserves_otp_fields(self):
        source = self.source("templates/accounts/verify.html")
        self.assertIn("{% load static i18n %}", source)
        self.assertIn("{% csrf_token %}", source)
        self.assertIn('name="active_code"', source)
        self.assertIn('id="id_active_code"', source)
        self.assertIn('autocomplete="one-time-code"', source)
        self.assertIn('inputmode="numeric"', source)
        self.assertIn('maxlength="8"', source)
        self.assertIn('dir="ltr"', source)
        self.assertIn("event.target.value.replace(/[^\\d]/g, '').slice(0, 8)", source)
        self.assertIn('data-auth-flow="verify"', source)
        self.assertIn("form.active_code.errors.0", source)
        self.assertEqual(source.count("localized_verify_back_href|default"), 2)
        self.assertIn("{% url verify_back_url as localized_verify_back_href %}", source)

    def test_recovery_page_preserves_brand_csrf_and_submission_contract(self):
        source = self.source("templates/accounts/remember_password.html")
        self.assertIn("{% load i18n %}", source)
        self.assertIn('{% include "partials/brand/logo.html" with variant="full" size="lg" %}', source)
        self.assertIn('{% trans "امنیت حساب" %} {{ deployment_brand.display_name }}', source)
        self.assertIn("{% csrf_token %}", source)
        self.assertIn('method="post"', source)
        self.assertIn("form.non_field_errors.0", source)
        self.assertIn("form.visible_fields", source)
        self.assertIn('data-auth-form', source)
        self.assertIn('el.setAttribute("dir", "ltr")', source)
        self.assertIn("{% url 'accounts:login' %}", source)

    def test_actual_recovery_html_render_uses_each_compiled_locale(self):
        cases = (
            ("fa", "فراموشی رمز عبور", "ارسال کد", "شماره موبایل", "بازگشت به صفحه ورود"),
            ("en", "Forgot password", "Send code", "Mobile number", "Back to sign in"),
            ("ar", "نسيت كلمة المرور", "إرسال الرمز", "رقم الهاتف المحمول", "العودة إلى تسجيل الدخول"),
        )
        for lang, heading, button, phone, back in cases:
            with self.subTest(lang=lang), translation.override(lang):
                html = render_to_string(
                    "accounts/remember_password.html",
                    {"form": RememberPasswordForm(), **self.brand()},
                )
                self.assertIn(heading, html)
                self.assertIn(button, html)
                self.assertIn(phone, html)
                self.assertIn(back, html)
                self.assertIn('name="mobile_number"', html)
                self.assertIn(reverse("accounts:login"), html)
                self.assertIn("Loomera", html)

    def test_actual_verification_html_renders_three_languages_and_valid_back_links(self):
        cases = (
            ("fa", "کد تأیید را وارد کن", "کد تأیید", "ادامه"),
            ("en", "Enter the verification code", "Verification code", "Continue"),
            ("ar", "أدخل رمز التحقق", "رمز التحقق", "متابعة"),
        )
        for lang, heading, field, button in cases:
            with self.subTest(lang=lang), translation.override(lang):
                context = _build_verification_context(
                    VerifyRegisterForm(), {
                        "remember_password": True,
                        "mobile_number": "09123456789",
                        "otp_max_attempts": 3,
                        "otp_attempts": 1,
                    }
                )
                html = render_to_string("accounts/verify.html", {**context, **self.brand()})
                self.assertIn(heading, html)
                self.assertIn(field, html)
                self.assertIn(button, html)
                self.assertIn('name="active_code"', html)
                self.assertIn('dir="ltr"', html)
                self.assertIn(reverse("accounts:remember_password"), html)
                self.assertNotIn('href=""', html)
                self.assertIn("••••", html)

    def test_signup_verification_context_localizes_role_and_retains_routes(self):
        cases = (
            ("salon", "accounts:register", "Salon and business", "الصالون والمنشأة"),
            ("stylist", "accounts:stylist_signup", "Professional", "متخصص"),
            ("customer", "accounts:customer_signup", "Customer", "عميل"),
        )
        for kind, route, en_role, ar_role in cases:
            for lang, role in (("en", en_role), ("ar", ar_role)):
                with self.subTest(kind=kind, lang=lang), translation.override(lang):
                    context = _build_verification_context(
                        VerifyRegisterForm(), {
                            "signup_kind": kind,
                            "mobile_number": "09123456789",
                            "otp_max_attempts": 3,
                            "otp_attempts": 0,
                        }
                    )
                    self.assertEqual(context["verification_mode"], "signup")
                    self.assertEqual(context["verify_back_url"], route)
                    self.assertIn(role, context["verify_heading"])
                    self.assertEqual(context["remaining_attempts"], 3)
                    self.assertIn("%(role)s", self.source("apps/accounts/views.py"))
                    html = render_to_string("accounts/verify.html", {**context, **self.brand()})
                    self.assertIn(reverse(route), html)

    def test_verification_context_keeps_exact_persian_legacy_strings(self):
        with translation.override("fa"):
            reset = _build_verification_context(VerifyRegisterForm(), {"remember_password": True})
            self.assertEqual(reset["verify_page_title"], "تایید کد")
            self.assertEqual(reset["verify_heading"], "کد تایید را وارد کنید")
            self.assertEqual(reset["verify_submit_label"], "ادامه")
            signup = _build_verification_context(
                VerifyRegisterForm(), {"signup_kind": "stylist"}
            )
            self.assertEqual(signup["verify_page_title"], "تایید شماره موبایل")
            self.assertEqual(signup["verify_heading"], "کد فعال‌سازی متخصص را وارد کنید")
            self.assertEqual(signup["verify_submit_label"], "تایید و ورود")

    def test_form_labels_and_placeholders_resolve_at_render_time_not_import_time(self):
        expected = (
            ("fa", "کد فعالسازی ", "کد دریافتی را وارد کنید ", "موبایل را وارد کنید "),
            ("en", "Activation code ", "Enter the received code ", "Enter mobile number "),
            ("ar", "رمز التفعيل ", "أدخل الرمز المستلم ", "أدخل رقم الهاتف "),
        )
        for lang, code_label, code_placeholder, mobile_placeholder in expected:
            with self.subTest(lang=lang), translation.override(lang):
                verification = VerifyRegisterForm()
                recovery = RememberPasswordForm()
                self.assertEqual(str(verification.fields["active_code"].label), code_label)
                self.assertEqual(
                    str(verification.fields["active_code"].widget.attrs["placeholder"]),
                    code_placeholder,
                )
                self.assertEqual(
                    str(recovery.fields["mobile_number"].widget.attrs["placeholder"]),
                    mobile_placeholder,
                )
                self.assertEqual(
                    str(recovery.fields["mobile_number"].label),
                    {"fa": "شماره موبایل", "en": "Mobile number",
                     "ar": "رقم الهاتف المحمول"}[lang],
                )

    def test_plural_otp_catalog_survives_new_compiled_catalogs(self):
        for lang, number, expected in (
            ("fa", 2, "کد وارد شده اشتباه است. 2 تلاش دیگر باقی مانده است."),
            ("en", 1, "The code is incorrect. 1 attempt remains."),
            ("en", 2, "The code is incorrect. 2 attempts remain."),
            ("ar", 2, "رمز التحقق غير صحيح. تبقت محاولتان."),
            ("ar", 7, "رمز التحقق غير صحيح. تبقت 7 محاولات."),
            ("ar", 11, "رمز التحقق غير صحيح. تبقت 11 محاولة."),
        ):
            with self.subTest(lang=lang, number=number), translation.override(lang):
                self.assertEqual(_format_remaining_otp_attempts(number), expected)

    def test_catalog_po_mo_sources_and_runtime_views_are_present(self):
        source = self.source("apps/accounts/views.py")
        self.assertIn('gettext("تایید کد")', source)
        self.assertIn('gettext("تایید شماره موبایل")', source)
        self.assertIn('gettext("کد فعال‌سازی %(role)s را وارد کنید")', source)
        self.assertIn('{"role": meta["label"]}', source)
        self.assertIn('gettext("تایید و ورود")', source)
        self.assertIn("remaining_attempts = max(", source)
        self.assertIn("request.session.pop(USER_SESSION_KEY, None)", source)
        for lang in ("fa", "en", "ar"):
            root = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            po = (root / "django.po").read_text(encoding="utf-8")
            self.assertTrue((root / "django.mo").is_file())
            self.assertIn('msgid "کد فعال‌سازی %(role)s را وارد کنید"', po)
            self.assertIn('msgid "فراموشی رمز عبور"', po)
            self.assertIn('msgid_plural "کد وارد شده اشتباه است.', po)

    def test_legacy_recovery_aliases_are_unchanged_and_no_domain_defaults_shift(self):
        for pair in (
            ("templates/accounts/verify_code.html", "templates/accounts/remember_password_verify.html"),
            ("templates/accounts/new_password.html", "templates/accounts/reset_password.html"),
        ):
            self.assertEqual(self.source(pair[0]), self.source(pair[1]))
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
