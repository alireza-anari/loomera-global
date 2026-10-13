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

## Shared Brand Identity Configuration Boundary

Task 2.1 adds a deployment-level brand identity read boundary without changing the existing settings layer or activating branding changes in runtime surfaces.

The supported application import path is:

`loomera.branding.config`

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

Task 2.2 registers the context processor:

`loomera.branding.context_processors.deployment_brand`

The processor exposes exactly three template variables:

- `deployment_brand` — a fresh `DeploymentBrandConfig` snapshot from Task 2.1;
- `deployment_brand_assets` — a fresh `DeploymentBrandAssetConfig` snapshot from Task 2.3;
- `deployment_brand_colors` — a fresh `DeploymentBrandColorConfig` snapshot from Task 2.4.

All three values are produced through their supported accessors. The context processor does not read Django settings or environment variables directly, access the database, inspect request/user/business/salon state, cache values, or infer locale or providers. Identity, assets, and colors remain sibling deployment-level branding contracts, with `loomera/settings/base.py` authoritative for settings validation/defaults.

Task 2.2 wires the safest shared textual identity in the shell/head, Task 2.3 wires shared logo/favicon/manifest/social-image references, and Task 2.4 wires the approved core color tokens and browser metadata through `deployment_brand_colors`. Persian SEO descriptions, `og:locale`, `<html lang>`/direction, translations, and broader SEO-content localization remain unchanged.

This is deployment-level branding only. Tasks 2.2–2.4 do not introduce per-salon or per-business white-label branding and do not make brand identity, assets, or colors drive language, country, currency, timezone, calendar, map/SMS/payment/messaging providers, authentication, authorization, or booking behavior.

## Shared Brand Asset Configuration

Task 2.3 adds a separate immutable deployment asset boundary at:

`loomera.branding.assets`

It defines exactly two public symbols:

- `DeploymentBrandAssetConfig` — a frozen immutable snapshot of the resolved deployment brand asset settings;
- `get_deployment_brand_asset_config()` — constructs a fresh snapshot from `django.conf.settings` on every call.

The snapshot and settings map exactly as follows:

| Django/environment setting | Snapshot field | Loomera compatibility default |
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

Every `*_STATIC_PATH` value is a Django-staticfiles-relative path. Settings import trims the value and rejects an empty path, a leading `/`, backslashes, URL schemes such as `://`, query strings, fragments, Windows absolute-drive paths, and `.` or `..` path segments with `ImproperlyConfigured`. The accessor does not repeat this validation. Social-image width and height must parse as positive integers; zero, negative, or non-integer values fail settings import with `ImproperlyConfigured`.

The supported templates continue resolving asset paths with Django's `{% static %}` tag. A deployment that overrides any path is responsible for packaging the referenced file in its staticfiles inputs. Remote/CDN URLs, `MEDIA_URL` assets, database uploads, and per-salon asset routing are not part of this contract.

`BRAND_WEBMANIFEST_STATIC_PATH` may point to a deployment-supplied static manifest. The repository's default `static/branding/favicon/site.webmanifest` remains unchanged and is not generated dynamically. A buyer providing a custom manifest owns its `name`, `short_name`, icon references, description, and theme/background colors.

The default Loomera files, Open Graph social-image size (`1254 × 1254`), `og:locale=fa_IR`, and Persian SEO descriptions remain unchanged. Task 2.4 owns the separate color contract described below; asset selection still does not infer or alter locale, country, currency, timezone, calendar, providers, authentication, authorization, or booking semantics.

## Shared Brand Color Configuration

Task 2.4 adds a third sibling branding boundary at `loomera.branding.colors`. The module exposes exactly two public symbols: `DeploymentBrandColorConfig`, a frozen slots-based immutable snapshot, and `get_deployment_brand_color_config()`, which returns a fresh snapshot from the eleven validated Django settings on every call. Validation and compatibility defaults remain owned by `loomera/settings/base.py`; the accessor does not read environment variables directly, duplicate validation/default logic, cache results, or inspect request/database/business/salon state.

The setting/environment names, snapshot fields, and exact Loomera compatibility defaults are:

| Django/environment setting | Snapshot field | Compatibility default |
| --- | --- | --- |
| `BRAND_PRIMARY_COLOR` | `primary_color` | `#735CBE` |
| `BRAND_PRIMARY_HOVER_COLOR` | `primary_hover_color` | `#886FD6` |
| `BRAND_PRIMARY_ACTIVE_COLOR` | `primary_active_color` | `#57526E` |
| `BRAND_PRIMARY_SOFT_COLOR` | `primary_soft_color` | `#EEE8FA` |
| `BRAND_SECONDARY_COLOR` | `secondary_color` | `#9B80E0` |
| `BRAND_ACCENT_COLOR` | `accent_color` | `#A7C8A1` |
| `BRAND_BACKGROUND_COLOR` | `background_color` | `#FCFBFE` |
| `BRAND_SURFACE_COLOR` | `surface_color` | `#FFFFFF` |
| `BRAND_TEXT_PRIMARY_COLOR` | `text_primary_color` | `#2E2A3C` |
| `BRAND_TEXT_ON_PRIMARY_COLOR` | `text_on_primary_color` | `#FFFFFF` |
| `BRAND_BROWSER_THEME_DARK_COLOR` | `browser_theme_dark_color` | `#16131F` |

