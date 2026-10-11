# Loomera Global Configuration Contracts

## Purpose

Phase 1 establishes explicit globalization configuration contracts before later phases migrate application behavior. Task 1.1 adds validated deployment defaults for language, country, currency, timezone, and calendar context while preserving the current Persian/Iran runtime exactly. Task 1.2 adds one shared typed, immutable application access boundary for those already-validated deployment settings. Task 1.3 adds a separate typed, immutable read boundary for the current effective deployment provider selectors without changing provider configuration or runtime behavior.

The six globalization settings remain deployment contracts for future owning phases. They are read and validated during settings import in `loomera/settings/base.py`. The Task 1.2 boundary reads those validated Django settings. The Task 1.3 provider boundary reads the already-resolved provider settings plus the existing application-level map compatibility fallback. No application feature consumes either boundary yet, so these snapshots do not activate locale, timezone, calendar, money, country, map, SMS, messaging, payment, model, or persisted-data behavior.

## Configuration Scope

Loomera Global separates configuration into three scopes:

- **Deployment defaults** are installation defaults and capability constraints. Task 1.1 defines the six validated globalization defaults, Task 1.2 exposes those defaults through a shared read boundary, and Task 1.3 exposes existing provider selectors through a separate read boundary. Task 1.3 does not add or redefine any provider setting.
- **Future business/salon data** represents facts that can differ by business, such as business country, business timezone, or an explicitly modeled primary currency. Those values must be introduced by their owning later phases and are not inferred from deployment defaults or provider selection.
- **Request/user presentation context** controls presentation for a request or user, such as active language, direction, calendar representation, and formatting. Tasks 1.2 and 1.3 do not create or change request/user locale behavior.

Deployment defaults are therefore fallbacks/contracts, not substitutes for future business data and not active presentation preferences. Deployment/business/request precedence remains an architectural concept until the owning later phases implement those additional scopes.

## Deployment Globalization Defaults

| Setting | Environment variable | Compatibility default | Validation | Read by shared boundary? | Drives application runtime behavior? | Owning future phase |
| --- | --- | --- | --- | --- | --- | --- |
| `LOOMERA_DEFAULT_LANGUAGE` | `LOOMERA_DEFAULT_LANGUAGE` | `fa` | Trimmed and normalized to lowercase; must be non-empty and present in `LOOMERA_ENABLED_LANGUAGES`. | Yes. | No. It does not replace Django `LANGUAGE_CODE`. | Phase 3 |
| `LOOMERA_ENABLED_LANGUAGES` | `LOOMERA_ENABLED_LANGUAGES` | `fa` | Comma-separated non-empty list; values are trimmed and normalized to lowercase; empty entries and duplicates after normalization are rejected. | Yes. Exposed as an immutable tuple. | No. It does not replace Django `LANGUAGES`. | Phase 3 |
| `LOOMERA_DEFAULT_COUNTRY` | `LOOMERA_DEFAULT_COUNTRY` | `IR` | Exactly two ASCII letters; normalized to uppercase. This is ISO 3166-1 alpha-2-shaped deployment context. | Yes. | No. No country model/data behavior is changed. | Phase 9 |
| `LOOMERA_DEFAULT_CURRENCY` | `LOOMERA_DEFAULT_CURRENCY` | empty | Empty is allowed. When configured, exactly three ASCII letters are required and normalized to uppercase. Shape validation does not prove official ISO 4217 allocation. | Yes. The empty string remains empty. | No. It does not label, convert, format, or reinterpret stored money. | Phase 8 |
| `LOOMERA_DEFAULT_TIMEZONE` | `LOOMERA_DEFAULT_TIMEZONE` | `Asia/Tehran` | Must be non-empty and resolve through Python `zoneinfo` as an IANA timezone identifier. | Yes. | No. It does not replace Django `TIME_ZONE` or appointment semantics. | Phase 5 |
| `LOOMERA_DEFAULT_CALENDAR` | `LOOMERA_DEFAULT_CALENDAR` | `jalali` | Trimmed and normalized to lowercase; only `gregorian` and `jalali` are accepted. | Yes. | No. It does not change date rendering or datepicker behavior. | Phase 5 |

