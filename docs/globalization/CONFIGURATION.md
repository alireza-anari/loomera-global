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

Task 2.1 adds a deployment-level brand identity read boundary without changing the existing settings layer or activating branding changes in runtime surfaces. Task 2.11 extends that same snapshot with the two already-existing deployment calendar brand-metadata settings without wiring a calendar runtime consumer.

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
| `calendar_prodid` | `LOOMERA_CALENDAR_PRODID` | `"-//Loomera//Appointment//FA"` |
| `calendar_name` | `LOOMERA_CALENDAR_NAME` | `"Loomera Appointment"` |
| `display_name_fa` | `BRAND_DISPLAY_NAME_FA` | `"لومرا"` |

Task 2.1 introduced no new environment variable, alias, fallback, or validation rule for the original ten identity values. Task 2.11 likewise introduced no new environment variable or Django setting for the original twelve fields, including independently configurable `LOOMERA_CALENDAR_PRODID` and `LOOMERA_CALENDAR_NAME`. The subsequent homepage Persian-display migration adds exactly one independent setting, `BRAND_DISPLAY_NAME_FA`, for a total of thirteen resolved snapshot fields. `loomera/settings/base.py` remains authoritative for defaults and normalization. The accessor reads only those resolved Django settings, performs no caching, database/request/user/business access, and does not duplicate settings logic.

Task 2.2 makes this snapshot available to Django templates through the shared template context described below. Configuration ownership remains in `loomera.branding.config`; Task 2.11 does not add a context processor, defaults, validation, or per-salon branding.

Brand identity and brand metadata remain independent of locale, country, currency, timezone, calendar presentation semantics, and provider selection. Changing deployment calendar metadata does not alter authentication, authorization, booking semantics, timezone behavior, Gregorian/Jalali presentation, geography, money meaning, or provider routing. Task 2.11 does not introduce per-salon or per-business white-label branding.

## Shared Brand Template Context

Task 2.2 registers the context processor:

`loomera.branding.context_processors.deployment_brand`

The processor exposes exactly three template variables:

- `deployment_brand` — a fresh `DeploymentBrandConfig` snapshot from Task 2.1, extended by Task 2.11;
- `deployment_brand_assets` — a fresh `DeploymentBrandAssetConfig` snapshot from Task 2.3;
- `deployment_brand_colors` — a fresh `DeploymentBrandColorConfig` snapshot from Task 2.4.

All three values are produced through their supported accessors. The context processor does not read Django settings or environment variables directly, access the database, inspect request/user/business/salon state, cache values, or infer locale or providers. Identity, metadata, assets, and colors remain deployment-level branding contracts, with `loomera/settings/base.py` authoritative for settings validation/defaults.

Task 2.2 wires the safest shared textual identity in the shell/head, Task 2.3 wires shared logo/favicon/manifest/social-image references, and Task 2.4 wires the approved core color tokens and browser metadata through `deployment_brand_colors`. Persian SEO descriptions, `og:locale`, `<html lang>`/direction, translations, and broader SEO-content localization remain unchanged.

This is deployment-level branding only. Tasks 2.2–2.4 and Task 2.11 do not introduce per-salon or per-business white-label branding and do not make brand identity, calendar metadata, assets, or colors drive language, country, currency, timezone, calendar presentation, map/SMS/payment/messaging providers, authentication, authorization, or booking behavior.

## Shared Brand Asset Configuration

Task 2.3 adds a separate immutable deployment asset boundary at:

`loomera.branding.assets`

It defines exactly two public symbols:

- `DeploymentBrandAssetConfig` — a frozen immutable snapshot of the resolved deployment brand asset settings;
- `get_deployment_brand_asset_config()` — constructs a fresh snapshot from `django.conf.settings` on every call.

The deployment asset snapshot has exactly **25 frozen fields** (15 original fields, four Task 2.16 quick-link print artwork paths, the Task 2.17 QR glyph path, four Task 2.18 authentication hero paths, and one workspace-chooser logo path). The settings map exactly as follows:

| Django/environment setting | Snapshot field | Loomera compatibility default |
| --- | --- | --- |
| `BRAND_LOGO_GLYPH_STATIC_PATH` | `logo_glyph_path` | `branding/logo/loomera-glyph-mark.png` |
| `BRAND_APP_ICON_STATIC_PATH` | `app_icon_path` | `branding/logo/loomera-app-icon.png` |
| `BRAND_LOGO_HEADER_STATIC_PATH` | `logo_header_path` | `branding/logo/loomera-logo-header.png` |
| `BRAND_LOGO_PRIMARY_STATIC_PATH` | `logo_primary_path` | `branding/logo/loomera-logo-primary.png` |
| `BRAND_WORKSPACE_LOGO_STATIC_PATH` | `workspace_logo_path` | `branding/logo/loomera-logo-horizontal-rtl-transparent-240.png` |
| `BRAND_FAVICON_SVG_STATIC_PATH` | `favicon_svg_path` | `branding/favicon/favicon.svg` |
| `BRAND_FAVICON_ICO_STATIC_PATH` | `favicon_ico_path` | `branding/favicon/favicon.ico` |
| `BRAND_FAVICON_16_STATIC_PATH` | `favicon_16_path` | `branding/favicon/favicon-16x16.png` |
| `BRAND_FAVICON_32_STATIC_PATH` | `favicon_32_path` | `branding/favicon/favicon-32x32.png` |
| `BRAND_FAVICON_48_STATIC_PATH` | `favicon_48_path` | `branding/favicon/favicon-48x48.png` |
| `BRAND_APPLE_TOUCH_ICON_STATIC_PATH` | `apple_touch_icon_path` | `branding/favicon/apple-touch-icon.png` |
| `BRAND_MASK_ICON_STATIC_PATH` | `mask_icon_path` | `branding/favicon/safari-pinned-tab.svg` |
| `BRAND_WEBMANIFEST_STATIC_PATH` | `webmanifest_path` | `branding/favicon/site.webmanifest` |
| `BRAND_SOCIAL_IMAGE_STATIC_PATH` | `social_image_path` | `branding/logo/loomera-logo-square.png` |
| `BRAND_QUICK_LINK_MIRROR_LABEL_ART_STATIC_PATH` | `quick_link_mirror_label_art_path` | `branding/quick-links/mirror-label-print-art.png` |
| `BRAND_QUICK_LINK_BUSINESS_CARD_FRONT_ART_STATIC_PATH` | `quick_link_business_card_front_art_path` | `branding/quick-links/business-card-front.png` |
| `BRAND_QUICK_LINK_BUSINESS_CARD_BACK_ART_STATIC_PATH` | `quick_link_business_card_back_art_path` | `branding/quick-links/business-card-back.png` |
| `BRAND_QUICK_LINK_TABLE_STAND_ART_STATIC_PATH` | `quick_link_table_stand_art_path` | `branding/quick-links/table-stand.png` |
| `BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH` | `quick_link_qr_glyph_path` | `branding/logo/loomera-glyph-mark-square-transparent-512.png` |
| `BRAND_LOGIN_HERO_STATIC_PATH` | `login_hero_path` | `branding/auth/login-desktop-hero.png` |
| `BRAND_CUSTOMER_SIGNUP_HERO_STATIC_PATH` | `customer_signup_hero_path` | `branding/auth/customer-signup-hero.png` |
| `BRAND_STYLIST_SIGNUP_HERO_STATIC_PATH` | `stylist_signup_hero_path` | `branding/auth/stylist-signup-hero.png` |
| `BRAND_MANAGER_SIGNUP_HERO_STATIC_PATH` | `manager_signup_hero_path` | `branding/auth/manager-signup-hero.png` |
| `BRAND_SOCIAL_IMAGE_WIDTH` | `social_image_width` | `1254` |
| `BRAND_SOCIAL_IMAGE_HEIGHT` | `social_image_height` | `1254` |

Every `*_STATIC_PATH` value is a Django-staticfiles-relative path. Settings import trims the value and rejects an empty path, a leading `/`, backslashes, URL schemes such as `://`, query strings, fragments, Windows absolute-drive paths, and `.` or `..` path segments with `ImproperlyConfigured`. The accessor does not repeat this validation. Social-image width and height must parse as positive integers; zero, negative, or non-integer values fail settings import with `ImproperlyConfigured`.

Task 2.18 routes the Login desktop hero and the customer, stylist, and manager Signup hero images through the same fresh deployment asset snapshot. The three Signup glyphs reuse the existing `logo_glyph_path`; they do not introduce another logo setting. Web/shared logos, authentication hero artwork, quick-link print artwork, and the QR glyph remain independently configured. The original Loomera images, layout, CSS, authentication behavior, and Persian copy remain unchanged by this asset-only task. The Homepage illustrations and media remain outside Task 2.18.

