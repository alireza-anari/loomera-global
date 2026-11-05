# Phase 4.3a — Public Search Suggestion and Popup Sink Safety

**Status:** security prerequisite; this is not completion of Phase 4 localization or Phase 3 release acceptance.

## Scope

Merchant-authored service, salon, neighborhood, address and user search text, plus remote JSON suggestion labels, now enter the public autocomplete and search-filter DOM through textContent. Search active-filter chips and selected-service labels retain their existing events and classes, without raw string-to-HTML interpolation.

The map popup still uses a static HTML skeleton. Human values remain escaped, while image/detail URLs accept only root-relative or HTTP(S) schemes. Executable, data, protocol-relative, and control-character URLs fail closed.

The Django-rendered payload.html search-results fragment is intentionally separate: it comes from a server-side escaped template and is not a generic sink for arbitrary suggestion JSON.

## Verification and boundaries

Node tests execute real source helpers with hostile API/merchant content and URL schemes, and verify valid route and image preservation. Fast checks runs the suite and module syntax checks.

Full interactive search localization, SEO, and salon detail remain later Phase 4 work. No gettext, persisted data, search query keys, booking/payment, auth, provider, source-repository or Production change. Phase 3 manual visual/keyboard/screen-reader/zoom gates and release approval remain open.
