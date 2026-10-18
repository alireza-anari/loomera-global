from __future__ import annotations

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import SalonManager
from apps.analytics.models import AnalyticsEvent
from apps.orders import quick_link_qr
from apps.orders.models import BookingQuickLink
from apps.orders.quick_links import (
    BOOKING_QUICK_LINK_CONVERTED_EVENT,
    BOOKING_QUICK_LINK_OPENED_EVENT,
)
from apps.salons.models import Salon
from apps.services.models import Services


User = get_user_model()


class QuickLinkReadinessCheckTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager_user = User.objects.create_user(
            mobile_number="09126661001",
            password="test-pass-123",
            name="مدیر",
            family="آمادگی لینک",
        )
        cls.manager_user.is_active = True
        cls.manager_user.save(
            update_fields=["is_active"]
        )

        cls.manager = SalonManager.objects.create(
            user=cls.manager_user,
            is_active=True,
        )

        cls.salon = Salon.objects.create(
            salon_name="سالن آمادگی لینک",
            salon_manager=cls.manager,
            is_active=True,
        )

        cls.service = Services.objects.create(
            service_name="خدمت آمادگی لینک",
            is_active=True,
            duration_minutes=30,
            base_price=100000,
        )

        cls.salon.services.add(cls.service)

    def create_link(self, **overrides):
        values = {
            "creator": self.manager_user,
            "salon": self.salon,
            "service": self.service,
            "title": "لینک آمادگی",
            "mode": BookingQuickLink.Mode.SERVICE,
            "placement": (
                BookingQuickLink.Placement.DIRECT
            ),
            "payload": {
                "mode": BookingQuickLink.Mode.SERVICE,
                "salon_id": self.salon.pk,
                "service_ids": [self.service.pk],
                "stylist_user_id": None,
                "date": "",
                "time": "",
                "summary": {},
            },
            "is_permanent": True,
        }
        values.update(overrides)

        return BookingQuickLink.objects.create(
            **values
        )

    def create_event(
        self,
        *,
        quick_link,
        event_type,
        session_key="",
    ):
        content_type = (
            ContentType.objects.get_for_model(
                BookingQuickLink,
                for_concrete_model=False,
            )
        )

        return AnalyticsEvent.objects.create(
            category="appointment",
            event_type=event_type,
            occurred_at=timezone.now(),
            salon=self.salon,
            target_content_type=content_type,
            target_object_id=quick_link.pk,
            session_key=session_key,
            source=quick_link.placement,
            metadata={
                "quick_link_id": quick_link.pk,
            },
        )

    def run_command(self, *arguments):
        output = StringIO()

        call_command(
            "quick_link_readiness_check",
            *arguments,
            stdout=output,
        )

        return output.getvalue()

    def test_healthy_project_passes_without_writes(self):
        quick_link = self.create_link()

        link_count = (
            BookingQuickLink.objects.count()
        )
        event_count = (
            AnalyticsEvent.objects.count()
        )

        output = self.run_command()

        self.assertIn(
            "Quick-link readiness passed.",
            output,
        )
        self.assertIn(
            "duplicate-conversions",
            output,
        )
        self.assertIn(
            "qr-glyph",
            output,
        )

        self.assertEqual(
            BookingQuickLink.objects.count(),
            link_count,
        )
        self.assertEqual(
            AnalyticsEvent.objects.count(),
            event_count,
        )

        quick_link.refresh_from_db()
        self.assertTrue(quick_link.is_active)

    def test_archived_active_link_fails(self):
        self.create_link(
            archived_at=timezone.now(),
            is_active=True,
        )

        with self.assertRaises(CommandError):
            self.run_command()

    def test_blank_session_is_warning_by_default(self):
        quick_link = self.create_link()

        self.create_event(
            quick_link=quick_link,
            event_type=(
                BOOKING_QUICK_LINK_OPENED_EVENT
            ),
            session_key="",
        )

        output = self.run_command()

        self.assertIn(
            "WARN blank-analytics-session",
            output,
        )

    def test_fail_on_warnings_returns_non_zero(self):
        quick_link = self.create_link()

        self.create_event(
            quick_link=quick_link,
            event_type=(
                BOOKING_QUICK_LINK_OPENED_EVENT
            ),
            session_key="",
        )

        with self.assertRaises(CommandError):
            self.run_command(
                "--fail-on-warnings"
            )

    def test_orphan_analytics_event_fails(self):
        quick_link = self.create_link()

        event = self.create_event(
            quick_link=quick_link,
            event_type=(
                BOOKING_QUICK_LINK_CONVERTED_EVENT
            ),
            session_key="session-1",
        )

        event.target_object_id = (
            quick_link.pk + 999999
        )
        event.save(
            update_fields=[
                "target_object_id",
            ]
        )

        with self.assertRaises(CommandError):
            self.run_command()

    def test_readiness_uses_buyer_png_after_import(self):
        with TemporaryDirectory() as directory:
            for index in range(2):
                path = Path(directory) / f"buyer-{index}.png"
                Image.new("RGBA", (64, 64), (17, 197, 61, 255)).save(path)
                selected = f"buyer/qr/{index}.png"
                with override_settings(BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH=selected):
                    with patch.object(quick_link_qr.finders, "find", return_value=str(path)) as find:
                        output = self.run_command()
                    find.assert_called_once_with(selected)
                self.assertIn("PASS qr-glyph", output)
                self.assertIn(selected, output)

    def test_readiness_rejects_missing_corrupt_and_invisible_buyer_glyphs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / "bad.png"
            corrupt.write_bytes(b"not PNG")
            empty = root / "empty.png"
            Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(empty)
            for resolved in (None, str(root / "missing.png"), str(corrupt), str(empty)):
                with self.subTest(resolved=resolved):
                    output = StringIO()
                    with override_settings(BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH="buyer/invalid.png"):
                        with patch.object(quick_link_qr.finders, "find", return_value=resolved) as find:
                            with self.assertRaises(CommandError):
                                call_command("quick_link_readiness_check", stdout=output)
                        find.assert_called_once_with("buyer/invalid.png")
                    self.assertIn("FAIL qr-glyph", output.getvalue())
                    self.assertIn("buyer/invalid.png", output.getvalue())
