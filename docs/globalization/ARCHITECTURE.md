# Loomera Global — Target Architecture

## Purpose

This document defines the target globalization architecture for Loomera Global. It is an architecture contract for later implementation work, not an implementation change. It establishes boundaries, compatibility requirements, configuration ownership, migration principles, provider-neutral interfaces, and stable architectural decisions that future phases must follow.

Loomera Global is an evolution of the existing Loomera application, not a rewrite. Existing production behavior remains authoritative until a dedicated later task intentionally changes a contract with explicit migration and regression coverage.

## Baseline and Audit Inputs

This architecture is based on the current Target repository at the Task 0.4 base and on the completed Phase 0 documents:

- [SOURCE_IMPORT.md](./SOURCE_IMPORT.md) — provenance and exact Source snapshot import.
- [BASELINE_VERIFICATION.md](./BASELINE_VERIFICATION.md) — imported baseline verification and CI evidence.
- [GLOBALIZATION_AUDIT.md](./GLOBALIZATION_AUDIT.md) — evidence-based findings `GLO-001` through `GLO-019`.

Repository baseline for this architecture:

- Target repository: `alireza-anari/loomera-global`
- Task 0.4 base SHA: `b5989c079891607e6f67371fceabad674213a458`
- Task 0.4 base tree: `7d50e86c605c52b6962caec65bf7256be5810f32`
- Source provenance repository: `alireza-anari/loomera`
- Source pinned SHA: `502f3a5a44451fcbe480bfc7a2f0e7a5c3b1f90a`
- Source pinned tree: `ed0de5edb110ce78b05f1e7296ebf362c40adba9`
- Task 0.3 post-merge CI: run `38114646984`, `Loomera CI`, `push` on `main`, completed with `success`.

The current implementation already provides useful seams: Django i18n and timezone support, `LocaleMiddleware`, environment-backed brand and provider settings, GeoDjango/GIS data, payment gateway result objects, notification channel/provider dispatch, feature flags, and targeted regression/security tests. The architecture extends those seams rather than introducing a parallel platform.

The Critical/High audit findings have explicit architecture owners:

| Audit finding | Primary architecture response |
| --- | --- |
| `GLO-001` Persian runtime language | `ARC-001` Locale |
| `GLO-003` Jalali/calendar coupling | `ARC-003` Calendar |
| `GLO-004` Tehran timezone assumption | `ARC-004` Timezone |
| `GLO-005` persisted weekday semantics | `ARC-005` Weekday |
| `GLO-006` Iranian phone identity | `ARC-006` Phone and authentication |
| `GLO-007` Tehran/country/map coupling | `ARC-007` Country/address and `ARC-009` Maps |
| `GLO-008` implicit monetary unit/currency | `ARC-008` Money/currency |
| `GLO-009` Iran-specific payment/payout rails | `ARC-011` Payments/payouts |
| `GLO-010` SMS.ir/phone coupling | `ARC-010` SMS/messaging |

## Architectural Principles

1. **Compatibility first.** Preserve current booking, authorization, financial, notification, API, provider-security, and deployment semantics unless a dedicated task changes them deliberately.
2. **English-first global default.** The target default locale is English. Arabic is a supported RTL-capable locale. Persian remains a supported optional locale and is not removed.
3. **Gregorian global presentation default.** Gregorian is the global default calendar presentation. Jalali remains a locale-specific presentation capability.
4. **Explicit context over global assumptions.** Country, currency, business timezone, locale, calendar presentation, and provider choice must be explicit or resolved from a documented default rather than inferred from Iran-specific behavior.
5. **Separate presentation from persisted meaning.** Language, direction, calendar display, number formatting, and first-day-of-week presentation must not silently reinterpret stored business data.
6. **Provider neutrality at application boundaries.** Maps, SMS, messaging, online payment, and payout capabilities are application concepts; existing regional providers may remain adapters.
7. **Exact money and identity contracts.** Money must have unambiguous currency semantics and exact arithmetic; phone identity must have an international canonical representation with collision-safe migration.
8. **Business-local time, UTC-aware persistence.** Timestamp persistence remains timezone-aware; business wall-clock rules are interpreted through an explicit IANA timezone.
9. **Configuration ownership is explicit.** Deployment defaults, business data, and request/user preferences are separate scopes with predictable precedence.
10. **No speculative rewrite.** No microservice split, frontend-framework replacement, Django rewrite, multi-tenant rewrite, or unrelated infrastructure modernization is implied by globalization.
11. **Regression evidence is part of architecture.** Existing tests and contract manifests are behavior evidence. Migrations and provider changes require compatibility tests, not deletion of inconvenient expectations.
12. **Portable installation target.** Liara may remain supported, but the product architecture is defined by standard environment/runtime contracts rather than by Liara-specific behavior.

