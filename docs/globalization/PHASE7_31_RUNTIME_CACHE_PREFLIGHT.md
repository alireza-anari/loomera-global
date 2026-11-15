# Phase 7.31 — deployed environment identity and non-destructive Redis cache preflight

**Runtime guard improvement; no credentials inspected, no live data migration, no OTP/SMS/session wiring, and no deployment executed.**

Baseline `main`: `ff8ec57bd595f4133c2502bbf8bd1da853caa253` (Phase 7.30 merged; four post-merge CI jobs succeeded).

## Findings addressed

1. `manage.py`, WSGI and ASGI default to `loomera.settings.production`, but the base setting defaulted `LOOMERA_ENVIRONMENT` to `local`. As a result, deployed-environment checks could be bypassed by a missing environment variable even when the production settings module was active.
2. Both `infrastructure_preflight_check` and `pre_beta_check` wrote to predictable shared cache keys with `cache.set`. A readiness command could overwrite an existing key in the application cache.
3. Deployed cache checks only rejected localhost and LocMem. They did not require an authenticated remote Redis URL or report whether the URL requested TLS / a named ACL identity.
4. Celery broker readiness similarly checked only presence and localhost.

## Changes

- `loomera.settings.production` now defaults `LOOMERA_ENVIRONMENT=production`; a deployment may explicitly set `staging`. The CI workflow declares `LOOMERA_ENVIRONMENT=ci`.
- Liara staging and production workflows explicitly synchronize their respective runtime identity before deploying. This changes workflow code only; no workflow was dispatched.
- Shared `apps.main.cache_preflight` validates deployed Django cache backend type and Redis URL scheme, host, port, database path, password presence, and explicit TLS certificate-verification downgrades. Error/warning codes never contain the URL, username or password.
- A missing or `default` Redis ACL username is reported as a warning; a plain `redis://` transport is reported as a TLS warning. The checker cannot inspect the live ACL command allowlist or prove network isolation.
- Both readiness commands use a cryptographically random per-run cache key and marker with `add` (SET NX semantics), read back only that key, and let its 30-second TTL expire. They no longer overwrite or delete a predictable shared cache key.
- When Celery is enabled in a deployed environment, its broker URL receives the same remote/authenticated Redis URL assessment.
- Fast CI, the security regression suite and the release-readiness structural suite run the new tests.

## Explicit limits

This phase does **not** inspect Liara environment secrets or connect to a production Redis endpoint. A configured `rediss://` URL does not prove that all application, host, administrator, stale TCP, old-master or alternate-network writers are fenced. A password does not prove a least-privilege ACL. A `redis://` endpoint still receives a warning, not a TLS proof. The live OTP helper still uses Django cache and retains its separate GET/compare/DELETE race; this phase does not migrate it to the synthetic outbox.

## Release gate remains BLOCKED

Before Production can be considered, the runtime owner must provide a named least-privilege ACL principal and verified TLS/private-network posture; enumerate and fence every Redis ingress including privileged and stale connections; isolate cache and broker identities; implement reviewed live OTP consume/rate-limit/session semantics and durable external SMS delivery/reconciliation; complete failover, rollback, privacy, operational and security-owner signoff. The CI fixtures in Phases 7.26–7.30 are evidence of limitations, not a deployable implementation.

Review the exact PR diff and all four PR-head CI jobs on one immutable SHA. Squash merge only after the scope and test review, then verify all four post-merge `main` jobs independently. **Do not deploy.**
