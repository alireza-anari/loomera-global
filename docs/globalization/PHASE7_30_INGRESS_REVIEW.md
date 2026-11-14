# Phase 7.30 — isolated read-only SQL/Redis review and explicit Redis ingress inventory

**CI-only, UNWIRED, no remediation, no auto-replay, no Production release approval.**

Pinned baseline `main` `63b92c748881072b951016645caac910cc793cec`. Phase 7.29 postmerge GitHub Actions run `43627366547` independently verified four successful completed jobs. This phase extends the **same disposable** PostGIS/Redis 7.4 fixture and deliberately does not migrate or wire a production worker.

## Bounded incident-review experiment

The new `SyntheticReadOnlyCrossStoreReviewer` accepts only an explicitly authorized CI test fixture ID and a Redis client configured for the existing `phase728_legacy` **GET-only** account at `127.0.0.1:6428`, DB15. It requires all Phase 7.26, 7.28, 7.29 and 7.30 grants; its database access is permitted only for the isolated PostGIS `test_` database.

For exactly one fabricated 32-hex operation ID and fabricated 64-hex fingerprint, review performs:

1. One Redis `GET` of a fixed fixture-scoped key.
2. One PostgreSQL `SELECT` that FULL OUTER JOINs the global operation ledger and outbox and reads the current single lease in that SQL statement; a missing intent, missing ledger or conflicted identity is not silently ignored.
3. A second `GET` of exactly the same Redis key. A changed marker yields a special `redis_changed_during_review` result.

All outcomes require manual security/operations review and authorize **zero** OTP authentication, SMS dispatch, repairs or automatic replays. Matching Redis bytes are not an external delivery receipt. No operation ID, fingerprint, code, Redis credential or customer account appears in the result object. No SQL `UPDATE`, `INSERT` or `DELETE`; no Redis `SET`, `EVAL`, `SCAN`, `KEYS` or `FLUSH`.

**Important weakness:** two `GET` results and one SQL snapshot are **not atomic with each other**. Redis might change and revert between GETs (ABA) or change immediately after the second GET. SQL lease/outbox may also change after the statement. No causal proof or stable forensic timestamp is established. This tool is an incident clue, never an authorization decision or trustworthy consensus observer.

## Explicit known ingress inventory

| Route | Bounded evidence and release decision |
| --- | --- |
| Legacy fixture Redis principal | `+get` but denied `SET` and raw `EVAL` within the isolated test fixture; no evidence about real application credentials |
| Cooperating gateway principal | Has isolated namespace `SET` capability but is constrained only when the *cooperating code* elects to consult PostgreSQL; direct credential use is an unclosed route |
| Fixture administrator | Still has unrestricted fixture ACL command set and can raw `EVAL` after PostgreSQL terminal halt; **open privileged bypass** |
| Already authenticated stale TCP connections | Phase 7.28 demonstrated that ACL `off` alone does not revoke an existing socket until explicit local `CLIENT KILL USER`; cannot claim global revocation |
| Alternate host-published Redis endpoint | Prior Phase 7.19/7.25 physical demonstrations proved old-primary raw writes through alternate host paths; unclosed outside narrowly isolated access |
| Unknown hosts/nodes/credentials/SMS senders | Not enumerated or proved inaccessible; cannot assert mandatory global ingress |

## Physical negative-case coverage

On actual isolated PostGIS/Redis: pending intent with no marker, observed with matching marker, two physically different `inflight` states (lost ACK after genuine write versus failure before write), privileged raw EVAL marker insertion, terminal SQL halt while raw admin still writes, orphan ledger and orphan intent, SQL fingerprint mismatch, owner epoch promotion, missing lease, no operation but existing Redis marker, injected between-GET marker mutation, read-only inspection with stable SQL/Redis bytes, ACL `GET` restriction, revoked reader connection and revoked CI grant. Tests explicitly assert no return value can authorize replay, account/session login, actual SMS or release.

## Production release gate: BLOCKED

A real solution needs an **independently enforced mandatory ingress policy** for every authorized, privileged, stale-TCP and alternate-network route, with principal inventory, network isolation and credential revocation verification on all Redis nodes and hosts; durable audit provenance; independently reviewed reconciliation and incident decision protocol; trusted operation identifiers and idempotent downstream side effects; customer privacy, retention, consent, account/session consistency, migration/reversal plans, disaster recovery and designated security/operations approval. The isolated read-only review does not satisfy any of those requirements.

Review the exact seven-file PR diff, immutable baseline/head and all four complete successful PR-head CI jobs. Only on unchanged SHAs and passing security scope may a SHA-leased squash merge occur, followed by independent four-job postmerge `main` CI verification. **No Production deploy or real OTP/SMS changes.**
