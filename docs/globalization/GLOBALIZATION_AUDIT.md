# Loomera Global — Globalization Audit

## Audit Scope

This document records the globalization baseline of `alireza-anari/loomera-global` at the exact Task 0.3 base. It is an evidence-based inventory of current Iran-, Persian-, calendar-, currency-, provider-, deployment-, and locale-specific assumptions that affect multi-country or multi-locale commercial operation.

This task is documentation-only. No globalization, internationalization, translation, refactor, cleanup, dependency change, migration, provider replacement, architecture change, or behavior change is included.

The audit was performed against the Target repository, not the Source repository. Repository search was combined with direct reads of settings, models, forms, services, templates, frontend JavaScript, deployment configuration, content data, and representative tests/contracts. Findings are limited to behavior confirmed in the Task 0.3 baseline.

## Repository Baseline

- Target repository: `alireza-anari/loomera-global`
- Target base SHA: `8987aed3e0778092f57c0a884a4c859b2b8087b2`
- Target base tree: `519f198bac10f13bd23eb26592628aadf0467810`
- Source provenance repository: `alireza-anari/loomera`
- Source pinned SHA: `502f3a5a44451fcbe480bfc7a2f0e7a5c3b1f90a`
- Source pinned tree: `ed0de5edb110ce78b05f1e7296ebf362c40adba9`
- Task 0.2 post-merge CI run: `38113258018` — `Loomera CI`, `push`, `main`, completed with `success`

The Source repository remained read-only and was used only for provenance verification.

## Executive Summary

The repository is operationally centered on a Persian/Iran baseline. The most consequential globalization risks are not merely translated copy: the canonical user identity is an Iranian local mobile number, monetary values do not carry an explicit currency while payment gateway logic applies toman/rial semantics, business scheduling encodes an Iran-style Saturday-to-Friday week, the runtime timezone is fixed to `Asia/Tehran`, and geography/map behavior is centered on Tehran and Iranian map providers.

At the same time, the repository already contains useful foundations for later work: Django i18n and timezone support are enabled, `LocaleMiddleware` is installed, provider-facing behavior is partly separated behind settings/services, branding and sender/domain metadata are configurable, GIS is already modeled, feature flags protect incomplete financial/messaging capabilities, and there is targeted regression/security coverage around booking, payments, deployment, and provider boundaries.

This audit records 19 findings. It does not define the target globalization architecture or the implementation roadmap; that work belongs to Task 0.4.

## Severity Summary

| Severity | Count |
| --- | ---: |
| Critical | 2 |
| High | 7 |
| Medium | 10 |
| Low | 0 |
| **Total** | **19** |

## Findings

### Language and i18n

### GLO-001 — Persian is the fixed runtime language baseline

**Domain:** Language / Django i18n  
**Severity:** High

**Current behavior / coupling**

Django i18n machinery is enabled, but the runtime language baseline is fixed to Persian. The base settings set `LANGUAGE_CODE = "fa"`, enable `USE_I18N`, and install `LocaleMiddleware`. The main HTML shell and broad application content are also authored for Persian. No explicit multi-language `LANGUAGES` configuration or repository-level user locale persistence mechanism was confirmed in the inspected settings and core flows.

**Evidence**

- `loomera/settings/base.py` — `LANGUAGE_CODE = "fa"`, `USE_I18N = True`, `django.middleware.locale.LocaleMiddleware`.
- `templates/base.html` — `<html lang="fa" ...>` and Persian default metadata.
- `loomera/settings/development.py` and `loomera/settings/production.py` inherit the base internationalization settings without overriding the language baseline.

**Globalization impact**

Django has localization infrastructure, but the product is not currently configured as a selectable multi-locale application. Non-Persian operation would encounter Persian defaults in runtime, templates, data/content, and UI behavior.

**Behavior-preservation constraint**

Future locale enablement must preserve the current Persian experience unless a dedicated task intentionally changes Persian wording or behavior. Existing request/session behavior must not be changed implicitly while introducing locale selection.

