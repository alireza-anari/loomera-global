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

## Phase 3 — Slice 3.16: Server and Browser Flash UI Parity

This cross-shell flash presentation slice reuses the already-reviewed,
versioned `feedback.title.*` and `feedback.close` gettext messages.
Server-rendered `partials/messages.html` now translates its four
static status/error/warning/information titles and accessible close button
label through Django i18n in fa/en/ar. The Persian default remains exactly
"انجام نشد", "انجام شد", "نیاز به بررسی", "اطلاع" and "بستن پیام".
The shared template, flash roles, icons, DOM selectors, dismissal duration
and `clean_ui_message` sanitization filter are otherwise unchanged.

A runtime issue also affected all browser-created feedback: within
`feedback.js` the local normalized message variable was named `text`,
shadowing the already-existing translation lookup function `text`.
The close-button aria-label tried to call the string as a function,
preventing successful construction of browser feedback nodes. Renaming
only that local message variable to `messageText` restores creation
of all four tones without changing sanitizer policy, trusted-message
allowlist, fallback messages or any content insertion API. Dynamic body
content still goes through `textContent`, never user-controlled HTML.

A no-database Django suite verifies exact compiled fa/en/ar
server-rendered headings and close labels, original safe flash body
sanitization (including technical-string suppression), stable markup,
and deployment locale defaults. A dependency-free Node VM suite executes
the real browser i18n bridge and feedback script with a simulated DOM
to test construction, localized labels, role/state, vetted en/ar
messages, hostile server messages, historical fa behavior, missing
catalog fallback, close handling and timeout cleanup. The dedicated
CI step runs both alongside all previous Phase 1–3 tests.

This slice deliberately does not change the Persian-only server-side
message body sanitizer or attempt to translate arbitrary server payloads.
Under en/ar an unapproved server flash body can still resolve to the
existing Persian safe fallback; the larger request-locale flash-body
policy is a separately reviewed workstream. No auth/payment/booking,
calendar, phone, migrations, locale defaults, browser-screen-reader
acceptance or production deployment changes occur.

## Phase 3 — Slice 3.17: Safe Server Flash Body Locale Policy

The active server-rendered flash partial continues to call
`clean_ui_message:message.tags`, which preserves the exact Persian
sanitizer and historical visible copy when the language is `fa`.

In English and Arabic, this filter now renders only exact, audited
gettext literals from the **existing 41-key message catalog**. For each
flash tone (error/danger, warning, success, info/neutral), its matching
`feedback.default.*` message is accepted from the original English
msgid or a compiled fa/en/ar translation, then emitted in the active
locale. The existing `validation.notice` and
`validation.server_form` messages are also allowed for error/warning
tones only. No custom message, user name, mobile number, raw exception,
backend error, business-specific detail, HTML fragment, interpolation,
near match or unknown catalog string is automatically translated.

Anything not an exact approved literal uses that tone's existing
localized `feedback.default.*` value. The filter checks the currently
active Django render language and uses bounded `translation.override()`
contexts to avoid leaking locale state. In Persian, the unchanged
`user_error_message` and `user_ui_message` functions continue to
handle all server flash bodies, including legitimate safe domain text.

This is an intentional progressive-localization trade-off: an
untranslated, application-specific server message in an en/ar session
will be replaced by a safe generic message until it has a separately
reviewed i18n contract. The template still autoescapes all text.
No new translation keys or `.po/.mo` changes are required.

The new database-free `apps.main.test_phase3_server_flash_safe_locale`
suite tests actual flash rendering for each tone, both alternate
languages, hostile/technical/PII-like inputs, all approved source
locales, strict matching and tone isolation, language switching,
historical Persian responses, and unchanged default currency/calendar.
The existing server/browser flash regression suite is updated to expect
the new typed fallback in English/Arabic. GitHub CI executes both.

No account/payment/booking/OTP/authorization logic, redirects,
data schema, browser i18n bridge, client feedback sanitizer, or
production deployment is changed. Cross-browser and screen-reader
acceptance are not claimed. Phase 3 remains open.

## Phase 3 — Slice 3.18: Trusted Account and OTP Flash Body Coverage

The strict fa/en/ar server flash policy from slice 3.17 now includes
**eight literal, already-translated account/OTP notices** from the active
`apps/accounts/views.py` code path. Seven approved error/danger
messages cover incorrect mobile/password, missing or expired recovery
session/code, exhausted or exceeded verification attempts, unknown
verification account, and invalid verification form information. The
single approved info notice instructs users to first enter the phone
number and received code. These are existing gettext msgids with
verified compiled fa/en/ar catalog translations; no new translation
catalog entries, currency assumptions or raw business records.

