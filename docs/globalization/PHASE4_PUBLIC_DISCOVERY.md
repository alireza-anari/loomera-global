# Phase 4.1 — Public Home and Discovery Locale Coverage

**Status:** implementation slice; English-first coverage is being expanded incrementally.
This slice does not change the deployment's default locale and does not close
the separate Phase 3 manual acceptance gates.

## Scope

The following public/customer discovery surfaces use native Django gettext
for application-owned copy in fa/en/ar:

- `templates/pages/home.html`
- `templates/pages/show_salons.html`
- `templates/components/salon_card.html`
- `templates/components/book_again_card.html`

The compiled PO/MO catalogs contain the same reviewed message set. The
customer-facing copy, image alternative text, accessible names, empty states,
and booking-card fallback labels are covered by database-free tests.

## Preserved boundaries

- Salon names, service names, stylist names, addresses, neighborhood names,
  discount labels, and other business/user-authored content remain source data
  and are not translated automatically.
- Brand display uses the Persian deployment name only for `fa`; English and
  Arabic use the configured Latin display name.
- Jalali date rendering, time values, timezone behavior, appointment logic,
  booking operations, price values, and currency identity are unchanged.
  The currency label is localized as “Toman” only; no conversion or monetary
  semantics are introduced.
- SEO title/description and social metadata remain in the later SEO phase.
- Search filters/results, salon detail, stylist profile, service detail,
  and authenticated dashboard surfaces remain subsequent Phase 4 slices.
- The default deployment locale remains unchanged until enough high-traffic
  surfaces are localized and the separate default-switch review is complete.

## Acceptance

CI verifies that every literal `trans` message used by these templates has
a compiled fa/en/ar translation, that visible template copy has no remaining
Persian literals outside the explicitly deferred title metadata, and that
dynamic salon/service content remains unchanged when UI labels are rendered
under each locale.

The Phase 3 exit audit remains **NOT EXITED**. Its manual browser, keyboard,
screen-reader, responsive-zoom, and deployment-approval gates are separate
and remain open.
