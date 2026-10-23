# Phase 2 Engineering Exit — Deployment Branding Foundation

**Assessment:** 2026-10-23. **Baseline:** `main` at `1a23642516f7b7573d630af42bf8bcba8340bd82` (PR #70 merged).  
**Decision scope:** engineering/source and CI exit only — **not** a production or independent browser acceptance certificate.

## Exit Decision

**Engineering exit: conditional GO, subject to the consolidated PR's final-head CI success and pinned review.** Phase 2 can be marked engineering-complete **only after** these checks pass and the final commit is on `main`. Otherwise it remains open, and Phase 3 remains blocked. Do not equate this decision with a deployed buyer installation.

The Roadmap's three exit criteria are covered by documented central settings and existing brand tests, plus the new `apps/main/test_phase2_buyer_brand_smoke.py` integration-style smoke. The new test adds coordinated *default → alternate buyer → default* checks across brand identity, assets, colors, renderer context, public/SEO metadata, email sender/contact, calendar identifiers, and independent runtime state. An environment-backed settings import runs for default and buyer values in separate processes. A temporary staticfiles directory supplies buyer-owned logo, recovery image, favicon, social asset, and webmanifest and verifies Django staticfiles discovery. It does not execute a deployed site, run an actual SMTP delivery, browser screenshot check, or collectstatic.

## Roadmap Exit Matrix

| Exit criterion or protected regression | Recorded engineering evidence | Important limitation |
| --- | --- | --- |
| Buyer changes supported brand inputs without editing app templates/code | `Phase2BuyerBrandSmokeTests`: real settings env import (default/buyer), overridden runtime config snapshots, branded logo/head rendering and Django staticfiles discovery for buyer assets | Tests simulate a packaged buyer staticfiles directory and a Django process; no actual buyer deployment |
| Loomera defaults preserved | Snapshot and rendering regression suites, default logo paths/manifest colors, isolated default → buyer → default cycle | No browser/visual pixel comparison |
| One brand setting source of truth | `loomera/settings/base.py` controls defaults and validators; frozen identity/asset/color configs and single global request-template context are tested | Buyer-specific production secrets must be configured by its operator |
| Email sender and contacts | `SharedEmailSenderIdentityTests` cover both plain-text mail delivery consumers with alternate and default From identity; buyer smoke checks sender/support/partner/marketing config | No real SMTP send; HTML email content is a separate contract |
| Public URL/SEO and machine-readable identity | Snapshot public/site URLs, service schema provider identity, logo/favicon/manifest/OG metadata rendered with alternate buyer | Locale-specific SEO/hreflang intentionally deferred to later phases |
| Color/token behavior | Existing color/token regressions and smoke of changed primary/background/browser metadata | No interactive theme screenshot |
| Calendar/product identifiers and behavior | Calendar snapshot plus existing ICS tests; buyer smoke verifies product metadata and unchanged language/timezone/calendar/payment runtime | No calendar/timezone migration, localization or currency reinterpretation |
| Static asset serving and webmanifest | Temporary buyer asset package resolves under Django finders; default manifest stays untouched and buyer-provided manifest carries its own name | Actual deployment build/collectstatic and CDN cache not tested |

## Two Legacy HTML Email Layouts: Static Consumer Classification

The repository contains `templates/email/loomera_email_base_rtl.html` and
`templates/email/loomera_minimal_transactional.html`. They retain historical
literal `Loomera` fallbacks and footer copy. An audited set of the principal
notification/account/orders/messaging/dashboard modules does **not** reference
these layout names. A new CI test scans all application/project `.py` files
and Django `.html` templates (excluding test fixtures, migrations, and the
two layouts themselves) for their static filename stems.

**If that scan passes, no direct static reference exists in the scoped runtime
source, so these layouts are classified as legacy/unreferenced-by-static-code;
they are not treated as active email-output identity defects.** This does
*not* rule out dynamically constructed template names, separate external
callers, or future activation. Before any future use, explicitly supply a
deployment-safe brand rendering context or a request-independent brand accessor,
and test default/buyer HTML plus delivery and consent behavior. The existing
`send_mail` notification paths send plain-text body content with a central
From address; no change to delivery/auth/consent occurs in this phase.

This static classification is an engineering boundary, not a claim that
`Loomera` should disappear from stable internal module names, CSS, legal
operator identity, provider trademarks or unused fallback templates.

## Verification Procedure and Gates

CI must run both the existing settings/release tests and the **new dedicated**
`Phase 2 buyer-brand smoke and email layout reference audit` step:
```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.main.test_liara_deployment_config --failfast
python manage.py test apps.main.test_production_settings_hygiene apps.main.test_build_release_archive --failfast
python manage.py test apps.main.test_phase2_buyer_brand_smoke --failfast
```

The last step requires no database migrations or external provider secrets.
Final-head CI success and independent diff/contract review are both necessary
before recording the engineering exit as GO. A failing reference scan indicates
a real source consumer to investigate and prohibits claiming dormant status.

## Next Phase and Production Boundary

If the engineering gate passes, Phase 3 may start on a **separate, scoped PR**
for i18n runtime and bidirectional shell foundation under
`docs/globalization/ROADMAP.md`. Phase 3 does not retroactively reassign
branding, alter payment/data semantics, or imply production rollout.
Production/release acceptance remains a **separate outstanding gate**:
real buyer environment/secrets, staticfiles build/hosting, email/provider
configuration, browser QA, contact-domain checks, manifest validation, and
deployment rollback testing must be verified by the actual operator.

**No production deployment was made by this audit or the engineering smoke.**