The supported templates continue resolving asset paths with Django's `{% static %}` tag. A deployment that overrides any path is responsible for packaging the referenced file in its staticfiles inputs, including the four authentication hero files and any separately overridden Signup glyph. Remote/CDN URLs, `MEDIA_URL` assets, database uploads, and per-salon asset routing are not part of this contract.

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

As of Task 2.12, the approved Python runtime consumers of `get_deployment_brand_config()` are exactly `apps/api/v1/views.py`, `apps/articles/views.py`, `apps/help_center/ai.py`, `apps/main/seo.py`, `apps/notifications/delivery.py`, `apps/orders/notification_delivery.py`, `apps/orders/views.py`, and `loomera/branding/context_processors.py`. Task 2.5 added no brand settings, fields, aliases, validation, caching, business/salon resolution, or environment reads. Brand identity remains deployment-level and does not infer or alter locale, country, currency, timezone, calendar, providers, authentication, authorization, or booking behavior.

Task 2.7 resolves each email sender from one fresh deployment brand snapshot's `default_from_email` at the existing sender-resolution point. `DEFAULT_FROM_EMAIL` remains owned by the settings layer; sender trimming, missing-email and empty-sender handling, opt-outs, attempts/retries, metadata, and masked logging retain their existing behavior. SMS and messaging paths do not use this branding accessor. No new setting or per-salon branding is introduced.

## Article Publisher Brand Identity

Task 2.8 makes `apps/articles/views.py` an explicitly approved brand-boundary runtime consumer. The Article JSON-LD publisher organization name uses `DeploymentBrandConfig.display_name` from one fresh snapshot; the default remains Loomera, with `BRAND_DISPLAY_NAME` still owned by the existing deployment setting and brand boundary. No new setting or environment variable is added. Branding remains deployment-level only, with no per-article, per-author, per-salon, or per-locale publisher branding. Persian magazine strings, Article author metadata, URLs, breadcrumbs, content, and locale behavior remain unchanged. Broader locale-aware SEO remains Phase 16.

## Help AI OpenRouter Brand Identity

Task 2.9 makes `apps/help_center/ai.py` an explicitly approved Python runtime consumer of `get_deployment_brand_config()`. OpenRouter uses one fresh local snapshot: `X-Title` uses `DeploymentBrandConfig.display_name`, and the `HTTP-Referer` fallback uses `DeploymentBrandConfig.public_base_url`. `HELP_AI_SITE_URL` remains the higher-priority Help AI-specific override; an empty effective URL omits `HTTP-Referer`. `BRAND_DISPLAY_NAME` and `PUBLIC_BASE_URL` remain owned by the existing deployment brand/settings boundary. No new setting or environment variable is introduced, and default Loomera behavior is preserved.

Branding remains deployment-level only, with no per-user, per-help-article, per-salon, or per-locale AI brand identity. Groq and custom providers remain unchanged and do not resolve this snapshot. Provider credentials, models, endpoints, provider selection, ZDR/data collection policy, request behavior, and error handling remain unchanged.

## Shared Shell Brand Literal Cleanup

Task 2.6 reuses the existing centralized `deployment_brand` template context in the shared loader splash and dashboard sidebar. The loader splash title and logo alt text, plus the sidebar navigation brand label and both shared logo alt values, resolve from `deployment_brand.display_name`; the current compatibility configuration therefore continues to render Loomera by default.

Task 2.6 introduces no new brand setting or branding boundary. CSS class names such as `loomera-*` remain implementation identifiers and are deliberately unchanged. Locale, direction, and translation behavior remain deferred to Phase 3. Branding remains deployment-level only; this task does not introduce per-salon or per-tenant white-labeling.

Task 2.10 extends the same existing shared template brand context to the desktop and mobile home-link accessibility labels and the shared footer copyright. Both home-link `aria-label` values and the footer deployment brand name now consume `deployment_brand.display_name`; Loomera remains the compatibility default. The Persian footer tagline, navigation, authentication behavior, URLs, Persian content, locale/direction behavior, and layout remain unchanged.

Task 2.10 introduced no new setting, environment variable, accessor, context processor, or Python runtime consumer. Task 2.12 subsequently adds only `apps/orders/views.py` to the approved Python runtime consumer set, bringing the current exact allowlist to eight paths: `apps/api/v1/views.py`, `apps/articles/views.py`, `apps/help_center/ai.py`, `apps/main/seo.py`, `apps/notifications/delivery.py`, `apps/orders/notification_delivery.py`, `apps/orders/views.py`, and `loomera/branding/context_processors.py`. Logo asset routing remains owned by the existing `DeploymentBrandAssetConfig` and shared `partials/brand/logo.html` partial; neither Task 2.10 nor Task 2.12 duplicates or replaces that behavior.

Branding remains deployment-level only. Task 2.10 does not introduce per-user, per-salon, per-business, or per-locale white-label behavior. Auth/password-recovery brand identity, quick-link print branding, and other remaining Phase 2 residuals remain deferred to separately authorized tasks; Phase 2 is not claimed complete.

## Calendar Brand Metadata Boundary

Task 2.11 extends `DeploymentBrandConfig` with `calendar_prodid` and `calendar_name`. These fields snapshot the already-existing `LOOMERA_CALENDAR_PRODID` and `LOOMERA_CALENDAR_NAME` Django settings through the same fresh deployment brand accessor; no new environment variable, Django setting, accessor, or context processor is introduced.

`LOOMERA_CALENDAR_PRODID` and `LOOMERA_CALENDAR_NAME` remain independently configurable in the settings layer. Their current compatibility defaults remain `-//Loomera//Appointment//FA` and `Loomera Appointment` under the default brand settings, while explicit deployment overrides are returned unchanged by the centralized brand snapshot. `loomera.branding.config` does not recompute either field from `DeploymentBrandConfig.name` or `display_name` and does not override explicitly configured calendar metadata.

Task 2.11 was boundary-only. Task 2.12 wires the existing calendar runtime surfaces in `apps/orders/views.py` through that same deployment brand boundary. Google Calendar details use one fresh snapshot's `display_name`; the endpoint, `action=TEMPLATE`, title, dates, location, query structure, Persian wording, duration, and timezone conversion remain unchanged. `AppointmentICSView` obtains one fresh `DeploymentBrandConfig` snapshot per request and uses that same snapshot for `name`, `domain`, `calendar_prodid`, and `calendar_name`; there is no module-global snapshot or brand cache.

ICS UID domain identity now comes from `deployment_brand.domain`, PRODID from `deployment_brand.calendar_prodid`, and `X-WR-CALNAME` from `deployment_brand.calendar_name`. The machine-safe calendar product token is derived from `deployment_brand.name` with Django `slugify`; a non-sluggable value falls back to the deployment-neutral token `brand`. The UID retains the structure `<brand-token>-appointment-<appointment-pk>-<order-id>@<brand-domain>` and the inline ICS filename uses `<brand-token>-appointment-<appointment-pk>.ics`. Default Loomera configuration therefore preserves `loomera-appointment` compatibility, while an alternate deployment such as Aurora produces `aurora-appointment` identity without editing `apps/orders/views.py`.

The existing `LOOMERA_CALENDAR_PRODID` and `LOOMERA_CALENDAR_NAME` settings remain independently configurable and continue to be resolved by the settings/configuration boundary. Task 2.12 introduces no environment variable or Django setting and does not recompute valid configured calendar metadata from the display name. RFC5545 text escaping, CRLF stripping/token sanitization, text-length limits, appointment ownership enforcement, ICS line construction, `Content-Disposition = inline`, and Android chooser behavior remain unchanged. Calendar date/timezone semantics and Gregorian/Jalali behavior are unchanged.

As of Task 2.12, `apps/orders/views.py` is the one new runtime consumer and the approved Python runtime consumer allowlist is exactly eight paths: `apps/api/v1/views.py`, `apps/articles/views.py`, `apps/help_center/ai.py`, `apps/main/seo.py`, `apps/notifications/delivery.py`, `apps/orders/notification_delivery.py`, `apps/orders/views.py`, and `loomera/branding/context_processors.py`.

Calendar branding remains deployment-level only. Task 2.12 introduces no per-salon, per-user, per-appointment, or per-locale white labeling. Auth/password-recovery brand identity, quick-link print branding, and any other fresh Phase 2 exit-audit residuals remain separately deferred. Phase 2 is not claimed complete, and Phase 3 remains blocked until a fresh Phase 2 exit audit proves completion.

