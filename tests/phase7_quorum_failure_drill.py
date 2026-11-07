"""Phase 7.17 real FIVE-Redis-process quorum vote and stale-writer bypass drill.

Two data masters + three separately hosted (same CI runner) Redis witnesses.
The majority is NOT Raft/Paxos consensus, no network-independent lease, and
the witness-to-data EVAL is non-atomic. No login, OTP or Django sessions.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
import time

import redis

from loomera.globalization.otp_epoch_redis_rehearsal import EPOCH_SCRIPT
from loomera.globalization.otp_quorum_voter_rehearsal import (
    PORTS, SyntheticVoter, SyntheticVote,
)
from loomera.globalization.otp_quorum_write_gateway_rehearsal import (
    PREFIX, SyntheticGateWrite, SyntheticQuorumWriteGateway,
)

OLD = "redis://127.0.0.1:6403/15"
PROMOTED = "redis://127.0.0.1:6404/15"


@contextmanager
def connection(url, ping=True):
    c = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=2,
                             retry_on_timeout=False)
    try:
        if ping:
            assert c.ping() is True
            assert c.config_get("appendonly").get("appendonly") == "yes"
            assert c.config_get("appendfsync").get("appendfsync") == "always"
        yield c
    finally:
        c.close()


@contextmanager
def environment():
    with connection(OLD) as old, connection(PROMOTED) as new:
        clients = {}
        for node, port in PORTS.items():
            clients[node] = redis.Redis.from_url(
                f"redis://127.0.0.1:{port}/15",
                socket_timeout=2, socket_connect_timeout=2,
                retry_on_timeout=False,
            )
        try:
            yield old, new, tuple(
                SyntheticVoter(clients[n], fixture_id=os.environ["LOOMERA_PHASE717_ID"],
                               voter=n)
                for n in ("a", "b", "c")
            )
        finally:
            for cli in clients.values():
                cli.close()


def gateway(client, node, voters):
    return SyntheticQuorumWriteGateway(
        client, fixture_id=os.environ["LOOMERA_PHASE717_ID"],
        node=node, voters=voters,
    )


def token_a():
    return os.environ["LOOMERA_PHASE717_TOKEN_A"]


def token_b():
    return os.environ["LOOMERA_PHASE717_TOKEN_B"]


def token_c():
    return os.environ["LOOMERA_PHASE717_TOKEN_C"]


def keys():
    f = PREFIX + os.environ["LOOMERA_PHASE717_ID"]
    return f + ":fence", f + ":counter"


def verify(label, result, expected):
    assert result == expected, (label, result, expected)
    for field in (
        "authenticated", "session_created", "production_write_allowed",
        "legacy_fallback_authorized",
    ):
        if hasattr(result, field):
            assert getattr(result, field) is False, (label, field, result)


def markers(client):
    left, right = keys()
    values = client.hgetall(left), client.hgetall(right)
    assert values[0] and values[1] and client.pttl(left) > 0 and client.pttl(right) > 0
    return values


def sync(master, replica):
    reference = markers(master)
    for _ in range(70):
        try:
            if markers(replica) == reference:
                return
        except AssertionError:
            pass
        time.sleep(0.15)
    raise AssertionError("fixture marker replication never converged")


def prepare():
    assert os.environ.get("LOOMERA_PHASE717_ALLOW_SEED") == "1"
    with environment() as (old, new, voters):
        assert old.info("replication")["role"] == "master"
        info = new.info("replication")
        assert info["role"] == "slave" and info["master_link_status"] == "up"
        for v in voters:
            verify("seed voter", v.seed_for_test(token=token_a()),
                   SyntheticVote("seeded", 1, token_a()))
        root = gateway(old, "original", voters)
        verify("seed data", root.seed_test_data(initial_token=token_a()),
               SyntheticGateWrite("initialized", 1, 0))
        raw = old.eval(
            EPOCH_SCRIPT, 2, *keys(), "write", os.environ["LOOMERA_PHASE717_ID"],
            "original", 1, token_a(), 0,
        )
        assert raw == [b"written", 1, 1], raw
        assert old.wait(1, 5000) >= 1, "initial replica did not acknowledge"
        sync(old, new)
        for v in voters:
            verify("initial witness", v.inspect(), SyntheticVote("ready", 1, token_a()))
        assert root.quorum_observation(
            candidate_token=token_b()
        ).status == "majority_unavailable"
    print("Phase 7.17: 3 separate witnesses ready, data replicas sync WAIT=1")


def after_partition():
    assert os.environ.get("LOOMERA_PHASE717_ALLOW_SEED") != "1"
    assert os.environ.get("LOOMERA_PHASE717_ALLOW_TEST_VOTE") == "1"
    with environment() as (old, new, voters):
        assert old.info("replication")["role"] == "master"
        assert new.info("replication")["role"] == "master"
        for v in voters[:2]:
            verify("quorum witness vote", v.vote_promote(
                expected_old_token=token_a(), new_token=token_b(),
            ), SyntheticVote("vote_recorded", 2, token_b()))
        verify("third voter still original",
               voters[2].inspect(), SyntheticVote("ready", 1, token_a()))
        old_gate = gateway(old, "original", voters)
        new_gate = gateway(new, "promoted", voters)
        decision = new_gate.quorum_observation(candidate_token=token_b())
        assert decision.status == "synthetic_majority_observed_only"
        assert decision.matching_votes == 2 and not decision.can_write_production
        verify(
            "old gateway denied despite old being a Redis master",
            old_gate.write_promoted_fixture(
                candidate_token=token_b(), expected_sequence=1,
            ), SyntheticGateWrite("old_writer_denied_by_gateway"),
        )
        verify(
            "promoted local Redis adoption (NOT cross-store atomic)",
            new_gate.adopt_promoted_fixture(
                previous_token=token_a(), candidate_token=token_b(),
            ), SyntheticGateWrite("adopted", 2, 1),
        )
        verify(
            "promoted local Lua CAS synthetic counter",
            new_gate.write_promoted_fixture(
                candidate_token=token_b(), expected_sequence=1,
            ), SyntheticGateWrite("written", 2, 2),
        )
        # Intentional NEGATIVE proof: bypass the gateway. Raw Redis at the
        # stale original master STILL accepts the old epoch/token.
        raw = old.eval(
            EPOCH_SCRIPT, 2, *keys(), "write", os.environ["LOOMERA_PHASE717_ID"],
            "original", 1, token_a(), 1,
        )
        assert raw == [b"written", 1, 2], raw
        assert old.hget(keys()[0], "epoch") == b"1"
        assert new.hget(keys()[0], "epoch") == b"2"
        assert markers(old) != markers(new)

        for v in voters[:2]:
            verify(
                "conflicting candidate cannot replace existing voter",
                v.vote_promote(
                    expected_old_token=token_a(), new_token=token_c(),
                ), SyntheticVote("conflicting_vote", 2, token_b()),
            )
        assert new_gate.quorum_observation(
            candidate_token=token_c()
        ).status == "conflicting_candidate_observed"
    print(
        "Phase 7.17: two-voter majority observed, promoted Lua wrote epoch 2; "
        "RAW old primary STILL accepted stale epoch-1 write"
    )


def witness_majority_lost():
    assert os.environ.get("LOOMERA_PHASE717_ALLOW_TEST_VOTE") != "1"
    with environment() as (old, new, voters):
        assert old.info("replication")["role"] == "master"
        assert new.info("replication")["role"] == "master"
        result = gateway(new, "promoted", voters).quorum_observation(
            candidate_token=token_b()
        )
        assert result.status == "majority_unavailable"
        verify(
            "two witness outages block approved gateway",
            gateway(new, "promoted", voters).write_promoted_fixture(
                candidate_token=token_b(), expected_sequence=2,
            ), SyntheticGateWrite("majority_unavailable"),
        )
        # A raw writer can still mutate stale old Redis without quorum.
        raw = old.eval(
            EPOCH_SCRIPT, 2, *keys(), "write", os.environ["LOOMERA_PHASE717_ID"],
            "original", 1, token_a(), 2,
        )
        assert raw == [b"written", 1, 3], raw
    print(
        "Phase 7.17: 2/3 witness outage prevents gateway write, "
        "but raw stale Redis bypass remains possible"
    )


def after_restore_and_rejoin():
    assert os.environ.get("LOOMERA_PHASE717_ALLOW_TEST_HALT") == "1"
    with environment() as (old, new, voters):
        assert new.info("replication")["role"] == "master"
        old_info = old.info("replication")
        assert old_info["role"] == "slave" and old_info["master_link_status"] == "up"
        sync(new, old)
        assert old.hget(keys()[0], "epoch") == b"2"
        assert old.hget(keys()[0], "token") == token_b().encode()
        try:
            old.hset(keys()[1], "sequence", "99")
        except redis.exceptions.ReadOnlyError:
            pass
        else:
            raise AssertionError("rejoined old master is writable")

        for v in voters[:2]:
            verify(
                "terminal synthetic voter halt",
                v.terminal_halt(expected_token=token_b()),
                SyntheticVote("halted", 3, token_b()),
            )
        new_gate = gateway(new, "promoted", voters)
        assert new_gate.quorum_observation(
            candidate_token=token_b()
        ).status == "terminal_halt_observed"
        verify(
            "no silent automatic new write after terminal witness halt",
            new_gate.write_promoted_fixture(
                candidate_token=token_b(), expected_sequence=2,
            ), SyntheticGateWrite("terminal_halt_observed"),
        )
    print(
        "Phase 7.17: old data master rejoins read-only; terminal voters "
        "keep synthetic gateway fail-closed"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=(
        "prepare", "after-partition", "witness-loss", "after-rejoin",
    ))
    stage = parser.parse_args().stage
    if os.environ.get("LOOMERA_PHASE717_TEST_REDIS") != "1":
        raise RuntimeError("test-only GitHub Redis grant required")
    {
        "prepare": prepare,
        "after-partition": after_partition,
        "witness-loss": witness_majority_lost,
        "after-rejoin": after_restore_and_rejoin,
    }[stage]()


if __name__ == "__main__":
    main()
