"""Reviewed multilingual labels for finite financial and booking states.

Only known internal enum values are mapped. Unknown values never expose raw
provider payloads or arbitrary status strings to the customer.
"""
from types import MappingProxyType

from django.utils.translation import gettext as _


PAYMENT_STATE_MESSAGES = MappingProxyType({
    "initiated": "Payment started",
    "pending": "Awaiting payment",
    "success": "Payment successful",
    "failed": "Payment failed",
    "cancelled": "Payment cancelled",
})

ORDER_STATUS_MESSAGES = MappingProxyType({
    "pending": "Awaiting confirmation",
    "confirmed": "Confirmed",
    "paid": "Paid",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "no_show": "No-show",
    "disputed": "Under dispute",
})

PAYMENT_METHOD_MESSAGES = MappingProxyType({
    "online": "Online payment",
    "wallet": "Wallet",
    "pay_in_salon": "Pay at salon",
})

PAYMENT_PROVIDER_MESSAGES = MappingProxyType({
    "zarinpal": "Zarinpal",
    "zibal": "Zibal",
    "wallet": "Wallet",
    "manual": "Manual",
    "mock": "Simulator",
})

SETTLEMENT_STATE_MESSAGES = MappingProxyType({
    "awaiting_payment": "Awaiting payment for settlement",
    "manual_collection": "Pay at salon",
    "ready": "Ready for settlement",
    "hold": "Settlement on hold for review",
    "paid": "Settled",
    "cancelled": "Settlement cancelled",
})

WALLET_TRANSACTION_TYPE_MESSAGES = MappingProxyType({
    "DEPOSIT": "Deposit",
    "WITHDRAW": "Withdrawal",
    "PURCHASE": "Purchase",
    "REFUND": "Refund",
    "WITHDRAW_RESTORE": "Rejected withdrawal returned",
})


def _label(messages, value, fallback):
    """Translate only a recognized state code; never render unknown raw codes."""
    msgid = messages.get(str(value or ""))
    return _(msgid) if msgid else _(fallback)


def payment_state_label(state):
    return _label(PAYMENT_STATE_MESSAGES, state, "Payment status unavailable")


def booking_status_label(status):
    return _label(ORDER_STATUS_MESSAGES, status, "Booking status unavailable")


def payment_method_label(method):
    return _label(PAYMENT_METHOD_MESSAGES, method, "Payment method unavailable")


def payment_provider_label(provider):
    return _label(PAYMENT_PROVIDER_MESSAGES, provider, "Payment provider unavailable")


def settlement_status_label(status):
    return _label(SETTLEMENT_STATE_MESSAGES, status, "Settlement status unavailable")


def wallet_transaction_type_label(transaction_type):
    return _label(
        WALLET_TRANSACTION_TYPE_MESSAGES,
        transaction_type,
        "Transaction type unavailable",
    )


def appointment_payment_status_label(method, is_paid):
    if method == "pay_in_salon":
        return _("Paid at salon") if is_paid else _("Pay at salon")
    return _("Paid") if is_paid else _("Awaiting payment")
