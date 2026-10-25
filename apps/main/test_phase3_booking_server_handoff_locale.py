"""Phase 3.39 — two actual public booking POST views, session boundaries,
specialist accessibility and native gettext availability copy.

Requests execute Django CBV POST handlers with real sessions and messages.
Only external domain lookups/validators are patched; there are no database,
payment, SMS, OTP or order writes. This is not a live browser E2E test.
"""
import json
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.exceptions import ValidationError
from django.template import engines
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django.utils import translation

from apps.orders.views import (
    BookingDateTimeSelectPersian,
    BookingStylistSelectPerService,
)

SELECTIONS = [{
    "serviceId": "15", "serviceName": 'Cut & Color <img onerror=1>',
    "stylistId": "any", "stylistName": "First available professional",
    "requestedStylistId": "any", "requestedStylistName": "First available professional",
}]
PICKED = {"15": {"date": "2026-11-03", "time": "10:00", "end_time": "10:45"}}
SOURCES = {
    "First available time: %(date)s • %(time)s": {
        "fa": "نخستین زمان آزاد: %(date)s • %(time)s",
        "en": "First available time: %(date)s • %(time)s",
        "ar": "أول موعد متاح: %(date)s • %(time)s",
    },
    "No available appointment time found yet": {
        "fa": "فعلاً زمان آزادی پیدا نشد",
        "en": "No available appointment time found yet",
        "ar": "لم يتم العثور على موعد متاح حتى الآن",
    },
    "No available professional for this service yet": {
        "fa": "فعلاً برای این خدمت متخصص آزادی پیدا نشد",
        "en": "No available professional for this service yet",
        "ar": "لا يوجد مختص متاح لهذه الخدمة حاليًا",
    },
    "Available professionals for %(service)s": {
        "fa": "متخصص‌های قابل انتخاب برای %(service)s",
        "en": "Available professionals for %(service)s",
        "ar": "المختصون المتاحون لخدمة %(service)s",
    },
    "Choose first available professional for %(service)s": {
        "fa": "انتخاب اولین متخصص آزاد برای %(service)s",
        "en": "Choose first available professional for %(service)s",
        "ar": "اختيار أول مختص متاح لخدمة %(service)s",
    },
    "Choose %(professional)s for %(service)s": {
        "fa": "انتخاب %(professional)s برای %(service)s",
        "en": "Choose %(professional)s for %(service)s",
        "ar": "اختيار %(professional)s لخدمة %(service)s",
    },
}


