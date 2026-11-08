# Phase 7.26 — test-only PostgreSQL write authority and operation uniqueness

**Non-production experiment.** Baseline main: d49a9bb92b1ff1ff0d4fe9786731dfaa1dbaa48b. Independently confirmed Phase 7.25 postmerge GitHub CI: run 42453506211, all four jobs successful.

## Motivation

Phase 7.25 proved that two Redis masters can each accept the same synthetic OTP operation ID and even consume a replicated fake challenge independently. Local Redis WATCH transactions, ledgers, WAIT 1 and AOF replication do not yield global idempotency. Physical client isolation did not stop a privileged host-side raw Redis writer.

This experiment narrows the next question: can a **single independently transactional PostgreSQL authority** serialize *cooperating synthetic callers* across two candidate writer identities? The answer is testable at a fixed PostGIS CI fixture, without touching live accounts or claiming production correctness.

## Fixture and exact boundaries

- Runs only in GitHub Actions with explicit LOOMERA_PHASE726_TEST_POSTGIS=1, run ID and attempt, PostgreSQL vendor, PostGIS backend and an actual Django test_ database. Scope is revalidated before every operation.
- The Django test runner provisions the isolated database. Two explicitly named synthetic tables are created and dropped by the test; no migrations, live auth tables, SMS send, sessions or deployed services are accessed.
- The lease table contains exactly one row: epoch, owner (old or promoted) and active/halted mode. The operation table has a **PRIMARY KEY operation_id** and a fixed-length SHA-256-formatted synthetic fingerprint, epoch and owner. No phone, code, client IP, token or real account identity is stored.
- Transactional claim locks the lease row with SELECT FOR UPDATE, validates epoch/owner/mode and only then INSERTs a synthetic operation using ON CONFLICT DO NOTHING. Conflicting same-ID fingerprints, including across epochs, fail closed. Identical same-ID retries return an observation without another insertion.
- Promotion is a one-way PostgreSQL epoch compare-and-swap old/1 to promoted/2. Stale old claims and competing promotions fail. Terminal halt does not reopen.
- The PostGIS CI tests use separate real PostgreSQL client sessions to race identical or conflicting operation IDs; a rollback test checks atomicity; a missing-table test confirms an actual DB error without a legacy fallback.

## Deliberately unproven properties

**This is not a real fencing implementation.** Only clients voluntarily calling this PostgreSQL test helper participate. An existing Redis writer using a raw socket, host port, direct EVAL or the legacy application endpoints bypasses PostgreSQL altogether, as Phase 7.25 proved. No Redis operation, OTP issuance, SMS outbound message, account update, or session creation is committed atomically with PostgreSQL here. An acknowledged database claim followed by a lost Redis or SMS response is still cross-store ambiguous. PostgreSQL outage, unsafe rollback, inconsistent grants, and an attacker-held old-primary connection must block production rollout.

Every returned observation has explicit false values for authentication, OTP issuance/consumption, SMS sent, session creation, global Redis fencing, cross-store atomicity and release permission. No live API/auth/session/migration/settings/deployment file is modified.

## Next release-critical work

A real proposal needs an independently reviewed ingress inventory and **mandatory** enforcement of write authority across *all* paths, including old-master raw host paths; a durable transactional outbox/dispatch protocol for external SMS; account/session handoff guarantees; failover and network-partition operations; PII/privacy audit; rollback rules; security owner signoff and a production rollout plan. The current proof authorizes none of those actions.

**Release gate: BLOCKED.**
