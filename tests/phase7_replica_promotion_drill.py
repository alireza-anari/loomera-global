"""Phase 7.14 real two-node Redis 7.4 manual replica promotion CI drill.

The shell script creates/stops/promotes/rejoins isolated Docker Redis processes.
This driver only touches synthetic paired marker keys on localhost 6393/6394.
AOF and a replica acknowledge are *test evidence*, not independent consensus.
"""
from __future__ import annotations

import argparse
import os
import time
from contextlib import contextmanager

import redis

from loomera.globalization.otp_replica_promotion_rehearsal import (
    PREFIX, SyntheticMarkerObservation, SyntheticPromotedMarkerFence,
)

PRIMARY_URL = "redis://127.0.0.1:6393/15"
PROMOTED_URL = "redis://127.0.0.1:6394/15"
LABELS = (
    ("observing", "LOOMERA_PHASE714_OBSERVING_ID"),
    ("quarantined", "LOOMERA_PHASE714_QUARANTINED_ID"),
    ("halted", "LOOMERA_PHASE714_HALTED_ID"),
)


@contextmanager
def client(url: str):
    conn = redis.Redis.from_url(
        url, socket_timeout=5, socket_connect_timeout=5,
        retry_on_timeout=False,
    )
    try:
        assert conn.ping() is True
        assert conn.config_get("appendonly").get("appendonly") == "yes"
        assert conn.config_get("appendfsync").get("appendfsync") == "always"
        yield conn
    finally:
        conn.close()


def gates(conn, node):
    return {
        name: SyntheticPromotedMarkerFence(
            conn, fixture_id=os.environ[env_name], node=node,
        )
        for name, env_name in LABELS
    }


def expected_before():
    return {
        "observing": SyntheticMarkerObservation("observing", 1),
        "quarantined": SyntheticMarkerObservation(
            "quarantined", 2, "replica_stale",
        ),
        "halted": SyntheticMarkerObservation("halted", 2),
    }


def expected_after():
    return {
        "observing": SyntheticMarkerObservation(
            "quarantined", 2, "lost_write_reply",
        ),
        "quarantined": SyntheticMarkerObservation(
            "halted", 3, "replica_stale",
        ),
        "halted": SyntheticMarkerObservation("halted", 2),
    }


def denied_auth(label, result):
    for field in (
        "authenticated", "session_created", "can_resume",
        "can_seed_on_restart", "safe_to_retry", "legacy_fallback_authorized",
        "production_recovery_authorized",
    ):
        assert getattr(result, field) is False, (label, field, result)


def exact(label, got, expected):
    assert got == expected, (label, got, expected)
    denied_auth(label, got)


def snapshots(conn):
    found = {}
    for name, fixture_env in LABELS:
        fixture_id = os.environ[fixture_env]
        for suffix in ("reference", "volatile"):
            key = PREFIX + fixture_id + ":" + suffix
            data = conn.hgetall(key)
            assert data, (name, suffix, "missing")
            assert conn.pttl(key) > 0, (name, suffix, "expired")
            found[key] = data
    return found


def matching_snapshots(master, replica, *, label):
    # The following is a bounded, *observational* test of exact fixture data.
    # It is not a proof of durable ack or cross-node linearizability.
    before = snapshots(master)
    for attempt in range(40):
        try:
            after = snapshots(replica)
        except AssertionError:
            after = {}
        if before == after:
            return
        time.sleep(0.15)
    raise AssertionError((label, "replica marker mismatch", before, after))


def check_mode(conn, node, expected):
    gate = gates(conn, node)
    for name in expected:
        exact(name, gate[name].inspect_on_selected_primary(), expected[name])
    return gate


def prepare():
    assert os.environ.get("LOOMERA_PHASE714_ACTIVE_LEADER") == "original"
    assert os.environ.get("LOOMERA_PHASE714_ALLOW_TEST_SEED") == "1"
    with client(PRIMARY_URL) as primary, client(PROMOTED_URL) as replica:
        assert primary.info("replication")["role"] == "master"
        replica_state = replica.info("replication")
        assert replica_state["role"] == "slave", replica_state
        assert replica_state.get("master_link_status") == "up", replica_state

        gate = gates(primary, "original")
        for name in gate:
            exact(
                "initial seed " + name,
                gate[name].initialize_fixture_for_test(),
                SyntheticMarkerObservation("initialized", 1),
            )
        exact(
            "first quarantine",
            gate["quarantined"].quarantine(
                expected_generation=1, cause="replica_stale",
            ),
            expected_before()["quarantined"],
        )
        exact(
            "first terminal halt",
            gate["halted"].halt(expected_generation=1),
            expected_before()["halted"],
        )
        check_mode(primary, "original", expected_before())

        # WAIT runs on the same redis-py client after fixture writes; the
        # independent exact snapshot comparison is a second explicit check.
        ack = primary.wait(1, 5000)
        assert type(ack) is int and ack >= 1, ("replica WAIT unacknowledged", ack)
        matching_snapshots(primary, replica, label="before primary loss")
        try:
            # Replica remains read-only before the promotion.
            replica.hset(
                PREFIX + os.environ["LOOMERA_PHASE714_OBSERVING_ID"] + ":reference",
                "mode", "halted",
            )
        except redis.exceptions.ReadOnlyError:
            pass
        else:
            raise AssertionError("replica unexpectedly accepted synthetic write")
        assert replica.info("replication")["role"] == "slave"
    print("Phase 7.14: master→replica exact synthetic marker replication and WAIT observed")


