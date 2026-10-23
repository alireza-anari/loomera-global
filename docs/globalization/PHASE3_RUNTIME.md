# Phase 3 — Slice 3.1: Request Locale and Bidirectional Shell

**State:** Slice 3.1 merged as PR #72; Slice 3.2 below is a separate implementation candidate subject to CI and review.  
**Dependency:** Phase 2 engineering exit source/CI tests passed in PR #71.  
**Scope:** language-selection middleware + shared document/email direction.  
**Not in scope:** full translation, locale-switch UI endpoint, public locale URL prefixes, production deployment, calendar/weekday/timezone/currency/phone/payment changes.

## Supported and Default Behavior

- `LOOMERA_ENABLED_LANGUAGES` remains the authoritative deployment allowlist.
  Values `en`, `ar`, `fa` can be configured together, and the Django
  `LANGUAGES` contract now exposes those enabled choices only.
- `LOOMERA_DEFAULT_LANGUAGE` is the deployment *request fallback*.
  Its existing default is still `fa`. The Django `LANGUAGE_CODE` compatibility
  default also remains `fa`. **Changing the global default to English is
  explicitly deferred** until core English product text is ready in Phase 4;
  this Phase 3 slice supports a deliberate buyer opt-in with
  `LOOMERA_DEFAULT_LANGUAGE=en` and
  `LOOMERA_ENABLED_LANGUAGES=en,ar,fa`.
- Locale selection happens in
  `loomera.globalization.middleware.DeploymentLocaleMiddleware`, which
  subclasses Django `LocaleMiddleware` to preserve its response handling.
  The existing middleware slot remains after session and authentication
  middleware so request identity and CSRF order do not change.

## Request Resolution and Persistence Contract

Precedence for this slice:
1. Explicit session key `loomera_language`, **only when already set by a
   trusted future language selection flow**.
2. Standard Django `LANGUAGE_COOKIE_NAME` cookie (normally
   `django_language`).
3. `Accept-Language` header, honoring priority quality weights and
   normalizing regional tags such as `en-US` to an enabled base locale.
4. Deployment `LOOMERA_DEFAULT_LANGUAGE` fallback.

All candidates must be enabled. Disabled, malformed, unknown, q=0,
unacceptable or unsupported header values never select a forbidden
language. Query-string `?lang=` is intentionally **not** a selector. The
resolver reads neither user roles nor permissions, business ownership or
country and writes neither session nor cookies. It does not create a
language-switch endpoint in this slice.

An authenticated-user language preference does **not** yet have a reviewed
persistence field; it is explicitly deferred. If added, it must be separate
from authorization/workspace identity and must take precedence only after
its migration and security review. For now, the session/cookie selectors
are presentation-only preferences.

## Template and Email Shells

`loomera.globalization.context_processors.deployment_locale` exposes a
frozen `DeploymentLocaleContext` snapshot with `language_code`,
`direction`, `is_rtl`, and `enabled_languages`. The two active
Django document shells (`templates/base.html` and
`templates/dashboard_template.html`) use those values for their root
`lang`/`dir` attributes; English is LTR, Arabic/Persian RTL.
Templates rendered without a request context retain `fa` / `rtl`
fallback and existing default markup.

The two **previously classified static-unreferenced** legacy email
layouts expose the same opt-in `deployment_locale` contract for HTML
root language/direction and body text direction. They default to
`fa`/`rtl` without a context, preserving their current rendering.
No new email sender, dispatch path, automatic recipient-language inference,
HTML mail activation, translation, or legal/sender copy edit occurs.
A future mail renderer must pass explicit recipient locale and use the
same selection boundary; the source scan from Phase 2 remains active.

**Important compatibility limitation:** RTL-assuming CSS/layout and
untranslated Persian product strings still exist. `lang=en`/`dir=ltr`
on the shared document is a **foundation**, not proof that every feature,
datepicker or mobile navigation is English-usable or visually correct.
Phase 3 later slices must audit bidirectional components; Phase 4 owns
product translation. The Jalali datepicker/formatters and legacy
Tehran/toman booking and money semantics are unchanged.

## Regression and Activation

The database-free suite
`apps.main.test_phase3_locale_shell` checks default and opt-in policy,
selector precedence and regional/q-weight handling, disabled fallback,
no session/cookie mutation, middleware language activation and response
metadata, immutable request context, public/dashboard shell markup in
all three languages, dormant email direction with default fallback,
middleware ordering and no business-runtime drift.

```bash
python manage.py test apps.main.test_phase3_locale_shell --failfast
```