### Directionality

### GLO-002 — The shared presentation shell is hard-coded RTL

**Domain:** HTML directionality / RTL-LTR  
**Severity:** Medium

**Current behavior / coupling**

The primary HTML shell declares Persian and RTL statically. The global shell also loads RTL/Persian-oriented date assets. Email presentation includes an RTL-specific base template. No dynamic document-direction selection was confirmed in the inspected shared shells.

**Evidence**

- `templates/base.html` — `<html lang="fa" dir="rtl">`.
- `templates/base.html` — global Jalali datepicker CSS/JS and `static/js/jalali.js` inclusion.
- `templates/email/loomera_email_base_rtl.html` — RTL-specific shared email presentation.

**Globalization impact**

An LTR locale cannot rely on the existing shared shell to select directionality at runtime. Components that use physical left/right layout assumptions may require validation even when text itself is translated.

**Behavior-preservation constraint**

Future directionality work must preserve the current RTL Persian layout and visual semantics. This audit does not redesign CSS or shared shells.

### Calendar and Date

### GLO-003 — Jalali date behavior spans dependencies, server helpers, templates, and frontend code

**Domain:** Calendar and date representation  
**Severity:** High

**Current behavior / coupling**

Jalali behavior is not confined to presentation. The repository includes multiple Jalali/Persian date dependencies, custom server-side conversion/formatting utilities, global frontend Jalali code, Persian month/day labels, and booking/dashboard-facing date behavior. This mixes calendar representation with UI and workflow assumptions across layers.

**Evidence**

- `requirements.txt` — `django-jalali`, `jalali_core`, `jdatetime`, `Khayyam`, and `persiantools`.
- `loomera/settings/base.py` — `django_jalali` in `INSTALLED_APPS`.
- `apps/dashboards/jalali_utils.py` — Gregorian/Jalali conversion, Persian month/weekday labels, Persian digit formatting, and Jalali parsing heuristics.
- `static/js/jalali.js` — custom `JalaliCalendar` behavior with Persian calendar labels.
- `templates/base.html` — Jalali JavaScript and datepicker assets loaded in the shared shell.

**Globalization impact**

Supporting Gregorian or another calendar as the user-facing calendar cannot be treated as a template-only change. Storage, parsing, business workflow inputs, formatting, and frontend date selection must be clearly separated in later design work.

**Behavior-preservation constraint**

Existing persisted date/time semantics and current booking calculations must remain unchanged unless a dedicated task explicitly migrates them. Jalali presentation currently relied upon by Persian users must remain regression-tested during future work.

### Timezone

### GLO-004 — Runtime and operational scheduling assume Tehran time without a confirmed business-specific timezone

**Domain:** Timezone  
**Severity:** High

**Current behavior / coupling**

Django timezone support is enabled, but the runtime timezone is fixed to `Asia/Tehran`. Liara deployment configuration also uses Tehran time for platform scheduling. The inspected `Salon` model does not contain a salon/business timezone field.

**Evidence**

- `loomera/settings/base.py` — `TIME_ZONE = "Asia/Tehran"`, `USE_TZ = True`.
- `liara.json` — deployment timezone set to `Asia/Tehran` and scheduled commands defined at the platform level.
- `apps/salons/models.py` — salon data includes location/opening-hours information but no per-salon timezone field in the inspected model.

**Globalization impact**

Multiple countries or businesses in different timezones cannot be safely represented by a single Tehran runtime/business timezone assumption. Notification, opening-hour, booking, no-show, and scheduled-job boundaries are especially sensitive.

**Behavior-preservation constraint**

Future timezone work must preserve the exact current interpretation of existing appointment/opening-hour data until a dedicated migration/compatibility design explicitly changes it.

### Week Structure

### GLO-005 — Business schedules encode Saturday as day 1 and Friday as day 7

**Domain:** Weekday and week structure  
**Severity:** High

**Current behavior / coupling**

