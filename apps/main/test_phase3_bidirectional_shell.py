"""Phase 3 slice 3.3: shared RTL/LTR presentation boundary regression guards.

Static source/CSS checks are intentionally distinct from a browser pixel audit.
No database or active external integration is required.
"""

from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template import engines
from django.test import SimpleTestCase

from loomera.globalization.locale import DeploymentLocaleContext


class SharedBidirectionalShellBatchTests(SimpleTestCase):
    @staticmethod
    def _source(path):
        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    @classmethod
    def _css(cls):
        return cls._source("static/css/components/bidirectional_shell.css")

    def test_both_root_shells_load_the_scoped_css_after_existing_switcher_styles(self):
        css_path = "css/components/bidirectional_shell.css"
        self.assertTrue(finders.find(css_path))
        for template in ("templates/base.html", "templates/dashboard_template.html"):
            with self.subTest(template=template):
                source = self._source(template)
                self.assertEqual(source.count(css_path), 1)
                self.assertLess(
                    source.index("css/components/workspace_switcher.css"),
                    source.index(css_path),
                )
                self.assertIn("deployment_locale.direction", source)
                self.assertIn("deployment_locale.language_code", source)

    def test_public_and_partner_root_direction_remains_per_locale(self):
        for path in ("templates/base.html", "templates/dashboard_template.html"):
            line = next(x for x in self._source(path).splitlines() if "<html " in x)
            for language, direction in (("fa", "rtl"), ("ar", "rtl"), ("en", "ltr")):
                with self.subTest(path=path, language=language):
                    rendered = engines["django"].from_string(line).render(
                        {"deployment_locale": DeploymentLocaleContext(
                            language, direction, ("en", "ar", "fa")
                        )}
                    )
                    self.assertIn(f'lang="{language}"', rendered)
                    self.assertIn(f'dir="{direction}"', rendered)
            self.assertIn('lang="fa"', engines["django"].from_string(line).render({}))
            self.assertIn('dir="rtl"', engines["django"].from_string(line).render({}))

    def test_new_shell_overrides_are_ltr_scoped_not_a_global_rtl_rewrite(self):
        css = self._css()
        self.assertIn('html[dir="ltr"]', css)
        self.assertNotIn('html[dir="rtl"]', css)
        self.assertNotIn("!important", css)
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertNotIn("@import", css)
        # No change to stable RTL utility classes or the global Tailwind output.
        self.assertIn(
            "  direction: ltr;",
            self._source("templates/partials/shell/customer_mobile_nav.html"),
        )
        self.assertIn("  direction: rtl;",
                      self._source("templates/partials/dashboard/mobile_nav.html"))

    def test_workspace_popover_uses_logical_alignment_and_keeps_post_forms(self):
        css = self._source("static/css/components/workspace_switcher.css")
        template = self._source("templates/partials/shell/workspace_switcher.html")
        self.assertIn("inset-inline-end: 0;", css)
        self.assertIn("inset-inline: 0.75rem;", css)
        self.assertIn("direction: inherit;", css)
        self.assertIn("text-align: start !important;", css)
        self.assertNotIn("direction: rtl;", css)
        self.assertIn(".lm-workspace-switch__trigger-copy", css)
        self.assertIn("lm-workspace-switch__trigger-copy", template)
        self.assertIn('html[dir="ltr"] .lm-workspace-switch__arrow .fa-arrow-left', css)
        self.assertIn('{% csrf_token %}', template)
        self.assertIn('action="{% url \'accounts:workspace_choose\' %}"', template)
        self.assertIn('data-workspace-option-form', template)
        self.assertIn('data-shell-workspace-switch', template)

    def test_customer_mobile_dock_visual_order_mirrors_without_reordering_routes(self):
        nav = self._source("templates/partials/shell/customer_mobile_nav.html")
        css = self._css()
        self.assertIn("direction: ltr;", nav)  # Persian baseline still intact
        self.assertIn('html[dir="ltr"] .lm-shell-customer-mobile-nav__inner', css)
        self.assertIn("  direction: rtl;", css)
        self.assertEqual(nav.count('role="listitem"'), 5)
        for route in (
            "accounts:customerProfile",
            "articles:magazine_home",
            "orders:appointments",
            "search:search_page",
            "salons:show_salons",
        ):
            self.assertIn(route, nav)
        self.assertIn('aria-current="page"', nav)
        self.assertIn("data-shell-nav", nav)

    def test_dashboard_sidebar_and_topbar_support_both_expanded_collapsed_offsets(self):
        css = self._css()
        js = self._source("static/js/pages/dashboard_layout.js")
        template = self._source("templates/dashboard_template.html")
        sidebar = self._source("templates/partials/dashboard/sidebar.html")
        navbar = self._source("templates/partials/dashboard/navbar.html")
        self.assertIn('data-dashboard-content', template)
        self.assertIn('data-dashboard-sidebar', sidebar)
        self.assertIn('data-dashboard-topbar', navbar)
        self.assertIn('html[dir="ltr"] [data-dashboard-sidebar]', css)
        self.assertIn('[data-dashboard-sidebar].translate-x-full', css)
        self.assertIn('transform: translateX(-100%);', css)
        self.assertIn('padding-left: 22rem;', css)
        self.assertIn('padding-left: 6rem;', css)
        self.assertIn('left: 22rem;', css)
        self.assertIn('left: 6rem;', css)
        for token in (
            'lg:pr-[22rem]',
            'lg:pr-24',
            'lg:right-[22rem]',
            'lg:right-24',
            'translate-x-full',
            'translate-x-0',
        ):
            self.assertIn(token, js)
        self.assertIn('[class~="lg:pr-24"]', css)
        self.assertIn('[class~="lg:right-24"]', css)
        self.assertIn("transition-property: left;", css)

    def test_sidebar_controls_and_tooltips_mirror_without_changing_hooks(self):
        css = self._css()
        sidebar = self._source("templates/partials/dashboard/sidebar.html")
        for selector in (
            "[data-sidebar-collapse]",
            "[data-sidebar-close]",
            "[data-sidebar-collapsed-tooltip]",
            "[data-sidebar-collapse-icon]",
        ):
            self.assertIn(selector, css)
            self.assertIn(selector[1:-1], sidebar)
        self.assertIn('data-sidebar-state="expanded"', sidebar)
        self.assertIn("data-sidebar-close", sidebar)
        self.assertIn("data-sidebar-collapse", sidebar)

    def test_partner_mobile_notch_and_create_control_have_ltr_mirror(self):
        css = self._css()
        nav = self._source("templates/partials/dashboard/mobile_nav.html")
        self.assertIn("direction: ltr;", nav)
        for selector in (
            ".lm-partner-mobile-nav__surface",
            ".lm-partner-mobile-nav__surface::before",
            ".lm-partner-mobile-nav__surface::after",
            ".lm-partner-mobile-nav__create-root",
            ".lm-partner-float-menu--create",
        ):
            self.assertIn('html[dir="ltr"] ' + selector, css)
            self.assertIn(selector, nav)
        self.assertIn("radial-gradient(circle 38px at 42px 0", css)
        self.assertIn("radial-gradient(circle 36px at 39px 0", css)
        self.assertIn("@media (max-width: 374px)", css)
        self.assertIn("data-mobile-create-root", nav)

    def test_shared_form_errors_use_flow_relative_text_without_numeric_changes(self):
        css = self._css()
        self.assertIn(".lm-field-label", css)
        self.assertIn(".lm-field-error", css)
        self.assertIn(".lm-form-error", css)
        self.assertIn("text-align: start;", css)
        self.assertNotIn('input[type="tel"]', css)
        self.assertNotIn("input[name*=amount]", css)
        legacy = self._source("static/css/loomera-brand.css")
        self.assertIn('input[type="tel"]', legacy)
        self.assertIn("direction: ltr;", legacy)
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertEqual(settings.LOOMERA_DEFAULT_CALENDAR, "jalali")
