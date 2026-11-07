"""Phase 7.18 disposable Redis ACL partition experiment. NEVER live auth."""
from __future__ import annotations

import os
import re
import sys
import redis
from redis.exceptions import AuthenticationError, NoPermissionError

from loomera.globalization.otp_acl_partition_evidence_policy import (
    AclNodeObservation, review_acl_partition,
)

PREFIX = "loomera:phase718:synthetic-acl-only:"
USERS = {"admin": "p718admin", "stale": "p718stale", "read": "p718read"}


def safety():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("GITHUB_RUN_ID")
            or not os.environ.get("GITHUB_RUN_ATTEMPT")
            or os.environ.get("LOOMERA_PHASE718_TEST_REDIS") != "1"):
        raise RuntimeError("Phase 7.18 requires an isolated GitHub CI grant")
    for key in ("ID", "ADMIN_PASS", "STALE_PASS", "READ_PASS"):
        value = os.environ.get("LOOMERA_PHASE718_" + key, "")
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            raise RuntimeError("random synthetic-only identity/password required")


def client(port, principal=None):
    if port not in (6408, 6409):
        raise ValueError("non-isolated Redis endpoint")
    name = USERS.get(principal)
    password = (os.environ["LOOMERA_PHASE718_" + {
        "admin": "ADMIN_PASS", "stale": "STALE_PASS",
        "read": "READ_PASS",
    }[principal]] if principal is not None else None)
    return redis.Redis(host="127.0.0.1", port=port, db=15,
                       username=name, password=password,
                       socket_timeout=3, socket_connect_timeout=2,
                       retry_on_timeout=False)


def marker():
    return PREFIX + os.environ["LOOMERA_PHASE718_ID"] + ":state"


def denied(label, fn):
    try:
        fn()
    except (AuthenticationError, NoPermissionError):
        return
    raise AssertionError("expected ACL denial: " + label)


def assert_node(c, role):
    assert c.ping() is True
    assert c.info("replication")["role"] == role
    assert c.config_get("appendonly").get("appendonly") == "yes"
    assert c.config_get("appendfsync").get("appendfsync") == "always"


def seed():
    old, new = client(6408), client(6409)
    try:
        assert_node(old, "master")
        assert_node(new, "slave")
        assert new.info("replication")["master_link_status"] == "up"
        old.hset(marker(), mapping={"epoch": "1", "writer": "initial"})
        assert old.wait(1, 5000) >= 1, "initial replication WAIT 1 failed"
        assert new.hgetall(marker()) == old.hgetall(marker())
    finally:
        old.close()
        new.close()
    print("Phase 7.18: real replica WAIT 1 and exact marker match confirmed")


def install_acl(c, stale_enabled):
    prefix = PREFIX + os.environ["LOOMERA_PHASE718_ID"] + ":*"
    # Never apply this temporary admin grant to any real/shared Redis.
    c.execute_command("ACL", "SETUSER", USERS["admin"], "reset", "on", "resetpass",
                      ">" + os.environ["LOOMERA_PHASE718_ADMIN_PASS"], "~*", "+@all")
    c.execute_command("ACL", "SETUSER", USERS["stale"], "reset",
                      "on" if stale_enabled else "off", "resetpass",
                      ">" + os.environ["LOOMERA_PHASE718_STALE_PASS"],
                      "~" + prefix, "+ping", "+eval", "+hset", "+hgetall")
    c.execute_command("ACL", "SETUSER", USERS["read"], "reset", "on", "resetpass",
                      ">" + os.environ["LOOMERA_PHASE718_READ_PASS"],
                      "~" + prefix, "+ping", "+hgetall")
    # Last anonymous bootstrap command. Redis ACL modifications do not
    # replicate to the other master across the physical bridge outage.
    c.execute_command("ACL", "SETUSER", "default", "off")


def raw_eval(c, label):
    return c.eval("return redis.call('HSET', KEYS[1], 'writer', ARGV[1])",
                  1, marker(), label)


