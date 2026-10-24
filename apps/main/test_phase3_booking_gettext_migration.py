"""Phase 3.20: deterministic and fail-closed gettext migration preparation.

The script under test generates reviewable PO text only. It is explicitly
*not* a production catalog edit: compiled .mo files remain unchanged until
the reviewed six-artifact migration can be committed atomically.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from loomera.globalization.booking_flash_catalog_migration import (
    LANGUAGES,
    preview_booking_gettext_appendix,
)
from loomera.globalization.booking_flash_messages import BOOKING_FLASH_MESSAGES


class BookingGettextMigrationPreviewTests(SimpleTestCase):
    @staticmethod
    def source(language):
        return (Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES" /
                "django.po").read_text(encoding="utf-8")

    def test_three_languages_generate_all_fourteen_exact_catalog_entries(self):
        self.assertEqual(LANGUAGES, ("fa", "en", "ar"))
        for language in LANGUAGES:
            with self.subTest(language=language):
                appendix = preview_booking_gettext_appendix(language, self.source(language))
                ids = re.findall(r'(?m)^msgid ("[^"\n]*")$', appendix)
                values = re.findall(r'(?m)^msgstr ("[^"\n]*")$', appendix)
                self.assertEqual(len(ids), 14)
                self.assertEqual(len(values), 14)
                self.assertEqual(
                    [json.loads(msgid) for msgid in ids],
                    [record[1] for record in BOOKING_FLASH_MESSAGES],
                )
                index = {"fa": 1, "en": 2, "ar": 3}[language]
                self.assertEqual(
                    [json.loads(msgstr) for msgstr in values],
                    [record[index] for record in BOOKING_FLASH_MESSAGES],
                )
                self.assertEqual(
                    appendix.count("#: loomera/globalization/booking_flash_messages.py"),
                    14,
                )

    def test_appendices_are_deterministic_and_preserve_existing_catalog_bytes(self):
        for language in LANGUAGES:
            original = self.source(language)
            with self.subTest(language=language):
                first = preview_booking_gettext_appendix(language, original)
                self.assertEqual(
                    first, preview_booking_gettext_appendix(language, original)
                )
                self.assertTrue(first.startswith("\n#: "))
                self.assertNotIn("booking #", first)
                self.assertTrue(original.startswith(
                    "# Phase 3 system-owned navigation messages."
                ))
                self.assertEqual(self.source(language), original)

    def test_fail_closed_on_repeated_keys_in_catalog(self):
        for language in LANGUAGES:
            original = self.source(language)
            appendix = preview_booking_gettext_appendix(language, original)
            with self.subTest(language=language), self.assertRaises(ValueError):
                preview_booking_gettext_appendix(language, original + appendix)

    def test_fail_closed_on_wrong_header_unsupported_language_and_nontext(self):
        for language in ("de", "", "FA", "en-US"):
            with self.subTest(language=language), self.assertRaises(ValueError):
                preview_booking_gettext_appendix(language, self.source("en"))
        with self.assertRaises(ValueError):
            preview_booking_gettext_appendix("ar", self.source("en"))
        with self.assertRaises(TypeError):
            preview_booking_gettext_appendix("fa", b"untrusted catalog")

    def test_only_static_reviewed_literal_messages_are_in_preview(self):
        appendix = preview_booking_gettext_appendix("en", self.source("en"))
        for entry in (
            "09123456789", "user@example.com", "discount_code",
            "OTP=12345678", "payment_id", "provider trace",
        ):
            self.assertNotIn(entry, appendix)
        self.assertNotIn("msgid_plural", appendix)
        self.assertNotIn("msgctxt", appendix)
        for tone, persian, english, arabic in BOOKING_FLASH_MESSAGES:
            self.assertIn(tone, {"error", "success", "info"})
            for text in (persian, english, arabic):
                self.assertLessEqual(len(text), 300)
                self.assertNotIn("{", text)
                self.assertNotIn("<", text)
                self.assertNotIn("\n", text)

    def test_existing_compiled_catalogs_are_present_but_not_rebuilt_by_preview(self):
        for language in LANGUAGES:
            folder = Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES"
            self.assertTrue((folder / "django.mo").is_file())
            self.assertTrue((folder / "django.po").is_file())
            original = (folder / "django.mo").read_bytes()
            preview_booking_gettext_appendix(language, self.source(language))
            self.assertEqual((folder / "django.mo").read_bytes(), original)

    def test_runtime_stays_on_reviewed_table_until_po_and_mo_migrate_together(self):
        src = (Path(settings.BASE_DIR) /
               "apps/main/templatetags/ui_message_extras.py").read_text(encoding="utf-8")
        self.assertIn("trusted_booking_flash(raw, tone, language)", src)
        self.assertIn("return approved_booking", src)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
