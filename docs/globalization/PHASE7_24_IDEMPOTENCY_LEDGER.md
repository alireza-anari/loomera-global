# Phase 7.24 — bounded OTP operation-ID ledger on the real legacy Redis wire

**Only a disposable test in GitHub CI. Never import this module into live API/auth/session code; never connect to customer Redis, send SMS, authenticate, or deploy.**

Baseline \`main\` SHA \`b9dfa8979d5b73e85020d53e1f57837b4315c718\`. Independently checked Phase 7.23 postmerge 4/4 CI: \`42450758225\`.

## Goal and exact scope

Phase 7.23 proved synthetic issuance and verification share one actual Django-Redis 5.4 serialized legacy STRING challenge on one Redis 7.4 AOF node, and fail closed on ambiguous responses or a physical Redis outage. But manually retrying a wrong-code operation whose \`EXEC\` had already committed still decremented the attempt budget twice. Neither issuance nor verification had stable operation identity.

Phase 7.24 adds a **test-only bounded operation ledger** using the **same disposable Redis 7.4-alpine container, localhost port 6414, DB15, random per-test Django-Redis prefix** and strict issue/verify WATCH transactions. It does not mutate Phase 7.22/7.23 candidates or live code. The five-key issuer and two-key verifier each commit the ledger record in the SAME Redis \`MULTI/EXEC\` as their business-state mutation.

The exact \`operation:synthetic:<32-hex-id>\` logical key is namespaced and versioned through django-redis. IDs are freshly generated \`uuid4().hex\` for fixture tests and validated as lowercase 32-hex. The record is a Django-Redis serialized dict in Redis STRING with a **SHA-256 fingerprint** binding the operation type (\`issue\` vs \`verify\`), fake mobile, synthetic IP token, and test code's 40-character salted-HMAC SHA1 digest; raw mobile, code, digest and session information are never written to the ledger. Simulated \`now_ts\` is intentionally *not* included in the fingerprint because retries may occur later, but a changed operation type or digest is rejected. Every returned result has all real authentication, SMS, Production and auto-retry authorization flags \`False\`.

The fixture LEDGER_TTL is **3900 seconds** (slightly longer than the 3600-second per-hour rate TTL). Replaying does not rewrite or extend the ledger's TTL. This is a **bounded, single-master rehearsal** and does *not* assert permanent idempotency if a ledger key expires, is evicted/deleted, or is lost during failover. This TTL and retention policy is experimental, NOT a privacy-approved Production design.

## Atomic issue protocol (5 keys, 5 writes)

1. Enforce GitHub CI grants \`LOOMERA_PHASE722_TEST_REDIS=1\` and \`LOOMERA_PHASE724_TEST_REDIS=1\`, run ID/attempt, random fixture, fake mobile/IP, strict digest, exact localhost connection. Validate before Redis IO.
2. \`WATCH\` the ledger **and** challenge, resend cooldown, mobile rate, and IP rate keys before ANY read.
3. If the ledger exists, validate its type/TTL/fields/fingerprint. The exact same operation yields \`synthetic_replayed\` with the prior fake outcome; a changed digest/type/malformed entry yields an explicit fail-closed conflict. Do not mutate or renew any TTL.
4. Otherwise enforce the unchanged Phase 7.22 rules: no pending challenge or cooldown; strict integer counters and positive TTLs; fake mobile limit 2/hour, shared synthetic IP limit 3/hour.
5. In one \`MULTI\`, write real Django-Redis legacy \`record\` (120s), resend timestamp (60s), mobile/IP counters (3600s on first create, \`XX KEEPTTL\` afterward) **and a serialized operation ledger (3900s)**. Only strictly five \`True\` responses from \`EXEC\` confirm *synthetic* issuance. No SMS is actually sent.

No application-layer fallback, blind retry, cross-store auth or external delivery is authorized.

## Atomic verification protocol (2 keys, 2 writes)

1. \`WATCH\` the same ledger and challenge physical keys before reading, checking the ledger first.
2. On exact replay, read the prior synthetic result without touching challenge bytes or retry budget. The client receives no real auth grant even if the prior operation deleted a valid record.
3. On a first-time operation, validate the existing genuine legacy dict, purpose/mobile/expiry/remaining attempts and strict 40-hex digest; compare using \`secrets.compare_digest\`.
4. Queue the challenge transition plus the ledger entry in **one \`MULTI\`**: correct code \`DEL\` + ledger; wrong nonterminal \`SET XX KEEPTTL\` + ledger; final wrong \`DEL\` + ledger. Only \`EXEC [1, True]\` or \`[True, True]\` is accepted as a synthetic mutation. Other results, \`WatchError\` and timeouts fail closed.

The operation ledger remembers \`prior_status\` plus synthetic attempts remaining or request quota remaining. A replay never means a session may be created. Reusing an issue operation ID to verify a code, or changing the digest associated with an existing ID, returns \`operation_reuse_conflict\`.

## Real Redis/AOF integration tests

The Phase 7.22/7.23 isolated shell fixture now also runs Phase 7.24 before its existing EXIT cleanup trap and adds \`loomera.phase724=idempotency-test\` to the exact Docker container. The new test suite uses freshly generated random fixture-owned keys, real Django-Redis 5.4 encoding and independent redis-py clients:

- Five-key issue then same-ID replay: no changed challenge/ledger bytes, no TTL extension or additional rate counter charge.
- Valid consume then same-ID replay even after challenge deletion, never a login grant or second consume.
- Wrong attempt and correct consume with **post-commit lost \`EXEC\` reply**: first call returns unavailable; subsequent same-ID call sees the ledger, does not mutate or authenticate. A wrong retry no longer double-charges *within this bounded test ledger lifetime*.
- Exhausted attempt replay; different operation IDs still charge genuinely distinct attempts.
- Two independent workers barriered after WATCH on the same issue ID or same wrong-verify ID: **one synthetic transaction winner and one Watch conflict**; a later retry reads the single ledger entry.
- Old consumed operation replay after a fresh fake code generation does not touch the new challenge.
- Changed digest/kind with reused operation ID, invalid pickle/fields/TTL/Redis type, unauthorized environment, remote/wrong database and wrong ID all fail closed.
- Physically stop **only the exact named, dual-labeled** disposable Docker Redis, verify no mutations or grants while unavailable, and restart with \`--appendonly yes --appendfsync always\` AOF. The fixture verifies challenge bytes, counters and both issue/wrong-attempt ledger records are preserved, and that retries do **not** charge again after restart.
- **Negative boundary proof**: explicitly remove the synthetic ledger, challenge and cooldown (inside the disposable fixture). Reusing the previous ID can then perform a new issue. Thus the candidate proves bounded same-master idempotency only, not global exactly-once delivery or a permanent durable record.

The Fast CI policy test enforces the strict no-live-wiring boundary, exact synthetic cleanup, idempotency conflict handling, source-level WATCH-before-read, and machine-readable BLOCKED exit matrix. Fast, real Redis, Chromium and PostGIS existing jobs remain.

## Production gate remains BLOCKED

The actual \`apps/api/v1/auth_otp.py\` still uses separate get/compare/delete and returns \`True\` even when \`cache.delete()\` is \`False\`; issuance also uses separate non-atomic request/cooldown/rate writes. **No real security bug has been repaired by this test candidate.**

This is a **single Redis master**, not global durable consensus. A split-brain old primary can still accept privileged raw writes through a separate host interface shown in Phase 7.19; this ledger does not fence it. There is no SMS outbox/delivery idempotency, trusted Production client operation-ID provenance, account/session transaction, safe untrusted-pickle acceptance, live OTP/password-reset migration, or owner/security approval. A fresh operation ID intentionally represents a fresh wrong attempt; false claims of all-request exactly-once safety are forbidden.

Any approved rollout needs protocol/security review, retention/eviction and privacy policy, multi-host fencing, real request/verify operations, bounded migration and rollback plus independent signoff. **No Production deployment.**
