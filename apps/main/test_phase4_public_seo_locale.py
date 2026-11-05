"""Phase 4.3d — localized, deployment-branded public SEO metadata."""
import html
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


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = (
    "base.html",
    "pages/home.html",
    "pages/show_salons.html",
    "services/all_services.html",
    "articles/magazine_home.html",
    "pages/salon_stylist_profile.html",
)


def render_metadata(path, block, language, context):
    source = (ROOT / "templates" / path).read_text(encoding="utf-8")
    match = re.search(
        r"{% block " + block + r" %}(.*?){% endblock %}",
        source,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("Missing " + block + " in " + path)
    with translation.override(language):
        return Template("{% load i18n %}" + match.group(1)).render(Context(context))


class Phase4PublicSeoLocaleTests(SimpleTestCase):
    def test_native_templates_compile_and_merchant_seo_remains_untouched(self):
        for path in TEMPLATES:
            with self.subTest(path=path):
                get_template(path)
                self.assertIn("{% load i18n %}", (ROOT / "templates" / path).read_text())
        for path, prefix in (
            ("pages/detail_salon.html", "salon"),
            ("services/service_detail.html", "service"),
        ):
            source = (ROOT / "templates" / path).read_text(encoding="utf-8")
            for field in ("title", "description"):
                self.assertIn(
                    "{{ " + prefix + ".effective_seo_" + field + " }}", source
                )

    def test_default_shared_metadata_preserves_fa_and_escapes_buyer_brand(self):
        reviewed = json.loads(
            (ROOT / "docs/globalization/PHASE4_3D_MESSAGE_REVIEW.json").read_text()
        )["reviewed_messages"]
        msgid, social_id = reviewed[0]["msgid"], reviewed[1]["msgid"]
        brand = 'North & <Markets> "Studio"'
        context = {"deployment_brand": SimpleNamespace(display_name=brand)}
        for lang in ("fa", "en", "ar"):
            with self.subTest(lang=lang):
                catalog = load_catalog("django", localedir=str(ROOT / "locale"), languages=[lang])
                description = render_metadata("base.html", "meta_description", lang, context)
                self.assertEqual(
                    description,
                    catalog.gettext(msgid) % {"brand": html.escape(brand, quote=True)},
                )
                for block in ("og_description", "twitter_description"):
                    self.assertEqual(
                        render_metadata("base.html", block, lang, context),
                        catalog.gettext(social_id),
                    )
                self.assertNotIn("<Markets>", description)
        self.assertEqual(
            render_metadata("base.html", "meta_description", "fa", context),
            html.escape(brand) +
            "، پلتفرم انتخاب و رزرو خدمات زیبایی، aesthetic treatments، ماساژ و wellness با تجربه‌ای آرام، دقیق و قابل‌اعتماد.",
        )

    def test_home_and_salons_directory_titles_are_locale_correct(self):
        brand = SimpleNamespace(display_name="North & Co", display_name_fa="برند فارسی")
        for lang in ("fa", "en", "ar"):
            context = {
                "deployment_brand": brand,
                "deployment_locale": SimpleNamespace(language_code=lang),
            }
            with self.subTest(lang=lang), translation.override(lang):
                expected_brand = "برند فارسی" if lang == "fa" else "North &amp; Co"
                self.assertEqual(
                    render_metadata("pages/home.html", "title", lang, context),
                    expected_brand + " | " + translation.gettext("Beauty, made simpler"),
                )
                self.assertEqual(
                    render_metadata("pages/show_salons.html", "title", lang, context),
                    translation.gettext("Discover salons"),
                )

    def test_service_directory_fallback_is_localized_but_curated_seo_is_not(self):
        brand = SimpleNamespace(display_name="Studio & Spa")
        curated = SimpleNamespace(
            effective_seo_title="Author's curated <title>",
            effective_seo_description="Author & original <description>",
        )
        for lang in ("fa", "en", "ar"):
            with self.subTest(lang=lang), translation.override(lang):
                general = {"deployment_brand": brand, "selected_group": None}
                self.assertEqual(
                    render_metadata("services/all_services.html", "title", lang, general),
                    translation.gettext("All beauty services") + " | Studio &amp; Spa",
                )
                self.assertEqual(
                    render_metadata("services/all_services.html", "meta_description", lang, general),
                    translation.gettext("Browse beauty services and choose what suits you."),
                )
                owned = {"deployment_brand": brand, "selected_group": curated}
                self.assertEqual(
                    render_metadata("services/all_services.html", "title", lang, owned),
                    html.escape(curated.effective_seo_title),
                )
                self.assertEqual(
                    render_metadata("services/all_services.html", "meta_description", lang, owned),
                    html.escape(curated.effective_seo_description),
                )

    def test_magazine_title_description_use_right_brand_for_each_language(self):
        rows = json.loads(
            (ROOT / "docs/globalization/PHASE4_3D_MESSAGE_REVIEW.json").read_text()
        )["reviewed_messages"]
        title_id, description_id = rows[5]["msgid"], rows[6]["msgid"]
        context_brand = SimpleNamespace(
            display_name="Buyer & Co",
            display_name_fa="خریدار فارسی",
        )
        for lang in ("fa", "en", "ar"):
            context = {
                "deployment_brand": context_brand,
                "deployment_locale": SimpleNamespace(language_code=lang),
            }
            with self.subTest(lang=lang), translation.override(lang):
                expected_brand = "خریدار فارسی" if lang == "fa" else "Buyer &amp; Co"
                for block, key in (("title", title_id), ("meta_description", description_id)):
                    rendered = render_metadata(
                        "articles/magazine_home.html", block, lang, context
                    )
                    self.assertEqual(
                        rendered,
                        translation.gettext(key) % {"brand": expected_brand},
                    )
        title_fa = render_metadata(
            "articles/magazine_home.html", "title", "fa",
            {"deployment_brand": context_brand,
             "deployment_locale": SimpleNamespace(language_code="fa")},
        )
        self.assertEqual(
            title_fa,
            "مجله خریدار فارسی | آموزش زیبایی، مقالات متخصصان و استوری مجموعه‌ها",
        )

    def test_professional_description_preserves_names_and_escapes_markup(self):
        stylist = SimpleNamespace(professional_display_name="Alice & <Pro>")
        salon = SimpleNamespace(salon_name="Studio & <Home>")
        msgid = json.loads(
            (ROOT / "docs/globalization/PHASE4_3D_MESSAGE_REVIEW.json").read_text()
        )["reviewed_messages"][7]["msgid"]
        for lang in ("fa", "en", "ar"):
            with self.subTest(lang=lang), translation.override(lang):
                result = render_metadata(
                    "pages/salon_stylist_profile.html", "meta_description", lang,
                    {"stylist": stylist, "salon": salon},
                )
                self.assertEqual(
                    result,
                    translation.gettext(msgid) % {
                        "professional": html.escape(stylist.professional_display_name),
                        "salon": html.escape(salon.salon_name),
                    },
                )
                self.assertNotIn("<Pro>", result)
                self.assertNotIn("<Home>", result)

    def test_eight_reviewed_native_catalog_messages_preserve_compiled_parity(self):
        ledger = json.loads(
            (ROOT / "docs/globalization/PHASE4_3D_MESSAGE_REVIEW.json").read_text()
        )
        rows = ledger["reviewed_messages"]
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({r["msgid"] for r in rows}), 8)
        for lang in ("fa", "en", "ar"):
            with self.subTest(lang=lang):
                po = (ROOT / f"locale/{lang}/LC_MESSAGES/django.po").read_text(encoding="utf-8")
                mo = (ROOT / f"locale/{lang}/LC_MESSAGES/django.mo").read_bytes()
                self.assertEqual(struct.unpack_from("<I", mo, 0)[0], 0x950412de)
                self.assertEqual(struct.unpack_from("<I", mo, 8)[0], 904)
                catalog = load_catalog("django", localedir=str(ROOT / "locale"), languages=[lang])
                for row in rows:
                    self.assertIn(
                        "msgid " + json.dumps(row["msgid"], ensure_ascii=False),
                        po,
                    )
                    self.assertEqual(catalog.gettext(row["msgid"]), row[lang])

    def test_untranslated_help_legal_content_and_manual_release_gate_remain_out_of_scope(self):
        source = (ROOT / "templates/help_center/home.html").read_text(encoding="utf-8")
        self.assertIn("مرکز راهنمای {{ deployment_brand.display_name_fa }}", source)
        matrix = json.loads(
            (ROOT / "docs/globalization/PHASE3_EXIT_MATRIX.json").read_text()
        )
        self.assertEqual(matrix["release_gate"], "BLOCKED_MANUAL_ACCEPTANCE")
        self.assertEqual(matrix["production_deployment"], "NOT_PERFORMED")
