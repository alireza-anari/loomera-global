"""Phase 7.19 synthetic network ingress evidence, NEVER a Production fence.

A Docker client bridge is only one path to a data node. A still-writable
Redis master can be accessed through a separate management/host path even
when its dedicated client bridge has been physically disconnected.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IngressNodeObservation:
    node: str
    role: str
    client_bridge_attached: bool
    bridge_raw_write_accepted: bool
    host_raw_write_accepted: bool


@dataclass(frozen=True, slots=True)
class IngressFenceReview:
    status: str
    operator_review_required: bool = True
    authentication_allowed: bool = False
    otp_consume_allowed: bool = False
    otp_issue_allowed: bool = False
    real_session_created: bool = False
    production_write_allowed: bool = False
    old_master_globally_fenced: bool = False
    alternate_ingress_eliminated: bool = False
    distributed_consensus_proven: bool = False
    recovery_authorized: bool = False
    legacy_fallback_allowed: bool = False


def review_ingress_partition(
    observations: tuple[IngressNodeObservation, ...], *,
    replication_partition_verified: bool,
) -> IngressFenceReview:
    if type(observations) is not tuple or len(observations) != 2:
        raise ValueError("exactly two ordered network node observations required")
    if type(replication_partition_verified) is not bool:
        raise TypeError("strict replication partition evidence required")
    for index, node in enumerate(observations):
        if type(node) is not IngressNodeObservation:
            raise TypeError("typed node observations required")
        if type(node.node) is not str or node.node != ("old", "promoted")[index]:
            raise ValueError("ordered old/promoted node identities required")
        if type(node.role) is not str:
            raise TypeError("role must be a strict string")
        for field in ("client_bridge_attached", "bridge_raw_write_accepted",
                      "host_raw_write_accepted"):
            if type(getattr(node, field)) is not bool:
                raise TypeError("strict network observation booleans required")

    old, promoted = observations
    if old.role != "master" or promoted.role != "master":
        return IngressFenceReview("not_two_writable_masters")
    if not replication_partition_verified:
        return IngressFenceReview("replication_partition_unverified")
    if old.client_bridge_attached:
        return IngressFenceReview("old_client_bridge_still_attached")
    if old.bridge_raw_write_accepted:
        return IngressFenceReview("old_client_bridge_still_writable")
    if not promoted.client_bridge_attached or not promoted.bridge_raw_write_accepted:
        return IngressFenceReview("promoted_client_route_unverified")
    if old.host_raw_write_accepted:
        return IngressFenceReview("bridge_fenced_but_host_bypass_open")
    # Even observing denial on two paths never proves every possible ingress,
    # credential, persistent connection, or privileged local writer is fenced.
    return IngressFenceReview("two_local_ingress_paths_observed_only")