Salon opening hours use an explicit numeric mapping from Saturday (`1`) through Friday (`7`) with Persian weekday labels. The same Iran-oriented weekday sequence is represented in Jalali/frontend date behavior.

**Evidence**

- `apps/salons/models.py` — `SalonOpeningHours.DAY_CHOICES`, Saturday=`1` through Friday=`7`.
- `apps/salons/models.py` — Persian weekday labels used in schedule behavior.
- `static/js/jalali.js` and `apps/dashboards/jalali_utils.py` — Persian/Jalali weekday ordering and labels.

**Globalization impact**

Changing display labels alone would be unsafe because numeric weekday semantics are part of business schedule data and code contracts. Regions with different first-day/weekend conventions could be interpreted incorrectly if the mapping is reused as a locale-neutral weekday index.

**Behavior-preservation constraint**

Existing numeric weekday meanings must not be renumbered implicitly. Any future locale-specific display abstraction must preserve current stored schedule semantics unless a dedicated migration is approved.

### Phone and Authentication

### GLO-006 — Canonical user identity is an Iranian local `09...` mobile number

**Domain:** Phone numbers and authentication  
**Severity:** Critical

**Current behavior / coupling**

The custom Django user uses `mobile_number` as the username and constrains it to 11 characters. Signup validation normalizes Persian/Arabic digits but requires exactly 11 digits starting with `09`. SMS helpers normalize `+98`, `0098`, and `98` forms back into the local Iranian form expected by SMS.ir.

**Evidence**

- `apps/accounts/models.py` — `mobile_number = CharField(max_length=11, unique=True)` and `USERNAME_FIELD = "mobile_number"`.
- `apps/accounts/forms.py` — signup placeholder `09xxxxxxxxx`; validation requires length 11 and prefix `09`; Persian/Arabic digit normalization.
- `apps/accounts/services/sms.py` — Iranian `+98`/`0098`/`98` normalization and 11-digit local mobile validation.

**Globalization impact**

Phone identity, uniqueness, login/signup, OTP delivery, and stored account identity cannot safely represent arbitrary international E.164 numbers. This is an authentication/data-correctness blocker for multi-country operation.

**Behavior-preservation constraint**

Future phone normalization must preserve uniqueness and login behavior for all existing Iranian users and must not create identity collisions. E.164 migration is explicitly outside this task.

### Geography and Maps

### GLO-007 — Geography and map behavior are centered on Tehran/Iran without confirmed country-neutral hierarchy

**Domain:** Geography, addresses, GIS, and maps  
**Severity:** High

**Current behavior / coupling**

The repository has strong GIS primitives, but the inspected business/location data is city/zone/address oriented rather than explicitly country-aware. Search/map helpers default to Tehran, contain Tehran bounds logic, enable maps through Map.ir settings, and construct Neshan map links.

**Evidence**

- `apps/salons/models.py` — free-form `city`, `zone`, `zone_label`, address fields, GIS point, and neighborhood relation; no country field in the inspected salon model.
- `apps/locations/models.py` — `Neighborhood` polygon/name model without a country/city hierarchy.
- `apps/search/map_helpers.py` — `DEFAULT_CITY = "تهران"`, Tehran center/bounds helpers, `MAP_PROVIDER == "mapir"`, and Neshan URL construction.
- `loomera/settings/base.py` — map/provider settings boundary.

**Globalization impact**

Country-aware addresses, geocoding, routing, map coverage, and regional search cannot be derived reliably from current Tehran/provider assumptions. Free-form city/address data also lacks a confirmed country discriminator.

**Behavior-preservation constraint**

Existing GIS coordinates, neighborhood polygons, Tehran search behavior, and map links must remain valid until dedicated geography/provider work defines compatibility behavior.

### Money and Currency

### GLO-008 — Monetary records lack explicit currency while gateway logic assigns toman/rial semantics

**Domain:** Money and currency  
**Severity:** Critical

**Current behavior / coupling**