## Compatibility Contract

Unless a dedicated later task explicitly changes a contract, globalization work must preserve:

- booking creation and scheduling semantics;
- appointment timing correctness;
- existing customer, stylist, manager, and administrative authorization boundaries;
- the separation between workspace preference and authorization;
- Pay at Salon (`pay_in_salon`);
- financial ledger arithmetic and balance invariants;
- payment state transitions and provider-verification integrity rules;
- refund semantics;
- wallet behavior;
- payout safeguards;
- notification preference, delivery-status, retry, and feature-flag semantics;
- provider verification/security behavior while a provider remains supported;
- public/API contracts unless intentionally versioned;
- deployment safety guards;
- current Persian/Iran behavior until the dedicated migration task for that behavior changes it.

Future tasks must classify every globalization change into one or more of these change types before implementation:

1. **Presentation change** — translation, direction, formatting, calendar rendering, display labels, or frontend presentation without changing stored meaning.
2. **Configuration change** — new or changed deployment/business/user configuration with existing data semantics preserved.
3. **Data-contract change** — a new canonical representation or new persisted semantic, such as E.164 phone identity, ISO country, IANA timezone, or ISO 4217 currency.
4. **Migration** — transformation or compatibility handling for existing persisted values. Migrations require preflight data analysis, collision/invariant checks, rollback or recovery planning where appropriate, and explicit regression coverage.
5. **Provider substitution** — changing or adding an external adapter while application-level capability and security/status semantics remain stable.

A task may contain more than one class, but it must not hide a data-contract change inside a presentation or provider change.

## Target Configuration Model

The target model has three configuration scopes.

### Deployment-level defaults

Deployment configuration supplies safe defaults and globally enabled capabilities for one installation. These are environment/config contracts, not business records. Examples include enabled languages, default language, default country, default currency, fallback timezone, brand identity, public URLs, email sender identity, and enabled provider adapters.

### Business/salon-level data

Business data represents facts that can differ by salon/business and must eventually be persisted when the product supports that difference. Examples include business country, IANA timezone, address structure, and—if commercial requirements require it—business primary currency and business-specific presentation preferences. Business configuration must not be inferred from map or payment provider choice.

### Request/user locale context

Request/user context controls presentation and communication for a specific user/request. Examples include active language, direction, calendar presentation, number/date formatting, and eventually authenticated user locale preference. It must not grant authorization or change business ownership/security scope.

### Conceptual ownership matrix

| Concern | Deployment-level | Business/salon-level | Request/user context |
| --- | --- | --- | --- |
| Default language | Required default; target `en` | Optional future policy only if needed | Active language/preference |
| Enabled languages | Required allow-list | Not initially required | Must be within enabled set |
| Default country | Required ISO default | Explicit business country target | Used only as parsing/display fallback |
| Default currency | Required ISO 4217 default | Explicit business primary currency if/when supported | Display formatting only; cannot reinterpret amounts |
| Default timezone | Required IANA fallback | Explicit business IANA timezone target | Display conversion may use user zone only where product semantics allow |
| Calendar default | Global default Gregorian | Optional business policy only if required | Locale/user presentation preference |
| First day of week | Display fallback | Optional business display convention | Locale/user display convention |
| Brand name/display name | Primary ownership | No per-salon white-label requirement in initial architecture | Read-only presentation |
| Domain/public URLs | Primary ownership | Not initial business data | Request host may inform URL generation through approved configuration |
| Email identity | Primary ownership | Optional future business sender only if explicitly required | Locale selects content, not sender authority |
| Map provider | Enabled/default adapter | Optional provider routing only if coverage requires it | No direct provider ownership |
| SMS provider | Enabled/default adapter | Optional routing policy later | No canonical phone normalization authority |
| Payment provider | Enabled/default adapter set | Business/provider eligibility may be configured later | User selects product payment method, not arbitrary provider |
| Messaging providers | Enabled/allowed adapters | Business/channel availability may be policy-driven | User/channel preference within allowed capabilities |

### Resolution rules

- Deployment configuration defines defaults and enabled capabilities.
- Business data overrides only concerns explicitly modeled as business facts; it never silently overrides user authorization or account identity.
- Request/user locale context controls presentation only within enabled deployment capabilities.
- Provider settings resolve adapter selection but do not define country, currency, phone identity, or geography semantics.
- Missing business data during migration uses an explicit compatibility fallback, not an inferred provider-based value.

No configuration changes are implemented by Task 0.4.

## Locale Architecture

The target locale model is English-first with English (`en`) as the global default, Arabic (`ar`) as an RTL-capable supported locale, and Persian (`fa`) as an optional supported locale.

