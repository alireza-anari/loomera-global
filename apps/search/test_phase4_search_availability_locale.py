"""Phase 4.3c: localized availability labels and branded public search SEO."""
import json
import re
import struct
from gettext import translation as load_catalog
from pathlib import Path
from types import SimpleNamespace

from django.template import Context, Template
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.utils import translation

from apps.search.utils import (
    SearchFilters,
    build_search_availability_label,
    serialize_salon_for_map,
)

ROOT = Path(__file__).resolve().parents[2]
SEO_MESSAGE = (
    "Explore salons, services and beauty professionals at %(brand)s. "
    "Filter by price, ratings, discounts and available appointments."
)


class Phase4SearchAvailabilityLocaleTests(SimpleTestCase):
    def test_search_availability_statuses_render_in_three_languages(self):
        expected = {
            "fa": (
                "اولین زمان آزاد 09:30",
                "اولین زمان آزاد ۱۴۰۵/۰۱/۱۰ ساعت 09:30",
                "دارای وقت آزاد",
                "نوبت آزاد",
            ),
            "en": (
                "First available at 09:30",
                "First available on ۱۴۰۵/۰۱/۱۰ at 09:30",
                "Appointments available",
                "Available appointment",
            ),
            "ar": (
                "أول موعد متاح الساعة 09:30",
                "أول موعد متاح يوم ۱۴۰۵/۰۱/۱۰ الساعة 09:30",
                "تتوفر مواعيد للحجز",
                "موعد متاح",
            ),
        }
        for lang, (single, multiple, available, fallback) in expected.items():
            with self.subTest(lang=lang), translation.override(lang):
                self.assertEqual(build_search_availability_label("09:30"), single)
                self.assertEqual(
                    build_search_availability_label("09:30", "۱۴۰۵/۰۱/۱۰"), multiple
                )
                self.assertEqual(build_search_availability_label(""), available)
                self.assertEqual(translation.gettext("Available appointment"), fallback)

    def test_map_api_and_card_keep_the_same_localized_status_value(self):
        card_source = (ROOT / "templates/search/search_results.html").read_text()
        self.assertIn("{{ salon.search_available_label }}", card_source)
        utils_source = (ROOT / "apps/search/utils.py").read_text()
        self.assertIn("_format_search_date_label(current_date)", utils_source)
        self.assertIn("build_search_availability_label(", utils_source)
        for lang in ("fa", "en", "ar"):
            with translation.override(lang):
                label = build_search_availability_label("12:30")
                salon = SimpleNamespace(
                    id=9, salon_name="Business provided name", address="",
                    neighborhood=None, location=None, banner_image=None,
                    avg_score=0, search_available_label=label,
                    get_absolute_url=lambda: "/salons/9/",
                )
                api_label = serialize_salon_for_map(salon)["available_label"]
                self.assertEqual(api_label, label)

    def test_search_title_and_meta_are_translated_and_brand_safe(self):
        path = "templates/pages/search.html"
        get_template(path.removeprefix("templates/"))
        source = (ROOT / path).read_text(encoding="utf-8")
        title = re.search(
            r"{% block title %}(.*?){% endblock %}", source
        ).group(1)
        meta = re.search(
            r"{% block meta_description %}(.*?){% endblock %}", source
        ).group(1)
        self.assertIn("blocktrans with brand=deployment_brand.display_name", meta)
        context = Context({
            "deployment_brand": SimpleNamespace(display_name="Brand & Co"),
        })
        for lang in ("fa", "en", "ar"):
            with self.subTest(lang=lang), translation.override(lang):
                rendered_title = Template("{% load i18n %}" + title).render(context)
                rendered_meta = Template("{% load i18n %}" + meta).render(context)
                translated_title = translation.gettext(
                    "Search for salons and beauty services"
                )
                translated_meta = translation.gettext(SEO_MESSAGE)
                self.assertEqual(
                    rendered_title, translated_title + " | Brand &amp; Co"
                )
                self.assertEqual(
                    rendered_meta,
                    translated_meta % {"brand": "Brand &amp; Co"},
                )
                self.assertNotIn("%(brand)s", rendered_meta)

    def test_reviewed_translations_and_compiled_catalogs_have_parity(self):
        ledger = json.loads(
            (ROOT / "docs/globalization/PHASE4_3C_MESSAGE_REVIEW.json").read_text()
        )["reviewed_messages"]
        self.assertEqual(len(ledger), 6)
        self.assertEqual(len(set(x["msgid"] for x in ledger)), 6)
        for lang in ("fa", "en", "ar"):
            with self.subTest(lang=lang):
                po = (ROOT / f"locale/{lang}/LC_MESSAGES/django.po").read_text()
                data = (ROOT / f"locale/{lang}/LC_MESSAGES/django.mo").read_bytes()
                self.assertEqual(struct.unpack_from("<I", data, 0)[0], 0x950412de)
                self.assertEqual(struct.unpack_from("<I", data, 8)[0], 896)
                catalog = load_catalog("django", localedir=str(ROOT / "locale"), languages=[lang])
                for msg in ledger:
                    self.assertIn("msgid " + json.dumps(msg["msgid"]), po)
                    self.assertEqual(catalog.gettext(msg["msgid"]), msg[lang])

    def test_previous_behavior_and_manual_release_gate_remain_intact(self):
        source = (ROOT / "apps/search/utils.py").read_text(encoding="utf-8")
        self.assertIn("_slot_is_past(current_date, start_minutes)", source)
        self.assertIn("if first_slot and len(availability_dates) > 1", source)
        self.assertIn("return _(\"Appointments available\")", source)
        matrix = json.loads(
            (ROOT / "docs/globalization/PHASE3_EXIT_MATRIX.json").read_text()
        )
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["production_deployment"], "NOT_PERFORMED")