GitHub CI runs this independently of the existing Phase 1/2 regression
guards. Production deployment, public URL locale prefixes, persisted user
preference, translation catalogs and the English-first switch are **not
implied** by this slice. Phase 3 remains open after it merges.

## Phase 3 — Slice 3.2: Explicit Language Choice, Persistence and Translation Catalog Seed

The new POST-only endpoint `/language/` (`set_deployment_language`) provides
a narrowly scoped way for a user to select an **enabled** deployment language.
It is a presentation preference, not a user-profile or workspace setting and
it does not change any model, permissions, business or authentication ownership.

The POST form requires a valid CSRF token and exactly one `language` value
matching the enabled locale list. On success, the view sets the existing
`loomera_language` session key and the standard Django language cookie with
the configured cookie age, path, domain, Secure and SameSite properties;
HttpOnly is enforced because no client-side language-cookie access is required.
The response redirects (302, `Cache-Control: no-store`) to the submitted
site-local `next` path, or safely falls back to `/` if the supplied URL is
absent, non-root-relative, scheme-qualified or otherwise unsafe. No off-site
redirect is permitted. GET is not accepted; invalid/disabled choices yield
HTTP 400 **without modifying the existing preference**.

The existing Phase 3.1 resolver gives the saved session choice precedence
over the language cookie and Accept-Language header. The locale middleware
continues to run after the session and authentication middleware. Anonymous
and authenticated users can use the selector. Login, logout, role/workspace
authorization and user profile storage are not modified. Persistence lasts
for the session and the configured language cookie lifetime; there is no
new database-backed user language preference.

The shared selector partial `templates/partials/shell/language_switcher.html`
is included in public desktop/mobile headers and in the dashboard shell.
It uses native HTML POST, a CSRF token, a safe-return hidden field and a
language `select` plus explicit submit button (no JavaScript required).
**The partial does not render for a deployment with only one enabled
language**, retaining the exact default fa-only visual shell. For multi-locale
deployments, native-language options make the selection accessible without
assuming every product string is translated. English remains LTR; Persian
and Arabic remain RTL through the already-shared document language context.
Underlying existing fixed-side CSS/layout and datepickers remain future
bidirectional review work, not silently claimed solved.

### Versioned gettext catalogs

`LOCALE_PATHS = [BASE_DIR / "locale"]` registers new app-owned
`locale/en/LC_MESSAGES/django.{po,mo}`,
`locale/fa/LC_MESSAGES/django.{po,mo}`, and
`locale/ar/LC_MESSAGES/django.{po,mo}`. The source catalog initially contains
only two **application-owned UI strings**: `Language` and
`Apply language`. The compiled `.mo` files are committed alongside
their `.po` sources so runtime Django can load them without build-time
GNU gettext dependencies. Keep source and binary catalogs synchronized when
changing translations (e.g. via `django-admin compilemessages` in a
controlled build environment). The CI tests exercise `gettext` in each
language and guard these exact initial compiled translations.

This is **not a full English/Persian/Arabic product translation**. The
selector's accessibility copy remains bilingual when catalogs are unavailable,
and application-owned content outside this tiny initial set is still in its
legacy language until the Phase 4 localization workstream. No user-entered
business content is machine-translated or rewritten.

### Security and compatibility checks

`apps.main.test_phase3_language_switch` runs as a separate GitHub CI step
and checks real Client POST/session/cookie round trips with a database-free
signed-cookie test session, strict CSRF/method rejection, disabled/malformed
languages, safe next-path redirects, session preservation, cookie security,
shell inclusion and single-language invisibility, HTML output escaping,
native language labels, and compiled gettext lookup. No authentication,
booking, calendar, price/money, timezone, SMS, email-delivery or payment
code is changed.

**Phase 3 remains open.** Future slices own deeper RTL/LTR component
regression patterns and rollout of product translation markers/catalogs.
No production/staging deployment is performed by this PR.

## Phase 3 — Slice 3.3: Shared-Shell RTL/LTR Navigation and Form Parity

**Scope:** a CSS-only presentation bridge and a limited workspace-switcher
CSS/markup normalization. It does not modify business logic, dashboard
JavaScript state transitions, route targets, form actions, CSRF controls,
access permissions, or locale persistence.

The prior Phase 3.1 shell roots set the correct HTML language and direction,
but several shared components still assumed a permanently Persian-side
layout. The new `static/css/components/bidirectional_shell.css` is loaded
**after** existing workspace-switcher CSS in both public and partner root
templates. It is scoped under `html[dir="ltr"]` to preserve the exact
`fa/ar` RTL presentation and all legacy RTL utility classes.