def review(old_raw, old_stale, reached):
    result = review_acl_partition(
        (AclNodeObservation("old", "master", True, old_stale, old_raw),
         AclNodeObservation("promoted", "master", True, False, False)),
        old_admin_reachable=reached,
    )
    assert result.operator_review_required
    assert not result.production_write_allowed
    assert not result.global_fencing_proven
    assert not result.authentication_allowed
    assert not result.otp_consume_allowed
    assert not result.session_created
    return result


def partition():
    old, new = client(6408), client(6409)
    try:
        assert_node(old, "master")
        assert_node(new, "master")
        assert old.hgetall(marker()) == new.hgetall(marker())
        probe = PREFIX + os.environ["LOOMERA_PHASE718_ID"] + ":probe"
        assert old.set(probe, "source-only", ex=60)
        assert old.wait(1, 1500) == 0, "partition failed: data still replicates"
        assert new.get(probe) is None
        install_acl(old, stale_enabled=True)
        install_acl(new, stale_enabled=False)
    finally:
        old.close()
        new.close()

    connections = [client(port, user) for port in (6408, 6409)
                   for user in ("admin", "stale", "read")]
    anonymous = [client(6408), client(6409)]
    old_admin, old_stale, old_read, new_admin, new_stale, new_read = connections
    try:
        assert_node(old_admin, "master")
        assert_node(new_admin, "master")
        denied("old anonymous default", anonymous[0].ping)
        denied("promoted anonymous default", anonymous[1].ping)
        denied("promoted stale user", new_stale.ping)
        assert old_stale.ping() is True
        assert old_read.hgetall(marker()) == old_admin.hgetall(marker())
        assert new_read.hgetall(marker()) == new_admin.hgetall(marker())
        denied("old read-only HSET", lambda: old_read.hset(marker(), "writer", "bad"))
        denied("promoted read-only HSET",
               lambda: new_read.hset(marker(), "writer", "bad"))
        denied("wrong synthetic fixture prefix",
               lambda: old_stale.hset(PREFIX + "outside-fixture:state", "writer", "bad"))
        # NEGATIVE SECURITY EVIDENCE. The old master still authenticates
        # the same stale principal that the promoted master revoked.
        raw_eval(old_stale, "stale-old")
        assert old_admin.hget(marker(), "writer") == b"stale-old"
        assert new_admin.hget(marker(), "writer") == b"initial"
        assert review(True, True, False).status == "stale_old_raw_writer_bypass"
    finally:
        for connection in connections + anonymous:
            connection.close()
    print("Phase 7.18: promoted ACL revocation DID NOT prevent old raw EVAL")


def revoke_old():
    old, new = client(6408, "admin"), client(6409, "admin")
    try:
        assert_node(old, "master")
        assert_node(new, "master")
        assert old.hget(marker(), "writer") == b"stale-old"
        assert new.hget(marker(), "writer") == b"initial"
        # This explicit administrative reachability is available only
        # because the lab uses one GitHub host. NOT real remote fencing.
        old.execute_command("ACL", "SETUSER", USERS["stale"], "off")
        old.execute_command("CLIENT", "KILL", "USER", USERS["stale"])
        old_stale, new_stale = client(6408, "stale"), client(6409, "stale")
        try:
            denied("old stale principal after local ACL mutation", old_stale.ping)
            denied("promoted stale principal remains disabled", new_stale.ping)
        finally:
            old_stale.close()
            new_stale.close()
        assert review(False, False, True).status == "local_old_acl_revocation_observed_only"
        assert old.hget(marker(), "writer") == b"stale-old"
        assert new.hget(marker(), "writer") == b"initial"
    finally:
        old.close()
        new.close()
    print("Phase 7.18: explicit local old ACL revocation denies fresh stale connections ONLY")


def main():
    safety()
    if len(sys.argv) != 2 or sys.argv[1] not in ("seed", "partition", "revoke-old"):
        raise SystemExit("expected seed | partition | revoke-old")
    {"seed": seed, "partition": partition, "revoke-old": revoke_old}[sys.argv[1]]()


if __name__ == "__main__":
    main()
