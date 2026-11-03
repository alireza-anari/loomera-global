import re
from gettext import translation as load_gettext_catalog
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils import translation


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DISCOVERY_TEMPLATES = (
    "templates/pages/home.html",
    "templates/pages/show_salons.html",
    "templates/components/salon_card.html",
    "templates/components/book_again_card.html",
)
TRANS_TAG = re.compile(r"""{%\s*trans\s+(?P<quote>["'])(?P<message>.*?)(?P=quote)\s*%}""")
PERSIAN_OR_ARABIC = re.compile(r"[\u0600-\u06FF]")


class Phase4PublicDiscoveryLocaleTests(SimpleTestCase):
    def _template_source(self, relative_path):
        return (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def test_every_public_discovery_trans_message_has_compiled_fa_en_ar_copy(self):
        for relative_path in PUBLIC_DISCOVERY_TEMPLATES:
            with self.subTest(template=relative_path):
                source = self._template_source(relative_path)
                self.assertIn("{% load i18n %}", source)
                messages = sorted({match.group("message") for match in TRANS_TAG.finditer(source)})
                self.assertTrue(messages)

                for language in ("fa", "en", "ar"):
                    with self.subTest(template=relative_path, language=language):
                        catalog = load_gettext_catalog(
                            "django",
                            localedir=str(REPO_ROOT / "locale"),
                            languages=[language],
                        )
                        for message in messages:
                            self.assertIn(message, catalog._catalog)
                            translated = catalog.gettext(message)
                            if language == "en":
                                self.assertEqual(translated, message)
                            else:
                                self.assertNotEqual(
                                    translated,
                                    message,
                                    f"Missing {language} translation for {message!r}",
                                )

    def test_dynamic_brand_video_title_has_compiled_fa_en_ar_translation(self):
        message = "Introducing %(brand)s and how the platform works"
        expected = {
            "fa": ("لومرا", "معرفی لومرا و نحوه کار با پلتفرم"),
            "en": ("Loomera", "Introducing Loomera and how the platform works"),
            "ar": ("Loomera", "تعرّف على Loomera وكيفية عمل المنصة"),
        }

        for language, (brand, expected_title) in expected.items():
            with self.subTest(language=language):
                catalog = load_gettext_catalog(
                    "django",
                    localedir=str(REPO_ROOT / "locale"),
                    languages=[language],
                )
                self.assertIn(message, catalog._catalog)
                rendered = catalog.gettext(message) % {"brand": brand}
                self.assertEqual(rendered, expected_title)

    def test_public_discovery_body_has_no_untranslated_persian_literals(self):
        for relative_path in PUBLIC_DISCOVERY_TEMPLATES:
            with self.subTest(template=relative_path):
                source = self._template_source(relative_path)
                source = re.sub(
                    r"{%\s*block\s+title\s*%}.*?{%\s*endblock\s*%}",
                    "",
                    source,
                    flags=re.DOTALL,
                )
                self.assertIsNone(PERSIAN_OR_ARABIC.search(source))

    def test_salon_card_localizes_ui_but_preserves_salon_owned_content(self):
        salon = SimpleNamespace(
            get_absolute_url=lambda: "/salons/atelier-north/",
            card_image_url="",
            salon_name="Atelier North",
            card_location="Westend",
            card_rating=4.8,
            card_discount_label="",
            card_reviews_count=12,
            min_price=125,
        )
        expected = {
            "en": ("View and book", "Westend"),
            "fa": ("مشاهده و رزرو", "Westend"),
            "ar": ("عرض وحجز", "Westend"),
        }

        for language, (action_label, location) in expected.items():
            with self.subTest(language=language):
                with translation.override(language):
                    html = render_to_string(
                        "components/salon_card.html",
                        {"salon": salon},
                    )
                self.assertIn("Atelier North", html)
                self.assertIn(location, html)
                self.assertIn(action_label, html)

    def test_book_again_card_localizes_fallbacks_and_preserves_business_content(self):
        salon = SimpleNamespace(
            get_absolute_url=lambda: "/salons/atelier-north/",
            salon_name="Atelier North",
            card_image_url="",
            banner_image=None,
            card_location="",
            neighborhood=None,
            address="",
        )
        service = SimpleNamespace(service_name="Signature cut", price=125)
        item = SimpleNamespace(
            salon=salon,
            service=service,
            date=None,
            time=None,
            stylist_name="",
            stylist=None,
            price=125,
            order=None,
        )
        expected = {
            "en": (
                "Previous booking",
                "Previous service",
                "Location not provided",
                "Date not recorded",
                "Time not recorded",
                "Professional not recorded",
                "Previous amount",
                "Toman",
            ),
            "fa": (
                "رزرو قبلی",
                "خدمت قبلی",
                "موقعیت ثبت نشده",
                "تاریخ ثبت نشده",
                "ساعت ثبت نشده",
                "متخصص ثبت نشده",
                "مبلغ قبلی",
                "تومان",
            ),
            "ar": (
                "الحجز السابق",
                "الخدمة السابقة",
                "الموقع غير محدد",
                "التاريخ غير مسجل",
                "الوقت غير مسجل",
                "المختص غير مسجل",
                "المبلغ السابق",
                "تومان",
            ),
        }

        for language, labels in expected.items():
            with self.subTest(language=language):
                with translation.override(language):
                    html = render_to_string(
                        "components/book_again_card.html",
                        {"item": item},
                    )
                self.assertIn("Atelier North", html)
                self.assertIn("Signature cut", html)
                for label in labels:
                    self.assertIn(label, html)

    def test_jalali_date_filter_and_currency_value_boundary_are_preserved(self):
        book_again = self._template_source(
            "templates/components/book_again_card.html"
        )
        salon_card = self._template_source("templates/components/salon_card.html")
        self.assertIn("{{ item.date|jalali }}", book_again)
        self.assertIn("{{ item.price|intcomma }} {% trans \"Toman\" %}", book_again)
        self.assertIn("{% trans \"Toman\" %}", salon_card)
