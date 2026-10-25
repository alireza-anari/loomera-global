"""Phase 3.32: localized finite financial states and cancellation/refund feedback.

These database-free tests cover the real gettext catalog and pure view/policy
helpers. They intentionally do not exercise live gateways or issue refunds.
"""
import json
from pathlib import Path
import struct
from types import SimpleNamespace

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.utils import translation

from apps.orders.booking_utils import build_cancellation_policy
from apps.payments.views import (
    _appointment_payment_expired_checkout_context,
    _appointment_payment_pending_review_context,
)
from loomera.globalization.financial_status import (
    appointment_payment_status_label,
    booking_status_label,
    payment_method_label,
    payment_provider_label,
    payment_state_label,
    settlement_status_label,
    wallet_transaction_type_label,
)


class FinancialRuntimeLocaleTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @classmethod
    def rows(cls):
        payload = json.loads(cls.source("docs/globalization/PHASE3_32_MESSAGE_REVIEW.json"))
        return payload

    def tearDown(self):
        translation.deactivate_all()

    def test_review_ledger_has_64_unique_safe_static_messages(self):
        payload = self.rows()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["phase"], "3.32")
        rows = payload["message_rows"]
        self.assertEqual(len(rows), 64)
        self.assertEqual(len({row["en"] for row in rows}), 64)
        for row in rows:
            with self.subTest(msgid=row["en"][:45]):
                self.assertEqual(set(row), {"en", "fa", "ar"})
                for lang in ("en", "fa", "ar"):
                    self.assertTrue(row[lang].strip())
                    self.assertLess(len(row[lang]), 500)
                    for forbidden in ("<", ">", "{", "}"):
                        self.assertNotIn(forbidden, row[lang])

    def test_all_64_reviewed_messages_match_three_compiled_catalogs(self):
        rows = self.rows()["message_rows"]
        marker = "#: docs/globalization/PHASE3_32_MESSAGE_REVIEW.json"
        for lang in ("fa", "en", "ar"):
            folder = Path(settings.BASE_DIR) / "locale" / lang / "LC_MESSAGES"
            po = (folder / "django.po").read_text(encoding="utf-8")
            mo = (folder / "django.mo").read_bytes()
            self.assertEqual(struct.unpack_from("<I", mo, 0)[0], 0x950412de)
            self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 490)
            self.assertEqual(po.count(marker), 64)
            lines = po.splitlines()
            added = {
                json.loads(lines[index + 1][6:])
                for index, line in enumerate(lines)
                if line == marker and lines[index + 1].startswith("msgid ")
            }
            self.assertEqual(len(added), 64)
            with translation.override(lang):
                for row in rows:
                    with self.subTest(lang=lang, msgid=row["en"][:40]):
                        self.assertEqual(translation.gettext(row["en"]), row[lang])

    def test_state_helpers_localize_known_codes_and_never_echo_unknown_codes(self):
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                with self.subTest(lang=lang):
                    self.assertEqual(payment_state_label("pending"), translation.gettext("Awaiting payment"))
                    self.assertEqual(payment_state_label("failed"), translation.gettext("Payment failed"))
                    self.assertEqual(booking_status_label("no_show"), translation.gettext("No-show"))
                    self.assertEqual(booking_status_label("disputed"), translation.gettext("Under dispute"))
                    self.assertEqual(payment_method_label("wallet"), translation.gettext("Wallet"))
                    self.assertEqual(payment_provider_label("zibal"), translation.gettext("Zibal"))
                    self.assertEqual(settlement_status_label("hold"), translation.gettext("Settlement on hold for review"))
                    self.assertEqual(settlement_status_label("manual_collection"), translation.gettext("Pay at salon"))
                    self.assertEqual(wallet_transaction_type_label("DEPOSIT"), translation.gettext("Deposit"))
                    self.assertEqual(wallet_transaction_type_label("WITHDRAW"), translation.gettext("Withdrawal"))
                    self.assertEqual(wallet_transaction_type_label("PURCHASE"), translation.gettext("Purchase"))
                    self.assertEqual(wallet_transaction_type_label("WITHDRAW_RESTORE"), translation.gettext("Rejected withdrawal returned"))
                    self.assertEqual(wallet_transaction_type_label("UNKNOWN_TYPE"), translation.gettext("Transaction type unavailable"))
                    self.assertEqual(
                        appointment_payment_status_label("pay_in_salon", False),
                        translation.gettext("Pay at salon"),
                    )
                    self.assertEqual(
                        appointment_payment_status_label("pay_in_salon", True),
                        translation.gettext("Paid at salon"),
                    )
                    unknown = payment_state_label("SECRET_GATEWAY_STATUS")
                    self.assertEqual(unknown, translation.gettext("Payment status unavailable"))
                    self.assertNotIn("SECRET_GATEWAY_STATUS", unknown)

    def test_pending_and_expired_payment_copy_is_localized_without_gateway_payload_leaks(self):
        payment = SimpleNamespace(
            state="pending",
            is_finally=False,
            meta={"verify_pending": {
                "requires_review": True,
                "retryable": False,
                "message": "SECRET_GATEWAY_TRACE private-token",
            }},
        )
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                pending = _appointment_payment_pending_review_context(payment)
                self.assertTrue(pending["is_active"])
                self.assertEqual(pending["title"], translation.gettext("Payment requires review"))
                self.assertEqual(
                    pending["body"],
                    translation.gettext(
                        "The payment gateway response did not match the order details. "
                        "For financial safety, this transaction is under review."
                    ),
                )
                self.assertNotIn("SECRET_GATEWAY_TRACE", pending["body"])
                self.assertNotIn("private-token", pending["body"])
                self.assertEqual(
                    pending["primary_hint"],
                    translation.gettext("Please do not pay again while this transaction is being checked."),
                )
                expired = _appointment_payment_expired_checkout_context(SimpleNamespace(
                    state="cancelled",
                    meta={"abandoned_checkout": {"expired": True, "reason": "private internal code"}},
                ))
                self.assertTrue(expired["is_active"])
                self.assertEqual(expired["title"], translation.gettext("Payment window expired"))
                self.assertEqual(
                    expired["body"],
                    translation.gettext(
                        "Online payment was not completed in time. The booking is no longer "
                        "pending and the selected time has been released."
                    ),
                )

    def test_policy_fallback_is_translated_but_salon_authored_policy_is_preserved(self):
        salon = SimpleNamespace(
            supplementary_info=SimpleNamespace(filter=lambda **kwargs: []),
            cancellation_window_hours=24,
            cancellation_refund_percent=80,
            cancellation_policy_note="",
        )
        custom = SimpleNamespace(
            title="Cancellation policy",
            description="This salon-specific policy remains exactly as authored.",
        )
        custom_salon = SimpleNamespace(
            supplementary_info=SimpleNamespace(filter=lambda **kwargs: [custom]),
            cancellation_window_hours=24,
            cancellation_refund_percent=80,
            cancellation_policy_note="",
        )
        description_id = (
            "Online cancellation is available up to %(hours)s hours before the appointment. "
            "For online or wallet payments, %(percent)s%% of the amount is returned to your wallet."
        )
        hint_id = (
            "Online cancellation is currently available. If you cancel, "
            "%(percent)s%% of the digital payment will be returned to your wallet."
        )
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                policy = build_cancellation_policy(salon, can_cancel=True, is_upcoming=True)
                self.assertEqual(policy["title"], translation.gettext("Cancellation policy"))
                self.assertEqual(
                    policy["description"],
                    translation.gettext(description_id) % {"hours": 24, "percent": 80},
                )
                self.assertEqual(
                    policy["hint"], translation.gettext(hint_id) % {"percent": 80},
                )
                custom_policy = build_cancellation_policy(custom_salon, can_cancel=False, is_upcoming=True)
                self.assertEqual(custom_policy["title"], translation.gettext("Salon cancellation policy"))
                self.assertEqual(custom_policy["description"], custom.description)
                self.assertEqual(
                    custom_policy["hint"],
                    translation.gettext(
                        "Online cancellation is not available for this appointment. "
                        "Please contact the salon if you need help."
                    ),
                )

    def test_cancellation_api_and_browser_fallbacks_use_native_gettext(self):
        source = self.source("apps/orders/views.py")
        start = source.index("class CancelAppointmentView(")
        end = source.index("\n# ---------------------------------------------------------------------", start)
        block = source[start:end]
        self.assertIn("order__customer__user=request.user", block)
        self.assertIn("with transaction.atomic():", block)
        self.assertIn("cancel_order_with_financials(", block)
        self.assertIn('_("Cancellation is not available for this appointment. Please contact the salon.")', block)
        self.assertIn('_("This appointment has already been cancelled.")', block)
        self.assertIn('_("Cancellation is temporarily unavailable. Please try again.")', block)
        self.assertIn('_("Your appointment was cancelled successfully.")', block)
        self.assertIn('"Refunded %(amount)s toman to your wallet."', block)
        self.assertIn('logger.exception(', block)

        detail = self.source("templates/orders/appointment_detail.html")
        self.assertIn('{% trans \'Are you sure you want to cancel this appointment?\' as cancelConfirmMessage %}', detail)
        self.assertIn('confirm(cancelConfirmMessage)', detail)
        self.assertIn("data.error || cancelFallbackError", detail)
        self.assertIn("data.message || cancelFallbackSuccess", detail)
        self.assertIn("cancelNetworkError", detail)
        self.assertIn('<bdi dir="auto">{{ appointment.order.cancellation_reason }}</bdi>', detail)
        self.assertEqual(detail.count("{{ amount }} toman was returned to your wallet under the cancellation policy."), 2)

    def test_payment_result_and_appointment_detail_templates_compile_and_use_localized_context(self):
        result = self.source("templates/payments/appointment_result.html")
        self.assertIn("payment_state_label", self.source("apps/payments/views.py"))
        self.assertIn('"payment_method_label":', self.source("apps/payments/views.py"))
        self.assertIn('"payment_provider_label":', self.source("apps/payments/views.py"))
        self.assertIn("{{ payment_method_label|default:'—' }}", result)
        self.assertIn("{{ payment_provider_label|default:'—' }}", result)
        self.assertIn("{{ settlement_status_label }}", result)
        self.assertIn("{% trans 'Refund status' %}", result)
        self.assertIn("{% blocktrans with amount=refund_amount|floatformat:0 %}", result)
        self.assertIn("{% blocktrans with time=refund_time|jalali_datetime %}", result)
        payment_views = self.source("apps/payments/views.py")
        result_view = payment_views[payment_views.index("class AppointmentPaymentResultView("):]
        self.assertIn('"payment_status_label": payment_state_label(payment.state)', result_view)
        self.assertIn('"order_status_label": (', result_view)
        self.assertNotIn("payment.get_state_display()", result_view)
        self.assertNotIn("order.get_status_display()", result_view)
        detail = self.source("templates/orders/appointment_detail.html")
        self.assertIn("{% trans 'Cancellation reason' %}", detail)
        self.assertIn('_("Service discount campaign")', self.source("apps/orders/views.py"))
        self.assertIn("appointment_payment_status_label(", self.source("apps/orders/views.py"))
        self.assertIn("wallet_transaction_type_label(", self.source("apps/orders/views.py"))
        self.assertIn("{{ tx.localized_type_label }}", detail)
        self.assertNotIn("get_transaction_type_display", detail)
        self.assertNotIn("get_selected_payment_method_display", detail)
        self.assertNotIn("payment_record.get_state_display", detail)
        self.assertNotIn("appointment.order.get_status_display", detail)
        get_template("payments/appointment_result.html")
        get_template("orders/appointment_detail.html")

    def test_financial_copy_keeps_values_parameterized_and_release_gates_blocked(self):
        with translation.override("en"):
            refund = translation.gettext(
                "Your appointment was cancelled successfully. Refunded %(amount)s toman to your wallet."
            ) % {"amount": "12,500"}
            self.assertIn("12,500", refund)
            self.assertNotIn("%(amount)s", refund)
            policy = translation.gettext(
                "Online cancellation is available up to %(hours)s hours before the appointment. "
                "For online or wallet payments, %(percent)s%% of the amount is returned to your wallet."
            ) % {"hours": 24, "percent": 80}
            self.assertIn("24 hours", policy)
            self.assertIn("80%", policy)
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["manual_evidence"], [])
        for gate in (
            "real_browser_visual", "real_keyboard_acceptance",
            "screen_reader_acceptance", "responsive_zoom",
            "release_deployment_approval",
        ):
            self.assertIn(gate, matrix["open_gates"])