- **Public customer mobile dock:** preserves the original five route targets,
  active-state logic and DOM/focus order. The grid presentation mirrors for
  English LTR while the prior RTL order remains unchanged.
- **Partner dashboard sidebar and topbar:** mirrors fixed sidebar placement,
  mobile hidden/visible translation, expanded and collapsed content padding
  (22rem / 6rem), and topbar offsets. The existing JS continues to toggle
  exactly the same `lg:pr-*`, `lg:right-*`, `translate-x-*` and sidebar
  data-state classes; no storage, menu toggling, notification or role code
  changes. Collapsed tooltips, close/collapse affordances and arrow glyph
  receive scoped mirror treatment.
- **Partner mobile navigation:** the glass dock's raised create-action
  notch, backdrop mask, popover and smaller-screen offsets mirror only for
  LTR. The default RTL dock remains unchanged.
- **Workspace selector:** popovers and option labels now use CSS logical
  properties and inherited direction; a trigger-copy semantic class replaces
  a hardcoded alignment dependency. Arrow glyph presentation mirrors in LTR,
  while the POST workspace-switch forms, CSRF token and data hooks are intact.
- **Shared field labels and error messages:** LTR flow-relative text
  alignment applies to a small explicit selector list. Phone/mobile, money,
  numeric input and Jalali/calendar formatting rules are **not** changed.

### Verification limits

The database-free `apps.main.test_phase3_bidirectional_shell` suite covers
root template inclusion/order, three-locale HTML lang/dir, LTR-scoped CSS,
RTL compatibility source, mobile navigation route order, workspace form
controls, JS collapse-state coupling, fixed/mobile sidebar offsets, partner
mobile notch controls and logical form labels. CI must pass this suite
alongside all existing Phase 1–3 regression suites:

```bash
python manage.py test apps.main.test_phase3_bidirectional_shell --failfast
```

These are **structural and rendering-contract tests**, not screenshots or
actual cross-browser layout measurements. Browser-level QA at desktop and
mobile widths for fa/ar/en, keyboard/focus navigation, overlay placement,
collapsed sidebar and calendar controls must be completed at a future
browser/deployment acceptance gate. Phase 3 and product translation remain
open; no production deployment is performed by this task.


## Phase 3 — Slice 3.4: Authentication Forms, Controls and Bidirectionality

**Scope:** Structural bidirectional parity of four currently shipped auth form
templates (`login.html`, `register.html`, `customer_signup.html`, and
`stylist_signup.html`). The new
`static/css/components/bidirectional_auth.css` is loaded **after** each
form's existing isolated page stylesheet. Its rules are scoped exclusively to
`html[dir="ltr"]`; default Persian and opt-in Arabic RTL do not change.

On LTR desktop layouts, the login panel and all three signup panels mirror
their right-aligned Persian placement to the left, including the artwork
softener's gradient direction. Existing widths, mobile layouts, short-height
scroll behavior and buyer-brand asset paths are preserved. Label, help and
error copy aligns to inline start, and forward CTA arrows mirror only in
LTR. Password visibility eyes, phone icons, numeric input direction and
password-strength indicators are **not** mirrored or transformed.

All four templates retain their POST/CSRF contracts, field identifiers,
autocomplete, mobile input `dir="ltr"` and numeric keyboard, existing
form errors, signup terms, password show/hide and client-side strength
listeners; no view, model, session, authentication, validation or script
changes occur. This means the presentation work does **not** internationalize
Iranian phone number validation or introduce a new country-code policy.

The dedicated no-database
`apps.main.test_phase3_bidirectional_auth` CI step adds regression tests
for page CSS inclusion order, LTR-only scope, desktop/mid-screen side
mirroring, signup variants, CTA icon semantics, preserved field/JS hooks,
brand asset paths and fa/en/ar root document direction:

```bash
python manage.py test apps.main.test_phase3_bidirectional_auth --failfast
```

**Explicit limitations:** These source/template-contract checks are not
browser screenshots. Hero image compositions and mobile overflow need
actual browser QA in all three languages before production rollout.
Persian prose currently remains in authentication forms even when the
request's root language is English or Arabic; translation markers,
catalog expansion, form-generated validation messages and production-level
language usability must be addressed in the separate product-localization
workstream. **Phase 3 remains open; no deployment was performed.**

## Phase 3 — Slice 3.5: Trusted Interactive Messages and Validation Catalog

**Scope:** app-owned, static interactive copy in the shared
`form_interactions.js` client-validation renderer and `feedback.js` flash
component. Existing Django form validation semantics, user-entered data,
account authorization, booking/payment, calendar and currency are unchanged.