The allowlist is **tone-scoped**: error-only messages are never promoted
to warnings, success or information, and the one info-only message
cannot appear as an authorized error. Each non-Persian flash body
must match a complete catalog msgid or an exact compiled translation
from a supported source language, and is translated into the current
render language. All dynamic/compound text, OTP test codes, customer
numbers, payment details, booking descriptions, provider exceptions,
and unreviewed domain notices still resolve to a generic translated
feedback message appropriate for their tone. English and Arabic
therefore gain useful verified guidance without a general translation
channel for sensitive messages.

The historical Persian server flash sanitizer is untouched. The
existing 41-key browser dictionary, browser feedback, form validation,
authentication/OTP state, lockouts, routes, booking/payment behavior,
Iranian mobile rules and Jalali/timezone defaults are untouched.
No source repository writes and no production deployment are included.

`apps.main.test_phase3_account_otp_flash_locale` adds eight database-free
Django tests covering complete three-source-language and two-target
rendering, compiled gettext reuse, tone isolation, strict dynamic/PII
rejection, unreviewed booking/payment fallback, live source-msgid
contract and historical Persian behavior. The dedicated CI step runs
them alongside all previous Phase 1–3 tests. Browser visual and
assistive-technology acceptance are still pending.

## Phase 3 — Slice 3.19: Reviewed Booking and Service Flash Locales

The booking UI still contains many literal Persian notifications emitted by
active `apps/orders/views.py` flows. These strings are **not** yet available
as compiled translations in the deployed fa/en/ar gettext catalogs. This
slice adds a deliberately bounded transitional presentation-only catalog:
14 exact reviewed phrases in immutable `BOOKING_FLASH_MESSAGES`, with
approved English and Arabic renderings. Ten error notices cover
invalid/incomplete service and stylist selections, unavailable salon
links, incomplete bookings, a newly taken time slot, and unsupported
rebooking. Three success notices cover booking completion, restored
rebooking state and submitted customer reviews. One info notice covers
unavailable previous professionals when rebooking.

The existing `clean_ui_message` template filter first checks its previously
audited gettext key/OTP-message list. Only if no match is found does it
consult the new static booking phrase table; matching is exact across the
Persian source and both approved translations and is **tone-scoped**.
A request in English/Arabic then displays only the corresponding approved
static translation. Any concatenation, user identity, phone number, coupon,
price, payment/gateway state, unreviewed booking notification, or arbitrary
HTML remains rejected and receives the existing generic translated
fallback for that tone. Persian requests bypass this new table and continue
through the unchanged historical sanitizer. No dynamic translation or
external service is introduced.

Unlike the prior account/OTP slices, these 14 reviewed renderings are
currently stored in a small independent Python-only static table instead
of updating `.po` sources without regenerated `.mo` binaries. The table is
intended as a temporary, explicitly audited bridge until gettext catalogs
are regenerated and reviewed together. No runtime language switch or
global gettext behavior is changed.

A dedicated no-database ten-test Django suite exercises real flash HTML
for all 14 phrases from three allowed source-language forms into both
alternate languages; strict tone isolation, danger/error equivalence,
unapproved booking/payment/PII/XSS fallback, typo and concatenation
rejection, locale switching, exact Persian compatibility, source-code
presence and existing business defaults. The previous account/OTP
suite's unapproved-booking examples were updated to remain genuinely
unapproved. GitHub CI runs both suites and the entire earlier Phase 1–3
regression set.

Booking/order/payment, appointment authorization, OTP, price consent,
payment-gateway and SMS logic, migrations, fa/Jalali/timezone defaults,
and production deployment are unchanged. Browser screenshot, keyboard
and screen-reader acceptance are still pending; Phase 3 remains open.

## Phase 3 — Slice 3.20: Rebooking Journey Parity and Gettext Migration Readiness

This slice strengthens the customer rebooking journey using an
executable, no-database test suite. The real authenticated GET view is
exercised with fake order retrieval and stylist-selection resolution
only. Tests verify that unauthenticated visitors cannot fetch bookings;
owner-scoped order lookup remains pinned to the active user; an
incomplete salon or invalid/empty prior selections return to the
customer's appointment history without modifying booking-session data.
A valid rebooking resets only stale date/service/reschedule choices,
preserves unrelated session values, restores the selected salon and
professional, and continues to the date/time selection page. If the
previous professional has become unavailable, the existing `any`
selection still triggers the alternate info notice, while an intact
professional selection triggers the success notice. The tests
cross-check fa/en/ar display of both phrases and their strict tone and
untrusted-user-data fallback contracts. No backend booking, order,
payment, account or permission logic has been edited.

