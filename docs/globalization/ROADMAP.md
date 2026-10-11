# Loomera Global — Globalization Roadmap

## Purpose

This roadmap orders the work required to evolve the current Loomera Iran/Persian baseline into a commercially configurable global product while preserving existing behavior. It implements the architecture defined in [ARCHITECTURE.md](./ARCHITECTURE.md) through isolated, reviewable phases. It is not permission to combine phases or perform opportunistic rewrites.

Phase 0 is the completed repository/bootstrap/audit/architecture baseline. Phases 1–19 are future implementation phases. Task 0.4 does not start Phase 1 implementation.

## Release Goal

The release target is a state where a commercial buyer can eventually:

1. clone the repository;
2. configure environment variables;
3. configure a database;
4. run migrations;
5. create an admin;
6. set brand identity;
7. replace logo/favicon;
8. configure brand colors;
9. configure default country;
10. configure default currency;
11. configure timezone;
12. configure default language;
13. enable English and/or Arabic;
14. optionally retain Persian;
15. select/configure supported providers through documented contracts;
16. deploy without editing dozens of unrelated source files.

These are release targets, not claims about current capability.

The initial global commercial target does not require live FX, simultaneous multi-currency settlement inside one order, mandatory replacement of existing regional providers, or a rewrite of Django/frontend/business architecture.

## Ordering Principles

1. Architecture and configuration contracts precede widespread implementation.
2. Branding is isolated from language translation so white-label/commercial configuration does not become coupled to i18n work.
3. Locale resolution and bidirectional shell support precede broad English-first UI conversion.
4. Calendar/timezone boundaries precede broad replacement of Jalali-first presentation.
5. Persisted weekday semantics are isolated in their own phase because current numeric meanings are contractual data.
6. Phone/auth identity migration precedes assuming international SMS delivery.
7. Currency semantics become explicit before adding or generalizing international payment/payout providers.
8. Country/address concepts become explicit before generalized map-provider work.
9. Provider-neutral boundaries preserve current providers before any replacement/addition.
10. Frontend, notifications, search, Help/Lumi, and SEO/legal localization build on the same locale/country/time/money contracts rather than inventing parallel context.
11. Deployment portability is addressed after core application contracts stabilize and before commercial packaging.
12. Commercial packaging and full release-candidate regression occur only after core globalization contracts are implemented and migration paths are proven.
13. Each phase changes the smallest coherent contract possible and avoids unrelated cleanup/refactoring.

## Phase Dependency Overview

| Phase | Primary dependency |
| --- | --- |
| Phase 0 | Completed Source import, baseline verification, audit, architecture/roadmap documentation |
| Phase 1 | Phase 0 architecture decisions |
| Phase 2 | Phase 1 configuration ownership/contracts |
| Phase 3 | Phase 1 locale/config contracts; Phase 2 branding separated |
| Phase 4 | Phase 3 locale and direction runtime |
| Phase 5 | Phase 1 config contracts; protected booking/schedule behavior |
| Phase 6 | Phase 5 time/calendar boundary and explicit legacy weekday mapping |
| Phase 7 | Phase 1 country/default config; current auth/OTP contracts |
| Phase 8 | Phase 1 default currency config; current financial invariants |
| Phase 9 | Phase 1 default country config; Phase 5 timezone where location affects time; GIS baseline |
| Phase 10 | Phases 3, 5, 6, 8, 9 locale/time/week/money/country contracts |
| Phase 11 | Phases 3 and 10 locale/direction context |
| Phase 12 | Phases 3 and 9 locale/country search context |
| Phase 13 | Phase 3 locale context; Phase 9 country/provider applicability |
| Phase 14 | Phase 7 canonical phone identity; Phase 11 notification semantics |
| Phase 15 | Phase 8 currency semantics; Phase 9 country context; preserved financial contracts |
| Phase 16 | Phases 2, 3, 9 branding/locale/country; public URL decision |
| Phase 17 | Stable application/config contracts from earlier phases |
| Phase 18 | Phases 2–17 sufficiently stable and documented |
| Phase 19 | All implementation phases complete enough for release-candidate validation |

### Audit Finding Primary Ownership

Each Task 0.3 finding has exactly one primary roadmap owner. Cross-phase prerequisites are documented in the phase text but do not change primary ownership.

