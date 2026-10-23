"""Phase 3.12: change-password LTR presentation regression guards.

This suite checks source/markup contracts, not visual browser acceptance.
"""
from pathlib import Path
from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase


class ChangePasswordDirectionalLayoutTests(SimpleTestCase):
    @staticmethod
    def source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def test_bridge_loaded_in_page_head_without_affecting_shared_shell(self):
        source = self.source("templates/accounts/change_password.html")
        self.assertEqual(source.count("css/components/bidirectional_change_password.css"), 1)
        self.assertIn("{% block head %}", source)
        self.assertTrue(finders.find("css/components/bidirectional_change_password.css"))
        self.assertIn('{% extends "base.html" %}', source)

    def test_all_three_password_fields_have_direction_safe_hooks(self):
        source = self.source("templates/accounts/change_password.html")
        self.assertEqual(source.count('class="relative lm-password-field"'), 3)
        self.assertEqual(source.count("lm-password-input w-full"), 3)
        self.assertEqual(source.count("lm-password-field-icon absolute"), 3)
        self.assertEqual(source.count("lm-password-toggle absolute"), 3)
        self.assertEqual(source.count("lm-password-back-icon"), 2)
        for target in ("currentPassword", "newPassword", "confirmPassword"):
            self.assertIn(f'data-target="{target}"', source)
            self.assertIn(f'aria-controls="{target}"', source)

    def test_ltr_rules_mirror_only_presentation_not_rtl_defaults(self):
        css = self.source("static/css/components/bidirectional_change_password.css")
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn('html[dir="ltr"] .lm-password-field-icon', css)
        self.assertIn('html[dir="ltr"] .lm-password-toggle', css)
        self.assertIn("right: auto;", css)
        self.assertIn("left: auto;", css)
        self.assertIn("transform: scaleX(-1);", css)
        self.assertNotIn('html[dir="rtl"]', css)
        self.assertNotIn("!important", css)
        self.assertNotIn("direction: rtl", css)

    def test_password_security_and_client_behavior_unchanged(self):
        source = self.source("templates/accounts/change_password.html")
        self.assertIn("{% csrf_token %}", source)
        self.assertIn('id="changePasswordForm" method="post"', source)
        for name in ("current_password", "password1", "password2"):
            self.assertIn(f'name="{name}"', source)
        self.assertIn('{% if requires_current_password %}', source)
        self.assertIn('autocomplete="current-password"', source)
        self.assertEqual(source.count('autocomplete="new-password"'), 2)
        self.assertIn('input.setAttribute("type", shouldShow ? "text" : "password")', source)
        self.assertIn("if (password1 !== password2)", source)
        self.assertIn("if (password1.length < 8)", source)
        self.assertIn('window.LoomeraFeedback?.error?', source)

    def test_original_rtl_utility_classes_remain_in_markup(self):
        source = self.source("templates/accounts/change_password.html")
        self.assertEqual(source.count("right-4 top-1/2"), 3)
        self.assertEqual(source.count("absolute left-2 top-1/2"), 3)
        self.assertEqual(source.count("pr-11 pl-12"), 3)
        self.assertIn('dir="ltr"', source)  # phone number badge
