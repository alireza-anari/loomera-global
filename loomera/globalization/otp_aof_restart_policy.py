"""Phase 7.13: pure offline claims about an isolated Redis AOF restart.

No Redis, subprocess, authentication or session access. Even fully green
caller-provided claims are only test evidence and cannot authorize live reuse.
"""
from __future__ import annotations

from dataclasses import dataclass

_SHUTDOWN = frozenset({"graceful", "sigkill", "not_executed"})
_PERSISTENCE = frozenset({"aof", "rdb_only", "disabled", "unknown"})
_FSYNC = frozenset({"always", "everysec", "no", "unknown"})
_MARKER = frozenset({"verified", "missing", "corrupt", "unreadable"})
_MODE = frozenset({"observing", "quarantined", "halted", "unknown"})
_ACK = frozenset({"confirmed", "timeout", "unknown"})


@dataclass(frozen=True, slots=True)
class SyntheticAofRestartEvidence:
    shutdown: str
    persistence: str
    appendfsync: str
    docker_isolated: bool
    fresh_process: bool
    same_test_volume: bool
    reference_marker: str
    volatile_marker: str
    expected_generation: int
    observed_generation: int
    mode_before: str
    mode_after: str
    fingerprint_matches: bool
    reason_matches: bool
    last_write_ack: str
    no_real_data: bool
    session_store_untouched: bool
    legacy_path_untouched: bool


@dataclass(frozen=True, slots=True)
class SyntheticAofRestartReview:
    status: str
    security_review_required: bool = True
    real_failover_proven: bool = False
    independently_durable_marker_proven: bool = False
    authenticated: bool = False
    otp_reissue_allowed: bool = False
    resume_allowed: bool = False
    missing_marker_reseed_allowed: bool = False
    session_retry_allowed: bool = False
    legacy_fallback_allowed: bool = False
    production_recovery_authorized: bool = False


def review_synthetic_aof_restart(
    evidence: SyntheticAofRestartEvidence,
) -> SyntheticAofRestartReview:
    """Fail closed on *claimed* restart evidence; never return an auth grant."""
    if type(evidence) is not SyntheticAofRestartEvidence:
        raise TypeError("exact synthetic AOF restart evidence required")
    for field, values in (
        ("shutdown", _SHUTDOWN),
        ("persistence", _PERSISTENCE),
        ("appendfsync", _FSYNC),
        ("reference_marker", _MARKER),
        ("volatile_marker", _MARKER),
        ("mode_before", _MODE),
        ("mode_after", _MODE),
        ("last_write_ack", _ACK),
    ):
        value = getattr(evidence, field)
        if type(value) is not str or value not in values:
            raise ValueError("unsupported synthetic AOF restart evidence enum")
    for field in (
        "docker_isolated", "fresh_process", "same_test_volume",
        "fingerprint_matches", "reason_matches", "no_real_data",
        "session_store_untouched", "legacy_path_untouched",
    ):
        if type(getattr(evidence, field)) is not bool:
            raise ValueError("exact boolean evidence required")
    for field in ("expected_generation", "observed_generation"):
        value = getattr(evidence, field)
        if type(value) is not int or not 1 <= value <= 1_000_000_000:
            raise ValueError("bounded generation required")

    if evidence.shutdown == "not_executed" or not evidence.fresh_process:
        return SyntheticAofRestartReview("restart_not_proven")
    if not evidence.docker_isolated or not evidence.no_real_data:
        return SyntheticAofRestartReview("unsafe_test_scope")
    if evidence.persistence != "aof" or evidence.appendfsync != "always":
        return SyntheticAofRestartReview("aof_not_verified")
    if not evidence.same_test_volume:
        return SyntheticAofRestartReview("volume_untrusted")
    if evidence.reference_marker != "verified":
        return SyntheticAofRestartReview("reference_untrusted")
    if evidence.volatile_marker != "verified":
        return SyntheticAofRestartReview("volatile_untrusted")
    if evidence.observed_generation < evidence.expected_generation:
        return SyntheticAofRestartReview("generation_regressed")
    if evidence.observed_generation > evidence.expected_generation:
        return SyntheticAofRestartReview("future_generation_untrusted")
    if not evidence.fingerprint_matches:
        return SyntheticAofRestartReview("fingerprint_mismatch")
    if not evidence.reason_matches:
        return SyntheticAofRestartReview("quarantine_reason_mismatch")
    if evidence.mode_before != evidence.mode_after:
        return SyntheticAofRestartReview("mode_changed_during_restart")
    if evidence.mode_after == "unknown":
        return SyntheticAofRestartReview("mode_unknown")
    if evidence.last_write_ack != "confirmed":
        return SyntheticAofRestartReview("write_outcome_ambiguous")
    if not evidence.session_store_untouched or not evidence.legacy_path_untouched:
        return SyntheticAofRestartReview("live_path_boundary_violation")
    if evidence.mode_after == "halted":
        return SyntheticAofRestartReview("halted_marker_observed")
    if evidence.mode_after == "quarantined":
        return SyntheticAofRestartReview("quarantined_marker_observed")
    # Even observing on a functioning test host grants nothing.
    return SyntheticAofRestartReview("isolated_restart_observed_only")