| Finding | Primary Phase | Notes |
| --- | --- | --- |
| `GLO-001` | Phase 3 | Runtime locale selection and English-first default |
| `GLO-002` | Phase 3 | Dynamic LTR/RTL shell |
| `GLO-003` | Phase 5 | Calendar boundary and Gregorian global default |
| `GLO-004` | Phase 5 | Explicit business timezone and appointment-safe migration |
| `GLO-005` | Phase 6 | Persisted weekday compatibility |
| `GLO-006` | Phase 7 | E.164 phone/auth identity migration |
| `GLO-007` | Phase 9 | Country/address/geography/map boundary |
| `GLO-008` | Phase 8 | Explicit currency semantics and legacy toman migration |
| `GLO-009` | Phase 15 | Payment/payout provider neutrality while preserving Pay at Salon |
| `GLO-010` | Phase 14 | International SMS/OTP provider boundary after phone migration |
| `GLO-011` | Phase 14 | Messaging provider/channel abstraction |
| `GLO-012` | Phase 11 | Localized email/notification rendering |
| `GLO-013` | Phase 12 | Locale-aware search normalization |
| `GLO-014` | Phase 10 | Shared frontend locale/formatting context |
| `GLO-015` | Phase 2 | Centralized branding foundation |
| `GLO-016` | Phase 16 | Locale-aware SEO and jurisdiction-aware legal metadata |
| `GLO-017` | Phase 13 | Locale/country-aware Help Center and Lumi corpus |
| `GLO-018` | Phase 17 | Portable deployment/installability contract |
| `GLO-019` | Phase 19 | Full regression and release-candidate contract reconciliation |

## Phase 0 — Repository Bootstrap and Baseline

Phase 0 is the completed foundation: exact Source snapshot import, baseline verification, globalization audit, and architecture/roadmap documentation. It establishes provenance and compatibility evidence without implementing globalization.

Completed artifacts include `SOURCE_IMPORT.md`, `BASELINE_VERIFICATION.md`, `GLOBALIZATION_AUDIT.md`, `ARCHITECTURE.md`, and this roadmap.

Phase 0 exit condition is an approved architecture/roadmap baseline with no application behavior change. Phase 1 implementation begins only after normal review/merge of Task 0.4 and a dedicated Phase 1 task.

## Phase 1 — Architecture and Configuration Contracts

**Goal**

Turn the approved architecture into minimal application configuration contracts and ownership boundaries without translating product surfaces or migrating country/phone/money data.

**Why this phase occurs at this point**

Every later phase depends on common definitions for deployment defaults, business-level data, and request/user presentation context. Implementing locales/providers first would recreate country-specific assumptions under new names.

**Inputs/dependencies**

- Phase 0 architecture decisions `ARC-001` through `ARC-019`.
- Existing environment-backed brand/provider settings and feature flags.
- Existing Django settings, app boundaries, and deployment safety guards.

**Major workstreams**

- Define central typed/constrained contracts for default language, enabled languages, default country, default currency, fallback timezone, calendar default, and provider selections.
- Define configuration precedence and validation without introducing unnecessary business fields early.
- Define shared context/service interfaces that later locale/time/money/provider phases can consume.
- Document environment variables and default/failure behavior as they are introduced.
- Add tests for configuration validation and compatibility fallbacks.

**Explicit non-goals**

- No broad UI translation.
- No phone, currency, country/address, weekday, or timezone data migration.
- No new external provider requirement.
- No branding asset migration beyond contracts needed by Phase 2.

**Exit criteria**

- Deployment configuration categories are explicit, validated, documented, and tested.
- Later phases can consume configuration through one documented boundary rather than scattered environment reads.
- Existing Iran/Persian behavior remains unchanged under compatibility defaults.
- No authorization or financial behavior changes.

**Key regression areas**

- production settings hygiene;
- deployment guards;
- current feature/provider flags;
- startup/collectstatic behavior;
- existing default behavior when new configuration is absent.

## Phase 2 — Branding Foundation

**Goal**

Make deployment brand identity centrally configurable using the existing brand/domain/email foundation, without coupling branding to translation.

**Why this phase occurs at this point**

Commercial installations need independent brand configuration, and shared brand context should exist before English/Arabic content conversion and SEO work.

**Inputs/dependencies**

- Phase 1 configuration contracts.
- Existing `BRAND_NAME`, `BRAND_DISPLAY_NAME`, `BRAND_DOMAIN`, public URL, sender, and contact settings.
- Existing brand partials/static assets and metadata fallbacks.

**Major workstreams**

- Define/configure logo, favicon, color/design-token, public URL, sender, contact, and SEO brand identity ownership.
- Replace representative duplicated brand literals with centralized context where safe.
- Preserve Loomera as the default configuration.
- Document buyer-facing brand configuration and asset requirements.
- Add regression tests for default and alternate brand configuration.

**Explicit non-goals**

- No product-language translation.
- No per-salon multi-tenant white-label system unless separately approved.
- No wholesale visual redesign.
- No public locale URL decision.

**Exit criteria**

- A buyer can change supported brand identity inputs through documented configuration without editing unrelated application files.
- Loomera defaults remain visually and behaviorally compatible.
- Brand settings have one documented source of truth.

**Key regression areas**

- shared shell/head assets;
- email sender identity;
- public URLs;
- calendar/product identifiers;
- existing static asset serving.

## Phase 3 — i18n Runtime and Bidirectional Shell

**Goal**

Establish English-first locale resolution and dynamic LTR/RTL presentation foundations while preserving Persian as a supported locale.

**Why this phase occurs at this point**

Broad English UI conversion must not begin until locale and direction are real runtime context rather than hard-coded shell constants.

**Inputs/dependencies**

