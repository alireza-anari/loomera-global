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

## Phase 3.31 post-checkout localization follow-up

The payment result, appointment index, card/empty-state and selected
detail labels now use reviewed native gettext (76 new and 7 reused
source messages). The two distinct financial states — collected
online funds and a confirmed appointment still requiring payment
at the salon — retain their original server-side guards; no gateway
status is inferred from translated copy. A database-free CI suite
checks all six compiled fa/en/ar PO/MO files, primary financial
branches, LTR payment references and accessible states.

**Remaining blockers:** backend-computed localized financial
status strings and some appointment-detail/cancellation language
still require explicit review. There are no real-browser screenshots,
keyboard, responsive-zoom or screen-reader acceptance records and
no deployment approval. Phase 3 remains NOT EXITED.

## Phase 3.31 — Payment-result and appointment identifier review

Payment-result order numbers, reference IDs, transaction tracking,
provider/status labels and split-day date/time strings now use
directional isolation. Appointment details retain untouched tel
links while isolating displayed phone and order numbers. Automated
Django tests protect financial and status branches and reference
serialization. This is **structural** bidi evidence only: real
browser, keyboard, screen reader, zoom, and release approval
remain pending, with no manual test evidence added.

## Phase 3.32 — Dynamic financial status and cancellation/refund copy

Known payment/order enum values, payment-method labels, pending-review and
expired-checkout copy, refund receipts, generic cancellation policy text,
and customer cancellation JSON/fallback messages now use native gettext.
Unknown enum codes fall back to a reviewed generic label. Raw gateway
verification messages are not appended to customer-facing pending copy.
The original ownership guard, atomic financial cancellation service,
refund amount, provider state machine and stored salon-authored policy /
cancellation reason remain unchanged.

The 64-message reviewed ledger is compiled in all three locales, bringing
each PO/MO catalog to 490 entries. Eight database-free Django tests cover
catalog parity, runtime state mapping, dynamic-message safety, policy
interpolation, cancellation feedback and template compilation.

**Phase 3 remains NOT EXITED.** Real-browser, keyboard, screen-reader,
responsive-zoom and deployment/rollback acceptance are still outstanding.

## Phase 3.33 — Appointment lifecycle progress and reminder localization

The customer appointment progress timeline now uses locale-aware lifecycle
labels, translated fixed descriptions, review-entry copy and accurate
reminder-state text. Reminder scheduling remains unchanged; the UI now
distinguishes scheduled, sent and skipped states even when a skipped
reminder retains its historical due timestamp. Jalali formatting,
payment state, review eligibility, salon-authored copy and stored
notifications remain unchanged.

The 24-message reviewed ledger is compiled in all three locales, bringing
each PO/MO catalog to 514 entries. Eight database-free tests protect
catalog parity, lazy locale resolution, lifecycle stage decisions,
reminder semantics and template rendering. The manual acceptance matrix
remains **BLOCKED_MANUAL_ACCEPTANCE** with no manual evidence recorded.

## Phase 3.34 — browser-level renderer smoke (not release acceptance)

The shared mobile viewport no longer disables zoom. Booking time
options expose valid group semantics and localized accessible
names; the service switcher is likewise a named native-button
group. GitHub CI now runs nine real Chromium fixture scenarios
covering fa/en/ar, keyboard Tab/Enter/Space, focus restoration
after dynamic DOM updates, pressed-state synchronization,
HTML-injection handling and clock direction isolation.

This is **partial automated browser evidence only**, not a
representative customer booking across real server APIs, real
viewport zoom, a visual screenshot audit or NVDA/VoiceOver
screen reader verification. The acceptance matrix continues
to mark all five manual gates open; no fake tester records or
deployment approval have been added.

## Phase 3.35 — Quick booking link locale and selection affordances

The invalid token-entry page and professional-specific service selector now use
39 new reviewed native gettext strings (plus reused compiled entries) in
fa/en/ar. These include fixed error states, static first-paint copy, form feedback,
service-description fallback, price/duration units and names in direction-isolated
markup. English navigation arrows are mirrored without changing DOM or tab order.
The reviewed JSON ledger, six native PO/MO files and database-free Django CI
check the new behavior. Existing quick-link ownership and token validation,
HTTP 410, POST field names, selected IDs, session transitions, checkout/business
logic, amounts and salon-authored text are unchanged.

**This is not Phase 3 exit.** CI and structural template checks do not substitute
for real-browser localization, keyboard, assistive technology or zoom acceptance.
All five manual release gates and Production deployment approval remain blocked.

The selected-service empty POST notice is added to a dedicated immutable,
error-tone-only flash allowlist; its native compiled gettext identifier is
matched exactly so arbitrary customer, provider or technical payloads still
fall back safely. Historical Persian booking flash identifiers are preserved.

