"""Phase 4.3b merge gate: reviewed source and compiled locale parity."""
import json
import struct
from gettext import translation
from pathlib import Path
from django.test import SimpleTestCase
from django.template.loader import get_template
from django.utils import translation as active_translation
from types import SimpleNamespace
from apps.search.utils import SearchFilters, build_search_summary

ROOT = Path(__file__).resolve().parents[2]

class Phase4SearchLocaleTests(SimpleTestCase):
    def test_search_templates_compile(self):
        for name in (
            "partials/search/search_topbar.html",
            "partials/search/search_filters_sheet.html",
            "partials/search/search_filter_fullscreen.html",
            "partials/search/search_locale_messages.html",
            "search/search_results.html",
            "components/categories.html",
        ):
            get_template(name)

    def test_reviewed_catalogs_require_compiled_parity(self):
        ledger = json.loads((ROOT / "docs/globalization/PHASE4_3B_MESSAGE_REVIEW.json").read_text())
        self.assertEqual(len(ledger["reviewed_messages"]), 130)
        for lang in ("fa", "en", "ar"):
            po = (ROOT / "locale" / lang / "LC_MESSAGES/django.po").read_text(encoding="utf-8")
            data = (ROOT / "locale" / lang / "LC_MESSAGES/django.mo").read_bytes()
            self.assertEqual(struct.unpack_from("<I", data, 8)[0], 904)
            catalog = translation("django", localedir=str(ROOT / "locale"), languages=[lang])
            for row in ledger["reviewed_messages"]:
                self.assertIn("msgid " + json.dumps(row["msgid"], ensure_ascii=False), po)
                self.assertEqual(catalog.gettext(row["msgid"]), row[lang])

    def test_initial_and_ajax_summary_messages_follow_request_language(self):
        filters = SearchFilters(
            location="نزدیک من",
            period="morning",
            min_price=200000,
            min_rating=4.5,
            has_discount=True,
        )
        service = SimpleNamespace(service_name="User-supplied service")
        expected = {
            "fa": ("نزدیک من", "صبح", "امتیاز از 4.5"),
            "en": ("Near me", "Morning", "Rating 4.5+"),
            "ar": ("بالقرب مني", "الصباح", "التقييم 4.5"),
        }
        for lang, fragments in expected.items():
            with self.subTest(lang=lang), active_translation.override(lang):
                summary = build_search_summary(filters, [service], None)
                for fragment in fragments:
                    self.assertIn(fragment, summary)
                self.assertIn("User-supplied service", summary)
        with active_translation.override("en"):
            self.assertEqual(
                build_search_summary(SearchFilters(), [], None),
                "Search for salons, services, or areas...",
            )
