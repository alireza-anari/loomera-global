# Phase 7.33 — physical Redis ACL role isolation and adversarial overlap

**CI-only Redis 7.4 behavioral tests. No live Redis, staging/production credentials, authentication changes, deployment or release approval.**

Pinned baseline: `main` `39ac7b454eff2fd19dba6acb2a5749f5764bbd37`. Phase 7.32 postmerge CI `43723897122` completed with four successful jobs.

## Rationale and disposable fixture

Phase 7.32's PASS describes distinct Redis URL principals, but does not verify server-side ACL grants. This phase exercises four *actual* named ACL accounts in a standalone Redis 7.4-alpine container, exclusively `127.0.0.1:6433` and DB15, started by the GitHub Redis CI job. It uses random per-run test credentials, refuses occupied ports and pre-existing containers, requires an explicit CI grant and removes only its own container. It has no Redis volume, external endpoint, user, account, SMS or session state, or production settings. The existing 6379 service is untouched.

Four named accounts (`general`, `otp`, `broker`, `result`) get only `GET`, `SET`, `DEL`, `EXISTS`, `PTTL`, `EXPIRE`, `PING`, `SELECT` and a prefix-scoped ACL key pattern. The OTP fixture uses the actual Django-Redis `KEY_PREFIX=loomera:api-auth-otp-cache` and a random synthetic logical key. It proves real add/get/delete semantics, duplicate `add` denial and positive TTL. All twelve directed cross-role key pairs are checked for actual GET/SET/DEL denial without mutation.

Redis `ACL DRYRUN` verifies the scoped rights and rejects `ACL`, `CONFIG`, `EVAL`, `FLUSHDB`, `FLUSHALL`, `KEYS`, `SCAN` and `PUBLISH` without executing those operations. Anonymous access is rejected.

## Deliberately preserved negative evidence

- A fixture-only privileged administrator still writes raw bytes into the OTP namespace. Scoped user ACLs alone cannot prove global mandatory writer enforcement.
- A distinct named user granted intentionally overbroad `~*` access reads and mutates all four role namespaces. **Different ACL usernames alone do not prove isolation.** This user is turned off and its fixture connection terminated after the negative test.
- The isolated loopback Redis fixture uses plaintext transport; it does **not** establish production TLS/certificate trust.
- The tests do not verify actual Liara Redis ACLs, every host/node/ingress, privileged credentials, stale authenticated sockets, Redis failover, live OTP atomic consumption, SQL outbox/SMS delivery, or session recovery.

The Fast CI job adds static policy guards for the fixture-only boundary; the existing isolated Redis job adds the physical suite. No live application code, settings, migration, deployment workflow or secrets change.

**Production release BLOCKED.** Real service-side ACL review, complete network/credential fencing, live atomic OTP consume, durable delivery/reconciliation and operational/failover signoff remain required. A passing disposable CI fixture does not authorize cutover.