Every value must be a CSS hexadecimal RGB color in exact `#RRGGBB` form. Settings import trims surrounding whitespace, normalizes hexadecimal letters to uppercase, and rejects empty values, `#RGB` shorthand, alpha forms such as `#RRGGBBAA`, `rgb()`/`hsl()`, named colors, CSS variables, URLs, semicolons/newlines, and arbitrary CSS. Invalid explicit values raise `ImproperlyConfigured`. Hover, active, and soft values are explicit compatibility defaults; they are not mathematically derived from the primary color.

`DeploymentBrandColorConfig` has exactly the eleven fields above. Its `primary_rgb`, `primary_hover_rgb`, `primary_active_rgb`, `primary_soft_rgb`, `secondary_rgb`, `accent_rgb`, `background_rgb`, `surface_rgb`, `text_primary_rgb`, and `text_on_primary_rgb` properties derive CSS-ready decimal triplets such as `115 92 190`. These helpers are derived values, not additional deployment settings.

The shared template context exposes the snapshot as `deployment_brand_colors`. In `templates/base.html`, the `deployment-brand-color-tokens` inline bridge layers over the existing application stylesheets and maps the configured values to the supported semantic variables: `--lm-primary`, `--lm-primary-hover`, `--lm-primary-active`, `--lm-primary-soft`, `--lm-secondary`, `--lm-accent`, `--lm-bg`, `--lm-app-surface`, `--lm-dashboard-surface`, `--lm-surface`, `--lm-card-surface`, `--lm-surface-raised`, `--lm-surface-elevated`, `--lm-sheet-surface`, `--lm-dashboard-panel`, `--lm-text-primary`, and `--lm-text-on-primary`. The corresponding `--lm-*-rgb` bridge variables use the derived RGB helpers. `--lm-border-selected` and `--lm-info` alias the configured primary color, while `--lm-info-soft`, `--lm-selection`, and `--lm-selected` alias the configured primary-soft color. Template output does not use `|safe`; strict settings validation is the injection boundary.

Browser metadata uses the same color contract: the light `theme-color` follows `BRAND_BACKGROUND_COLOR`, the dark `theme-color` follows `BRAND_BROWSER_THEME_DARK_COLOR`, and both `msapplication-TileColor` and the Safari mask-icon color follow `BRAND_PRIMARY_COLOR`. `BRAND_BROWSER_THEME_DARK_COLOR` is metadata-only in Task 2.4 and does not configure the application dark palette.

`static/css/loomera-brand.css` and `static/css/loomera-palette-override.css` remain unchanged compatibility foundations; Task 2.4 layers the runtime bridge over them instead of rewriting CSS files. Full dark-palette configurability and cleanup of historical hard-coded hex/rgba literals are deliberately deferred. The default `static/branding/favicon/site.webmanifest` also remains unchanged. A buyer that needs manifest `theme_color` or `background_color` to follow an alternate palette must provide a custom static manifest and configure `BRAND_WEBMANIFEST_STATIC_PATH`, retaining the buyer-owned manifest responsibility established in Task 2.3.

Brand colors remain deployment-level only: there is no per-salon color configuration and no locale, country, currency, timezone, calendar, provider, authentication, authorization, or booking inference.

## Compatibility Behavior

Tasks 1.1, 1.2, and 1.3 intentionally preserve the current runtime behavior:

- the current Persian runtime remains unchanged, including `LANGUAGE_CODE = "fa"`;
- the current Tehran Django timezone remains unchanged, including `TIME_ZONE = "Asia/Tehran"`;
- current Jalali rendering, parsing, datepicker, and scheduling behavior remains unchanged;
- current monetary values retain their legacy toman semantics;
- the empty `LOOMERA_DEFAULT_CURRENCY` compatibility default is intentional because assigning `IRR` before the Phase 8 money migration would give existing toman-semantic values incorrect financial meaning;
- configuring or reading any of the six deployment values does not migrate or activate application behavior;
- current map, SMS, messaging, and payment selector/feature-flag behavior remains unchanged, including the existing `mapir`, `disabled`, `zibal`, and empty messaging-provider compatibility baseline.

In particular, a deployment may configure a future-facing default such as `LOOMERA_DEFAULT_LANGUAGE=en`, `LOOMERA_DEFAULT_TIMEZONE=UTC`, or `LOOMERA_DEFAULT_CALENDAR=gregorian`. Task 1.1 validates that configuration and Task 1.2 can expose it through a snapshot, but the current Django/application runtime continues to use its existing Persian, Tehran, and Jalali behavior until the owning later phase deliberately wires the contract in. Task 2.4 preserves the current Loomera core light palette under its exact defaults while allowing deployment-level alternate colors through the semantic-token bridge and approved browser metadata only.

