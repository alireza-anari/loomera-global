# Phase 7.6 — Historical OTP/session continuity and cutover drain gates

**Scope:** source-anchored contracts, mocked regression tests of CURRENT web/API
helpers and a strict **offline-only, PII-aware** metadata audit. Baseline
`62a45aebf4deb9fcd67c7583aaacb57827daff85`; Phase 7.5 post-merge
CI run `42239809779` was successful in all three jobs.

**No** changes to OTP generation, historical cache names, Django auth,
stored `CustomUser.mobile_number`, session handling, SMS.ir provider,
schema/migrations, real account records, or Production.

## Current binding boundaries

The current web signup OTP session is stored under
`request.session["user_session"]`. Its historical payload contains a
normalized Iranian mobile, an **actual plaintext verification code**,
attempt count/limit, issuance/expiration, signup role, purpose
`signup` or `password_reset` and a reset authorization grant expiry.
The web cooldown remains `otp:cooldown:{purpose}:{legacy_mobile}`.
Rekeying those sessions, or silently converting a historical password
reset grant to a different account or namespace, is prohibited.

The current API OTP subsystem uses `app_login`, distinct hashed
challenges, resend and rate-limit namespaces scoped by **legacy mobile
and purpose**. Incoming `+98` aliases normalize to the existing
`09` login identifier before a cache record is created or verified.
The correct OTP alone does **not** authenticate a user: the API view
must resolve an **active** account matching that literal legacy
number, then call Django `login` only after verification succeeds.

The API verifier currently deletes the challenge after a successful
hash comparison, and configured cache exceptions can fail closed.
**These single-request contracts are not proof of multi-worker
consumption atomicity.** The existing get/compare/delete sequence
must be evaluated under concurrent verifiers and a cache delete
that returns `False` without raising. Its atomic consumption/replay
property is **UNVERIFIED**. Do not widen the identity namespace, enable
dual reads, or claim replay security solely from these tests.

## Synthetic drain review

Pure utility:
`loomera/globalization/otp_session_transition_audit.py`
with `review_legacy_otp_transition`.

Inputs are two **in-memory** arrays only:

- Account rows exactly `account_id, mobile_number, is_active`.
- Challenge metadata exactly `account_id, mobile_number, namespace,
  issued_at, expires_at, attempts, max_attempts, consumed,
  cache_delete_confirmed, password_reset_grant_until`.

Accepted namespaces: `web_signup`, `web_password_reset`,
`api_app_login`. Raw phone values in inputs remain sensitive. The
utility never reads Django cache, database, session, requests, SMS or
filesystem and returns only fixed reason codes, aggregate counts and
flags. Do **not** pass real SMS codes, OTP hashes, session identifiers,
IP addresses, names or email: extra fields are rejected.

A challenge attached to the wrong account, an inactive user, or an
unknown ID blocks. So does an unexpired/unconsumed challenge, expired
record lacking cleanup evidence, consumed API OTP with unverified
deletion, outstanding password-reset grant, future issue timestamp,
or active exhausted attempt budget. Snapshot cardinalities, cache
integrity and web-session scope must be independently evidenced, not
guessed. The cache/session confirmation flags are only **operator
claims**; this utility cannot independently verify them.

**Even an empty or structurally clean challenge snapshot always reports**
`canonical_login_cutover_authorized=false` and
`concurrent_verify_atomicity_proven=false`. This is an evidence
collection aid, not a migration operation, an authorization decision,
a cache-key bridge, or a secure OTP replacement.

## CI regression coverage

`apps/accounts/test_phase7_otp_transition.py` runs a synthetic-only
suite in Fast checks:

- Candidate `+98` and legacy `09` use the same current API OTP key
  space and challenge hash semantics. A successful single verifier
  deletes its cache record, and immediate sequential replay fails.
- A different mobile or purpose cannot verify an existing code.
  Invalid attempt counters, expiry, cooldown aliasing, cache
  read/set/delete failures and fail-closed behavior remain tested.
- The API view can only log in after `verify_api_otp_code` returns and
  the active legacy-mobile user lookup succeeds; missing accounts and
  verification/cache failures do not authenticate.
- Current web password reset session retains its exact stored login
  number and temporary grant, while expiry removes the session and
  wrong codes cannot look up or activate users.
- The offline review rejects unexpected PII fields, malformed
  timestamps/purpose/status, unknown/inactive identities and
  non-drained sessions. Fixed aggregate output is checked for no raw
  IDs, phones, OTP secrets or session identifiers.
- A machine-readable source inventory in
  `PHASE7_6_OTP_SESSION_CONTRACT.json` is checked against existing
  code, without asserting all mobile/third-party clients were audited.

CI uses only deterministic local mocks and synthetics for these
checks. Existing Fast, Chromium, and PostGIS validation stay in place.

## Future go/no-go conditions — NOT met

Before implementing ANY versioned OTP bridge or canonical identity
cutover, separately complete:

1. Authorized, isolated historical session and active-challenge
   inventory; preflight all active/inactive/deleted accounts and
   resolve canonical aliases with data-owner consent. Do not upload
   real phone exports, OTP values, password reset grants or session
   keys to GitHub or ChatGPT.
2. Define cache namespace versioning and explicit monotonic switch,
   anti-replay semantics, old/new client policies, stale challenge
   rejection, purpose isolation and cross-account lookup avoidance.
   Never simply copy challenges into a new E.164 namespace.
3. Rehearse **atomic** cache compare-and-consume under two real
   independent workers/connections, deletion returning `False`,
   timeout and partial cache outages, rate counters, cooldowns,
   max attempts, plaintext code exposure policy and session
   invalidation. Prove no double login or account takeover.
4. Rehearse historical password reset grant draining across active
   web sessions, password changes and deletion/reactivation.
   Record legacy cache/session TTL maxima, deploy grace period
   and a *tested* rollback which restores only historical login
   lookup without granting stale challenges.
5. Obtain independent privacy, security, data-owner, mobile client,
   operator and Phase 3 manual-accessibility signoffs before any
   real schema/data migration or Production rollout.

**Release status:** legacy OTP/login works unchanged; offline
transition preparation exists. Atomic replay, old-session drain
coverage, carrier validation, canonical login and Production cutover
remain **BLOCKED**.
