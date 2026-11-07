# Phase 7.10 — Synthetic v2 OTP issuance, consume and session-handoff fencing

**No Production OTP migration, login, password reset, user/session lookup, account creation, mobile-client changes, data access or deployment.** Baseline main SHA: 62a4dc26ca96949afd0f82e86ccaa18bdd2c23c9 (Phase 7.9); its post-merge CI run 42367367376 succeeded in Fast/Chromium/PostGIS/Redis.

## Known live security issue (UNFIXED)

The current API OTP verifier in apps/api/v1/auth_otp.py does cache.get, secrets.compare_digest and cache.delete as three separate operations. The _cache_delete helper returns True after calling cache.delete(key), even when the backend returns False. Two workers may read the same valid challenge before either delete; a losing concurrent verifier may incorrectly succeed. This is still **unfixed**. Phase 7.7 HASH cannot interpret the Django-Redis STRING record and SHA-1 40-character digest from Phase 7.8. Phase 7.9 was only an offline, short-lived version gate simulation.

This phase adds neither a live feature flag nor a production OTP bridge. Neither synthetic module is imported by API, web login or Django session code.

## A. Redis 7.4 single-key synthetic rehearsal

Implementation: loomera/globalization/otp_v2_atomic_handoff_rehearsal.py.

The adapter accepts only an explicit LOOMERA_PHASE710_TEST_REDIS=1 opt-in, unauthenticated localhost port 6379 / logical DB15 and an isolated random 32-character fixture ID in the namespace loomera:phase710:synthetic-only:. Every operation rechecks the client and grant. Six Redis Lua scripts operate on only KEYS[1]; the test cleanup deletes only the owned key, never scans/flushed databases. No actual OTP, account ID, mobile, IP, session ID or provider is accessed or stored.

1. Bootstrap: One-time observe gate and fixed **10-minute fixture TTL**. Repeat calls cannot overwrite, resurrect or extend it. This is disposable CI isolation, **not durable Production routing**.
2. Activate: A compare-and-swap generation change activates v2_simulated. Absent, corrupt and stale states are denied.
3. Issue: In v2_simulated mode, one synthetic digest (64 lowercase SHA-256-style hexadecimal characters, not a production secret), a fixture-only subject label, purpose binding and bounded TTL are stored. Duplicate issuance cannot reset attempts or time-to-live.
4. Verify: One EVAL checks generation, mode, subject, purpose, server TIME expiry, a three-attempt maximum and digest. Incorrect attempts increment atomically. Correct digest changes challenge to consumed and deletes its digest. An expired/exhausted challenge remains as a denial tombstone; no reissue, no replay and no login. The five-second receipt is **a test-only value**.
5. Would-admit: One EVAL binds a short receipt to subject and purpose; two independent Redis clients can produce only one would_admit claim. The synthetic active and session-eligibility booleans are **untrusted caller claims**, not an authoritative Django account/database check or session-store transaction. Even would_admit means session_created=False and authenticated=False.
6. Halt: A terminal, monotonic generation change blocks all new issue, verify and session-admission claims. It does NOT reinstate the unsafe legacy verifier.

Any timeout, malformed reply, wrong Redis type, missing marker or ambiguous network response **after a successful Redis mutation** maps to backend_unavailable, not login success or automatic retry.

These atomicity assertions apply only to one Redis HASH on one standalone Redis instance. They do **not** prove cluster/failover durability, replica clock and key consistency, simultaneous PostgreSQL account deactivation, Django session creation, SMS/resend/rate limits, security of secret material or cross-backend rollback. Lua string comparison has not been proven constant-time and cannot be reused as a real OTP verifier. No users or third-party clients were exercised.

## B. Pure offline session policy

Implementation: loomera/globalization/otp_v2_session_policy.py. It takes only exact boolean synthetic evidence for:
- Atomic consume confirmation, correct version generation, and purpose binding;
- Unchanged literal Iranian legacy login identity (09...), exactly one active user, and no pending account deletion/deactivation;
- No outstanding historical web password-reset grant;
- Healthy cache and session store, unclaimed receipt within its deadline, and no emergency halt.

Every violated condition returns a fixed denial reason. Even if **all** caller-provided booleans are True, the decision is only simulation_candidate; it never authenticates or creates a session, authorizes Production, or allows legacy fallback. This offline helper cannot verify the completeness or truth of such claims.

The old web signup/reset session at request.session["user_session"], including plaintext OTP and grant semantics, is not changed or reinterpreted. The current app_login API contract and legacy Iranian mobile account lookup remain intact. A real implementation needs an independently reviewed transactional, idempotent session handoff across account DB and session store, which no standalone Redis Lua operation can guarantee.

## C. CI and source guard coverage

The existing Fast job adds 18 Django SimpleTestCase tests in apps/accounts/test_phase7_otp_handoff_policy.py: all failure reasons, strict booleans, blocked release matrix, absence of imports in live API/web models, and explicit guard that the old race is still present.

The existing Redis 7.4 service job adds 22 isolated integration tests from tests/phase7_v2_handoff_test.py, running with LOOMERA_PHASE710_TEST_REDIS=1. Coverage includes two independent client verification and session-claim races, stale generation, halt versus verification, wrong purpose and subject, attempt exhaustion, expiry, duplicate issuance, post-consume replay, missing/corrupt keys, receipt expiry, inactive account claims, post-commit timeout, malformed replies, DB15/env guards and exact key cleanup.

Original Phase 7.7, 7.8 and 7.9 tests remain required, as do all Fast, Chromium and PostGIS checks.

## D. Required approvals and STOP conditions

1. Account/data owner, privacy and security reviews of *authorized* historical cache, session, inactive/deleting account and password-reset-grant inventories. Never upload real user records, OTP values, cache hashes or session keys to a repository or chat. Independently prove the legacy writers are frozen and in-flight challenges drained; caller-provided flags are not evidence by themselves.
2. A Production-grade durable version generation, explicit single-version issuance/verification affinity, startup and failover guarantees, strict purpose namespace boundaries and approved plan for partial issuance. Missing/ambiguous state must fail closed, **never silently accept in legacy mode**.
3. Security-reviewed digest comparison, key rotation, expiration, attempt counters, cooldown, resend and rate limiting. Fix the live two-worker GET/compare/DELETE race and false deletion-return handling in a separately approved change with actual Django-Redis compatibility testing.
4. Independent tests of identity matching, concurrent user deactivation/deletion, missing/duplicate accounts, user-session storage failure, timeout-after-commit and clear HTTP/API error contracts. One Redis consumption claim is **not** proof of exactly one actual Django login or session.
5. A reviewed emergency stop/forward-recovery plan; do not use halt as unconditional rollback to unsafe legacy verification or a resurrection of consumed codes. Verify authorized mobile client and Phase 3 manual accessibility acceptance.
6. Obtain formal security, data-owner and deployment signoffs before any live cutover. All-green CI is not Production authorization.

**Release gate: BLOCKED. Phase 7.10 is a synthetic-only security preflight; the live OTP race is still unfixed.**
