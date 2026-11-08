"""Phase 7.27: REAL isolated PostGIS + REAL raw Redis ingress counterexamples.

The existing Phase 7.26 PostgreSQL authority is VOLUNTARY; bypasses, SQL
rollback and stale Redis credentials are physically observed, NEVER fixed.
Only disposable fixture data, no live OTP, account, user, session, or SMS.
"""
from __future__ import annotations

import os
import re

from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase
import redis

from loomera.globalization.otp_ingress_boundary_policy import (
    SyntheticIngressRoute, review_synthetic_ingress, validate_disposable_redis,
)
from loomera.globalization.otp_postgis_writer_authority_rehearsal import (
    LEASE, LEDGER, SyntheticPostGISWriterAuthority, verify_ci_test_scope,
)

SCRIPT = "return redis.call('SET', KEYS[1], ARGV[1])"
HEX32 = re.compile(r"[0-9a-f]{32}\Z")


class InjectedPostgresRollback(Exception):
    """Test-controlled rollback, not a real outage."""


class Phase727PostGISRedisIngressProof(TransactionTestCase):
    databases = {"default"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        verify_ci_test_scope(connection)
        fixture = os.environ.get("LOOMERA_PHASE727_ID")
        if type(fixture) is not str or HEX32.fullmatch(fixture) is None:
            raise RuntimeError("phase727_random_fixture_required")
        credentials = {}
        for role in ("ADMIN", "STALE", "PROMOTED"):
            secret = os.environ.get("LOOMERA_PHASE727_" + role + "_PASS")
            if type(secret) is not str or HEX32.fullmatch(secret) is None:
                raise RuntimeError("phase727_random_credentials_required")
            credentials[role] = secret
        cls.fixture = fixture
        cls.prefix = "loomera:phase727:synthetic-pg-redis-only:" + fixture + ":"
        cls.key = cls.prefix + "record:synthetic"
        cls.credentials = credentials
        bootstrap = redis.Redis(host="127.0.0.1", port=6427, db=15,
                                socket_connect_timeout=1, socket_timeout=3)
        assert validate_disposable_redis(bootstrap, fixture) == cls.prefix
        if not bootstrap.ping():
            raise RuntimeError("disposable_redis_not_running")
        # Fixed names scoped to one exact disposable Docker Redis instance.
        # Disable anonymous access BEFORE any fixture operations.
        bootstrap.execute_command(
            "ACL", "SETUSER", "phase727_admin", "reset", "on",
            "resetpass", ">" + credentials["ADMIN"],
            "~" + cls.prefix + "*", "+@all",
        )
        cls.admin = redis.Redis(
            host="127.0.0.1", port=6427, db=15, username="phase727_admin",
            password=credentials["ADMIN"],
            socket_connect_timeout=1, socket_timeout=3,
        )
        assert validate_disposable_redis(cls.admin, fixture) == cls.prefix
        if not cls.admin.ping():
            raise RuntimeError("phase727_test_admin_not_authenticated")
        cls.admin.execute_command("ACL", "SETUSER", "default", "off")
        bootstrap.close()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.admin.close()
        finally:
            super().tearDownClass()

    def _reset_actor(self, name, role):
        # Revocation in one test must not taint later independent cases.
        self.admin.execute_command(
            "ACL", "SETUSER", name, "reset", "on", "resetpass",
            ">" + self.credentials[role],
            "~" + self.prefix + "*", "+ping", "+select", "+get", "+set", "+eval",
        )
        client = redis.Redis(
            host="127.0.0.1", port=6427, db=15, username=name,
            password=self.credentials[role],
            socket_connect_timeout=1, socket_timeout=3,
        )
        assert validate_disposable_redis(client, self.fixture) == self.prefix
        self.assertTrue(client.ping())
        return client

    def setUp(self):
        super().setUp()
        verify_ci_test_scope(connection)
        self.old = self._reset_actor("phase727_stale", "STALE")
        self.promoted = self._reset_actor("phase727_promoted", "PROMOTED")
        with connection.cursor() as cur:
            cur.execute("SELECT current_database(), PostGIS_Version()")
            db, version = cur.fetchone()
            self.assertTrue(db.startswith("test_"))
            self.assertTrue(version)
            cur.execute(f'DROP TABLE IF EXISTS "{LEDGER}"')
            cur.execute(f'DROP TABLE IF EXISTS "{LEASE}"')
            cur.execute(
                f'CREATE TABLE "{LEASE}" ('
                'singleton INTEGER PRIMARY KEY CHECK (singleton=1), '
                'epoch INTEGER NOT NULL CHECK (epoch BETWEEN 1 AND 1000000), '
                "owner VARCHAR(12) NOT NULL CHECK (owner IN ('old', 'promoted')), "
                "mode VARCHAR(12) NOT NULL CHECK (mode IN ('active', 'halted')))"
            )
            cur.execute(
                f'CREATE TABLE "{LEDGER}" ('
                'operation_id CHAR(32) PRIMARY KEY, '
                'fingerprint CHAR(64) NOT NULL, '
                'epoch INTEGER NOT NULL, owner VARCHAR(12) NOT NULL)'
            )
            cur.execute(
                f'INSERT INTO "{LEASE}" (singleton, epoch, owner, mode) '
                "VALUES (1, 1, 'old', 'active')"
            )
        self.admin.delete(self.key)
        self.gate = SyntheticPostGISWriterAuthority()

    def tearDown(self):
        try:
            # Exact fixture key only; the shell destroys the whole container.
            self.admin.delete(self.key)
            self.old.close()
            self.promoted.close()
            with connection.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{LEDGER}"')
                cur.execute(f'DROP TABLE IF EXISTS "{LEASE}"')
        finally:
            super().tearDown()

    def claim(self, owner="old", epoch=1, op="a" * 32,
              digest="b" * 64):
        return self.gate.claim(
            owner=owner, epoch=epoch, operation_id=op,
            fingerprint=digest,
        )

    def promote(self):
        self.assertEqual(
            self.gate.promote(
                expected_owner="old", expected_epoch=1,
                new_owner="promoted",
            ).status,
            "synthetic_promoted",
        )

    def raw_write(self, client, payload):
        assert validate_disposable_redis(client, self.fixture) == self.prefix
        return client.eval(SCRIPT, 1, self.key, payload)

    def ledger_count(self):
        with connection.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{LEDGER}"')
            return cur.fetchone()[0]

    def test_real_redis_acl_default_off_and_no_outside_keys(self):
        anonymous = redis.Redis(host="127.0.0.1", port=6427, db=15)
        try:
            self.assertEqual(
                validate_disposable_redis(anonymous, self.fixture),
                self.prefix,
            )
            with self.assertRaises(redis.exceptions.RedisError):
                anonymous.ping()
            with self.assertRaises(redis.exceptions.ResponseError):
                self.old.eval(SCRIPT, 1, "phase727:outside-prefix", "bad")
            with self.assertRaises(redis.exceptions.ResponseError):
                self.promoted.eval(SCRIPT, 1, "phase727:outside-prefix", "bad")
            self.assertIsNone(self.admin.get(self.key))
        finally:
            anonymous.close()

    def test_pg_promotion_denies_old_claim_but_host_raw_still_writes(self):
        self.assertEqual(self.claim().status, "synthetic_committed")
        self.promote()
        self.assertEqual(self.claim(op="c" * 32).status, "stale_writer")
        self.assertEqual(self.raw_write(self.old, "old-raw-after-promotion"), b"OK")
        self.assertEqual(self.admin.get(self.key), b"old-raw-after-promotion")

    def test_pg_global_operation_conflict_does_not_stop_raw_redis(self):
        self.assertEqual(self.claim().status, "synthetic_committed")
        self.promote()
        self.assertEqual(
            self.claim(owner="promoted", epoch=2, digest="d" * 64).status,
            "global_operation_conflict",
        )
        self.assertEqual(self.raw_write(self.old, "raw-conflicting-id"), b"OK")
        self.assertEqual(self.ledger_count(), 1)
        self.assertEqual(self.admin.get(self.key), b"raw-conflicting-id")

    def test_pg_check_then_promote_then_later_raw_write(self):
        self.assertEqual(self.claim(op="e" * 32).status, "synthetic_committed")
        self.promote()
        self.assertEqual(self.claim(op="f" * 32).status, "stale_writer")
        self.assertEqual(self.raw_write(self.old, "post-check-side-effect"), b"OK")
        self.assertEqual(self.admin.get(self.key), b"post-check-side-effect")

    def test_pg_rollback_cannot_undo_committed_redis_effect(self):
        with self.assertRaises(InjectedPostgresRollback):
            with transaction.atomic():
                self.assertEqual(self.claim(op="1" * 32).status,
                                 "synthetic_committed")
                self.assertEqual(self.raw_write(self.old, "redis-committed"), b"OK")
                raise InjectedPostgresRollback()
        self.assertEqual(self.ledger_count(), 0)
        self.assertEqual(self.admin.get(self.key), b"redis-committed")

    def test_pg_missing_authority_does_not_revoke_raw_client(self):
        with connection.cursor() as cur:
            cur.execute(f'DELETE FROM "{LEASE}"')
        self.assertEqual(self.claim().status, "missing_authority")
        self.assertEqual(self.raw_write(self.old, "no-pg-lease"), b"OK")
        self.assertEqual(self.admin.get(self.key), b"no-pg-lease")

    def test_missing_pg_ledger_sql_error_does_not_close_raw_route(self):
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE "{LEDGER}"')
        with self.assertRaises(DatabaseError):
            self.claim()
        self.assertEqual(self.raw_write(self.old, "pg-schema-unavailable"), b"OK")
        self.assertEqual(self.admin.get(self.key), b"pg-schema-unavailable")

    def test_pg_terminal_halt_still_leaves_raw_writer(self):
        self.assertEqual(self.gate.halt(owner="old", epoch=1).status,
                         "synthetic_halted")
        self.assertEqual(self.claim().status, "terminal_halt")
        self.assertEqual(self.raw_write(self.old, "sql-halted-raw-live"), b"OK")
        self.assertEqual(self.admin.get(self.key), b"sql-halted-raw-live")

    def test_acl_off_needs_existing_client_kill_and_still_not_global(self):
        self.assertEqual(self.raw_write(self.old, "old-before-revoke"), b"OK")
        self.promote()
        self.assertEqual(self.claim().status, "stale_writer")
        # Physical ACL revision on this exact disposable node; not a multihost
        # command or a PostgreSQL operation. Existing socket was opened above.
        self.admin.execute_command("ACL", "SETUSER", "phase727_stale", "off")
        # Critical physical negative proof: Redis 7.4 ACL "off" does NOT
        # invalidate an already authenticated socket. Do not call this
        # state fenced simply because a fresh AUTH attempt is rejected.
        self.assertEqual(
            self.raw_write(self.old, "existing-socket-survives-acl-off"), b"OK"
        )
        self.assertEqual(
            self.admin.get(self.key), b"existing-socket-survives-acl-off"
        )
        fresh = redis.Redis(
            host="127.0.0.1", port=6427, db=15, username="phase727_stale",
            password=self.credentials["STALE"], socket_connect_timeout=1,
            socket_timeout=3,
        )
        try:
            with self.assertRaises(redis.exceptions.AuthenticationError):
                self.raw_write(fresh, "must-not-reach-redis")
        finally:
            fresh.close()
        # Independently terminate the old session on THIS Redis server.
        # Other Redis servers/privileged credentials remain out of scope.
        killed = self.admin.execute_command(
            "CLIENT", "KILL", "USER", "phase727_stale"
        )
        self.assertGreaterEqual(killed, 1)
        with self.assertRaises(redis.exceptions.RedisError):
            self.raw_write(self.old, "must-not-reach-after-client-kill")
        self.assertEqual(
            self.admin.get(self.key), b"existing-socket-survives-acl-off"
        )
        self.assertEqual(self.raw_write(self.promoted, "new-raw-after-revoke"), b"OK")
        self.assertEqual(self.raw_write(self.admin, "admin-raw-bypass"), b"OK")
        self.assertEqual(self.admin.get(self.key), b"admin-raw-bypass")
        evidence = (
            SyntheticIngressRoute("pg_cooperating_old", True, False),
            SyntheticIngressRoute("old_host_raw", False, False),
            SyntheticIngressRoute("preexisting_stale_socket", False, False),
            SyntheticIngressRoute("promoted_raw", False, True),
            SyntheticIngressRoute("privileged_admin_raw", False, True),
            SyntheticIngressRoute("anonymous_raw", False, False),
        )
        review = review_synthetic_ingress(
            evidence, pg_stale_claim_rejected=True,
            local_stale_acl_revoked=True,
        )
        self.assertEqual(review.status, "ungated_raw_redis_writer_observed")
        self.assertFalse(review.actual_global_writer_fencing_proven)
        self.assertFalse(review.production_release_authorized)

    def test_wrong_credential_rejected_while_admin_still_has_raw_access(self):
        wrong = redis.Redis(
            host="127.0.0.1", port=6427, db=15, username="phase727_stale",
            password="0" * 32, socket_connect_timeout=1, socket_timeout=3,
        )
        try:
            with self.assertRaises(redis.exceptions.RedisError):
                self.raw_write(wrong, "must-not-write")
            self.assertIsNone(self.admin.get(self.key))
            self.assertEqual(self.raw_write(self.admin, "admin-write"), b"OK")
        finally:
            wrong.close()

    def test_all_synthetic_redis_written_values_are_fixture_only(self):
        self.assertEqual(self.raw_write(self.old, "marker"), b"OK")
        self.assertEqual(self.raw_write(self.promoted, "marker2"), b"OK")
        self.assertEqual(self.admin.get(self.key), b"marker2")
        self.assertEqual(self.ledger_count(), 0)