## Password Recovery Brand Identity

Task 2.13 wires only the active `accounts:remember_password` entry surface to the existing deployment brand template context. `templates/accounts/remember_password.html` now reuses the existing `partials/brand/logo.html` boundary for its horizontal logo and uses `deployment_brand.display_name` in the existing Persian account-security label. Configured logo selection therefore continues through the established `DeploymentBrandAssetConfig` template boundary, while the default Loomera deployment preserves the existing user-facing brand identity and alternate deployments require no recovery-template source edit.

Task 2.13 introduces no new Django setting, environment variable, context processor, Python brand accessor consumer, or module-global brand snapshot/cache. The approved Python runtime consumer allowlist remains exactly eight paths: `apps/api/v1/views.py`, `apps/articles/views.py`, `apps/help_center/ai.py`, `apps/main/seo.py`, `apps/notifications/delivery.py`, `apps/orders/notification_delivery.py`, `apps/orders/views.py`, and `loomera/branding/context_processors.py`. `apps/accounts/views.py` remains outside that boundary because request-rendered templates already receive the deployment brand context globally.

`RememberPasswordView`, the `accounts:remember_password` route, OTP generation/delivery/retry behavior, session state/TTL, reset authorization, redirects, CSRF, authentication checks, form fields, form submission behavior, and error handling are unchanged. The existing Persian copy remains intentionally unchanged except for deployment-brand interpolation; broader translation remains deferred to later phases. Other authentication templates are not changed by Task 2.13, and login-page branding remains separately deferred.

This remains deployment-level branding only and does not introduce per-user, per-salon, per-business, or per-locale white labeling. Quick-link print branding and any other residual found by the next fresh Phase 2 exit audit remain deferred. Phase 2 is not claimed complete, and Phase 3 remains blocked until a fresh Phase 2 exit audit proves completion.

## Login Brand Identity

Task 2.14 wires only the active `accounts:login` entry surface, served by `LoginUserView` with `templates/accounts/login.html`, to the existing deployment brand template context. The page title, visible home-pill brand name, home-pill accessible identity, and login heading now use `deployment_brand.display_name`. The home pill reuses the existing shared `partials/brand/logo.html` glyph boundary, so configured glyph selection continues through the established deployment brand asset contract without a login-specific setting or context processor.

Task 2.14 introduces no new Django setting, environment variable, Python runtime accessor consumer, module-global brand snapshot, or cache. The approved Python runtime consumer allowlist remains exactly eight paths: `apps/api/v1/views.py`, `apps/articles/views.py`, `apps/help_center/ai.py`, `apps/main/seo.py`, `apps/notifications/delivery.py`, `apps/orders/notification_delivery.py`, `apps/orders/views.py`, and `loomera/branding/context_processors.py`. `apps/accounts/views.py` remains outside that accessor boundary because request-rendered templates already receive the global deployment brand context.

`LoginUserView`, authentication, form fields/submission, session/login behavior, redirects, `next_url`/`next_query`, booking-return behavior, forgot-password/signup links, CSRF, error rendering, JavaScript, and page layout remain unchanged. Persian copy remains intentionally untranslated except for deployment-brand interpolation. Internal lower-case `loomera-*` CSS/design-token identifiers are implementation identifiers, not deployment identity, and remain unchanged.

The existing `branding/auth/login-desktop-hero.png` artwork and login CSS remain intentionally unchanged; any deployment-brand decision or redesign for that hero stays deferred to a later fresh Phase 2 exit audit. Quick-link print branding also remains deferred, and Task 2.14 does not claim all auth branding is complete. Phase 2 is not claimed complete, and Phase 3 remains blocked until a fresh Phase 2 exit audit proves completion.

## Signup Visible Brand Identity

The three active Signup templates — `templates/accounts/customer_signup.html`, `templates/accounts/stylist_signup.html`, and `templates/accounts/register.html` — now resolve the page title, visible home-pill name, and home-pill accessible label from the existing `deployment_brand.display_name` template context, backed by the deployment-level `BRAND_DISPLAY_NAME` setting. Their role-specific Persian registration labels remain unchanged. The default is still Loomera; a buyer override updates all three identity slots without a template edit, new setting, runtime accessor, or context processor.

This text identity is independent of authentication artwork: the three Signup hero paths still use their existing `deployment_brand_assets.*_signup_hero_path` fields, while each existing `lm-signup-brand-logo` image continues to use `deployment_brand_assets.logo_glyph_path`. No shared-logo partial substitution, image markup/layout/CSS change, form/CSRF/OTP/redirect change, or locale/provider inference is part of this follow-up.

This is a narrowly scoped Phase 2 follow-up stacked on Task 2.18, not a declaration that Phase 2 is complete. Phase 3 remains blocked pending a fresh Phase 2 exit audit.

## Shared Shell and Search Metadata Brand Identity

The shared public-shell description in `templates/base.html`, dashboard-shell SEO/Open Graph/Twitter fallback metadata in `templates/dashboard_template.html`, and public search title and description in `templates/pages/search.html` resolve the deployment display-name token from the existing `deployment_brand.display_name` context (`BRAND_DISPLAY_NAME`). A buyer can change the supported identity without editing templates, adding a new setting or Python runtime accessor, or introducing caching or request/salon/user inference.

With no override, the default **Loomera** identity and all surrounding Persian SEO copy remain unchanged in rendered output. Repeated sequential buyer overrides use fresh context snapshots; no extra context processor is added. HTML language/direction, `og:locale=fa_IR`, visual assets, styling, SEO prose apart from the brand token, public URLs, auth/booking/provider behavior, and locale handling remain unchanged.

This cleanup does not migrate Persian `لومرا` product/marketing text, homepage media, email fallback copy, PDFs, legal statements, static filenames, or other audit findings. **Phase 2 NOT COMPLETE. Phase 3 BLOCKED.**

## Homepage Persian Display Brand Identity

The public homepage (`templates/pages/home.html`) now takes its **twelve** visible Persian brand-name occurrences from `deployment_brand.display_name_fa`, backed by the independent deployment setting `BRAND_DISPLAY_NAME_FA`. Those twelve slots include the page title, hero copy and accessible labels, illustration alternative text, the final call to action, and the video-dialog accessible heading. The setting trims surrounding whitespace and falls back to `"لومرا"` when absent or blank, so the original Persian homepage renders identically by default.

Buyer configuration: set **both** `BRAND_DISPLAY_NAME` (Latin/shared shell, signup, search metadata) and `BRAND_DISPLAY_NAME_FA` (homepage Persian copy) if the two identities should change together. They intentionally do **not** derive from each other. For example, `BRAND_DISPLAY_NAME=Aurora` and `BRAND_DISPLAY_NAME_FA=آرورا` produce independent resolved values in the same fresh `DeploymentBrandConfig` snapshot. Changing only the Latin setting leaves the homepage Persian name as `لومرا`. Buyer-provided Persian text is HTML-escaped by normal Django template interpolation.

The homepage's surrounding Persian sentences, classes, layout, forms, routes, JavaScript, CSS, `loomera-*` implementation IDs, seven `images/home/` static file references, and two `videos/loomera-*` media references remain unchanged. The underlying image/video pixels may still contain embedded Loomera branding; this text-only change does not rebrand media assets, translate the page, infer locale, or add per-user/business/salon branding or provider behavior. No new Python runtime brand consumer, context processor, or cache is introduced.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED** pending a fresh residual audit.

## Active Manager PDF Report Brand Identity

The active report export path `dashboards:reports` keeps its legacy query parameter `export=csv` and `build_reports_csv_response()` compatibility entry point, which already generate `application/pdf` output with the same `loomera-salon-report-<id>.pdf` download filename. The fpdf2 producer is `apps/dashboards/reports_components.py`; this work does not modify the separate `templates/dashboards/reports_pdf.html` HTML document, whose usage requires an independent audit.

For each generated PDF, the producer reads **one fresh** `get_deployment_brand_config()` snapshot and **one fresh** `get_deployment_brand_asset_config()` snapshot. The PDF's visible footer host is `DeploymentBrandConfig.domain` (`BRAND_DOMAIN`); author metadata and the title/salon fallback use `DeploymentBrandConfig.display_name` (`BRAND_DISPLAY_NAME`). The report header logo resolves through the existing `DeploymentBrandAssetConfig.logo_header_path` (`BRAND_LOGO_HEADER_STATIC_PATH`) and the existing staticfiles resolver. All settings retain their existing import-time defaults and validation; no new environment variable, dynamic request branding, or new image assets are introduced.