Core payment and wallet monetary fields store numeric amounts without an explicit currency field. The active gateway interface names the input `amount_toman` and converts it to rials by multiplying by 10 for Zibal. This means currency/unit semantics are partly implicit in code rather than represented with each monetary value.

**Evidence**

- `apps/payments/models.py` — `Payment.amount`, wallet balance/transaction amounts, and withdrawal amounts without an explicit currency field on the inspected monetary records.
- `apps/payments/gateways.py` — `amount_toman` input and `amount_rial = int(amount_toman) * 10` for Zibal; verification performs the same unit conversion.
- Persian UI/content across booking/payment flows uses current local money semantics.

**Globalization impact**

A numeric amount cannot safely be interpreted across countries/currencies without an explicit currency/unit contract. Financial correctness, reporting, refunds, gateway verification, wallet accounting, and API interpretation are at risk if multi-currency behavior is layered onto the current implicit semantics.

**Behavior-preservation constraint**

Existing stored amounts and ledger arithmetic must retain their current unit interpretation. Currency introduction or conversion is migration/architecture work and is not performed here.

### Payments and Payouts

### GLO-009 — Online gateway and payout implementations are Iran-specific; Pay at Salon is an independent capability to preserve

**Domain:** Payments and payouts  
**Severity:** High

**Current behavior / coupling**

Payment models enumerate Zarinpal/Zibal alongside wallet/manual/mock options, while the active gateway adapter supports Zibal with Iranian rial/toman semantics. Withdrawal/payout data uses Sheba/IBAN-shaped fields and Iranian mobile assumptions. Separately, booking checkout explicitly supports `pay_in_salon`; that is a valid product capability and is not a globalization defect.

**Evidence**

- `apps/payments/models.py` — provider choices include `ZARINPAL`, `ZIBAL`, `WALLET`, `MANUAL`, and `MOCK`; withdrawal model carries Sheba/IBAN-oriented fields.
- `apps/payments/gateways.py` — active Zibal request/verify integration and provider validation.
- `apps/orders/forms.py` — `PAYMENT_METHOD_SALON = "pay_in_salon"` and beta behavior that can select Pay at Salon.
- `apps/orders/views.py` — Pay at Salon validation/settlement helpers and checkout behavior.

**Globalization impact**

Online payment and payout rails are tied to Iranian provider/banking conventions and cannot be assumed portable. Pay at Salon, however, is provider-independent product behavior that can remain valid internationally.

**Behavior-preservation constraint**

Do not remove or weaken Pay at Salon as part of provider globalization. Existing payment state transitions, wallet ledger behavior, first-visit/payment rules, refund behavior, and provider verification contracts must remain stable until dedicated financial tasks intentionally change them.

### Messaging and SMS

### GLO-010 — OTP and SMS delivery depend on SMS.ir and Iranian mobile normalization

**Domain:** SMS and messaging providers  
**Severity:** High

**Current behavior / coupling**

The implemented SMS path uses SMS.ir's verification endpoint and expects Iranian mobile normalization. Notification SMS delivery likewise recognizes the SMS.ir provider boundary and local-number behavior.

**Evidence**

- `apps/accounts/services/sms.py` — SMS.ir endpoint `https://api.sms.ir/v1/send/verify`, provider-specific request handling, and Iranian mobile normalization.
- `apps/notifications/delivery.py` — SMS channel/provider dispatch with `smsir` support and `+98`/local normalization.
- `loomera/settings/base.py` — messaging/provider feature settings.

**Globalization impact**

Authentication OTP and transactional SMS cannot be assumed to work for international numbers or alternative provider request/response contracts.

**Behavior-preservation constraint**

Future provider work must preserve existing OTP/security semantics, disabled-provider behavior, notification status handling, and current Iranian delivery until explicitly migrated.

### GLO-011 — Messaging abstractions exist, but concrete channels include region-specific providers

**Domain:** Messaging and SMS providers  
**Severity:** Medium

**Current behavior / coupling**