### Request-to-browser catalog boundary

`loomera.globalization.interactive_messages.interactive_messages` is a
request context processor producing `{language, messages}` from a frozen
allowlist of 24 named message keys. Message sources use English gettext
`msgid` and versioned `en/fa/ar` `django.po` catalogs, compiled into
matching `django.mo` files shipped in the repository. Translation is
explicitly activated for the resolved allowed request locale; it does not
read profile/workspace business identity or accept client-provided strings.

Both shared document shells serialize this static mapping with Django
`json_script`, which HTML-escapes the JSON, then load
`static/js/interactive_i18n.js` **before** `feedback.js` and the primary
application module. The lightweight runtime exposes `text`, `format` and
a trusted-message predicate. The client allows only `feedback.*` and
`validation.*` string values, bounded to 300 characters per entry.
Dynamic min/max constraints are substituted into predefined catalog
strings as text; no template interpolation into HTML occurs.

If the catalog is absent or malformed, the old Persian fallback paths
remain available, preserving the current default fa-only deployment.
This fallback is a compatibility behavior, not a translated UI claim.

### Language-dependent feedback safety

In the default Persian path, the original Persian message sanitizer and
technical-error filter remain unchanged. In enabled English or Arabic
requests, `feedback.js` accepts only messages already present in the
trusted catalog and rejects technical strings and arbitrary server/client
free text to a **localized generic fallback**. This is deliberately
conservative: arbitrary user/server/business messages are not translated,
inferred, or exposed. Existing clients can still call
`window.LoomeraFeedback`; API method names, roles and dismissal timing
are preserved.

The generic browser-side constraint error and notice texts are localized
in the same catalog, including required/email/URL/pattern, length/range,
step and invalid input messages. Server-origin field errors remain
server-provided and are **not** guessed or translated; only generic
fallback copy is localized.

**Not yet covered:** page-specific interactive strings, auth labels,
submission-pending button labels, Django model/form server errors, SMS
templates, notifications payloads, legal content, amount/date/phone
formatting, automated language detection, or full product translation.
English-first product defaults remain deferred.

### Test and rollout boundary

- Django database-free `apps.main.test_phase3_interactive_messages`
  validates the allowlist, compiled gettext lookups across three locales,
  request isolation, disabled language fallback, XSS-safe JSON embedding,
  both shell script order, and preserved numeric/calendar/form contracts.
- Node's dependency-free `tests/js/phase3_interactive_i18n.test.cjs`
  executes the browser runtime and flash component in an isolated VM,
  verifying safe formatting, trusted-message filtering, fa compatibility,
  malformed payload fail-closed behavior and unknown key blocking.
- CI performs JavaScript syntax checks and runs both suites **on the
  final PR head** alongside the previous Phase 1–3 guards.

This is not a browser/screenshot accessibility audit, an end-to-end
checkout test or a production deployment. Phase 3 remains open.

## Phase 3 — Slice 3.6: Localized Safe Form Submission Progress

The shared browser submit-pending indicator now uses 10 additional allowlisted
Django gettext entries under `submit.*` (saving, registering, sending,
creating, logging in, confirming, activating, deleting, cancelling and generic
working). Source `django.po` and compiled `django.mo` catalogs for
`fa/en/ar` include these entries; the reviewed request-specific
`interactive_messages` map grows from 24 to 34 messages.
The same `json_script` bridge supports `submit.*` keys without adding a
request endpoint, database field or browser fetch.

Existing buttons still infer a bounded action from their visible source text.
For now, the shared form handler recognizes common Persian, Arabic and English
action words; unknown labels display the generic `Working…` equivalent
rather than inventing a new domain-specific message. An existing
`data-lm-submitting-label` override is preserved without restriction in
the default Persian compatibility path. In en/ar, explicit overrides are
accepted only if they exactly match an allowlisted translated string; other
overrides fall back to an inferred or generic approved message.

**Security repair:** form submission markup no longer interpolates a
dynamic label into `innerHTML`. The pending icon and `span` are created as
DOM nodes and the label is assigned with `textContent`. The original button
HTML is restored via the existing snapshot contract on `pageshow`;
input submitter `value`, disabled/aria-busy state, opt-out flags, dirty-form
logic and form submit event timing remain unchanged.

A dedicated seven-test Django suite validates the expanded frozen message
allowlist, actual gettext output for all 10 entries in three languages, locale
isolation, disabled-language fallback, source security invariants and
unchanged business defaults. Nine dependency-free Node VM tests execute the
actual form handler and i18n bridge with simulated buttons/inputs to verify
language-specific action matching, hostile explicit labels, legacy Persian
overrides, state restoration, duplicate-submission idempotency and opt-out
semantics. Existing Phase 3.5 and earlier tests remain in CI.