def after_promotion():
    assert os.environ.get("LOOMERA_PHASE714_ACTIVE_LEADER") == "promoted"
    assert os.environ.get("LOOMERA_PHASE714_ALLOW_TEST_SEED") != "1"
    with client(PROMOTED_URL) as promoted:
        assert promoted.info("replication")["role"] == "master"
        gate = check_mode(promoted, "promoted", expected_before())
        exact(
            "promoted CAS quarantine",
            gate["observing"].quarantine(
                expected_generation=1, cause="lost_write_reply",
            ),
            expected_after()["observing"],
        )
        exact(
            "promoted terminal halt",
            gate["quarantined"].halt(expected_generation=2),
            expected_after()["quarantined"],
        )
        exact(
            "promoted previous halt never reopened",
            gate["halted"].quarantine(
                expected_generation=2, cause="operator_stop",
            ),
            SyntheticMarkerObservation("already_halted", 2),
        )
        exact(
            "promoted stale generation rejected",
            gate["observing"].halt(expected_generation=1),
            SyntheticMarkerObservation("stale_generation", 2, "lost_write_reply"),
        )
        check_mode(promoted, "promoted", expected_after())
        try:
            gate["observing"].initialize_fixture_for_test()
        except RuntimeError:
            pass
        else:
            raise AssertionError("promoted role unexpectedly has fixture seed grant")
    print("Phase 7.14: real replica promotion preserved epochs; CAS remains fail-closed")


def before_rejoin():
    # Redis does NOT inherently fence a restarted former primary. It may come
    # back self-identifying as master while the new leader is promoted.
    # This stage explicitly documents/detects that unsafe split-brain window.
    assert os.environ.get("LOOMERA_PHASE714_ACTIVE_LEADER") == "promoted"
    with client(PRIMARY_URL) as old:
        info = old.info("replication")
        assert info["role"] == "master", info
        stale = gates(old, "original")
        for name in stale:
            result = stale[name].inspect_on_selected_primary()
            exact(name, result, SyntheticMarkerObservation("not_active_leader"))
    print(
        "Phase 7.14: restarted old primary WAS master before reconfiguration; "
        "fixture harness denied it, raw Redis was NOT consensus-fenced"
    )


def after_rejoin():
    assert os.environ.get("LOOMERA_PHASE714_ACTIVE_LEADER") == "promoted"
    with client(PROMOTED_URL) as promoted, client(PRIMARY_URL) as old:
        assert promoted.info("replication")["role"] == "master"
        status = old.info("replication")
        assert status["role"] == "slave", status
        assert status.get("master_link_status") == "up", status
        check_mode(promoted, "promoted", expected_after())
        matching_snapshots(promoted, old, label="old primary rejoined")
        for name, gate in gates(old, "original").items():
            exact(
                "stale old adapter " + name,
                gate.inspect_on_selected_primary(),
                SyntheticMarkerObservation("not_active_leader"),
            )
        # Actual former-primary Redis server rejects raw writes only AFTER
        # it is explicitly attached as a read-only replica.
        key = PREFIX + os.environ["LOOMERA_PHASE714_OBSERVING_ID"] + ":reference"
        try:
            old.hset(key, "generation", 1)
        except redis.exceptions.ReadOnlyError:
            pass
        else:
            raise AssertionError("rejoined Redis replica unexpectedly accepted write")

        # Fault injection exclusively against the promoted, disposable fixture
        # AFTER the actual promotion and rejoin have been established.
        promoted.delete(key)
        exact(
            "missing reference blocks recovery",
            gates(promoted, "promoted")["observing"].inspect_on_selected_primary(),
            SyntheticMarkerObservation("reference_lost"),
        )
        qid = os.environ["LOOMERA_PHASE714_QUARANTINED_ID"]
        promoted.hset(PREFIX + qid + ":volatile", "generation", "2")
        exact(
            "injected stale replica epoch detected",
            gates(promoted, "promoted")["quarantined"].inspect_on_selected_primary(),
            SyntheticMarkerObservation("split_brain"),
        )
    print(
        "Phase 7.14: old primary rejoined as read-only replica, "
        "marker sync and fail-closed fault injection passed"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=("prepare", "after-promotion", "before-rejoin", "after-rejoin"),
    )
    stage = parser.parse_args().stage
    if os.environ.get("LOOMERA_PHASE714_TEST_REDIS") != "1":
        raise RuntimeError("isolated CI grant required")
    {
        "prepare": prepare,
        "after-promotion": after_promotion,
        "before-rejoin": before_rejoin,
        "after-rejoin": after_rejoin,
    }[stage]()


if __name__ == "__main__":
    main()
