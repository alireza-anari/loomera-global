# Phase 3 End-to-End Exit Audit — Loomera Global

**Status: NOT EXITED — manual acceptance and deployment approval outstanding.**

This record describes exactly what current GitHub CI can substantiate and
which acceptance evidence is still missing. It is not a production deployment
authorization, and it does not assert that browser, screen-reader, keyboard
or responsive testing was performed.

## Reviewed scope and current automated evidence

The machine-readable companion
[`PHASE3_EXIT_MATRIX.json`](PHASE3_EXIT_MATRIX.json) contains the eight
end-to-end journeys, their test files, the required locales, screen sizes and
manual verification steps. They span language switching, authentication,
OTP/password recovery, specialist selection, Jalali date/time and rebooking,
coupon/preview/checkout, wallet/pay-at-salon status, appointments and feedback.

The code-level coverage available through CI includes: Django response,
template and form contracts; native fa/en/ar gettext PO/MO parity; OTP
attempt/pluralization constraints; static and dynamic feedback PII
fail-closed rules; a booked-slot conflict guard; checkout and payment
status correctness; and source-level RTL/LTR, ARIA and numeric-field
invariants. The Phase 3.27 gate adds **actual Node execution of selected
production JS functions**, checking dynamic HTML escaping with hostile
names, exactly-once escaping of calendar summaries, keyboard-focus
restoration after a time-slot re-render, and numeric formatting across
fa/en/ar. These are runtime tests with stub DOM objects, **not** an
actual browser visit.

After identifying duplicate CI invocations, three redundant whole
workflow steps were removed. The exact same four affected Django
test modules continue to run via the remaining compiled gettext and
booking journey gates, so no unique regression suite is dropped.

## Release blockers (must remain explicit)

1. **Visual browser acceptance:** verify all eight journeys at
   360×800, 768×1024 and 1440×900, across fa/RTL, en/LTR and ar/RTL;
   inspect mixed-direction numbers, time ranges, coupons, navigation,
   payment amounts, error messages, text wrapping and overflow.
2. **Keyboard acceptance:** navigate without a pointer through booking,
   dynamic specialist/time choices, coupon application, checkout
   confirmation, error recovery and rebooking. Confirm visible focus,
   state announcements and no keyboard traps.
3. **Assistive technology:** record NVDA with Chromium/Firefox and
   VoiceOver with Safari for representative flow and error states,
   including roles, group names, button pressed state and live alerts.
4. **Responsive / zoom:** verify 200% and 400% zoom, mobile soft keyboard,
   narrow layouts, focus visibility and fixed booking action bars.
5. **Deployment sign-off:** confirm production configuration and rollback
   arrangements with the responsible owner. No automatic merge in this
   workstream deploys to Production.

The matrix marks all manual work **not run** and records no invented
screenshots, viewport observations, accessibility scores or tester
sign-offs. A future auditor should append individual structured evidence
and issue links to the matrix as work is completed, then independently
decide whether these blockers may be closed.

## Acceptance procedure

Use a non-production installation with representative, scrubbed bookings
including: a name containing an apostrophe and mixed Arabic/Latin text;
service and specialist switches; multiple services on the same and
different days; an unavailable stale slot; a rejected coupon; a
changed-price preview requiring renewed approval; a wallet-funded
booking; an unpaid pay-at-salon booking; payment failure and refund
states. Do not charge real customers or trigger production SMS/OTP.

For each row of the matrix, record the tester, locale, exact viewport
and browser version, keyboard sequence, screen-reader version (when
applicable), screenshot/recording reference, result and issue link.
Escalate misleading financial states or exposed personal/payment data
as blockers. Repeat the relevant scenario after every remediation;
rerun all GitHub CI checks before merging a follow-up.

## Preserved architectural boundaries

Historical default deployment remains fa, RTL, Asia/Tehran and Jalali.
English is LTR; Arabic RTL. Server booking, settlement, OTP, financial
authorizations, idempotency keys, original source repository and
database model semantics are not modified by this audit.
Browser-visible translations for some legacy dynamic customer booking
phrases remain incomplete and need explicit review before Phase 3
can be declared finished.

**Result: ready for structured manual acceptance, not Phase 3 exit.**

## Phase 3.28 localization follow-up (no manual gate closure)

Thirty-seven static dynamic-booking UI messages now come from reviewed
native Django gettext fa/en/ar catalogs and are exposed only as
display copy. Node and Django tests assert catalog parity,
request-scoped delivery and unchanged server flash trust boundaries.
A subset of the initial static controls uses native `trans` to avoid
brief Persian-only states in en/ar sessions. Explanatory paragraphs,
some calendar hints, and certain conditional messages still need
dedicated localization and real browser verification. **No manual
acceptance evidence was obtained in this slice**; all matrix release
blockers remain in place.

## Phase 3.29 booking full-flow localization follow-up

The shared booking header, staff availability/empty states and
interactive calendar planning gained 58 reviewed compiled gettext
messages (17 new immutable dynamic UI keys). New Django/Node
gates cover all three locale catalogs, first-paint templates,
calendar label fallback and server-flash trust isolation. LTR
specialist cards and mixed-script names are isolated at the
presentation boundary.

**None of the manual release blockers are closed.** No real
browser screenshots, NVDA/VoiceOver results, zoom outcomes or
tester sign-offs were collected. The release matrix remains
`BLOCKED_MANUAL_ACCEPTANCE`, and Production deployment still
requires separate authorization.

## Phase 3.30 preview and checkout localization follow-up

The customer-facing reservation preview and checkout now use native
Django gettext for their static content in fa/en/ar, including multi-day
booking explanations, appointment detail labels, coupon affordances,
discount/campaign-cap copy, payment-method descriptions, and the
financial summary. All 58 new source strings are compiled together in
the three native PO/MO catalogs; catalog size is now 350 entries per
language. Payment choice labels, coupon field label/placeholder and
two checkout validation messages use lazy gettext, so they follow the
active deployment locale.

The amount in the service-discount confirmation is passed through
Django `blocktrans` interpolation, while coupon tokens remain inside
the existing LTR `bdi` boundary. Amount values, currency identity,
coupon processing, permitted payment method values, payment conditions,
submit guard, and financial calculations are unchanged. New DB-free
tests verify compiled catalog parity, exact three-locale translations,
interpolation, form choice/validation labels and the checkout POST
contract.

This is automated locale coverage, **not** a real-browser visual or
screen-reader sign-off. Backend-generated booking/cancellation policy
text, dynamic salon-provided titles and live payment gateway outcomes
remain contextual data and are not translated generically in this slice.
All manual acceptance and deployment blockers remain open.

## Phase 3.31 — Payment-result and appointment identifier review

Payment-result order numbers, reference IDs, transaction tracking,
provider/status labels and split-day date/time strings now use
directional isolation. Appointment details retain untouched tel
links while isolating displayed phone and order numbers. Automated
Django tests protect financial and status branches and reference
serialization. This is **structural** bidi evidence only: real
browser, keyboard, screen reader, zoom, and release approval
remain pending, with no manual test evidence added.
