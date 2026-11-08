# Phase 7.25 — Redis failover and split-brain falsification of OTP idempotency

**Disposable GitHub CI only. No real OTP, customer identity, SMS, user account/session or Production writes. No Production deploy.**

Baseline \`main\`: \`9bb72e4d7a1190df728e32147de849b14958edb9\`. Phase 7.24 independently verified postmerge 4/4 CI \`42451932027\`.

## Security question

Phase 7.24 provides a bounded, **local** idempotency ledger for synthetic OTP issue and verification operations. It WATCHes the exact legacy Django-Redis STRING record and ledger keys on one Redis 7.4 AOF master, then commits both in the same MULTI/EXEC. Losing the EXEC acknowledgment does not double-charge a wrong attempt when the same operation ID is retried **against that same surviving master**.

Does this local guarantee survive **an acknowledged operation on an old primary that did not reach a promoted replica, while both Redis masters remain writable**? Can the same operation ID and even the same legacy OTP be processed twice?

**Expected negative evidence: it does not. This candidate must demonstrate that failure and leave every release permission explicitly FALSE.** Even a confirmed earlier \`WAIT 1\` is insufficient to authorize later partitioned writes.

## Real two-node test topology

A fresh per-run, labeled Docker topology with **two Redis 7.4-alpine servers, separate AOF volumes** and a disposable client container. Distinct networks:

- **Replication-only** bridge, connecting old and replica by explicit names \`p725-old-repl\` and \`p725-new-repl\`.
- **Client-only** bridge, connecting the simulated writer to the two masters. Old client alias \`p725-old-client\` and its real previous IPv4 address are independently tested.
- **Bypass** bridge, through which **host localhost ports 6415 and 6416** remain mapped even after the client bridge is severed. This intentionally reproduces the raw-host bypass from Phase 7.19, not a secure fencing design.

The GitHub CI runner requires \`LOOMERA_PHASE725_TEST_REDIS=1\`, \`GITHUB_ACTIONS=true\`, run ID and attempt. The Python candidate rejects every other endpoint, DB, cache prefix, operation ID, mobile or IP; it accepts only the fabricated placeholders \`09123456789\`, \`09123456780\`, \`09123456781\` and the non-real \`synthetic_ip_01\`. All physical keys belong under \`loomera:phase725:synthetic-two-master-only:<random32>:1:\`. Both containers have exact run-bound names and \`loomera.phase725\` labels. Exit-trap deletes only these exact containers, networks and volumes: never FLUSH, SCAN, wildcard cleanup, real Redis or Production data.

### Genuine wire and CAS semantics

The two-node reenactment reuses Phase 7.24's \`_read_ledger\`, \`_ledger_payload\`, \`_confirmed\` reply checks, and Phase 7.22's pinned Django-Redis 5.4 raw STRING \`_read_present\`/\`_serialized\` helpers, plus Phase 7.21's \`_legacy_record_valid\` verifier. It does **not** modify Phase 7.24 code or relax its strict 6414/15 scope.

The new strictly scoped candidate applies the equivalent Phase 7.24 logic on exactly **6415/15 (old)** and **6416/15 (promoted)**:

- Five-key issuer: WATCH ledger, legacy record, resend, mobile-hour and IP-hour counters before reads; \`MULTI\` SET challenge, cooldown, counter with EX or XX KEEPTTL, second counter, and operation ledger; strict five-command EXEC reply.
- Two-key verifier: WATCH ledger and the *same exact* legacy challenge; constant-time digest comparison; \`MULTI\` DEL on match or SET XX KEEPTTL for wrong code plus operation ledger; exact two-command EXEC reply.
- Fingerprint is unchanged from Phase 7.24: \`SHA256("phase724|v1|" + kind + "|" + mobile + "|" + synthetic_ip_tag + "|" + code_digest)\`. Local reuse of an ID with a different digest is rejected. This validation is scoped to whichever master has the ledger entry; it cannot inspect the disconnected master.
- Every result, even two local \`synthetic_issued\` or \`synthetic_single_winner\` statuses, **explicitly denies real authentication and session grant**.

## Four staged physical experiments

**1. Replicated baseline.** Create synthetic challenge A and C on the old primary with operation-ledger entries, then issue \`SET marker\` plus \`WAIT 1 5000\` on the **same Redis connection**. Independently compare every raw legacy record, ledger, resend and rate counter byte on the replica, with positive bounded TTL. This proves that A and C were actually replicated before the partition; merely receiving \`REPLICAOF OK\` or the replica role is not accepted as evidence.

**2. Split-brain promotion and contradictory operations.** Physically disconnect the replication-only network from the replica, kill its previous master connection, demand \`master_link_status:down\`, and execute \`REPLICAOF NO ONE\`. Verify both nodes report \`role:master\`. Now launch two concurrent workers behind a barrier, using the **same synthetic operation ID** for challenge B but **different fake code digests**: one against the old master and one against the promoted master. Both locally return \`synthetic_issued\`. Their ledger fingerprints and challenge bytes contradict one another, while each local fingerprint guard still rejects the other digest.

A and C were previously **identical** on both nodes. The same verification operation ID correctly consumes A on **both** independent masters—two locally confirmed successes on one originally replicated OTP. Likewise a wrong verification operation ID for C increments attempts on each; a further old-only wrong operation yields different attempt counts (2 vs 1).

The shared synthetic IP hourly counter had A and C = 2 before partition, but **both** independent B issuances each advance their local count to 3. Across the two masters, four total successful synthetic issue events occurred against a limit of 3: the global rate rule fails even while each standalone node is within its limit.

**3. Client-only network fencing and raw host bypass.** Physically remove only the old server from the simulated client bridge. Verify the surviving client container cannot send a Redis EVAL to the old DNS alias or the old actual client-interface IPv4 address. Meanwhile the old host-local published Redis endpoint still accepts a **test-key-only raw EVAL write**. The promoted master's corresponding key is untouched. The observer sees two writable masters, contradictory B ledger/record bytes and host-bypass evidence; it has **no ability to elect an authority or authorize a release**.

**4. AOF restart preservation.** After checking exact Docker labels, stop and restart only those two disposable Redis containers. Check both still advertise master and physically retained independent AOF histories: contradictory B ledger and code; old-only raw marker; independently committed A consumed ledgers; and divergent C wrong-attempt budgets (2 vs 1). No AOF restart automatically reconciles the two histories.

## Release verdict

The expected finding is an **explicit counterexample**, not a repair. A per-record Redis WATCH transaction plus operation ledger prevents double execution only *per reachable master*. \`WAIT 1\` before a partition does not imply all later writes are replicated, and cutting one client network does not block other privileged old-primary routes. AOF on two masters can preserve contradictory ledger outcomes. **Never infer global exactly-once behavior, replay resistance, a unique session grant or Production readiness from these tests.**

Current live \`apps/api/v1/auth_otp.py\` remains unchanged, with non-atomic get → compare → delete, incorrect handling of \`cache.delete(False)\`, and separate non-atomic issue/resend/rate mutations. No real SMS outbox, trusted client operation-ID provenance, global old-primary fencing, secure consensus, account/session cross-store atomicity, historical OTP migration or owner/security approval exists in this change.

**Production release gate: BLOCKED.** Next credible implementation step is an independently reviewed single-writer/fencing authority across every ingress (including raw host old-master writers), then hardened real OTP operation protocol and explicit approval; not another optimistic claim that Redis replication alone solves this.