This slice does **not** translate server validation, domain-specific form
labels, form field data, booking/checkout/payment workflows or phone/currency
formats. It does not constitute full browser-accessibility acceptance or a
production deployment; Phase 3 remains open.

## Phase 3 — Slice 3.7: Shared Authentication Copy and Controlled Login Feedback

**Scope:** static form copy in the four existing authentication entry pages
(`login`, customer signup, professional signup and business-manager signup)
and five generic messages emitted by the `LoginUserView`. This is not a
redesign of identity, permission, password policy or OTP handling.

The templates now load Django's `i18n` tag library and mark selected shared
labels, role/action links, accessible password-toggle labels, form-section
labels, submit CTAs and introductory explanations with `{% trans %}`.
Translation keys deliberately use the existing Persian source strings, with
compiled `en/fa/ar` Django gettext catalogs providing the alternate text.
In the default Persian deployment, the translated output is the exact
existing Persian wording. The four browser `title` blocks and branded
home-link accessibility labels are **intentionally unchanged** to preserve
the independently verified Phase 2 buyer-brand identity contract and
associated regression tests. The shell and direction switching still follow
the deployment's Phase 3 locale.

Five hardcoded, generic login feedback messages now use request-time Django
`gettext` under the already-activated request locale: invalid form fields,
invalid credentials, inactive account, denied platform-admin entry and
successful sign-in. Existing authentication branches, permission and
workspace predicates, login session semantics and safe return destination
are unchanged. Messages do not interpolate account credentials or
secret/user-specific data and are not used to make authorization decisions.

This slice **does not modify** Persian legal acceptance wording or legal
content, the Iranian mobile-number validation policy, signup/password and
OTP server error strings, the page-specific inline JavaScript password
strength hints, SMS copy, or user-generated data. Those are separate
reviewed localization tasks. In particular, the new generic login flash
messages may still be reduced to a safe generic fallback by the
conservative en/ar browser feedback sanitizer introduced in Phase 3.5;
they are not a license to display untrusted backend errors.

Nine database-free Django tests cover the four active templates' tag
integration and rendered common labels in fa/en/ar, compiled catalog
lookups, login feedback gettext, Phase 2 brand-sensitive title and
metadata invariants, preserved form/CSRF/mobile/direction contracts and
unchanged calendar/currency semantics. Existing Phase 2 and Phase 3
regression suites remain in CI. Production rollout and real-browser
accessibility/visual QA remain separate; **Phase 3 stays open**.

## Phase 3 — Slice 3.8: Signup, OTP and Password Recovery Validation Text

This engineering slice localizes **28 fixed Persian-source message identifiers**
with reviewed English and Arabic gettext translations. The compiled
`locale/{fa,en,ar}/LC_MESSAGES/django.mo` binaries and corresponding
`django.po` sources are versioned together; no additional locales are
enabled by default.

`apps/accounts/forms.py` uses immediate `gettext()` for selected
`ValidationError` branches evaluated during validation, and
`gettext_lazy()` for static class-level `error_messages` mappings that
must be evaluated in the current request language. Covered paths include
the existing Iranian 11-digit mobile-number format check, already-registered
role/number errors, password confirmation/minimum-length errors, specialist
minimum-length errors and blank field messages for OTP/login/recovery forms.
The existing validators, database access, password hashing and user
permissions are unchanged.

`apps/accounts/views.py` resolves a bounded set of **generic** OTP
registration, password recovery and change-password status/error strings via
request-time `gettext()`. It intentionally leaves the dynamic
`remaining_attempts` f-string untouched: plural-sensitive count
messages need a separate reviewed `ngettext()`/format contract. OTP
attempt increments, expiry/TTL, session cleanup, hash updates, login/logout,
and login/password recovery redirects were not changed.

The new no-database
`apps.main.test_phase3_auth_recovery_errors` suite runs ten regression
tests. It executes real invalid-form and direct clean-method branches
under fa/en/ar translations, validates compiled gettext for OTP/recovery
messages, checks static form/deployment configuration and asserts that
rate/attempt, phone-format and password-security hooks remain present.
The CI workflow runs this suite alongside all earlier Phase 1–3 gates.

**Limitations:** This is not a country-neutral mobile-number or recovery
flow, an international SMS provider, a translation of arbitrary backend
exception text, full signup page translation, or end-to-end browser/OTP
acceptance. The existing `fa` policy and returned error strings are
preserved exactly. No staging/production deployment is included;
Phase 3 remains open.