## Phase 3.36 — Payment outcomes and appointment detail customer copy

Forty-seven new reviewed, compiled fa/en/ar gettext entries complete the
remaining customer-facing static labels and guidance on the active payment
result and appointment-detail surfaces (600 catalog entries per language).
Financial outcome branches remain governed by the existing trusted
payment-state data; the locale change does not reinterpret a pending
verification, expired window, cancelled payment or collected settlement.

The appointment management and review dialogs now translate their fixed
headings, action descriptions, rating accessible names and input
placeholder. The rating uses reviewed gettext interpolation and keeps
the existing POST score/comment fields. The navigation fallback notice
is emitted into JavaScript through `escapejs`, not raw string insertion.
Financial references, amount/currency values, existing support-route
query identifiers, salon-authored content, order numbers, Jalali dates,
time selection, payment and cancellation operations are not modified.
A dedicated database-free Django suite validates native PO/MO parity,
real Django template compilation, context-safe interpolation, financial
branches and manual release blockers.

No browser viewport/screen-reader/manual keyboard/zoom acceptance is claimed.
The five manual Phase 3 gates and Production deployment approval remain open.

## Phase 3.37 — Appointment dialog keyboard and focus management

The appointment management and review dialogs now move initial focus to
their accessible title, contain Tab/Shift+Tab navigation, close on Escape,
and restore focus to the triggering control while restoring the previous
body scroll state. A modal stack handles the active dialog, and the
decorative management backdrop is removed from keyboard order. Review
rating buttons expose an explicit initial `aria-pressed=false` state;
their existing score/comment POST contract remains unchanged.

CI now runs a dedicated database-free Django contract suite and a Chromium
fixture suite using the real production modal HTML fragments and the
production modal/rating controller. The browser suite exercises both dialogs
for fa/en/ar at 360, 768 and 1440 CSS-pixel widths, including focus wrapping,
Escape, focus restoration, scroll locking, horizontal overflow and keyboard
rating submission state.

This is **fixture-level browser evidence**, not a full authenticated
server-rendered journey or screen-reader acceptance. The five manual Phase 3
gates and Production deployment approval remain open; no manual evidence
has been fabricated and no Production deployment is performed.

The Phase 3.37 review-form follow-up also closes a native HTML validation gap:
the score is stored in a hidden input, which browsers do not constraint-validate
even when marked required. The form now prevents an empty-score POST, exposes
an announced localized error, focuses the first rating button, and clears the
error when the user chooses a score. One reviewed gettext message is compiled
into fa/en/ar; each catalog now contains 601 entries. This is still automated
fixture evidence only and does not change the open manual acceptance gates.

The existing server-side score-range guard is unchanged; its invalid-score
fallback message now uses the same reviewed gettext identifier as the client
validation, so bypassing JavaScript does not force Persian-only feedback.

## Phase 3.38 — Checkout CTA live Chromium fixture verification

Production checkout guard code and native gettext form attributes are now
executed in 18 isolated Chromium fixture scenarios across fa/en/ar, both
checkout forms and three viewports. This tests payment-button label
transitions, keyboard coupon submission, form action guards, duplicate
confirmation prevention, mobile-bar inert state and safe rendering of
markup-bearing labels. It is **partial browser evidence**, not live
authenticated checkout, gateway payment, NVDA/VoiceOver, zoom acceptance
or Production readiness. All five manual release gates remain open.

## Phase 3.39 — Booking Server Session and Client Handoff

A database-free test now invokes the real pair of public booking POST
handlers, their shared Django session, redirects and validation failure
cleanup. A Chromium fixture executes the real specialist click handler,
date/time step switcher and booking JSON serializer together, for
fa/en/ar and mobile/tablet/desktop widths. Accessible professional
labels, availability texts and the first-available name transported
to the next step are now native compiled gettext in three locales.

These are cross-stage **automated** checks with controlled domain
validation and fixture DOM, not actual server-rendered
authenticated payments or a manual browser accessibility review.
The five manual release blockers and Production approval remain open.

## Phase 3.40 — Mixed-script checkout display boundaries

Real preview/checkout templates now isolate customer/salon service
names and policy copy with automatic text direction, and date/time
tokens with explicit directional containers without touching
posted booking data. Six DB-free Django tests render actual template
fragments with HTML metacharacters in fa/en/ar. The existing
18-scenario Chromium fixture suite now checks real production BDI
markup for hostile mixed-script names, date/time direction, injection
absence and horizontal overflow alongside localized CTA/keyboard
behavior. These are structural/fixture browser checks, **not**
a live authenticated user journey, audited manual keyboard/zoom
acceptance or a screen-reader run. The full manual release matrix
remains blocked; no Production authorization is implied.
