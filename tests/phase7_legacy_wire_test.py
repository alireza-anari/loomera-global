"""Phase 7.8 real Django-Redis wire rehearsal on disposable Redis DB15.

Uses the Django-Redis 5.4.0 backend with synthetic legacy OTP records.
No API/web views, actual users, external services or production cache.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os
import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
if not settings.configured:
    settings.configure(SECRET_KEY="phase78-only-test-secret-never-use-in-production")

import redis
from django.utils.crypto import salted_hmac
from django_redis.cache import RedisCache

from loomera.globalization.otp_cache_wire_rehearsal import (
    PREFIX, LegacyWireEvidence, inspect_synthetic_legacy_wire,
)
from loomera.globalization.otp_atomic_redis_rehearsal import (
    ATOMIC_CONSUME_SCRIPT, SyntheticRedisOtpRehearsal, SYNTHETIC_PREFIX,
)

REDIS_URL = "redis://127.0.0.1:6379/15"
MOBILE = "09123456789"
LOGICAL = f"record:app_login:{MOBILE}"


def new_cache(fixture_id):
    return RedisCache(REDIS_URL, {
        "KEY_PREFIX": PREFIX + fixture_id, "VERSION": 1,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    })


def synthetic_record():
    return {
        "purpose": "app_login", "mobile_number": MOBILE,
        "code_hash": salted_hmac(
            "loomera.api.auth.otp", f"app_login:{MOBILE}:123456"
        ).hexdigest(),
        "created_at": 1000, "expires_at": 1120,
        "attempts": 0, "max_attempts": 5, "verified": False,
        "delivery": {"channel": "sms", "mode": "simulated",
                     "sent": False, "provider": "none"},
    }


class Phase78DjangoRedisWireTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("LOOMERA_PHASE78_TEST_REDIS") != "1":
            self.fail("Phase 7.8 requires explicitly authorized ephemeral Redis")
        self.client = redis.Redis.from_url(REDIS_URL, socket_timeout=6)
        self.assertTrue(self.client.ping())
        self.fixture_id = uuid4().hex
        self.cache = new_cache(self.fixture_id)
        self.keys = [LOGICAL]
        self.shadow_key = SYNTHETIC_PREFIX + uuid4().hex

    def tearDown(self):
        try:
            # Only exact synthetic keys created in this fixture.
            for logical in self.keys:
                self.client.delete(str(self.cache.make_key(logical)))
            self.client.delete(self.shadow_key)
        finally:
            self.client.close()

    def _write(self, record=None, *, ttl=120):
        self.assertTrue(self.cache.set(
            LOGICAL, synthetic_record() if record is None else record,
            timeout=ttl,
        ))

    def _inspect(self):
        return inspect_synthetic_legacy_wire(
            self.cache, self.client,
            fixture_id=self.fixture_id, logical_key=LOGICAL,
        )

    def test_real_django_redis_wire_is_string_and_not_phase77_hash(self):
        self._write()
        key = str(self.cache.make_key(LOGICAL))
        self.assertEqual(self.client.type(key), b"string")
        self.assertGreater(self.client.pttl(key), 0)
        self.assertEqual(self.cache.get(LOGICAL), synthetic_record())
        self.assertEqual(len(self.cache.get(LOGICAL)["code_hash"]), 40)
        self.assertEqual(self._inspect().status, "legacy_string_pending_drain")
        self.assertFalse(self._inspect().hash_compatible)
        with self.assertRaises(redis.exceptions.ResponseError):
            self.client.eval(
                ATOMIC_CONSUME_SCRIPT, 1, key,
                "app_login", MOBILE, "0" * 64, 1050,
            )

    def test_read_only_inspection_keeps_bytes_and_ttl_and_never_grants_login(self):
        self._write()
        key = str(self.cache.make_key(LOGICAL))
        original = self.client.get(key)
        before = self.client.pttl(key)
        evidence = self._inspect()
        self.assertEqual(self.client.get(key), original)
        self.assertLessEqual(self.client.pttl(key), before)
        self.assertEqual(evidence.status, "legacy_string_pending_drain")
        self.assertFalse(evidence.authenticated)
        self.assertFalse(evidence.cutover_authorized)
        self.assertEqual(evidence.ttl_ms > 0, True)
        for sensitive in (MOBILE, "123456", synthetic_record()["code_hash"], key):
            self.assertNotIn(sensitive, repr(evidence))

    def test_missing_legacy_key_never_authorizes_transition(self):
        self.assertEqual(self._inspect(), LegacyWireEvidence("absent"))

    def test_legacy_expiry_and_persistent_key_fail_closed(self):
        key = str(self.cache.make_key(LOGICAL))
        self._write()
        self.client.persist(key)
        self.assertEqual(self._inspect().status, "missing_or_invalid_ttl")

    def test_wrong_type_is_blocked_without_mutation(self):
        key = str(self.cache.make_key(LOGICAL))
        self.client.hset(key, "purpose", "app_login")
        self.client.pexpire(key, 120000)
        self.assertEqual(self._inspect().status, "incompatible_redis_type")
        self.assertEqual(self.client.type(key), b"hash")

    def test_corrupt_and_inconsistent_records_block(self):
        for payload in (
            {"purpose": "app_login"},
            {**synthetic_record(), "mobile_number": "09123456780"},
            {**synthetic_record(), "verified": True},
            {**synthetic_record(), "attempts": 5},
            {**synthetic_record(), "code_hash": "plaintext"},
            {**synthetic_record(), "created_at": True},
        ):
            with self.subTest(fields=tuple(payload.keys())):
                self._write(payload)
                self.assertEqual(self._inspect().status, "invalid_legacy_payload")

    def test_corrupted_serialization_fails_without_plaintext_exposure(self):
        key = str(self.cache.make_key(LOGICAL))
        self.client.setex(key, 60, b"not a pickle or valid cache record")
        evidence = self._inspect()
        self.assertEqual(evidence.status, "backend_unavailable")
        self.assertFalse(evidence.authenticated)

    def test_two_independent_cache_clients_can_compare_before_one_delete(self):
        """Demonstrates legacy GET/compare/DELETE race; never logs anyone in."""
        self._write()
        barrier = Barrier(2, timeout=20)

        def contender():
            other = new_cache(self.fixture_id)
            seen = other.get(LOGICAL)
            valid = secrets.compare_digest(
                seen["code_hash"], synthetic_record()["code_hash"]
            )
            barrier.wait(timeout=20)
            return (valid, bool(other.delete(LOGICAL)))

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(contender)
            b = pool.submit(contender)
            results = [a.result(timeout=20), b.result(timeout=20)]
        self.assertEqual([a for a, _ in results], [True, True])
        self.assertEqual(sorted(b for _, b in results), [False, True])
        self.assertIsNone(self.cache.get(LOGICAL))

    def test_shadow_namespace_does_not_consume_legacy_or_resend_keys(self):
        self._write()
        resend = f"resend:app_login:{MOBILE}"
        rate = "rate:mobile:synthetic:0"
        self.keys.extend((resend, rate))
        self.cache.set(resend, 1000, timeout=60)
        self.cache.set(rate, 2, timeout=3600)
        # A test-only HASH must never share the Django-Redis serialized key.
        experimental = SyntheticRedisOtpRehearsal(self.client, key=self.shadow_key)
        self.assertTrue(experimental.seed(
            purpose="app_login", legacy_mobile=MOBILE,
            code_digest="a" * 64, now_ts=1000, expires_at=1120,
        ))
        self.assertEqual(self.client.type(self.shadow_key), b"hash")
        self.assertEqual(self._inspect().status, "legacy_string_pending_drain")
        self.assertEqual(self.cache.get(resend), 1000)
        self.assertEqual(self.cache.get(rate), 2)
        with self.assertRaises(ValueError):
            SyntheticRedisOtpRehearsal(
                self.client, key=str(self.cache.make_key(LOGICAL))
            )

    def test_missing_authorization_or_invalid_db_rejected_before_read(self):
        self._write()
        with patch.dict(os.environ, {"LOOMERA_PHASE78_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self._inspect()
        remote_cache = RedisCache("redis://example.invalid:6379/15", {
            "KEY_PREFIX": PREFIX + self.fixture_id, "VERSION": 1,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        })
        with self.assertRaises(RuntimeError):
            inspect_synthetic_legacy_wire(
                remote_cache, self.client,
                fixture_id=self.fixture_id, logical_key=LOGICAL,
            )
        remote = redis.Redis.from_url("redis://127.0.0.1:6379/14")
        with self.assertRaises(RuntimeError):
            inspect_synthetic_legacy_wire(
                self.cache, remote, fixture_id=self.fixture_id, logical_key=LOGICAL
            )
        with self.assertRaises(ValueError):
            inspect_synthetic_legacy_wire(
                self.cache, self.client,
                fixture_id=self.fixture_id, logical_key="record:app_login:+989123456789"
            )

    def test_key_prefix_and_version_must_be_exact_synthetic_scope(self):
        self._write()
        wrong = new_cache(uuid4().hex)
        with self.assertRaises(RuntimeError):
            inspect_synthetic_legacy_wire(
                wrong, self.client, fixture_id=self.fixture_id, logical_key=LOGICAL,
            )
        with self.assertRaises(ValueError):
            inspect_synthetic_legacy_wire(
                self.cache, self.client, fixture_id="bad", logical_key=LOGICAL,
            )


if __name__ == "__main__":
    unittest.main()