The default display name stays `Loomera`. The default header logo path `branding/logo/loomera-logo-header.png` has the same Git blob as the previously fixed PDF logo `branding/logo/loomera-logo-horizontal-rtl-transparent-360.png`, preserving default logo pixels. The default `BRAND_DOMAIN` is `loomera.local`, so a deployment that needs `loomera.ir` (or a buyer domain) in its PDF footer must explicitly configure `BRAND_DOMAIN`; no fixed domain is inferred. Separately overriding two deployment brands in one process yields fresh PDF metadata, footer and logo selection.

Report authorization, manager/salon ownership, selected filters, data queries and financial calculations, PDF formatting/layout, text shaping, fonts, file naming, response headers/content type and route semantics are unchanged. The internal class name `LoomeraReportPDF` and historical filename are technical compatibility identifiers and remain unchanged. The change extends the approved Python consumers of the shared brand identity and asset boundaries to include `apps/dashboards/reports_components.py`, with no caching or additional context processor.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** Remaining email, legal, auth, marketing, older HTML-PDF template and embedded artwork branding require separate review.

## Workspace Chooser Deployment Brand Identity

The active multi-role chooser (`accounts:workspace_choose`, `templates/accounts/workspace_choose.html`) now renders its four fixed Persian brand-identity positions from the existing fresh template `deployment_brand.display_name_fa` snapshot, backed by independently configured `BRAND_DISPLAY_NAME_FA`: the page title, brand-link accessible name, logo alternative text, and the empty-state invitation. With no override, these positions still render **لومرا**. Deployments requiring both Latin and Persian names to change must configure `BRAND_DISPLAY_NAME` and `BRAND_DISPLAY_NAME_FA` independently.

The workspace-specific 240-pixel RTL logo uses `deployment_brand_assets.workspace_logo_path`, backed by the new `BRAND_WORKSPACE_LOGO_STATIC_PATH`. Its exact original default `branding/logo/loomera-logo-horizontal-rtl-transparent-240.png` is preserved (the existing `BRAND_LOGO_HEADER_STATIC_PATH` default is a distinct 360-pixel file). Like other `BRAND_*_STATIC_PATH` values, settings import validates a non-empty staticfiles-relative path with the existing `_read_brand_static_path` validator. A buyer supplies an image through packaged Django staticfiles and configures the new path; there is no URL fetching, automatic image generation, or fallback to a different Loomera image when the override is missing.

No workspace permissions, role availability, ownership rules, POST data, CSRF behavior, redirects, URL routes, frontend interactions, CSS, layout or surrounding Persian wording change. The shared brand snapshots remain deployment-scoped and fresh; the chooser adds no new direct Python accessor consumer, context processor, locale inference or per-salon branding. The original image bytes and all other static assets remain unchanged.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** Legal, help/bot/notification content, media and other exit-audit residuals remain independently scoped.

## Quick-Link Print Brand Identity

Task 2.15 wires `apps/orders/quick_link_print_templates.py` to the existing deployment brand identity and asset boundaries. The generated print logo now resolves from `DeploymentBrandAssetConfig.logo_header_path`, backed by the existing `BRAND_LOGO_HEADER_STATIC_PATH`; no print-specific logo setting or environment variable is added. At this migration point the default `branding/logo/loomera-logo-header.png` and the previous fixed `branding/logo/loomera-logo-horizontal-rtl-transparent-360.png` are byte-identical Git blobs (`8512a25cac6fd0971427151dd27febb1eddf646a`), so default Loomera print-logo pixels remain compatible.

The fixed `https://loomera.ir` fallbacks and fixed visible `loomera.ir` print text are removed. Public-base resolution now uses `DeploymentBrandConfig.public_base_url` (`PUBLIC_BASE_URL`) and then `site_url` (`SITE_URL`) through the existing deployment brand accessor, while the current valid canonical/request-host precedence remains where the print runtime already used it; `DeploymentBrandConfig.domain` (`BRAND_DOMAIN`) supplies the final HTTPS deployment fallback. Visible printed host identity uses the effective configured public URL hostname when available and otherwise the deployment domain. Live preflight confirmed the old fixed print symbol was consumed only by dependency validation, so that unused symbol constant and dependency were removed rather than replaced by a new asset setting.

Task 2.15 introduces no new setting, environment variable, branding dataclass field, module-global branding snapshot, or cache. The exact approved Python runtime consumer allowlist for `get_deployment_brand_config()` is now nine paths: `apps/api/v1/views.py`, `apps/articles/views.py`, `apps/help_center/ai.py`, `apps/main/seo.py`, `apps/notifications/delivery.py`, `apps/orders/notification_delivery.py`, `apps/orders/quick_link_print_templates.py`, `apps/orders/views.py`, and `loomera/branding/context_processors.py`; the quick-link print module is the only new consumer. Its use of `get_deployment_brand_asset_config()` is likewise limited to fresh runtime logo resolution.

Quick-link QR generation and payload, tokens, salon lookup and URL/path composition, booking attribution and request/session behavior, generated filenames, response content type, preview behavior, print coordinates, dimensions, DPI, bleed/trim/QR/name boxes, colors, fonts, transparency, resize/compositing limits, and layout remain unchanged. The static quick-link artwork files `branding/quick-links/mirror-label-print-art.png`, `branding/quick-links/business-card-front.png`, `branding/quick-links/business-card-back.png`, and `branding/quick-links/table-stand.png` remain unchanged and are not yet claimed to be brand-neutral; embedded artwork branding remains subject to a fresh Phase 2 exit audit.

The login desktop hero-artwork deployment-brand decision also remains deferred, along with any remaining quick-link artwork branding or other residual found by the next fresh Phase 2 exit audit. Task 2.15 does not claim Phase 2 complete, and Phase 3 remains blocked until a fresh Phase 2 exit audit proves completion.

## Quick-Link Print Artwork Asset Configuration

Task 2.16 adds deployment-level asset substitution for the four **existing static print artwork images**. Each setting above is an environment/Django setting resolved and validated at settings import by the existing `_read_brand_static_path` helper. `get_deployment_brand_asset_config()` returns a **fresh, frozen 20-field snapshot** at runtime. The four artwork consumers in `apps/orders/quick_link_print_templates.py` and the print dependency checker use the snapshot with Django staticfiles resolution; the previous fixed paths are no longer authoritative. The Task 2.15 generated print logo remains independently controlled by `BRAND_LOGO_HEADER_STATIC_PATH`.

To supply buyer-branded print artwork:

1. Design four replacement PNG images without unintended Loomera logos, domain names, or promotional copy. Simply changing `BRAND_DISPLAY_NAME`, `BRAND_DOMAIN`, or the generated print logo setting cannot change pixels embedded in the default PNGs; the app does **not** scrub, recolor, mask, crop, or regenerate embedded print art.
2. Keep the exact print contracts: mirror label **945 × 945 px**, a genuinely transparent top-left pixel (alpha zero), and RGBA-compatible content; business-card **front and back each 1075 × 575 px**; table stand **1311 × 1819 px** with **300-DPI metadata** (the existing runtime tolerance is 295–305 DPI). Keep composition compatible with the existing QR/name placement, table-stand trim and bleed boxes, and all print geometry.
3. Package the four files in a Django **staticfiles input** available to the deployment (for example, `static/buyer/quick-links/`). Use distinct paths for front and back, and ensure each configured path resolves to a real file.
4. Configure `BRAND_QUICK_LINK_MIRROR_LABEL_ART_STATIC_PATH`, `BRAND_QUICK_LINK_BUSINESS_CARD_FRONT_ART_STATIC_PATH`, `BRAND_QUICK_LINK_BUSINESS_CARD_BACK_ART_STATIC_PATH`, and `BRAND_QUICK_LINK_TABLE_STAND_ART_STATIC_PATH` with their staticfiles-relative paths (for example, `buyer/quick-links/mirror-label.png`). Values are trimmed; empty, absolute/Windows-drive, backslash, URL, query/fragment, and `.`/`..` segment values fail settings import.
5. Run the deployment's usual staticfiles collection and deployment process. These are **deployment-packaged local static asset paths**, not remote URLs, CDN downloads, `MEDIA_URL` uploads, database media, or request-dependent assets. If a configured file is missing, the print loader raises `ImproperlyConfigured`; the dependency checker reports that configured missing path. There is no fallback to Loomera artwork.
6. Preview and download all relevant print outputs in the deployed environment: mirror label, business-card front, business-card back, and table stand. Confirm the buyer artwork, transparency, QR placement, printed name/host, dimensions, and print metadata. The counter-card behavior is unchanged.