Messaging behavior is partially separated behind provider/channel dispatch and flags, which is globalization-friendly. Concrete implementations and configuration nevertheless include Bale, Telegram, and Rubika-specific behavior, with Bale defaults present in the runtime settings.

**Evidence**

- `apps/notifications/delivery.py` — messaging channel dispatch delegated to messaging delivery code; channels include Bale/Telegram/Rubika behavior.
- `apps/messaging/` — provider-specific presenters/services including Bale and messaging links/flows.
- `apps/bale_bot/` and `apps/telegram_bot/` — provider-specific applications.
- `loomera/settings/base.py` — `MESSAGING_ALLOWED_PROVIDERS`, Bale and Telegram bot settings, and Loomi messaging provider defaults.

**Globalization impact**

The provider boundary reduces future coupling, but current concrete channels and operational assumptions are not a country-neutral messaging portfolio.

**Behavior-preservation constraint**

Provider substitution must preserve current notification intent, opt-out/preferences, outbound feature flags, security controls, and delivery status semantics.

### Email and Notifications

### GLO-012 — Email/notification presentation and content are Persian/RTL without a confirmed locale-selection path

**Domain:** Email and notification content  
**Severity:** Medium

**Current behavior / coupling**

Email sender identity is configurable, but the shared email presentation and notification content baseline are Persian/RTL. The inspected delivery service consumes notification title/body directly; no per-recipient locale selection was confirmed in that delivery path.

**Evidence**

- `templates/email/loomera_email_base_rtl.html` — RTL email base presentation.
- `apps/notifications/delivery.py` — email/SMS/messaging delivery consumes stored notification title/body and configured sender settings.
- `loomera/settings/base.py` — configurable `DEFAULT_FROM_EMAIL`, support/partner/marketing addresses, and sender branding.

**Globalization impact**

International email/notification delivery requires locale-aware content selection and directionality while retaining existing delivery contracts.

**Behavior-preservation constraint**

Do not change notification triggering, preference checks, sender configuration, or delivery state behavior as a side effect of later translation work.

### Search and Text Normalization

### GLO-013 — Search normalization is optimized for Persian/Arabic text rather than locale-aware multilingual input

**Domain:** Search and text normalization  
**Severity:** Medium

**Current behavior / coupling**

Search normalization converts Persian digits, maps Arabic `ك/ي` to Persian equivalents, removes/normalizes zero-width behavior, and recognizes Persian boolean words. This is useful for the current market but is not a generalized per-locale normalization/collation strategy.

**Evidence**

- `apps/search/services.py` — `PERSIAN_DIGITS_MAP`, Arabic-to-Persian character normalization, ZWNJ handling, and Persian boolean tokens such as `بله`/`آری`.
- `apps/search/map_helpers.py` — Tehran default city/bounds also influence geographic search context.

**Globalization impact**

Non-Persian languages may be normalized/ranked inconsistently, and locale-specific collation/token behavior is not represented as an explicit language-dependent concern.

**Behavior-preservation constraint**

Future normalization must preserve current Persian/Arabic-character search equivalence and existing query behavior while adding locale-aware behavior deliberately.

### Frontend Locale Assumptions

### GLO-014 — Frontend locale behavior is built around custom Jalali/Persian primitives

**Domain:** Frontend JavaScript locale assumptions  
**Severity:** Medium

**Current behavior / coupling**

The shared frontend loads a custom Jalali implementation globally. The calendar code contains Persian month/weekday semantics and Iran-style week ordering. A major browser `Intl`/`fa-IR`-based locale abstraction was not confirmed in the inspected shared locale hotspots.

**Evidence**

- `static/js/jalali.js` — custom Jalali calendar algorithms, Persian labels, and weekday ordering.
- `templates/base.html` — global inclusion of `jalali.js` and Jalali datepicker assets.
- `apps/dashboards/jalali_utils.py` — parallel server-side Persian digit/date formatting demonstrates duplicated locale concerns across frontend/backend.

**Globalization impact**

