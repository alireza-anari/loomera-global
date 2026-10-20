# HTTP 500 Deployment Brand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show independently configured deployment brand names in the real HTTP 500 page without making emergency rendering depend on request context processors.

**Architecture:** Register a 500-specific URL handler. It reads the existing deployment brand accessor, passes a minimal two-field object to `500.html` using `get_template(...).render(context)` without a request, and returns HTTP 500. Dedicated fallback logic catches configuration and template failures without leaking exception details.

**Tech Stack:** Python 3.13, Django 5.2.17, Django `SimpleTestCase`/`Client`/`RequestFactory`, native GitHub Actions.

**Spec:** [`docs/superpowers/specs/2026-10-20-http500-deployment-brand-design.md`](../specs/2026-10-20-http500-deployment-brand-design.md)

## Global Constraints

- Work only in `alireza-anari/loomera-global` PR #50 branch `global/phase2-error500-brand-metadata`, based on `9e267909a663b330f3fc14dad54bea8dfc1bfb6f`; source `alireza-anari/loomera` is strictly read-only.
- Current PR has 5 committed metadata regression tests and an approved design spec; tests-first RED SHA `f46258a882fd0dba8e3479cb796ba6364a67b126` was recorded by GitHub Actions `39480554899`.
- Exactly two text replacements in `templates/500.html`, with no altered payment/booking guidance, help text, routes, layout, CSS tokens or other error pages.
- Keep existing settings `BRAND_DISPLAY_NAME` / `BRAND_DISPLAY_NAME_FA` independent and defaults `Loomera` / `لومرا`. Do not add migrations, providers, network calls or deployment actions.
- The emergency handler may read settings via the existing accessor, but must not call a request context processor, ORM, notifications, payments, cache, middleware authorization logic or `render(request, ...)`.
- Production/error-handling changes must be preceded by tests-only RED commits. Use native GitHub CI as the executable environment; never claim that unavailable local, full-suite, browser or live-infrastructure tests passed.
- User pre-authorized squash merge only if final-head checks, independent review, mergeability and scope all pass; verify push-triggered CI on `main` afterward. Phase 2 remains incomplete; Phase 3 remains blocked.

## Review Focus

1. An actual `DEBUG=False` HTTP 500 with custom deployment settings must show both names and keep status 500 — tested in Task 2 by `test_client_real_500_uses_custom_deployment_brand`.
2. A context processor failing while the 500 view runs must not prevent the emergency response — tested in Task 2 by `test_500_handler_does_not_call_brand_asset_context_processor`.
3. A failing brand accessor or blank/invalid labels must produce stable default names without leaking exceptions — tested in Task 3 by `test_500_brand_lookup_failure_uses_safe_defaults` and `test_500_missing_or_blank_names_use_defaults`.
4. A 500 template load/render failure must return the exact safe plain-text response with status 500 — tested in Task 3 by `test_500_template_failure_returns_static_safe_response`.
5. HTML metacharacters in independent brand names must be escaped; original payment and recovery links remain available — covered by Task 1 existing `test_500_title_and_meta_escape_untrusted_brand_labels` plus Task 2 HTTP-level assertions.

---

### Task 1: Bind exactly two HTTP 500 metadata slots

**Files:**
- Modify: `templates/500.html` (two existing metadata lines only)
- Existing tests: `apps/main/test_production_settings_hygiene.py::ServerError500DeploymentBrandTests` (5 tests already committed)

**Interfaces:**
- Consumes: existing template variable `deployment_brand` with `.display_name` and `.display_name_fa`.
- Produces: title `اختلال موقت | <Latin brand>` and meta `در حال حاضر اختلال موقتی در <Persian brand> رخ داده است.` under an explicit template context. This intermediate state is not suitable for a real production 500 until Task 2 lands.

- [ ] **Step 1: Verify preexisting RED:** Check run `39480554899` for an expected assertion failure on the old fixed title; confirm tests-only SHA `f46258a882fd0dba8e3479cb796ba6364a67b126` and no production change at that point.
- [ ] **Step 2: Change the Latin title:** Replace the one fixed `Loomera` suffix in the title block with `{{ deployment_brand.display_name }}`; do not alter literal page-title text.
- [ ] **Step 3: Change Persian meta:** Replace the one fixed `لومرا` in the meta-description block with `{{ deployment_brand.display_name_fa }}`; do not edit visible error or payment text.
- [ ] **Step 4: Structural check:** GitHub diff for `templates/500.html` must show exactly two deleted lines and two added lines; both default labels must still render through the existing tests.
- [ ] **Step 5: Commit and verify GREEN:** Create a template-only commit on PR #50, let GitHub Actions run its `Production settings hygiene` step (`python manage.py test apps.main.test_production_settings_hygiene apps.main.test_build_release_archive --failfast`), and confirm `ServerError500DeploymentBrandTests` plus all current CI guards pass. If GitHub CI is not green, stop and diagnose. Do not merge this incomplete intermediate state.

### Task 2: Handle real Django HTTP 500 with minimal explicit brand context

**Files:**
- Modify: `apps/main/test_production_settings_hygiene.py` (new handler test class and test-only URLconf fixtures)
- Modify: `apps/main/views.py` (new handler)
- Modify: `loomera/urls.py` (single `handler500` registration)

**Interfaces:**
- Consumes: existing `loomera.branding.config.get_deployment_brand_config()`, Django `loader.get_template`, template from Task 1.
- Produces: `apps.main.views.server_error_view(request) -> HttpResponseServerError` and root `handler500 = 'apps.main.views.server_error_view'`. Only `deployment_brand.display_name` and `.display_name_fa` are passed; template renders **without** `request`.

