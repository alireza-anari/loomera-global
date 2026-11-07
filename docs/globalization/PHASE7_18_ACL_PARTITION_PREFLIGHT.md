# Phase 7.18 — real Redis ACL control-plane partition preflight

**Only disposable synthetic test data. No Production, OTP, accounts, customer sessions, real credentials, migration, configuration or deployment.**

Baseline main: 83a3b36cceb53a61b9f78dbe553fef4f0c8f5c5c. Phase 7.17 independently verified postmerge CI run 42404645311: Fast, Redis, Chromium and PostGIS passed.

## Why this matters

Phase 7.17 showed that two-of-three local test-witness votes and a voluntary Python gateway do not fence raw writers on the old Redis primary. This follow-up tests the **real ACL control plane** instead of assuming an out-of-process permission check protects the write side.

Two Redis 7.4-alpine servers on separate AOF volumes replicate a synthetic marker (actual WAIT 1 and identical snapshots). The shell driver disconnects only the replication network; old and promoted nodes become two masters. A post-disconnect source probe returns **WAIT 0** and is absent on the promoted node.

On each data server, test-only administrators create one prefix-scoped EVAL/HSET legacy writer and one read-only principal, with random ephemeral passwords. They disable the unrestricted default user on both. Only the promoted server disables the legacy writer. **The identical stale credential still authenticates and executes raw EVAL against the old master**, despite the promoted node's ACL revocation and its restricted default user. Prefix/readonly probes deny unauthorized writes on both nodes.

Finally, a separate authenticated admin connection to the old node *on the same runner* explicitly disables the old stale principal and kills its clients. A fresh old-master stale credential now fails. This is only a **local** node ACL change when the administrator can reach the old node: no remote revocation ledger, independent durable quorum, fail-safe multi-host partition or globally enforced write fence was proven. The synthetic data remains divergent until a separate controlled data recovery procedure.

## Safety and implementation boundaries

- Only isolated localhost 6408/6409, Redis logical DB15, two temporary Docker bridges and AOF volumes. Standard CI Redis 6379 is never changed.
- The stage driver refuses requests without the GitHub Actions CI context, explicit Phase 7.18 environment grant, random 32-hex ephemeral identities/passwords or the expected fixed test ports. The shell uses an EXIT cleanup trap for *only its own resources*.
- Test admin permissions are deliberately powerful **only inside these disposable containers**; they are neither appropriate for live Redis nor a secure key rotation/compromise response recipe.
- The pure offline observation policy always denies authentication, session creation, OTP consumption, production writes, global fencing and legacy fallback even for observed local revocation. Fast tests enforce strict type/order, failure outcomes, no-live-wiring and the blocked release matrix.
- All earlier Phase 7.7–7.17 Redis and Fast tests, Chromium and PostGIS must remain in CI.

## Production release remains BLOCKED

The ACL experiments cannot revoke credentials across an unreachable network partition, ensure all raw/legacy writers have lost access, authenticate multihost consensus, fence privileged connections or coordinate OTP/account/session transactions. Real apps/api/v1/auth_otp.py still has cache get→compare→delete and ignores a deletion returning False: concurrent OTP replay is **not fixed**. Synthetic HASH markers are incompatible with live Django-Redis serialized STRING records. Signed security/owner/operations approvals, external enforceable write-side isolation, actual multihost failover testing and separate controlled rollout are all absent.

**Release verdict: BLOCKED. Never deploy these CI ACLs or this experimental code as an authentication fix.**