class BookingServerHandoffLocaleTests(SimpleTestCase):
    @staticmethod
    def make_request(step, post, session=None):
        request = RequestFactory().post(reverse(step), data=post)
        request.session = session if session is not None else SessionStore()
        request._messages = FallbackStorage(request)
        request.user = SimpleNamespace(is_authenticated=False)
        return request

    @staticmethod
    def salon():
        return SimpleNamespace(pk=27)

    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def tearDown(self):
        translation.deactivate_all()

    def post_specialist(self, request, error=None):
        with patch("apps.orders.views._public_booking_salon_or_none", return_value=self.salon()) as lookup, \
             patch("apps.orders.views._validate_public_booking_stylist_selections") as validator, \
             patch("apps.orders.views.record_booking_quick_link_started"):
            if error:
                validator.side_effect = error
            response = BookingStylistSelectPerService.as_view()(request)
        return response, lookup, validator

    def post_datetime(self, request, error=None):
        with patch("apps.orders.views._public_booking_salon_or_none", return_value=self.salon()) as lookup, \
             patch("apps.orders.views._validate_public_booking_datetime_selections") as validator, \
             patch("apps.orders.views.record_booking_quick_link_started"):
            if error:
                validator.side_effect = error
            response = BookingDateTimeSelectPersian.as_view()(request)
        return response, lookup, validator

    def test_actual_two_step_views_preserve_exact_booking_json_session(self):
        previous = SessionStore()
        previous.update({
            "salon_id": "old", "datetime_selections": {"stale": "paid"},
            "checkout_price_consent": {"stale": True}, "customer_preferences": "keep",
        })
        first = self.make_request("orders:select_stylists", {
            "salon_id": "27", "stylist_selections": json.dumps(SELECTIONS),
        }, previous)
        response, lookup, validator = self.post_specialist(first)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("orders:select_dateTime"))
        self.assertEqual(previous["salon_id"], "27")
        self.assertEqual(previous["stylist_selections"], SELECTIONS)
        self.assertNotIn("datetime_selections", previous)
        self.assertEqual(previous["customer_preferences"], "keep")
        validator.assert_called_once()
        lookup.assert_called_once_with("27")
        self.assertEqual(list(get_messages(first)), [])
        payload = {
            "salon_id": 27,
            "stylist_selections": SELECTIONS,
            "datetime_selections": PICKED,
        }
        second = self.make_request("orders:select_dateTime", {
            "booking_data": json.dumps(payload),
        }, previous)
        final, lookup, validation = self.post_datetime(second)
        self.assertEqual(final.status_code, 302)
        self.assertEqual(final.url, reverse("orders:reservation_preview"))
        self.assertEqual(previous["salon_id"], "27")
        self.assertEqual(previous["stylist_selections"], SELECTIONS)
        self.assertEqual(previous["datetime_selections"], PICKED)
        self.assertEqual(previous["customer_preferences"], "keep")
        self.assertNotIn("orders", previous)
        lookup.assert_called_once_with(27)
        validation.assert_called_once()

    def test_bad_stylist_json_fails_closed_and_cannot_keep_older_slot(self):
        session = SessionStore()
        session.update({"salon_id": "27", "stylist_selections": SELECTIONS,
                        "datetime_selections": PICKED, "other": "kept"})
        request = self.make_request("orders:select_stylists", {
            "salon_id": "27", "stylist_selections": "{invalid",
        }, session)
        response, lookup, validation = self.post_specialist(request)
        self.assertEqual(response.url, reverse("orders:select_stylists"))
        lookup.assert_not_called()
        validation.assert_not_called()
        for key in ("salon_id", "stylist_selections", "datetime_selections"):
            self.assertNotIn(key, session)
        self.assertEqual(session["other"], "kept")
        self.assertEqual(len(list(get_messages(request))), 1)

    def test_rejected_domain_stylist_selection_clears_session(self):
        session = SessionStore()
        session.update({"salon_id": "27", "datetime_selections": PICKED})
        request = self.make_request("orders:select_stylists", {
            "salon_id": "27", "stylist_selections": json.dumps(SELECTIONS),
        }, session)
        response, _, validator = self.post_specialist(
            request, ValidationError("Unapproved specialist"))
        self.assertEqual(response.url, reverse("orders:select_stylists"))
        validator.assert_called_once()
        self.assertNotIn("datetime_selections", session)
        self.assertNotIn("stylist_selections", session)
        self.assertNotIn("salon_id", session)

    def test_invalid_datetime_json_fails_closed_before_lookup(self):
        session = SessionStore()
        session.update({"salon_id": "27", "stylist_selections": SELECTIONS,
                        "datetime_selections": PICKED})
        request = self.make_request("orders:select_dateTime", {"booking_data": "[]"}, session)
        response, lookup, validator = self.post_datetime(request)
        self.assertEqual(response.url, reverse("orders:select_dateTime"))
        lookup.assert_not_called()
        validator.assert_not_called()
        self.assertNotIn("datetime_selections", session)
        self.assertNotIn("stylist_selections", session)
        self.assertEqual(len(list(get_messages(request))), 1)

    def test_datetime_domain_conflict_fails_closed_before_checkout(self):
        session = SessionStore()
        session["customer_preferences"] = "keep"
        request = self.make_request("orders:select_dateTime", {
            "booking_data": json.dumps({
                "salon_id": "27", "stylist_selections": SELECTIONS,
                "datetime_selections": PICKED,
            }),
        }, session)
        response, lookup, validator = self.post_datetime(
            request, ValidationError("Slot no longer available"))
        self.assertEqual(response.url, reverse("orders:select_dateTime"))
        lookup.assert_called_once_with("27")
        validator.assert_called_once()
        self.assertNotIn("salon_id", session)
        self.assertNotIn("datetime_selections", session)
        self.assertEqual(session["customer_preferences"], "keep")

    def test_compiled_gettext_availability_and_aria_messages_three_locales(self):
        for lang in ("fa", "en", "ar"):
            with translation.override(lang), self.subTest(locale=lang):
                for msgid, forms in SOURCES.items():
                    self.assertEqual(translation.gettext(msgid), forms[lang])
                label = BookingStylistSelectPerService()._format_next_available_label({
                    "date": date(2026, 11, 3), "time": time(10, 45)
                })
                self.assertIn("10:45", label)
                self.assertIn("•", label)
                self.assertNotIn("%(date)s", label)
                self.assertNotIn("%(time)s", label)
                self.assertEqual(
                    BookingStylistSelectPerService()._format_next_available_label(None),
                    SOURCES["No available appointment time found yet"][lang]
                )

    def test_aria_format_escapes_hostile_service_and_professional_names(self):
        template = (
            "{% load i18n %}{% blocktrans with professional=person service=service %}"
            "Choose {{ professional }} for {{ service }}{% endblocktrans %}"
        )
        service = 'Cut <svg/onload=1> & شینیون'
        professional = 'Sara "O\'Reilly" & نازنین'
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                rendered = engines["django"].from_string(template).render({
                    "person": professional, "service": service,
                })
                self.assertNotIn("<svg", rendered)
                self.assertIn("&lt;svg", rendered)
                self.assertIn("&amp;", rendered)
                self.assertIn("شینیون", rendered)
                self.assertIn("نازنین", rendered)

    def test_specialist_template_data_handoff_and_a11y_reuse_real_translations(self):
        src = self.source("templates/orders/select_stylists.html")
        self.assertIn('data-stylist-name="{% trans \'First available professional\' %}"', src)
        self.assertIn("blocktrans with professional=", src)
        self.assertIn("blocktrans with service=", src)
        self.assertIn("dir=\"auto\"", src)
        self.assertIn('aria-pressed="false"', src)
        self.assertIn("data-stylist-id=\"any\"", src)
        self.assertIn("data-next-date=", src)
        self.assertIn("data-stylist-price=", src)
        self.assertIn("data-stylist-name=\"{{ item.stylist.user.get_fullName", src)
        self.assertNotIn('data-stylist-name="اولین متخصص آزاد"', src)
        self.assertIn("{% trans 'minutes' %}", src)
        self.assertIn("{% trans 'toman' %}", src)

    def test_public_booking_stage_does_not_create_order_or_charge_payment(self):
        src = self.source("apps/orders/views.py")
        block = src[src.index("class BookingStylistSelectPerService("):
                    src.index("class StylistAvailabilityAPI(")]
        self.assertIn("_validate_public_booking_stylist_selections(", block)
        self.assertIn("_validate_public_booking_datetime_selections(", block)
        self.assertIn('request.session["datetime_selections"] = datetime_selections', block)
        self.assertIn('return redirect("orders:reservation_preview")', block)
        self.assertNotIn("Order.objects.create", block)
        self.assertNotIn("Payment.objects.create", block)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")

    def test_manual_release_signoff_remains_unearned(self):
        data = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(data["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertFalse(data["manual_evidence"])
        self.assertIn("screen_reader_acceptance", data["open_gates"])
