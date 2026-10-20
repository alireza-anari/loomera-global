# HTTP 500 Deployment Brand Identity — Design

**Date:** 2026-10-20
**Project:** `alireza-anari/loomera-global` — Phase 2
**Existing PR:** [#50](https://github.com/alireza-anari/loomera-global/pull/50) (`global/phase2-error500-brand-metadata`)
**Base:** `main` at `9e267909a663b330f3fc14dad54bea8dfc1bfb6f`
**Status:** Architecture design for user review; no production implementation authorized by this document alone.

## 1. Intent and success criteria

Make the actual production HTTP 500 page display the deployment-specific independent Latin and Persian brand names in two existing metadata slots, while keeping HTTP 500 recovery reliable even when ordinary request rendering fails. The default appearance remains `Loomera` / `لومرا`. No customer-facing recovery guidance, payment warning, navigation or business behavior changes.

Acceptance requires: (a) the configured names appear in the browser title and Persian meta description on a real HTTP 500 response when `DEBUG=False`; (b) a failed brand lookup or broken 500 template still yields a safe status-500 response without exposing the original exception; (c) the existing payment/booking caution and links stay intact; (d) untrusted brand labels are escaped; (e) RED → GREEN GitHub CI, independent code review, conditional squash merge and post-merge CI success.

## 2. Current behavior and root cause

The default Django 5.2 `django.views.defaults.server_error` renders `500.html` with an empty template `Context`, so neither template context processors nor a RequestContext provide `deployment_brand`. See [Django 5.2 built-in error views](https://docs.djangoproject.com/en/5.2/ref/views/#the-500-server-error-view). This differs from the 403/404 rendering paths. `loomera/urls.py` currently registers only `handler400` and `handler403`; it has no `handler500`.

The draft PR #50 currently contains **tests only**, commit `f46258a882fd0dba8e3479cb796ba6364a67b126`. Native GitHub RED [run 39480554899](https://github.com/alireza-anari/loomera-global/actions/runs/39480554899) failed as expected while the Latin title was fixed. The draft tests manually provide a brand context, so they do not yet protect the actual HTTP 500 path; the expanded work must close that gap before implementation can be considered complete.

## 3. Approaches and decision

1. **Selected: 500-specific handler with minimal explicit context.** Declare `handler500` in the root URLconf. Call the existing deployment-brand accessor once, expose only the two needed display names through a small context object, and render the template without a request object. This meets runtime branding requirements while avoiding context processors on the emergency path.
2. **Rejected: template tag reads settings during 500 rendering.** This hides configuration lookups inside emergency template rendering, couples the template to a new tag and makes failure recovery harder to isolate and verify.
3. **Deferred alternative: retain static 500 brand names.** This retains current reliability but does not satisfy Phase 2 deployment-brand identity.

## 4. Component and data-flow design

- `loomera/urls.py`: register `handler500 = 'apps.main.views.server_error_view'` alongside the existing error handlers. The existing 400, 403 and CSRF routing stays untouched.
- `apps/main/views.py`: define a synchronous `server_error_view(request)` that always creates an `HttpResponseServerError` (HTTP 500). It invokes `loomera.branding.config.get_deployment_brand_config()` but uses only its `display_name` and `display_name_fa`. It does **not** access the database, exception message, session, authentication or per-request context processors.
- Construct minimal `deployment_brand` context exposing only `display_name` and `display_name_fa` (e.g. a `SimpleNamespace`). Use `django.template.loader.get_template('500.html').render(context)` **without a request**; deliberately avoid `render(request, ...)` and `render_to_string(..., request=request)`, both of which would activate context processors that may have caused the original 500.
- `templates/500.html`: replace **exactly two** hard-coded identity references: the Latin title suffix `Loomera` with `{{ deployment_brand.display_name }}` and Persian meta description name `لومرا` with `{{ deployment_brand.display_name_fa }}`. Keep autoescaping enabled. Other occurrences of `loomera` in CSS class names are styling tokens, not brand-display slots, and stay intact.
- On successful lookup, each deployment independently controls its Latin and Persian display name through existing settings. No new configuration or global cache is introduced; two sequential deployments in the same test process must not leak values.

## 5. Emergency fallbacks and security

- If the deployment-brand accessor raises an exception or returns a missing/empty required display label, the handler substitutes the existing safe defaults: Latin `Loomera`, Persian `لومرا`. Fallback is specific to this emergency handler and does not mutate global settings.
- If loading or rendering `500.html` fails, return a minimal static HTTP 500 response (safe Persian service-unavailable guidance, no traceback, paths, credentials, request details or exception text). Do not re-enter ordinary template rendering or recursively invoke the handler.
- Do not call template context processors, notifications, payment services, providers, network endpoints or database code to create an emergency response. The handler must not alter security exception classification or turn a 500 into a 200/302.
- Django template autoescaping must prevent HTML injection in both metadata slots. No use of `mark_safe`, global state or request-sourced branding is allowed.
- As with Django's standard 500 view, this applies to errors handled by Django with `DEBUG=False`; it does not claim to cover infrastructure-generated 500/502/503 responses.

## 6. Verification design

Use test-driven development on the existing draft PR:

1. Preserve the five existing database-free metadata regressions (exact slots, original default/payment guidance, sequential independent deployments, separate Latin/Persian overrides, autoescaping). The tests-only RED baseline is already recorded.
2. Add failing handler and URLconf registration tests **before** implementing the handler: resolve `handler500`, force an actual Django error response with `DEBUG=False` via a controlled test-only URLconf/raising view and `Client(raise_request_exception=False)`, and assert status 500 plus branded HTML.
3. Test handler resilience with a simulated brand-accessor failure and an isolated template-rendering failure; both must return status 500 with non-sensitive fallback content. Verify context processors are not required by the handler even if they would raise.
4. Test custom-brand HTML escaping and independent overrides in the actual handler response. Confirm home, customer panel and support links plus payment and booking cautions are unchanged in the ordinary 500 template rendering path.
5. Run natural GitHub CI on final SHA (Django checks, migration drift, deployment guards, production-settings hygiene); record test counts and any skipped checks accurately. Full-suite, browser, live infrastructure and deployment results must not be inferred.

## 7. File scope and review gates

Expected production/test files: `loomera/urls.py`, `apps/main/views.py`, `templates/500.html`, `apps/main/test_production_settings_hygiene.py`, `docs/globalization/CONFIGURATION.md`. This approved design document is an additional file in the same PR. No changes to database migrations, payment flows, context processors, other error templates, providers, branding settings or source repository `alireza-anari/loomera`.

Before any squash merge: confirm actual 500-path tests and template-render tests GREEN on the final SHA; independently review every changed file; verify exact scope and PR mergeability. After merge, verify `main` tree and native push-triggered CI. Do not deploy. **Phase 2 NOT COMPLETE; Phase 3 BLOCKED.**
