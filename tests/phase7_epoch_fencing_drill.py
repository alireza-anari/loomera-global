"""Phase 7.16 actual two-node split-brain epoch token fencing drill.

No live account/OTP/session data. Two Redis servers share one CI host.
The SQLite witness is NOT a consensus lease and cannot fence raw Redis writes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
import time

import redis

from loomera.globalization.otp_epoch_witness_rehearsal import (
    SyntheticLocalEpochWitness, SyntheticLeaderEpoch, witness_path,
)
from loomera.globalization.otp_epoch_redis_rehearsal import (
    PREFIX, EPOCH_SCRIPT, SyntheticEpochRedisFence, SyntheticEpochWrite,
)

OLD_URL = "redis://127.0.0.1:6397/15"
NEW_URL = "redis://127.0.0.1:6398/15"


@contextmanager
def connection(url):
    c = redis.Redis.from_url(url, socket_timeout=5, socket_connect_timeout=5,
                             retry_on_timeout=False)
    try:
        assert c.ping() is True
        assert c.config_get("appendonly").get("appendonly") == "yes"
        assert c.config_get("appendfsync").get("appendfsync") == "always"
        yield c
    finally:
        c.close()


def witness():
    fixture = os.environ["LOOMERA_PHASE716_WITNESS_ID"]
    return SyntheticLocalEpochWitness(fixture_id=fixture,
                                      path=witness_path(fixture))


def gate(client, node):
    return SyntheticEpochRedisFence(
        client, fixture_id=os.environ["LOOMERA_PHASE716_FIXTURE_ID"],
        node=node, witness=witness(),
    )


def keys():
    fid = os.environ["LOOMERA_PHASE716_FIXTURE_ID"]
    return PREFIX + fid + ":fence", PREFIX + fid + ":counter"


def a():
    return os.environ["LOOMERA_PHASE716_TOKEN1"]


def b():
    return os.environ["LOOMERA_PHASE716_TOKEN2"]


def assert_denial_flags(result):
    for name in (
        "authenticated", "session_created", "otp_reissue_allowed",
        "can_resume", "safe_to_retry", "legacy_fallback_authorized",
        "production_cutover_authorized",
    ):
        assert getattr(result, name) is False, (name, result)


def eq(label, result, expected):
    assert result == expected, (label, result, expected)
    assert_denial_flags(result)


def snapshot(client):
    f, c = keys()
    values = client.hgetall(f), client.hgetall(c)
    assert values[0] and values[1]
    assert client.pttl(f) > 0 and client.pttl(c) > 0
    return values


def matching(a_client, b_client, *, label):
    required = snapshot(a_client)
    for _ in range(60):
        try:
            if snapshot(b_client) == required:
                return
        except AssertionError:
            pass
        time.sleep(0.15)
    raise AssertionError((label, required, snapshot(b_client)))


def prepare():
    assert os.environ.get("LOOMERA_PHASE716_ACTIVE_LEADER") == "original"
    assert os.environ.get("LOOMERA_PHASE716_ALLOW_SEED") == "1"
    assert os.environ.get("LOOMERA_PHASE716_ALLOW_TEST_WRITE") == "1"
    with connection(OLD_URL) as old, connection(NEW_URL) as replica:
        assert old.info("replication")["role"] == "master"
        state = replica.info("replication")
        assert state["role"] == "slave" and state["master_link_status"] == "up"

        w = witness()
        eq("witness setup", w.initialize_fixture(token=a()),
           SyntheticLeaderEpoch("initialized", 1, "original", a()))
        g = gate(old, "original")
        eq("initial Redis epoch token", g.initialize_fixture(token=a()),
           SyntheticEpochWrite("initialized", 1, 0))
        eq("pre-partition synthetic CAS write",
           g.write_fixture_marker(
               owner="original", epoch=1, token=a(), expected_sequence=0,
           ), SyntheticEpochWrite("written", 1, 1))
        assert old.wait(1, 5000) >= 1
        matching(old, replica, label="before network partition")
        assert w.inspect() == SyntheticLeaderEpoch("active", 1, "original", a())
    print("Phase 7.16: witness/original token epoch=1 and replica WAIT sync verified")


def during_partition():
    assert os.environ.get("LOOMERA_PHASE716_ALLOW_SEED") != "1"
    assert os.environ.get("LOOMERA_PHASE716_ALLOW_TEST_WRITE") == "1"
    assert os.environ.get("LOOMERA_PHASE716_ALLOW_TEST_ADOPT") == "1"
    with connection(OLD_URL) as old, connection(NEW_URL) as promoted:
        assert old.info("replication")["role"] == "master"
        assert promoted.info("replication")["role"] == "master"
        w = witness()
        result = w.rotate_to_promoted(
            expected_epoch=1, expected_token=a(), next_token=b(),
        )
        eq("SQLite local epoch CAS",
           result, SyntheticLeaderEpoch("rotated", 2, "promoted", b()))
        assert w.inspect() == SyntheticLeaderEpoch("active", 2, "promoted", b())

        old_adapter = gate(old, "original")
        eq("old token on stale master adapter denied",
           old_adapter.write_fixture_marker(
               owner="original", epoch=1, token=a(), expected_sequence=1,
           ), SyntheticEpochWrite("stale_token"))
        eq("old owner even with future token denied",
           old_adapter.write_fixture_marker(
               owner="original", epoch=2, token=b(), expected_sequence=1,
           ), SyntheticEpochWrite("stale_token"))
        # CRITICAL EXPLOIT DEMONSTRATION: raw Redis bypasses the local witness
        # entirely. The old master STILL ACCEPTS a stale epoch/old token write.
        f, c = keys()
        raw = old.eval(
            EPOCH_SCRIPT, 2, f, c, "write",
            os.environ["LOOMERA_PHASE716_FIXTURE_ID"],
            "original", 1, a(), 1,
        )
        assert raw == [b"written", 1, 2], raw
        assert old.hget(c, "sequence") == b"2"

        promoted_adapter = gate(promoted, "promoted")
        before = promoted_adapter.inspect(owner="promoted", epoch=2, token=b())
        eq("unadopted new primary still exposes stale local epoch",
           before, SyntheticEpochWrite("active", 1, 1))
        eq("promoted local epoch CAS adoption",
           promoted_adapter.adopt_after_rotation(
               old_epoch=1, old_token=a(), new_token=b(),
           ), SyntheticEpochWrite("adopted", 2, 1))
        eq("old token denied in promoted Redis EVAL",
           promoted_adapter.write_fixture_marker(
               owner="promoted", epoch=2, token=a(), expected_sequence=1,
           ), SyntheticEpochWrite("stale_token"))
        eq("new token records only synthetic marker write",
           promoted_adapter.write_fixture_marker(
               owner="promoted", epoch=2, token=b(), expected_sequence=1,
           ), SyntheticEpochWrite("written", 2, 2))
        assert old.hget(f, "epoch") == b"1"
        assert promoted.hget(f, "epoch") == b"2"
        assert old.hget(f, "token") == a().encode()
        assert promoted.hget(f, "token") == b().encode()
        assert snapshot(old) != snapshot(promoted)
        print(
            "Phase 7.16: old adapter denied stale token, but RAW old master "
            "accepted it; new master adopted epoch 2 via standalone Lua"
        )

        eq("terminal witness CAS on ambiguous dual-master state",
           w.halt(expected_epoch=2, expected_token=b(), reason="leader_ambiguity"),
           SyntheticLeaderEpoch("halted", 3, "promoted", b(), "leader_ambiguity"))
        eq("halt blocks new adapter",
           promoted_adapter.write_fixture_marker(
               owner="promoted", epoch=2, token=b(), expected_sequence=2,
           ), SyntheticEpochWrite("witness_halted"))
        eq("halt blocks old adapter",
           old_adapter.write_fixture_marker(
               owner="original", epoch=1, token=a(), expected_sequence=2,
           ), SyntheticEpochWrite("witness_halted"))
    print("Phase 7.16: local witness halted at epoch 3, no automatic recovery")


def after_rejoin():
    assert os.environ.get("LOOMERA_PHASE716_ALLOW_SEED") != "1"
    assert os.environ.get("LOOMERA_PHASE716_ALLOW_TEST_WRITE") != "1"
    assert os.environ.get("LOOMERA_PHASE716_ALLOW_TEST_ADOPT") != "1"
    with connection(OLD_URL) as old, connection(NEW_URL) as promoted:
        assert promoted.info("replication")["role"] == "master"
        old_info = old.info("replication")
        assert old_info["role"] == "slave", old_info
        assert old_info["master_link_status"] == "up", old_info
        matching(promoted, old, label="old primary rejoined")
        assert old.hget(keys()[0], "epoch") == b"2"
        assert old.hget(keys()[0], "token") == b().encode()
        try:
            old.hset(keys()[1], "sequence", "12")
        except redis.exceptions.ReadOnlyError:
            pass
        else:
            raise AssertionError("old Redis not read-only after rejoin")

        persisted = witness().inspect()
        eq("persistent terminal local witness",
           persisted, SyntheticLeaderEpoch(
               "halted", 3, "promoted", b(), "leader_ambiguity",
           ))
        eq("correct token denied after rejoin: witness halted",
           gate(promoted, "promoted").write_fixture_marker(
               owner="promoted", epoch=2, token=b(), expected_sequence=2,
           ), SyntheticEpochWrite("witness_halted"))

        # Loss of witness must never silently re-seed during incident recovery.
        witness().cleanup_owned_fixture()
        eq("lost witness also denies inspection",
           gate(promoted, "promoted").inspect(owner="promoted", epoch=2, token=b()),
           SyntheticEpochWrite("witness_untrusted"))
    print(
        "Phase 7.16: old leader now read-only, Redis copies converge; "
        "halt/lost witness never reauthorizes any adapter"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=("prepare", "during-partition", "after-rejoin"),
    )
    stage = parser.parse_args().stage
    if (
        os.environ.get("LOOMERA_PHASE716_TEST_REDIS") != "1"
        or os.environ.get("LOOMERA_PHASE716_TEST_WITNESS") != "1"
    ):
        raise RuntimeError("Phase 7.16 disposable CI grants required")
    {
        "prepare": prepare,
        "during-partition": during_partition,
        "after-rejoin": after_rejoin,
    }[stage]()


if __name__ == "__main__":
    main()
