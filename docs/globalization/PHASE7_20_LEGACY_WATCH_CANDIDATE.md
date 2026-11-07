# Phase 7.20 — real legacy-format Django-Redis WATCH/MULTI single-winner candidate

**CI synthetic experiment ONLY. No Production implementation, account creation, session creation, OTP delivery, authentication, migration, or deployment.**

Baseline main: \`919629f60d18ac9bdb3ad68414219c5facd00086\`. Phase 7.19 independent post-merge four-job CI: \`42410265534\` (Fast, Redis, Chromium, PostGIS success).

## Finding and why this candidate is different

\`apps/api/v1/auth_otp.py\` still follows \`cache.get → Python compare_digest → cache.delete\`, while \`_cache_delete(required=True)\` reports success when \`cache.delete\` **returns False**. Both workers may obtain the same valid record before either deletes it. Prior Phase 7.8 reproduced this interleaving with two independent Django-Redis clients. It remains a **live bug**.

Legacy API cache entries are Django-Redis 5.4.0 **pickled dictionary bytes stored as Redis STRINGs**, under prefixed version-1 physical keys. The code digest uses Django \`salted_hmac\` default SHA-1 (40 hex). Experiments operating on Redis HASH / SHA-256 cannot be dropped into this key format.

This new **unwired** candidate tries a narrow atomic delete on the real legacy wire representation, without conversion, via a single-Redis-node optimistic transaction:

1. Strictly validate a GitHub-CI-only disposable namespace, 127.0.0.1:6412/15, exact \`record:app_login:09...\` logical key, Django-Redis prefix and version, and the raw redis-py client's DB.
2. Use \`WATCH physical_key\` on the **same pipeline connection before reading** \`TYPE\`, \`PTTL\` and \`GET\` from Redis.
3. Decode the observed raw Redis bytes via Django-Redis's own serializer, enforce exact synthetic legacy fields, temporal bounds, strict attempt types, purpose and mobile binding; compare a submitted synthetic 40-hex hash in Python using constant-time \`secrets.compare_digest\`.
4. For valid challenge only: \`MULTI; DEL physical_key; EXEC\`. Count the deletion as a **synthetic single winner** only if EXEC returns exactly \`[1]\`.
5. On another writer's \`DEL\`, \`SET\`, even an identical-byte \`SET\` (ABA), \`WATCH\` aborts EXEC. No retry, grant, fallback, payload leak or TTL extension. All failures return bounded result codes.

### Real test cases

A dedicated Redis 7.4-alpine container with AOF, loopback port **6412**, DB15, a disposable volume and Docker bridge executes the project-pinned **django-redis==5.4.0** and **redis==5.2.1**.

The test runner creates true serialized Django-Redis cache records using \`RedisCache.set\`, validates STRING bytes and exact legacy readback, and executes the candidate with **two independent clients and a thread barrier after both WATCHed reads**. Exactly one may confirm deletion; the other must report Redis optimistic transaction conflict, with no login grant.

The runner also tests the difficult same-byte ABA reissue after WATCH, rotated digest generation, wrong digest, exhausted and expired records, mismatched identity/purpose, corrupt pickle, wrong Redis type, missing/persistent TTL, invalid cache prefix, remote backend and wrong DB. Separate synthetic resend and rate keys are not touched. Fast tests enforce no-live-wiring, scope, invalid payloads, machine-readable blocking criteria, and security consequences.

Cleanup touches only the named test container, volume, bridge and known fixture keys. **No FLUSH, SCAN, customer key or Production cache access.**

## Limits and release block

This proves a *single-node, per-key optimistic-transaction property* for a **test-only record**, not a secure new Production verifier. Specifically:

- The candidate **does not increment wrong-code attempts**, enforce resend cooldown, protect hourly mobile/IP counters, create sessions, check active account status or issue the challenge.
- A single Redis \`WATCH/MULTI\` transaction is **not** durable multi-host consensus. It does not fence an old primary during failover/split brain, even if local single-node concurrency works. Phase 7.19 demonstrated an alternate raw writer ingress still open.
- Actual live API OTP verify stays untouched and vulnerable to the observed concurrent \`get/compare/delete\` and false deletion semantics.
- Historical web signup and password-reset OTP session grants, resend/rate state, old cache record drain and cross-store account/session atomicity are not solved.
- More work: a reviewed atomic **complete verification state machine**, wrong-attempt and rate atomicity, feature-flagged reversible migration with in-flight session drain, real multihost write-side authority, security/owner signoff, release authorization and rollback.

**Release gate: BLOCKED.** Do not wire this test candidate, key layout, serializer access or Redis port into live auth without separate architecture/security approval. The machine-readable exit matrix is \`PHASE7_20_EXIT_MATRIX.json\`.