- Phase 1 language/enabled-locale configuration.
- Existing `LocaleMiddleware` and Django i18n support.
- Phase 2 branding context.
- `ARC-001` and `ARC-002`.

**Major workstreams**

- Define enabled locales and English target default with deterministic fallback.
- Implement request locale resolution/persistence according to approved policy.
- Make shared HTML/email direction derive from locale.
- Introduce translation markers/catalog structure for system strings without translating every feature at once.
- Establish bidirectional component regression patterns.

**Explicit non-goals**

- No full product translation in this phase.
- No automatic translation of user-entered content.
- No calendar/timezone/weekday data migration.
- No claim that Arabic content is complete merely because RTL works.

**Exit criteria**

- English, Arabic, and Persian can be represented as enabled locale choices in architecture/runtime contracts.
- Shared shell can render LTR or RTL from active locale.
- Persian RTL remains compatible.
- Locale fallback/persistence behavior is covered by tests.

**Key regression areas**

- authentication/session behavior;
- shared shell/navigation/forms;
- Persian RTL rendering;
- CSRF/session middleware ordering;
- user/workspace authorization separation.

## Phase 4 — English-First Product Surface

**Goal**

Convert the primary application-owned product surface to English as the global default while retaining Persian translations and leaving Arabic translation scope incremental.

**Why this phase occurs at this point**

Phase 3 provides the runtime and direction layer required to translate safely without replacing hard-coded Persian with hard-coded English.

**Inputs/dependencies**

- Phase 3 locale runtime/catalog structure.
- Phase 2 centralized branding.
- Inventory of high-traffic templates/forms/model choice labels/system messages.

**Major workstreams**

- Translate prioritized shared/customer/manager/stylist system strings to English catalogs/source conventions.
- Preserve Persian translations for current behavior.
- Establish translation review conventions and missing-string checks.
- Distinguish application-owned strings from user-entered content.
- Incrementally add Arabic content only where explicitly in scope and reviewed.

**Explicit non-goals**

- No wholesale UI redesign.
- No calendar/timezone/phone/money migration.
- No promise of complete Arabic translation in one task/phase slice.
- No rewriting user-generated Persian content.

**Exit criteria**

- Core commercial flows are usable in English under the new default.
- Persian remains usable through locale selection.
- Missing translation behavior is deterministic and tested.
- Arabic RTL support remains structurally correct even where translation coverage is incomplete and clearly tracked.

**Key regression areas**

- booking/checkout forms;
- role/workspace flows;
- validation/error messages;
- admin/support surfaces where included;
- Persian locale fallback and RTL.

## Phase 5 — Calendar and Timezone Foundation

**Goal**

Separate canonical scheduling/time semantics from presentation calendar and introduce an explicit business IANA timezone path without shifting existing appointments.

**Why this phase occurs at this point**

Calendar and timezone assumptions affect booking correctness. They must be solved before broad frontend date changes and before weekday migration.

**Inputs/dependencies**

- Phase 1 timezone/calendar configuration contracts.
- Existing timezone-aware Django behavior, Jalali utilities/assets, booking contracts, salon opening hours, reminders, no-show logic, and scheduled jobs.
- `ARC-003` and `ARC-004`.

**Major workstreams**

- Inventory persisted date/time fields and determine their current real-world meaning.
- Establish canonical date/time service boundaries and Gregorian default presentation.
- Isolate Jalali input/output behind explicit adapters.
- Design/add business IANA timezone data only after migration assumptions are verified.
- Define legacy timezone fallback and migrate without shifting existing appointment instants/wall-clock expectations.
- Classify scheduled jobs as UTC, deployment-local, or business-local.

**Explicit non-goals**

- No weekday renumbering; that is Phase 6.
- No removal of Jalali support.
- No timezone inference from language or map provider.
- No unrelated booking refactor.

**Exit criteria**

- Same canonical booking/date can render Gregorian globally and Jalali where selected.
- Business timezone contract is explicit and migration-tested.
- Existing appointment meaning is proven unchanged through migration fixtures/rehearsal.
- Background scheduling semantics are documented and tested.

**Key regression areas**

- appointment creation/reschedule/cancel;
- opening hours and availability;
- reminders/no-show windows;
- calendar exports;
- DST-sensitive IANA zones plus Tehran compatibility;
- protected booking contract manifest.

## Phase 6 — Weekday Semantics

**Goal**

Decouple weekday identity from Iran-specific persisted numbering and from first-day-of-week display conventions.

**Why this phase occurs at this point**

Current Saturday=`1`…Friday=`7` values are persisted business data. Phase 5 must first stabilize scheduling/time boundaries so weekday migration does not silently alter availability.

**Inputs/dependencies**

- Phase 5 canonical scheduling boundaries.
- Current `SalonOpeningHours` values and all weekday consumers.
- `ARC-005`.

**Major workstreams**

- Inventory every persisted/query/UI/API weekday use.
- Introduce explicit compatibility mapping for legacy numbering.
- Choose and document the approved canonical representation (ISO weekday or named enum) in the dedicated implementation design.
- Migrate persisted values only with data validation and before/after schedule equivalence tests.
- Separate first-day-of-week display preference from weekday identity.

