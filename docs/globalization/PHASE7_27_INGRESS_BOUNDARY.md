# Phase 7.27 — physical PostGIS × Redis ingress-bypass / ACL fence test

**CI-only, negative proof; no live auth/session/SMS, migration or production change.**

Baseline main: 6e4afcb685ce5d9398c57c1761f4acbc9294dcd7.
Phase 7.26 postmerge CI 42515689736 independently succeeded in all four jobs.

## What Phase 7.27 adds

Phase 7.18 proved that revoking ACL permissions on a promoted Redis node does not reach an old disconnected master. Phase 7.19 proved that dropping one Docker client bridge does not close a raw host-published Redis port. Phase 7.25 proved split-brain issuance and consumption are possible on two masters. Phase 7.26 proved only that **cooperating PostgreSQL test callers** serialize through an isolated SELECT FOR UPDATE and unique-ID ledger.

**New gap tested here: real PostgreSQL and real Redis are both reached from one test.** Even when a PostgreSQL epoch transition rejects a stale owner, a second Redis client with independent credentials can still EVAL the fake test key. PostgreSQL uniqueness does not automatically guard Redis; an acknowledged pre-promotion claim followed by a later Redis effect is a time-of-check/time-of-use gap; and a PostgreSQL rollback does not roll back an already committed Redis effect. This does not require a stubbed Redis client.

## Strict, disposable infrastructure

The existing CI PostGIS service and its Django test_ database host two **test-owned** Phase 7.26 tables. A new shell-only runner starts one distinct Redis 7.4-alpine AOF container with a dedicated volume and exact run-bound name/label, publishing **only 127.0.0.1:6427**, logical **DB15**. Its separate fixture prefix includes a random per-run 32-hex ID; no accounts, phone numbers, codes, customer IPs, cookies, migration records, sessions or SMS artifacts are present. All Redis operations are limited to that fixture namespace. No FLUSH commands, SCAN, wildcard deletion, default CI Redis 6379, or live databases are used.

Both LOOMERA_PHASE727_TEST_REDIS=1 and the Phase 7.26 LOOMERA_PHASE726_TEST_POSTGIS=1, GitHub Actions run ID/attempt and the PostGIS test_ backend are mandatory before operations. The runner requires a free port, creates only the exact named container/volume, and removes only those resources using its EXIT trap. Admin, legacy and promoted Redis ACL credentials are per-run generated synthetically and never printed.

A single disposable Redis server is sufficient for *this cross-store bypass counterexample*. A successful test on this server does **not** establish an old Redis master was fenced after a real network partition. Physical two-master evidence remains the earlier Phase 7.25 **negative** test.

## Actual negative assertions

- Old PostgreSQL epoch/owner claims are denied after one-way promotion; the previously valid stale **Redis raw writer still commits** directly to the independent fixture key.
- A globally conflicting PostgreSQL operation ID does not prevent a raw Redis mutation by the old writer.
- A pre-promotion successful SQL claim followed by promotion cannot authorize a post-promotion Redis effect; the existing separate Redis credential still writes.
- A PostgreSQL transaction rollback can leave a committed Redis side effect. Missing PostgreSQL authority/ledger does not fail-stop an **ungated** Redis client.
- On the disposable Redis server only, the default user is disabled and named test users are prefix-scoped. Explicitly disabling the stale Redis ACL account denies existing and freshly opened stale connections; wrong credentials and out-of-prefix writes fail. A promoted writer and a privileged (fixture-only) administrator still have raw-write access. This is **local ACL evidence**, not an independent authority that can revoke unreachable masters, privileged paths or unknown ingress routes.
- Strict offline inventory has exactly six known synthetic route classes. Even when every enumerated route is denied, it never asserts complete real-world ingress coverage, consensus, a safe retry, or a release grant.

## Release decision

**BLOCKED.** No application code has adopted the PostgreSQL test helper or Redis test ACLs. Real OTP still lacks atomic consume/issue, verified trusted operation provenance, durable cross-store outbox and exactly-once external SMS or account/session handoff. A secure architecture must force every real writer through a reviewed mandatory gate, close alternate raw privileged/host/legacy access, handle network failures and restart, and be signed off by security, ownership and operations before any deployment. This stage is an adversarial test, not a recommended production ACL or live auth implementation.
