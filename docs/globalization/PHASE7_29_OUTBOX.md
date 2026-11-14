# Phase 7.29 — committed synthetic PostgreSQL outbox before restricted Redis SET NX

**CI-only, UNWIRED experimental protocol. Not a deployable worker, OTP system, SMS queue or security release.**

Pinned baseline main: `913f00826ccb2f54a2e58c9dd093aa0c738e5245`.
Phase 7.28 postmerge GitHub Actions run `43084981845`: all four jobs completed successfully.

## Problem and limited change

Phase 7.28 commits a real Redis SET NX inside an open PostgreSQL transaction. If the outer SQL transaction rolls back or the Redis reply is lost, a Redis marker exists without a committed SQL claim. The new Phase 7.29 **synthetic-only** module models an alternate ordering: commit a PostgreSQL operation ledger plus a durable outbox **intent** in one SQL transaction before touching Redis. The isolated record has `pending`, `inflight`, `observed` and `quarantined` states. No customer details, OTP codes, SMS or account/session records enter this table.

**Arm before effect:** An attempted delivery first commits `pending → inflight` while holding a PostgreSQL lease and row lock. It then starts a separate SQL transaction, re-checks the active lease (so a promotion between arm and write can deny the old writer), holds the lease lock across exactly one real `SET NX` to an isolated Redis key, and records `observed` on a positive acknowledgement or `quarantined` on collision. Duplicate dispatch callers see `inflight`, `observed` or `quarantined` and are denied; there is **no automatic retry** from those states.

This is **at-most-one attempted Redis mutation by cooperating dispatcher calls** with an intentionally stranded state after ambiguity. It is **not** at-least-once delivery, exactly-once SMS, an XA/distributed transaction or global mandatory fencing. A crash after the arm commit but before Redis access leaves an `inflight` intent with **no marker**. Redis SET may succeed before a lost response or SQL rollback, leaving `inflight` with a marker. The read-only inspector shows byte matches or mismatches but neither confirms external delivery nor changes anything.

## Physical evidence and failure cases

- Both SQL ledger and outbox intent roll back together on an outer SQL abort; no Redis side effect occurs during enqueue.
- Only fixture-scoped, localhost `127.0.0.1:6428`, DB15 and the restricted `phase728_gateway` Redis principal can participate, with all Phase 7.26, 7.28 and new 7.29 CI grants simultaneously required.
- Physical success marks `observed` after one Redis SET NX and does not touch Redis on duplicate invocation. Concurrent independent PostgreSQL sessions attempt the same operation; only one may attempt the write.
- Simulated loss of a reply **after actual Redis storage** leaves SQL `inflight`; a separate failure **before storage** likewise strands `inflight` but without a marker. In neither case may the method automatically dispatch again.
- A fixture-only admin can write a foreign marker without consulting PostgreSQL. Redis NX refuses to overwrite it and the outbox becomes `quarantined`; that raw-admin path still disproves complete ingress control.
- Missing SQL intent, stale post-promotion owner, terminal halt, ACL revocation, or revoked grant fail closed. A physical cross-store inspection never tries to repair either database.
- No password, database access or Redis grants are reused from a production system. The existing Phase 7.28 Docker fixture and its strict cleanup are reused. No new service, deployment, migration, production setting, live API endpoint or SMS adapter is changed.

## Operator implications

A **real** implementation would need a privileged-access and network policy covering every writer; authenticated provenance, durable and audited operator quarantine/reconciliation, explicit failure budgets, transactionally committed events and an idempotent downstream delivery contract, retention/privacy and session/account consistency, safe backfills and reversibility, independent security approval and release gating. This rehearsal has **no** authorization to replay a stranded intent even if the inspected Redis marker matches; matching fixture bytes are not a downstream receipt.

## Merge / production gate

Review the bounded seven-file scope, check four completed successful PR-head CI jobs (Fast, Redis, Chromium, PostGIS) on the exact reviewed head SHA, and ensure unchanged baseline. Squash merge only after CI and security-scope review; independently verify the four postmerge `main` jobs. **Production release remains BLOCKED.** No live integration or deployment.
