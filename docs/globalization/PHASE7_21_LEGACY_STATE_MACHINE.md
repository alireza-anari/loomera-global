# Phase 7.21 — legacy Django-Redis OTP per-record optimistic state machine

**Disposable CI experiment only. No Production, live OTP, SMS, account creation, web signup, password reset, Django session, migration, or deployment.**

Baseline main \`2e6f2b9933479c53d94b5fffaeddbabdbd95771b\`. Phase 7.20 postmerge four-job CI \`42411929288\` independently succeeded.

## Problem and progression

The actual API \`apps/api/v1/auth_otp.py\` still uses \`cache.get → compare_digest → cache.delete\`, and \`_cache_delete(required=True)\` ignores the **False** result from \`cache.delete\`. Two workers can read a valid challenge and both proceed; this remains **UNFIXED in live auth**.

Phase 7.20 established the narrower single-node WATCH/MULTI/EXEC delete on **real serialized Django-Redis 5.4 STRING bytes** with a two-worker forced race and byte-identical ABA reissue test, without touching production auth. However, that candidate did not charge wrong attempts or enforce an exhausted attempt budget.

Phase 7.21 extends the *test-only per-record* state machine to a real wrong/valid/exhaustion transition. It uses the same legacy record fields and 40-character Django \`salted_hmac\` SHA-1 digest, not an incompatible Redis HASH/SHA-256 representation. All test keys are random-namespaced and exist only on a disposable local Redis 7.4 AOF server.

## Transition contract

Before network IO, enforce all of: \`GITHUB_ACTIONS=true\`, explicit \`LOOMERA_PHASE721_TEST_REDIS=1\`, GitHub run ID and attempt, random lowercase hex fixture ID, exact \`record:app_login:09...\` logical key, Django-Redis prefix/version, \`redis://127.0.0.1:6413/15\` and raw-byte redis-py connection to the same host/port/DB.

The test candidate uses **one pinned Redis pipeline connection**:

1. \`WATCH physical_key\` **before** \`TYPE\`, \`PTTL\`, \`GET\`; reject missing, non-STRING, persistent, expired or unusually long-lived Redis TTL and bad serialization/legacy fields.
2. Decode via Django-Redis's pinned legacy serializer. Require purpose/mobile binding, unverified status, strict integer timestamps and attempts (not boolean), expiry and attempts within bounds.
3. Compare supplied *synthetic digest* with stored digest via \`secrets.compare_digest\`.
4. **Correct code**: \`MULTI; DEL physical_key; EXEC\`. Only an exact \`[1]\` is a synthetic consumption. Never return login authorization.
5. **Wrong nonterminal code**: clone the record, increment \`attempts\` once, encode the entire dict using Django-Redis's *existing* encoder, check its decoded round-trip, then \`MULTI; SET physical_key serialized XX KEEPTTL; EXEC\`. The positive result must be exactly \`[True]\`. \`XX\` refuses re-creation; \`KEEPTTL\` preserves the original expiry instead of refreshing it.
6. **Last wrong attempt**: \`MULTI; DEL; EXEC\` with exact \`[1]\`; report synthetic exhaustion (never synthetic consumption or authentication).
7. Concurrent \`SET\`, \`DELETE\`, expiry or *byte-identical reissue* aborts \`EXEC\` via \`WatchError\`. No automatic fallback or unsafe replay. An exception or lost \`EXEC\` reply returns \`backend_unavailable\`; the server *may* have committed, so the caller cannot infer success and must never authenticate.

**No returned status authenticates a real user, creates a session or authorizes Production.** The evidence includes only status, optional attempts remaining and test mutation flags; never mobile, digest, password, raw pickled bytes, physical Redis key, or identity.

## CI physical isolation and adversarial cases

The workflow launches **a fresh Redis 7.4-alpine Docker container** on \`127.0.0.1:6413\`, DB15, one dedicated bridge and AOF volume. The runner only deletes these named disposable resources and known synthetic keys; no wildcard operations, \`SCAN\`, \`FLUSHALL\` or customer data.

Actual project-pinned \`django-redis==5.4.0\`/\`redis==5.2.1\` create and load pickled dicts. The real test asserts:

- Correct code consumes once; another lookup is missing.
- Wrong code increments exactly once via serialized STRING, preserves unrelated delivery fields and **does not extend Redis TTL**. Correct code after wrong attempts may still consume the remaining challenge.
- Last wrong attempt deletes and blocks a subsequent correct code, including one-attempt budgets.
- Two **independent Redis clients** blocked behind a barrier *after both WATCHed reads*: correct/correct only one winner, wrong/wrong one attempted increment, correct/wrong only one successful transition, and last-wrong/correct only one terminal transition. The loser must report an optimistic transaction conflict.
- Old generation cannot delete or charge a reissued challenge—even when reissued bytes are **identical** (ABA). New-code generation succeeds only under its own later verifier.
- Invalid record, exhausted attempts, malformed pickle, bad identity or purpose, type, TTL, remote cache, wrong DB, or unauthorized grant are rejected.
- A forced **post-commit loss of the EXEC response** yields \`backend_unavailable\`, never a false-positive auth grant; the test observes whether a delete or attempt update nevertheless committed.
- Separate simulated resend and hourly rate cache records are left unchanged by this per-record candidate.

Fast checks enforce strict scoping, disallowed live imports, fail-closed outcomes, CI wiring and a release-blocked exit JSON. The existing four jobs and all prior Phase 7 integration checks remain in place.

## Security and incomplete architecture

This is **not yet a complete Production OTP state machine**. It does *not* make issuance, resend cooldown, per-mobile/IP rate limits, account/session login, SMS delivery or cross-store transactions atomic. In particular, wrong-attempt and code-consumption CAS on **one writable Redis node cannot fence a split-brain old primary**; Phases 7.17–7.19 demonstrated raw old-primary and separate management/network bypasses. This does not prove durable multi-host authorization, all-path isolation, or failover safety.

Pickled Django-Redis records are interpreted only from CI-created bytes; unsafe untrusted pickle inputs must never be promoted to a new Production deserialize endpoint. Historical web signup and password-reset OTP sessions still require independent review and drain. Live API verification remains untouched, including \`delete(False)\`, and replay security is **not repaired**.

A Production proposal needs a reviewed atomic *issue/verify/attempt/rate/expiry* protocol, versioned reversible migration, actual all-writer fencing across nodes, cross-store account/session consistency, security/owner signoff and a separately approved deploy/rollback. All release indicators stay **BLOCKED**.