Frontend locale behavior cannot be switched safely by changing a single language token. Calendar/date/digit/direction behavior is embedded in shared scripts and templates.

**Behavior-preservation constraint**

Existing Persian/Jalali booking and dashboard UI must remain functionally equivalent during any later locale abstraction.

### Branding

### GLO-015 — Branding is partly configurable but product identity remains hard-coded in representative content/fallbacks

**Domain:** Branding and product identity  
**Severity:** Medium

**Current behavior / coupling**

The settings layer centralizes brand name, display name, domain, public/site URL, sender names, and support/partner/marketing addresses. Representative templates and model SEO fallbacks still contain literal Loomera identity and Persian product messaging.

**Evidence**

- `loomera/settings/base.py` — `BRAND_NAME`, `BRAND_DISPLAY_NAME`, `BRAND_DOMAIN`, `PUBLIC_BASE_URL`, `SITE_URL`, sender/support/partner/marketing configuration.
- `templates/base.html` — literal `Loomera` title/metadata defaults.
- `apps/salons/models.py` — Loomera/Persian SEO fallback text in salon metadata behavior.
- `partials/brand/head_assets.html` and Loomera-branded static styles/assets are included by the shared shell.

**Globalization impact**

The existing configuration foundation reduces work, but changing market identity/domain/SEO consistently cannot rely on settings alone while literal product identity remains in content and fallbacks.

**Behavior-preservation constraint**

Task 0.3 does not rename Loomera. Later branding work must preserve existing URLs/assets/fallback behavior until replacements are explicitly approved.

### SEO and Legal

### GLO-016 — Public metadata defaults are Persian/product-specific; a multilingual legal/canonical pipeline was not confirmed

**Domain:** SEO, legal, and public metadata  
**Severity:** Medium

**Current behavior / coupling**

The main shell provides Persian default descriptions and literal Loomera social metadata. Salon metadata also includes Persian/Loomera fallback behavior. Repository searches performed for canonical/legal/privacy/terms localization did not confirm a dedicated multilingual canonical or legal-content pipeline; this is recorded as an audit gap rather than an assertion that no such content exists anywhere.

**Evidence**

- `templates/base.html` — Persian default `meta_description`, Open Graph description, Twitter description, and Loomera title defaults.
- `apps/salons/models.py` — Persian/Loomera SEO fallback behavior.
- `loomera/settings/base.py` — configurable `PUBLIC_BASE_URL`/`SITE_URL` and brand/domain settings are a positive foundation.

**Globalization impact**

Search/social metadata is not selected by locale in the representative shared shell. Country-/locale-specific legal obligations and canonical/hreflang-style public metadata require explicit confirmation/design before international launch.

**Behavior-preservation constraint**

Current public metadata and URLs must not be silently removed or rewritten by unrelated globalization work.

### Help Center and Lumi

### GLO-017 — Production help/Lumi content is explicitly Iran/Persian-oriented

**Domain:** Help Center, Lumi, and content data  
**Severity:** Medium

**Current behavior / coupling**

The production Help Center data identifies itself as Iran documentation and contains Persian categories/workflow guidance, including regional messaging/provider references. Help/Lumi services consume this repository content as part of the product support experience.

**Evidence**

- `apps/help_center/data/production_docs.json` — version `2026-09-04-iran-docs`, Persian category/content data, and Bale-related communications content.
- `apps/help_center/` — `ai.py`, `content.py`, `lumi_domain_service.py`, and data/workflow content demonstrate the Help Center/Lumi content boundary.

**Globalization impact**

International Help Center/Lumi behavior cannot safely reuse the current corpus as country-neutral knowledge. Content locale/country/provider context is material to support answers and workflows.

**Behavior-preservation constraint**

Do not change AI/Lumi behavior or current Iran documentation in this audit. Later content localization must preserve current supported actions and guardrails unless explicitly changed.

### Deployment and Installability

### GLO-018 — Deployment is Liara-specific and carries Tehran/runtime-version assumptions