**Explicit non-goals**

- No silent relabeling of existing integer values.
- No change to business closed/open policies unrelated to representation.
- No locale translation work beyond weekday labels required by the new boundary.

**Exit criteria**

- Stored weekday meaning is canonical or safely isolated behind a compatibility boundary.
- All existing schedules produce equivalent real weekdays after migration.
- Different locale first-day conventions can change display without changing identity.

**Key regression areas**

- opening hours;
- availability/search date windows;
- stylist schedules;
- booking date selection;
- Persian/Jalali weekday display.

## Phase 7 — Phone and Authentication Internationalization

**Goal**

Migrate account phone identity to an E.164-compatible canonical contract while preserving every valid existing Iranian account/login path and avoiding identity collisions.

**Why this phase occurs at this point**

Global SMS/OTP providers cannot be safely introduced while account identity itself is limited to Iranian `09...` format.

**Inputs/dependencies**

- Phase 1 default country/config contracts.
- Existing `CustomUser.mobile_number`, login/signup/password reset/admin/API paths, OTP/security behavior, and uniqueness constraints.
- `ARC-006`.

**Major workstreams**

- Profile existing phone data and prove deterministic Iran legacy mapping.
- Define canonical parsing/normalization service with country-aware local input.
- Detect and resolve/stop on collisions before uniqueness migration.
- Implement staged schema/data migration to E.164-compatible storage.
- Maintain legacy Iranian input compatibility during transition.
- Decouple canonical phone normalization from SMS.ir formatting.
- Update forms/admin/APIs/log masking/tests consistently.

**Explicit non-goals**

- No automatic merging of accounts with normalization collisions.
- No mandatory new SMS provider; provider expansion is Phase 14.
- No country/address migration beyond parsing defaults required for phone input.

**Exit criteria**

- New international numbers can be represented canonically.
- Existing Iranian users retain login/identity continuity.
- Uniqueness is enforced on canonical identity with collision evidence recorded.
- OTP still obeys current security/rate-limit semantics.

**Key regression areas**

- signup/login/password reset;
- account uniqueness;
- inactive-user reuse behavior;
- manager/stylist/customer role profiles;
- OTP rate limits and masking;
- admin/API compatibility.

## Phase 8 — Money and Currency

**Goal**

Give every business monetary value explicit ISO 4217 currency semantics while preserving legacy toman economic meaning and exact financial invariants.

**Why this phase occurs at this point**

International payment providers and commercial reporting cannot be correct until internal amounts have unambiguous currency semantics.

**Inputs/dependencies**

- Phase 1 default currency contract.
- Current payment, wallet, transaction, refund, commission, withdrawal, order/price, reporting, and API semantics.
- `ARC-008`.

**Major workstreams**

- Inventory every monetary field and its actual current unit.
- Choose exact storage/value-object strategy; prohibit float arithmetic.
- Design explicit migration for legacy toman-semantic values; never relabel them as `IRR` without conversion.
- Add ISO 4217 currency semantics consistently across orders/payments/wallet/ledger/refunds/payout/reporting.
- Move provider-specific rial/toman conversion fully into provider adapters.
- Add reconciliation and invariant tests around migration.

**Explicit non-goals**

- No live FX engine.
- No simultaneous mixed-currency settlement inside one order.
- No mandatory new payment gateway.
- No unrelated redesign of wallet/ledger behavior.

**Exit criteria**

- Every relevant amount has unambiguous currency interpretation.
- Legacy balances/payments reconcile exactly before and after migration.
- Wallet/ledger/order/payment/refund arithmetic remains consistent.
- Provider conversions no longer define internal currency semantics.

**Key regression areas**

- balances/running balances;
- deposits/withdrawals/refunds;
- commissions and first-visit rules;
- provider verification amount checks;
- reporting/exports;
- integer/Decimal exactness.

## Phase 9 — Country, Location, and Maps

**Goal**

Introduce explicit country/address semantics and provider-neutral map/geocoding boundaries while preserving existing GIS and Tehran behavior.

**Why this phase occurs at this point**

Map-provider globalization is unsafe until the application knows country/address independently of provider defaults. Currency/timezone contracts from earlier phases reduce ambiguity for country-aware business configuration.

**Inputs/dependencies**

- Phase 1 default country contract.
- Phase 5 business timezone context where relevant.
- Existing salon city/zone/address, `Neighborhood`, GeoDjango points/polygons, Map.ir/Neshan helpers, search filters.
- `ARC-007` and `ARC-009`.

**Major workstreams**

- Profile existing address/location records.
- Add explicit ISO country/business address structure through staged migration.
- Preserve GIS coordinates as provider-neutral data.
- Define map/geocode/search provider adapter contracts and normalized response models.
- Convert Tehran viewport/bounds to compatibility/default configuration rather than global geography rules.
- Preserve current providers while adding country-aware provider capability/routing if required.