The Phase 3.19 booking translation table is still a transitional
**display-only** asset. A new pure, deterministic and fail-closed helper,
`preview_booking_gettext_appendix(language, existing_po)`, produces
reviewable `.po` draft entries for all 14 exact, tone-scoped booking
phrases in fa/en/ar. It checks language headers, rejects any duplicate
source msgid, rejects unsupported languages and unsafe/interpolated
strings, and does not write to disk or mutate Django locale state.
A separate database-free test suite verifies each generated msgid and
translation, duplicate refusal, deterministic previews, existing
`.po` and `.mo` artifacts, and preservation of the current runtime.

**The gettext migration is prepared but not activated in this slice.**
Its release gate remains an atomic update to each of the three `.po`
sources **and the three matching compiled `.mo` binaries**, together
with tests proving the compiled `translation.gettext()` values and the
same fail-closed flash boundary. Publishing `.po` changes alone, or
removing the existing static table first, would cause a mixed runtime
and is therefore expressly prohibited. The pure preview helper is
not used by live request processing.

GitHub Actions executes both new suites alongside all existing
Phase 1–3 checks. No migrations, production deployment, changing
payment gateways, SMS, appointment prices or Iranian default locale,
currency/timezone/calendar, browser screenshot acceptance or
screen-reader validation are claimed. Phase 3 remains open.

## Phase 3 — Slice 3.21: Atomic Compiled Booking Gettext Migration

The 14 previously reviewed static booking/service flash messages have now
been migrated from their temporary runtime translation table to native
Django gettext. An **atomic Git tree commit** updated all six relevant
catalog files together: `locale/{fa,en,ar}/LC_MESSAGES/django.po` and their
matching `django.mo` compiled binary catalogs. Each language catalog now
contains the 14 reviewed, exact original-Persian msgids and its reviewed
translations, preserving all previous entries and the existing Arabic
pluralized OTP translations. The Persian msgstr values exactly match the
historical Persian text.

`loomera/globalization/booking_flash_messages.py` now contains only an
immutable **tone-to-source-msgid allowlist** (10 error, 3 success, 1 info).
It no longer carries English/Arabic runtime translations or the former
`trusted_booking_flash` lookup. The shared server flash display filter
reuses its existing strict exact-match gettext policy: it accepts one of
these approved msgids or one of their exact compiled fa/en/ar translations
**only for the matching flash tone**, then resolves the active target
locale using `translation.gettext`. The already-present account/OTP
allowlist and generic validation messages are unaffected. Near matches,
unreviewed booking/payment/checkout messages, user/customer details,
telephone numbers, exception text and markup are still rejected for
en/ar and mapped to an existing generic safe fallback. For fa, the
original Python user-message sanitizer remains authoritative.

The previous draft-only migration helper has been replaced by a
**read-only PO audit** function that verifies the complete set of
approved identifiers, correct locale headers, uniqueness, non-empty
safe translations and unchanged fa text. The Django migration suite
asserts that all 14 compiled `translation.gettext` values in each of
the three languages exactly match their checked-in PO entries; test-only
fixtures independently verify the previously reviewed en/ar wording.
All earlier runtime flash, OTP, pluralization and rebooking tests now
run against the native compiled catalogs instead of the transitional
table. This migration removes the temporary **runtime translation
table**, not the essential exact allowlist safety boundary.

The dedicated CI step validates PO/MO parity, booking flash rendering
and rebooking security alongside all previous Phase 1–3 checks. No
business/booking/payment, checkout consent, SMS/OTP, session authorization,
database schema, Iranian mobile/Jalali/timezone/currency defaults,
deployment or source-repository writes are introduced. Real browser
visual and assistive-technology acceptance remains outstanding. Phase 3
is still open.

## Phase 3 — Slice 3.22: Checkout, Settlement and Rescheduling Gettext

Nineteen additional **exact, user-facing static** flash strings used by
active `apps/orders/views.py` routes are now approved and available
through native Django gettext, with original Persian plus reviewed
English and Arabic text. The breakdown is nine error messages
(including on-site settlement eligibility, cancelled/invalid payable
bookings and rescheduling failures), five information notices
(already-settled or in-progress payments, receipt recording and coupon
removal), three warnings (taken time slot, changed checkout
price/financial preview requiring renewed confirmation, and invalid
coupon), and two successes (coupon applied and appointment rescheduled).

All six `locale/{fa,en,ar}/LC_MESSAGES/django.po` and `django.mo`
files were updated together in an atomic Git tree commit, retaining
the previous **171** catalog entries and adding exactly **19** (190
entries per language). The active display filter uses the immutable
`CHECKOUT_FLASH_MSGIDS` tone-scoped allowlist alongside the existing
booking, OTP and generic message allowlists. Each exact approved
Persian msgid or corresponding compiled English/Arabic translation is
translated into the current request locale only when the flash tone
matches. Existing status markup and escaping remain unchanged.