Django's existing `LocaleMiddleware` remains the runtime foundation. A later implementation phase should define an enabled `LANGUAGES` set and a single locale-resolution service/policy. Conceptual precedence is:

1. explicit authenticated user preference, when implemented and enabled;
2. explicit session/cookie language selection;
3. accepted request language/header behavior allowed by Django/application policy;
4. deployment default language (`en` target).

All selected locales must be constrained to the enabled-language set. Fallback must be deterministic and must never select a disabled locale.

Translated application strings and user-entered content are separate concerns. UI/system strings can be translated. User-entered salon names, descriptions, reviews, addresses, service names, and similar content must not be automatically treated as translations or rewritten because the request locale changes.

Public URL language strategy (for example URL prefixes versus non-prefixed locale negotiation) is deferred to the SEO/public-routing phase because it affects canonical/hreflang contracts.

## Directionality Architecture

Direction is derived from the active locale, not stored as a product-global constant. Locale metadata must declare whether the language is LTR or RTL.

- English: LTR.
- Arabic: RTL.
- Persian: RTL.

The document shell, reusable components, emails, and locale-aware frontend behavior should receive direction from the same locale context. Future CSS work should prefer logical layout concepts where practical, but Task 0.4 does not redesign CSS.

Existing Persian RTL behavior is a compatibility requirement and must be regression-tested when direction becomes dynamic.

## Calendar Architecture

Four concepts must remain separate:

1. persisted date/time values;
2. business scheduling calculations;
3. calendar input/output representation;
4. locale-specific date formatting.

The global presentation default is Gregorian. Jalali is a supported locale/presentation capability, particularly for Persian users, but it must not remain the universal application calendar.

Business scheduling calculations operate on canonical date/time values, not on rendered Jalali labels. Calendar input adapters convert user-entered calendar values to canonical dates before domain logic; output formatters convert canonical values to the selected calendar representation.

Task 0.4 does not assert that existing database dates require transformation. Any field found later to persist Jalali-encoded strings or non-canonical calendar values requires a dedicated migration design. Existing Jalali dependencies remain until later phases prove they can be retained, isolated, or removed safely.

## Timezone Architecture

Timezone-aware timestamp persistence remains the baseline. UTC/timezone-aware instants should be the canonical representation for real instants where Django model semantics already support them.

Business wall-clock concepts—opening times, appointment-local display, reminder windows, no-show windows, and similar rules—must be interpreted using an explicit salon/business IANA timezone. The deployment timezone becomes a fallback for legacy records and operational defaults, not the permanent business-time definition.

Target resolution is:

1. explicit business IANA timezone when available;
2. documented legacy compatibility fallback during migration;
3. deployment fallback timezone for operations that are not business-specific.

A future timezone migration must preserve the real-world meaning of existing appointments. Adding a timezone field and changing `TIME_ZONE` are separate operations and must not be combined without data analysis.

Scheduled jobs must declare whether their schedule is UTC, deployment-local, or business-local. Platform cron timezone must not silently define business appointment semantics.

## Weekday Architecture

The current persisted contract maps Saturday=`1` through Friday=`7`. That numeric meaning is protected until an explicit migration changes it.

The target boundary separates:

- **weekday identity** — a locale-neutral canonical value;
- **first-day-of-week display preference** — a locale/business/user presentation convention;
- **weekend/business closure policy** — business data, not a language property.

A future canonical representation may use ISO weekday identity (`Monday=1` through `Sunday=7`) or a named enum, but existing persisted integers must never be reinterpreted in place. The implementation roadmap requires a compatibility adapter and explicit data migration before any stored-value conversion.

## Phone and Authentication Architecture

The target canonical phone contract is E.164-compatible.

- Persisted canonical identity must represent international numbers unambiguously.
- Parsing is country-aware when local-format input is accepted.
- International uniqueness applies to the canonical form.
- Existing Iranian `09...` accounts require a migration path that maps to the correct `+98...` canonical identity without collisions.
- Login must remain compatible during migration, allowing approved legacy input forms to resolve to the same account.
- OTP delivery consumes canonical phone identity; a provider adapter may transform that identity into its required wire format.
- Provider-specific normalization must not be the canonical identity rule.
- Migration preflight must detect collisions or ambiguous records before enforcing a new unique canonical constraint.
- No automatic account merge is allowed merely because normalization produces a collision.

Authentication migration requires dedicated schema, data-migration, login/OTP compatibility, security, and regression tasks.

## Country and Address Architecture

The product requires an explicit country concept. The target canonical country identifier is ISO 3166-1 alpha-2 unless a later requirement demonstrates a need for another standard representation.

Country/address data, GIS coordinates, map display, search/geocoding, and provider implementation are separate concerns.

