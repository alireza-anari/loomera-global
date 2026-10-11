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

The supported application import path is `loomera.globalization.config`.

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

The supported application import path is `loomera.globalization.providers`.

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

## Shared Brand Identity Configuration Boundary

Task 2.1 adds a deployment-level brand identity read boundary without changing the existing settings layer or activating branding changes in runtime surfaces.

The supported application import path is `loomera.branding.config`.

It defines exactly two public symbols:

- `DeploymentBrandConfig` — a frozen immutable snapshot of deployment brand identity settings;
- `get_deployment_brand_config()` — constructs a fresh snapshot from `django.conf.settings` on each call.

The snapshot exposes exactly these fields:

| Field | Existing Django setting | Loomera compatibility value |
| --- | --- | --- |
| `name` | `BRAND_NAME` | `"Loomera"` |
| `display_name` | `BRAND_DISPLAY_NAME` | `"Loomera"` |
| `domain` | `BRAND_DOMAIN` | `"loomera.local"` |
| `public_base_url` | `PUBLIC_BASE_URL` | `""` |
| `site_url` | `SITE_URL` | `""` |
| `email_sender_name` | `LOOMERA_EMAIL_SENDER_NAME` | `"Loomera"` |
| `default_from_email` | `DEFAULT_FROM_EMAIL` | `"Loomera <no-reply@loomera.local>"` |
| `support_email` | `LOOMERA_SUPPORT_EMAIL` | `"support@loomera.local"` |
| `partner_email` | `LOOMERA_PARTNER_EMAIL` | `"partners@loomera.local"` |
| `marketing_email` | `LOOMERA_MARKETING_EMAIL` | `"hello@loomera.local"` |

Task 2.1 introduces no new environment variable, alias, fallback, or validation rule. `loomera/settings/base.py` remains authoritative for all ten values. The accessor reads only those already-resolved Django settings, performs no caching, database/request/user/business access, and does not duplicate settings logic.

Task 2.2 makes this Task 2.1 snapshot available to Django templates through the shared template context described below. Configuration ownership remains in `loomera.branding.config`; Task 2.2 does not add brand settings, defaults, validation, or per-salon branding.

Brand identity is independent of locale, country, currency, timezone, calendar, and provider selection. Changing the deployment brand name must not alter authentication, authorization, booking semantics, geography, money meaning, or provider routing. Task 2.1 does not introduce per-salon or per-business white-label branding.

## Shared Brand Template Context

Task 2.2 registers the context processor `loomera.branding.context_processors.deployment_brand` and exposes `deployment_brand`, a fresh `DeploymentBrandConfig` snapshot. Task 2.3 keeps the same registered processor and additionally exposes `deployment_brand_assets`, a fresh `DeploymentBrandAssetConfig` snapshot. Both values are created through their supported accessors; the processor does not read settings or environment variables directly, access the database, inspect request/user/business/salon state, cache values, or infer locale or providers.

Task 2.2 wires the safest shared textual identity in the shell/head: the default document title, Open Graph title, Twitter title, application name, Apple mobile web app title, and Open Graph site name consume `deployment_brand.display_name`. Task 2.3 wires the shared logo/favicon/manifest/social-image paths and social-image dimensions through `deployment_brand_assets` while retaining the exact Loomera compatibility defaults.

Persian SEO descriptions, `og:locale`, `<html lang>`/direction, translations, broader SEO-content localization, and brand-color configuration remain deferred to their owning tasks/phases. Branding remains deployment-level only; neither context value drives language, country, currency, timezone, calendar, providers, authentication, authorization, or booking behavior.

## Shared Brand Asset Configuration

Task 2.3 adds a sibling asset boundary at `loomera.branding.assets`. It intentionally does not expand the ten-field `DeploymentBrandConfig` identity/email/domain contract.

The module exposes exactly two public symbols:

- `DeploymentBrandAssetConfig` — a frozen immutable deployment asset snapshot;
- `get_deployment_brand_asset_config()` — returns a fresh snapshot from the fifteen validated Django settings on every call.

The asset settings, snapshot fields, and Loomera compatibility defaults are:

| Setting / environment variable | Snapshot field | Compatibility default |
| --- | --- | --- |
| `BRAND_LOGO_GLYPH_STATIC_PATH` | `logo_glyph_path` | `branding/logo/loomera-glyph-mark.png` |
| `BRAND_APP_ICON_STATIC_PATH` | `app_icon_path` | `branding/logo/loomera-app-icon.png` |
| `BRAND_LOGO_HEADER_STATIC_PATH` | `logo_header_path` | `branding/logo/loomera-logo-header.png` |
| `BRAND_LOGO_PRIMARY_STATIC_PATH` | `logo_primary_path` | `branding/logo/loomera-logo-primary.png` |
| `BRAND_FAVICON_SVG_STATIC_PATH` | `favicon_svg_path` | `branding/favicon/favicon.svg` |
| `BRAND_FAVICON_ICO_STATIC_PATH` | `favicon_ico_path` | `branding/favicon/favicon.ico` |
| `BRAND_FAVICON_16_STATIC_PATH` | `favicon_16_path` | `branding/favicon/favicon-16x16.png` |
| `BRAND_FAVICON_32_STATIC_PATH` | `favicon_32_path` | `branding/favicon/favicon-32x32.png` |
| `BRAND_FAVICON_48_STATIC_PATH` | `favicon_48_path` | `branding/favicon/favicon-48x48.png` |
| `BRAND_APPLE_TOUCH_ICON_STATIC_PATH` | `apple_touch_icon_path` | `branding/favicon/apple-touch-icon.png` |
| `BRAND_MASK_ICON_STATIC_PATH` | `mask_icon_path` | `branding/favicon/safari-pinned-tab.svg` |
| `BRAND_WEBMANIFEST_STATIC_PATH` | `webmanifest_path` | `branding/favicon/site.webmanifest` |
| `BRAND_SOCIAL_IMAGE_STATIC_PATH` | `social_image_path` | `branding/logo/loomera-logo-square.png` |
| `BRAND_SOCIAL_IMAGE_WIDTH` | `social_image_width` | `1254` |
| `BRAND_SOCIAL_IMAGE_HEIGHT` | `social_image_height` | `1254` |

