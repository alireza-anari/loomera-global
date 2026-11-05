# Phase 4.3b — Interactive Public Search Localization

Status: implementation candidate, **not release-ready** until fa/en/ar compiled MO catalogs and CI are verified.

The public search toolbar, result/filters sheet, full filter dialog, category cards, result cards, map fallback and map popup now use native Django gettext tags for application-owned UI copy. Dynamic status and map labels are read from trusted, server-rendered locale attributes rather than embedded Persian literals.

The review ledger contains 130 keys; 17 reuse existing translations and 113 have been added to the native fa/en/ar PO files. The existing compiled MO catalogs still require regeneration and verification at 890 entries each.

Preserved: all selected filter IDs, query parameters, booking links, price amounts/Toman semantics, Jalali date values, backend availability data, merchant-authored text, map provider, user authorization, and the Persian internal "نزدیک من" geolocation marker. Locale-aware map direction and search-panel positioning are cosmetic only.

Deferred: full public SEO localization and the presentation of backend-authored availability labels. No Production deployment or source-repository change. Phase 3 remains BLOCKED_MANUAL_ACCEPTANCE, with manual screen-reader, zoom, keyboard and visual evidence still outstanding.

**Merge gate:** regenerated compiled catalogs, source/catalog parity tests, exact-branch GitHub CI, independent diff review and guarded squash merge. No merge while any item is missing.
