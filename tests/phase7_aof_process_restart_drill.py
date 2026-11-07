"""Phase 7.13 three-stage verification across REAL isolated Redis process restarts.

The shell runner controls the Docker process and persistent test-only volume.
Each stage runs in a different Python process, opens a new Redis connection,
and never reads a real user or session. NO live OTP or Production network.
"""
from __future__ import annotations

import argparse
import os
from contextlib import contextmanager

import redis

from loomera.globalization.otp_aof_process_restart_rehearsal import (
    PREFIX, SyntheticAofProcessRestartFence, SyntheticMarkerObservation,
)

URL = "redis://127.0.0.1:6392/15"
FIXTURES = (
    ("observing", "LOOMERA_PHASE713_OBSERVING_ID"),
    ("quarantined", "LOOMERA_PHASE713_QUARANTINED_ID"),
    ("halted", "LOOMERA_PHASE713_HALTED_ID"),
)


@contextmanager
def isolated_client():
    client = redis.Redis.from_url(
        URL, socket_timeout=5, socket_connect_timeout=5,
        retry_on_timeout=False,
    )
    try:
        assert client.ping() is True
        aof = client.config_get("appendonly")
        fsync = client.config_get("appendfsync")
        assert aof.get("appendonly") == "yes", aof
        assert fsync.get("appendfsync") == "always", fsync
        yield client
    finally:
        client.close()


def fences(client):
    return {
        name: SyntheticAofProcessRestartFence(
            client, fixture_id=os.environ[env_var],
        )
        for name, env_var in FIXTURES
    }


def checked(label: str, result, expected: SyntheticMarkerObservation) -> None:
    assert result == expected, (label, result, expected)
    assert result.authenticated is False, label
    assert result.session_created is False, label
    assert result.can_resume is False, label
    assert result.can_seed_on_restart is False, label
    assert result.safe_to_retry is False, label
    assert result.legacy_fallback_authorized is False, label
    assert result.production_recovery_authorized is False, label


def prepared():
    assert os.environ.get("LOOMERA_PHASE713_ALLOW_TEST_SEED") == "1"
    with isolated_client() as client:
        gates = fences(client)
        for name, gate in gates.items():
            checked(
                f"{name}: explicit prepare",
                gate.initialize_disposable_fixture_for_test(),
                SyntheticMarkerObservation("initialized", 1),
            )
        checked(
            "quarantined: initial CAS",
            gates["quarantined"].quarantine(
                expected_generation=1, cause="client_timeout",
            ),
            SyntheticMarkerObservation("quarantined", 2, "client_timeout"),
        )
        checked(
            "halted: initial terminal CAS",
            gates["halted"].halt(expected_generation=1),
            SyntheticMarkerObservation("halted", 2),
        )
        for name, gate in gates.items():
            checked(
                "prepared " + name,
                gate.inspect_after_process_restart(),
                {
                    "observing": SyntheticMarkerObservation("observing", 1),
                    "quarantined": SyntheticMarkerObservation(
                        "quarantined", 2, "client_timeout",
                    ),
                    "halted": SyntheticMarkerObservation("halted", 2),
                }[name],
            )
    print("Phase 7.13: AOF fixture prepared in three distinct modes; no login")


def after_graceful():
    assert os.environ.get("LOOMERA_PHASE713_ALLOW_TEST_SEED") != "1"
    with isolated_client() as client:
        gates = fences(client)
        expected = {
            "observing": SyntheticMarkerObservation("observing", 1),
            "quarantined": SyntheticMarkerObservation("quarantined", 2, "client_timeout"),
            "halted": SyntheticMarkerObservation("halted", 2),
        }
        for name, gate in gates.items():
            checked(
                "graceful restart " + name,
                gate.inspect_after_process_restart(), expected[name],
            )

        checked(
            "graceful: quarantine observed after persisted restart",
            gates["observing"].quarantine(
                expected_generation=1, cause="lost_write_reply",
            ),
            SyntheticMarkerObservation("quarantined", 2, "lost_write_reply"),
        )
        checked(
            "graceful: halt formerly quarantined marker",
            gates["quarantined"].halt(expected_generation=2),
            SyntheticMarkerObservation("halted", 3, "client_timeout"),
        )
        checked(
            "graceful: terminal halt cannot be undone",
            gates["halted"].quarantine(
                expected_generation=2, cause="operator_stop",
            ),
            SyntheticMarkerObservation("already_halted", 2),
        )
        for gate in gates.values():
            assert gate.inspect_after_process_restart().can_resume is False
    print("Phase 7.13: real graceful process restart preserved marker epochs")


def after_sigkill():
    assert os.environ.get("LOOMERA_PHASE713_ALLOW_TEST_SEED") != "1"
    with isolated_client() as client:
        gates = fences(client)
        expected = {
            "observing": SyntheticMarkerObservation(
                "quarantined", 2, "lost_write_reply",
            ),
            "quarantined": SyntheticMarkerObservation(
                "halted", 3, "client_timeout",
            ),
            "halted": SyntheticMarkerObservation("halted", 2),
        }
        for name, gate in gates.items():
            checked(
                "SIGKILL restart " + name,
                gate.inspect_after_process_restart(), expected[name],
            )
        checked(
            "SIGKILL: old epoch is not accepted",
            gates["observing"].halt(expected_generation=1),
            SyntheticMarkerObservation("stale_generation", 2, "lost_write_reply"),
        )
        checked(
            "SIGKILL: cannot re-quarantine terminal",
            gates["quarantined"].quarantine(
                expected_generation=3, cause="operator_stop",
            ),
            SyntheticMarkerObservation("already_halted", 3, "client_timeout"),
        )

        # Fault injection occurs ONLY after both real restart checks and ONLY
        # inside one disposable, dedicated CI Redis Docker container.
        obs_id = os.environ["LOOMERA_PHASE713_OBSERVING_ID"]
        client.delete(PREFIX + obs_id + ":reference")
        checked(
            "selective loss is not a reason to silently reseed",
            gates["observing"].inspect_after_process_restart(),
            SyntheticMarkerObservation("reference_lost"),
        )
        checked(
            "selective loss forbids new halt mutation",
            gates["observing"].halt(expected_generation=2),
            SyntheticMarkerObservation("reference_lost"),
        )
        qid = os.environ["LOOMERA_PHASE713_QUARANTINED_ID"]
        client.hset(PREFIX + qid + ":volatile", "generation", "2")
        checked(
            "injected stale marker is split brain",
            gates["quarantined"].inspect_after_process_restart(),
            SyntheticMarkerObservation("split_brain"),
        )
        try:
            gates["observing"].initialize_disposable_fixture_for_test()
        except RuntimeError:
            pass
        else:
            raise AssertionError("recovery stage must not have test-seed authority")
    print("Phase 7.13: SIGKILL+AOF restart preserved generations; injected losses deny")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=("prepare", "after-graceful", "after-sigkill"),
    )
    args = parser.parse_args()
    if os.environ.get("LOOMERA_PHASE713_TEST_REDIS") != "1":
        raise RuntimeError("only explicitly authorized isolated test")
    if args.stage == "prepare":
        prepared()
    elif args.stage == "after-graceful":
        after_graceful()
    else:
        after_sigkill()


if __name__ == "__main__":
    main()