**Explicit non-goals**

- No mandatory replacement map provider.
- No geodata rewrite unrelated to country/address needs.
- No automatic assumption that language determines country.

**Exit criteria**

- Business records can represent country explicitly.
- Address/GIS semantics are independent of map vendor.
- Existing Tehran location/search behavior remains compatible.
- Provider adapter/security tests cover current and any newly approved providers.

**Key regression areas**

- salon onboarding/location editing;
- search/map suggestions;
- GIS queries/distances;
- neighborhood relations;
- map proxy/security;
- existing Tehran links/viewport compatibility.

## Phase 10 — Frontend Locale and JavaScript

**Goal**

Make frontend date/number/currency/direction/week behavior consume the shared global context instead of hard-coded Jalali/Persian assumptions.

**Why this phase occurs at this point**

The frontend must build on stable locale, calendar/timezone, weekday, currency, and country contracts rather than create its own competing representation.

**Inputs/dependencies**

- Phases 3, 5, 6, 8, and 9.
- Existing `static/js/jalali.js`, datepicker integration, templates, and JS modules.
- `ARC-014`.

**Major workstreams**

- Define server-to-frontend locale/context payload.
- Introduce formatting utilities using browser `Intl` where sufficient.
- Isolate Jalali-specific behavior behind a focused adapter.
- Migrate components incrementally to locale direction/date/number/currency/week context.
- Remove duplicated Persian-only formatting only after equivalence tests.

**Explicit non-goals**

- No frontend framework replacement.
- No wholesale UI rewrite.
- No removal of Jalali until equivalent supported behavior exists.

**Exit criteria**

- Shared frontend components render correct English LTR and Arabic/Persian RTL structure.
- Gregorian is the default date presentation and Jalali remains selectable where supported.
- Money/date/time formatting uses explicit context, not language-to-country guesses.

**Key regression areas**

- booking date/time pickers;
- dashboards;
- price displays;
- sliders/navigation/modals;
- mobile/desktop shells;
- Persian Jalali equivalence.

## Phase 11 — Email and Notifications

**Goal**

Localize system-generated email/notification content and direction without changing trigger, preference, retry, or delivery-status contracts.

**Why this phase occurs at this point**

Notification localization depends on stable locale/direction and frontend/server content conventions but should precede provider expansion so providers receive already-localized content.

**Inputs/dependencies**

- Phase 3 locale/direction runtime.
- Phase 10 shared formatting conventions where relevant.
- Existing notification models/delivery attempts/preferences/channel dispatch.
- `ARC-012`.

**Major workstreams**

- Classify notification content as message intent versus already-rendered persisted content.
- Introduce recipient locale resolution and localized rendering/templates.
- Make email direction/layout locale-aware.
- Preserve delivery adapter/status/retry behavior.
- Add fallback/missing-translation tests for asynchronous delivery.

**Explicit non-goals**

- No provider replacement.
- No change to opt-out/preference semantics.
- No mass rewrite of historical notification text.

**Exit criteria**

- New supported notifications can render in active recipient locale.
- LTR/RTL email layouts are correct.
- Existing delivery status/preferences/retries are unchanged.

**Key regression areas**

- notification creation/dispatch;
- email sender identity;
- SMS/messaging payload content;
- delivery attempts/statuses;
- disabled-provider behavior.

## Phase 12 — Search Globalization

**Goal**

Make text normalization/query parsing locale-aware while preserving current Persian search behavior.

**Why this phase occurs at this point**

Locale and country context must exist before search can distinguish language normalization from geographic filtering.

**Inputs/dependencies**

- Phase 3 locale context.
- Phase 9 country/location context.
- Existing search normalization/ranking/filtering/logging.
- `ARC-013`.

**Major workstreams**

- Separate universal-safe normalization from locale-specific rules.
- Preserve Persian/Arabic character equivalence and digit behavior under Persian context.
- Add English and Arabic normalization/query tests.
- Review boolean/value parsing, collation, ranking, and searchable content behavior.
- Keep geographic context separate from text normalization.

**Explicit non-goals**

- No automatic translation of user-entered content.
- No mandatory cross-language semantic search/AI search.
- No ranking rewrite unrelated to globalization.

**Exit criteria**

- Search normalization behavior is explicit per supported locale.
- Existing Persian queries remain compatible.
- English/Arabic inputs are not corrupted by Persian-only transformations.

**Key regression areas**

- query/filter parsing;
- rankings/sorts;
- Persian digit/character equivalence;
- location filters;
- search logs and APIs.

## Phase 13 — Help Center and Lumi Localization

**Goal**

Create locale/country/provider-aware support content selection while preserving Lumi behavior and existing Iran/Persian documentation.

**Why this phase occurs at this point**

Support content must reflect the product contracts implemented in earlier phases and must know locale/country/provider applicability before international commercial use.

**Inputs/dependencies**

- Phase 3 locale context.
- Phase 9 country/provider context.
- Existing Help Center content services, Lumi retrieval/domain services, and Iran/Persian corpus.
- `ARC-016`.

