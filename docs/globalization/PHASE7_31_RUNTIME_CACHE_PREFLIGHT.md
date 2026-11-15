# Phase 7.31 — dedicated OTP cache role, runtime Redis inventory and safe preflight

**Backward-compatible runtime seam and readiness hardening. Dedicated OTP Redis is opt-in. No Production credentials, deployment, OTP delivery or release approval.**

Baseline `main` at PR review: `ab70c12900e952ad907b6ee319037ffd4850dda1`. The repository's accompanying Phase 7.31 role map is documented in `PHASE7_31_REDIS_RUNTIME_ROLES.md`.

## Findings addressed

1. Production WSGI/ASGI and `manage.py` default to `loomera.settings.production`, but the base setting defaulted `LOOMERA_ENVIRONMENT` to `local`. A missing environment variable could make deployed checks treat a production settings module as local.
2. Both `infrastructure_preflight_check` and `pre_beta_check` wrote to predictable shared cache keys with `cache.set`, risking overwrite of an application key.
3. Live API OTP used Django's global cache proxy for challenge records, resend cooldowns and rate counters. General cache, OTP, infrastructure probes and Celery broker/result could share one Redis principal.
4. Deployed cache validation only rejected localhost/LocMem and did not require an authenticated Redis URL or report TLS / named ACL posture.

## Changes

### Runtime identity and safe preflight

- `loomera.settings.production` defaults `LOOMERA_ENVIRONMENT=production`; staging explicitly sets `staging`; CI explicitly sets `ci`.
- Liara staging and production workflows set their respective runtime identity before deployment. No workflow was dispatched.
- Shared cache assessment requires the exact Django-Redis backend for deployed environments and checks Redis URL scheme, remote host, port, database path, password and explicit TLS certificate-verification downgrades. Error/warning codes never contain URLs or credentials.
- Plain `redis://` and absent/default ACL usernames are warnings, not proof of TLS or least privilege. The check cannot inspect the live ACL command allowlist.
- Both readiness commands use a cryptographically random per-run key and marker with cache `add` (NX semantics), read only that key, and rely on a 30-second TTL. They no longer overwrite or delete predictable shared keys.
- Enabled Celery broker URLs receive the same deployed Redis URL assessment.

### Optional dedicated OTP cache role

- `LOOMERA_API_AUTH_OTP_CACHE_LOCATION` optionally configures a dedicated OTP Redis URL.
- `LOOMERA_API_AUTH_OTP_CACHE_ALIAS` accepts `default` or `otp`; it defaults to `otp` when a dedicated location is supplied and otherwise remains `default`.
- Selecting `otp` without a location, without `django-redis`, with a non-TLS URL, a default/missing ACL username, no password, invalid URL, disabled certificate verification, or the same Redis principal as the general cache fails settings import with a generic error.
- The dedicated cache uses a separate key prefix. The live API OTP helpers resolve the selected cache lazily. When the alias is `default`, the original global cache proxy is returned, preserving existing behavior and test patch contracts. **No default is silently switched.**
- Infrastructure and pre-beta readiness warn while OTP still shares the general cache; when `otp` is selected, they probe the dedicated alias as well.
- `python manage.py audit_phase7_otp_redis_roles --json` emits a settings-only role map for general cache, OTP, infrastructure preflight, Celery broker and Celery result. It groups endpoints/principals without printing host, username, password or full URLs and opens no Redis or SQL connection. Logical DB numbers are not treated as security boundaries.

## Explicit limits

This phase does **not** provision or rotate Redis credentials, inspect actual Liara environment values, verify server-side ACL commands/key patterns, prove network isolation, enumerate every node/host, revoke privileged or stale TCP writers, or fix the live OTP GET/compare/DELETE race. The dedicated OTP alias remains opt-in and must be exercised against a disposable/staging Redis service only after the service-side ACL and network policy are independently verified. The synthetic SQL-first outbox remains disconnected from live OTP and SMS.

## Release gate remains BLOCKED

Before Production can be considered, the runtime owner must provision and independently verify a dedicated named least-privilege OTP ACL principal with TLS, isolate general cache and Celery broker/result identities, enumerate and fence every Redis ingress including privileged and stale connections, implement reviewed live OTP consume/rate-limit/session semantics and durable external SMS delivery/reconciliation, and complete failover, rollback, privacy, operations and security-owner signoff.

Review the exact PR diff and all four PR-head CI jobs on one immutable SHA. Squash merge only after scope and security review, then verify all four post-merge `main` jobs independently. **Do not deploy.**
