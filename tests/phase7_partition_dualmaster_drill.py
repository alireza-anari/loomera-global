"""Phase 7.15 real Redis replication-network partition and dual-master CI drill.

Driver stages use only two isolated Redis Docker containers and a test-only
local SQLite witness. This intentionally demonstrates raw Redis writes bypass
the witness and that one local file is NOT quorum/consensus-backed fencing.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
import time

import redis

from loomera.globalization.otp_partition_witness_rehearsal import (
    SyntheticLocalPartitionWitness, SyntheticWitnessState, fixture_witness_path,
)
from loomera.globalization.otp_partition_redis_rehearsal import (
    PREFIX, SyntheticMarkerObservation, SyntheticPartitionMarkerFence,
)
from loomera.globalization.otp_restart_marker_rehearsal import FENCE_SCRIPT

SOURCE = "redis://127.0.0.1:6395/15"
PROMOTED = "redis://127.0.0.1:6396/15"
LABELS = (
    ("observing", "LOOMERA_PHASE715_OBSERVING_ID"),
    ("quarantined", "LOOMERA_PHASE715_QUARANTINED_ID"),
    ("halted", "LOOMERA_PHASE715_HALTED_ID"),
)


@contextmanager
def redis_client(url):
    client = redis.Redis.from_url(
        url, socket_timeout=5, socket_connect_timeout=5,
        retry_on_timeout=False,
    )
    try:
        assert client.ping() is True
        assert client.config_get("appendonly").get("appendonly") == "yes"
        assert client.config_get("appendfsync").get("appendfsync") == "always"
        yield client
    finally:
        client.close()


def witness():
    wid = os.environ["LOOMERA_PHASE715_WITNESS_ID"]
    return SyntheticLocalPartitionWitness(
        fixture_id=wid, path=fixture_witness_path(wid),
    )


def marker_keys(name):
    fid = os.environ[dict(LABELS)[name]]
    return (PREFIX + fid + ":reference", PREFIX + fid + ":volatile")


def gates(client, node):
    return {
        name: SyntheticPartitionMarkerFence(
            client, fixture_id=os.environ[env], node=node, witness=witness(),
        )
        for name, env in LABELS
    }


def no_grant(result):
    for attr in (
        "authenticated", "session_created", "can_resume",
        "can_seed_on_restart", "safe_to_retry",
        "legacy_fallback_authorized", "production_recovery_authorized",
    ):
        assert getattr(result, attr) is False, (attr, result)


def check(label, observed, expected):
    assert observed == expected, (label, observed, expected)
    if isinstance(observed, SyntheticMarkerObservation):
        no_grant(observed)
    else:
        assert isinstance(observed, SyntheticWitnessState)
        for field in (
            "authenticated", "session_created", "can_resume", "can_reseed",
            "safe_to_retry", "external_consensus_proven",
            "production_cutover_authorized", "legacy_fallback_authorized",
        ):
            assert getattr(observed, field) is False, (label, field, observed)


def before():
    return {
        "observing": SyntheticMarkerObservation("observing", 1),
        "quarantined": SyntheticMarkerObservation(
            "quarantined", 2, "replica_stale",
        ),
        "halted": SyntheticMarkerObservation("halted", 2),
    }


def promoted_fork():
    return {
        "observing": SyntheticMarkerObservation(
            "quarantined", 2, "replica_stale",
        ),
        "quarantined": before()["quarantined"],
        "halted": before()["halted"],
    }


def snapshots(client):
    found = {}
    for name, _ in LABELS:
        for key in marker_keys(name):
            data = client.hgetall(key)
            assert data, ("fixture key lost", key)
            assert client.pttl(key) > 0, ("fixture TTL absent", key)
            found[key] = data
    return found


def sync_exact(master, follower, *, label):
    current = snapshots(master)
    for _ in range(60):
        try:
            mirror = snapshots(follower)
            if mirror == current:
                return
        except AssertionError:
            pass
        time.sleep(0.15)
    raise AssertionError(("replication mismatch", label, current, snapshots(follower)))


def prepare():
    assert os.environ.get("LOOMERA_PHASE715_ACTIVE_LEADER") == "original"
    assert os.environ.get("LOOMERA_PHASE715_ALLOW_TEST_SEED") == "1"
    assert os.environ.get("LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION") == "1"
    with redis_client(SOURCE) as source, redis_client(PROMOTED) as replica:
        assert source.info("replication")["role"] == "master"
        replica_info = replica.info("replication")
        assert replica_info["role"] == "slave", replica_info
        assert replica_info.get("master_link_status") == "up", replica_info
        w = witness()
        check(
            "prepare SQLite independent file witness",
            w.initialize_test_fixture(),
            SyntheticWitnessState("initialized", 1),
        )
        assert w.inspect() == SyntheticWitnessState("observing", 1)
        primary = gates(source, "original")
        for name, gate in primary.items():
            check(
                "fixture initialize " + name,
                gate.initialize_disposable_fixture_for_test(),
                SyntheticMarkerObservation("initialized", 1),
            )
        check(
            "initial quarantine",
            primary["quarantined"].quarantine(
                expected_generation=1, cause="replica_stale",
            ),
            before()["quarantined"],
        )
        check(
            "terminal halt",
            primary["halted"].halt(expected_generation=1),
            before()["halted"],
        )
        for name in before():
            check(name, primary[name].inspect(), before()[name])

        ack = source.wait(1, 5000)
        assert type(ack) is int and ack >= 1, ("WAIT replica ack absent", ack)
        sync_exact(source, replica, label="before partition")
    print("Phase 7.15: initial exact AOF marker replication and WAIT=1 confirmed")


def during_partition():
    assert os.environ.get("LOOMERA_PHASE715_ALLOW_TEST_SEED") != "1"
    assert os.environ.get("LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION") != "1"
    with redis_client(SOURCE) as source, redis_client(PROMOTED) as promoted:
        assert source.info("replication")["role"] == "master"
        assert promoted.info("replication")["role"] == "master"

        # Both are simultaneously writable RAW Redis masters: the original
        # survives while its replica has been promoted in a real partition.
        forkkey = PREFIX + os.environ["LOOMERA_PHASE715_OBSERVING_ID"] + ":fork"
        source.set(forkkey, "old-primary-branch", ex=600)
        promoted.set(forkkey, "promoted-primary-branch", ex=600)
        assert source.get(forkkey) == b"old-primary-branch"
        assert promoted.get(forkkey) == b"promoted-primary-branch"

        # A raw client can bypass local app configuration and mutate a marker
        # on the promoted branch. DO NOT reuse this bypass for production.
        keys = marker_keys("observing")
        raw = promoted.eval(
            FENCE_SCRIPT, 2, *keys,
            os.environ["LOOMERA_PHASE715_OBSERVING_ID"],
            "quarantine", 1, "replica_stale",
        )
        assert raw[0] == b"quarantined" and raw[1] == 2, raw
        assert source.hget(keys[0], "generation") == b"1"
        assert promoted.hget(keys[0], "generation") == b"2"
        assert snapshots(source) != snapshots(promoted)

        # Both local Redis roles claim master. A role check alone is insufficient.
        with os_environ("LOOMERA_PHASE715_ACTIVE_LEADER", "original"):
            check(
                "unsafe original local observation",
                gates(source, "original")["observing"].inspect(),
                before()["observing"],
            )
        with os_environ("LOOMERA_PHASE715_ACTIVE_LEADER", "promoted"):
            check(
                "unsafe promoted local observation",
                gates(promoted, "promoted")["observing"].inspect(),
                promoted_fork()["observing"],
            )

        w = witness()
        check(
            "external test-only SQLite halt",
            w.halt(expected_generation=1, reason="dual_master"),
            SyntheticWitnessState("halted", 2, "dual_master"),
        )
        with os_environ("LOOMERA_PHASE715_ACTIVE_LEADER", "original"):
            gate = gates(source, "original")["observing"]
            check("stale primary denied", gate.inspect(),
                  SyntheticMarkerObservation("witness_halted"))
            check("stale primary mutation denied",
                  gate.quarantine(expected_generation=1, cause="replica_stale"),
                  SyntheticMarkerObservation("witness_halted"))
        with os_environ("LOOMERA_PHASE715_ACTIVE_LEADER", "promoted"):
            gate = gates(promoted, "promoted")["observing"]
            check("promoted primary denied", gate.inspect(),
                  SyntheticMarkerObservation("witness_halted"))
            check("promoted primary mutation denied",
                  gate.halt(expected_generation=2),
                  SyntheticMarkerObservation("witness_halted"))
    print(
        "Phase 7.15: REAL replication partition produced TWO writable raw masters "
        "and divergent marker epochs; local witness terminal halt denied adapter"
    )


class os_environ:
    """Restore only the selected synthetic CI leader variable."""

    def __init__(self, name, value):
        self.name, self.value = name, value

    def __enter__(self):
        self.old = os.environ.get(self.name)
        os.environ[self.name] = self.value

    def __exit__(self, *_):
        if self.old is None:
            os.environ.pop(self.name, None)
        else:
            os.environ[self.name] = self.old


def after_rejoin():
    assert os.environ.get("LOOMERA_PHASE715_ALLOW_TEST_SEED") != "1"
    assert os.environ.get("LOOMERA_PHASE715_ALLOW_FIXTURE_MUTATION") != "1"
    with redis_client(SOURCE) as old, redis_client(PROMOTED) as promoted:
        assert old.info("replication")["role"] == "slave"
        assert old.info("replication").get("master_link_status") == "up"
        assert promoted.info("replication")["role"] == "master"
        sync_exact(promoted, old, label="after explicit old-primary demotion")
        assert promoted.get(
            PREFIX + os.environ["LOOMERA_PHASE715_OBSERVING_ID"] + ":fork"
        ) == b"promoted-primary-branch"
        assert old.get(
            PREFIX + os.environ["LOOMERA_PHASE715_OBSERVING_ID"] + ":fork"
        ) == b"promoted-primary-branch"

        try:
            old.hset(marker_keys("observing")[0], "generation", "5")
        except redis.exceptions.ReadOnlyError:
            pass
        else:
            raise AssertionError("rejoined old primary accepted raw write")

        # Even though Redis data converged, the external witness remains
        # terminal halt; automatic login/OTP recovery is NEVER allowed.
        attached = witness()
        check(
            "SQLite witness survived Python process and rejoin",
            attached.inspect(),
            SyntheticWitnessState("halted", 2, "dual_master"),
        )
        with os_environ("LOOMERA_PHASE715_ACTIVE_LEADER", "promoted"):
            for name, gate in gates(promoted, "promoted").items():
                check(
                    "rejoined but still blocked " + name,
                    gate.inspect(), SyntheticMarkerObservation("witness_halted"),
                )
        with os_environ("LOOMERA_PHASE715_ACTIVE_LEADER", "original"):
            check(
                "old replica still blocked",
                gates(old, "original")["observing"].inspect(),
                SyntheticMarkerObservation("witness_halted"),
            )
    print(
        "Phase 7.15: old master rejoined read-only, divergent data converged "
        "but independent local witness remained terminal HALTED"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "during-partition", "after-rejoin"))
    stage = parser.parse_args().stage
    if os.environ.get("LOOMERA_PHASE715_TEST_REDIS") != "1":
        raise RuntimeError("explicit disposable network test grant required")
    if os.environ.get("LOOMERA_PHASE715_WITNESS_TEST") != "1":
        raise RuntimeError("explicit disposable witness test grant required")
    {"prepare": prepare, "during-partition": during_partition,
     "after-rejoin": after_rejoin}[stage]()


if __name__ == "__main__":
    main()
