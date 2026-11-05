"""Phase 4.2: translated public service, price and specialist discovery surfaces."""
import json
import re
import struct
from gettext import translation as load_gettext_catalog
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import get_template, render_to_string
from django.test import SimpleTestCase
from django.utils import translation

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = (
    "templates/services/all_services.html",
    "templates/services/partials/filtered_services.html",
    "templates/services/partials/priceList.html",
    "templates/services/service_detail.html",
    "templates/pages/salon_stylist_profile.html",
    "templates/pages/search.html",
)
TRANS_TAG = re.compile(
    r"""{%\s*trans\s+(?P<quote>["'])(?P<message>.*?)(?P=quote)(?:\s+as\s+\w+)?\s*%}"""
)
PERSIAN_OR_ARABIC = re.compile(r"[\u0600-\u06FF]")


class Phase4ServicesDiscoveryLocaleTests(SimpleTestCase):
    def source(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def catalog(self, lang):
        return load_gettext_catalog(
            "django", localedir=str(ROOT / "locale"), languages=[lang]
        )

    def test_all_templates_compile_and_native_translations_are_present(self):
        messages = set()
        for path in TEMPLATES:
            with self.subTest(path=path):
                source = self.source(path)
                self.assertIn("{% load i18n %}", source)
                get_template(path.removeprefix("templates/"))
                messages.update(m.group("message") for m in TRANS_TAG.finditer(source))
        messages.add("About %(duration)s minutes")
        ledger = json.loads(self.source("docs/globalization/PHASE4_2_MESSAGE_REVIEW.json"))
        reviewed = {entry["msgid"] for entry in ledger["reviewed_messages"]}
        self.assertEqual(len(reviewed), 53)
        for language in ("fa", "en", "ar"):
            catalog = self.catalog(language)
            with self.subTest(language=language):
                compiled = (ROOT / "locale" / language / "LC_MESSAGES" / "django.mo").read_bytes()
                self.assertEqual(struct.unpack_from("<I", compiled)[0], 0x950412de)
                self.assertEqual(struct.unpack_from("<I", compiled, 8)[0], 904)
                for msgid in messages:
                    self.assertIn(msgid, catalog._catalog)
                    if language == "en":
                        self.assertEqual(catalog.gettext(msgid), msgid)
                    else:
                        self.assertNotEqual(catalog.gettext(msgid), msgid)
                for entry in ledger["reviewed_messages"]:
                    self.assertEqual(catalog.gettext(entry["msgid"]), entry[language])

    def test_public_service_bodies_have_no_hardcoded_persian_ui(self):
        for path in TEMPLATES:
            source = self.source(path)
            source = re.sub(
                r"{%\s*block\s+(?:title|meta_description)\s*%}.*?{%\s*endblock\s*%}",
                "",
                source,
                flags=re.DOTALL,
            )
            with self.subTest(path=path):
                self.assertIsNone(PERSIAN_OR_ARABIC.search(source))

    def test_service_directory_preserves_domain_values_and_safe_modal_loading(self):
        listing = self.source("templates/services/all_services.html")
        filtered = self.source("templates/services/partials/filtered_services.html")
        prices = self.source("templates/services/partials/priceList.html")
        self.assertIn("{{ selected_group.group_title }}", listing)
        self.assertIn("{{ group.group_title }}", listing)
        self.assertIn("{{ service.service_name }}", filtered)
        self.assertIn("{{ service.duration_minutes }}", filtered)
        self.assertIn("data-service-name=\"{{ service.service_name }}\"", filtered)
        self.assertIn("{{ item.stylist_fullName }}", prices)
        self.assertIn("{{ item.price|intcomma }}", prices)
        self.assertIn("data-price-loading-text=\"{% trans 'Loading prices...' %}\"", listing)
        self.assertIn("data-price-error-text=\"{% trans 'Unable to load the price list.' %}\"", listing)
        self.assertIn("modalBody.firstElementChild.textContent = modal.dataset.priceLoadingText", listing)
        self.assertIn("modalBody.firstElementChild.textContent = modal.dataset.priceErrorText", listing)
        self.assertIn("modalBody.innerHTML = await response.text();", listing)
        self.assertNotIn("modalBody.innerHTML = trigger.dataset.serviceName", listing)

    def test_partial_service_list_and_empty_prices_render_per_language(self):
        service = SimpleNamespace(
            id=25,
            get_absolute_url=lambda: "/services/25/",
            service_image=None,
            service_name="Signature wash",
            duration_minutes=60,
            public_service_groups=[],
            public_avg_score=0,
        )
        expected = {
            "fa": ("قیمت‌ها", "هنوز متخصص فعالی"),
            "en": ("Prices", "No active professionals"),
            "ar": ("الأسعار", "لا يوجد مختصون"),
        }
        for language, (price_label, empty_label) in expected.items():
            with self.subTest(language=language):
                with translation.override(language):
                    listing = render_to_string(
                        "services/partials/filtered_services.html",
                        {"services": [service]},
                    )
                    prices = render_to_string(
                        "services/partials/priceList.html",
                        {"service_price_list": []},
                    )
                self.assertIn("Signature wash", listing)
                self.assertIn(price_label, listing)
                self.assertIn(empty_label, prices)
                self.assertIn("q_id=25", listing)

    def test_service_detail_and_profile_preserve_business_data_and_book_paths(self):
        detail = self.source("templates/services/service_detail.html")
        profile = self.source("templates/pages/salon_stylist_profile.html")
        self.assertIn("{{ service.service_name }}", detail)
        self.assertIn("{{ service.summery_description|default:service_summary_fallback }}", detail)
        self.assertIn("{% blocktrans with duration=service.duration_minutes %}", detail)
        self.assertIn("q_id={{ service.id }}", detail)
        self.assertIn("{{ salon.min_price|floatformat:0|intcomma }}", detail)
        self.assertIn("{{ stylist.professional_display_name }}", profile)
        self.assertIn("{{ item.service.service_name }}", profile)
        self.assertIn("{{ stylist.resume_summary|default:stylist.description|default:professional_bio_fallback }}", profile)
        self.assertIn("href=\"{{ book_with_stylist_url }}\"", profile)
        self.assertIn("{% trans 'Professional at' %}", profile)

    def test_phase3_manual_acceptance_and_production_gate_stay_open(self):
        matrix = json.loads(self.source("docs/globalization/PHASE3_EXIT_MATRIX.json"))
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["production_deployment"], "NOT_PERFORMED")
        self.assertFalse(matrix.get("manual_evidence"))