The target address boundary can represent country plus administrative/locality/postal/address-line data without assuming Iranian city/zone structure. Exact fields and migration mechanics are deferred to the country/location phase because current free-form data must be profiled first.

GeoDjango point/polygon capabilities remain useful and should be preserved. Coordinates are provider-neutral geographic data; they are not owned by Map.ir, Neshan, or any other map vendor.

Deployment default country is a fallback for new configuration and parsing. Existing records must not be mass-assigned or reinterpreted without an evidence-based migration.

## Money and Currency Architecture

Every business monetary value must have unambiguous currency semantics. The target domain contract is an exact amount plus an ISO 4217 currency code.

Rules:

- no floating-point arithmetic for business money;
- exact integer/decimal storage is required;
- currency code is explicit at the appropriate monetary boundary;
- order, payment, wallet, ledger, refund, payout, reporting, and API interpretations must agree on the currency of each amount;
- the initial commercial architecture uses a configured primary currency per deployment/business context rather than introducing an FX engine;
- simultaneous multi-currency settlement inside one order is not required;
- provider unit conversion belongs at the provider adapter boundary.

Existing data is especially sensitive: current application amounts carry legacy toman semantics while Zibal adapters send rials. Existing numeric values must **not** simply be labeled `IRR`, because that would change their value by a factor of ten. A dedicated Phase 8 migration must choose and test an explicit legacy-to-ISO representation strategy while preserving ledger arithmetic and financial meaning.

## Maps and Geospatial Architecture

The application map capability is provider-neutral. Application/domain code owns geography, coordinates, viewport intent, location search intent, and address/search results. Provider adapters own vendor requests, credentials, response mapping, links, rate limits, and provider-specific error handling.

Map.ir and Neshan may remain supported adapters. Their Tehran defaults or coverage assumptions must not define the application's country/address model.

A default map viewport is configuration. A business location point is data. Geocoding/search is a capability. These must not be collapsed into one provider-specific helper contract.

Provider replacement is not required in this architecture task.

## Messaging and SMS Architecture

The target communication boundary separates:

- OTP delivery;
- transactional SMS;
- notification/messaging channels;
- provider adapter selection;
- delivery status and attempt history;
- feature flags and capability enablement.

Canonical phone identity is resolved before provider dispatch. SMS adapters receive a canonical number plus message/template intent and perform only provider-specific wire-format conversion.

Existing SMS.ir, Bale, Telegram, and other current channels may remain adapters. Existing delivery-status, retry, feature-flag, security, preference, and webhook verification behavior remains protected until a dedicated provider task changes it.

Provider availability may differ by country/deployment, but provider selection must not determine canonical country or phone semantics.

## Payment and Payout Architecture

The target financial boundary separates:

- **product payment method** — for example `pay_in_salon`, wallet, online payment;
- **gateway provider** — for example Zibal or Zarinpal;
- **currency/unit conversion** — explicit adapter responsibility;
- **provider verification** — integrity and provider-specific response validation;
- **wallet** — internal balance capability;
- **ledger** — financial source-of-truth transitions and invariants;
- **payout rail** — business withdrawal/settlement mechanism and country-specific bank details.

`pay_in_salon` remains a valid provider-independent product payment method. It is not legacy provider debt and must not be removed as part of globalization.

Existing gateway result objects and verification boundaries are useful foundations. Provider adapters should remain unable to silently mutate ledger/order truth; domain/application services own state transitions and idempotency.

Zibal/Zarinpal may remain adapters. No mandatory global payment provider is selected. Payout rails must be country-aware and must not assume Iranian Sheba/IBAN/mobile fields are universal.

## Email and Notification Localization

Notification intent, recipient, channel, preference, delivery status, and localized content generation are separate concerns.

The target notification pipeline resolves locale before rendering system-generated content. Email/SMS/messaging adapters receive rendered content plus delivery metadata; they do not choose business locale.

Authenticated user preference should be used when available. For recipients without a user preference, a deterministic fallback based on request/business/deployment policy must be used.

Current notification title/body storage and triggering behavior must not be silently changed. A future phase must determine which notification records represent already-rendered content versus renderable message intent before changing persistence.

RTL/LTR email presentation derives from locale. Sender identity remains deployment/brand configuration unless a dedicated business-sender requirement is approved.

## Search and Text Normalization Architecture

Search normalization becomes a locale-aware pipeline rather than a single Persian-specific normalization rule.

The target separates:

- universal normalization that is safe across languages;
- locale-specific normalization/token rules;
- query parsing and boolean/value interpretation;
- collation/ranking behavior;
- geographic search context.

Existing Persian/Arabic-character equivalence and digit normalization are compatibility behavior for Persian search and must remain covered by regression tests. English and Arabic support should be added without globally applying Persian transformations to all text.

