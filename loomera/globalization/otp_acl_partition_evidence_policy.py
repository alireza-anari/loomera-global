"""Test-only Phase 7.18 ACL partition evidence; never an auth or release grant."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AclNodeObservation:
    node: str
    role: str
    default_disabled: bool
    stale_user_enabled: bool
    stale_raw_write_accepted: bool


@dataclass(frozen=True, slots=True)
class AclPartitionReview:
    status: str
    operator_review_required: bool = True
    authentication_allowed: bool = False
    otp_consume_allowed: bool = False
    session_created: bool = False
    production_write_allowed: bool = False
    global_fencing_proven: bool = False
    external_revocation_proven: bool = False
    consensus_proven: bool = False
    fallback_allowed: bool = False


def review_acl_partition(observations, *, old_admin_reachable):
    if type(observations) is not tuple or len(observations) != 2:
        raise ValueError("two ordered observations required")
    if type(old_admin_reachable) is not bool:
        raise TypeError("strict boolean required")
    for index, item in enumerate(observations):
        if type(item) is not AclNodeObservation:
            raise TypeError("typed ACL observations required")
        if type(item.node) is not str or item.node != ("old", "promoted")[index]:
            raise ValueError("ordered old/promoted identities required")
        if type(item.role) is not str:
            raise TypeError("strict role string required")
        for name in ("default_disabled", "stale_user_enabled",
                     "stale_raw_write_accepted"):
            if type(getattr(item, name)) is not bool:
                raise TypeError("strict ACL observation boolean required")
    old, promoted = observations
    if old.role != "master" or promoted.role != "master":
        return AclPartitionReview("topology_not_two_masters")
    if not old.default_disabled or not promoted.default_disabled:
        return AclPartitionReview("anonymous_default_user_open")
    if promoted.stale_user_enabled or promoted.stale_raw_write_accepted:
        return AclPartitionReview("promoted_stale_user_not_revoked")
    if old.stale_raw_write_accepted:
        return AclPartitionReview("stale_old_raw_writer_bypass")
    if old.stale_user_enabled:
        return AclPartitionReview("old_stale_user_still_enabled")
    if not old_admin_reachable:
        return AclPartitionReview("old_control_plane_unverified")
    return AclPartitionReview("local_old_acl_revocation_observed_only")