**Major workstreams**

- Define content metadata for locale and applicability.
- Build deterministic corpus selection/fallback.
- Author/review English global content aligned with implemented behavior.
- Add optional Arabic/Persian variants incrementally.
- Prevent retrieval from mixing incompatible country/provider guidance.
- Preserve AI/Lumi guardrails, permissions, and supported actions.

**Explicit non-goals**

- No unreviewed machine translation as authoritative documentation.
- No new Lumi product capabilities unrelated to localization.
- No deletion of existing Iran documentation.

**Exit criteria**

- Support answers can be grounded in an explicitly applicable locale/country corpus.
- Existing Iran/Persian corpus remains accessible.
- Retrieval/fallback behavior is tested for missing variants.

**Key regression areas**

- Help Center routing/search;
- Lumi retrieval/grounding;
- permission/action guardrails;
- provider-specific guidance;
- fallback behavior.

## Phase 14 — Messaging and SMS Providers

**Goal**

Generalize OTP, transactional SMS, and messaging provider adapters for international deployment while retaining existing SMS.ir/Bale/Telegram compatibility.

**Why this phase occurs at this point**

Canonical E.164 identity from Phase 7 and localized notification content from Phase 11 must exist before global provider delivery is safe.

**Inputs/dependencies**

- Phase 7 canonical phone identity.
- Phase 11 localized notification content/status semantics.
- Existing SMS/messaging feature flags, delivery attempts, webhook/security rules, and adapters.
- `ARC-010`.

**Major workstreams**

- Define stable OTP/SMS/messaging adapter contracts and capability metadata.
- Move provider-specific phone formatting fully inside adapters.
- Preserve status/error/retry mapping and security/webhook verification.
- Add provider routing/configuration by deployment/capability as requirements demand.
- Add any international provider only through a separate approved adapter task.

**Explicit non-goals**

- No mandatory provider replacement.
- No removal of SMS.ir/Bale/Telegram solely because they are regional.
- No change to canonical account identity rules.

**Exit criteria**

- Providers consume canonical E.164 identity and stable message intent/content.
- Existing providers pass compatibility contract tests.
- At least the documented provider configuration model supports country/deployment-specific selection without application rewrites.

**Key regression areas**

- OTP delivery/security;
- transactional SMS statuses;
- messaging links/webhooks;
- notification preferences/retries;
- feature flags and disabled states.

## Phase 15 — Payments and Payouts

**Goal**

Make online payment and payout rails provider-neutral and country-aware after internal currency semantics are explicit, while preserving Pay at Salon and existing financial truth.

**Why this phase occurs at this point**

Gateway globalization before Phase 8 would reproduce implicit currency errors. Country/address context from Phase 9 is also required for payout eligibility/details.

**Inputs/dependencies**

- Phase 8 money/currency contract.
- Phase 9 country context.
- Existing payment result/verification boundaries, wallet/ledger/state transitions, refund logic, withdrawal safeguards, and provider flags.
- `ARC-011`.

**Major workstreams**

- Formalize gateway adapter interface around canonical amount/currency and provider unit conversion.
- Preserve local verification/integrity and idempotency rules.
- Keep `pay_in_salon` as a product payment method independent of gateways.
- Model payout rails/details as country/provider-specific capability rather than universal Sheba fields.
- Add new gateway/payout adapters only when commercially approved.
- Maintain reconciliation and financial auditability.

**Explicit non-goals**

- No mandatory Stripe or other specific global vendor.
- No FX engine.
- No mixed-currency settlement inside a single order.
- No removal of Pay at Salon.

**Exit criteria**

- Application payment methods are independent of gateway vendor.
- Gateway adapters receive explicit currency and own unit conversion only.
- Wallet/ledger/payment/refund invariants remain green.
- Country-specific payout data can be isolated behind a documented rail/profile contract.

**Key regression areas**

- payment initiation/verification;
- amount integrity checks;
- payment state/idempotency;
- refunds;
- wallet/ledger;
- withdrawals/payout permissions;
- `pay_in_salon` checkout behavior.

## Phase 16 — SEO, Legal, and Product Metadata

**Goal**

Make public metadata locale/brand aware and establish explicit country/jurisdiction applicability for legal content.

**Why this phase occurs at this point**

SEO/legal routing depends on stable branding, locale, country, and public URL behavior. Doing it earlier risks locking the wrong URL/canonical strategy.

**Inputs/dependencies**

- Phase 2 branding.
- Phase 3 locale runtime.
- Phase 9 country context.
- English-first product/content coverage from earlier phases.
- `ARC-017`.

**Major workstreams**

- Decide public locale URL strategy and document compatibility/migration impact.
- Implement localized titles/descriptions/social metadata.
- Define canonical/hreflang behavior consistent with routing.
- Inventory legal/privacy/terms content and define jurisdiction/locale ownership.
- Prevent unsafe cross-jurisdiction legal fallback.
- Preserve existing public URLs or introduce redirects/versioning where required.

**Explicit non-goals**

