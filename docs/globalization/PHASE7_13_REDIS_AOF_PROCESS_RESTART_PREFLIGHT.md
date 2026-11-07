# Phase 7.13 — Actual isolated Redis 7.4 AOF process-restart preflight

**Synthetic-only, standalone GitHub CI rehearsal. No live authentication, production cache, real account, OTP, password-reset grant, Django session, real migration or deployment.**

Baseline main: 753966d8984ac003a379f4e07c639c8a4435e31c. Phase 7.12 post-merge CI 42386617119 passed all Fast, Redis, Chromium and PostGIS jobs.

## What this phase genuinely adds

Phase 7.12 used a second Redis client and injected missing/stale markers but **did not restart the Redis server process**. Phase 7.13 adds a real Docker process restart **on an isolated, short-lived Redis 7.4-alpine container**, first graceful shutdown/start and then SIGKILL/start, with AOF enabled and appendfsync set to always. Both restarts use the same disposable Docker named volume. A new Python process and a new Redis client reconnect after each real restart to check the synthetic mode, exact generation and immutable halt/quarantine cause before any new test mutation.

This is a **real local standalone Redis process-restart experiment**, but NOT a real failover, Redis Sentinel/Cluster, replica promotion, data-center failure, independent durable anchor or production-safe recovery design. Even successful AOF replay on one CI host cannot guarantee that a real OTP and Django session transaction is durable, atomic or safe.

## Isolated execution boundary

Existing CI Redis service (127.0.0.1:6379): **untouched**. The new container publishes only 127.0.0.1:6392 and uses logical DB15 with unique random 32-character lowercase-hex fixture IDs. Test-only prefix: loomera:phase713:synthetic-aof-only:. The fixture keys have suffixes reference and volatile and inherit the **10-minute test TTL** of the Phase 7.12 Lua scripts. Both keys and their AOF file are in one Redis failure domain; neither is an independent durable production marker. Official test command uses the redis:7.4-alpine image and is only permitted in GitHub Actions with LOOMERA_PHASE713_TEST_REDIS=1.

The Docker job creates its own uniquely named volume and container using GitHub run ID and attempt, starts Redis with appendonly yes and appendfsync always, and disables RDB snapshots for the drill. The Redis process intentionally disables Redis protected mode *inside the ephemeral CI container*; only its loopback port is published and no real secrets or accounts are present. The shell checks port 6392 is unused, checks Docker and Redis readiness, asserts the AOF configuration and verifies the container started timestamp changes across both restarts. A final EXIT trap deletes **only that job's container and volume**, not other Docker resources or the existing job's Redis service.

Initializer authority is additionally gated by LOOMERA_PHASE713_ALLOW_TEST_SEED=1. This grant exists only during the initial isolated unit tests and initial fixture preparation. It is removed before either process restart and is never enabled during recovery checks. Inspect, quarantine and halt methods have no reseed/repair path. The ordinary wrapper at loomera/globalization/otp_aof_process_restart_rehearsal.py imports the previously exercised two-key Lua CAS scripts from Phase 7.12, but uses a distinct namespace, endpoint and grant. All responses expose authenticated=False, session_created=False, can_resume=False, safe_to_retry=False, can_seed_on_restart=False, no legacy fallback and no production recovery permission.

## Exact restart experiment

Stage 1: The Python driver opens the isolated port, checks Redis config and deliberately seeds three synthetic paired-marker fixtures: observing generation 1, quarantined generation 2 with client_timeout, and terminal halted generation 2. Each is inspected for matching mode and cause. No OTP is verified or session created.

Stage 2: The shell runs an actual docker stop (graceful process shutdown), docker start and config/readiness check using the same named volume. A **new Python process/client** verifies the three markers and generations survived. It then quarantines the observing fixture at generation 2 and halts the quarantined fixture at generation 3, preserving the original cause. Terminal halt refuses re-quarantine.

Stage 3: The shell runs an actual docker kill --signal KILL, docker start, and verifies the process start timestamp changed. A **third Python process/client** checks those committed states survived the abrupt process death via AOF. Stale generation attempts are denied. Only after all persistence checks, a deliberately deleted reference marker must return reference_lost; an injected stale second marker must report split_brain. The recovery process cannot seed replacements.

Important limitations: The three-stage tests establish a specific favorable observation on a GitHub-hosted CI machine, not zero data-loss guarantees for all fsync/file-system failures. RDB, replica consistency, failover on another host, active-active writes, network partition, AOF truncation/corruption and disk exhaustion remain UNTESTED. The ten-minute fixture TTL deliberately prevents permanent retention; it is incompatible with a production routing/incident marker.

## Test coverage / CI

Fast Django CI adds 30 tests in apps/accounts/test_phase7_otp_aof_restart_safety.py for the pure offline AOF-evidence review model in loomera/globalization/otp_aof_restart_policy.py, including missing reference, generation regression, untrusted fsync, ambiguous write acknowledgement, unauthorized session path and explicit no-live-wiring guards.

The existing Redis CI job additionally runs tests/phase7_redis_process_restart_ci.sh. It starts the isolated container and executes 24 real-Redis adapter tests from tests/phase7_aof_restart_fixture_test.py, followed by the 3-stage real process-restart drill in tests/phase7_aof_process_restart_drill.py. Previous Phase 7.7–7.12 Redis checks on port 6379, all Fast checks, Chromium and PostGIS still run and remain mandatory.

Runbook: CI fixture only. Do not invoke the shell script against a developer's normal Docker host, customer workload or remote Redis. Do not mount anything except the job-specific disposable volume. Do not make the explicit seed method part of any startup, authentication, incident recovery or deployment service.

## Release gate: STILL BLOCKED

Before any runtime cutover, independently require:
1. Security/owner/privacy consent and real OTP/account/session inventory without exporting personal credentials or customer records into CI/GitHub.
2. A separately controlled and integrity-protected **durable version marker** that is independent of the volatile Redis failure domain; audited monotone generations across failure/restart and no silent recreation.
3. Actual authorized Redis Sentinel/Cluster, replica promotion, crash-injection, persistence fault, disk-full, lost acknowledgment and network partition testing, including stale writers fenced after promotion.
4. A separately approved fix of the **existing live API OTP read/compare/delete race and delete(False) behavior**. The production Django-Redis serialized STRING/SHA-1 legacy challenge is NOT compatible with the experimental HASH scripts. Require constant-time production-format verification, TTL, atomic attempt budget and resend/cooldown/rate limits.
5. Authoritative DB/account state locking and genuine Django session-store idempotency, account deletion and password-reset grant drain, and recovery from uncertain session write without accidental double grant.
6. Independent security, account owner, session-store owner, privacy, mobile, operations and accessibility signoff, a reviewed incident forward-recovery runbook, and separate deployment approval.

**Production status: BLOCKED.** Passing the isolated AOF drill is evidence only for these synthetic Redis process restarts, not permission to authenticate a user, replay an OTP, resume issuance, create a session, or deploy.