- [ ] **Step 1: Write tests before the handler:** Add `ServerError500HandlerTests(SimpleTestCase)` and a controlled raising view reachable only under a test-specific `ROOT_URLCONF`. Include `test_500_handler_registered_in_root_urlconf` asserting `get_resolver('loomera.urls').resolve_error_handler(500).__module__ == 'apps.main.views'` and function name `server_error_view`.
- [ ] **Step 2: Test actual HTTP dispatch:** With `override_settings(DEBUG=False, BRAND_DISPLAY_NAME='Aurora', BRAND_DISPLAY_NAME_FA='آرورا')`, run `Client(raise_request_exception=False).get('/_test/500/')` through the test-only URLconf whose throwing view raises `RuntimeError('sensitive-internal-secret')`; assert status `500`, title `<title>اختلال موقت | Aurora</title>`, meta `در حال حاضر اختلال موقتی در آرورا رخ داده است.`, and no raw secret. Add a second sequential brand to ensure isolation.
- [ ] **Step 3: Pin no context processor:** Monkeypatch `loomera.branding.context_processors.get_deployment_brand_asset_config` to raise during the direct 500 handler test, and assert a successful status-500 HTML response; a handler using `render(request, ...)` must fail this test.
- [ ] **Step 4: RED on GitHub:** Commit tests only, run native CI on that tests-only SHA, and inspect logs for the missing registered handler, not a setup or syntax error.
- [ ] **Step 5: Minimal implementation:** In `apps/main/views.py`, introduce `server_error_view(request)` using the existing brand accessor and `SimpleNamespace` with two display fields; `get_template('500.html').render({'deployment_brand': brand})` without `request`; return `HttpResponseServerError(html)`. In `loomera/urls.py`, register the handler. Do not render via `django.shortcuts.render()`.
- [ ] **Step 6: GREEN and commit:** Run native GitHub CI against the new head, verify the handler tests plus existing metadata tests are green; commit only the two production files. Do not interpret a green direct-template test as a substitute for HTTP-level behavior.

### Task 3: Error-on-error safeguards, docs and final verification

**Files:**
- Modify: `apps/main/test_production_settings_hygiene.py` (emergency failure tests)
- Modify: `apps/main/views.py` (fallback handling)
- Modify: `docs/globalization/CONFIGURATION.md` (document scoped behavior and exclusions)

**Interfaces:**
- Consumes: `server_error_view(request)` and configured brand accessor from Task 2.
- Produces: status-500 HTML when lookup works; defaults `Loomera` / `لومرا` when it fails or labels are missing/non-string/whitespace; a static plain-text 500 response on template error with exact text `در حال حاضر اختلال موقتی رخ داده است. لطفاً کمی بعد دوباره تلاش کنید.` and `Content-Type: text/plain; charset=utf-8`.

- [ ] **Step 1: Write failure tests first:** Add `test_500_brand_lookup_failure_uses_safe_defaults` (patch the imported getter to raise an exception containing `secret`), `test_500_missing_or_blank_names_use_defaults` (getter returns missing, non-string or whitespace-only labels), and `test_500_template_failure_returns_static_safe_response` (patch `get_template` or the loaded template to raise). Verify status 500, exact fallbacks, and no exception text in any response.
- [ ] **Step 2: RED via native CI:** Commit tests only, observe expected failure(s) in GitHub Actions before changing the handler. Failures due to test setup must be corrected and re-run.
- [ ] **Step 3: Implement fallback paths:** In the handler, sanitize each display label; fallback to defaults for invalid values and getter errors. Catch template-loading/rendering errors and return the exact safe plain-text 500 response. Avoid re-entering template loading or logging unsafe exception bodies.
- [ ] **Step 4: Append documentation:** Describe the actual `DEBUG=False` 500 handler, two independent brand slots, no RequestContext/DB calls, exact fallbacks, existing recovery links and payment warning, and HTTP/error-handling test boundaries in `docs/globalization/CONFIGURATION.md`.
- [ ] **Step 5: GREEN and scope check:** Run GitHub CI on the final SHA; every workflow job (Django system, migrations, deployment guards and production-settings hygiene) must finish `completed/success`. Check that intended changed files are exactly the five files in the spec plus spec and plan documents; the final `500.html` diff is still precisely two substitutions.
- [ ] **Step 6: Independent review:** Ask a read-only reviewer to inspect the diff, actual HTTP/500 failure tests, sensitive information handling, absence of request context processors, PR base/head SHA and docs. Fix any Critical/Important findings and rerun final-head CI.
- [ ] **Step 7: Merge gate:** Update PR #50 description with RED/GREEN run links, exact final SHA and exclusion statements; mark Ready for Review. Re-read `main` and mergeability. Only on success and unchanged PR head perform authorized `squash` merge using `expected_head_sha`.
- [ ] **Step 8: Postmerge verification:** Confirm merged PR, new `main` SHA, equal Git tree between reviewed head and squashed main, then inspect push-triggered GitHub Actions for `completed/success` and report actual test counts. No deployment. Leave Phase 2 open and Phase 3 blocked.

## Execution notes

All repository writes use the connected GitHub API on the already existing PR #50 branch; no alternate environments or dependency installations are required locally. Tests are executed by `.github/workflows/ci.yml` on GitHub; intermediate RED commits are expected and not completion evidence. If an external check or full suite is unavailable, report the gap accurately. The human partner already requested native implementation by this assistant and a conditional safe squash merge, but the written plan must be reviewed before execution.
