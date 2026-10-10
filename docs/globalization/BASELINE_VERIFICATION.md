# Loomera Global Baseline Verification

## Repository Baseline

- Target repository: `alireza-anari/loomera-global`
- Verified Task 0.2 base SHA: `af6ba97080509bbf499371276e8ca56a68b131e1`
- Verified Task 0.2 base tree: `23c2c15ea018713911f0c6561938f3764109ee3a`
- Source pinned repository: `alireza-anari/loomera`
- Source pinned SHA: `502f3a5a44451fcbe480bfc7a2f0e7a5c3b1f90a`
- Source pinned tree: `ed0de5edb110ce78b05f1e7296ebf362c40adba9`
- Task 0.1 reference: pull request `#1`, merged as `af6ba97080509bbf499371276e8ca56a68b131e1`.
- The preserved Target root `README.md` contains `# loomera-global`; the Source README remains archived at `docs/globalization/SOURCE_README.md`.
- Runtime verification used a local snapshot whose Git tree was verified before testing to equal the exact Target base tree `23c2c15ea018713911f0c6561938f3764109ee3a`.

## Environment

- OS: Linux, x86_64, kernel `6.18.44`.
- Python: `3.13.5`.
- pip: `25.1.1`.
- Node.js: `v22.16.0`.
- npm: `10.9.2`.
- Database configuration: SQLite via `DATABASE_URL=sqlite:///ci.sqlite3`.
- Runtime environment values:
  - `SECRET_KEY=ci-only-secret-key-not-for-runtime`
  - `DATABASE_URL=sqlite:///ci.sqlite3`
  - `DEBUG=False`
  - `ALLOWED_HOSTS=localhost,127.0.0.1`
  - `CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1`
  - `ONLINE_PAYMENT_ENABLED=False`
  - `MESSAGING_ENABLED=False`
  - `MESSAGING_OUTBOUND_ENABLED=False`
  - `BALE_BOT_ENABLED=False`
- No production or staging services, databases, payment providers, or messaging providers were contacted.

## Dependency Installation

### Python

Command:

```bash
python -m pip install -r requirements.txt
```

Result: **failed in the Chat execution environment (exit code 1)**. The runtime had no working DNS/network access to PyPI. pip retried `https://pypi.org/simple/asgiref/` and ultimately reported that it could not obtain `asgiref==3.8.1`. This is recorded as an environment/network limitation, not as a repository dependency-version defect. No dependency files were changed.

### Frontend

Command:

```bash
npm ci
```

Result: **not completed in the Chat execution environment**. With registry access unavailable, the command remained pending until the execution timeout and was terminated; npm did not produce a repository/lockfile inconsistency error. No package files were changed.

## CI Baseline

The existing post-merge GitHub Actions run for Task 0.1 was verified:

- Workflow: `Loomera CI`
- Run ID: `38085584800`
- Event: `push`
- Branch: `main`
- Head SHA: `af6ba97080509bbf499371276e8ca56a68b131e1`
- Status: `completed`
- Conclusion: `success`

The `Fast checks` job completed successfully, including:

- Python dependency installation: success.
- Django system check: success.
- Migration drift check: success.
- Deployment configuration guards: success.
- Production settings hygiene: success.

This successful post-merge CI run is the authoritative evidence that the imported baseline passes the existing CI fast-check coverage in the GitHub-hosted environment.

## Django Checks

The mandatory local commands were invoked against the exact Target base tree. Because Python dependency installation could not complete in the network-isolated Chat environment, Django was unavailable and each command stopped before application checks/tests could execute.

### Django system check

```bash
python manage.py check
```

Result: **failed, exit code 1** before Django startup with `ModuleNotFoundError: No module named 'django'` / `ImportError: Couldn't import Django`.

GitHub CI evidence for the same baseline: **success**.

### Migration drift check

```bash
python manage.py makemigrations --check --dry-run
```

Result: **failed, exit code 1** before Django startup with `ModuleNotFoundError: No module named 'django'`.

GitHub CI evidence for the same baseline: **success**.

### Deployment configuration guards

```bash
python manage.py test apps.main.test_liara_deployment_config --failfast
```

Result: **failed, exit code 1** before test discovery with `ModuleNotFoundError: No module named 'django'`.

GitHub CI evidence for the deployment configuration guard stage: **success**.

### Production settings hygiene and release archive guards

```bash
python manage.py test apps.main.test_production_settings_hygiene apps.main.test_build_release_archive --failfast
```

Result: **failed, exit code 1** before test discovery with `ModuleNotFoundError: No module named 'django'`.

GitHub CI evidence for the production settings hygiene stage: **success**.

## Full Test Suite

Command:

```bash
python manage.py test
```

Result: **failed, exit code 1** before Django test discovery because Django was not installed in the Chat runtime after the dependency-install network failure.

- Tests discovered/run: `0` (test discovery was not reached).
- Pass/fail/error/skip summary: not produced by Django.
- Elapsed test time: not produced by Django.
- First meaningful error: `ModuleNotFoundError: No module named 'django'`.

This result does not establish an inherited application test failure; it establishes only that the full suite could not run in this network-isolated verification environment.

## Frontend Build

Command:

```bash
npm run build
```

Result: **failed, exit code 127**. The build reached the existing `build:css` script and failed with `tailwindcss: not found` because `npm ci` could not complete in the network-isolated Chat environment.

No Tailwind, PostCSS, package, or lockfile configuration was changed.

## Optional Existing Release Check

`python manage.py release_readiness_check --run-tests --skip-operational-dry-runs` was not run because the Python dependency installation had already failed and Django was unavailable. No fake credentials were supplied and no production operation was attempted.

## Known Baseline Issues

### Repository/application baseline issues

- None established by this verification. The existing Task 0.1 post-merge CI fast checks are green.

### Environment/platform limitations

- The Chat runtime had no working external package-registry DNS/network access, so `python -m pip install -r requirements.txt` could not download `asgiref==3.8.1` and exited `1`.
- `npm ci` could not complete because registry access was unavailable and was terminated by the execution timeout.
- Consequently, local Django commands could not import Django and the full Django suite could not reach test discovery.
- Consequently, `npm run build` could not find the local `tailwindcss` executable and exited `127`.

### External-service limitations

- None observed. External production services were intentionally not contacted.

## Baseline Conclusion

- Reproducibly installable in the tested Chat environment: **No — package installation was blocked by the environment's lack of external registry network access.**
- Django-check clean: **Verified green by Task 0.1 post-merge GitHub CI; not independently runnable in the local Chat environment because dependencies could not be installed.**
- Migration-drift clean: **Verified green by Task 0.1 post-merge GitHub CI; not independently runnable locally for the same environment reason.**
- CI green: **Yes — run `38085584800` completed successfully.**
- Full-suite green: **Not established; the suite was invoked but stopped before test discovery because Django was unavailable.**
- Frontend-build green: **Not established; the build was invoked but failed because frontend dependencies could not be installed.**

No Globalization, Internationalization, Translation, Refactoring, Cleanup, Architecture change, dependency upgrade, or inherited behavior fix was performed in Task 0.2.
