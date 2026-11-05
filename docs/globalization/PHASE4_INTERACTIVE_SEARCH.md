# Phase 4.3b — Interactive Public Search Localization

Status: Phase 4.3b merged as PR #118 (main SHA cfe3f3d5b04e65b8064e72179c9b071ea8ab252a); exact-head and post-merge CI passed. This is not a Production release, and manual acceptance remains blocked.

The public search toolbar, result/filters sheet, full filter dialog, category cards, result cards, map fallback and map popup now use native Django gettext tags for application-owned UI copy. Dynamic status and map labels are read from trusted, server-rendered locale attributes rather than embedded Persian literals.

The review ledger contains 130 keys; 17 reuse existing translations and 113 have been added to the native fa/en/ar PO files. The compiled MO catalogs have been regenerated to 890 entries each; final CI must verify exact source/compiled parity and all prior mappings.

Preserved: all selected filter IDs, query parameters, booking links, price amounts/Toman semantics, Jalali date values, backend availability data, merchant-authored text, map provider, user authorization, and the Persian internal "نزدیک من" geolocation marker. Locale-aware map direction and search-panel positioning are cosmetic only.

Phase 4.3c follows up on the search-only SEO title/description and backend-authored availability status labels, with no change to booking eligibility. SEO across other public pages remains a separate scope. No Production deployment or source-repository change. Phase 3 remains BLOCKED_MANUAL_ACCEPTANCE, with manual screen-reader, zoom, keyboard and visual evidence still outstanding.

**Phase 4.3c gate:** six additional reviewed messages and 896-entry catalogs per locale, application-owned availability label tests, brand-safe translated search SEO, exact-head CI, and independent diff review. Manual release gate remains separate.