With no overrides, the four default paths still reference the original, **unchanged Loomera PNGs**. This task does not modify any `static/branding/quick-links/*.png` bytes or introduce per-salon, per-user, per-business, per-location, or per-locale white-labeling. Image loading/conversion, geometry, text/QR positions, URL precedence, DPI checks, filename/content-type contracts, preview and download behavior remain unchanged.

The approved Python runtime consumer list for `get_deployment_brand_config()` remains the **nine Task 2.15 paths**: `apps/api/v1/views.py`, `apps/articles/views.py`, `apps/help_center/ai.py`, `apps/main/seo.py`, `apps/notifications/delivery.py`, `apps/orders/notification_delivery.py`, `apps/orders/quick_link_print_templates.py`, `apps/orders/views.py`, and `loomera/branding/context_processors.py`. The approved runtime consumers for `get_deployment_brand_asset_config()` are **exactly four**: `apps/orders/quick_link_print_templates.py`, `loomera/branding/context_processors.py`, `apps/orders/quick_link_qr.py`, and `apps/orders/management/commands/quick_link_readiness_check.py`. Neither boundary reads request, user, salon, business, database, or locale state to choose quick-link artwork.

The remaining deployment-brand decision for `branding/auth/login-desktop-hero.png` is deferred, as are other residuals identified by a fresh Phase 2 exit audit. Task 2.16 does not represent a Phase 2 exit audit or authorize additional cleanup.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.**


## Quick-Link QR Center Glyph Deployment Asset

Task 2.17 adds exactly one setting, `BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH`, with the unchanged compatibility default `branding/logo/loomera-glyph-mark-square-transparent-512.png`. It maps to `DeploymentBrandAssetConfig.quick_link_qr_glyph_path`; the fresh, frozen snapshot now has exactly **20 fields**. Settings import validates this path with the existing `_read_brand_static_path` helper.

The website logo and QR center glyph are **independently configured**. Changing `BRAND_LOGO_GLYPH_STATIC_PATH`, another website logo, or the four print artwork settings does not automatically replace the glyph composited into QR pixels. Both standalone QR output and print output use the shared QR service; print layouts are unchanged.

To replace the QR emblem:

1. Supply a readable raster **PNG**, preferably square, with visible pixels, a clear centered mark and transparent surrounding space. Keep fine detail modest for print readability. The existing loader converts to RGBA, crops transparent outer bounds, and resizes/composites within the existing center/backing limits; transparency is recommended, not mandatory. Completely transparent images and non-PNG files are rejected.
2. Package it in a deployment staticfiles input, for example `static/buyer/qr/glyph.png`, and set `BRAND_QUICK_LINK_QR_GLYPH_STATIC_PATH=buyer/qr/glyph.png`. Use a staticfiles-relative path, not a URL, absolute path or media upload. Apply the usual staticfiles collection/deployment process.
3. A missing, non-file, unreadable, corrupt, non-PNG or invisible configured glyph fails explicitly with `ImproperlyConfigured`; there is no fallback to Loomera artwork. The read-only `quick_link_readiness_check` command uses the same selected path and shared image loader and reports a `qr-glyph` failure for invalid files. No network image fetching occurs.
4. Preview standalone and printed QR outputs and test scanning at intended physical sizes in the deployment. Confirm the buyer glyph and destination URL. The generated result's `glyph_static_path` records the selected path, and sequential Django settings overrides take effect after module import.

QR payload/target URL, tokens, error correction, border/quiet zone, output dimensions, colors, backing region, overlay ratios, resizing/compositing geometry, content type and filenames remain unchanged. Original static PNG bytes remain unchanged; the default preserves the existing Loomera artwork. Selection uses only deployment settings, with no module-global snapshot/cache or request/user/salon/business/locale routing. The nine identity consumers remain unchanged; the four asset consumers are listed above.

The existing natural CI executes production hygiene/build-release tests, including new database-free QR glyph regressions in the hygiene module. The complete focused QR service and readiness suites are separate: authored tests are not evidence of execution, and green hygiene CI alone does not establish full print rendering, QR decoding or browser validation.

Remaining Phase 2 gaps include login/signup artwork, direct identity/logo consumers, homepage artwork, public/legal/SEO copy, reports, download filenames, notification/help/bot copy and theme/deployment-content review. This task resolves only the shared QR glyph selection boundary.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.**

## Partners Landing Page Persian Brand Identity

The active `/partners/` page (also served at the legacy `/join-loomera/` route) now renders seven Persian brand references from the existing request/template `deployment_brand.display_name_fa` snapshot, configured by `BRAND_DISPLAY_NAME_FA`. The references are the HTML page title, meta description, Open Graph title, hero badge, introductory paragraph, benefits heading, and closing call-to-action heading. The compatibility default remains **لومرا**. Separate buyer deployments may set an independent Persian brand name; overriding only the Latin `BRAND_DISPLAY_NAME` does not implicitly translate or change it. Django template autoescaping remains enabled, including within metadata.

**Explicit preservation boundary:** The two support links intentionally retain their existing literal `?topic=درخواست همکاری مجموعه با لومرا` values because they are support-form prefill/routing inputs rather than visible display text. This incremental change does not redefine that support-topic contract. The `/partners/` and `/join-loomera/` routes, authenticated/anonymous registration links, layout, classes, static assets, shared header/footer, all other Persian copy, and support processing are unchanged. No settings, views, URLs, context processors, client scripts, providers, migrations or legal documents were modified.

