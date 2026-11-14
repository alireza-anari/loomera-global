"""Phase 7.28: real isolated PostGIS+Redis restricted gateway and bypass limits.

This deliberately cannot prove global mandatory enforcement: a fixture admin
can still bypass the PostgreSQL gate, and Redis writes cannot share a SQL
transaction. NO real customer/account/OTP/SMS/session objects are accessed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import os
import re
import time
from unittest.mock import patch

from django.db import DatabaseError, close_old_connections, connection, connections
from django.db import transaction
from django.test import TransactionTestCase
import redis

from loomera.globalization.otp_postgis_writer_authority_rehearsal import (
    LEASE, LEDGER, SyntheticPostGISWriterAuthority, verify_ci_test_scope,
)
from loomera.globalization.otp_outbox_review_rehearsal import (
    SyntheticReadOnlyCrossStoreReviewer, validate_review_scope,
)
from loomera.globalization.otp_postgis_outbox_rehearsal import (
    OUTBOX, SyntheticPostGISOutboxRehearsal,
)
from loomera.globalization.otp_restricted_writer_gateway_rehearsal import (
    PREFIX, PORT, DB, SyntheticRestrictedWriterGateway,
    validate_gateway_scope,
)

_ID = re.compile(r"[0-9a-f]{32}\Z")
RAW = "return redis.call('SET', KEYS[1], ARGV[1])"
OPS = "abcdef1234567890"


class SimulatedPostgresRollback(Exception):
    pass


class Phase728PhysicalRestrictedWriterTest(TransactionTestCase):
    databases = {"default"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        verify_ci_test_scope(connection)
        fixture = os.environ.get("LOOMERA_PHASE728_ID")
        if type(fixture) is not str or _ID.fullmatch(fixture) is None:
            raise RuntimeError("phase728_random_fixture_required")
        credentials = {}
        for role in ("ADMIN", "GATEWAY", "LEGACY", "REVOKE"):
            secret = os.environ.get("LOOMERA_PHASE728_" + role + "_PASS")
            if type(secret) is not str or _ID.fullmatch(secret) is None:
                raise RuntimeError("phase728_random_acl_credential_required")
            credentials[role] = secret
        cls.fixture = fixture
        cls.prefix = PREFIX + fixture + ":"
        cls.credentials = credentials
        bootstrap = redis.Redis(
            host="127.0.0.1", port=PORT, db=DB,
            socket_connect_timeout=1, socket_timeout=3,
        )
        if not bootstrap.ping():
            raise RuntimeError("phase728_disposable_redis_unreachable")
        # One privileged *test-fixture-only* administrator is intentionally
        # retained to demonstrate a real raw Redis bypass.
        bootstrap.execute_command(
            "ACL", "SETUSER", "phase728_admin", "reset", "on",
            "resetpass", ">" + credentials["ADMIN"],
            "~" + cls.prefix + "*", "+@all",
        )
        cls.admin = cls.actor("phase728_admin", "ADMIN")
        if not cls.admin.ping():
            raise RuntimeError("phase728_disposable_admin_unreachable")
        cls.admin.execute_command("ACL", "SETUSER", "default", "off")
        bootstrap.close()

    @classmethod
    def actor(cls, username, role):
        return redis.Redis(
            host="127.0.0.1", port=PORT, db=DB,
            username=username, password=cls.credentials[role],
            socket_connect_timeout=1, socket_timeout=3,
        )

    @classmethod
    def tearDownClass(cls):
        try:
            cls.admin.close()
        finally:
            super().tearDownClass()

    def configure_actor(self, username, role, *allowed):
        self.admin.execute_command(
            "ACL", "SETUSER", username, "reset", "on", "resetpass",
            ">" + self.credentials[role], "~" + self.prefix + "*",
            "+ping", "+select", *allowed,
        )
        client = self.actor(username, role)
        self.assertTrue(client.ping())
        return client

    def setUp(self):
        super().setUp()
        verify_ci_test_scope(connection)
        with connection.cursor() as cur:
            cur.execute("SELECT current_database(), PostGIS_Version()")
            dbname, version = cur.fetchone()
            self.assertTrue(dbname.startswith("test_"))
            self.assertTrue(version)
            cur.execute(f'DROP TABLE IF EXISTS "{OUTBOX}"')
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
            cur.execute(
                f'CREATE TABLE "{OUTBOX}" ('
                'operation_id CHAR(32) PRIMARY KEY, '
                'fingerprint CHAR(64) NOT NULL, '
                'epoch INTEGER NOT NULL, owner VARCHAR(12) NOT NULL, '
                "state VARCHAR(12) NOT NULL CHECK "
                "(state IN ('pending', 'inflight', 'observed', 'quarantined')))"
            )
        self.gateway_client = self.configure_actor(
            "phase728_gateway", "GATEWAY", "+get", "+set",
        )
        self.legacy = self.configure_actor(
            "phase728_legacy", "LEGACY", "+get",
        )
        # Adversarial writer is OFF outside its single explicit test.
        self.admin.execute_command("ACL", "SETUSER", "phase728_revoke",
                                   "reset", "off")
        self.admin.execute_command("CLIENT", "KILL", "USER", "phase728_revoke")
        self.revocable = None
        self.gateway = SyntheticRestrictedWriterGateway(
            self.gateway_client, self.fixture,
        )
        self.authority = SyntheticPostGISWriterAuthority()
        self.clear_fixture()

    def key(self, op="a" * 32):
        return self.prefix + "operation:" + op

    def clear_fixture(self):
        # Strict exact small allowlist: no wildcard enumeration/deletion.
        keys = [self.key(letter * 32) for letter in OPS]
        keys.append(self.prefix + "revocation-proof")
        self.admin.delete(*keys)

    def tearDown(self):
        try:
            self.clear_fixture()
            self.gateway_client.close()
            self.legacy.close()
            if self.revocable is not None:
                self.revocable.close()
            with connection.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{OUTBOX}"')
                cur.execute(f'DROP TABLE IF EXISTS "{LEDGER}"')
                cur.execute(f'DROP TABLE IF EXISTS "{LEASE}"')
        finally:
            super().tearDown()

    def submit(self, owner="old", epoch=1, op="a" * 32, digest="b" * 64):
        return self.gateway.submit(
            owner=owner, epoch=epoch, operation_id=op,
            fingerprint=digest,
        )

    def ledger(self):
        with connection.cursor() as cur:
            cur.execute(f'SELECT operation_id, fingerprint FROM "{LEDGER}" '
                        'ORDER BY operation_id')
            return tuple(cur.fetchall())

    def test_gateway_client_is_the_only_nonadmin_fixture_writer(self):
        self.assertEqual(
            validate_gateway_scope(self.gateway_client, self.fixture),
            self.prefix,
        )
        for prohibited in (
            lambda: self.legacy.set(self.key(), "old-raw"),
            lambda: self.legacy.eval(RAW, 1, self.key(), "old-eval"),
            lambda: self.legacy.set(self.prefix + "outside-namespace", "denied"),
        ):
            with self.assertRaises(redis.exceptions.RedisError):
                prohibited()
        result = self.submit()
        self.assertEqual(result.status, "synthetic_redis_marker_observed")
        self.assertTrue(result.synthetic_redis_marker_written)
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)
        self.assertEqual(len(self.ledger()), 1)
        self.assertFalse(result.production_release_authorized)
        self.assertFalse(result.cross_store_atomicity_proven)

    def test_same_operation_replay_no_second_redis_write(self):
        self.assertEqual(self.submit().status, "synthetic_redis_marker_observed")
        self.assertEqual(self.submit().status, "same_operation_observed")
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)
        self.assertEqual(len(self.ledger()), 1)

    def test_conflicting_operation_fails_without_marker_mutation(self):
        self.submit()
        self.assertEqual(
            self.submit(digest="c" * 64).status, "global_operation_conflict",
        )
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)
        self.assertEqual(len(self.ledger()), 1)

    def test_promoted_epoch_allows_only_cooperating_promoted_claim(self):
        self.assertEqual(self.authority.promote(
            expected_owner="old", expected_epoch=1,
            new_owner="promoted",
        ).status, "synthetic_promoted")
        self.assertEqual(self.submit(op="c" * 32).status, "stale_writer")
        self.assertIsNone(self.admin.get(self.key("c" * 32)))
        self.assertEqual(
            self.submit(owner="promoted", epoch=2, op="c" * 32).status,
            "synthetic_redis_marker_observed",
        )
        self.assertEqual(self.admin.get(self.key("c" * 32)), b"b" * 64)

    def test_halt_denies_gateway_even_if_gateway_redis_acl_on(self):
        self.assertEqual(
            self.authority.halt(owner="old", epoch=1).status,
            "synthetic_halted",
        )
        self.assertEqual(self.submit().status, "terminal_halt")
        self.assertIsNone(self.admin.get(self.key()))

    def test_missing_pg_authority_fails_before_redis_set(self):
        with connection.cursor() as cur:
            cur.execute(f'DELETE FROM "{LEASE}"')
        self.assertEqual(self.submit().status, "missing_authority")
        self.assertIsNone(self.admin.get(self.key()))
        self.assertEqual(self.ledger(), ())

    def test_missing_pg_ledger_raises_without_redis_fallback(self):
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE "{LEDGER}"')
        with self.assertRaises(DatabaseError):
            self.submit()
        self.assertIsNone(self.admin.get(self.key()))

    def test_invalid_synthetic_inputs_fail_before_side_effect(self):
        for kw in (
            {"op": "g" * 32}, {"op": "a" * 31},
            {"digest": "not-a-digest"}, {"owner": "server"},
            {"epoch": True}, {"epoch": 0},
        ):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.submit(**kw)
        self.assertIsNone(self.admin.get(self.key()))
        self.assertEqual(self.ledger(), ())

    def test_revoked_ci_grant_aborts_gateway_before_io(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE728_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assertIsNone(self.admin.get(self.key()))
        self.assertEqual(self.ledger(), ())

    def test_redis_gate_revocation_and_client_kill_rolls_back_pg_claim(self):
        self.assertTrue(self.gateway_client.ping())
        self.admin.execute_command("ACL", "SETUSER", "phase728_gateway", "off")
        # Old authenticated gateway TCP remains valid until killed.
        self.assertTrue(self.gateway_client.ping())
        self.assertGreaterEqual(self.admin.execute_command(
            "CLIENT", "KILL", "USER", "phase728_gateway"
        ), 1)
        with self.assertRaises(redis.exceptions.RedisError):
            self.submit()
        self.assertEqual(self.ledger(), ())
        self.assertIsNone(self.admin.get(self.key()))

    def test_acl_off_does_not_close_old_socket_without_client_kill(self):
        self.revocable = self.configure_actor(
            "phase728_revoke", "REVOKE", "+get", "+set", "+eval",
        )
        proof = self.prefix + "revocation-proof"
        self.assertEqual(self.revocable.eval(RAW, 1, proof, "before-off"), b"OK")
        self.admin.execute_command("ACL", "SETUSER", "phase728_revoke", "off")
        self.assertEqual(
            self.revocable.eval(RAW, 1, proof, "old_socket_survives_acl_off"),
            b"OK",
        )
        self.assertEqual(self.admin.get(proof), b"old_socket_survives_acl_off")
        fresh = self.actor("phase728_revoke", "REVOKE")
        try:
            with self.assertRaises(redis.exceptions.AuthenticationError):
                fresh.eval(RAW, 1, proof, "must-not-be-accepted")
        finally:
            fresh.close()
        self.assertGreaterEqual(self.admin.execute_command(
            "CLIENT", "KILL", "USER", "phase728_revoke"
        ), 1)
        with self.assertRaises(redis.exceptions.RedisError):
            self.revocable.eval(RAW, 1, proof, "must-not-be-accepted")
        self.assertEqual(self.admin.get(proof), b"old_socket_survives_acl_off")

    def test_admin_can_always_raw_write_fixture_key(self):
        # Deliberate negative proof of privileged bypass; production must
        # independently close this path in a real deployment.
        self.assertEqual(self.authority.halt(
            owner="old", epoch=1,
        ).status, "synthetic_halted")
        self.assertEqual(self.submit().status, "terminal_halt")
        self.assertEqual(self.admin.eval(RAW, 1, self.key(), "admin-bypass"), b"OK")
        self.assertEqual(self.admin.get(self.key()), b"admin-bypass")
        self.assertEqual(self.ledger(), ())

    def test_pg_outer_rollback_keeps_committed_redis_marker(self):
        with self.assertRaises(SimulatedPostgresRollback):
            with transaction.atomic():
                self.assertEqual(
                    self.submit().status, "synthetic_redis_marker_observed",
                )
                raise SimulatedPostgresRollback()
        self.assertEqual(self.ledger(), ())
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)
        # SET NX refuses to silently overwrite an unresolved Redis effect;
        # no unauthorized application retry or repair is performed.
        with self.assertRaisesRegex(
            RuntimeError, "phase728_ambiguous_redis_marker_collision"
        ):
            self.submit()
        self.assertEqual(self.ledger(), ())

    def test_failed_ack_after_redis_write_is_not_auto_retried(self):
        actual_set = self.gateway_client.set

        def stored_but_ack_lost(*args, **kwargs):
            self.assertIs(actual_set(*args, **kwargs), True)
            raise redis.exceptions.ConnectionError("synthetic_ack_lost")

        with patch.object(self.gateway_client, "set",
                          side_effect=stored_but_ack_lost):
            with self.assertRaises(redis.exceptions.ConnectionError):
                self.submit()
        # Real Redis SET succeeded while SQL transaction rolled back.
        self.assertEqual(self.ledger(), ())
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)
        with self.assertRaisesRegex(
            RuntimeError, "phase728_ambiguous_redis_marker_collision"
        ):
            self.submit()
        self.assertEqual(self.ledger(), ())

    def test_sql_committed_missing_redis_marker_not_auto_repaired(self):
        self.assertEqual(self.submit().status, "synthetic_redis_marker_observed")
        self.admin.delete(self.key())
        self.assertEqual(self.submit().status, "same_operation_observed")
        self.assertIsNone(self.admin.get(self.key()))
        self.assertEqual(len(self.ledger()), 1)

    def test_pg_promote_waits_for_inflight_gateway_sql_lock(self):
        entered, release, promoter_started = Event(), Event(), Event()
        actual_set = self.gateway_client.set

        def held_after_real_write(*args, **kwargs):
            result = actual_set(*args, **kwargs)
            entered.set()
            if not release.wait(timeout=15):
                raise RuntimeError("phase728_test_barrier_timeout")
            return result

        def write_worker():
            close_old_connections()
            try:
                return self.submit(op="d" * 32).status
            finally:
                connections["default"].close()

        def promote_worker():
            close_old_connections()
            try:
                promoter_started.set()
                return SyntheticPostGISWriterAuthority().promote(
                    expected_owner="old", expected_epoch=1,
                    new_owner="promoted",
                ).status
            finally:
                connections["default"].close()

        try:
            with patch.object(self.gateway_client, "set",
                              side_effect=held_after_real_write):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    future_write = pool.submit(write_worker)
                    self.assertTrue(entered.wait(timeout=15))
                    future_promotion = pool.submit(promote_worker)
                    self.assertTrue(promoter_started.wait(timeout=15))
                    time.sleep(0.15)
                    self.assertFalse(future_promotion.done())
                    release.set()
                    self.assertEqual(future_write.result(timeout=20),
                                     "synthetic_redis_marker_observed")
                    self.assertEqual(future_promotion.result(timeout=20),
                                     "synthetic_promoted")
        finally:
            release.set()
        self.assertEqual(
            self.submit(op="e" * 32).status, "stale_writer",
        )
        self.assertEqual(self.admin.get(self.key("d" * 32)), b"b" * 64)
        self.assertIsNone(self.admin.get(self.key("e" * 32)))

    # Phase 7.29: the same isolated CI fixture now covers SQL-first intent.
    @property
    def outbox(self):
        return SyntheticPostGISOutboxRehearsal(
            self.gateway_client, self.fixture,
        )

    def outbox_state(self, operation_id="a" * 32):
        with connection.cursor() as cur:
            cur.execute(
                f'SELECT state FROM "{OUTBOX}" WHERE operation_id=%s',
                [operation_id],
            )
            row = cur.fetchone()
            return row[0] if row else None

    def enqueue_outbox(self, owner="old", epoch=1, op="a" * 32,
                       digest="b" * 64):
        return self.outbox.enqueue(
            owner=owner, epoch=epoch, operation_id=op, fingerprint=digest,
        )

    def dispatch_outbox(self, owner="old", epoch=1, op="a" * 32,
                        digest="b" * 64):
        return self.outbox.dispatch_once(
            owner=owner, epoch=epoch, operation_id=op, fingerprint=digest,
        )

    def test_phase729_commit_intent_before_any_redis_effect(self):
        self.assertEqual(
            self.enqueue_outbox().status, "synthetic_intent_committed",
        )
        self.assertEqual(self.outbox_state(), "pending")
        self.assertEqual(len(self.ledger()), 1)
        self.assertIsNone(self.admin.get(self.key()))
        self.assertEqual(
            self.outbox.inspect_read_only(
                operation_id="a" * 32, fingerprint="b" * 64,
            ).status,
            "pending_marker_absent_no_repair",
        )

    def test_phase729_one_shot_dispatch_and_no_duplicate_redis_set(self):
        self.enqueue_outbox()
        result = self.dispatch_outbox()
        self.assertEqual(result.status, "synthetic_marker_observed")
        self.assertTrue(result.synthetic_redis_marker_written)
        self.assertFalse(result.real_sms_sent)
        self.assertFalse(result.production_release_authorized)
        self.assertEqual(self.outbox_state(), "observed")
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)
        with patch.object(self.gateway_client, "set",
                          side_effect=AssertionError("no second SET")):
            self.assertEqual(
                self.dispatch_outbox().status, "already_observed_no_retry",
            )
        self.assertEqual(self.outbox.inspect_read_only(
            operation_id="a" * 32, fingerprint="b" * 64,
        ).status, "observed_marker_matches_no_receipt")

    def test_phase729_duplicate_or_conflicting_enqueue_never_rearms(self):
        self.assertEqual(
            self.enqueue_outbox().status, "synthetic_intent_committed",
        )
        self.assertEqual(
            self.enqueue_outbox().status, "same_operation_observed",
        )
        self.assertEqual(
            self.enqueue_outbox(digest="c" * 64).status,
            "global_operation_conflict",
        )
        self.assertEqual(self.outbox_state(), "pending")
        self.assertIsNone(self.admin.get(self.key()))

    def test_phase729_rollback_discards_sql_intent_and_ledger(self):
        with self.assertRaises(SimulatedPostgresRollback):
            with transaction.atomic():
                self.assertEqual(
                    self.enqueue_outbox().status, "synthetic_intent_committed",
                )
                raise SimulatedPostgresRollback()
        self.assertIsNone(self.outbox_state())
        self.assertEqual(self.ledger(), ())
        self.assertIsNone(self.admin.get(self.key()))

    def test_phase729_lost_ack_after_physical_set_never_retries(self):
        self.enqueue_outbox()
        actual_set = self.gateway_client.set

        def commit_then_lose_reply(*args, **kwargs):
            self.assertIs(actual_set(*args, **kwargs), True)
            raise redis.exceptions.ConnectionError("synthetic_lost_ack")

        with patch.object(self.gateway_client, "set",
                          side_effect=commit_then_lose_reply):
            with self.assertRaises(redis.exceptions.ConnectionError):
                self.dispatch_outbox()
        self.assertEqual(self.outbox_state(), "inflight")
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)
        with patch.object(self.gateway_client, "set",
                          side_effect=AssertionError("unsafe retry")):
            self.assertEqual(
                self.dispatch_outbox().status, "inflight_requires_manual_review",
            )
        self.assertEqual(self.outbox.inspect_read_only(
            operation_id="a" * 32, fingerprint="b" * 64,
        ).status, "inflight_marker_matches_no_receipt")

    def test_phase729_failure_before_redis_call_remains_inflight(self):
        self.enqueue_outbox()
        with patch.object(self.gateway_client, "set",
                          side_effect=redis.exceptions.ConnectionError(
                              "synthetic_connection_down"
                          )):
            with self.assertRaises(redis.exceptions.ConnectionError):
                self.dispatch_outbox()
        self.assertEqual(self.outbox_state(), "inflight")
        self.assertIsNone(self.admin.get(self.key()))
        self.assertEqual(
            self.dispatch_outbox().status, "inflight_requires_manual_review",
        )
        self.assertEqual(self.outbox.inspect_read_only(
            operation_id="a" * 32, fingerprint="b" * 64,
        ).status, "inflight_marker_absent_no_repair")

    def test_phase729_preexisting_foreign_marker_is_quarantined(self):
        self.enqueue_outbox()
        self.assertTrue(self.admin.set(self.key(), "raw-admin-marker"))
        self.assertEqual(
            self.dispatch_outbox().status, "marker_collision_quarantined",
        )
        self.assertEqual(self.outbox_state(), "quarantined")
        self.assertEqual(self.admin.get(self.key()), b"raw-admin-marker")
        self.assertEqual(self.outbox.inspect_read_only(
            operation_id="a" * 32, fingerprint="b" * 64,
        ).status, "foreign_marker_no_repair")
        self.assertEqual(
            self.dispatch_outbox().status, "quarantined_no_retry",
        )

    def test_phase729_missing_intent_denies_even_with_committed_ledger(self):
        self.enqueue_outbox()
        with connection.cursor() as cur:
            cur.execute(f'DELETE FROM "{OUTBOX}"')
        self.assertEqual(
            self.dispatch_outbox().status, "missing_committed_intent",
        )
        self.assertIsNone(self.admin.get(self.key()))

    def test_phase729_stale_or_halted_authority_denies_pending_dispatch(self):
        self.enqueue_outbox()
        self.assertEqual(
            self.authority.promote(
                expected_owner="old", expected_epoch=1,
                new_owner="promoted",
            ).status, "synthetic_promoted",
        )
        self.assertEqual(self.dispatch_outbox().status, "stale_writer")
        self.assertEqual(self.outbox_state(), "pending")
        self.assertIsNone(self.admin.get(self.key()))
        self.assertEqual(
            self.enqueue_outbox(owner="promoted", epoch=2,
                                op="c" * 32).status,
            "synthetic_intent_committed",
        )
        self.assertEqual(
            self.dispatch_outbox(owner="promoted", epoch=2,
                                 op="c" * 32).status,
            "synthetic_marker_observed",
        )
        self.assertEqual(
            self.authority.halt(owner="promoted", epoch=2).status,
            "synthetic_halted",
        )
        self.assertEqual(
            self.enqueue_outbox(owner="promoted", epoch=2,
                                op="d" * 32).status, "terminal_halt",
        )
        self.assertIsNone(self.admin.get(self.key("d" * 32)))

    def test_phase729_two_sql_workers_only_one_can_dispatch(self):
        self.enqueue_outbox()

        def worker():
            close_old_connections()
            try:
                return self.dispatch_outbox().status
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            statuses = [future.result(timeout=20) for future in futures]
        self.assertEqual(statuses.count("synthetic_marker_observed"), 1)
        self.assertEqual(
            set(statuses) - {"synthetic_marker_observed"},
            {"inflight_requires_manual_review"}
            if "inflight_requires_manual_review" in statuses else
            {"already_observed_no_retry"},
        )
        self.assertEqual(self.outbox_state(), "observed")
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)

    def test_phase729_acl_and_ci_grant_revocation_still_fail_closed(self):
        self.enqueue_outbox()
        with patch.dict(os.environ, {"LOOMERA_PHASE729_TEST_OUTBOX": "0"}):
            with self.assertRaises(RuntimeError):
                self.dispatch_outbox()
        self.assertEqual(self.outbox_state(), "pending")
        self.assertIsNone(self.admin.get(self.key()))
        self.admin.execute_command("ACL", "SETUSER", "phase728_gateway", "off")
        self.admin.execute_command("CLIENT", "KILL", "USER", "phase728_gateway")
        with self.assertRaises(redis.exceptions.RedisError):
            self.dispatch_outbox()
        self.assertEqual(self.outbox_state(), "inflight")
        self.assertIsNone(self.admin.get(self.key()))

    # Phase 7.30 — read-only review of REAL isolated SQL + Redis effects.
    @property
    def reviewer(self):
        return SyntheticReadOnlyCrossStoreReviewer(self.legacy, self.fixture)

    def inspect730(self, op="a" * 32, digest="b" * 64):
        return self.reviewer.inspect(operation_id=op, fingerprint=digest)

    def test_phase730_pending_intent_never_implies_delivery(self):
        self.enqueue_outbox()
        evidence = self.inspect730()
        self.assertEqual(evidence.classification, "pending_marker_absent")
        self.assertTrue(evidence.redis_reads_stable)
        self.assertFalse(evidence.marker_present)
        self.assertTrue(evidence.requires_manual_review)
        self.assertFalse(evidence.auto_replay_allowed)
        self.assertFalse(evidence.production_release_authorized)
        self.assertEqual(self.outbox_state(), "pending")
        self.assertIsNone(self.admin.get(self.key()))

    def test_phase730_observed_matching_bytes_are_not_delivery_receipt(self):
        self.enqueue_outbox()
        self.assertEqual(self.dispatch_outbox().status, "synthetic_marker_observed")
        evidence = self.inspect730()
        self.assertEqual(evidence.classification, "observed_marker_matches_untrusted")
        self.assertTrue(evidence.marker_present)
        self.assertTrue(evidence.redis_reads_stable)
        self.assertFalse(evidence.external_sms_delivery_proven)
        self.assertFalse(evidence.cross_store_atomic_snapshot_proven)
        self.assertEqual(self.admin.get(self.key()), b"b" * 64)

    def test_phase730_inflight_with_marker_after_real_lost_ack(self):
        self.enqueue_outbox()
        actual_set = self.gateway_client.set

        def physical_write_then_timeout(*args, **kwargs):
            self.assertIs(actual_set(*args, **kwargs), True)
            raise redis.exceptions.ConnectionError("synthetic_lost_ack")

        with patch.object(self.gateway_client, "set",
                          side_effect=physical_write_then_timeout):
            with self.assertRaises(redis.exceptions.ConnectionError):
                self.dispatch_outbox()
        evidence = self.inspect730()
        self.assertEqual(evidence.classification, "inflight_marker_matches_untrusted")
        self.assertTrue(evidence.marker_present)
        self.assertEqual(self.outbox_state(), "inflight")
        self.assertEqual(self.dispatch_outbox().status,
                         "inflight_requires_manual_review")

    def test_phase730_inflight_without_marker_is_also_not_replay_grant(self):
        self.enqueue_outbox()
        with patch.object(self.gateway_client, "set",
                          side_effect=redis.exceptions.ConnectionError(
                              "synthetic_down"
                          )):
            with self.assertRaises(redis.exceptions.ConnectionError):
                self.dispatch_outbox()
        evidence = self.inspect730()
        self.assertEqual(evidence.classification, "inflight_marker_absent")
        self.assertFalse(evidence.marker_present)
        self.assertFalse(evidence.auto_replay_allowed)
        self.assertEqual(self.outbox_state(), "inflight")

    def test_phase730_admin_raw_bypass_visible_but_not_fenced(self):
        self.enqueue_outbox()
        self.assertEqual(self.admin.eval(RAW, 1, self.key(),
                                         "fixture-admin-bypass"), b"OK")
        evidence = self.inspect730()
        self.assertEqual(evidence.classification, "pending_foreign_marker")
        self.assertFalse(evidence.all_redis_ingress_fenced)
        self.assertEqual(self.outbox_state(), "pending")
        self.assertEqual(self.admin.get(self.key()), b"fixture-admin-bypass")
        self.assertEqual(self.authority.halt(
            owner="old", epoch=1,
        ).status, "synthetic_halted")
        self.assertEqual(self.inspect730().classification, "authority_halted")
        self.assertEqual(self.admin.eval(
            RAW, 1, self.key(), "admin-after-halt",
        ), b"OK")
        self.assertEqual(self.admin.get(self.key()), b"admin-after-halt")

    def test_phase730_sql_orphan_ledger_and_intent_are_distinguished(self):
        self.enqueue_outbox()
        with connection.cursor() as cur:
            cur.execute(f'DELETE FROM "{OUTBOX}"')
        self.assertEqual(
            self.inspect730().classification, "orphan_ledger_without_intent",
        )
        with connection.cursor() as cur:
            cur.execute(f'DELETE FROM "{LEDGER}"')
            cur.execute(
                f'INSERT INTO "{OUTBOX}" '
                '(operation_id, fingerprint, epoch, owner, state) '
                'VALUES (%s, %s, %s, %s, %s)',
                ["a" * 32, "b" * 64, 1, "old", "pending"],
            )
        self.assertEqual(
            self.inspect730().classification, "orphan_intent_without_ledger",
        )

    def test_phase730_untracked_redis_marker_and_no_operation(self):
        self.assertEqual(
            self.inspect730().classification, "no_intent_or_marker",
        )
        self.assertTrue(self.admin.set(self.key(), "fixture-untracked"))
        self.assertEqual(
            self.inspect730().classification, "untracked_redis_marker",
        )
        self.assertEqual(self.ledger(), ())

    def test_phase730_fingerprint_mismatch_stays_redacted(self):
        self.enqueue_outbox()
        with connection.cursor() as cur:
            cur.execute(
                f'UPDATE "{OUTBOX}" SET fingerprint=%s WHERE operation_id=%s',
                ["c" * 64, "a" * 32],
            )
        evidence = self.inspect730()
        self.assertEqual(evidence.classification, "conflicting_sql_identity")
        # The report contains only structural classification and bools.
        self.assertNotIn("a" * 32, repr(evidence))
        self.assertNotIn("b" * 64, repr(evidence))
        self.assertNotIn("c" * 64, repr(evidence))

    def test_phase730_stale_epoch_and_missing_lease_are_not_ignored(self):
        self.enqueue_outbox()
        self.assertEqual(self.authority.promote(
            expected_owner="old", expected_epoch=1,
            new_owner="promoted",
        ).status, "synthetic_promoted")
        self.assertEqual(self.inspect730().classification, "owner_epoch_stale")
        with connection.cursor() as cur:
            cur.execute(f'DELETE FROM "{LEASE}"')
        self.assertEqual(self.inspect730().classification, "authority_missing")
        self.assertIsNone(self.admin.get(self.key()))

    def test_phase730_two_reads_detect_interposed_physical_raw_write(self):
        self.enqueue_outbox()
        actual_read = self.legacy.get
        reads = [0]

        def interpose_between_reads(key):
            value = actual_read(key)
            reads[0] += 1
            if reads[0] == 1:
                self.assertTrue(self.admin.set(self.key(), "interposed-raw-write"))
            return value

        with patch.object(self.legacy, "get",
                          side_effect=interpose_between_reads):
            evidence = self.inspect730()
        self.assertEqual(reads[0], 2)
        self.assertEqual(evidence.classification, "redis_changed_during_review")
        self.assertFalse(evidence.redis_reads_stable)
        self.assertTrue(evidence.marker_present)
        self.assertFalse(evidence.auto_replay_allowed)
        self.assertEqual(self.outbox_state(), "pending")

    def test_phase730_reviewer_never_writes_or_repairs_sql_or_redis(self):
        self.enqueue_outbox()
        self.assertTrue(self.admin.set(self.key(), "foreign"))
        before_ledger = self.ledger()
        before_state = self.outbox_state()
        before_marker = self.admin.get(self.key())
        with patch.object(self.legacy, "set",
                          side_effect=AssertionError("read-only violation")):
            self.assertEqual(
                self.inspect730().classification, "pending_foreign_marker",
            )
        self.assertEqual(self.ledger(), before_ledger)
        self.assertEqual(self.outbox_state(), before_state)
        self.assertEqual(self.admin.get(self.key()), before_marker)

    def test_phase730_readonly_actor_denied_writes_and_acl_verified(self):
        self.enqueue_outbox()
        self.assertEqual(
            validate_review_scope(self.legacy, self.fixture), self.prefix,
        )
        with self.assertRaises(redis.exceptions.RedisError):
            self.legacy.set(self.key(), "legacy-writer-denied")
        with self.assertRaises(redis.exceptions.RedisError):
            self.legacy.eval(RAW, 1, self.key(), "legacy-script-denied")
        legacy_acl = self.admin.acl_getuser("phase728_legacy")
        admin_acl = self.admin.acl_getuser("phase728_admin")
        self.assertIn("+get", str(legacy_acl.get("commands", "")))
        self.assertIn("+@all", str(admin_acl.get("commands", "")))
        self.assertFalse(self.inspect730().auto_replay_allowed)

    def test_phase730_revoked_legacy_reader_fails_closed_without_repair(self):
        self.enqueue_outbox()
        self.admin.execute_command("ACL", "SETUSER", "phase728_legacy", "off")
        self.admin.execute_command("CLIENT", "KILL", "USER", "phase728_legacy")
        with self.assertRaises(redis.exceptions.RedisError):
            self.inspect730()
        self.assertEqual(self.outbox_state(), "pending")
        self.assertIsNone(self.admin.get(self.key()))

    def test_phase730_revoked_extra_ci_grant_denies_before_redis_get(self):
        self.enqueue_outbox()
        with patch.dict(os.environ, {"LOOMERA_PHASE730_TEST_REVIEW": "0"}):
            with patch.object(self.legacy, "get",
                              side_effect=AssertionError("unexpected read")):
                with self.assertRaises(RuntimeError):
                    self.inspect730()
        self.assertEqual(self.outbox_state(), "pending")
