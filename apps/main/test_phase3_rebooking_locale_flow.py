"""Phase 3.20: executable rebooking session and multilingual flash contract.

Patch only the database fetch and pure booking-selection resolver. Requests run
through the actual LoginRequiredMixin dispatch, session and messages storage;
no writes, SMS, booking creation or payment integrations are exercised.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.contrib.messages.storage.base import Message
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django.utils import translation

from apps.main.templatetags.ui_message_extras import clean_ui_message
from apps.orders.views import RebookPastOrderView
from loomera.globalization.booking_flash_messages import BOOKING_FLASH_MSGIDS
from loomera.globalization.interactive_messages import MESSAGE_IDS


class RebookingLocaleFlowTests(SimpleTestCase):
    def tearDown(self):
        translation.deactivate_all()

    def request(self, authenticated=True, initial=None):
        request = RequestFactory().get(reverse("orders:rebook", kwargs={"order_id": 72}))
        request.user = (
            SimpleNamespace(is_authenticated=True, pk=41)
            if authenticated else AnonymousUser()
        )
        request.session = SessionStore()
        request.session.update(initial or {})
        request._messages = FallbackStorage(request)
        return request

    @staticmethod
    def view(request, *, salon_id=15, selections=None, items=None, raises=None):
        order = SimpleNamespace(salon_id=salon_id)
        items = [object()] if items is None else items
        selections = ([{"serviceId": 3, "stylistId": "23"}]
                      if selections is None else selections)
        with patch("apps.orders.views.get_object_or_404", return_value=order) as fetch, \
             patch("apps.orders.views._build_rebook_stylist_selections") as selection:
            if raises is not None:
                selection.side_effect = raises
            else:
                selection.return_value = (items, selections)
            response = RebookPastOrderView.as_view()(request, order_id=72)
            return response, fetch, selection

    @staticmethod
    def queued(request):
        return list(get_messages(request))

    def test_anonymous_user_is_redirected_before_fetch_or_session_mutation(self):
        req = self.request(authenticated=False, initial={"marker": "keep"})
        response, fetch, selector = self.view(req)
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)
        fetch.assert_not_called()
        selector.assert_not_called()
        self.assertEqual(req.session["marker"], "keep")
        self.assertEqual(self.queued(req), [])

    def test_success_restores_expected_selection_and_clears_stale_booking_state(self):
        existing = {
            "salon_id": "old",
            "stylist_selections": [{"stylistId": "old"}],
            "datetime_selections": {"old": True},
            "service_selections": ["old"],
            "stylists_data": [{"old": True}],
            "reschedule_order_id": "old",
            "reschedule_base_appointment_id": "old",
            "other_session_context": "retain",
        }
        req = self.request(initial=existing)
        selections = [{"serviceId": 90, "stylistId": "25"}]
        response, fetch, resolver = self.view(req, salon_id=18, selections=selections)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("orders:select_dateTime"))
        self.assertEqual(req.session["salon_id"], "18")
        self.assertEqual(req.session["stylist_selections"], selections)
        for key in ("datetime_selections", "service_selections", "stylists_data",
                    "reschedule_order_id", "reschedule_base_appointment_id"):
            self.assertNotIn(key, req.session)
        self.assertEqual(req.session["other_session_context"], "retain")
        self.assertTrue(req.session.modified)
        self.assertEqual(
            fetch.call_args.kwargs["customer__user"], req.user
        )
        self.assertEqual(fetch.call_args.kwargs["pk"], 72)
        resolver.assert_called_once()
        messages = self.queued(req)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].level_tag, "success")
        self.assertEqual(
            str(messages[0]),
            "اطلاعات رزرو قبلی بازیابی شد. حالا زمان جدید را انتخاب کنید.",
        )

    def test_unavailable_previous_professional_yields_info_without_role_or_price_change(self):
        req = self.request(initial={"private_other_state": "persist"})
        selections = [
            {"serviceId": 90, "stylistId": "25"},
            {"serviceId": 91, "stylistId": "any"},
        ]
        response, _, _ = self.view(req, salon_id=18, selections=selections)
        self.assertEqual(response.url, reverse("orders:select_dateTime"))
        self.assertEqual(req.session["stylist_selections"], selections)
        self.assertEqual(req.session["private_other_state"], "persist")
        msg = self.queued(req)
        self.assertEqual(len(msg), 1)
        self.assertEqual(msg[0].level_tag, "info")
        self.assertEqual(str(msg[0]),
            "برای برخی خدمات، متخصص قبلی در دسترس نبود و می‌توانید زمان جدید را با متخصص آزاد انتخاب کنید.")

    def test_incomplete_salon_redirects_without_populating_booking_session(self):
        req = self.request(initial={"datetime_selections": "unchanged"})
        response, fetch, resolver = self.view(req, salon_id=None)
        self.assertEqual(response.url, reverse("orders:appointments"))
        resolver.assert_not_called()
        self.assertEqual(req.session["datetime_selections"], "unchanged")
        msg = self.queued(req)
        self.assertEqual(len(msg), 1)
        self.assertEqual(msg[0].level_tag, "error")
        self.assertEqual(str(msg[0]), "اطلاعات این رزرو برای رزرو مجدد کامل نیست.")

    def test_invalid_prior_selection_fails_closed_and_keeps_current_session(self):
        req = self.request(initial={"reschedule_order_id": "keep"})
        response, _, resolver = self.view(
            req, raises=ValidationError("برای این رزرو خدمتی یافت نشد.")
        )
        self.assertEqual(response.url, reverse("orders:appointments"))
        self.assertEqual(req.session["reschedule_order_id"], "keep")
        self.assertEqual(len(self.queued(req)), 1)
        resolver.assert_called_once()

    def test_empty_items_redirects_without_session_side_effect(self):
        req = self.request(initial={"service_selections": [72]})
        response, _, _ = self.view(req, items=[])
        self.assertEqual(response.url, reverse("orders:appointments"))
        self.assertEqual(req.session["service_selections"], [72])
        msg = self.queued(req)
        self.assertEqual(str(msg[0]), "برای این رزرو امکان رزرو مجدد وجود ندارد.")

    def test_actual_rebooking_flash_text_localizes_for_en_and_ar_only(self):
        expected = {
            "success": "اطلاعات رزرو قبلی بازیابی شد. حالا زمان جدید را انتخاب کنید.",
            "info": "برای برخی خدمات، متخصص قبلی در دسترس نبود و می‌توانید زمان جدید را با متخصص آزاد انتخاب کنید.",
            "error": "برای این رزرو امکان رزرو مجدد وجود ندارد.",
        }
        for tag, persian in expected.items():
            self.assertIn(persian, BOOKING_FLASH_MSGIDS[tag])
            for language in ("en", "ar", "fa"):
                with translation.override(language):
                    with self.subTest(tag=tag, language=language):
                        target = translation.gettext(persian)
                        self.assertEqual(clean_ui_message(persian, tag), target)
                        for hostile in (persian + " user=private", persian + " 09123456789"):
                            if language != "fa":
                                self.assertEqual(
                                    clean_ui_message(hostile, tag),
                                    translation.gettext(MESSAGE_IDS["feedback.default." + tag]),
                                )

    def test_success_and_fallback_info_messages_remain_tone_separated(self):
        success = next(
            phrase for phrase in BOOKING_FLASH_MSGIDS["success"]
            if "اطلاعات رزرو قبلی" in phrase
        )
        info = next(
            phrase for phrase in BOOKING_FLASH_MSGIDS["info"]
            if "برای برخی خدمات" in phrase
        )
        for language in ("en", "ar"):
            with translation.override(language):
                self.assertEqual(clean_ui_message(success, "info"), translation.gettext(
                    MESSAGE_IDS["feedback.default.info"]))
                self.assertEqual(clean_ui_message(info, "success"), translation.gettext(
                    MESSAGE_IDS["feedback.default.success"]))

    def test_source_contract_preserves_ownership_resolver_and_redirects(self):
        src = (Path(settings.BASE_DIR) / "apps/orders/views.py").read_text(
            encoding="utf-8"
        )
        block = src[src.index("class RebookPastOrderView("):]
        block = block[:block.index("\ndef _order_detail_date_field_kind")]
        for critical in (
            "LoginRequiredMixin", "customer__user=request.user",
            "_build_rebook_stylist_selections(order)",
            'selection.get("stylistId") == "any"',
            'request.session["salon_id"] = str(order.salon_id)',
            'request.session["stylist_selections"] = stylist_selections',
            'return redirect("orders:select_dateTime")',
            'return redirect("orders:appointments")',
        ):
            self.assertIn(critical, block)
        self.assertNotIn("Payment.objects.create", block)
        self.assertNotIn("Order.objects.create", block)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