**Security and business policy:** no submitted coupon codes, personal
identifiers, monetary amounts, exception contents, payment gateway
responses, interpolated text or arbitrary operational messages were
added to the trusted boundary. Modified/concatenated strings and
cross-tone copies in en/ar still fall back to the existing localized
generic message. Static notices about payments do **not** authorize,
calculate, confirm, collect or settle payments; no checkout, payment,
rescheduling or order backend logic was changed. Persian flash bodies
still use the original server sanitizer with the same default copy.

A new database-free regression suite uses the actual server flash
partial to verify all 19 compiled messages for fa/en/ar, the expected
190-entry MO headers, read-only PO audit, existing 14 booking notices,
strict tone isolation, warning alert roles, sensitive-data rejection,
independently pinned critical financial notices and unmodified Iranian
defaults. Prior unapproved-copy tests are adjusted to check genuinely
unapproved messages, not newly reviewed literals. CI runs the new
suite alongside all prior Phase 1–3 checks.

There is no migration, SMS/OTP change, production deployment or source
repository write. Real browser and assistive-technology acceptance
remain outstanding; Phase 3 is not closed.

## Phase 3 — Slice 3.23: Remaining Checkout Error Messages

Five additional exact, static error notices from the active checkout flow
are now covered by the existing gettext boundary: missing time-selection
data, malformed time-selection data, preview-only requests that must not
create a booking, and two generic payment-start fallback messages. These
messages are approved in Persian, English and Arabic and are included only
in the immutable error-tone allowlist.

All three native `django.po` catalogs and their matching compiled
`django.mo` files were updated together in one atomic Git tree commit.
The existing 190 entries were preserved and five were added, yielding
195 entries per language. The cumulative checkout allowlist contains
24 messages: 14 errors, five information notices, three warnings and
two successes. The read-only catalog audit and database-free regression
suite verify the exact source IDs, all compiled locales, MO entry counts,
tone isolation, escaping, generic fallbacks and unchanged checkout guards.

No booking or payment business logic was changed. The preview-only guard
still prevents creation of a reservation when the request only refreshes
the preview. No deployment is included. Browser visual review and
assistive-technology validation remain open Phase 3 exit criteria.

## Phase 3 — Slice 3.24: Payment Completion Flash Locale Parity

Two remaining static checkout success notifications have been reviewed
against their **actual issuing branches** and localized in the compiled
fa/en/ar Django gettext catalogs. The first is issued after wallet
withdrawal, successful wallet payment recording and the order being
marked paid. The second is issued when the reservation is confirmed
and scheduled with the order still in the `pending` state: **payment
will be made at the salon**, and must not be described as already
collected. Both reviewed messages have identical legacy Persian
sources, distinct English/Arabic copy, and are approved only for
success-tone server flashes.

All three `django.po` files and the corresponding three compiled
`django.mo` files were updated in one atomic Git commit: the existing
195 messages remain and two were added, for **197 catalog entries per
language**. The immutable checkout allowlist grows from 24 to 26
messages (14 errors, 5 information, 3 warnings and 4 successes). The
existing strict complete-string and tone match, generic en/ar fallback
for any user data or appended payment amounts, and historical fa
sanitizer remain unchanged. The read-only PO audit and Django rendered
flash suite now verify all 26 entries and the compiled MO payloads.

Three new DB-free regression methods independently pin wallet versus
pay-at-salon wording, check that the real issuing view only presents
the wallet success after payment/order state changes and the on-site
success while payment remains pending, and verify that augmented
phone, wallet, amount and gateway-like details are never displayed.
The existing Phase 3 checkout gettext CI step automatically runs these
tests together with the full previous Phase 1–3 checks.

There is no change to business/order/payment logic, transaction
authorization, idempotency, OTP, Iranian locale defaults, database
migrations or production deployment. Physical browser, RTL/LTR visual
and assistive-technology acceptance remain outstanding before closing
Phase 3.

## Phase 3 — Slice 3.25: Booking Bidirectional and Accessibility Guards

This slice addresses concrete **presentation-only** issues in the
customer booking/checkout journey, without changing transaction
processing or POST form semantics.