**Domain:** Deployment and installability  
**Severity:** Medium

**Current behavior / coupling**

Production deployment is explicitly automated through Liara. `liara.json` defines the Django platform, GIS capability, `Asia/Tehran` timezone, Python `3.12`, and scheduled commands. CI independently uses Python `3.13` and installs Linux GIS system packages. The production workflow installs the Liara CLI and deploys via Liara token/app variables.

**Evidence**

- `liara.json` — Liara Django platform configuration, `pythonVersion: 3.12`, `timezone: Asia/Tehran`, geospatial support, cron jobs.
- `.github/workflows/liara-production.yml` — `@liara/cli@9`, `LIARA_API_TOKEN`, `LIARA_APP_NAME`, and `liara deploy`.
- `.github/workflows/ci.yml` — Python `3.13` and GDAL/GEOS system dependencies.
- `loomera/settings/base.py` — collectstatic/runtime comments and database fallback behavior reference Liara build characteristics.

**Globalization impact**

Deploying the product to other infrastructures/regions requires accounting for platform-specific build/runtime/deployment behavior, GIS dependencies, timezone scheduling, and the current CI/runtime Python-version difference.

**Behavior-preservation constraint**

No deployment workflow, Python version, GIS dependency, or platform configuration is changed by this task. Existing production safety gates and deployment semantics must remain intact.

### Tests, Fixtures, and Documentation

### GLO-019 — Regression assets encode current Iran/Persian/provider contracts while providing strong safety coverage

**Domain:** Tests, fixtures, and documentation  
**Severity:** Medium

**Current behavior / coupling**

The repository contains tests/contracts for payment gateways, deployment settings, maps/providers, booking checkout, finance scopes, permissions, and other current behavior. These are a globalization constraint because many intentionally encode the current Iran/provider baseline, but they are also a major safety foundation for preserving behavior during future changes.

**Evidence**

- `apps/orders/booking_checkout_contract_manifest.json` — protected booking symbols/hashes including checkout/date-selection contracts.
- `apps/search/test_mapir_proxy_security.py` — Map.ir security/provider expectations.
- `apps/payments/` tests — gateway, verification, finance, wallet/withdrawal, and provider behavior coverage.
- `.github/workflows/ci.yml` — Django system check, migration drift, deployment guards, and production-settings hygiene.
- Existing account/search/salon/order tests and fixtures include current phone, Persian, provider, weekday, or financial assumptions in representative flows.

**Globalization impact**

Future globalization work will require deliberate test evolution; blindly making old provider/locale expectations pass or deleting them could conceal regressions in current production behavior.

**Behavior-preservation constraint**

Treat existing tests and contract manifests as behavior evidence. Update expectations only in the dedicated task that intentionally changes the corresponding contract, with explicit compatibility/regression coverage.

## Existing Globalization-Friendly Foundations

Confirmed foundations that can reduce risk in later work include:

- Django internationalization is enabled with `USE_I18N = True` and `LocaleMiddleware`.
- Django timezone-aware behavior is enabled with `USE_TZ = True`, even though the business timezone baseline is fixed to Tehran.
- Brand/domain/public URL/email sender metadata is centralized and environment-configurable in `loomera/settings/base.py`.
- Product capabilities such as online payments, withdrawals, messaging, and Bale/Telegram behavior are guarded by feature/provider flags.
- Payment gateway behavior is separated in `apps/payments/gateways.py` rather than embedded directly in checkout templates.
- Notification delivery has channel/provider boundaries in `apps/notifications/delivery.py`.
- Map behavior is accessed through map/search helpers and settings rather than being only literal frontend code.
- GIS support already exists through GeoDjango fields and geospatial deployment dependencies.
- The repository is divided into domain apps (`accounts`, `salons`, `orders`, `payments`, `search`, `locations`, `notifications`, `messaging`, `help_center`, and others), providing observable ownership boundaries.
- Booking checkout has a contract manifest, and provider/finance/security behavior has targeted test coverage.
- Role preference and authorization are modeled separately in account/workspace behavior; preference is not itself an authorization grant.
- Pay at Salon is represented as a distinct payment method and is not intrinsically tied to an online gateway.