User-entered content is not translated automatically for search. Cross-language synonym/transliteration features are optional later enhancements, not initial architecture requirements.

## Frontend Locale Architecture

Frontend locale behavior must consume the same conceptual locale context as Django-rendered pages.

The target frontend locale contract includes:

- active locale identifier;
- direction;
- calendar preference;
- date/time formatting context;
- number/currency formatting context;
- first-day-of-week display preference where needed.

Browser `Intl` capabilities should be preferred for standards-based formatting when they satisfy product requirements, with narrow adapters for Jalali or unsupported behavior. The existing custom Jalali implementation remains until later phases provide compatible behavior.

Frontend modules must not infer country or currency from language alone. Arabic does not imply one country/currency, and English does not imply one timezone.

## Branding Architecture

The target branding model builds on current environment-backed brand/domain/email foundations rather than inventing an unrelated subsystem.

A single deployment-level brand configuration owns:

- brand name and display name;
- logo and favicon references;
- brand colors/design tokens;
- public domain and base/site URLs;
- sender identity;
- support/contact addresses;
- public/SEO brand identity.

Templates, emails, metadata, generated calendar identifiers, and public assets should consume this centralized configuration or derived context rather than duplicate literals across apps.

No per-salon white-label/multi-tenant branding system is required by the initial architecture. Loomera is not renamed in Task 0.4.

## Help Center and Lumi Content Architecture

Help Center/Lumi content must become explicitly locale- and applicability-aware.

Target content metadata should be able to identify at least language/locale and, where operational instructions differ, country/provider applicability. Content selection should prefer the best matching supported corpus and use a documented fallback; it must not mix incompatible jurisdiction/provider instructions into one answer.

The existing Iran/Persian production corpus remains supported during migration. User-facing AI/Lumi behavior, permissions, supported actions, and safety/guardrail boundaries must not be changed merely to localize content.

Automatic machine translation is not assumed as the authoritative content pipeline.

## SEO and Legal Metadata Architecture

Public metadata becomes locale-aware and brand-aware. Title/description/social metadata should derive from translated system content plus centralized brand/public URL configuration.

Canonical and hreflang behavior depends on the future public URL locale strategy and is therefore finalized in the SEO/legal phase, not guessed in Task 0.4.

Legal content must be explicitly applicable to the relevant country/jurisdiction and locale. A missing legal document must not silently fall back to a different jurisdiction in a way that implies legal coverage.

Existing public URLs and metadata remain protected until the dedicated phase introduces versioned/compatible behavior.

## Deployment and Installability Architecture

The portable target is defined by documented standard environment and runtime contracts:

- Python/runtime version support;
- dependency installation;
- database connection and migration contract;
- GIS/system dependencies where required;
- static/media storage configuration;
- cache/background-job configuration where enabled;
- environment variables and secrets;
- admin/bootstrap procedure;
- provider configuration;
- health/check/release validation.

Liara remains a supported deployment implementation, not the conceptual architecture itself.

The current difference between Liara Python `3.12` and CI Python `3.13` is a deliberate issue for the deployment/installability phase. Task 0.4 does not choose a new version or modify either environment.

Kubernetes, microservices, or unrelated infrastructure modernization are not required for portability.

## Testing and Regression Architecture

Globalization changes require layered regression evidence:

- preserve current Persian/Iran behavior until intentionally migrated;
- test English LTR and Arabic/Persian RTL shell behavior;
- test locale fallback and disabled-locale behavior;
- test Gregorian/Jalali representation against the same canonical dates;
- test timezone conversions and daylight-saving-sensitive IANA zones where applicable;
- test legacy weekday mapping before/after any migration;
- test E.164 normalization, legacy Iranian login compatibility, uniqueness, and collision handling;
- test exact currency semantics and financial invariants before/after migration;
- test provider adapters through contract/mocked integration boundaries;
- test Pay at Salon independently from gateway availability;
- test country/address/map behavior independently from a single map provider;
- test notification localization without changing delivery preference/status semantics;
- retain migration-drift, deployment-guard, and production-settings hygiene checks;
- use full regression before commercial release.

Existing booking contract manifests, payment/security tests, provider tests, and authorization tests are evidence to preserve and evolve deliberately.

## Architectural Decisions

### ARC-001 — Locale selection and English-first default

**Context:** `GLO-001` confirms a fixed Persian runtime baseline while Django i18n and `LocaleMiddleware` already exist.

**Decision:** The target default locale is English. Enabled locales are explicitly configured, with English, Arabic, and optional Persian supported by architecture. Active request locale is resolved through one policy using authenticated preference when available, session/cookie/request signals, then deployment fallback. UI translation is distinct from user-entered content.

**Compatibility implications:** Persian remains supported; current Persian behavior stays intact until a dedicated locale migration task changes defaults. Locale selection cannot alter authorization or stored business data.

