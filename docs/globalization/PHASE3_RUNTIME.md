# Phase 3 — Slice 3.1: Request Locale and Bidirectional Shell

**State:** Implementation candidate subject to PR GitHub CI and merge.  
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
