# Phase 7.8 — Django-Redis legacy OTP wire compatibility preflight

**Test-only. No real OTP migration, login, signup, password reset, or Production deployment.**

Baseline: main `23c23cccf0192f39b1746e1dccd4632025cbd3cc`, Phase 7.7 post-merge CI run `42254247483` (Fast/Chromium/PostGIS/Redis jobs all succeeded).

## Finding and purpose

The live API OTP helper builds a `dict` with `purpose`, `mobile_number`,
`code_hash`, `created_at`, `expires_at`, attempts, maximum attempts,
verification flag and delivery metadata. Django-Redis 5.4 serializes that
record into a **Redis STRING** under a versioned/prefixed physical cache key.
Phase 7.7 EVAL expects a **Redis HASH** with a different key, field set,
digest and expiry. Running the Phase 7.7 script directly on a legacy STRING
raises WRONGTYPE; neither its test-only adapter nor an unreviewed alias can
safely consume the legacy record.

The live API verifier still does `cache.get`, Python hash comparison,
then `cache.delete` as separate operations; it does not check the
boolean return value from `cache.delete`. Phase 7.8 uses **two separate
Django-Redis cache clients**, a barrier after both valid reads, and one
delete per contender to reproduce the unsafe interleaving: both see a
matching digest while only one confirms deletion. This is synthetic
evidence of the legacy race, **not** a demonstration that a real account
was authenticated twice.

## Read-only synthetic preflight and isolation

`loomera/globalization/otp_cache_wire_rehearsal.py` only inspects
the caller-created Django-Redis synthetic fixture. It validates the
explicit environment grant `LOOMERA_PHASE78_TEST_REDIS=1`, localhost
port 6379, DB 15, a random UUID-shaped fixture identifier, a dedicated
`loomera:phase78:synthetic-only:` key prefix, version 1 and the
legacy logical record key pattern. It reads the raw Redis type and TTL,
then Django-Redis's decoded payload only if the stored value is a STRING;
no arbitrary production data or session store is accessed.

It returns only a status code and bounded TTL: `absent`,
`legacy_string_pending_drain`, `incompatible_redis_type`,
`missing_or_invalid_ttl`, `invalid_legacy_payload`, or
`backend_unavailable`. No mobile, OTP, hash, key, session ID or
account ID is returned. **Every result** retains
`hash_compatible=False`, `authenticated=False` and
`cutover_authorized=False`.

A separate Redis CI service supplies real Redis 7.4; tests exercise
Django-Redis==5.4.0 and redis==5.2.1 with disposable records, including
wrong Redis type, malformed pickle/record, expired/persistent TTL
classification, wrong purpose/binding, unauthorized scope, two-client
GET/compare/DELETE race, and preservation of separate cooldown/rate
keys while a Phase 7.7 synthetic HASH coexists. Only fixture-owned keys
are deleted during test cleanup; no flush/scan.

## Blocking follow-up

A passing test does **not** migrate, fix, authorize or deploy any live OTP
security behavior. Required next work includes account-owner approval of
legacy active/expired OTP and web/password-reset session drain, a versioned
and reversible storage transition, production-compatible atomic verification
and failed/ambiguous deletion semantics, atomic resend/rate counters,
cluster/failover and secure digest comparison evaluation, active-user
session race testing, external mobile client acceptance and security review.
Live API semantics and historical Iranian mobile identity are unchanged.

**Release state: BLOCKED.**
