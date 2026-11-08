"""Phase 7.25: two REAL isolated Redis 7.4 AOF masters, lost ledger replication.

Run only through tests/phase7_redis_idempotency_failover_ci.sh; stages are
controlled by that script's physical replication/client network changes.
This is an adversarial demonstration of missing global OTP idempotency:
each master can locally commit *the same* operation ID with a different code.
Only fabricated records. Never touch real data, SMS or Django auth.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import os
import sys

from django.conf import settings
if not settings.configured:
    settings.configure(
        SECRET_KEY="phase725-github-actions-fixture-only-not-a-real-signing-key",
    )
from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache
import redis

from loomera.globalization.otp_legacy_idempotency_failover_rehearsal import (
    OLD_URL, PROMOTED_URL, PREFIX, validate_two_master_scope,
    issue_on_synthetic_master, verify_on_synthetic_master,
    summarize_split_brain,
)

A = "09123456789"
B = "09123456780"
C = "09123456781"
IP_TAG = "synthetic_ip_01"
PHASES = frozenset({"seed", "partition", "host-bypass", "after-restart"})


def hmac_for(mobile, code):
    return salted_hmac(
        "loomera.api.auth.otp", f"app_login:{mobile}:{code}",
    ).hexdigest()


def operation(fixture, label):
    return hashlib.sha256(
        (fixture + ":" + label).encode("ascii"),
    ).hexdigest()[:32]


def cache_for(url, fixture):
    return RedisCache(url, {
        "KEY_PREFIX": PREFIX + fixture,
        "VERSION": 1,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    })


def client_for(url):
    return redis.Redis.from_url(
        url, socket_connect_timeout=1, socket_timeout=5,
        decode_responses=False,
    )


def assert_no_auth(evidence):
    for name in (
        "real_otp_issued_or_consumed", "real_authentication_allowed",
        "real_session_created", "automatic_retry_or_grant_authorized",
        "production_cutover_authorized", "live_idempotency_fixed",
        "multihost_fencing_proven", "cross_store_consistency_proven",
    ):
        assert getattr(evidence, name) is False, (name, evidence.status)
    for secret in (A, B, C, IP_TAG, "111111", "222222"):
        assert secret not in repr(evidence)


def assert_no_release(evidence):
    for name in (
        "globally_unique_execution_proven", "global_fencing_proven",
        "globally_durable_idempotency_proven", "safe_production_replay",
        "real_authentication_allowed", "real_session_created",
        "production_cutover_authorized",
    ):
        assert getattr(evidence, name) is False, name


def raw_keys(cache, fixture, mobile, kind, label, code, now_ts=1050):
    op = operation(fixture, label)
    digest = hmac_for(mobile, code)
    # Connection must be supplied to full strict scope validation elsewhere.
    hour = now_ts // 3600
    return tuple(str(cache.make_key(x)) for x in (
        "operation:synthetic:" + op,
        f"record:app_login:{mobile}",
        f"resend:app_login:{mobile}",
        f"rate:mobile:app_login_{mobile}:{hour}",
        f"rate:ip:{IP_TAG}:{hour}",
    ))


def assert_roles(old, promoted, left, right):
    assert old.info("replication")["role"] == left
    assert promoted.info("replication")["role"] == right


def run(fixture, stage):
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("LOOMERA_PHASE725_TEST_REDIS") != "1"
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")
            or type(fixture) is not str or len(fixture) != 32
            or stage not in PHASES):
        raise SystemExit("invalid disposable Phase7.25 GitHub CI scope")
    oldcache = cache_for(OLD_URL, fixture)
    newcache = cache_for(PROMOTED_URL, fixture)
    old = client_for(OLD_URL)
    new = client_for(PROMOTED_URL)
    try:
        # Before ANY Redis IO, validate identity, key transformation,
        # exact port, DB15 and both independent test-only clients.
        for cache, client in ((oldcache, old), (newcache, new)):
            validate_two_master_scope(
                cache, client, fixture_id=fixture, mobile=A,
                digest=hmac_for(A, "123456"),
                operation_id=operation(fixture, "A-issue"),
                kind="issue", now_ts=1050,
            )
        ka = raw_keys(oldcache, fixture, A, "issue", "A-issue", "123456")
        kc = raw_keys(oldcache, fixture, C, "issue", "C-issue", "123456")
        kb = raw_keys(oldcache, fixture, B, "issue", "B-issue", "111111")
        va = raw_keys(oldcache, fixture, A, "verify", "A-verify", "123456")
        vc = raw_keys(oldcache, fixture, C, "verify", "C-wrong", "000000")
        vc2 = raw_keys(oldcache, fixture, C, "verify", "C-wrong-2", "000000")
        marker = str(oldcache.make_key("phase725:test-replication-confirmed"))
        bypass = str(oldcache.make_key("phase725:test-host-raw-bypass"))

        if stage == "seed":
            assert_roles(old, new, "master", "slave")
            for mobile, label in ((A, "A-issue"), (C, "C-issue")):
                row = issue_on_synthetic_master(
                    oldcache, old, fixture_id=fixture, mobile=mobile,
                    digest=hmac_for(mobile, "123456"),
                    operation_id=operation(fixture, label),
                )
                assert row.status == "synthetic_issued", row.status
                assert row.mutation_confirmed
                assert_no_auth(row)

            # Redis WAIT operates on THIS exact connection, and we also
            # compare raw bytes of all initialized keys on replica.
            with old.pipeline(transaction=False) as p:
                p.set(marker, b"phase725-replication-seed", ex=3900)
                p.wait(1, 5000)
                result = p.execute()
            assert result == [True, 1], result
            assert old.get(marker) == new.get(marker)
            for key in set(ka + kc):
                expected = old.get(key)
                assert expected is not None, key
                assert new.get(key) == expected, key
                assert 0 < old.pttl(key) and 0 < new.pttl(key)
            assert old.get(kb[0]) is None
            assert new.get(kb[0]) is None
            assert old.get(kb[3]) is None and new.get(kb[3]) is None
            assert old.get(ka[4]) == new.get(ka[4]) == b"2"
            print("Phase7.25 SEED: two legacy operations plus their ledgers replicated; WAIT 1 confirmed")
            return

        if stage == "partition":
            assert_roles(old, new, "master", "master")
            assert new.get(ka[0]) == old.get(ka[0])
            assert new.get(kc[0]) == old.get(kc[0])
            assert old.get(kb[0]) is None and new.get(kb[0]) is None

            # Two *different* local masters accept a concurrent same-ID
            # operation with CONTRADICTORY code digests. WATCH on one server
            # cannot observe keys, conflicting ledger, or writes on the other.
            barrier = Barrier(2, timeout=20)
            def issue_b(cache, client, code):
                barrier.wait(timeout=20)
                return issue_on_synthetic_master(
                    cache, client, fixture_id=fixture, mobile=B,
                    digest=hmac_for(B, code),
                    operation_id=operation(fixture, "B-issue"),
                )
            with ThreadPoolExecutor(max_workers=2) as workers:
                futures = [
                    workers.submit(issue_b, oldcache, old, "111111"),
                    workers.submit(issue_b, newcache, new, "222222"),
                ]
                rows = [f.result(timeout=25) for f in futures]
            assert [r.status for r in rows] == [
                "synthetic_issued", "synthetic_issued",
            ], [r.status for r in rows]
            for row in rows:
                assert row.mutation_confirmed
                assert_no_auth(row)
            assert old.get(kb[0]) != new.get(kb[0])
            assert old.get(kb[1]) != new.get(kb[1])
            # Each counter sees only its own B issuance: both report 3,
            # while globally there are FOUR synthetic successful issuances
            # (A, C, old-B, promoted-B), exceeding IP_LIMIT=3.
            assert old.get(ka[4]) == new.get(ka[4]) == b"3"
            assert old.get(kb[3]) == new.get(kb[3]) == b"1"

            # On its own server, fingerprint reuse guards DO work.
            old_replay = issue_on_synthetic_master(
                oldcache, old, fixture_id=fixture, mobile=B,
                digest=hmac_for(B, "111111"),
                operation_id=operation(fixture, "B-issue"),
            )
            changed_on_old = issue_on_synthetic_master(
                oldcache, old, fixture_id=fixture, mobile=B,
                digest=hmac_for(B, "222222"),
                operation_id=operation(fixture, "B-issue"),
            )
            changed_on_new = issue_on_synthetic_master(
                newcache, new, fixture_id=fixture, mobile=B,
                digest=hmac_for(B, "111111"),
                operation_id=operation(fixture, "B-issue"),
            )
            assert old_replay.status == "synthetic_replayed"
            assert changed_on_old.status == "operation_reuse_conflict"
            assert changed_on_new.status == "operation_reuse_conflict"
            for row in (old_replay, changed_on_old, changed_on_new):
                assert_no_auth(row)

            # Same A legacy record was correctly synced BEFORE failover:
            # both masters now independently accept the same operation ID
            # as successful consumption. No real session may be authorized.
            for cache, client in ((oldcache, old), (newcache, new)):
                accepted = verify_on_synthetic_master(
                    cache, client, fixture_id=fixture, mobile=A,
                    digest=hmac_for(A, "123456"),
                    operation_id=operation(fixture, "A-verify"),
                )
                assert accepted.status == "synthetic_single_winner"
                assert accepted.mutation_confirmed
                assert_no_auth(accepted)
                assert client.get(ka[1]) is None
                assert client.get(va[0]) is not None

            # A wrong attempt with the SAME op ID can likewise execute on
            # both sides. A second old-only op makes histories diverge.
            for cache, client in ((oldcache, old), (newcache, new)):
                wrong = verify_on_synthetic_master(
                    cache, client, fixture_id=fixture, mobile=C,
                    digest=hmac_for(C, "000000"),
                    operation_id=operation(fixture, "C-wrong"),
                )
                assert wrong.status == "synthetic_invalid_attempt"
                assert wrong.attempts_remaining == 4
                assert wrong.mutation_confirmed
                assert_no_auth(wrong)
            old_second = verify_on_synthetic_master(
                oldcache, old, fixture_id=fixture, mobile=C,
                digest=hmac_for(C, "000000"),
                operation_id=operation(fixture, "C-wrong-2"),
            )
            assert old_second.status == "synthetic_invalid_attempt"
            assert old_second.attempts_remaining == 3
            assert_no_auth(old_second)
            assert oldcache.client.decode(old.get(kc[1]))["attempts"] == 2
            assert newcache.client.decode(new.get(kc[1]))["attempts"] == 1
            assert old.get(vc2[0]) is not None
            assert new.get(vc2[0]) is None
            assert old.get(kb[0]) != new.get(kb[0])
            print("Phase7.25 PARTITION: two independent same-op issue + consume commits; IP quota overrun and ledger divergence PROVEN")
            return

        if stage == "host-bypass":
            assert_roles(old, new, "master", "master")
            assert old.get(bypass) is None and new.get(bypass) is None
            # Raw host EVAL below is a *synthetic* direct writer on old
            # primary after a client-only bridge cut. It proves why a
            # client-route disconnect does NOT globally fence old Redis.
            script = "return redis.call('SET', KEYS[1], ARGV[1], 'EX', 3900)"
            committed = old.eval(script, 1, bypass, b"old-primary-host-raw")
            # EVAL returns a Redis simple-string OK as bytes with redis-py.
            assert type(committed) is bytes and committed == b"OK", committed
            assert old.get(bypass) == b"old-primary-host-raw"
            assert new.get(bypass) is None
            status = summarize_split_brain(
                old_master_role=old.info("replication")["role"],
                promoted_role=new.info("replication")["role"],
                old_issue_ledger=old.get(kb[0]),
                new_issue_ledger=new.get(kb[0]),
                old_challenge=old.get(kb[1]),
                new_challenge=new.get(kb[1]),
                old_bypass_write_confirmed=True,
            )
            assert status.status == "two_masters_divergent_same_operation"
            assert status.two_local_master_claims
            assert status.divergent_ledgers_observed
            assert status.old_primary_raw_bypass_observed
            assert_no_release(status)
            assert_no_auth(old_replay_result(oldcache, old, fixture))
            print("Phase7.25 HOST BYPASS: client bridge fenced, old PRIMARY still accepts host raw EVAL; release BLOCKED")
            return

        if stage == "after-restart":
            assert_roles(old, new, "master", "master")
            assert old.get(marker) == new.get(marker) == b"phase725-replication-seed"
            assert old.get(bypass) == b"old-primary-host-raw"
            assert new.get(bypass) is None
            assert old.get(kb[0]) != new.get(kb[0])
            assert old.get(kb[1]) != new.get(kb[1])
            assert oldcache.client.decode(old.get(kc[1]))["attempts"] == 2
            assert newcache.client.decode(new.get(kc[1]))["attempts"] == 1
            assert old.get(ka[4]) == new.get(ka[4]) == b"3"
            assert old.get(va[0]) is not None and new.get(va[0]) is not None
            assert old.get(vc[0]) is not None and new.get(vc[0]) is not None
            # AOF preserves separate contradictory histories; restart is
            # no substitute for global reconciliation, quorum or fencing.
            evidence = summarize_split_brain(
                old_master_role=old.info("replication")["role"],
                promoted_role=new.info("replication")["role"],
                old_issue_ledger=old.get(kb[0]),
                new_issue_ledger=new.get(kb[0]),
                old_challenge=old.get(kb[1]),
                new_challenge=new.get(kb[1]),
                old_bypass_write_confirmed=True,
            )
            assert evidence.status == "two_masters_divergent_same_operation"
            assert_no_release(evidence)
            print("Phase7.25 AOF RESTART: both independent conflicting ledgers persist; no global idempotency or auth grant")
            return

    finally:
        old.close()
        new.close()


def old_replay_result(cache, client, fixture):
    return issue_on_synthetic_master(
        cache, client, fixture_id=fixture, mobile=B,
        digest=hmac_for(B, "111111"),
        operation_id=operation(fixture, "B-issue"),
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: phase7_idempotency_failover_drill.py <CI-stage>")
    run(os.environ.get("LOOMERA_PHASE725_ID", ""), sys.argv[1])