Booking headers, professional/date selection and appointment-detail
back-arrow icons now carry a narrow `data-booking-back-icon` hook.
`bidirectional_booking.css` mirrors those arrows **only when the
actual deployment document has `html[dir="ltr"]`**. Persian/Arabic
RTL remains the original rightward icon direction. DOM/tab order,
routes, history and layout order are unchanged. A scoped stylesheet
loaded after the existing shell layer also isolates Latin coupon
codes inside mixed Persian/Arabic descriptions with `bdi dir="ltr"`
in the preview, checkout and payment result templates; currency,
discount calculations and original code values are untouched.

The booking preview's single available payment option previously
rendered a focusable screen-reader-only radio as a sibling of its
visual card, not inside any label. It is now nested inside a real
`label[data-payment-option]`, retaining its name, checked state
and submit value. This restores a readable accessible name, keyboard
label activation and compatibility with the existing JS selector
that reads `option.querySelector('input[type="radio"]')`. Focus
indication is scoped to that payment option. Multi-choice
RadioSelect behavior is not modified.

Both checkout and reservation-preview error summaries now use
Django BoundField `auto_id + "_error"` IDs. Native Django coupon
widgets refer to their error ID; the hand-built preview coupon input
sets explicit `aria-invalid`, conditional `aria-describedby` and
`dir="ltr"`. Django's RadioSelect does **not** attach an error
description by default, so the payment `radiogroup` now conditionally
sets `aria-invalid` and `aria-describedby` when validation fails,
including the labeled single-choice payment card. Associated inline
errors have `role="alert"`. Coupon/payment validation and server
decisions are unchanged.

A ten-test DB-free Django suite validates the actual bound-widget
error references, template-rendered preview input states, source
markup for the labeled single payment radio, JavaScript hook parity,
scoped CSS and default fa/Jalali/timezone invariants. CI runs the
suite alongside existing Phase 1–3 tests.

These automated **structural/render checks are not a substitute**
for acceptance in real browsers using screen readers and keyboard
navigation, nor for visual review at varied viewport sizes. Those
Phase 3 exit gates remain open; no production deployment is included.

## Phase 3 — Slice 3.26: Booking Specialist and Date/Time Journey Hardening

This cohesive slice reviews the **actual interactive specialist → date/time →
preview/checkout** journey, rather than another small static translation table.

The booking date-time page previously inserted the serialized
`stylist_selections_json` using a Django `|safe` HTML attribute. A
specialist/service name with a quote or HTML token could disrupt that
transport. It now uses Django's `json_script` serializer and parses
the resulting typed JSON string before mapping the existing selections.
Names and selection data are preserved byte-for-byte as user content;
validation still rejects a non-list payload. Crucially, the existing
reservation POST structure, session storage keys, backend availability
and conflict revalidation, and payment/checkout safeguards are untouched.

The date-time JS builds portions of the UI dynamically via `innerHTML`.
User-provided service/stylist labels and rendered time labels are now
escaped at that **display boundary**, leaving stored request/service
fields intact. A selected time slot re-render retains keyboard focus
on its replacement button, and visually isolates clock ranges using
LTR spans without altering times or the Jalali calendar. The existing
`aria-pressed` time-slot contract is retained.

Stylist-choice buttons previously mixed `role=listitem` and
`aria-selected` with native toggle-button `aria-pressed`. These
are now ordinary named buttons within labeled `role=group` regions,
using the single supported pressed state. No selected stylist,
availability option, POST value, price or enabled/disabled logic changes.

Both booking browser scripts now format displayed digits/amounts
according to the active document's fa/en/ar language, defaulting to
the historic Persian appearance when no language is supplied.
Numeric amounts, service lengths, ISO dates, Jalali↔Gregorian
conversion, validation and payment calculations are unchanged.
Some existing customer-flow copy remains Persian and still needs
full localized UI acceptance; this slice does not claim to finish
all translation work.

A new DB-free test suite checks real Django-safe JSON serialization
with apostrophes/angle brackets and mixed Persian/Latin names,
escaped dynamic markup sites, focus restoration, accessibility
semantics, per-language digit configuration, preserved POST and
stale-availability contract, and fa/Jalali/Tehran defaults.
CI syntax-checks both JavaScript files and executes these checks
together with the earlier checkout accessibility regression suite.

This does **not** constitute a real browser, screen-reader, zoom or
visual RTL/LTR acceptance test. Those Phase 3 exit requirements
remain open. There is no production deployment or backend mutation.

## Phase 3 — Slice 3.27: Integrated Exit Evidence and CI Efficiency

The preceding slices added localization, bidi, finance-safe flash copy and
booking DOM protections. This slice consolidates the outstanding exit review
into a **documented acceptance matrix**, instead of claiming CI is a
substitute for browser or screen-reader tests.