- No speculative marketing-site rewrite.
- No legal-content invention without owner/approval.
- No domain migration unless explicitly approved.

**Exit criteria**

- Public pages emit correct locale/brand metadata.
- Canonical/hreflang policy is testable and documented where applicable.
- Required legal content has explicit applicability and fallback behavior.

**Key regression areas**

- salon/public canonical URLs;
- metadata fallbacks;
- sitemap/indexing behavior;
- social cards;
- existing URL compatibility.

## Phase 17 — Deployment and Installability

**Goal**

Make the product installable through documented standard environment/runtime contracts while retaining Liara as a supported deployment path.

**Why this phase occurs at this point**

Portable deployment documentation must reflect the configuration, database, GIS, jobs, storage, and provider contracts that actually survived implementation.

**Inputs/dependencies**

- Stable configuration/environment contracts from Phases 1–16.
- Existing CI, Liara configuration/workflow, GIS dependencies, storage/cache/job settings, and production safety tests.
- `ARC-018`.

**Major workstreams**

- Deliberately resolve/document supported Python version(s), including current Liara `3.12` versus CI `3.13` difference.
- Document dependency/system/GIS/database setup.
- Define standard environment variable reference and startup/migration/admin procedures.
- Define background-job/scheduler contract independent of Liara cron implementation.
- Validate a supported non-Liara installation path without weakening Liara.
- Document static/media/storage/cache/provider configuration and release checks.

**Explicit non-goals**

- No Kubernetes requirement.
- No speculative microservices.
- No infrastructure modernization unrelated to portability.
- No provider behavior changes hidden inside deployment work.

**Exit criteria**

- A clean environment can install/run the supported product using documented contracts.
- Liara remains a supported implementation.
- Python-version policy is explicit and CI/runtime-aligned or intentionally matrix-tested.
- Deployment safety checks remain green.

**Key regression areas**

- `manage.py check`;
- migration drift;
- production settings hygiene;
- GIS availability;
- collectstatic/static/media;
- job scheduling;
- environment/secret failures;
- Liara deployment guards.

## Phase 18 — Commercial Packaging

**Goal**

Package the stabilized configuration and operational knowledge so a commercial buyer can configure brand, locale, country, currency, timezone, and supported providers without source-code scavenger hunts.

**Why this phase occurs at this point**

Buyer documentation and packaging should describe stable, tested capabilities rather than promises from unfinished implementation phases.

**Inputs/dependencies**

- Phases 2–17 sufficiently complete.
- Validated installation/environment/provider contracts.
- Final supported locale/country/currency/provider scope for the release.

**Major workstreams**

- Produce buyer/operator configuration guide and environment reference.
- Provide brand asset/color setup instructions.
- Document database/migration/admin/bootstrap workflow.
- Document supported locales and optional Persian behavior.
- Document country/currency/timezone setup and provider capability matrices.
- Provide upgrade/migration notes from Iran/Persian legacy baseline where supported.
- Define supportability boundaries and known unsupported combinations.

**Explicit non-goals**

- No new core feature implementation to improve packaging aesthetics.
- No promise of providers/locales/countries not validated in earlier phases.
- No multi-tenant rewrite or hosted-control-plane requirement.

**Exit criteria**

- A buyer can follow documentation to reach the release goal using supported combinations.
- Required configuration does not demand editing dozens of unrelated source files.
- Unsupported/deferred capabilities are explicit.

**Key regression areas**

- fresh install walkthrough;
- environment examples/defaults;
- brand configuration;
- locale/country/currency/timezone/provider setup;
- upgrade documentation consistency.

## Phase 19 — Full Regression and Release Candidate

**Goal**

Validate the complete globalization release candidate across compatibility, migrations, locales, finance, scheduling, providers, security, and installability before commercial release.

**Why this phase occurs at this point**

Only an integrated release-candidate pass can prove that individually correct phases did not break cross-domain invariants or current Persian/Iran behavior.

**Inputs/dependencies**

- All prior implementation phases and commercial packaging.
- Existing repository tests/contracts plus new globalization regression suites.
- Migration rehearsal datasets and supported deployment/provider matrices.
- `ARC-019`.

**Major workstreams**

- Run full backend test suite and mandatory CI/release checks.
- Run frontend build and targeted browser/bidirectional/date/time regression where available.
- Rehearse migrations from representative legacy Iran/Persian data.
- Validate English default, Arabic RTL architecture/content scope, and optional Persian behavior.
- Validate booking/timezone/weekday equivalence and financial reconciliation.
- Validate phone identity/login/OTP compatibility.
- Validate Pay at Salon independent of online provider availability.
- Validate supported map/SMS/messaging/payment/payout adapter configurations.
- Execute fresh-install/commercial packaging walkthrough.
- Record known limitations and block release on Critical/High correctness/security regressions.

**Explicit non-goals**

- No unrelated cleanup/refactor during release validation.
- No late provider/framework/infrastructure replacement without returning to the responsible phase.
- No weakening tests to force a green release candidate.

**Exit criteria**