`LOOMERA_ENABLED_LANGUAGES` is represented in the environment as a comma-separated value, for example `fa,en`. The setting value exposed by Django settings is the validated normalized list. The shared boundary exposes that list as a tuple so callers cannot mutate deployment configuration through the snapshot.

## Shared Deployment Configuration Boundary

The supported application import path is:

`loomera.globalization.config`

It defines exactly two public symbols:

- `DeploymentGlobalizationConfig` — an immutable deployment snapshot value object;
- `get_deployment_globalization_config()` — constructs a fresh snapshot from `django.conf.settings` on each call.

The snapshot exposes exactly these fields:

| Field | Compatibility value |
| --- | --- |
| `default_language` | `"fa"` |
| `enabled_languages` | `("fa",)` |
| `default_country` | `"IR"` |
| `default_currency` | `""` |
| `default_timezone` | `"Asia/Tehran"` |
| `default_calendar` | `"jalali"` |

The accessor reads only the six validated Task 1.1 `LOOMERA_*` Django settings. It does not read environment variables directly, import `loomera.settings.base`, duplicate validation, cache snapshots, access the database, inspect a request/user, resolve business/salon overrides, or select providers. Settings validation remains owned by `loomera/settings/base.py`.

Later globalization code should prefer this boundary over direct reads of these six `LOOMERA_*` settings. Future owning phases will become consumers one at a time. Task 1.2 itself does not wire the boundary into middleware, context processors, views, forms, models, templates, APIs, authentication, booking, calendar/timezone utilities, money, payments, maps, SMS/messaging, notifications, jobs, branding, or SEO.

The architecture still distinguishes deployment configuration, future business/salon facts, and future request/user presentation context. Their precedence remains conceptual and unimplemented in Task 1.2. Provider selection remains outside this six-field globalization boundary; Task 1.3 exposes it through a separate boundary.

## Shared Provider Configuration Boundary

The supported application import path is:

`loomera.globalization.providers`

It defines exactly two public symbols:

- `DeploymentProviderConfig` — an immutable snapshot of the current effective deployment provider selectors;
- `get_deployment_provider_config()` — constructs a fresh snapshot from `django.conf.settings` on each call.

The snapshot exposes exactly these fields and compatibility values:

| Field | Compatibility value | Source |
| --- | --- | --- |
| `map_provider` | `"mapir"` | Existing application compatibility fallback when `MAP_PROVIDER` is absent or empty. Task 1.3 does **not** add `MAP_PROVIDER` to `loomera/settings/base.py` and does not make that environment variable newly active. |
| `sms_provider` | `"disabled"` | Existing resolved Django `SMS_PROVIDER` setting. |
| `payment_provider` | `"zibal"` | Existing resolved Django `PAYMENT_PROVIDER` setting. `PAYMENT_MODE` is not part of the snapshot and is unchanged. |
| `messaging_allowed_providers` | `()` | Existing resolved Django `MESSAGING_ALLOWED_PROVIDERS`, copied into an immutable tuple. |

The map selector preserves the same application compatibility rule already used by current map code: `(getattr(settings, "MAP_PROVIDER", "mapir") or "mapir").strip().lower()`. The other three values come from the already-resolved Django settings. The accessor does not read environment variables, use `django-environ`, import `loomera.settings.base`, access the database, inspect a request/user/business, cache results, or read provider credentials, API URLs, secrets, or feature flags.