The booking date/time dynamic HTML is now escaped at a single well-defined
DOM output boundary: switcher subtitles contain raw user-facing time strings
until rendering, while picked summaries remain raw until their HTML sink.
This prevents double escaping and keeps hostile specialist names/time
strings from being interpreted as HTML. Time-slot choice containers use an
accessible `role="group"` for their native pressed buttons rather than
advertising a list without list-items. Underlying bookings, ISO dates,
Jalali conversions, form POST bodies and financial operations remain
unchanged.

A new no-dependency Node runner executes real production JavaScript
helpers with a small DOM stub: malicious names/time strings, single-pass
HTML escaping, pressed-state and keyboard focus after a slot re-render,
and fa/en/ar digit/amount parity are checked for actual behavior.
Django's new exit-evidence audit verifies eight required end-to-end
flows, all three directions and viewports, explicit release blockers,
and preserved historical defaults. An acceptance matrix and release
procedure are maintained in
`docs/globalization/PHASE3_EXIT_MATRIX.json` and
`docs/globalization/PHASE3_EXIT_AUDIT.md`.

Three **duplicate** CI invocations of existing Django test suites are
removed; all four affected test modules still run exactly once via
the existing booking/compiled-catalog gates. The consolidated gate
includes the Node runner and the new exit evidence tests. Other
CI test coverage and release checks remain in place.

**Open blockers:** real-browser screenshots, responsive/zoom,
hands-on keyboard tests, NVDA/VoiceOver, additional legacy dynamic
customer text localization and production approval. No manual results
or deployed success are implied; Phase 3 remains unclosed.

## Phase 3 — Slice 3.28: Compiled Interactive Booking UI Gettext

After the broader Phase 3.27 exit audit, the specialist and date/time
browser steps still displayed a substantial amount of static Persian
UI text in their dynamic controls even under an English or Arabic
document locale. This coherent slice adds **37 reviewed UI-only
English-source message identifiers**, mapped to original Persian and
reviewed Arabic translations in the project's **native compiled
fa/en/ar Django gettext catalogs**. All six PO/MO files were updated
atomically, growing from 197 to 234 entries per language. The
original 41 generic browser validation/feedback message identifiers
remain completely unchanged.

The existing request-scoped `interactive_messages` context processor
now emits the reviewed `booking.*` keys in its existing safe Django
`json_script` payload. The browser bridge accepts the bounded
namespaced values as **display-only text** and does not promote them
to `LoomeraFeedback.isTrustedMessage`. This prevents a translated
short label such as "Morning", "Service" or "Selected" from becoming
a newly trusted server flash. There is no runtime translation
dictionary, interpolation with user or payment values, or generic
translation of backend exceptions.

The actual specialist and datetime browser scripts use this shared
compiled catalog for navigation labels, selection counts, duration
and currency suffixes, summary states, daypart names, calendar
controls, time-slot headings and CTA buttons. Static initial
Continue/Choose Time/No Selection states also use Django's native
`{% trans %}` tags, preventing an initial flash of untranslated
copy on those controls. The Persian fallbacks remain available
without JavaScript/catalog bootstrap. The scripts still escape
translated text before placing it in a generated HTML string,
while dynamic customer/stylist names are still escaped at the
existing sink. Stored ISO times, amounts, Jalali conversions,
availability API, POST data and business behavior are unchanged.

A new DB-free Django suite checks 37 exact PO/MO equivalents
for all three languages, original Persian wording, immutability,
the 41-key generic catalog boundary, context serialization
and initial template translations. New Node tests execute the
actual browser bridge and real booking UI helpers in fa/en/ar,
verify the strict flash trust boundary and ensure unknown,
oversized, malformed and unsupported values fail closed. CI adds
one integrated gate on top of all previous Django and Node suites.

**Outstanding:** Many older hardcoded Persian explanatory paragraphs
and conditional backend responses on the booking pages are not yet
covered, and real-browser visual, keyboard, zoom and screen-reader
acceptance remains open. This patch is not Phase 3 sign-off and
includes no Production deployment.

## Phase 3 — Slice 3.29: Booking Journey Static and Conditional Gettext

This is a **larger, cohesive booking customer-flow localization batch**:
shared booking progress header, staff selection and availability/empty
states, date/time selection and multi-day planning hints, review summaries
and screen-reader labels, direction-sensitive names, plus compiled catalog
and runtime regression coverage.

Exactly **58** newly reviewed English-source gettext messages with
historical Persian and approved Arabic renderings are recorded in
the native `locale/{fa,en,ar}/LC_MESSAGES/django.po` files and their
matching compiled `django.mo` artifacts **atomically**. Each language
catalog now contains 292 entries, preserving the prior 234. Static
templates use native `{% trans %}` output on first paint. The **17**
new dynamic calendar-planning keys live in the immutable
`BOOKING_JOURNEY_MESSAGE_IDS` namespace and are resolved by the
existing request-scoped `interactive_messages` browser bridge.
The generic 41-key message set and prior 37-key booking UI set
remain unchanged. Total scoped browser keys are now 95.

