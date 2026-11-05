# Phase 4.3c — Search Availability Copy and SEO Metadata

**Status:** Phase 4.3c merged as PR #119 at main SHA 95fe315e5f29b3dc390591e1180c28aebdd283ba; branch and post-merge CI passed. This is not a Production release. Phase 3 manual exit remains BLOCKED_MANUAL_ACCEPTANCE.

## Scope
- Translate first available appointment status with and without a date, and the available appointment fallback, at the **server presentation boundary** using request-active Django gettext.
- Preserve Persian UI messages exactly: `اولین زمان آزاد HH:MM`, `اولین زمان آزاد تاریخ ساعت HH:MM`, `دارای وقت آزاد`, `نوبت آزاد`.
- Preserve date selection, Jalali display, HH:MM, slot filtering, service identity, price, merchant-provided names, booking URL and search API schema.
- Use the same translated `salon.search_available_label` on result cards and as `available_label` in map JSON. Map popup keeps escaping labels as untrusted content.
- Localize the **search page** browser title and meta description using native gettext; resolve brand from `deployment_brand.display_name` without embedding hardcoded brand names.
- Six reviewed message IDs are recorded in `PHASE4_3C_MESSAGE_REVIEW.json`, with fa/en/ar translations. The previously compiled 890-entry catalogs grow to 896, keeping all existing entries and values.
- Add tests for single/multiple-date status, brand substitution and HTML-escaping, map payload propagation, catalog integrity, and existing release gates.

## Explicit exclusions
This does **not** change the notion of available/bookable slots, open-now state, calendar or timezone models, currency/Toman semantics, structured data, redirects, canonical URLs, sitemap strategy, SEO on other pages, or merchant-authored service descriptions. This does not deploy Production and does not modify source repository `alireza-anari/loomera`.

Manual browser visual, real 400% zoom, NVDA/VoiceOver and release-signoff checks are **not** claimed complete.

## Evidence required before merge
CI exact head: new Django and Node tests plus existing backend regressions and Chromium fixture smoke. Confirm the current `main` base, no unrelated files, all old compiled MO messages preserved, and use a SHA-guarded squash merge only after green.
