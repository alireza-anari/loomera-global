# Phase 7.31 — opt-in dedicated OTP cache role and redacted runtime Redis inventory

**Backward-compatible runtime seam; opt-in only. No Production credentials, deployment, OTP delivery, or release approval.**

Baseline `main`: `ff8ec57bd595f4133c2502bbf8bd1da853caa253`. Phase 7.30 post-merge CI run `43631196441` completed all four jobs successfully on that exact main SHA.

## Runtime configuration gap found

The live API OTP module imports Django's global `cache` proxy and uses it for challenge records, resend cooldowns, and rate counters. The default cache is configured from `CACHE_LOCATION`. `CELERY_BROKER_URL` also defaults to `CACHE_LOCATION`, and `CELERY_RESULT_BACKEND` defaults to the broker URL. The deployment preflight writes its own sentinel through the same default cache. Therefore the synthetic Phase 7.28–7.30 Redis roles were not yet represented as separate runtime identities.

## Bounded implementation

### Optional OTP cache alias

New settings:

- `LOOMERA_API_AUTH_OTP_CACHE_LOCATION`: optional Redis URL for a dedicated OTP cache.
- `LOOMERA_API_AUTH_OTP_CACHE_ALIAS`: `default` or `otp`; defaults to `otp` when a dedicated location is provided, otherwise remains `default`.

When a dedicated location is configured, settings create a Django `otp` cache using `django-redis`. Selecting `otp` without a location, selecting an unknown alias, or providing a malformed/non-Redis location fails settings import with a generic configuration error. No URL, username or password is printed.

The live API OTP helpers now resolve their cache lazily through the configured alias for GET/SET/DELETE operations. The existing default cache proxy is retained when the alias is `default`, preserving current behavior and existing patch/test contracts. **No default is silently switched and no Production environment variable is changed by this PR.**

### Deployment preflight

When the alias remains `default`, infrastructure preflight emits a warning that OTP still shares the general cache. When `otp` is explicitly selected, preflight performs one short-lived random-key SET/GET/DELETE against that alias, verifies the round trip, and reports only operation status. Cleanup is attempted in a `finally` block; the marker also has a 30-second TTL. It does not inspect or print credentials.

### Read-only role audit

Run:

```sh
python manage.py audit_phase7_otp_redis_roles --json
```

The command reads Django settings only; it opens **no Redis or database connections**. It reports role labels for the default cache, API OTP, infrastructure preflight, Celery broker and Celery result backend. It emits no URL, host, username or password. Endpoint/principal group labels allow operators to see sharing without disclosing identities. Redis logical DB numbers are intentionally ignored when comparing principal identity because selecting DB 1 versus DB 9 does not create an ACL boundary.

The report always leaves Production blocked: a settings-only inventory cannot read server ACLs, enumerate all nodes/network routes, prove privileged credential revocation or terminate authenticated stale sockets.

## Required operator-side configuration before enabling the alias

Provision and independently verify a dedicated Redis ACL user for OTP on the target service, with TLS, a non-default named user, a strong secret, only the required OTP key patterns and commands, and no administrative or scripting privileges unless a separately reviewed protocol proves they are necessary. Configure the OTP cache location with `rediss://` and set `LOOMERA_API_AUTH_OTP_CACHE_ALIAS=otp` in **staging first**, after verifying the service's ACL semantics and key-prefix behavior. A different logical DB on the same shared user is not a substitute.

The same inventory must separately account for Celery broker/result principals when Celery is enabled. Do not reuse the OTP credential for cache, Celery, deployment automation or administrators. Network policy must restrict Redis to approved application/worker sources; all old sockets, alternate endpoints, replicas/masters and privileged paths need independent verification.

## Deliberate nonclaims

- This phase does **not** change OTP issue/verify semantics, GET/SET/DELETE atomicity, retry behavior, account/session handoff or external SMS delivery.
- The SQL-first synthetic outbox is still not connected to the live OTP path.
- An OTP cache alias is a routing seam, not proof that the Redis ACL or network boundary is mandatory.
- The role audit is configuration evidence only, not server-side or runtime ingress evidence.
- No credentials were provisioned or rotated; no staging or Production deployment was performed.

**Production release remains BLOCKED.** Next work must provision and verify the actual service-side ACL/network boundary, then exercise the opt-in alias against a disposable/staging Redis service before any production cutover or OTP algorithm migration.