**Deferred implementation work:** Define `LANGUAGES`, persistence/cookie/session mechanics, translation catalogs, locale switch UI, and public URL locale strategy in later phases.

### ARC-002 — Direction derives from locale

**Context:** `GLO-002` confirms the shared shell is statically RTL.

**Decision:** Direction is locale metadata, with LTR and RTL supported by the shared presentation contract. English is LTR; Arabic and Persian are RTL.

**Compatibility implications:** Persian RTL layout must remain regression-equivalent while direction becomes dynamic.

**Deferred implementation work:** Shell/template/CSS/email changes and component-level bidirectional testing occur in later phases.

### ARC-003 — Gregorian default with calendar adapters

**Context:** `GLO-003` confirms Jalali behavior spans dependencies, server helpers, templates, and frontend code.

**Decision:** Canonical business dates/times are independent from presentation calendar. Gregorian is the global presentation default; Jalali is a supported presentation/input adapter selected by locale/user context.

**Compatibility implications:** Existing stored meaning and Persian/Jalali user behavior must not be silently changed. Booking calculations remain canonical and calendar-neutral.

**Deferred implementation work:** Inventory calendar touchpoints, create format/input boundaries, migrate UI incrementally, and determine whether any persisted non-canonical values exist.

### ARC-004 — Explicit business IANA timezone

**Context:** `GLO-004` confirms `Asia/Tehran` is a global runtime/deployment assumption and no business timezone was confirmed.

**Decision:** Real instants remain timezone-aware; each business/salon ultimately has an explicit IANA timezone. Deployment timezone is a fallback/operational setting. Conversion occurs at business and presentation boundaries.

**Compatibility implications:** Existing appointment meaning must not shift. Legacy records use an explicit compatibility fallback until migrated.

**Deferred implementation work:** Field/schema design, data profiling, timezone migration, schedule/reminder review, and cron/background-job changes.

### ARC-005 — Weekday identity is separate from display order

**Context:** `GLO-005` confirms persisted Saturday=`1` through Friday=`7` semantics.

**Decision:** Target weekday identity is locale-neutral; first-day-of-week is presentation configuration. A future canonical enum/ISO representation may be adopted only through an explicit compatibility mapping and migration.

**Compatibility implications:** Existing stored integers retain their current meaning until migrated; no relabeling or in-place reinterpretation is allowed.

**Deferred implementation work:** Mapping layer, data audit, migration design, schedule/query updates, and regression tests.

### ARC-006 — E.164 canonical phone identity

**Context:** `GLO-006` confirms the current username is an 11-character Iranian local mobile number and OTP helpers apply Iran-specific normalization.

**Decision:** Canonical phone identity is E.164-compatible, country-aware for parsing, globally unique, and provider-independent. Legacy Iranian input remains a compatibility alias during migration.

**Compatibility implications:** Existing accounts must map without identity collisions or accidental merges; login and OTP remain functional through the transition.

**Deferred implementation work:** Schema expansion, normalization service, collision audit, data migration, login compatibility, OTP changes, admin/forms/API updates, and security regression.

### ARC-007 — ISO country and provider-neutral address model

**Context:** `GLO-007` confirms free-form city/zone/address data and no confirmed country hierarchy.

**Decision:** Country is explicit using ISO 3166-1 alpha-2. Address data is separate from GIS coordinates and provider results. Deployment default country is a fallback, not a substitute for business data.

**Compatibility implications:** Existing addresses and GIS data remain valid and must not be bulk-reinterpreted without profiling.

**Deferred implementation work:** Address schema, country field(s), backfill strategy, UI/forms/API contracts, and migration rules.

### ARC-008 — Explicit ISO 4217 currency semantics

**Context:** `GLO-008` confirms monetary columns lack currency while application/gateway logic carries toman/rial semantics.

**Decision:** Money is exact amount plus ISO 4217 currency. No floats. Provider unit conversion is adapter-local. Initial releases use a configured primary currency per deployment/business context and do not require live FX or mixed-currency order settlement.

**Compatibility implications:** Existing toman-semantic values cannot be relabeled as `IRR`; migration must preserve numerical/economic meaning and ledger invariants.

**Deferred implementation work:** Legacy-money inventory, target storage strategy, currency fields/contracts, migration/reconciliation tooling, API/reporting updates, and financial regression.

### ARC-009 — Provider-neutral maps/geospatial capability

**Context:** `GLO-007` also confirms Tehran bounds/defaults and Map.ir/Neshan-specific behavior.

**Decision:** Application geography and GIS are provider-neutral. Map/geocode adapters map provider responses into application contracts. Viewport/defaults are configuration, not geography schema.