## Phase 3 — Slice 3.9: OTP Remaining-Attempt Pluralization

The existing incorrect-OTP branch still increments
`user_session["otp_attempts"]`, computes
`remaining_attempts = max(otp_max_attempts - otp_attempts, 0)`,
and locks out, clears the session and redirects at zero. None of these
security-sensitive operations, TTLs or verification and reset flows changes.

Only the human-visible **positive remaining-attempt** message is replaced
with `_format_remaining_otp_attempts(remaining_attempts)` using Django
`ngettext(singular_msgid, plural_msgid, remaining_attempts)` and named
integer interpolation `%(count)d`. The helper executes after the existing
`remaining_attempts <= 0` lockout branch; neither a zero attempt count
nor an expired OTP ever returns this progress message.

Three source and compiled catalogs ship the same new plural message ID:
- **Persian:** both forms return exactly the prior
  `کد وارد شده اشتباه است. N تلاش دیگر باقی مانده است.`
  string, including spacing and ASCII integer rendering
- **English:** one `attempt remains` versus multiple `attempts remain`
- **Arabic:** all six GNU gettext forms (zero, one, two, 3–10, 11–99,
  and the remaining category), respecting the existing declared
  `Plural-Forms` header

The new database-free `apps.main.test_phase3_otp_pluralization`
regression suite executes the real compiled `.mo` gettext paths for
fa/en/ar across multiple counts, asserts exact Persian message identity,
and invokes the actual `VerifyRegisterView.post` handler with
a signed-cookie test session and mocked presentation transports.
The latter verifies that three invalid codes against a three-attempt
budget show 2 then 1 remaining, then **do not** show a counter and
instead clear the session and redirect on the third failed attempt.
It also exercises already-exhausted attempts, preserving the lockout
path and the separate generic translation. Earlier signup, recovery,
Phase 2 brand and frontend suites continue to run.

These tests do not send SMS or connect to a real account, and do not
replace a browser/production acceptance gate. No default language,
authentication, payment, booking, locale formatting or data schema is
changed. Phase 3 is still open.


## Phase 3 — Slice 3.10: Active OTP Verification and Password Recovery Pages

This bounded localization slice covers **the active** `accounts/verify.html`
and `accounts/remember_password.html` pages, request-time verification
metadata built by `_build_verification_context()`, and presentation labels
for `VerifyRegisterForm` / `RememberPasswordForm`. The legacy alias
templates (`verify_code.html`, `remember_password_verify.html`,
`new_password.html` and `reset_password.html`) are not used by the
current authentication URL handlers and are intentionally unchanged.
The interactive change-password screen is deferred to a separate slice.

Selected headings, help text, accessible labels, button captions and
return links now use Django `{% trans %}`; message IDs retain their exact
historical Persian wording. The verify page receives a localized
fallback title and submit label for standalone rendering. View context
strings now use request-time `gettext()`, including the signup kind.
The role-specific verification heading uses one named
`%(role)s` placeholder and a translated, fixed allowlist of role labels.
No account/user/profile data is interpolated into translation sources.

The verify page's two **back** links now reverse the existing verified
`verify_back_url` route name provided by the view context instead of
referring to an undefined `verify_back_href` value. Absent context
falls back to `/`; no POST, arbitrary URL or external redirect is added.

For active recovery/verification forms, class-declared label and
placeholder strings use `gettext_lazy()` so the selected locale is
resolved at render time. Existing Persian trailing spaces in those
specific form strings remain **exactly preserved**. The legacy
mobile-number normalization, numeric one-time-code input direction,
eight-digit client input cap, CSRF, OTP counter/lockout/TTL, session
cleanup and password policy are not modified. The buyer-brand recovery
logo and the exact branded `امنیت حساب {{ deployment_brand.display_name }}`
source boundary are deliberately unchanged.

25 reviewed gettext IDs are added to versioned source and compiled
`fa/en/ar` Django catalogs; the prior ngettext six-form Arabic
OTP-attempt plural entry remains in all regenerated binaries.

The new no-database
`apps.main.test_phase3_recovery_verify_pages` suite verifies actual
page rendering in all three languages, live form label/placeholder
translations, signup/customer/stylist/manager verification context and
return paths, Persian snapshots, presence of security-sensitive input
and CSRF controls, prior OTP plural behavior, and legacy-alias
source compatibility. Existing prior-phase CI gates remain required.

**Not yet covered:** the interactive change-password page, its inline
password-strength JavaScript text, legacy recovery aliases, arbitrary
server errors, real SMS, multilingual numeric/calendar formatting, and
cross-browser visual/accessibility acceptance. No production deployment
or underlying account security behavior changes. **Phase 3 remains open.**


