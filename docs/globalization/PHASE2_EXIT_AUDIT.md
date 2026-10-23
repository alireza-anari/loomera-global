# Phase 2 Exit Audit — Deployment Branding Foundation

**Assessment date:** 2026-10-23  
**Repository:** `alireza-anari/loomera-global`  
**Reviewed main baseline:** `482f3c015ec3db7b36be32ee80cebe252c17d9e2` (merged PR #69)  
**Scope:** evidence-based Phase 2 exit readiness; no deployment, locale switch or Phase 3 implementation.

## Decision

**Not yet signed off (NO-GO for declaring Phase 2 complete).**

The core configurable deployment-brand architecture is implemented and has substantial
regression coverage. The original Roadmap Phase 2 exit criteria, however, require
a buyer to change the supported brand inputs **without editing unrelated source files**
while preserving Loomera behavior. Repository-level tests substantiate many
individual contracts, but the complete buyer acceptance path has not been
independently exercised here. There are also two legacy HTML email layouts
with literal `Loomera` fallback/copy whose rendering consumers and deployment
behavior have not been established in this audit. They should be classified,
not automatically rewritten through web-request context processors.

This decision is a gate, not a claim that production branding is broken. The
Phase 3 dependency remains closed pending a positive exit sign-off.

## Roadmap Exit Criteria and Evidence

| Criterion / regression area | Status | Concrete evidence and boundary |
| --- | --- | --- |
| Central identity and contact settings | **Verified at source/test contract level** | `loomera/branding/config.py` exposes a frozen fresh snapshot of 13 resolved Django settings; `loomera/settings/base.py` owns defaults. `SharedBrandConfigurationBoundaryTests` covers default and buyer values. |
| Shared web template context | **Verified at source/test contract level** | `loomera/branding/context_processors.py` supplies identity, assets, and colors to request-rendered Django templates. `SharedBrandTemplateContextTests` and surface tests check compatibility. |
| Logos, favicon and brand artwork | **Verified at source/test contract level** | `loomera/branding/assets.py`, `partials/brand/logo.html` and `partials/brand/head_assets.html` select package-owned staticfiles paths. The new recovery-logo setting extends the asset snapshot from 25 to 26 fields while retaining the preexisting default image path. Asset import and rendering tests are added in this batch; their CI result must be recorded before sign-off. |
| Colors and theme metadata | **Verified at source/test contract level** | `loomera/branding/colors.py`, settings validation, semantic tokens and associated tests preserve default colors with alternate-brand coverage. |
| Sender identity | **Verified for two tested email delivery consumers; broader HTML layouts unclassified** | `apps/notifications/delivery.py` and `apps/orders/notification_delivery.py` obtain the snapshot sender address; `SharedEmailSenderIdentityTests` guards empty, alternate, opted-out and failure paths. Two HTML layouts still contain fixed fallback/copy; usage/dispatch has not been verified. |
| Public URLs, API/SEO and calendar product metadata | **Verified at targeted source/test level** | The brand snapshot includes public base/site URLs and calendar identifiers; API metadata, service schema, quick-link/calendar/PDF surfaces have targeted hygiene regression classes and documentation. This is not a claim of jurisdiction-aware locale SEO, which belongs to Phase 16. |
| Existing Loomera defaults and independent buyer overrides | **Verified by targeted test suites, not an end-to-end buyer install** | CI on PR #68 and PR #69 passed; tests cover defaults, sequential names, Latin/Persian independence and escaping across various surfaces. This batch adds recovery artwork equivalence and buyer override cases. |
| Buyer install/acceptance from configuration | **Open** | No independently recorded deployment-style buyer smoke run that packages custom assets, configures the supported identity/contact/color/URL inputs, renders representative flows, and checks default compatibility end-to-end. |

## Specifically Deferred or Not Evidence of Failure

- `templates/accounts/remember_password.html` is the verified active recovery entry route. The five additional legacy recovery templates are handled conservatively for asset configuration but **must not** be described as verified live routes; no URL ownership was found in the inspected `apps/accounts/urls.py`/active `RememberPasswordView`.
- `templates/email/loomera_email_base_rtl.html` and `templates/email/loomera_minimal_transactional.html` still have literal brand strings. Determine whether and how those layouts are rendered, and whether their contexts support brand snapshots, **before** applying any replacement. SMTP "From" identity and message HTML identity are separate contracts.
- Legal operator identity, jurisdiction-specific policies, third-party provider trademarks, stable `loomera-` CSS/JS identifiers, customer data and other embedded names are **not** automatically interchangeable with the deployment brand.
- `site.webmanifest` is a static file. Buyer-provided replacement content and icon paths are documented responsibilities, not an automatic rewrite of the default manifest.
- Locale switching, LTR/RTL runtime, translation catalogs, country/currency/timezone/provider activation, and email content localization remain outside Phase 2. They must not be inferred from branding tests.
- GitHub CI validation is not a production/browser acceptance test. No production/staging deployment was performed in this work.

## Exit-Gate Actions

1. **Conclude current consolidated PR:** verify final-head GitHub Actions checks and strict patch scope, then merge with pinned SHA if green.
2. **Classify HTML email layouts:** trace actual render/dispatch consumers or document genuine inactivity with direct repository evidence. For active deployment-branded layout rendering, implement context-safe brand substitution and test default/buyer behavior without changing notification consent/delivery logic.
3. **Record a buyer-config smoke matrix:** default Loomera and one alternate buyer configuration; compare logo/favicons, text, colors, From sender, contact links, public/SEO URLs, manifest ownership and calendar metadata. Where deployment/browser execution is unavailable, explicitly mark the relevant result as **not verified**, rather than claiming acceptance.
4. **Reassess** the Roadmap's three Phase 2 exit criteria using the completed evidence, then explicitly record a GO/NO-GO. Only a positive review unblocks the Phase 3 implementation plan.

## Audit Discipline

This file inventories source-backed facts and outstanding verification, not an
exhaustive search over all user-visible literals. Patch review and CI must remain
independent of this prose. A later phase may legitimately preserve source
repository/product identifiers as stable implementation contracts.

**Current state: Phase 2 open; Phase 3 not started; no deployment.**
