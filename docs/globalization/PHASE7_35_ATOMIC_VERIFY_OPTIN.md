# Phase 7.35 — opt-in single-node legacy OTP WATCH verification

**Runtime-capable, OFF by default. Production release remains BLOCKED. No real OTPs, accounts, sessions, SMS, migrations, infrastructure changes, or deployment in this phase.**

Pinned baseline main: 49fec7090b7dc048b3db198ec11bb8848c7eb494. Phase 7.34 postmerge run 43733052008 succeeded 4/4.

## Narrow security gain

After Phase 7.34, a successful cache deletion was required, but the result did not bind to the record read earlier. An old verifier could read a challenge, a reissue could replace the same logical key, and the stale verifier could delete the new generation and continue toward login.

This phase adds apps/api/v1/otp_atomic_verify.py: an **opt-in** legacy-format per-record WATCH state machine. Dispatch from verify_api_otp_code occurs only with LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_VERIFY=True. **The default is False and existing behavior is unchanged.**

When enabled, the verifier requires the separately configured otp cache alias, django-redis RedisCache + DefaultClient and a fail-closed policy. Settings reject incompatible flag combinations at startup; runtime repeats the safety check if settings are overridden. The existing dedicated OTP alias requires remote rediss://, verified TLS and its own named, non-default ACL identity. This phase does not configure credentials or change real cache endpoints.

On a single Redis server, the verifier:

1. Resolves the Django-Redis physical key; on one raw-byte Redis connection, WATCH precedes TYPE/PTTL/GET.
2. Reads the existing Django-Redis 5.4 serialized STRING and validates identity/purpose, 40-character salted-HMAC SHA-1 digest, timestamps, attempt budget and TTL. Uses the already-trusted legacy serializer; it is **not a safe generic untrusted-pickle parser**.
3. Correct OTP: MULTI; DEL; EXEC. A verified outcome is possible only on the exact reply [1], without retry.
4. Nonterminal wrong OTP: increment the attempt count by serializing the existing dictionary, then MULTI; SET XX KEEPTTL; EXEC with the exact reply [True], preserving expiry.
5. Terminal wrong OTP: MULTI; DEL; EXEC with exact [1], reporting exhaustion without granting a session.
6. Missing/expired/exhausted records preserve expected API errors. A WATCH conflict, malformed bytes, unsupported backend, invalid TTL, ambiguous EXEC acknowledgement, serializer exception, malformed transaction result or wrong cache alias fails closed with HTTP 503 before account lookup or session login. **No fallback to the old get/compare/delete path.**

The dedicated Redis ACL principal needs WATCH, MULTI, EXEC, UNWATCH, TYPE, PTTL, GET, SET and DEL on OTP record keys. No Lua EVAL, global key scans or administrative Redis permissions are required for the verifier. Existing Phase 7.33 ACL fixtures are not permission to activate this mode; real deployment grants need separate review.

## CI evidence and limits

Fast CI checks opt-in dispatch, disabled default, fail-open rejection, no-login HTTP 503, and historical release-blocking guards. The Redis Phase 7.21 isolated container is reused while still running on loopback port 6413, DB15, with a **separate randomized fixture namespace**. It tests the existing serializer and real Redis transactions: correct single winner, concurrent correct/correct, wrong/wrong budget, terminal exhaustion, byte-identical and changed reissue after WATCH, malformed bytes/types/persistent TTL, and post-EXEC lost acknowledgement. Cleanup deletes only exact fixture-created keys, never wildcard scans or flushes.

**Strictly unresolved:** atomic *issuance* (resend cooldown and mobile/IP limits are currently separate cache operations), multi-node authoritative write fencing, split-brain and old-primary raw-writer bypass, durable account/session SQL handoff, retry idempotency, remote pickle storage trust, real ACL topology, SMS delivery and durable SQL-first outbox, historical web/password-reset drain, and separate deployment authorization. Single-node WATCH is not multihost consensus. Enabling the feature requires explicit security, architecture and operational approval plus independently reviewed reversible cutover and rollback.

**Release gate: BLOCKED. Deployment: NONE.**
