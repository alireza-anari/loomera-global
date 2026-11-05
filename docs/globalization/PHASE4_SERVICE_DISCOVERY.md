# Phase 4.2 — Service and Professional Discovery Localization

**Status:** code implementation candidate; not a Phase 3 release acceptance.

## Scope

The service catalogue and public professional discovery templates now use native
fa/en/ar gettext for application-owned UI copy and accessibility labels:

- templates/services/all_services.html: navigation, groups, price modal, feedback
- templates/services/partials/filtered_services.html: service cards and empty state
- templates/services/partials/priceList.html: professional pricing and empty state
- templates/services/service_detail.html: service information and salon discovery
- templates/pages/salon_stylist_profile.html: professional portfolio, reviews and booking entry
- templates/pages/search.html: accessible search region name only

There are **53 reviewed new msgids**, each represented in the three native PO
and compiled MO catalogs; each compiled catalog now has **777 entries**.
The review ledger is PHASE4_2_MESSAGE_REVIEW.json.

The price-list asynchronous loader and error messages are sourced from translated
DOM attributes and written to the page with textContent, not interpolated into HTML.

## Preserved boundaries

- User/merchant-authored service, salon, professional, portfolio, address,
  description and review text is displayed as authored, without machine translation.
- Existing service IDs, search query arguments, URL routing, ordering, prices,
  payment paths and booking POST handlers remain unchanged.
- Current Jalali/calendar, timezone and Toman currency semantics remain unchanged;
  only labels can be translated.
- Existing public SEO title/meta description values stay deferred to the SEO phase.
- Salon detail / its JavaScript booking renderer, interactive search filters/results,
  and authenticated dashboards are **not** in this slice.
- The default deployment locale is **not** changed.
- No Production deployment is performed.

## Validation and release gate

- GitHub Fast checks runs the new database-free template, compiled gettext,
  AJAX-message-sink and immutable business-value regression suite.
- All historic compiled-message count checks update to **777**, with their existing
  translation assertions retained.
- Phase 3 remains **BLOCKED_MANUAL_ACCEPTANCE**: real browser visual, keyboard,
  screen reader, true zoom, and explicit deployment approval are still open.
