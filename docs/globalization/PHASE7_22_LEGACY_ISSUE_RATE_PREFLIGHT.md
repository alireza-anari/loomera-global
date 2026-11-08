# Phase 7.22 — legacy Django-Redis OTP issue, resend and rate multi-key CAS preflight

**Synthetic disposable GitHub CI ONLY. No real OTP issuance, SMS, account, login, session, migration, Production configuration or deployment.**

Baseline main: \`7f34b5639d089ec34285d7c5cf2d19f06e46fde6\`. Phase 7.21 postmerge CI run \`42447668047\` independently confirmed all four jobs successful.

## Purpose

Phase 7.20 proved a single-node WATCH/MULTI optimistic delete on real Django-Redis serialized \`STRING\` fixtures. Phase 7.21 added single-record correctness, wrong-attempt increment and final-attempt exhaustion on the same legacy wire format. Neither addressed the issuing side: the **actual API** still checks resend cooldown and hourly mobile/IP rate as separate read/write operations, creates the record separately and stores the cooldown separately. Multiple concurrent issuers can race, overrun limits, or incorrectly duplicate issues; Production remains unchanged and unrepaired.

This candidate tests four keys **atomically together** on one isolated Redis server:

- \`record:app_login:09...\` — Django-Redis serialized dictionary with purpose/mobile/digest/time/attempts/delivery, 120-second Redis TTL.
- \`resend:app_login:09...\` — Django-Redis native integer timestamp in Redis STRING with 60-second TTL.
- \`rate:mobile:app_login_09...:<hour>\` — native integer count, max 2 per simulated hour, 3600-second TTL on first creation.
- \`rate:ip:synthetic_ip_01:<hour>\` — native integer count shared across synthetic mobile numbers, max 3 per simulated hour, same first-write TTL.

**Django-Redis 5.4 optimization matters**: its \`encode(int)\` is an integer, sent over redis-py as a decimal Redis STRING, *not* the serialized/pickled dict bytes used for the challenge record. The experiment preserves both actual wire formats, not a new HASH or arbitrary JSON representation.

## Atomic path

1. Hard-validate the exact GitHub CI grant, runner identity, random fixture ID, a synthetic mobile, a synthetic **non-real IP token**, valid test digest/clock, one Django-Redis backend \`redis://127.0.0.1:6414/15\` and byte-oriented redis-py client. No network access occurs on a failed guard.
2. \`WATCH\` all four physical prefixed/versioned keys *before* reading any; verify \`TYPE\`, \`PTTL\`, and decode only temporary test-owned Redis STRINGs.
3. Deny an existing challenge or persisted resend cooldown **without charging either quota**. Fail closed for corrupted metadata, wrong Redis type, missing TTL or exceeded mobile/IP limit.
4. Construct a fake challenge using the legacy SHA-1-format \`salted_hmac\` digest supplied by the test caller. Use the project-pinned Django-Redis encoder for the record and integer fields.
5. Queue a single \`MULTI\`: \`SET record EX 120\`, \`SET cooldown EX 60\`, and \`SET\` each rate counter. If a counter already exists, use \`XX KEEPTTL\` to preserve the original expiry; if new, use \`EX 3600\`. Only exactly \`[True, True, True, True]\` from \`EXEC\` confirms **synthetic issuance**.
6. \`WATCH\` conflicts and other faults fail closed. A lost response after an actual commit yields \`backend_unavailable\`, *not* issuance or real authentication permission; no naive retry or fallback is used. All result objects explicitly have every real auth/release permission flag **False**.

Single-node Redis execution serializes all queued commands. However, failures to apply one command during \`EXEC\` can still produce an ambiguous or partially applied mutation: the machine **never authorizes** on an incomplete reply. This test is deliberately not Production transaction semantics across replicas or databases.

## Real CI scenarios

A fresh Redis 7.4-alpine container with a dedicated bridge and AOF volume exposes only \`127.0.0.1:6414\` (DB15). A new random fixture prefix is used for each test and only fixture-created keys are removed; never \`FLUSH\`, \`SCAN\`, remote Redis or customer data.

- Verify all four keys were written, including exact real Django-Redis dict/string and integer/string forms, and positive bounded TTLs.
- Existing challenge, or a cooldown remaining after a simulated challenge consumption, rejects new issuance without advancing either quota.
- Simulate expiry of the challenge and cooldown *in the test container only*, then issue a new generation and confirm mobile and IP counters increment with no renewed hourly TTL. Exhaust both configured hourly quotas and verify no record is created when limited.
- Force **two separate Redis connections behind a barrier after WATCHed reads**: same mobile/IP and different mobile/shared IP both yield exactly one synthetic issuance and one optimistic conflict; no double rate increment.
- Check the generated serialized record passes Phase 7.21's legacy-field validation and that a separately scripted **test-only WATCH+DEL** can consume the fixture; cooldown still denies immediate reissue.
- Force a *byte-identical* counter rewrite after WATCH: the issuer must conflict rather than charge on stale state.
- Wrong Redis type, invalid count, untrusted backend, wrong port/DB/prefix or real IP literal fail closed. A forged \`EXEC\` result cannot confirm mutation; actual commit followed by lost reply is still not permission.
- Simulated hour boundary generates a different counter key (clock behavior is test-only; no trusted Production clock is established).

The Fast CI contract additionally checks strict scoping, forbidden live imports, dedicated cleanup, required race tests, unchanged historical API code and machine-readable **BLOCKED** release evidence. All existing Redis, Fast, Chromium and PostGIS checks remain.

## Critical limitations

The active \`apps/api/v1/auth_otp.py\` still has a **non-atomic get → compare → delete**, whose delete helper ignores the boolean \`delete(False)\`; it also has independent request/cooldown/mobile/IP rate check-and-set operations. **Neither live issue nor live verify was changed.**

This candidate is one Redis-master transaction only; it **cannot** fence privileged raw writers on a partitioned old primary (Phase 7.19 demonstrated an alternate host ingress), establish durable consensus or replace atomic account/session transactions. A Django-Redis legacy pickle is decoded only when created by test fixtures. Never treat arbitrary externally supplied serialized pickle bytes as a safe Production input. No SMS outbox/delivery, retry/idempotency policy, trusted proxy/IP parsing, credential rotation, historical web/signup/password-reset OTP drain, live account review, security approval or reversible deployment plan is delivered here.

**Release gate: BLOCKED**, including any Production implementation or migration. A production-ready issuance/verify/rate protocol and cross-store write authority require security/owner signoff and separate explicit deployment permission.