**Compatibility implications:** Existing Tehran behavior and provider links remain supported until dedicated changes replace or generalize them.

**Deferred implementation work:** Adapter interfaces, country-aware viewport/search configuration, provider contract tests, and optional additional providers.

### ARC-010 — Communication capabilities separated from providers

**Context:** `GLO-010` and `GLO-011` confirm SMS.ir plus regional messaging integrations, while some channel/provider dispatch boundaries already exist.

**Decision:** OTP, transactional SMS, and messaging are application capabilities with provider adapters, feature flags, and stable delivery-status contracts. Canonical phone normalization occurs before adapter dispatch.

**Compatibility implications:** Existing SMS.ir/Bale/Telegram behavior, security, preferences, statuses, and feature flags remain compatible while supported.

**Deferred implementation work:** Common adapter contracts, provider capability metadata, international provider additions if approved, and migration of hidden phone normalization out of provider code.

### ARC-011 — Payment method, gateway, ledger, and payout rail are separate

**Context:** `GLO-009` confirms Iran-specific online gateways/payout data and a separate Pay at Salon product method.

**Decision:** Product payment method is distinct from gateway provider; currency conversion is adapter-local; provider verification is isolated; wallet/ledger own financial truth; payout rail is country-specific. `pay_in_salon` remains provider-independent.

**Compatibility implications:** Existing state transitions, verification integrity, refunds, wallet/ledger arithmetic, payout safeguards, and Pay at Salon must remain stable.

**Deferred implementation work:** Provider-neutral gateway/payout interfaces, country-aware payout profiles, additional providers if approved, and currency integration after Phase 8.

### ARC-012 — Notification content localized before delivery

**Context:** `GLO-012` confirms Persian/RTL notification/email presentation with delivery services consuming already-rendered title/body content.

**Decision:** Notification intent and localized rendering are separated from channel delivery. Locale is resolved before rendering; delivery adapters receive content and preserve status/preference semantics.

**Compatibility implications:** Existing notification triggers, preferences, retries, statuses, and sender configuration are protected.

**Deferred implementation work:** Message catalog/template strategy, recipient locale resolution, persistence review for rendered versus renderable notification records, and RTL/LTR email templates.

### ARC-013 — Locale-aware search normalization

**Context:** `GLO-013` confirms Persian/Arabic-specific character, digit, and boolean normalization.

**Decision:** Search uses a staged normalization pipeline with universal-safe rules plus locale-specific rules. Geographic search context is separate from text normalization.

**Compatibility implications:** Current Persian equivalence behavior remains covered and must not regress when English/Arabic rules are added.

**Deferred implementation work:** Normalization interfaces, language-aware query parsing/collation, search test matrix, and optional transliteration/synonym work if later required.

### ARC-014 — Shared frontend locale context

**Context:** `GLO-014` confirms frontend locale behavior is centered on custom Jalali/Persian primitives.

**Decision:** Frontend code consumes explicit locale, direction, calendar, timezone/formatting, currency, and week-display context. Standards-based browser `Intl` formatting is preferred where sufficient; Jalali remains behind a focused adapter.

**Compatibility implications:** Existing Persian/Jalali booking/dashboard behavior remains functional during incremental migration.

**Deferred implementation work:** Context transport, frontend formatting utilities, component migration, and browser/RTL regression coverage.

### ARC-015 — Centralized deployment branding

**Context:** `GLO-015` confirms useful brand settings coexist with hard-coded Loomera/Persian fallbacks.

**Decision:** Existing brand/domain/email settings become the nucleus of one deployment-level branding contract that also owns logo, favicon, colors, assets, and SEO identity.

**Compatibility implications:** Loomera defaults remain valid; no unrelated template behavior is changed simply to centralize branding.

**Deferred implementation work:** Asset/color configuration contract, template/metadata consumption, validation/defaults, and buyer documentation.

### ARC-016 — Locale/country-aware Help Center and Lumi corpus

**Context:** `GLO-017` confirms the current production knowledge corpus is explicitly Iran/Persian-oriented.

**Decision:** Support/AI content has explicit locale and applicability metadata with deterministic corpus selection and safe fallback. Country/provider-specific guidance is isolated from global guidance.

**Compatibility implications:** Existing Iran/Persian content and Lumi permissions/actions/guardrails remain supported.

**Deferred implementation work:** Content metadata/schema, English corpus, optional Arabic/Persian variants, retrieval filtering, authoring/review workflow, and content regression tests.

### ARC-017 — Locale-aware SEO and jurisdiction-aware legal metadata

**Context:** `GLO-016` confirms Persian/Loomera metadata defaults and no confirmed multilingual canonical/legal pipeline.

