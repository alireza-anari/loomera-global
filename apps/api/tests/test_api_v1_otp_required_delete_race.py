"""Phase 7.34: fail-closed simulated same-record verify race.

This is only a deterministic acknowledgement test, NOT a Redis atomic compare-
and-delete, a multi-node safety proof or an authorization/session test.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Lock
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.api.v1.auth_otp import (
    ApiOtpRateLimitUnavailable,
    hash_otp_code,
    verify_api_otp_code,
)

MOBILE = "09121234567"
CODE = "123456"


class TwoVerifierReadRaceCache:
    def __init__(self, record):
        self.record = deepcopy(record)
        self.read_barrier = Barrier(2, timeout=15)
        self.lock = Lock()
        self.delete_results = []

    def get(self, key, default=None):
        with self.lock:
            snapshot = deepcopy(self.record)
        self.read_barrier.wait(timeout=15)
        return snapshot if snapshot is not None else default

    def delete(self, key):
        with self.lock:
            deleted = self.record is not None
            self.record = None
            self.delete_results.append(deleted)
            return deleted


@override_settings(
    LOOMERA_API_AUTH_OTP_LENGTH=6,
    LOOMERA_API_AUTH_OTP_FAIL_CLOSED=True,
)
class Phase734RequiredDeleteRaceTests(SimpleTestCase):
    def test_both_verifiers_read_same_valid_record_but_only_one_delete_ack(self):
        record = {
            "purpose": "app_login",
            "mobile_number": MOBILE,
            "code_hash": hash_otp_code(
                mobile_number=MOBILE, code=CODE, purpose="app_login"
            ),
            "created_at": 1000,
            "expires_at": 1120,
            "attempts": 0,
            "max_attempts": 3,
            "verified": False,
        }
        cache = TwoVerifierReadRaceCache(record)

        def contender():
            try:
                result = verify_api_otp_code(mobile_number=MOBILE, code=CODE)
                return ("verified", result["verified"])
            except ApiOtpRateLimitUnavailable:
                return ("blocked", False)

        with (
            patch("apps.api.v1.auth_otp._otp_cache", return_value=cache),
            patch("apps.api.v1.auth_otp.api_otp_now_ts", return_value=1050),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            futures = [executor.submit(contender) for _ in range(2)]
            results = [item.result(timeout=20) for item in futures]

        self.assertEqual(sorted(results), [("blocked", False), ("verified", True)])
        self.assertEqual(sorted(cache.delete_results), [False, True])
        self.assertIsNone(cache.record)

    @override_settings(LOOMERA_API_AUTH_OTP_FAIL_CLOSED=False)
    def test_local_failopen_still_requires_confirmed_delete_on_correct_code(self):
        record = {
            "purpose": "app_login",
            "mobile_number": MOBILE,
            "code_hash": hash_otp_code(
                mobile_number=MOBILE, code=CODE, purpose="app_login"
            ),
            "created_at": 1000,
            "expires_at": 1120,
            "attempts": 0,
            "max_attempts": 3,
            "verified": False,
        }

        class AmbiguousCache:
            def get(self, *args, **kwargs):
                return deepcopy(record)

            def delete(self, *args, **kwargs):
                raise RuntimeError("private-backend-detail")

        with (
            patch("apps.api.v1.auth_otp._otp_cache", return_value=AmbiguousCache()),
            patch("apps.api.v1.auth_otp.api_otp_now_ts", return_value=1050),
        ):
            with self.assertRaises(ApiOtpRateLimitUnavailable):
                verify_api_otp_code(mobile_number=MOBILE, code=CODE)
