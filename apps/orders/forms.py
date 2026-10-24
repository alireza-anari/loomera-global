from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .models import PaymentType


class OrderForm(forms.Form):
    payment_type = forms.ChoiceField(
        label="",
        choices=[],
        widget=forms.RadioSelect(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_type"].choices = [
            (item.pk, item.payment_title) for item in PaymentType.objects.all()
        ]


class AppointmentCheckoutForm(forms.Form):
    PAYMENT_METHOD_ONLINE = "online"
    PAYMENT_METHOD_WALLET = "wallet"
    PAYMENT_METHOD_SALON = "pay_in_salon"

    coupon_code = forms.CharField(
        required=False,
        max_length=100,
        label=_("Discount code"),
        widget=forms.TextInput(
            attrs={
                "class": "w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm focus:border-purple-500 focus:outline-none",
                "placeholder": _("Enter your discount code"),
                "dir": "ltr",
            }
        ),
    )
    payment_method = forms.ChoiceField(
        label=_("Payment method"), choices=[], widget=forms.RadioSelect()
    )

    def __init__(self, *args, requires_online_payment=False, **kwargs):
        super().__init__(*args, **kwargs)
        online_payment_enabled = bool(
            getattr(settings, "ONLINE_PAYMENT_ENABLED", False)
        )
        self.requires_online_payment = bool(
            requires_online_payment and online_payment_enabled
        )
        self.online_payment_enabled = online_payment_enabled

        choices = []
        if online_payment_enabled:
            choices.extend(
                [
                    (self.PAYMENT_METHOD_ONLINE, _("Online payment")),
                    (self.PAYMENT_METHOD_WALLET, _("Pay with wallet")),
                ]
            )

        if not self.requires_online_payment:
            choices.append((self.PAYMENT_METHOD_SALON, _("Pay at the salon")))

        self.fields["payment_method"].choices = choices
        self.fields["payment_method"].initial = (
            self.PAYMENT_METHOD_ONLINE
            if self.requires_online_payment
            else self.PAYMENT_METHOD_SALON
        )

    def clean_coupon_code(self):
        return (self.cleaned_data.get("coupon_code") or "").strip().upper()

    def clean_payment_method(self):
        method = self.cleaned_data.get("payment_method")
        if not self.online_payment_enabled and method != self.PAYMENT_METHOD_SALON:
            raise forms.ValidationError(_("In the beta, only pay-at-the-salon is available."))
        if self.requires_online_payment and method not in {
            self.PAYMENT_METHOD_ONLINE,
            self.PAYMENT_METHOD_WALLET,
        }:
            raise forms.ValidationError(
                _("For a first visit to this salon, only digital payment (online or wallet) is allowed.")
            )
        return method
