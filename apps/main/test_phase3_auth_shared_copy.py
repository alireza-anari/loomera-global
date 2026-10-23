"""Phase 3 slice 3.7: reviewed shared auth copy and login feedback."""

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.utils import translation

from loomera.branding.config import get_deployment_brand_config
from loomera.branding.assets import get_deployment_brand_asset_config
from loomera.branding.colors import get_deployment_brand_color_config


TEMPLATES = (
    "accounts/login.html",
    "accounts/register.html",
    "accounts/customer_signup.html",
    "accounts/stylist_signup.html",
)
LOCALES = (("fa", "شماره موبایل", "رمز عبور"),
           ("en", "Mobile number", "Password"),
           ("ar", "رقم الهاتف المحمول", "كلمة المرور"))
LOGIN_FEEDBACK = {
    "لطفاً تمام فیلدها را به درستی پر کنید.": (
        "Please complete all fields correctly.",
        "يرجى إكمال جميع الحقول بشكل صحيح.",
    ),
    "شماره موبایل یا رمز عبور اشتباه است.": (
        "Incorrect mobile number or password.",
        "رقم الهاتف أو كلمة المرور غير صحيحة.",
    ),
    "حساب کاربری شما فعال نمی‌باشد.": (
        "Your account is not active.",
        "حسابك غير نشط.",
    ),
    "ورود با موفقیت انجام شد.": (
        "Signed in successfully.",
        "تم تسجيل الدخول بنجاح.",
    ),
    "برای ورود به پنل پلتفرم، صفحه مدیریت را باز کن یا از ورود امن مدیران استفاده کن.": (
        "To access the platform dashboard, open the administration page or use secure administrator sign-in.",
        "للوصول إلى لوحة تحكم المنصة، افتح صفحة الإدارة أو استخدم تسجيل دخول المدير الآمن.",
    ),
}


class AuthSharedCopyLocalizationTests(SimpleTestCase):
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

    def test_active_auth_templates_have_i18n_tags_and_preserve_form_contracts(self):
        for path in TEMPLATES:
            with self.subTest(template=path):
                src = self.source("templates/" + path)
                self.assertIn("{% load static %}", src)
                self.assertIn("{% load i18n %}", src)
                self.assertIn('{% trans "شماره موبایل" %}', src)
                self.assertIn('{% trans "رمز عبور" %}', src)
                self.assertIn("{% csrf_token %}", src)
                self.assertIn('method="post"', src)
                self.assertIn('name="mobile_number"', src)
                self.assertIn('dir="ltr"', src)
                self.assertIn('type="password"', src)
                self.assertIn('autocomplete="tel"', src)
                self.assertIn("document.querySelectorAll('.toggle-password')", src)

    def test_existing_brand_sensitive_browser_titles_are_unchanged(self):
        source = self.source("templates/accounts/login.html")
        self.assertIn(
            "{% block title %}ورود به {{ deployment_brand.display_name }}{% endblock %}",
            source,
        )
        expected_titles = (
            ("register", "مدیر مجموعه"),
            ("customer_signup", "مشتری"),
            ("stylist_signup", "متخصص"),
        )
        for name, role in expected_titles:
            src = self.source("templates/accounts/" + name + ".html")
            self.assertIn(
                "{% block title %}ثبت‌نام " + role
                + " | {{ deployment_brand.display_name }}{% endblock %}",
                src,
            )
            self.assertIn(
                'aria-label="صفحه اصلی {{ deployment_brand.display_name }}"',
                src,
            )

    def test_compiled_translations_render_shared_field_labels_in_three_locales(self):
        for lang, phone, password in LOCALES:
            with translation.override(lang):
                for path in TEMPLATES:
                    with self.subTest(lang=lang, template=path):
                        html = render_to_string(path, self.context())
                        self.assertIn(phone + "</span>", html)
                        self.assertIn(password + "</span>", html)
                        self.assertIn('name="mobile_number"', html)
                        self.assertIn('dir="ltr"', html)
                        self.assertIn("Loomera", html)
                        self.assertIn('class="toggle-password', html)

    def test_shared_labels_and_accessibility_translate_without_changing_identifiers(self):
        cases = (
            ("نام", "First name", "الاسم الأول"),
            ("نام خانوادگی", "Last name", "اسم العائلة"),
            ("نمایش یا پنهان‌کردن رمز عبور", "Show or hide password",
             "إظهار كلمة المرور أو إخفاؤها"),
            ("دریافت کد تأیید", "Get verification code", "الحصول على رمز التحقق"),
            ("تخصص اصلی", "Main specialty", "التخصص الرئيسي"),
        )
        for msgid, english, arabic in cases:
            for lang, expected in (("fa", msgid), ("en", english), ("ar", arabic)):
                with self.subTest(msgid=msgid, lang=lang):
                    with translation.override(lang):
                        self.assertEqual(translation.gettext(msgid), expected)
        for path in TEMPLATES:
            src = self.source("templates/" + path)
            self.assertIn("{% trans 'نمایش یا پنهان‌کردن رمز عبور' %}", src)

    def test_five_login_feedback_messages_are_lazy_resolved_at_request_time(self):
        src = self.source("apps/accounts/views.py")
        self.assertIn("from django.utils.translation import gettext", src)
        for msgid, (en, ar) in LOGIN_FEEDBACK.items():
            with self.subTest(message=msgid):
                self.assertIn('gettext("' + msgid + '")', src)
                for lang, expected in (("fa", msgid), ("en", en), ("ar", ar)):
                    with translation.override(lang):
                        self.assertEqual(translation.gettext(msgid), expected)

    def test_login_security_flow_and_return_destination_unmodified(self):
        src = self.source("apps/accounts/views.py")
        begin = src.index("class LoginUserView(View):")
        end = src.index("class LogoutUserView(View):", begin)
        block = src[begin:end]
        self.assertIn("authenticate(", block)
        self.assertIn("if user is None:", block)
        self.assertIn("if not user.is_active:", block)
        self.assertIn("if user.is_admin", block)
        self.assertIn("login(request, user)", block)
        self.assertIn("_redirect_after_auth(request, user, next_url=next_url)", block)
        self.assertIn("_clean_next_url(request)", block)

    def test_default_fa_catalog_is_unchanged_for_explicit_auth_copy(self):
        with translation.override("fa"):
            for msgid in (
                "شماره موبایل", "رمز عبور", "نام",
                "لطفاً تمام فیلدها را به درستی پر کنید.",
            ):
                self.assertEqual(translation.gettext(msgid), msgid)
        for lang in ("fa", "en", "ar"):
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            self.assertTrue((folder / "django.po").is_file())
            self.assertTrue((folder / "django.mo").is_file())
            source = (folder / "django.po").read_text(encoding="utf-8")
            self.assertIn('msgid "شماره موبایل"', source)
            self.assertIn('msgid "شماره موبایل یا رمز عبور اشتباه است."', source)

    def test_terms_links_and_legacy_signup_strength_hooks_not_rewritten(self):
        for path in TEMPLATES[1:]:
            src = self.source("templates/" + path)
            self.assertIn("{% url 'accounts:terms_of_use' %}", src)
            self.assertIn("{% url 'accounts:privacy_policy' %}", src)
            self.assertIn('name="agree_to_terms"', src)
            self.assertIn("form.password1.errors", src)
            self.assertIn("form.password2.errors", src)
            self.assertIn("data-password-hint", src)
            self.assertIn("e.target.value.replace(/[^\\d]/g, '')", src)

    def test_no_business_or_calendar_runtime_settings_changed(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