The calendar translates unavailable/suggested-day badges, same-day
and split-day explanatory copy, action labels, 90-day availability
hint, selected times and multi-day summaries. Source dates, slot
quantities, JavaScript state, availability API requests, rescheduling
authorization and the JSON submitted at checkout are unchanged.
Translated text inserted in dynamic markup is escaped at the HTML
sink. A guarded browser label lookup rejects empty, oversized,
markup-like or NUL-containing values, falling back to the original
reviewed Persian display copy; it never promotes `booking.*`
messages into trusted server flash or payment messages.

The shared progress header and specialist/date-time templates
translate title, step labels, relevant help copy and initial
empty states. RTL staff cards remain unchanged; English/LTR
aligns option text to the logical start. Mixed Persian/Latin
service and professional names have isolated direction
(`dir="auto"`) while their stored identifiers remain intact.
This improves structural locale behavior, **not** an actual
browser or screen-reader accessibility sign-off.

New database-free Django tests validate all 58 compiled PO/MO
entries, 17 immutable calendar keys, all 95 scoped browser keys,
fa original copy, template translations, mixed-direction display
and security boundaries. Executed Node tests exercise the real
browser bridge and booking label helper in fa/en/ar, validate
markup rejection and original fallback. The existing full Phase
1–3 CI suite also remains mandatory.

Remaining legacy checkout/preview explanatory paragraphs and
some user-provided or backend-generated copy still require
separate locale/security review. The Phase 3 acceptance matrix
continues to mark real-browser visuals, hands-on keyboard tests,
screen-reader use, responsive zoom and deployment approval as
unperformed. No production deployment is included.

## Phase 3 — Slice 3.30: Native Preview and Checkout Gettext

The reservation preview and checkout pages previously kept most visible
headings, coupon controls, payment explanations and financial labels in
Persian even when the deployment locale was English or Arabic. This
cohesive batch migrates 58 reviewed strings into the native compiled
fa/en/ar Django gettext catalogs, increasing each catalog from 292 to
350 entries. Both templates now use native `trans`/ `blocktrans`
on first paint, including the page title/subtitle, multi-day details,
service summary, coupon feedback, payment method copy, amount labels
and mobile/desktop finalization controls.

The checkout form's payment-method and coupon field labels/placeholders,
online/wallet/pay-at-salon choice labels, and beta/first-visit validation
messages now use lazy gettext. The choice values (`online`, `wallet`,
`pay_in_salon`), checkout POST action names, coupon normalization,
payment eligibility rules, idempotent submit guard and all price/discount
calculations remain unchanged. Service-discount confirmation uses
Django `blocktrans` interpolation for the amount rather than composing
translated fragments around a financial value. Coupon tokens remain
isolated with the existing LTR `bdi`; currency unit uses the reviewed
existing `toman` catalog key.

Five new database-free Django tests audit all 58 exact source entries in
all three compiled catalogs, validate 350-entry PO/MO parity, verify
translated dynamic amount interpolation, exercise localized lazy form
labels and validation messages, and protect the existing checkout action
contract. The CI workflow now runs this dedicated suite alongside the
existing bidirectional and checkout-flash regression suites.

Backend-generated cancellation-policy copy, dynamic salon/coupon titles
and payment gateway results remain contextual data and are not rewritten
by generic template translation. This patch is **not** manual Phase 3
acceptance or deployment approval: the exit matrix remains
`BLOCKED_MANUAL_ACCEPTANCE`, with real-browser visuals, keyboard,
screen-reader, responsive zoom and deployment/rollback approval still
open.

## Phase 3 — Slice 3.31: Post-Checkout, Payment Outcomes and Appointments

After Phase 3.30 localized booking preview/checkout, this larger slice
covers the **next customer journey**: payment result, the upcoming/past
appointments index and its cards/empty states, and key appointment-detail
status labels. The financial outcome branches remain semantically
distinct: a confirmed supplementary salon payment is not conflated
with an active but *unpaid* pay-at-salon appointment, gateway failure
or pending manual reconciliation.

An explicitly reviewed fa/en/ar source ledger lives in
`docs/globalization/PHASE3_31_MESSAGE_REVIEW.json` (83 static phrases).
Seven existing native msgids are reused without modifying their
previous translations. The other **76 newly reviewed msgids** are
compiled atomically into all three Django `.po/.mo` catalog pairs:
**350 → 426 catalog entries per language**. No private customer,
coupon, payment reference, account balance or gateway error value is
used as a gettext source string.