**Decision:** SEO metadata derives from locale plus centralized brand/public URL context. Legal content is explicitly jurisdiction/applicability aware. Canonical/hreflang design follows the approved public locale-routing strategy.

**Compatibility implications:** Existing public URLs and metadata remain valid until deliberately migrated; legal fallback must not imply applicability across jurisdictions.

**Deferred implementation work:** URL strategy, canonical/hreflang rules, localized metadata, legal content inventory/ownership, and country-specific publication process.

### ARC-018 — Portable environment/runtime contract with Liara as an adapter

**Context:** `GLO-018` confirms Liara-specific deployment behavior, Tehran scheduling, and Python `3.12` versus CI `3.13`.

**Decision:** Installability is defined by standard environment/runtime/database/GIS/storage/job/provider contracts. Liara remains one supported deployment implementation.

**Compatibility implications:** Existing Liara safety guards and workflows remain intact until the deployment phase intentionally changes them.

**Deferred implementation work:** Supported Python-version decision, portable setup documentation, standard job scheduler contract, environment reference, and non-Liara deployment validation.

### ARC-019 — Regression contracts govern globalization changes

**Context:** `GLO-019` confirms tests/manifests encode both current market assumptions and important production contracts.

**Decision:** Existing tests are classified and evolved by the task that changes each contract. Globalization adds cross-locale, migration, provider-adapter, financial, scheduling, and installability regression coverage rather than deleting old tests wholesale.

**Compatibility implications:** Current Persian/Iran behavior stays testable until its migration is complete; security/authorization/financial contracts remain mandatory.

**Deferred implementation work:** Build the phase-specific matrix, expand contract tests, add migration rehearsal datasets, and run full release-candidate regression in Phase 19.

## Deferred Decisions

The following decisions are intentionally deferred because current evidence or approved scope does not justify choosing them in Task 0.4:

- public locale URL strategy (URL prefix, domain strategy, or negotiated non-prefixed URLs) and resulting canonical/hreflang design;
- exact database-field layout for country/address data after profiling existing records;
- exact business-timezone field placement and migration defaults after appointment/schedule data analysis;
- whether persisted weekday values should ultimately migrate to ISO integers or a named enum;
- exact phone-schema transition shape (single expanded field versus staged companion field) and collision remediation procedure;
- exact monetary persistence shape (companion currency fields, money value object integration, staged ledger conversion) after financial inventory;
- which international SMS, messaging, payment, payout, map, or geocoding providers, if any, should be added;
- whether any business-level branding overrides are commercially required; initial architecture assumes deployment-level branding;
- exact Help Center/Lumi authoring/CMS workflow;
- legal jurisdiction ownership/content approval process;
- supported Python version that resolves the current CI/runtime difference;
- packaging mechanism such as Docker images; portability is required, Docker itself is not mandated.

Deferred means “requires a later evidence-based decision,” not “safe to improvise during implementation.”

## Non-Goals

Task 0.4 and the target architecture do not require:

- translating the UI now;
- changing `LANGUAGE_CODE` now;
- removing Jalali support;
- adding timezone/country/currency fields now;
- migrating phone numbers or money now;
- full Arabic translation in one task;
- immediate Stripe integration or any mandatory new payment provider;
- a live FX engine;
- simultaneous multi-currency settlement inside one order;
- a new multi-tenant rewrite;
- frontend framework replacement;
- Django rewrite;
- wholesale UI rewrite;
- removal of current regional providers merely because they are regional;
- removal of Pay at Salon;
- speculative microservices;
- Kubernetes or unrelated infrastructure modernization;
- implementation of Phase 1 or any later roadmap phase.

## Completion Definition

The target architecture is considered defined for Phase 0 when:

- every Critical/High audit finding has an explicit architecture response;
- stable decisions exist for locale, directionality, calendar, timezone, weekday, phone/auth, country/address, money/currency, maps, SMS/messaging, payments/payouts, branding, and deployment/installability;
- compatibility requirements protect booking, appointments, authorization, Pay at Salon, financial state, notification semantics, provider security, API contracts, deployment guards, and current Persian/Iran behavior;
- configuration ownership distinguishes deployment defaults, business data, and request/user locale context;
- English-first does not imply removing Persian, and Arabic support is defined as architecture rather than claimed as complete;
- Gregorian default does not reinterpret persisted dates;
- timezone design does not silently shift existing appointments;
- weekday design does not silently renumber stored values;
- E.164 design includes legacy Iranian-account compatibility and collision prevention;
- currency design does not reinterpret legacy toman-semantic values;
- provider neutrality preserves existing adapters until dedicated provider tasks alter them;
- Liara remains supported while portability is defined independently;
- deferred decisions are explicit rather than guessed;
- the roadmap assigns every audit finding to a primary implementation phase;
- no globalization functionality is implemented by this document.
