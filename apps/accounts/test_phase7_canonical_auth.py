"""Exit B: canonical password login, legacy OTP compatibility and foreign denial."""
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import phonenumbers
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.forms import CustomerSignupForm, LoginUserForm, RememberPasswordForm
from apps.accounts.models import CustomUser, Customer
from apps.accounts.services import sms
from apps.accounts.services.phone_auth import password_identity, legacy_sms_mobile
from apps.accounts.views import _send_verification_code
from apps.api.v1.auth_serializers import validate_mobile_for_auth
from loomera.globalization.phone_identity import PhoneIdentityInputError


IR = "09123456789"
ALIAS = "+989123456789"
FOREIGN = phonenumbers.format_number(
    phonenumbers.example_number_for_type("GB", phonenumbers.PhoneNumberType.MOBILE),
    phonenumbers.PhoneNumberFormat.E164,
)
PASSWORD = "Fixture-Only!9-zeta-761"


@override_settings(LOOMERA_CANONICAL_PASSWORD_LOGIN=True)
class CanonicalPhoneAuthTests(TestCase):
    def account(self, value, active=True, password=PASSWORD):
        user = CustomUser.objects.create_user(mobile_number=value, password=password)
        user.is_active = active
        user.save(update_fields=["is_active"])
        return user

    def test_legacy_aliases_authenticate_same_identity(self):
        user = self.account(IR)
        for value in (IR, ALIAS, "00989123456789", "۰۹۱۲۳۴۵۶۷۸۹"):
            with self.subTest(value=value):
                self.assertEqual(authenticate(username=value, password=PASSWORD).pk, user.pk)
                self.assertEqual(validate_mobile_for_auth(value), (True, IR, ""))
        self.assertEqual(CustomUser.objects.count(), 1)

    def test_foreign_password_requires_valid_number_and_correct_password(self):
        user = self.account(FOREIGN)
        self.assertEqual(password_identity(FOREIGN), FOREIGN)
        self.assertEqual(authenticate(username=FOREIGN, password=PASSWORD).pk, user.pk)
        self.assertIsNone(authenticate(username=FOREIGN, password="wrong"))
        self.assertIsNone(authenticate(username=FOREIGN[1:], password=PASSWORD))
        self.assertFalse(validate_mobile_for_auth(FOREIGN)[0])
        for value in ("+0000000000", "+999123456789", "+80012345678", "+442079460000",
                      FOREIGN + " ext 1"):
            with self.subTest(value=value), self.assertRaises(PhoneIdentityInputError):
                password_identity(value)

    def test_no_inactive_or_deleted_identity_resurrection(self):
        user = self.account(FOREIGN, active=False)
        self.assertIsNone(authenticate(username=FOREIGN, password=PASSWORD))
        user.is_active = True
        user.save(update_fields=["is_active"])
        self.assertIsNotNone(authenticate(username=FOREIGN, password=PASSWORD))
        CustomUser.objects.filter(pk=user.pk).update(mobile_number="98000000001", is_active=False)
        self.assertIsNone(authenticate(username=FOREIGN, password=PASSWORD))
        self.assertIsNone(authenticate(username="98000000001", password=PASSWORD))

    @override_settings(LOOMERA_CANONICAL_PASSWORD_LOGIN=False)
    def test_default_off_preserves_legacy_and_denies_foreign(self):
        local = self.account(IR)
        self.account(FOREIGN)
        self.assertEqual(authenticate(username=IR, password=PASSWORD).pk, local.pk)
        self.assertIsNone(authenticate(username=FOREIGN, password=PASSWORD))
        self.assertFalse(LoginUserForm().canonical_phone_enabled)

    def test_web_login_and_api_session_for_foreign_customer(self):
        user = self.account(FOREIGN)
        Customer.objects.create(user=user, notify_appointment_sms=False)
        url = reverse("accounts:login")
        page = self.client.get(url, secure=True)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'inputmode="tel"')
        response = self.client.post(url, {"mobile_number": FOREIGN, "password": PASSWORD}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        response = self.client.get("/api/v1/auth/me/", secure=True)
        self.assertEqual(response.status_code, 200)

    def test_legacy_sms_signup_alias_and_foreign_rejection(self):
        self.assertEqual(legacy_sms_mobile(ALIAS), IR)
        with self.assertRaises(PhoneIdentityInputError):
            legacy_sms_mobile(FOREIGN)
        form = CustomerSignupForm()
        form.cleaned_data = {"mobile_number": ALIAS}
        self.assertEqual(form.clean_mobile_number(), IR)
        form.cleaned_data = {"mobile_number": FOREIGN}
        with self.assertRaises(ValidationError):
            form.clean_mobile_number()

    def test_recovery_aliases_and_foreign_rejected_before_lookup(self):
        form = RememberPasswordForm({"mobile_number": ALIAS})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["mobile_number"], IR)
        self.assertFalse(RememberPasswordForm({"mobile_number": FOREIGN}).is_valid())
        with patch("apps.accounts.views.CustomUser.objects.get") as lookup:
            response = self.client.post(
                reverse("accounts:remember_password"), {"mobile_number": FOREIGN}, secure=True
            )
        self.assertEqual(response.status_code, 200)
        lookup.assert_not_called()

    def test_unsupported_destination_never_simulates_otp_or_consumes_cooldown(self):
        for enabled in (True, False):
            with self.settings(LOOMERA_CANONICAL_PASSWORD_LOGIN=enabled,
                               SMS_OTP_ENABLED=False):
                result = sms.send_otp_sms(FOREIGN, "123456", purpose="signup")
                self.assertFalse(result.success)
                self.assertFalse(result.simulated)
                self.assertEqual(result.error_code, "unsupported_destination")
                with (
                    patch("apps.accounts.views.messages.error"),
                    patch("apps.accounts.views._otp_cooldown_remaining") as cooldown,
                    patch("apps.accounts.views.utils.send_otp_sms") as send,
                ):
                    self.assertIsNone(_send_verification_code(
                        SimpleNamespace(), user=SimpleNamespace(mobile_number=FOREIGN),
                        purpose="password_reset",
                    ))
                cooldown.assert_not_called()
                send.assert_not_called()

    def provision(self, **kwargs):
        output = StringIO()
        with (
            patch("apps.main.management.commands.provision_verified_foreign_customer.sys.stdin.isatty", return_value=True),
            patch("apps.main.management.commands.provision_verified_foreign_customer.sys.stderr.isatty", return_value=True),
            patch("apps.main.management.commands.provision_verified_foreign_customer.getpass.getpass",
                  side_effect=[FOREIGN, PASSWORD, PASSWORD]) as prompt,
        ):
            call_command("provision_verified_foreign_customer", stdout=output, **kwargs)
        self.assertEqual(prompt.call_count, 3)
        self.assertNotIn(FOREIGN, output.getvalue())
        self.assertNotIn(PASSWORD, output.getvalue())

    def test_provisioning_requires_explicit_ownership_and_recovery_approval(self):
        with patch("apps.main.management.commands.provision_verified_foreign_customer.getpass.getpass") as prompt:
            with self.assertRaises(CommandError):
                call_command("provision_verified_foreign_customer")
        prompt.assert_not_called()
        self.assertEqual(CustomUser.objects.count(), 0)

    def test_verified_provision_creates_only_customer_and_conflict_never_rekeys(self):
        options = {"confirm_verified_ownership": True, "confirm_non_sms_recovery": True}
        self.provision(**options)
        user = CustomUser.objects.get(mobile_number=FOREIGN)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_admin)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.customer_profile.notify_appointment_sms)
        self.assertFalse(user.customer_profile.notify_marketing_sms)
        with self.assertRaises(CommandError):
            self.provision(**options)
        self.assertEqual(CustomUser.objects.count(), 1)
        self.assertEqual(authenticate(username=FOREIGN, password=PASSWORD).pk, user.pk)