- Full required test/build/release matrix is green for the supported release scope.
- Legacy migration reconciliation is proven for identity, scheduling, weekday, and money contracts.
- Existing authorization/security/financial invariants are intact.
- Commercial install/configuration walkthrough succeeds.
- Known limitations are documented and accepted; no unresolved release-blocking globalization defects remain.

**Key regression areas**

- all `GLO-001`…`GLO-019` owner outcomes;
- booking and appointment timing;
- authorization/workspace separation;
- phone/login/OTP;
- money/ledger/payment/refund/payout;
- locale/direction/calendar/timezone/weekday;
- maps/search;
- notifications/messaging;
- SEO/legal/public URLs;
- deployment/installability.

## Cross-Phase Regression Requirements

Every implementation phase must preserve these cross-cutting contracts unless its approved scope intentionally changes them:

- booking creation, checkout, scheduling, reschedule/cancel, and appointment timing correctness;
- customer/stylist/manager authorization and workspace-preference separation;
- Pay at Salon as a valid product capability;
- wallet/ledger exact arithmetic, payment state transitions, refunds, and payout safeguards;
- notification preferences, delivery statuses, retries, feature flags, and provider security verification;
- public/API contracts unless intentionally versioned;
- deployment safety guards and production-settings hygiene;
- current Persian/Iran behavior through each migration's explicit compatibility window.

Data-contract phases (5–9 and relevant provider phases) additionally require:

- before/after migration fixtures or rehearsals;
- invariant/reconciliation checks;
- collision/ambiguity detection where identity or normalization changes;
- no silent default-based reinterpretation of existing records;
- explicit rollback/recovery approach where migration risk justifies it.

Provider phases require adapter contract tests that separate application semantics from provider wire formats. Presentation phases require locale fallback and LTR/RTL regression. No phase may delete an existing behavior test solely because the current market assumption is inconvenient; the task changing that contract owns the replacement compatibility evidence.

## Deferred / Explicitly Out of Scope

Unless separately approved, the roadmap explicitly defers:

- full Arabic translation in one task;
- immediate Stripe integration;
- any mandatory new payment provider;
- a live FX engine;
- simultaneous multi-currency settlement inside one order;
- a new multi-tenant rewrite;
- frontend framework replacement;
- Django rewrite;
- wholesale UI rewrite;
- removal of current providers merely because they are regional;
- removal of Pay at Salon;
- speculative microservices;
- Kubernetes or infrastructure modernization unrelated to portability;
- unapproved account merges during phone normalization;
- silent conversion/relabeling of existing monetary or weekday data;
- automatic legal-jurisdiction fallback that implies unsupported coverage.

Additional architecture choices intentionally remain deferred until their owning phase has enough evidence: exact locale URL strategy, exact phone schema transition, exact money storage migration shape, exact country/address fields, exact business-timezone field placement, final weekday canonical representation, international provider selection, Help/Lumi authoring workflow, legal content ownership process, and final supported Python version.

## Release Exit Criteria

A commercial globalization release is eligible for release only when all of the following are true for the declared supported scope:

- Phase 0–19 required exit criteria are satisfied or explicitly waived through project review with documented risk.
- English is the configured global default and the primary commercial product flows are usable in English.
- Arabic can use the RTL-capable architecture; actual translation coverage is documented and not overstated.
- Persian remains optionally supported with compatibility/regression coverage.
- Gregorian is the global calendar presentation default, and Jalali remains available where supported without changing canonical date meaning.
- Business/salon timezone can be represented with an explicit IANA identifier, and migrated appointments preserve real-world meaning.
- Weekday identity/display conventions are separated and legacy persisted meanings are safely migrated or compatibly isolated.
- Canonical phone identity is E.164-compatible; existing Iranian accounts retain identity/login continuity and uniqueness is collision-safe.
- Business monetary values have explicit ISO 4217 semantics with exact arithmetic; legacy toman semantics are reconciled rather than relabeled.
- Country/address data is explicit enough for the supported markets and independent from map provider implementation.
- Maps, SMS, messaging, payments, and payouts use documented provider boundaries; existing supported providers may remain adapters.
- `pay_in_salon` remains available according to product rules and is not dependent on online gateway availability.
- Brand name/display name, domain/public URLs, email identity, logo/favicon, colors, and public metadata can be configured through documented supported contracts.
- Help Center/Lumi content selection can distinguish supported locale/country/provider applicability.
- SEO/public metadata and required legal content have documented locale/country behavior for supported releases.
- A supported installation can be configured through standard environment/database/runtime contracts without relying conceptually on Liara, while Liara remains supported if retained.
- The Python/runtime support policy is deliberate and validated.
- A buyer can clone, configure environment/database, run migrations, create an admin, configure brand/country/currency/timezone/language/providers, and deploy the supported product without editing dozens of unrelated source files.
- Full release-candidate regression is green, including existing security/authorization/financial/deployment contracts and the globalization migration matrix.
- Deferred and unsupported capabilities are documented clearly rather than implied to work.
