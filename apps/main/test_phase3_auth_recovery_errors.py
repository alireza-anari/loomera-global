"""Phase 3 slice 3.8: signup, OTP and recovery errors without policy changes."""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import translation

from apps.accounts.forms import (
    ChangePasswordForm,
    CustomerSignupForm,
    LoginUserForm,
    RememberPasswordForm,
    StylistSignupForm,
    VerifyRegisterForm,
)


class AuthenticationRecoveryValidationLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def tearDown(self):
        translation.deactivate_all()

    def test_required_field_errors_are_lazy_localized_at_validation_time(self):
        expectations = {
            "fa": "این فیلد نمی‌تواند خالی باشد",
            "en": "This field cannot be empty",
            "ar": "لا يمكن ترك هذا الحقل فارغًا",
        }
        for lang, expected in expectations.items():
            with translation.override(lang):
                with self.subTest(language=lang):
                    for form_class, field in (
                        (VerifyRegisterForm, "active_code"),
                        (RememberPasswordForm, "mobile_number"),
                    ):
                        form = form_class(data={})
                        self.assertFalse(form.is_valid())
                        self.assertEqual(form.errors[field][0].strip(), expected)
                        if form_class is RememberPasswordForm:
                            # Legacy trailing space remains part of the source msgid.
                            self.assertTrue(form.errors[field][0].endswith(" "))
                    # Historical trailing space on login's required message
                    # is intentionally preserved in every locale.
                    login = LoginUserForm(data={})
                    self.assertFalse(login.is_valid())
                    self.assertEqual(login.errors["mobile_number"][0].strip(), expected)

    def test_signup_mobile_policy_is_unchanged_and_errors_are_localized(self):
        expected = {
            "fa": "شماره موبایل باید ۱۱ رقم باشد و با 09 شروع شود",
            "en": "The mobile number must have 11 digits and start with 09.",
            "ar": "يجب أن يتكون رقم الهاتف من 11 رقمًا وأن يبدأ بـ 09.",
        }
        for lang, message in expected.items():
            with translation.override(lang):
                form = CustomerSignupForm()
                form.cleaned_data = {"mobile_number": "123456"}
                with self.assertRaises(ValidationError) as caught:
                    form.clean_mobile_number()
                self.assertEqual(caught.exception.messages[0], message)
        forms_src = self.source("apps/accounts/forms.py")
        self.assertIn("len(mobile_number) != 11", forms_src)
        self.assertIn('mobile_number.startswith("09")', forms_src)
        self.assertIn("queryset.first()", forms_src)
        self.assertIn("has_conflicting_role", forms_src)

    def test_signup_password_match_and_minimum_remain_exactly_as_before(self):
        expected_mismatch = {
            "fa": "رمز عبور و تأیید آن مطابقت ندارند",
            "en": "The password and confirmation do not match",
            "ar": "كلمة المرور وتأكيدها غير متطابقين",
        }
        expected_short = {
            "fa": "رمز عبور باید حداقل ۸ کاراکتر باشد",
            "en": "The password must be at least 8 characters long",
            "ar": "يجب أن تتكون كلمة المرور من 8 أحرف على الأقل",
        }
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                form = CustomerSignupForm()
                form.cleaned_data = {
                    "password1": "some-valid-long-password",
                    "password2": "does-not-match",
                }
                with self.assertRaises(ValidationError) as caught:
                    form.clean_password2()
                self.assertEqual(caught.exception.messages[0], expected_mismatch[lang])
                form.cleaned_data = {"password1": "short", "password2": "short"}
                with self.assertRaises(ValidationError) as caught:
                    form.clean_password2()
                self.assertEqual(caught.exception.messages[0], expected_short[lang])
        self.assertIn(
            "validate_password(",
            self.source("apps/accounts/forms.py"),
        )

    def test_change_password_branch_preserves_current_password_requirement(self):
        expectations = (
            ("fa", "رمز عبور و تکرار آن مغایرت دارند"),
            ("en", "The password entries do not match"),
            ("ar", "إدخالا كلمة المرور غير متطابقين"),
        )
        for lang, error in expectations:
            with translation.override(lang):
                form = ChangePasswordForm(require_current_password=True)
                self.assertTrue(form.fields["current_password"].required)
                form.cleaned_data = {"password1": "long-password-123", "password2": "different-password"}
                with self.assertRaises(ValidationError) as caught:
                    form.clean_password2()
                self.assertEqual(caught.exception.messages[0], error)
                recovery = ChangePasswordForm(require_current_password=False)
                self.assertFalse(recovery.fields["current_password"].required)
                self.assertEqual(recovery.fields["current_password"].widget.__class__.__name__, "HiddenInput")

    def test_stylist_expert_validation_keeps_min_length_and_localizes_error(self):
        for lang, expected in (
            ("fa", "تخصص اصلی باید حداقل ۲ کاراکتر باشد."),
            ("en", "The main specialty must be at least 2 characters long."),
            ("ar", "يجب أن يتكون التخصص الرئيسي من حرفين على الأقل."),
        ):
            with translation.override(lang):
                form = StylistSignupForm()
                form.cleaned_data = {"expert": "x"}
                with self.assertRaises(ValidationError) as caught:
                    form.clean_expert()
                self.assertEqual(caught.exception.messages[0], expected)
        self.assertIn("max_length=100", self.source("apps/accounts/forms.py"))

    def test_otp_and_recovery_feedback_uses_request_time_gettext(self):
        source = self.source("apps/accounts/views.py")
        for message in (
            "جلسه بازیابی یا ثبت‌نام منقضی شده است.",
            "کد تایید منقضی شده است. لطفاً دوباره درخواست کد بدهید.",
            "اطلاعات وارد شده اشتباه است.",
            "تعداد تلاش‌های مجاز تمام شده است. لطفاً دوباره درخواست کد بدهید.",
            "رمز عبور فعلی صحیح نیست.",
            "رمز عبور با موفقیت تغییر کرد.",
            "شماره موبایل را درست وارد کنید.",
            "شماره وارد شده در سیستم پیدا نشد.",
        ):
            self.assertIn('gettext("' + message + '")', source)
            for lang in ("fa", "en", "ar"):
                with translation.override(lang):
                    translated = translation.gettext(message)
                    self.assertTrue(translated)
                    if lang == "fa":
                        self.assertEqual(translated, message)
                    else:
                        self.assertNotEqual(translated, message)

    def test_dynamic_attempt_counter_and_otp_session_security_are_unchanged(self):
        src = self.source("apps/accounts/views.py")
        start = src.index("class VerifyRegisterView(View):")
        end = src.index("class DismissMessagingWelcomePromptView(", start)
        body = src[start:end]
        self.assertIn("remaining_attempts = max(", body)
        self.assertIn('f"کد وارد شده اشتباه است. {remaining_attempts} تلاش دیگر باقی مانده است."', body)
        self.assertIn('user_session["otp_attempts"]', body)
        self.assertIn("request.session.pop(USER_SESSION_KEY, None)", body)
        self.assertIn('user_session["otp_verified"] = True', body)
        self.assertIn("_otp_max_attempts()", body)
        self.assertIn("_password_reset_session_ttl_seconds()", body)
        self.assertIn("utils.create_state_token()", body)

    def test_recovery_post_and_password_reset_semantics_are_unchanged(self):
        src = self.source("apps/accounts/views.py")
        self.assertIn("class RememberPasswordView(View):", src)
        self.assertIn("class ChangePasswordView(View):", src)
        self.assertIn("form = RememberPasswordForm(request.POST)", src)
        self.assertIn("form = ChangePasswordForm(", src)
        self.assertIn("user.check_password(data[\"current_password\"])", src)
        self.assertIn('user.set_password(data["password1"])', src)
        self.assertIn('user.save(update_fields=["password", "active_code"])', src)
        self.assertIn("logout(request)", src)
        self.assertIn("purpose=OTP_PURPOSE_PASSWORD_RESET", src)

    def test_catalogs_keep_existing_auth_and_interactive_strings(self):
        for lang in ("fa", "en", "ar"):
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            src = (folder / "django.po").read_text(encoding="utf-8")
            self.assertTrue((folder / "django.mo").is_file())
            for msg in (
                "شماره موبایل", "رمز عبور", "Saving…",
                "شماره موبایل باید ۱۱ رقم باشد و با 09 شروع شود",
                "جلسه بازیابی یا ثبت‌نام منقضی شده است.",
            ):
                self.assertIn('msgid "' + msg + '"', src)

    def test_no_default_locale_money_calendar_or_sms_configuration_changes(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
        source = self.source("apps/accounts/forms.py")
        self.assertIn("normalize_digits(", source)
        self.assertIn("PERSIAN_DIGITS_MAP", source)
        self.assertIn("ARABIC_DIGITS_MAP", source)