## Phase 3 — Slice 3.11: Active Change-Password UI and Client Validation

This bounded slice localizes the **active** `accounts/change_password.html`
screen, not the legacy recovery alias templates. All selected page headings,
labels, placeholders, CTA, recovery link and toggle accessible names use
Django `{% trans %}` with the historical Persian source. The form's
`requires_current_password` conditional and its return route are unchanged.
The client-side password fields retain the same names, autocomplete, CSRF,
validation, keyboard/focus state and three-bar score thresholds.

Seven additional trusted `password.*` keys extend the existing
`interactive_messages` gettext boundary (from 34 to 41 messages).
They cover strength status (strong/acceptable/guidance), show/hide
accessibility labels, mismatch and minimum-eight feedback. The browser
i18n bridge still accepts only bounded known-prefix string values.
In English and Arabic, the existing feedback sanitizer accepts these
pre-approved translated messages rather than treating them as untrusted
server text; arbitrary strings remain behind safe fallbacks. Persian
fallbacks match the previous JavaScript literals exactly.

The inline change-password script preserves the previous password-eye
toggle behavior, focus, class changes, scoring formula, `< 8` minimum
length and mismatch-prevents-submit logic. It replaces only visible
message string selection via the already initialized `LoomeraI18n.text`
bridge. All strength hint updates use `textContent`, never HTML.
Server-side `ChangePasswordForm` validation, password hashing, session
and OTP reset authorization, account permissions and login/logout
behavior are **not** changed.

25 reviewed new gettext IDs are added to source `django.po` and
compiled `django.mo` for fa/en/ar (two common existing IDs are reused).
The previous six-form Arabic `ngettext` OTP counter remains intact.

The new ten-test database-free Django suite renders the real page in
all three languages and both change/recovery modes, checks catalog
lookups and the preservation of CSRF/field names/security thresholds,
and rechecks OTP plural forms. A seven-test dependency-free Node VM
suite executes the actual inline JavaScript plus the trusted browser
i18n bridge and feedback sanitizer. It verifies weak/acceptable/strong
scores, localized feedback and accessible toggles, client submission
blocking, valid submissions, Persian fallback and hostile input safety.

**Not yet covered:** browser screenshot/keyboard/screen-reader
acceptance, translation of arbitrary server-side errors, legacy
change-password presentation aliases, full account/business
internationalization, or real SMS. No production deployment. **Phase 3
remains open.**


## Phase 3 — Slice 3.12: Change-password LTR field affordances

This isolated presentation-only patch aligns the already localized change-password
page's three password fields with the English LTR document direction. A scoped
stylesheet loaded in that page's head moves the lock/key/check icons to the
inline-start side, password-visibility buttons to inline-end, adjusts the
corresponding input padding, and reverses the two back arrows for LTR only.
The existing fa/ar RTL utility classes remain untouched; the phone badge retains
its explicit LTR direction. No DOM order, form action, CSRF, password show/hide
script, strength scoring, server validation, session or recovery behavior changes.

The database-free `apps.main.test_phase3_change_password_direction` suite checks
stylesheet scope and load order, all three field hooks, visible navigation icons,
preserved Persian-side classes and auth/security contracts. These structural tests
are not cross-browser or visual accessibility acceptance. No deployment.

## Phase 3 — Slice 3.13: Signup and Login Password Interaction Localization

This slice improves the four **active** login/signup forms without modifying
any server-side login, signup or password-policy logic. Their existing
password visibility buttons now carry explicit `aria-controls` and initial
`aria-pressed="false"` attributes. Existing click listeners update both the
visible eye icon and pressed state, and supply the *current action* as the
accessible name. The names reuse the versioned, trusted
`password.show`/`password.hide` request-locale message catalog; the static
Django-translated generic label remains useful before JS initialization.

The manager and stylist three-bar password strength displays still use their
exact existing score thresholds; their initial hints and input-driven weak,
acceptable and strong messages use the preapproved
`password.strength.{guidance,acceptable,strong}` keys. Customer signup
continues to check **length only**, not three-bar strength, reusing the
generic translated guidance/minimum-length/acceptable copy. No new browser
message keys, gettext binary catalogs or untranslated arbitrary text are
added. Historical Persian source wording remains unchanged, including the
two different initial signup hints and the customer length-specific status
messages, even when the bridge supplies compiled fa strings with different
wording. If the bridge is absent, the same Persian fallback applies.
English and Arabic render translated guidance immediately at load, not only
after the first keystroke. Dynamic copy is assigned with `textContent`, never
`innerHTML`, and password values are not used as message content.