## Future Ownership

Language and enabled-language runtime behavior belongs to **Phase 3**. Calendar and business/deployment timezone migration belongs to **Phase 5**. Explicit currency semantics and legacy toman reconciliation belongs to **Phase 8**. Country/address data and country-aware geography behavior belongs to **Phase 9**. Provider-neutral map routing belongs to **Phase 9**, SMS/messaging provider globalization to **Phase 14**, and payment/payout provider globalization to **Phase 15**.

Later phases must preserve the architecture separation between deployment defaults, provider selection, business facts, and request/user presentation context. They must also perform any required data profiling, migration, and regression work before changing persisted meaning or provider behavior.

## Non-Goals

Tasks 1.1, 1.2, and 1.3 do not implement globalization runtime behavior. They do not switch the UI to English, enable Arabic runtime behavior, modify Django `LANGUAGES`, modify `LANGUAGE_CODE`, modify `TIME_ZONE`, activate Gregorian presentation, change Jalali behavior, introduce business timezone or country fields, migrate phone identity, alter weekday semantics, reinterpret money, add currency fields, add/replace/enable/disable map/payment/SMS/messaging providers, change existing provider selectors or feature flags, add an environment-backed `MAP_PROVIDER` setting, add dependencies, add migrations, or implement business/request/provider routing. Task 1.3 does not start Phase 2.

Task 2.1 establishes the shared brand identity read boundary. Task 2.2 wires that boundary into shared textual shell/head identity. Task 2.3 adds only deployment-configurable staticfiles-relative logo/favicon/manifest/social-image paths and social-image dimensions. Task 2.4 adds only the validated eleven-color deployment contract, approved browser metadata wiring, and the runtime semantic-token bridge. It does not redesign the palette, configure typography, change asset paths or images, rewrite `static/**`, generate or modify `site.webmanifest`, configure the complete dark-mode palette, clean up every legacy color literal, localize SEO, change language/direction, add models/migrations/dependencies, change providers/authentication/authorization/booking semantics, introduce per-salon branding, start Task 2.5, or start Phase 3.

## Machine-Readable Brand Identity Wiring

Task 2.5 adds exactly two non-template runtime consumers of the existing `loomera.branding.config` identity boundary. `ApiV1MetaView` takes one fresh `DeploymentBrandConfig` snapshot per metadata request and maps `application.name` to `display_name` and `application.brand` to `name`. All other API metadata fields and the health endpoint keep their existing behavior.

`build_service_schema()` takes one fresh snapshot per service schema build and maps only `provider.name` to `display_name`. The service schema type, name, description, URL, optional image behavior, salon schema, breadcrumb schema, Persian address-region text, `addressCountry="IR"`, and public URL handling remain unchanged.

The approved Python runtime consumers of `get_deployment_brand_config()` are `apps/api/v1/views.py`, `apps/main/seo.py`, `loomera/branding/context_processors.py`, and, from Task 2.7, `apps/notifications/delivery.py` and `apps/orders/notification_delivery.py`. Task 2.5 adds no brand settings, fields, aliases, validation, caching, business/salon resolution, or environment reads. Brand identity remains deployment-level and does not infer or alter locale, country, currency, timezone, calendar, providers, authentication, authorization, or booking behavior.

Task 2.7 resolves each email sender from one fresh deployment brand snapshot's `default_from_email` at the existing sender-resolution point. `DEFAULT_FROM_EMAIL` remains owned by the settings layer; sender trimming, missing-email and empty-sender handling, opt-outs, attempts/retries, metadata, and masked logging retain their existing behavior. SMS and messaging paths do not use this branding accessor. No new setting or per-salon branding is introduced.

## Article Publisher Brand Identity

Task 2.8 makes `apps/articles/views.py` an explicitly approved brand-boundary runtime consumer. The Article JSON-LD publisher organization name uses `DeploymentBrandConfig.display_name` from one fresh snapshot; the default remains Loomera, with `BRAND_DISPLAY_NAME` still owned by the existing deployment setting and brand boundary. No new setting or environment variable is added. Branding remains deployment-level only, with no per-article, per-author, per-salon, or per-locale publisher branding. Persian magazine strings, Article author metadata, URLs, breadcrumbs, content, and locale behavior remain unchanged. Broader locale-aware SEO remains Phase 16.

## Shared Shell Brand Literal Cleanup

Task 2.6 reuses the existing centralized `deployment_brand` template context in the shared loader splash and dashboard sidebar. The loader splash title and logo alt text, plus the sidebar navigation brand label and both shared logo alt values, resolve from `deployment_brand.display_name`; the current compatibility configuration therefore continues to render Loomera by default.

Task 2.6 introduces no new brand setting or branding boundary. CSS class names such as `loomera-*` remain implementation identifiers and are deliberately unchanged. Locale, direction, and translation behavior remain deferred to Phase 3. Branding remains deployment-level only; this task does not introduce per-salon or per-tenant white-labeling.
