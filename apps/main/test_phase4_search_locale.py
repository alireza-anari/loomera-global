"""Phase 4.3b merge gate: reviewed source and compiled locale parity."""
import json
import struct
from gettext import translation
from pathlib import Path
from django.test import SimpleTestCase
from django.template.loader import get_template

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
            data = (ROOT / "locale" / lang / "LC_MESSAGES/django.mo").read_bytes()
            self.assertEqual(struct.unpack_from("<I", data, 8)[0], 890)
            catalog = translation("django", localedir=str(ROOT / "locale"), languages=[lang])
            for row in ledger["reviewed_messages"]:
                self.assertEqual(catalog.gettext(row["msgid"]), row[lang])