The four forms preserve the existing input IDs, show/hide behavior, explicit
LTR mobile number input and digit filtering, register role, terms consent,
CSRF and server validation. No migration, mobile-country rules, OTP, routing,
authentication/session, authorization, brand-title, payment or production
changes occur.

`apps.main.test_phase3_auth_password_interactions` adds five database-free
Django guards for all four active template/form contracts, compiled gettext
lookups, fa compatibility and render output. The dependency-free
`tests/js/phase3_auth_password_interactions.test.cjs` executes all four
actual inline scripts in a Node VM under fa/en/ar/absent-bridge cases,
checking toggle accessibility and states, localized live hints, unchanged
strength/length thresholds, hostile password values and phone sanitization.
GitHub Actions executes both alongside all previous Phase 1–3 suites.
Browser screen-reader and visual acceptance remain pending; no deployment.

## Phase 3 — Slice 3.14: Recovery and OTP Presentation, A11y and Help-Text Safety

Active pages only: `accounts/remember_password.html` and
`accounts/verify.html`. The recovery security caption now uses the
**existing, compiled** Django gettext string for “Account security” and
continues to interpolate the deployment brand as escaped, dynamic text.
The Persian caption preserves its exact original wording and spacing.
There are no new catalog keys or binary catalog edits.

Recovery field help text no longer bypasses template autoescaping via
`|safe`. This is a defense-in-depth improvement if any future form
configurations introduce non-literal help text; the currently active
`RememberPasswordForm` does not provide field help markup. Generic form
field styling still applies to editable inputs, but the script now pins
`dir=ltr` only for the named `mobile_number` input, not every possible
free-text/email/password input. Existing form names, mobile-number policy,
views, CSRF, submission and redirects stay unchanged. Non-field errors
expose an alert role.

The OTP input now exposes `aria-invalid` and associates its existing
help text and conditionally rendered validation error with `aria-describedby`.
An actual invalid form render includes an alert element for the field error;
a pristine form references only the help element. The same single OTP
field, `autocomplete=one-time-code`, numeric keyboard, eight-character
client cap and ASCII-digit filtering remain. An isolated stylesheet is
loaded only by the active verify page; under English/LTR it mirrors the
back and continue arrows without changing fa/ar RTL, numeric input
direction or the shared application shell.

An eight-case no-database Django suite tests compiled fa/en/ar brand
copy, escaped hostile help text, actual rendered valid/invalid OTP ARIA
references, stylesheet direction scoping, and business/security invariants.
A dependency-free Node VM suite runs the **actual** active inline scripts,
checking OTP focus, missing-control resilience, eight-digit input cap,
sanitization, recovery form styling, trusted field direction and no
user-value mutation. The dedicated GitHub CI step runs both alongside all
existing Phase 1–3 checks.

No backend signup/OTP attempt-count changes, migrations, SMS, new phone
formatting, payment, deployment, browser-visual or assistive-technology
acceptance. Phase 3 remains open.

## Phase 3 — Slice 3.15: Active Auth Field-Error Accessibility

This scoped template-only improvement links server-side field validation
feedback to the inputs in the active login, manager, customer and stylist
signup pages. All 21 existing field controls (mobile/password for login;
name/family/mobile/passwords/terms in manager/customer signup; plus expert
in stylist signup) now render a matching `aria-invalid` state. When a
field has server-side errors, its input conditionally references the
single corresponding `small` error node via `aria-describedby`. The
error nodes have stable ids and `role="alert"` for assistive technologies.

The password1 input also always references its existing strength guidance
paragraph (now assigned a stable id), with the error id appended only
when validation fails. The already-localized browser password strength
hint updater still uses `textContent`; no new gettext entries or JS
handlers were added.

All error states are derived from Django `form.<field>.errors`; no
client-provided error state, arbitrary HTML interpolation, new validation
policy, redirect, form action or data model is introduced. Exact Persian
copy, en/ar gettext, legal consent wording/links, browser title/brand,
CSRF, password-eye controls, signup roles and Iranian phone restrictions
remain unchanged. This is source/template and Django-rendering validation,
not a claim of real screen-reader or browser acceptance.

The database-free `apps.main.test_phase3_auth_field_error_a11y` suite
renders pristine and synthetic-invalid real templates in fa/en/ar and
verifies each input's state, error linkage, escaping, preserved
strength hints and unchanged security/identity contracts. GitHub CI runs
it alongside the existing Phase 1–3 regressions. No production deployment.