Every `*_STATIC_PATH` is a Django-staticfiles-relative path. Values are trimmed and must remain non-empty, relative, forward-slash paths. Absolute paths, URL schemes, backslashes, query strings, fragments, and `.` or `..` path segments are rejected with `ImproperlyConfigured`; invalid absolute/URL input is never converted into a relative path. These settings are not filesystem paths, remote/CDN URLs, `MEDIA_URL` references, or database-uploaded assets.

`BRAND_SOCIAL_IMAGE_WIDTH` and `BRAND_SOCIAL_IMAGE_HEIGHT` must be positive integers. Zero, negative, non-integer, or otherwise invalid explicit values raise `ImproperlyConfigured`. The default remains `1254 × 1254`, preserving the existing Open Graph output.

Templates continue to resolve all configured paths through Django's `{% static %}` tag. A buyer selecting alternate paths is responsible for packaging those referenced files where Django staticfiles can discover them; Task 2.3 does not verify synthetic alternate files exist and does not add replacement assets.

The default `static/branding/favicon/site.webmanifest` remains unchanged. A buyer can set `BRAND_WEBMANIFEST_STATIC_PATH` to a deployment-supplied static manifest. That buyer-owned manifest is responsible for its `name`, `short_name`, icon references, description, theme color, and background color. Task 2.3 does not dynamically generate a manifest.

All existing Loomera static files remain unchanged. The current colors `#FCFBFE`, `#16131F`, and `#735CBE` remain compatibility literals; no color setting is introduced by Task 2.3. Color/design-token configuration is deferred to a later Phase 2 task. SEO localization remains deferred, including localized descriptions and locale-aware metadata. There is no per-salon or per-business white-label asset layer.

Asset selection is presentation configuration only. It does not infer or change `LANGUAGE_CODE`, `LOOMERA_DEFAULT_LANGUAGE`, country, currency, timezone, calendar, map/SMS/payment/messaging providers, authentication, authorization, or booking semantics.

## Compatibility Behavior

Tasks 1.1, 1.2, and 1.3 intentionally preserve the current runtime behavior:

- the current Persian runtime remains unchanged, including `LANGUAGE_CODE = "fa"`;
- the current Tehran Django timezone remains unchanged, including `TIME_ZONE = "Asia/Tehran"`;
- current Jalali rendering, parsing, datepicker, and scheduling behavior remains unchanged;
- current monetary values retain their legacy toman semantics;
- the empty `LOOMERA_DEFAULT_CURRENCY` compatibility default is intentional because assigning `IRR` before the Phase 8 money migration would give existing toman-semantic values incorrect financial meaning;
- configuring or reading any of the six deployment values does not migrate or activate application behavior;
- current map, SMS, messaging, and payment selector/feature-flag behavior remains unchanged, including the existing `mapir`, `disabled`, `zibal`, and empty messaging-provider compatibility baseline.

Task 2.3 likewise preserves the current Loomera visual asset URLs under defaults, leaves all static files and colors unchanged, and does not alter locale/provider/authentication/booking behavior.

## Future Ownership

Language and enabled-language runtime behavior belongs to **Phase 3**. Calendar and business/deployment timezone migration belongs to **Phase 5**. Explicit currency semantics and legacy toman reconciliation belongs to **Phase 8**. Country/address data and country-aware geography behavior belongs to **Phase 9**. Provider-neutral map routing belongs to **Phase 9**, SMS/messaging provider globalization to **Phase 14**, and payment/payout provider globalization to **Phase 15**.

Later phases must preserve the architecture separation between deployment defaults, provider selection, business facts, request/user presentation context, and deployment branding. They must also perform any required data profiling, migration, and regression work before changing persisted meaning or provider behavior.

## Non-Goals

Tasks 1.1, 1.2, and 1.3 do not implement globalization runtime behavior. They do not switch the UI to English, enable Arabic runtime behavior, modify Django `LANGUAGES`, modify `LANGUAGE_CODE`, modify `TIME_ZONE`, activate Gregorian presentation, change Jalali behavior, introduce business timezone or country fields, migrate phone identity, alter weekday semantics, reinterpret money, add currency fields, add/replace/enable/disable map/payment/SMS/messaging providers, change existing provider selectors or feature flags, add dependencies, add migrations, or implement business/request/provider routing.

Tasks 2.1 and 2.2 establish the shared brand identity boundary and textual template context. Task 2.3 configures only the approved shared static asset paths and social-image dimensions. It does not replace any static asset, change brand colors/CSS, redesign logo markup, dynamically generate a manifest, support database-uploaded or remote/CDN assets, localize SEO metadata, change `og:locale` or Persian descriptions, modify locale/model/email/calendar/user-agent/provider/auth/booking behavior, add migrations/dependencies, introduce per-salon branding, or start Task 2.4 or Phase 3.