The five added database-free hygiene regressions cover exactly seven template bindings, unchanged support links and route names, existing default copy, sequential independent buyers, Latin/Persian separation, and escaped buyer-supplied HTML. The tests-only RED commit intentionally demonstrated that the original static template did not satisfy those requirements (PR #38, GitHub Actions run #39448618778). Any later GREEN result must be verified separately; passing the targeted CI does not establish full-suite or browser QA.

Other Phase 2 gaps (including support-topic localization, legal review, help/messaging copy and embedded visual branding) remain separate. **Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized by this change.

## Help Article Wrapper Persian Brand Identity

The active `/help/article/<slug>/` template uses the existing `deployment_brand.display_name_fa` snapshot for exactly **three** Persian identity references: the browser title suffix (`<article title> | مرکز راهنمای <brand>`), the document metadata label (`راهنمای <brand>`), and the action-sidebar instruction (`... در <brand> شو.`). The current default remains **لومرا**. Buyers configure their independent Persian display name using `BRAND_DISPLAY_NAME_FA`; the Latin `BRAND_DISPLAY_NAME` alone does not change it. Django autoescaping is preserved in all three contexts, including the HTML title.

This is a presentation-only change in `templates/help_center/article.html`. It does **not** alter article titles, summaries, stored database content, body Markdown rendering, dynamic category/article links, action-link destinations, assistant prompts/triggers, CSS, template filters, the `/help/article/` route, role authorization, support/help services, other Help Center pages, legal documentation, existing settings, or the brand context processor. No new runtime accessors or provider/locale inference are introduced.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` verify exactly three shared template bindings, unchanged article behavior, legacy default copy, two sequential independent Persian brand overrides, Latin/Persian separation, and HTML escaping. The tests-only RED commit `8187779d2ce11ea78e951d001ee3f048e1268f13` was validated by expected-failing GitHub Actions run `39450746404`; this is not evidence of GREEN CI. The final commit CI must be checked separately. Full-suite, database-backed behavior and browser testing are not covered by this focused change.

Other residual Help Center templates, legal-copy decisions and help-assistant text remain for separately scoped review. **Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized by this change.

## Help Search and Category Browser Title Identity

Exactly two active Help Center templates now derive their **browser title only** from the existing shared deployment Persian identity `deployment_brand.display_name_fa` (configured independently by `BRAND_DISPLAY_NAME_FA`): `templates/help_center/search.html` renders `جستجو در مرکز راهنمای <brand>` and `templates/help_center/category.html` renders `<category title> | مرکز راهنمای <brand>`. The default remains **لومرا**; a Latin `BRAND_DISPLAY_NAME` override alone does not infer a Persian name. Both title expressions retain normal Django HTML autoescaping.

The scope is display-only: search query, category slug/title and description, article results, filters and query parameters, role-aware article visibility, forms, breadcrumbs, help assistant buttons, support links, markup/classes, JavaScript/static assets, root URLs `/help/search/` and `/help/category/<slug>/`, views, stored content, document/legal content and other Help Center pages are unchanged. Existing deployment brand settings and the context processor are reused; no new configuration setting, runtime accessor, provider/locale selection, or database migration is introduced.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` cover exactly one brand slot per template, unchanged default titles and page flows, two sequential buyers, separation of Latin and Persian brand names, and HTML escaping. The tests-only RED commit `750635fad3a7d494cca2fa2d4eeb23b3a61add96` failed as expected in GitHub Actions run `39452418095` before template changes; the final implementation CI is evaluated separately. Passing natural CI does not certify full-suite, browser, or production behavior.

Other Help Center labels, homepage/legal headings, articles and help-assistant text remain separately scoped Phase 2 items. **Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment or Merge is authorized by this task.

## Help Center Home Metadata Persian Brand Identity

The public `/help/` landing page now uses the existing deployment template context `deployment_brand.display_name_fa` for exactly **two metadata identity references** in `templates/help_center/home.html`: browser title (`مرکز راهنمای <brand>`) and meta description (`راهنمای ساده و مرحله‌به‌مرحله استفاده از <brand>`). Both continue to show **لومرا** under the existing default. For independent deployments, `BRAND_DISPLAY_NAME_FA` supplies the Persian name; changing only `BRAND_DISPLAY_NAME` does not change it. Django autoescaping applies to both fields, including the HTML meta attribute.

**Deliberately preserved legal boundary:** The visible legal-documents section heading `قوانین و مقررات لومرا` remains a fixed literal in this task. Legal section naming and contract titles require separate review and are not implicitly localized as website metadata. There is therefore exactly one unchanged `لومرا` literal left in this template. This task does not change legal document records, legal document contents, legal links, support/service copy, help article content, category/role data, search URLs/forms, page body, help assistant behavior, template CSS, or other Help Center routes. It adds no new settings, runtime accessor, context processor, provider/locale switching, migrations, or deployment behavior.

Five database-free regression tests in `apps/main/test_production_settings_hygiene.py` check exactly two dynamic brand slots while preserving the legal heading, original default page content, independent sequential buyer overrides, Latin/Persian separation, and safe escaping. The tests-only RED commit `afdd5efff697884c7786d4478bdbf6aff7c5ed98` failed as expected in GitHub Actions `39453931982` before the template changes. A separate successful natural GitHub CI run is required to establish GREEN; these checks do not substitute for complete regression, legal review or browser QA.

Remaining Phase 2 items, including the legal heading, legal document identity, other page copy, help-assistant content and art assets, remain separate. **Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No Merge or deployment is authorized by this work.

## Magazine Landing Page Persian Brand Identity

The active public `/magazine/` template (`templates/articles/magazine_home.html`) uses the existing shared `deployment_brand.display_name_fa` context for exactly **four** Persian brand labels: HTML title (`مجله <brand> | ...`), meta description (`مجله <brand>؛ ...`), visible magazine eyebrow (`مجله <brand>`), and the conditional magazine stories section label (`استوری‌های <brand>`). The default remains **لومرا**. Independent deployments configure the Persian label with `BRAND_DISPLAY_NAME_FA` and do not derive it from a Latin-only `BRAND_DISPLAY_NAME` override. Django autoescaping remains active for title, meta and visible labels.

**Scope boundary:** The magazine route, view and its existing `page_title` context string, source articles, story data and payloads, story viewer partial, viewer moderation/report strings and reason values, user permissions, report/analytics behavior, ordering and filter forms, category links, dynamic article snippets, URLs, client-side JS, static assets, shared shell, persistent records, providers, legal terms, and other magazine pages are unchanged. This does not introduce settings, runtime accessors, migrations, or deployment/provider/locale changes. Content outside these four explicitly selected display labels requires separate treatment.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` check exactly four template bindings, default behavior including an active stories section, sequential deployment-independent buyer names, Latin/Persian separation, autoescaping, and unchanged filter and story links. The tests-only RED commit `70a8a686e90a48efeb5f5233c84dcbf08ded1f71` failed as expected in GitHub Actions `39461022970` on zero brand bindings in the original template. A separately verified successful CI on the final head is required for GREEN; this workflow does not certify full-suite, database-backed, browser, or production behavior.

Remaining Phase 2 branding and legal/messaging/story-moderation copy gaps are separate tasks. **Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No Merge or deployment is authorized by this task.

## Magazine Category and Tag List Persian Brand Identity

The active shared `templates/articles/article_list.html` template serves category (`/magazine/category/<slug>/`) and tag (`/magazine/tag/<slug>/`) views. Exactly **two** presentation-only brand references now use the existing `deployment_brand.display_name_fa` context: the browser title suffix (`<list_title> | مجله <brand>`) and the visible link back to the magazine landing page (`مجله <brand>`). The default remains **لومرا**. Buyers may configure independent Persian naming with `BRAND_DISPLAY_NAME_FA`; changing only Latin `BRAND_DISPLAY_NAME` does not infer a Persian translation. Django autoescaping applies to both placements.

This task does not change dynamic `list_title` or `list_description`, the Persian content fallback in `ArticleTagView` (`apps/articles/views.py`), category/tag model data, published articles, article cards, pagination, category/tag URLs and links, empty states, user permissions, request processing, styles, scripts, shared shell, other magazine pages, provider/locale behavior, settings, or the database. The View's default content copy remains separately scoped for future editorial review; this change is deliberately limited to two template chrome labels.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` cover exact template slots and preserved pagination markup, default title and backlink, sequential independent buyer overrides, Latin/Persian separation, escaping, and stable category/tag route names. The tests-only RED commit `458d637962e448d4f8af4d1e8714a5577157f8fc` failed as expected in GitHub Actions `39464289164` while the original template still hard-coded the brand. Only a separately verified GREEN CI on the final head establishes the targeted checks; these checks do not claim full-suite, database-backed, or browser coverage.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized as part of this change.

## Magazine Story Explorer Persian Brand Identity

The public `/magazine/stories/` page (`templates/articles/story_explore.html`) now uses existing `deployment_brand.display_name_fa` template context in **exactly three** Persian identity slots: browser title (`استوری‌های مجموعه‌ها | مجله <brand>`), meta description (`استوری‌های مجموعه‌های زیبایی در <brand>`), and the backlink label to the magazine home (`مجله <brand>`). The default remains **لومرا**. A separate Persian `BRAND_DISPLAY_NAME_FA` setting controls the brand; Latin-only `BRAND_DISPLAY_NAME` does not infer a Persian name. Django template autoescaping is unchanged.

This is a presentation-only boundary. Story model and payload data, read/visibility permissions, request-driven search, favorite scope, sorting, topic and service filters, paging and query parameters, all route names and destinations, the story viewer include, reporting/moderation strings and reason codes, JS event handlers, styles/static assets, views, existing context processors, provider selection, database schema and legal copy are unchanged. The included story viewer continues to use its original literal `تیم لومرا` reporting/help copy; that text is deliberately outside this task.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` verify exact three bindings, default page and filters, two independent sequential buyer names, Latin/Persian separation and HTML escaping. Tests-only RED SHA `99785d4631e4a16b884ce156ffcc95a42f40f412` was observed failing in GitHub Actions run `39465813470` (0 template bindings vs 3). Final-head CI must independently pass; no claim of full-suite, browser, or deployed behavior is made.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.

## Article Detail Magazine Backlink Persian Brand Identity

The active public article detail template (`templates/articles/article_detail.html`, route `/magazine/<slug>/`) uses existing `deployment_brand.display_name_fa` context in **exactly one** website-chrome slot: the link back to the magazine home (`مجله <brand>`). `BRAND_DISPLAY_NAME_FA` configures the independent Persian display name and the default remains **لومرا**; a Latin-only `BRAND_DISPLAY_NAME` override does not change the Persian label. Standard Django autoescaping remains enabled for this text.

**Deliberate isolation:** The article's `effective_seo_title`, `effective_seo_description`, title, author, category, body and stored data, canonical URL, structured-data snippets, article card, read-time/related services, gallery/FAQ, links and routes, and `ContentReport` form/JS are unchanged. Both existing moderation text literals (`تبلیغ خارج از لومرا`, `گزارش ثبت شد و تیم لومرا آن را بررسی می‌کند.`) are **intentionally preserved** and remain separately scoped for moderation/legal review. No provider/locale inference, new settings, context processors, migrations, browser behavior, or deployment changes are introduced.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` exercise the default article wrapper, one shared brand slot, sequential independent buyer brands, Latin/Persian separation, HTML escaping, unchanged SEO metadata and report message, and article/magazine routes. The tests-only RED commit `cc45bfd614f0a4b0ae2ce7b883bc9204920d0ca4` failed as expected in GitHub Actions `39467728035` (0 brand slots instead of 1). A separately checked successful final-head CI run is required to establish GREEN; complete test suite, database and browser QA are not implied.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.

## Support Success Page Latin Browser Title Identity

The successful support-submission confirmation page at `/main/success/` (`templates/main/support/success.html`) uses the existing `deployment_brand.display_name` template context in **exactly one Latin identity slot**: the browser title (`درخواست ثبت شد | <brand>`). `BRAND_DISPLAY_NAME` controls that independent title segment; the default remains **Loomera**. Changing only Persian `BRAND_DISPLAY_NAME_FA` does not infer a new Latin name. Django autoescaping is retained.

**Deliberate operational boundary:** The visible Persian response promise (`در صورت نیاز، پاسخ تیم لومرا در همان بخش نمایش داده می‌شود.`) is unchanged in this phase and is not renamed implicitly to the deployment display name. The success heading, support-submission and tracking links (`main:contact`, `accounts:login`, `accounts:customer_panel`), their destinations and permission branches, view functions, navigation and layout, other support pages, existing brand settings/context processors, persisted tickets, notification delivery and legal text remain unchanged. No new settings, database migration, provider/locale behavior or deployment operations are introduced.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` check one Latin slot, default compatibility and preserved support actions, two sequential independent buyer names, Latin/Persian name separation and HTML escaping. RED tests-only SHA `cb3fc69f2a026e72c4b9a9930f0497a518fd1c00` failed as expected in GitHub Actions `39469505730` while the title was still static. A separately observed successful CI on the final implementation head is required for GREEN; the targeted checks do not certify full-suite, browser or live production behavior.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.

## HTTP 400 Page Deployment Brand Metadata

The public HTTP 400 error template (`templates/400.html`) now uses the existing request-scoped `deployment_brand` context in **exactly two metadata identity slots**: the browser title `درخواست نامعتبر | <deployment_brand.display_name>` (Latin label from `BRAND_DISPLAY_NAME`) and the meta description `درخواست ارسال‌شده برای <deployment_brand.display_name_fa> معتبر نبود.` (Persian label from `BRAND_DISPLAY_NAME_FA`). Defaults remain **Loomera** and **لومرا**. The settings are independent: changing one name does not infer or override the other. Django autoescaping protects both placements.

**Strict failure-handling boundary:** `apps.main.views.bad_request_view` still renders `400.html` with HTTP status **400**. The visible `خطای ۴۰۰` indicator, guidance about technical detail confidentiality, page content, root and browser-back actions, base layout, HTML structure, route handlers, security disclosures and statuses are unchanged. Other error pages (403, 404, 500), providers, settings, context processors, database schema and deployment behavior are outside this change.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` cover the exact two shared brand context slots, unchanged HTTP 400 handler source and navigation, default appearance, two sequential independent deployment brands, separate Latin/Persian overrides, and escaped markup. RED tests-only commit `e7425949fe468d2600742f342081881d7af5f42a` was observed failing on unchanged title in GitHub Actions `39471691744`. The final head requires a separate successful native GitHub CI result; these targeted checks do not certify a full test suite, browser QA or production error handling.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.

## HTTP 404 Page Deployment Brand Identity

The public HTTP 404 error template (`templates/404.html`) now uses the existing `deployment_brand` context for **exactly three** brand identity references: the Latin browser-title suffix (`صفحه پیدا نشد | <brand>`) from `deployment_brand.display_name`, the Persian meta description from `deployment_brand.display_name_fa`, and the visible Persian main heading (`این صفحه در <brand> پیدا نشد`) from the same Persian value. Existing defaults remain **Loomera** and **لومرا**. `BRAND_DISPLAY_NAME` and `BRAND_DISPLAY_NAME_FA` are independent, and Django autoescaping remains on for all three placements.

The surrounding public-error behavior is outside this task: the existing 404 error handling/status is not altered or independently HTTP-tested, and the `خطای ۴۰۴` badge, `کد خطا: 404`, original navigation help, home (`/`) and `search:search_page` links and destinations, layout, template inheritance, other 400/403/500 error templates, SEO routes, settings, providers, accessors, migrations and deployment operations remain unchanged.

Five database-free tests in `apps/main/test_production_settings_hygiene.py` verify exactly three brand slots, unchanged default display and links, sequential buyer independence, separate Latin/Persian overrides and HTML escaping. Tests-only RED commit `8aa02e8ee1382b008e785d4882b3995c72f81423` failed as expected in GitHub Actions `39473521490` (zero existing binding slots). A successful native GitHub CI run on the final head is required for GREEN; this task does not certify full-suite, real HTTP 404, browser or production behavior.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.


## HTTP 403 Page Deployment Brand Identity

The public HTTP 403 template (`templates/403.html`) uses the existing request-scoped `deployment_brand` config in **exactly three display-identity slots**: the Latin browser-title suffix (`دسترسی مجاز نیست | <brand>`) reads `deployment_brand.display_name`, while the Persian meta description and the non-CSRF access-denied guidance (`به بخش دیگری از <brand> برگردید`) read `deployment_brand.display_name_fa`. Defaults remain **Loomera** and **لومرا**, Latin and Persian settings remain independent, and Django autoescaping protects all three placements.

**Security and operational boundary:** Both `is_csrf_failure` rendering branches remain intact. The expired-request heading and refresh guidance for CSRF failures, the access-denied heading, technical-error confidentiality guidance, the HTTP 403 indicator, root/home and `accounts:login` links, error status/handling, markup/layout, authentication and authorization logic, context processors, settings, providers, migrations, other error pages and deployment behavior are unchanged. No live HTTP 403 or CSRF-handling claim is made from template-render tests.

Five database-free regressions in `apps/main/test_production_settings_hygiene.py` cover the exact three slots and both security branches, original default and navigation behavior, sequential independent deployments, separate Latin/Persian overrides and HTML escaping. Tests-only RED commit `c2e307bafe0e49a52cdf865e2724670e50ea9d8f` failed as expected in GitHub Actions `39478302847` (the fixed Latin title did not vary). Successful GitHub CI on the final implementation head is required before merge; these checks do not certify the full test suite, browser QA, HTTP-level behavior or production.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.

## HTTP 500 Page Deployment Brand Identity and Emergency Recovery

The production Django 5.2 HTTP 500 route now registers `handler500 = "apps.main.views.server_error_view"` in `loomera/urls.py`, because the framework's default 500 handler passes an empty template context and cannot provide the deployment brand to `500.html`. The dedicated handler reads the existing `get_deployment_brand_config()` accessor and passes **only** `display_name` and `display_name_fa` into the template using `get_template("500.html").render(context)` **without a request**. It never invokes request context processors or reads database, cache, payments or notifications for its own branding work.

Exactly two public `templates/500.html` metadata identity slots use the independent deployment settings: `BRAND_DISPLAY_NAME` supplies the Latin browser-title suffix (`اختلال موقت | <name>`) and `BRAND_DISPLAY_NAME_FA` supplies the Persian meta description (`در حال حاضر اختلال موقتی در <name> رخ داده است.`). Defaults remain **Loomera** and **لومرا**; blank, missing or non-string labels individually fall back to those defaults, and accessor exceptions do not escape the handler. HTML autoescaping protects both metadata slots. The visible heading, 500 error badge, payment/booking warnings (including avoiding duplicate payments), home/customer-panel/support links, layout and other error handlers remain unchanged.

If `500.html` cannot be loaded or rendered, the handler returns HTTP **500** with `Content-Type: text/plain; charset=utf-8` and precisely `در حال حاضر اختلال موقتی رخ داده است. لطفاً کمی بعد دوباره تلاش کنید.`. No exception details, request secrets or tracebacks are included. This handler applies to errors routed through Django with `DEBUG=False`; it does not claim to cover upstream proxy or infrastructure 500/502/503 pages, or failures before Django can load its URL handler.

Database-free regression coverage in `apps/main/test_production_settings_hygiene.py` includes the five original metadata tests, actual HTTPS client errors with `DEBUG=False`, unchanged navigation/payment guidance, independent deployment names and HTML escaping, a context-processor failure isolation test, and accessor/invalid-label/template failure paths. The initial metadata tests-only RED SHA `f46258a882fd0dba8e3479cb796ba6364a67b126` is recorded in GitHub Actions `39480554899`; the handler registration RED in `39489884279`; and emergency fallback RED in `39491180359`. Require a separate successful native GitHub CI run on the final implementation head; these checks do not certify the full test suite, browser/infrastructure handling or production deployment.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.


## Support Confirmation Persian Team Brand Follow-up

After the earlier support-success browser-title task, the confirmation at `/main/success/` now uses the existing shared template `deployment_brand.display_name_fa` in exactly **one visible Persian identity slot**: `در صورت نیاز، پاسخ تیم <brand> در همان بخش نمایش داده می‌شود.`. This deliberately supersedes the earlier title-only task's preservation of the fixed `تیم لومرا` wording; **the promise, workflow and surrounding sentence stay the same**. The existing Latin title independently continues using `deployment_brand.display_name`. The default deployment still renders `Loomera` and `لومرا` exactly as before.

`BRAND_DISPLAY_NAME_FA` and `BRAND_DISPLAY_NAME` remain independently configured through the existing brand snapshot and context processor; neither is inferred from the other or read directly from a request. Django's normal template autoescaping protects user-configured label text. This follow-up adds no settings, accessor, context processor, caching, models or migrations.

The success view, submission/tracking semantics, support-team response promise, authorized/anonymous return-link branches, `main:contact` and `accounts:login`/`accounts:customer_panel` URL references, static assets, CSS, CSRF, forms, authentication, notifications, payment and provider behavior are unchanged. The six database-free `SupportSuccessTitleDeploymentBrandTests` cover exact template bindings, unchanged default text/actions, sequential independent deployments, Latin/Persian separation, and HTML escaping. A tests-only RED CI result does not establish GREEN; successful final-head CI is required. No live browser, full-suite or production deployment claim is made.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.

## Social Login Information Page Deployment Brand Identity

The active public `accounts:social_login_info` TemplateView (`/accounts/social-login-info/`) renders `templates/accounts/social_login_info.html` with exactly **two presentation-only deployment identity slots**: the badge `روش‌های ورود <brand>` uses `deployment_brand.display_name` (configured independently through `BRAND_DISPLAY_NAME`), while the primary-login explanation `در حال حاضر ورود اصلی <brand> با شماره موبایل و رمز عبور انجام می‌شود` uses `deployment_brand.display_name_fa` (`BRAND_DISPLAY_NAME_FA`). The default appearance is still **Loomera** and **لومرا**. Neither language is inferred from the other, and Django template autoescaping applies to both.

**Deliberate behavior boundary:** The social-login status remains *disabled*, and the existing explanation that mobile number and password are the primary login method is retained. The text about Google, Apple and other providers remains unchanged. Customer-settings, change-password and support links and route names stay unchanged. This task does not enable OAuth or social login, alter authentication or permissions, change routing, implement a provider, introduce settings or migrations, change account data, or edit JavaScript/CSS and legal terms.

Five database-free regression tests in `apps/main/test_production_settings_hygiene.py` check exact template slots and stable link names, default content, two sequential independent buyer deployments, Latin-only versus Persian-only setting overrides, HTML escaping and unchanged disabled-status guidance. The tests-only RED SHA `fe42d7084de184983a7f5297e8d96efdd9a5c46a` failed as expected in GitHub Actions `39544993936` (zero dynamic brand slots in the original template). A separate final-head GREEN CI run is mandatory before Merge; targeted hygiene coverage does not certify full-suite, browser or production deployment behavior.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** This task does not authorize deployment.

## Recovery Code Verification Latin Identity Labels

The password-recovery verification template (`templates/accounts/verify_code.html`) now uses the existing `deployment_brand.display_name` in exactly **two Latin identity slots**: the image's accessible `alt` label and the visible `امنیت حساب <brand>` security badge. `BRAND_DISPLAY_NAME` is independent of `BRAND_DISPLAY_NAME_FA`, and defaults to **Loomera**. Django autoescaping protects both normal text and the HTML attribute.

**Deliberately preserved asset boundary:** the static `branding/logo/loomera-logo-horizontal-transparent.png` image, its layout, the recovery verification form, CSRF, hidden/visible form fields, input enhancements, URLs, authentication state, token validation, password-change behavior, and all other account pages remain unchanged. Visual logo artwork may still reflect Loomera and requires a separately scoped asset branding task; relabeling accessible text does not replace image content.

Five database-free tests in `apps/main/test_production_settings_hygiene.py` cover exactly two bindings, unchanged default behavior, sequential buyer isolation, independent Persian override, and HTML escaping. The test-only RED commit `df56beebe22e08835928cd2c31e337948e5704ee` failed in GitHub Actions run `39551279718` with zero bindings instead of two. GREEN CI on the final head must be confirmed before merge; browser or full-suite coverage is not claimed.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment is authorized.


## Active Role Attachment Page — Persian Browser Title

The active `accounts:add_role` view renders `templates/accounts/add_role.html` for the stylist and manager role-attachment routes. Its browser title is `افزودن نقش | {{ deployment_brand.display_name_fa }}`, using the existing deployment-wide `BRAND_DISPLAY_NAME_FA` configuration. The default stays `افزودن نقش | لومرا`; `BRAND_DISPLAY_NAME` remains independent. Django's template autoescaping protects the title from HTML injection.

**Preserved behavior:** role attachment and permissions, accepted `kind` values, POST and CSRF behavior, expert input/validation, routes, form copy, role data and redirects are unchanged. No new brand settings, migrations, authentication logic, assets, translations, or deployment are part of this task.

Five database-free regression tests cover the exact title binding, default buyer behavior for both role kinds, sequential buyer isolation, Latin-only settings, and HTML escaping. The test-only RED commit `de55b38d62c553d3e3638040c35f4713fdc67a97` failed as expected in [GitHub Actions #39640433473](https://github.com/alireza-anari/loomera-global/actions/runs/39640433473) with zero-versus-one binding. Final-head GREEN GitHub CI and independent scope review are required before merge. Full-suite, browser, and deployment testing are not claimed.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment authorized.


## Customer Settings Header — Deployment Persian Brand

The active authenticated `accounts:customer_settings` route renders `templates/accounts/customer_settings.html`. Its visible header description is `اطلاعات شخصی، امنیت و روش‌های ارتباط با {{ deployment_brand.display_name_fa }}`, resolved from the existing deployment-level `BRAND_DISPLAY_NAME_FA` setting. The default output remains `اطلاعات شخصی، امنیت و روش‌های ارتباط با لومرا`, independent of the Latin `BRAND_DISPLAY_NAME` value. Django autoescaping protects untrusted Persian display names.

**Compatibility boundary:** Only this one visible Persian label is replaced. The page title, role/authentication guards, account data/address count, navigation links to profile, addresses, password, communications, legal/privacy and deletion, and all related models, views, routes, forms, scripts, and security policies are unchanged. No new settings, assets or migrations were introduced.

Five database-free regression tests in `apps/main/test_production_settings_hygiene.py` check exactly one binding, default identity and navigation, two sequential buyer identities, Latin-only override, and HTML escaping. The test-only RED SHA `c7b69a8899d04b72b77b9445f63ce63c69777d3a` failed as expected in [GitHub Actions #39642741256](https://github.com/alireza-anari/loomera-global/actions/runs/39642741256) with zero rather than one dynamic identity slot. Require GREEN CI on the final PR head and independent structural review before Squash Merge. Full-suite, browser or production tests are not claimed.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment authorized.


## Customer Communications Settings — Persian Brand Identity in Visible Copy

The active `accounts:customer_communication_settings` route uses `templates/accounts/customer_communication_settings.html`. Eight visible Persian identity labels — Bale and Telegram appointment guidance, independent in-app notification explanation, marketing section/email/Bale descriptions, and both messaging connection headings — now resolve from the existing request-scoped `deployment_brand.display_name_fa`. This is an independent `BRAND_DISPLAY_NAME_FA` display setting; the Latin `BRAND_DISPLAY_NAME` does not supply or infer the Persian name. The Loomera default renders the same original Persian text in all eight locations, with HTML autoescaping for configured names.

**Strict behavior boundary:** Exactly eight static copy substitutions in one template. Message-channel availability, connection status, actual bot identities/usernames, provider delivery, role-specific notification preference storage, operational versus marketing opt-ins, checkbox names and values, POST and CSRF, connect/disconnect destinations, permission checks, scripts, styling, models, migrations, and authentication are not changed. Changing a displayed brand label does *not* rename/configure a Bale or Telegram bot; that needs its own independent provider/asset configuration and verification work.

Five database-free regression tests in `apps/main/test_production_settings_hygiene.py` cover eight exact source bindings, original channel/switch routes and identifiers, default display, two sequential buyer identities without leakage, independent Latin override, and HTML escaping. RED-only commit `9e809604f04aaa8ce15e993fdbbc291271b0c38f` failed on fixed copy in [Actions #39665191984](https://github.com/alireza-anari/loomera-global/actions/runs/39665191984). Final-head GREEN CI and scope review are mandatory before Squash Merge. This targeted CI is not full-suite, live provider, browser or production validation.

**Phase 2 NOT COMPLETE. Phase 3 BLOCKED.** No deployment authorized.
