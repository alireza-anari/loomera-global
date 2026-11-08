# Phase 7.23 — Integrated legacy OTP issue/verify under retry ambiguity and Redis outage

**Test-only GitHub CI. Neither real OTPs nor real accounts or sessions are accessed, and no Production deployment is authorized.**

Baseline \`main\` SHA \`08496038f90bdb1cd4b2b04f2f3be6358d12f98c\`, Phase 7.22 postmerge push CI \`42449040096\` 4/4 succeeded.

## Why integrate the two previous experiments

Phase 7.21 validated *per-record* optimistic verification using genuine Django-Redis 5.4 serialized Redis STRING bytes and \`WATCH\` before \`GET\`. Phase 7.22 atomically issued a **synthetic** legacy-format record together with resend cooldown, per-mobile and per-IP request counts, all \`WATCH\`ed and committed in one \`MULTI/EXEC\`.

Those experiments used separate disposable Redis ports/namespaces; success individually does not establish end-to-end compatibility with the **same physical challenge key**, retry semantics, or a Redis outage. This phase adds a **test-only integrated verifier** that reuses the Phase 7.22 exact localhost endpoint, prefix, random fixture and record key. It imports the earlier pure verification field/reply validators and existing Django-Redis serializer; it cannot be imported by live API/auth/session code. Both explicit Phase 7.22 and Phase 7.23 CI grants must be present.

This is still **one writable Redis master**. No durability/quorum across multiple masters, global fencing, real login permission or account/session cross-store transaction is established.

## The integrated contract

For the exact \`record:app_login:09...\` key produced by Phase 7.22, the verifier uses the same Redis 7.4 AOF server on \`127.0.0.1:6414\`, DB15:

1. Validate GitHub CI-only grants and the exact Phase 7.22 backend, random fixture, purpose/mobile and non-real synthetic IP token **before** any Redis IO.
2. \`WATCH\` the physical record *before* observing its Redis TYPE, PTTL or raw bytes.
3. Decode **only fixture-created** legacy Django-Redis serialized STRING bytes. Validate identity/purpose, expiry, strict attempt budget and 40-hex Django salted SHA-1-format digest.
4. If code matches, \`MULTI; DEL key; EXEC\` and accept only reply exactly \`[1]\` as **synthetic record consumption**, never real authentication.
5. For wrong code, increment attempts with the pinned serializer and \`MULTI; SET XX KEEPTTL; EXEC\`, accepting only exact \`[True]\`; last wrong attempt \`MULTI; DEL; EXEC [1]\` is test-only exhaustion.
6. Redis \`WatchError\`, corrupt records, timeout, malformed replies, interrupted IO or lost \`EXEC\` acknowledgment never authorize a session. Every result carries \`automatic_retry_authorized=False\`, \`real_authentication_allowed=False\`, \`real_session_created=False\` and \`production_cutover_authorized=False\`.

Issuer and verifier now serialize their transactions against **the same physical record**, while the issuer separately guards cooldown and mobile/IP counters. The test explicitly documents that the old-generation verifier must conflict if a record is removed/reissued while it holds a WATCH, including **byte-identical** reissue.

### Retry and ambiguous commit policy

The experimental worker cannot distinguish a request whose \`EXEC\` was never received from a request committed by Redis whose acknowledgment was lost.

- A fake issue may commit its record and rate counters before the client receives \`backend_unavailable\`. A subsequent explicit attempt sees \`challenge_already_pending\` and does not charge again in the tested same-node state. This is *not* a general exactly-once issuance or SMS guarantee.
- A fake valid verify may commit \`DEL\` before the acknowledgment is lost. It returns **no auth grant**; the subsequent verify reports missing.
- A fake wrong-code verify may commit the updated attempt counter before the acknowledgment is lost. A *new manually repeated wrong code* then incurs another attempt. The experiment **proves the absence of operation-idempotency keys**. It must not silently retry ambiguous calls.

This phase does not introduce a real idempotency ledger, outbox, transactionally bound login/session store or secure application retry policy.

### Physical outage and AOF recovery

The existing Phase 7.22 Docker CI fixture is reused for the integration suite **while its test Redis remains alive**. The runner marks the exact container \`loomera.phase723=synthetic\`, verifies its expected unique run ID/attempt name, and allows test code to stop/start **only that container**. While it is physically stopped, both test-only issuer and verifier must return \`backend_unavailable\` and never grant or claim a success. When restarted, Redis 7.4 AOF recovery must preserve the already-written record bytes and both counters; one test-only verify may consume the record, and cooldown still blocks a new issue.

This is physical **single-node process recovery**, not cluster quorum, multihost failover, global auth durability or host-bypass fencing. Redis restart is performed in the disposable CI container; no Production Redis is touched.

Additional tests check one correct single winner across two independent verification clients, wrong attempt + valid consume on an issued fixture, exhausted attempt, cooldown after consumption, genuine SHA-1 legacy serializer compatibility, stale generation replacement race, invalid pickle/wrong TTL and strict endpoint/grant rejection. Tests never create users, sessions, send SMS or use real phone/IP data.

The Fast job guards source imports and all real permissions being false, exact Docker label and container-name checks, no wildcard Redis cleanup, and the machine-readable **BLOCKED** release matrix. All prior Fast/Redis/Chromium/PostGIS tests remain.

## Outstanding Production work

\`apps/api/v1/auth_otp.py\` still performs **non-atomic** \`cache.get → compare_digest → cache.delete\` and ignores a false \`cache.delete()\` result. The live issuer likewise performs multiple independent cache check-and-set operations. This experimental component **does not repair either vulnerability**.

Other gates: explicit operation idempotency and duplicate-charge policy, rate/cooldown abuse prevention, real request IP trust boundary, SMS provider/outbox delivery, safe migration/drain of historical OTP/web/password-reset sessions, consistent account/session authorization and rollback, audit of unsafe pickle trust boundary, and every Redis writer fenced during failover including old-primary host ingress as shown in Phase 7.19.

**Release gate: BLOCKED.** No Production rollout, no real authentication code changes and no implicit approval from a green CI run.
