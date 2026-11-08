"""Phase 7.27, offline ingress inventory / isolated Redis scope (NEVER live auth).

Phase 7.26 PostgreSQL is a voluntary gate. A raw Redis client can bypass
that gate. Observing local ACL denial does not prove a global writer fence.
All result flags deliberately deny real OTP, SMS, sessions, or deployment.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Any

PREFIX = "loomera:phase727:synthetic-pg-redis-only:"
REDIS_URL = "redis://127.0.0.1:6427/15"
ROUTES = (
    "pg_cooperating_old",
    "old_host_raw",
    "preexisting_stale_socket",
    "promoted_raw",
    "privileged_admin_raw",
    "anonymous_raw",
)
_ID = re.compile(r"[0-9a-f]{32}\Z")


def validate_disposable_redis(client: Any, fixture_id: str) -> str:
    """Reject off-CI/other DB/other host before any Redis command is sent."""
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("LOOMERA_PHASE727_TEST_REDIS") != "1"
        or not os.environ.get("GITHUB_RUN_ID")
        or not os.environ.get("GITHUB_RUN_ATTEMPT")
    ):
        raise RuntimeError("phase727_ci_scope_grant_required")
    if type(fixture_id) is not str or _ID.fullmatch(fixture_id) is None:
        raise ValueError("invalid_synthetic_fixture")
    kwargs = getattr(getattr(client, "connection_pool", None),
                     "connection_kwargs", None)
    if type(kwargs) is not dict:
        raise RuntimeError("phase727_redis_client_missing_scope")
    if (
        kwargs.get("host") != "127.0.0.1"
        or type(kwargs.get("port")) is not int
        or kwargs["port"] != 6427
        or type(kwargs.get("db")) is not int
        or kwargs["db"] != 15
    ):
        raise RuntimeError("phase727_wrong_redis_target")
    return PREFIX + fixture_id + ":"


@dataclass(frozen=True, slots=True)
class SyntheticIngressRoute:
    route: str
    authority_checked: bool
    raw_write_accepted: bool

    def __post_init__(self) -> None:
        if type(self.route) is not str or self.route not in ROUTES:
            raise ValueError("unknown_ingress_route")
        if type(self.authority_checked) is not bool:
            raise TypeError("untyped_authority_check")
        if type(self.raw_write_accepted) is not bool:
            raise TypeError("untyped_ingress_result")


@dataclass(frozen=True, slots=True)
class SyntheticIngressReview:
    status: str
    operator_review_required: bool = True
    actual_global_writer_fencing_proven: bool = False
    all_ingress_routes_closed: bool = False
    production_authentication_allowed: bool = False
    real_otp_issue_or_consume_allowed: bool = False
    real_sms_delivery_allowed: bool = False
    real_session_created: bool = False
    postgres_redis_atomicity_proven: bool = False
    production_release_authorized: bool = False


def review_synthetic_ingress(
    routes: tuple[SyntheticIngressRoute, ...], *,
    pg_stale_claim_rejected: bool,
    local_stale_acl_revoked: bool,
) -> SyntheticIngressReview:
    if type(routes) is not tuple or len(routes) != len(ROUTES):
        raise ValueError("exact_ingress_inventory_required")
    if type(pg_stale_claim_rejected) is not bool:
        raise TypeError("untyped_postgres_evidence")
    if type(local_stale_acl_revoked) is not bool:
        raise TypeError("untyped_redis_acl_evidence")
    for expected, row in zip(ROUTES, routes):
        if type(row) is not SyntheticIngressRoute or row.route != expected:
            raise ValueError("ingress_order_or_type_mismatch")
    if routes[0].authority_checked is not True:
        return SyntheticIngressReview("pg_authority_not_observed")
    if not pg_stale_claim_rejected:
        return SyntheticIngressReview("pg_stale_writer_denial_missing")
    if any(row.raw_write_accepted and not row.authority_checked
           for row in routes):
        return SyntheticIngressReview("ungated_raw_redis_writer_observed")
    if not local_stale_acl_revoked:
        return SyntheticIngressReview("local_credential_revocation_unverified")
    return SyntheticIngressReview("bounded_local_denial_evidence_only")
