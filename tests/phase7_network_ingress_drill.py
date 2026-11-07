"""Phase 7.19 REAL disposable Docker network-ingress preflight.

Only 127.0.0.1:6410/6411 Redis DB15 on a GitHub Actions runner. Every
marker is synthetic; no OTP, Django session or production Redis keys.
"""
from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager

import redis

from loomera.globalization.otp_network_ingress_evidence_policy import (
    IngressNodeObservation, review_ingress_partition,
)

PREFIX = "loomera:phase719:synthetic-network-only:"
PORTS = (6410, 6411)
RAW_SCRIPT = "return redis.call('HSET', KEYS[1], 'writer', ARGV[1])"


def guard():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")
            or os.environ.get("LOOMERA_PHASE719_TEST_REDIS") != "1"):
        raise RuntimeError("Phase 7.19 requires explicit disposable GitHub CI")
    ident = os.environ.get("LOOMERA_PHASE719_ID", "")
    if re.fullmatch(r"[0-9a-f]{32}", ident) is None:
        raise RuntimeError("random synthetic fixture ID required")


def key():
    return PREFIX + os.environ["LOOMERA_PHASE719_ID"] + ":state"


def probe_key():
    return PREFIX + os.environ["LOOMERA_PHASE719_ID"] + ":probe"


@contextmanager
def node(port):
    if port not in PORTS:
        raise ValueError("only two fixed loopback Redis nodes allowed")
    c = redis.Redis(
        host="127.0.0.1", port=port, db=15,
        socket_timeout=3, socket_connect_timeout=2,
        retry_on_timeout=False,
    )
    try:
        assert c.ping() is True
        assert c.config_get("appendonly").get("appendonly") == "yes"
        assert c.config_get("appendfsync").get("appendfsync") == "always"
        yield c
    finally:
        c.close()


def require_role(c, expected):
    assert c.info("replication")["role"] == expected, "unexpected Redis role"


def require_same(old, promoted):
    assert old.hgetall(key()) and old.hgetall(key()) == promoted.hgetall(key()), (
        "initial synthetic marker snapshots diverged"
    )


def seed():
    with node(6410) as old, node(6411) as promoted:
        require_role(old, "master")
        require_role(promoted, "slave")
        assert promoted.info("replication")["master_link_status"] == "up"
        assert old.hset(key(), mapping={"epoch": "1", "writer": "seed"}) >= 0
        assert old.wait(1, 5000) >= 1, "replication ACK absent"
        require_same(old, promoted)
    print("Phase 7.19: source and replica WAIT 1, AOF, exact marker match")


def bridge_before():
    with node(6410) as old, node(6411) as promoted:
        require_role(old, "master")
        require_role(promoted, "slave")
        assert old.hget(key(), "writer") == b"bridge-before"
        assert old.wait(1, 5000) >= 1, "raw bridge writer not replicated"
        require_same(old, promoted)
    print("Phase 7.19: real client-container raw EVAL to old primary and WAIT 1")


def after_partition():
    with node(6410) as old, node(6411) as promoted:
        require_role(old, "master")
        require_role(promoted, "master")
        require_same(old, promoted)
        assert old.set(probe_key(), "after-replication-break", ex=60)
        assert old.wait(1, 1500) == 0, "replication network not isolated"
        assert promoted.get(probe_key()) is None, "source probe crossed partition"
        assert old.hget(key(), "writer") == b"bridge-before"
    print("Phase 7.19: two RAW masters and data replication WAIT 0 confirmed")


def before_client_fence():
    with node(6410) as old, node(6411) as promoted:
        require_role(old, "master")
        require_role(promoted, "master")
        assert old.hget(key(), "writer") == b"stale-client"
        assert promoted.hget(key(), "writer") == b"bridge-before"
        assert old.hgetall(key()) != promoted.hgetall(key())
    print("Phase 7.19: stale client network write to old master succeeded pre-fence")


def after_client_fence():
    with node(6410) as old, node(6411) as promoted:
        require_role(old, "master")
        require_role(promoted, "master")
        assert old.hget(key(), "writer") == b"stale-client", (
            "client network fence must not modify prior old record"
        )
        assert promoted.hget(key(), "writer") == b"promoted-client"
        # NEGATIVE: a separate loopback-published, bypass-bridge data path
        # remains reachable to the still-writable old Redis primary.
        raw_reply = old.eval(RAW_SCRIPT, 1, key(), "host-bypass")
        assert type(raw_reply) is int and raw_reply in (0, 1)
        assert old.hget(key(), "writer") == b"host-bypass"
        assert promoted.hget(key(), "writer") == b"promoted-client"
        assert old.hgetall(key()) != promoted.hgetall(key())

        evidence = (
            IngressNodeObservation("old", "master", False, False, True),
            IngressNodeObservation("promoted", "master", True, True, True),
        )
        review = review_ingress_partition(
            evidence, replication_partition_verified=True,
        )
        assert review.status == "bridge_fenced_but_host_bypass_open"
        assert review.operator_review_required
        for field in ("authentication_allowed", "otp_consume_allowed",
                      "otp_issue_allowed", "real_session_created",
                      "production_write_allowed", "old_master_globally_fenced",
                      "alternate_ingress_eliminated", "distributed_consensus_proven",
                      "recovery_authorized", "legacy_fallback_allowed"):
            assert getattr(review, field) is False, field
    print("Phase 7.19: old client bridge raw EVAL denied, HOST raw old-master EVAL STILL ACCEPTED")


def main():
    guard()
    stages = {
        "seed": seed,
        "bridge-before": bridge_before,
        "after-partition": after_partition,
        "pre-client-fence": before_client_fence,
        "post-client-fence": after_client_fence,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in stages:
        raise SystemExit("expected: " + "|".join(stages))
    stages[sys.argv[1]]()


if __name__ == "__main__":
    main()