Settings import remains authoritative for existing SMS, payment, and messaging behavior. In particular, Task 1.3 does not modify `SMS_PROVIDER`, `PAYMENT_PROVIDER`, `PAYMENT_MODE`, `MESSAGING_ALLOWED_PROVIDERS`, `BALE_BOT_ENABLED`, `TELEGRAM_BOT_ENABLED`, `MESSAGING_ENABLED`, or the existing settings-import mutation that can append enabled Bale/Telegram providers. The snapshot simply copies the final resolved `MESSAGING_ALLOWED_PROVIDERS` value into a tuple.

Provider selection is not country, currency, phone, timezone, calendar, or business-geography data. A value such as `payment_provider == "zibal"` does not imply `IRR` or `IR`; an SMS provider does not define phone country; a map provider does not define timezone or business geography; and no provider value determines calendar or language. These concerns remain owned by their explicit globalization contracts and later data migrations.

No application feature consumes the provider boundary in Task 1.3. Existing map helpers, payment gateway code, SMS code, messaging dispatch, Bale/Telegram apps, views, models, middleware, context processors, and jobs continue to read/use their current contracts. Actual provider-neutral adapter/routing globalization belongs to **Phase 9** for maps, **Phase 14** for SMS/messaging, and **Phase 15** for payments/payouts. Task 1.3 does not claim that any international provider is implemented.

## Compatibility Behavior

Tasks 1.1, 1.2, and 1.3 intentionally preserve the current runtime behavior:

- the current Persian runtime remains unchanged, including `LANGUAGE_CODE = "fa"`;
- the current Tehran Django timezone remains unchanged, including `TIME_ZONE = "Asia/Tehran"`;
- current Jalali rendering, parsing, datepicker, and scheduling behavior remains unchanged;
- current monetary values retain their legacy toman semantics;
- the empty `LOOMERA_DEFAULT_CURRENCY` compatibility default is intentional because assigning `IRR` before the Phase 8 money migration would give existing toman-semantic values incorrect financial meaning;
- configuring or reading any of the six deployment values does not migrate or activate application behavior;
- current map, SMS, messaging, and payment selector/feature-flag behavior remains unchanged, including the existing `mapir`, `disabled`, `zibal`, and empty messaging-provider compatibility baseline.

In particular, a deployment may configure a future-facing default such as `LOOMERA_DEFAULT_LANGUAGE=en`, `LOOMERA_DEFAULT_TIMEZONE=UTC`, or `LOOMERA_DEFAULT_CALENDAR=gregorian`. Task 1.1 validates that configuration and Task 1.2 can expose it through a snapshot, but the current Django/application runtime continues to use its existing Persian, Tehran, and Jalali behavior until the owning later phase deliberately wires the contract in.

## Future Ownership

Language and enabled-language runtime behavior belongs to **Phase 3**. Calendar and business/deployment timezone migration belongs to **Phase 5**. Explicit currency semantics and legacy toman reconciliation belongs to **Phase 8**. Country/address data and country-aware geography behavior belongs to **Phase 9**. Provider-neutral map routing belongs to **Phase 9**, SMS/messaging provider globalization to **Phase 14**, and payment/payout provider globalization to **Phase 15**.

Later phases must preserve the architecture separation between deployment defaults, provider selection, business facts, and request/user presentation context. They must also perform any required data profiling, migration, and regression work before changing persisted meaning or provider behavior.

## Non-Goals

Tasks 1.1, 1.2, and 1.3 do not implement globalization runtime behavior. They do not switch the UI to English, enable Arabic runtime behavior, modify Django `LANGUAGES`, modify `LANGUAGE_CODE`, modify `TIME_ZONE`, activate Gregorian presentation, change Jalali behavior, introduce business timezone or country fields, migrate phone identity, alter weekday semantics, reinterpret money, add currency fields, add/replace/enable/disable map/payment/SMS/messaging providers, change existing provider selectors or feature flags, add an environment-backed `MAP_PROVIDER` setting, add dependencies, add migrations, or implement business/request/provider routing. Task 1.3 does not start Phase 2.
