"""Phase 3.21: atomic fa/en/ar booking PO+MO runtime migration checks."""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import translation

from loomera.globalization.booking_flash_catalog_migration import (
    LANGUAGES, inspect_booking_gettext_catalog,
)
from loomera.globalization.booking_flash_messages import BOOKING_FLASH_MSGIDS


class BookingGettextMigrationTests(SimpleTestCase):
    @staticmethod
    def directory(language):
        return Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES"

    def tearDown(self):
        translation.deactivate_all()

    def test_exact_fourteen_booking_messages_exist_in_each_po(self):
        self.assertEqual(LANGUAGES, ("fa", "en", "ar"))
        all_msgids = tuple(msg for values in BOOKING_FLASH_MSGIDS.values() for msg in values)
        self.assertEqual(len(all_msgids), 14)
        self.assertEqual(len(set(all_msgids)), 14)
        for language in LANGUAGES:
            with self.subTest(language=language):
                content = (self.directory(language) / "django.po").read_text(encoding="utf-8")
                approved = inspect_booking_gettext_catalog(language, content)
                self.assertEqual(set(approved), set(all_msgids))
                for msgid in all_msgids:
                    self.assertTrue(approved[msgid])
                    self.assertIn('msgid "' + msgid + '"', content)
                    self.assertEqual(content.count(
                        '#: loomera/globalization/booking_flash_messages.py'
                    ), 14)

    def test_all_compiled_mo_translations_equal_reviewed_po_entries(self):
        for language in LANGUAGES:
            folder = self.directory(language)
            self.assertTrue((folder / "django.mo").is_file())
            self.assertGreater((folder / "django.mo").stat().st_size, 1000)
            expected = inspect_booking_gettext_catalog(
                language, (folder / "django.po").read_text(encoding="utf-8")
            )
            with translation.override(language):
                for msgid, localized in expected.items():
                    with self.subTest(lang=language, msgid=msgid):
                        self.assertEqual(translation.gettext(msgid), localized)

    def test_existing_compiled_otp_pluralization_survives_migration(self):
        source = "کد وارد شده اشتباه است. %(count)d تلاش دیگر باقی مانده است."
        plural = "کد وارد شده اشتباه است. %(count)d تلاش دیگر باقی مانده‌اند."
        for language in LANGUAGES:
            with translation.override(language):
                one = translation.ngettext(source, plural, 1)
                many = translation.ngettext(source, plural, 3)
                self.assertTrue(one)
                self.assertTrue(many)
                self.assertNotIn("msgstr", one)
                self.assertNotIn("msgstr", many)

    def test_bad_header_unsupported_locale_and_bytes_fail_closed(self):
        en = (self.directory("en") / "django.po").read_text(encoding="utf-8")
        for language in ("de", "EN", "", "en-GB"):
            with self.subTest(lang=language), self.assertRaises(ValueError):
                inspect_booking_gettext_catalog(language, en)
        with self.assertRaises(ValueError):
            inspect_booking_gettext_catalog("ar", en)
        with self.assertRaises(TypeError):
            inspect_booking_gettext_catalog("en", b"untrusted")

    def test_missing_duplicate_and_blank_catalog_entries_are_rejected(self):
        en = (self.directory("en") / "django.po").read_text(encoding="utf-8")
        source = next(iter(BOOKING_FLASH_MSGIDS["error"]))
        entry = 'msgid "' + source + '"'
        block = en[en.index(entry):]
        block = block[:block.index("\n\n")]
        for broken in (
            en.replace(entry, 'msgid "Missing approved entry"', 1),
            en + "\n" + block + "\n",
            en.replace(block.split("msgstr ")[-1], '""', 1),
        ):
            with self.assertRaises(ValueError):
                inspect_booking_gettext_catalog("en", broken)

    def test_audit_is_deterministic_read_only_and_not_runtime_template(self):
        en = (self.directory("en") / "django.po").read_text(encoding="utf-8")
        before = (self.directory("en") / "django.mo").read_bytes()
        x = inspect_booking_gettext_catalog("en", en)
        self.assertEqual(x, inspect_booking_gettext_catalog("en", en))
        self.assertEqual((self.directory("en") / "django.mo").read_bytes(), before)
        ui = (Path(settings.BASE_DIR) /
              "apps/main/templatetags/ui_message_extras.py").read_text(encoding="utf-8")
        self.assertIn("BOOKING_FLASH_MSGIDS.get(tone, ())", ui)
        self.assertNotIn("trusted_booking_flash(", ui)
        self.assertNotIn("return approved_booking", ui)

    def test_fa_deployment_defaults_and_existing_browser_catalog_remain(self):
        from loomera.globalization.interactive_messages import MESSAGE_IDS
        self.assertEqual(len(MESSAGE_IDS), 41)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
        self.assertEqual(settings.LOOMERA_DEFAULT_CURRENCY, "")
