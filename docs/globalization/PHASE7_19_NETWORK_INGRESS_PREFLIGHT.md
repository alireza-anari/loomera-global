# Phase 7.19 — real Redis client-network cut and alternate-ingress raw-writer bypass

**Synthetic CI only, NEVER Production.** No accounts, customer OTPs, sessions, credentials, migrations, settings changes, application auth rewiring, or deployment.

Baseline main: \`e721094a72416e167de45ec4ec088147045fa0fc\`. Phase 7.18 postmerge CI run \`42407228524\` independently passed Fast, Redis, Chromium and PostGIS.

## Why this experiment

Phase 7.17 showed a voluntarily majority-gated gateway can be bypassed by raw Redis. Phase 7.18 showed promoted-node ACL revocation does not propagate to a partitioned old master. Phase 7.19 tests an **actual Docker network detach** at the old master's client ingress rather than a caller-side policy.

Only the *specified client bridge* is physically fenced. The old master intentionally remains reachable through a **different, independent Docker management/bypass bridge and a loopback-published host port**. This is a negative demonstration that network isolation has a scope: cutting one interface does not stop raw writers on another interface.

## Topology / test steps

Three dedicated Docker bridges: **client**, **replication**, and **bypass**. Two Redis 7.4-alpine AOF data containers with distinct short-lived volumes; the host port mappings are fixed to **127.0.0.1:6410/6411**, DB15. A third disposable Redis image serves solely as an **unprivileged network client**, attached ONLY to the client bridge and with no published ports. The existing Redis 6379 and all non-test bridges are untouched.

1. With both data nodes on the replication and client bridges, set the new data node to replica. Verify an actual upstream link, seed a fake hash marker, require **WAIT 1**, identical replica snapshot, and an actual raw client-container EVAL to the old primary.
2. Disconnect ONLY the promoted node from the replication bridge, kill its old upstream connection, demand link down, issue a fresh source-only probe, require **WAIT 0** and verify the promoted copy never received the probe. Manually promote; require **two writable masters**.
3. Before client fencing, the client-container writes a fresh fake value directly to the **old** master and the two data nodes diverge. This confirms a genuine raw client path existed and worked before the cut.
4. Record the old master's previous client-network IP and disconnect the **old data container** from the client bridge. From the unchanged client container, require both old DNS alias **and former IP** requests to fail; require fresh EVAL on the promoted master through the same client bridge to work. Thus not merely a DNS-label change.
5. From the separate host/bypass network, execute raw Redis EVAL against the **old still-writable master**. It still accepts a new fake value while the client bridge rejects it. The two Redis data copies remain divergent. This is explicit negative evidence against claims of complete fencing.

The old master remains on the bypass and replication-only bridges, which is intentional. There is **no rejoin, automatic conflict resolution, migration, or live recovery**; test resources are destroyed by an EXIT trap.

## Validation and limitations

The network policy takes exactly two ordered typed observations (old/promoted) and a strict partition flag. No result authorizes OTP issue/consume, account authentication, a real Django session, Production writes, Redis multihost consensus, global old-master fencing, reconfiguration, or legacy fallback. Invalid evidence fails closed. Fast tests check guards, CI script isolation, no-live imports and machine-readable BLOCKED matrix. The real Redis integration runs after Phases 7.7–7.18, preserving Chromium/PostGIS.

This experiment runs on **one GitHub runner**. It does NOT prove existing long-lived TCP connections or other credentials are revoked, nor a secure multi-host network policy/CNI/firewall, ACL correctness, quorum fencing, emergency credential rotation, failover, protected management ports, or all possible raw access routes. It intentionally retains a privileged host-bypass path to prove the gap. A real deployment would need a separately reviewed enforceable network/credential boundary across every writer ingress, authenticated durable consensus or trusted write-side authority, and controlled recovery.

The live API \`apps/api/v1/auth_otp.py\` still uses cache \`get → compare → delete\` and ignores \`delete(False)\`, so its possible concurrent replay remains **UNFIXED**; legacy Django-Redis pickled STRINGs are incompatible with these fake HASH markers. Production release stays **BLOCKED** until those issues, real account/session atomicity, privacy, security and owner signoffs, and deployment authorization are independently resolved. Do not copy these test network or Redis settings into Production.
