# Phase 7.32 — settings-only Redis role isolation gate

**A conservative, opt-in configuration test. It does not contact any server, alter live OTP or authorize deployment.**

Base: `main` at `297b80e473583267e1494fd50a5a92046931c5e4` (Phase 7.31, postmerge CI success).

## Problem and response

Phase 7.31 emitted a redacted inventory with shared-principal warnings, but it had no machine-actionable failure mode that an operator could use before enabling a dedicated OTP Redis role. Phase 7.32 adds `assess_redis_role_isolation` and an opt-in CLI mode, preserving existing `audit_phase7_otp_redis_roles --json` output.

Run a *settings-only* check in a disposable or staging configuration:

```bash
python manage.py audit_phase7_otp_redis_roles --json --require-isolation
```

`--require-isolation` returns exit 1 and parseable JSON when it detects a violation; exit 0 indicates **only** that the settings pass this limited static gate. The JSON contains an inventory and a `configuration_assessment` with `PASS`/`FAIL`, fixed generic blocking codes, required roles and explicit unsupported claims. No credentials, URLs, usernames, hostnames or Redis traffic are produced by this gate.

The check requires:
- `LOOMERA_API_AUTH_OTP_CACHE_ALIAS=otp`, backed by an existing named and remote `rediss://` principal distinct from the general cache.
- General and OTP roles to each use a valid, authenticated Redis URL with TLS and non-default named ACL user.
- When Celery is enabled, broker and result roles to have valid, authenticated TLS Redis URLs and distinct named principals from one another and from both cache roles.
- Distinct endpoint+ACL username identities. Different logical DBs or passwords on the **same endpoint and ACL user** do not count as isolation.
- Rejection of explicit TLS certificate verification downgrade via the same shared Redis URL assessor used by runtime preflight.

Celery-disabled configurations do not require broker or result credentials. The gate never enforces these requirements on application startup or changes default OTP traffic; operators must explicitly request it.

## What a PASS does *not* establish

Endpoint names can resolve to the same cluster, and different ACL users can have overlapping key/command grants. This check cannot verify actual TLS negotiation/trust stores, live ACL rules, network/egress allowlists, stale sockets, alternate ingress, DNS aliases, external SMS receipts, cross-store recovery, or the live OTP GET/compare/DELETE atomicity gap. It performs no Redis/SQL calls. It is **not** a production security sign-off.

CI covers the gate with synthetic role settings, negative cases (missing dedicated role, plaintext Redis, default ACL user, missing password, certificate downgrade, shared identity despite DB/password change, non-Redis result backend), command failure/JSON/redaction, disabled-Celery behavior and explicit no-release flags.

**Production release remains BLOCKED.** Physical isolated Redis ACL/ingress testing and reviewed live OTP atomic consume, SMS outbox, account/session recovery, failover and operations signoff are still required. No Liara workflow was dispatched, no production credentials were accessed, no live deployment was performed.
