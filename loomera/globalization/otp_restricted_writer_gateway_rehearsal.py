"""Phase 7.28 synthetic-only, UNWIRED PostGIS -> restricted Redis write gate.

A cooperating test gateway holds the PostgreSQL lease/operation lock during
an isolated Redis SET NX. Redis ACL admits only the gateway *within this test
fixture*, except a deliberately retained fixture administrator. No global
fencing or cross-store transaction is claimed. DO NOT import from live auth.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

from django.db import connection, transaction

from loomera.globalization.otp_postgis_writer_authority_rehearsal import (
    SyntheticPostGISWriterAuthority, _check_epoch_owner, _check_operation,
    verify_ci_test_scope,
)

PORT = 6428
DB = 15
PREFIX = "loomera:phase728:restricted-gateway-only:"
GATEWAY_USER = "phase728_gateway"
_ID = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class SyntheticGatewayObservation:
    status: str
    synthetic_redis_marker_written: bool = False
    real_authentication_allowed: bool = False
    real_otp_issue_or_consume_allowed: bool = False
    real_session_created: bool = False
    real_sms_sent: bool = False
    all_redis_ingress_fenced: bool = False
    cross_store_atomicity_proven: bool = False
    production_release_authorized: bool = False


def validate_gateway_scope(client: Any, fixture_id: str) -> str:
    """Deny non-CI contexts and wrong Redis clients BEFORE network/SQL IO."""
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("LOOMERA_PHASE728_TEST_REDIS") != "1"
        or os.environ.get("LOOMERA_PHASE726_TEST_POSTGIS") != "1"
        or not os.environ.get("GITHUB_RUN_ID")
        or not os.environ.get("GITHUB_RUN_ATTEMPT")
    ):
        raise RuntimeError("phase728_both_ci_grants_required")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("phase728_invalid_fixture_id")
    kwargs = getattr(getattr(client, "connection_pool", None),
                     "connection_kwargs", None)
    if type(kwargs) is not dict:
        raise RuntimeError("phase728_missing_redis_connection_scope")
    if (
        kwargs.get("host") != "127.0.0.1"
        or type(kwargs.get("port")) is not int or kwargs["port"] != PORT
        or type(kwargs.get("db")) is not int or kwargs["db"] != DB
        or kwargs.get("username") != GATEWAY_USER
    ):
        raise RuntimeError("phase728_restricted_gateway_client_required")
    return PREFIX + fixture_id + ":"


class SyntheticRestrictedWriterGateway:
    """Strict cooperation boundary; a privileged direct Redis socket bypasses it."""

    def __init__(self, client: Any, fixture_id: str):
        self.client = client
        self.fixture_id = fixture_id
        self._scope()
        self.authority = SyntheticPostGISWriterAuthority()

    def _scope(self) -> str:
        prefix = validate_gateway_scope(self.client, self.fixture_id)
        verify_ci_test_scope(connection)
        return prefix

    def submit(self, *, owner: str, epoch: int, operation_id: str,
               fingerprint: str) -> SyntheticGatewayObservation:
        _check_epoch_owner(owner, epoch)
        _check_operation(operation_id, fingerprint)
        key = self._scope() + "operation:" + operation_id
        # Lock the PG authority row across the Redis call, so cooperating
        # promotion cannot interleave with the write. This is STILL NOT a
        # distributed transaction: a PG rollback can leave Redis committed.
        with transaction.atomic(using="default"):
            claim = self.authority.claim(
                owner=owner, epoch=epoch, operation_id=operation_id,
                fingerprint=fingerprint,
            )
            if claim.status != "synthetic_committed":
                return SyntheticGatewayObservation(claim.status)
            # SET NX refuses silent key overwrite after a lost PG commit.
            # A missing Redis acknowledgement is an error, never a retry grant.
            acknowledged = self.client.set(key, fingerprint, nx=True)
            if acknowledged is not True:
                raise RuntimeError("phase728_ambiguous_redis_marker_collision")
            return SyntheticGatewayObservation(
                "synthetic_redis_marker_observed",
                synthetic_redis_marker_written=True,
            )