The rendered pages use Django's native `trans` tags for first paint,
rather than introducing another browser translation map. Main payment
outcome headings, warnings, status descriptions, payment and booking
labels, follow-up actions, empty-state text, upcoming/past headings,
and selected appointment progress labels now use native gettext.
Customer order references and gateway tracking codes have local
`bdi dir="ltr"` boundaries; the existing coupon-token LTR boundary
and monetary calculations remain unchanged. Booking cards distinguish
`Paid` from `Pay at salon` based on the original server state.

Seven database-free Django guards check the reviewed ledger, compiled
PO/MO integrity, active fa/en/ar translations, distinct financial
outcome templates, native first paint, accessible labels/announcements,
safe reference numbers, original server settlement contracts and
the unchanged Phase 3 manual release gates. Existing checkout and
booking locale tests now expect 426 total compiled entries but retain
their original allowlists, flash safety checks and business assertions.

**Not translated generically:** server-computed gateway/pending text,
customer- or salon-provided names, per-booking cancellation conditions,
and some legacy appointment-detail dynamic statuses. These require
separate, context-specific review; generic string replacement would
risk misleading a customer about the payment state. Real browser,
RTL/LTR visual review, keyboard, NVDA/VoiceOver and 400% zoom
acceptance remain **unperformed**. There is no Production deployment.

## Phase 3 — Slice 3.31: Financial Result / Appointment Bidi Integrity

This cross-screen patch addresses the **payment confirmation and
appointment details** journey after Phase 3.30 checkout localization.
Machine-generated order numbers, provider settlement references and
gateway tracking IDs now use local `<bdi dir="ltr">` isolation on
the confirmation page. User-facing salon names, payment status/method
labels, providers and split-day date/time strings use
`<bdi dir="auto">`. The customer appointment detail page similarly
isolates the displayed order number, phone number and service time
range; importantly, the raw `tel:` URL value is preserved.

Isolation modifies neither the displayed machine value nor the
Django autoescaped source, and does not change payment status
decisions, totals, wallet accounting, gateway callbacks, coupon
codes, refund logic, access control or reservation persistence.

Seven database-free Django tests pin that contract, live-region
and financial branch invariants, historic fa/Tehran/Jalali defaults,
and the continued absence of manual browser/screen-reader
acceptance. CI runs the suite alongside prior booking bidi
regressions. Visual browser and NVDA/VoiceOver tests are still
required; **not Phase 3 sign-off or Production deployment**.

## Phase 3 — Slice 3.32: Dynamic Financial Status, Cancellation and Refund Copy

This slice localizes the **finite server-generated financial states** used
on the payment-result and appointment-detail pages. A reviewed
`loomera/globalization/financial_status.py` maps known payment, order,
payment-method and provider enum values to approved English gettext IDs.
Unknown codes return a localized generic label; arbitrary gateway status
strings are never echoed to customers. No database choice, model field,
stored order value or payment transition was changed.

The payment result now resolves state and method labels at request time.
The pending-review and expired-checkout context helpers use native gettext
for their title, body and next-step hints. Raw provider verification text
stored in `payment.meta["verify_pending"]` is no longer appended to the
customer-facing message; it remains operational metadata. This avoids
showing potentially technical or untrusted provider payloads as customer
copy while preserving the existing pending/retry/review decisions.

Cancellation JSON responses, refund-success wording, confirmation-dialog
and network fallback messages now follow the active request locale.
Generic cancellation policy text interpolates the existing hours and
refund percentage using reviewed parameterized gettext strings. Salon-
authored policy text and stored cancellation reasons remain untouched
business data and are not machine-translated. Refund amounts and timestamps
are parameterized; cancellation continues through the original atomic
`cancel_order_with_financials` path and ownership-filtered endpoint.

The appointment detail finance summary now localizes fixed labels and
finite payment-status text while preserving salon campaign titles, coupon
tokens, recorded cancellation reasons, calculated amounts and Jalali date
values as data. Payment-result status/method/provider labels use the same
reviewed helpers. Three compiled catalogs contain **477 entries each**
(51 additional reviewed source IDs, with the existing `Coupon code`
translation reused). The new database-free Django suite checks all three
PO/MO catalogs, exact translations, known/unknown state codes, pending
provider-message isolation, cancellation-policy interpolation, template
compilation and release-gate integrity.

This is structural and automated evidence only. Real-browser visual,
keyboard, screen-reader, responsive-zoom and release approval remain
open. No payment gateway is called, no refund is issued, no migration is
created and no Production deployment is performed.