## Cross-Cutting Risks

- **Identity and communications are coupled:** the same Iranian phone assumptions influence account identity, OTP, SMS, and notification delivery.
- **Money and providers are coupled:** stored numeric amounts, gateway units, payout fields, and provider contracts collectively assume the current market even when the database field itself looks generic.
- **Calendar, weekday, and timezone concerns overlap:** changing one representation without auditing opening hours, booking logic, notifications, and scheduled jobs could shift real-world appointment meaning.
- **Presentation and business assumptions overlap:** Persian/RTL/Jalali concerns occur in settings, models/helpers, templates, and JavaScript rather than only content files.
- **Country context is often implicit:** Tehran defaults, Iranian phone/banking conventions, Persian content, and provider choices supply country meaning that is not always represented by explicit country/currency/timezone fields.
- **Existing tests intentionally protect current behavior:** future changes must distinguish obsolete market assumptions from production contracts that still need backward compatibility.

## Behavior That Must Be Preserved

Unless a dedicated later task explicitly changes them, globalization work must preserve:

- Current booking creation, checkout, appointment timing, and protected booking contract semantics.
- **Pay at Salon (`pay_in_salon`) as a valid product capability.** It must not be classified as a behavior to remove merely because online providers are country-specific.
- Existing customer/manager/stylist role and permission boundaries, including the distinction between workspace preference and authorization.
- Existing wallet/financial ledger arithmetic, salon-scoped finance permissions, payment state transitions, refunds, and payout safeguards.
- Existing notification preference checks, delivery status behavior, feature/provider flags, and security boundaries.
- Existing provider request verification and security behavior while a provider remains supported.
- Existing API/checkout contracts and current Persian/Iran production behavior until the dedicated task responsible for that contract defines compatibility changes.
- Current deployment safety gates and non-production protections.

## Audit Gaps / Not Confirmed

The following items were not confirmed strongly enough to state as repository-wide findings:

- An explicit Django `LANGUAGES` list and a complete user/account locale-selection and persistence mechanism were not confirmed in the inspected settings/core flows.
- A business/tenant-specific timezone field or timezone selection mechanism outside the inspected salon/core scheduling models was not confirmed.
- A generalized ISO country/address hierarchy and explicit currency model were not confirmed in the inspected core salon/location/payment models.
- A shared browser `Intl`/`fa-IR` abstraction acting as the primary frontend locale layer was not confirmed; the representative shared locale hotspot is the custom Jalali/Persian code.
- A dedicated multilingual canonical/hreflang/legal/privacy/terms content pipeline was not confirmed by the inspected shared metadata and repository searches. This does not assert that no isolated legal text exists elsewhere.
- This audit records representative hard-coded Persian/provider hotspots rather than enumerating every Persian literal in every template/test fixture.
- Provider coverage in this document is focused on the mandatory/currently confirmed payment, map, SMS, and messaging integrations; it is not a vendor-selection exercise.

## Conclusion

Loomera Global starts from a coherent Iran/Persian production baseline with meaningful modularity, feature flags, provider boundaries, GIS support, Django i18n/timezone foundations, and regression coverage. However, safe international commercial operation is blocked by several assumptions that reach into identity, money, schedules, timezone, geography, providers, and shared presentation—not only translated text.

The highest-risk areas are international phone/auth identity and explicit currency semantics. High-risk supporting areas include Persian runtime language, Jalali/calendar coupling, fixed Tehran time, Iran-specific week semantics, Tehran/map geography, payment/payout providers, and SMS/OTP delivery.

No globalization implementation, architecture selection, migration plan, provider replacement, refactor, cleanup, or behavior change was performed in Task 0.3. Detailed target architecture and roadmap decisions remain reserved for Task 0.4.
