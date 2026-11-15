"""Phase 7.33: physical Redis 7.4 named ACL isolation, CI fixture only.

Host and port are fixed to an independent loopback-only disposable container.
The test does not import application settings or real credentials.
"""
from __future__ import annotations

import os
import re
import unittest

from django.conf import settings

if not settings.configured:
    settings.configure(SECRET_KEY="phase733-disposable-only")

import redis
from django_redis.cache import RedisCache


PORT = 6433
DB = 15
ROLES = ("general", "otp", "broker", "result")
PREFIXES = {
    "general": "loomera:phase733:general",
    "otp": "loomera:api-auth-otp-cache",
    "broker": "loomera:phase733:broker",
    "result": "loomera:phase733:result",
}
HEX32 = re.compile(r"[0-9a-f]{32}\Z")


class Phase733PhysicalAclTests(unittest.TestCase):
    @classmethod
    def client(cls, role):
        return redis.Redis(
            host="127.0.0.1", port=PORT, db=DB,
            username="phase733_" + role,
            password=cls.passwords[role.upper()],
            socket_connect_timeout=1, socket_timeout=3,
        )

    @classmethod
    def setUpClass(cls):
        if (
            os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("LOOMERA_PHASE733_TEST_REDIS") != "1"
        ):
            raise RuntimeError("phase733_requires_disposable_ci_grant")
        fixture = os.environ.get("LOOMERA_PHASE733_ID", "")
        if not HEX32.fullmatch(fixture):
            raise RuntimeError("phase733_random_fixture_missing")
        passwords = {}
        for role in ("ADMIN", "GENERAL", "OTP", "BROKER", "RESULT", "OVERBROAD"):
            password = os.environ.get("LOOMERA_PHASE733_" + role + "_PASS", "")
            if not HEX32.fullmatch(password):
                raise RuntimeError("phase733_random_acl_password_missing")
            passwords[role] = password
        cls.fixture = fixture
        cls.passwords = passwords

        bootstrap = redis.Redis(
            host="127.0.0.1", port=PORT, db=DB,
            socket_connect_timeout=1, socket_timeout=3,
        )
        if not bootstrap.ping():
            raise RuntimeError("phase733_disposable_redis_missing")
        try:
            # Fixture-only privileged account intentionally remains a bypass.
            bootstrap.execute_command(
                "ACL", "SETUSER", "phase733_admin", "reset", "on",
                "resetpass", ">" + passwords["ADMIN"], "~*", "+@all",
            )
            cls.admin = cls.client("admin")
            if not cls.admin.ping():
                raise RuntimeError("phase733_fixture_admin_unavailable")
            cls.admin.execute_command("ACL", "SETUSER", "default", "off")
        finally:
            bootstrap.close()

        cls.clients = {}
        cls.caches = {}
        for role in ROLES:
            cls.admin.execute_command(
                "ACL", "SETUSER", "phase733_" + role, "reset", "on",
                "resetpass", ">" + passwords[role.upper()],
                "~" + PREFIXES[role] + ":*",
                "+ping", "+select", "+get", "+set", "+del", "+exists",
                "+pttl", "+expire",
            )
            cls.clients[role] = cls.client(role)
            cls.caches[role] = RedisCache(
                "redis://phase733_" + role + ":" + passwords[role.upper()]
                + "@127.0.0.1:6433/15",
                {
                    "KEY_PREFIX": PREFIXES[role], "VERSION": 1,
                    "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
                },
            )
            if not cls.clients[role].ping():
                raise RuntimeError("phase733_named_principal_unavailable")
        cls.admin.execute_command(
            "ACL", "SETUSER", "phase733_overbroad", "reset", "off"
        )

    @classmethod
    def tearDownClass(cls):
        for client in getattr(cls, "clients", {}).values():
            client.close()
        if hasattr(cls, "admin"):
            cls.admin.close()

    def setUp(self):
        self.logical = "phase733:" + self.fixture + ":marker"
        self.keys = {
            role: str(self.caches[role].make_key(self.logical))
            for role in ROLES
        }
        for role in ROLES:
            self.admin.set(
                self.keys[role], ("synthetic-" + role).encode(), ex=120
            )

    def tearDown(self):
        # Exact, finite keys. Never wildcard SCAN or FLUSH.
        self.admin.delete(*self.keys.values())
        self.admin.execute_command("ACL", "SETUSER", "phase733_overbroad", "off")
        self.admin.execute_command("CLIENT", "KILL", "USER", "phase733_overbroad")

    def test_all_named_clients_read_own_synthetic_marker(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertEqual(
                    self.clients[role].get(self.keys[role]),
                    ("synthetic-" + role).encode(),
                )
                self.assertTrue(
                    self.keys[role].startswith(PREFIXES[role] + ":1:")
                )

    def test_real_django_redis_otp_add_get_delete_uses_production_key_prefix(self):
        cache = self.caches["otp"]
        key = "phase733:" + self.fixture + ":challenge"
        physical = str(cache.make_key(key))
        self.assertTrue(
            physical.startswith("loomera:api-auth-otp-cache:1:")
        )
        try:
            self.assertTrue(
                cache.add(key, {"challenge": "synthetic-only"}, timeout=30)
            )
            self.assertEqual(
                cache.get(key), {"challenge": "synthetic-only"}
            )
            self.assertFalse(
                cache.add(key, {"challenge": "overwritten"}, timeout=30)
            )
            self.assertEqual(
                cache.get(key), {"challenge": "synthetic-only"}
            )
            self.assertGreater(self.clients["otp"].pttl(physical), 0)
            self.assertTrue(cache.delete(key))
            self.assertIsNone(cache.get(key))
        finally:
            self.admin.delete(physical)

    def test_all_twelve_cross_role_get_set_delete_attempts_are_denied(self):
        for actor in ROLES:
            for target in ROLES:
                if actor == target:
                    continue
                key = self.keys[target]
                with self.subTest(actor=actor, target=target):
                    for operation in (
                        lambda: self.clients[actor].get(key),
                        lambda: self.clients[actor].set(key, b"forbidden"),
                        lambda: self.clients[actor].delete(key),
                    ):
                        with self.assertRaises(redis.exceptions.ResponseError):
                            operation()
                    self.assertEqual(
                        self.admin.get(key),
                        ("synthetic-" + target).encode(),
                    )

    def test_actual_acl_dryrun_allows_scoped_io_and_denies_dangerous_commands(self):
        for role in ROLES:
            user = "phase733_" + role
            key = self.keys[role]
            for command in (
                ("GET", key),
                ("SET", key, "value"),
                ("DEL", key),
            ):
                self.assertEqual(
                    self.admin.execute_command("ACL", "DRYRUN", user, *command),
                    b"OK",
                )
            # DRYRUN does not execute the dangerous operation.
            for command in (
                ("ACL", "LIST"), ("CONFIG", "GET", "*"),
                ("EVAL", "return 1", "0"), ("FLUSHDB",),
                ("FLUSHALL",), ("KEYS", "*"), ("SCAN", "0"),
                ("PUBLISH", "topic", "value"),
            ):
                with self.subTest(role=role, cmd=command[0]):
                    self.assertNotEqual(
                        self.admin.execute_command(
                            "ACL", "DRYRUN", user, *command
                        ),
                        b"OK",
                    )

    def test_acl_dryrun_denies_other_role_key_patterns(self):
        for actor in ROLES:
            for target in ROLES:
                if actor != target:
                    self.assertNotEqual(
                        self.admin.execute_command(
                            "ACL", "DRYRUN",
                            "phase733_" + actor, "GET", self.keys[target],
                        ),
                        b"OK",
                    )

    def test_default_anonymous_user_is_disabled(self):
        anonymous = redis.Redis(
            host="127.0.0.1", port=PORT, db=DB,
            socket_connect_timeout=1, socket_timeout=2,
        )
        try:
            with self.assertRaises(redis.exceptions.AuthenticationError):
                anonymous.ping()
        finally:
            anonymous.close()

    def test_fixture_admin_still_bypasses_otp_role_boundary(self):
        self.admin.set(self.keys["otp"], b"fixture-admin-bypass", ex=30)
        self.assertEqual(
            self.clients["otp"].get(self.keys["otp"]),
            b"fixture-admin-bypass",
        )

    def test_different_named_but_overbroad_acl_user_bypasses_all_four_roles(self):
        # This *negative* result is why distinct user names alone are not proof.
        self.admin.execute_command(
            "ACL", "SETUSER", "phase733_overbroad", "reset", "on",
            "resetpass", ">" + self.passwords["OVERBROAD"],
            "~*", "+ping", "+select", "+get", "+set",
        )
        client = self.client("overbroad")
        try:
            for role in ROLES:
                with self.subTest(target=role):
                    self.assertEqual(
                        client.get(self.keys[role]),
                        ("synthetic-" + role).encode(),
                    )
                    self.assertTrue(
                        client.set(self.keys[role], b"overbroad", ex=15)
                    )
                    self.assertEqual(
                        self.clients[role].get(self.keys[role]),
                        b"overbroad",
                    )
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
