"""Explicit operator-only onboarding; never infer phone ownership from syntax."""
import getpass
import sys
import warnings

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.accounts.models import CustomUser, Customer
from apps.accounts.services.phone_auth import canonical_password_enabled, password_identity
from loomera.globalization.phone_identity import PhoneIdentityInputError


class Command(BaseCommand):
    help = "Provision one ownership-verified foreign customer with a password (no SMS)."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-verified-ownership", action="store_true")
        parser.add_argument("--confirm-non-sms-recovery", action="store_true")

    def handle(self, *args, **options):
        if not canonical_password_enabled():
            raise CommandError("Canonical password login is disabled.")
        if not (
            options["confirm_verified_ownership"]
            and options["confirm_non_sms_recovery"]
        ):
            raise CommandError("Verified ownership and non-SMS recovery approval required.")
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise CommandError("An interactive private terminal is required.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                raw = getpass.getpass("Verified international mobile (+E.164): ")
                canonical = password_identity(raw)
                if canonical.startswith("+98") or raw != canonical:
                    raise CommandError("Explicit canonical foreign mobile required.")
                password = getpass.getpass("New password: ")
                confirmation = getpass.getpass("Confirm password: ")
        except (PhoneIdentityInputError, getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            raise CommandError("Provisioning input rejected.") from None

        if not password or password != confirmation:
            raise CommandError("Password confirmation failed.")
        user = CustomUser(mobile_number=canonical, is_active=True)
        try:
            validate_password(password, user=user)
        except ValidationError:
            raise CommandError("Password does not meet policy.") from None
        user.set_password(password)
        try:
            with transaction.atomic():
                user.save(force_insert=True)
                Customer.objects.create(
                    user=user, notify_appointment_sms=False,
                    notify_marketing_sms=False,
                    notify_appointment_whatsapp=False,
                    notify_marketing_whatsapp=False,
                )
        except IntegrityError:
            raise CommandError("Identity or account provisioning conflict.") from None
        self.stdout.write(self.style.SUCCESS("Verified customer provisioned."))
