# Phase 7.36 — opt-in atomic legacy OTP issuance, cooldown and quotas

**Default OFF. No deployment. Production release remains BLOCKED.**

Pinned base main: 2e9cdaa948a3adc85cce589dc63268df59887ee9. Phase 7.35 main postmerge run 43736998617 succeeded 4/4.

## Previous gap and bounded security change

The live API formerly checked resend cooldown, read/wrote mobile and IP hourly counters, then stored a challenge and resend marker in separate cache operations. Concurrent requests could pass quota checks, overwrite each other's records or leave partially mutated state if another step failed.

Phase 7.36 adds a single-node WATCH/MULTI/EXEC four-key issuer. It is invoked only with LOOMERA_API_AUTH_OTP_ATOMIC_REDIS_ISSUE=True, **False by default**. Startup and runtime both require the named dedicated otp Redis cache alias, a fail-closed cache policy and Phase 7.35 atomic verification enabled. No unsafe fallback to sequential cache operations is allowed when opted in. Existing deployment behavior stays unchanged while the flag is off.

For the record, the issuer checks presence and TTL but does not deserialize existing Pickle bytes. For cooldown and rate counters it strictly parses canonical ASCII decimal Redis STRING bytes, without using the Pickle deserializer. Only the newly constructed record is serialized/round-trip checked before writing.

The issuer watches the existing Django-Redis-format physical keys **before any reads**: challenge record, resend marker, mobile hourly quota and IP hourly quota. A successful issue queues precisely four SET commands in one MULTI and requires four confirmed True replies from EXEC. Existing unexpired challenges or resend markers deny reissue without charging quota. Only opted-in semantics change: unlike the default legacy issuer, a pending challenge will not be overwritten merely because cooldown elapsed. Two simultaneous issuers or two different mobiles sharing one IP quota cannot both consume the same available slot on one Redis node.

Each new challenge stores only a salted HMAC digest (not a plaintext OTP). API delivery mode remains **simulated**: no SMS is sent, user created or session authenticated. Mobile and IP quota counters use the original hourly Django-Redis integer STRING representation. New counters get a 3600s TTL; existing counters are updated through SET XX KEEPTTL without extending their lifetime.

In the opt-in path, the IP quota is based solely on directly observed REMOTE_ADDR, NOT HTTP X-Forwarded-For, which is untrusted unless ingress sanitization has been independently verified. This may conservatively throttle users sharing a reverse-proxy address. Invalid or missing peer addresses cause HTTP 503 rather than trusting a spoofable forwarded value.

**Fail-closed behavior:** WATCH conflicts, unexpected Redis types or TTLs, corrupt serialized legacy data, malformed numeric counters, unsupported serializer/client, malformed or lost EXEC replies and backend errors yield HTTP 503. Pending challenge/cooldown and exhausted mobile/IP limits yield HTTP 429 with the existing scope and positive Redis-PTTL-derived retry-after. A lost EXEC reply is *not proof of issuance*: Redis may already have applied the transaction, and there is no automatic retry.

## Tests and limitations

Fast checks cover actual API dispatch, default-off status, named alias and fail-closed guards, 429/503 mapping, no raw credentials or mobile in API error output, key names, one clock bucket and spoofed X-Forwarded-For denial. Real Redis 7.4 tests reuse only the existing Phase 7.22 disposable container on 127.0.0.1:6414 DB15 with separate random Phase 7.36 key prefixes and exact-key cleanup, without SCAN/FLUSH. Scenarios include all four committed keys, cooldown, quotas, TTL retention, same-key two-worker races, different mobiles contending on one IP, same-byte ABA rewrite, malformed wire/TTL, lost post-EXEC acknowledgement and incorrect backend rejection.

**Explicit release blockers:** Single-node WATCH is not multi-primary fencing or global consensus; old-primary raw Redis ingress and production ACL grants are not attested. Cross-request idempotency is absent; an ambiguous EXEC error may still consume quota and create a challenge while returning 503. Durable SQL-first SMS outbox, provider delivery, cross-store session/account consistency, trusted proxy IP attribution, legacy web/password reset drain and remote pickle storage trust remain unproven. Operator cutover needs separate architecture/security review, migration/drain, failover fencing and reversible runbook.

**Production release: BLOCKED. Production cutover: NOT AUTHORIZED. Deployment: NONE.**
