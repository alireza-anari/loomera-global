"""Phase 7.6: offline OTP/session drain *evidence review*, not auth cutover.

Only operator-supplied synthetic metadata or separately approved protected
offline exports. Never read a cache, database, session, SMS provider or OTP
code. Outputs contain only fixed reason codes/counts and explicit blockers.
"""
from __future__ import annotations

from loomera.globalization.phone_collision_audit import MAX_ACCOUNTS
from loomera.globalization.phone_identity import (
    PhoneIdentityInputError,
    to_candidate_e164,
)
from loomera.globalization.phone_identity_transition import (
    LEGACY_FIELDS,
    LEGACY_STORAGE_RE,
)

MAX_CHALLENGES = 100_000
CHALLENGE_FIELDS = frozenset((
    "account_id", "mobile_number", "namespace", "issued_at", "expires_at",
    "attempts", "max_attempts", "consumed", "cache_delete_confirmed",
    "password_reset_grant_until",
))
ALLOWED_NAMESPACES = frozenset((
    "web_signup", "web_password_reset", "api_app_login",
))


def review_legacy_otp_transition(
    source_rows: list[dict],
    challenge_rows: list[dict],
    *,
    expected_accounts: int,
    expected_challenges: int,
    now_ts: int,
    cache_integrity_confirmed: bool = False,
    session_store_scope_confirmed: bool = False,
) -> dict:
    """Fail closed on unknown accounts, live grants, stale OTPs, unsafe replay.

    A challenge is *metadata*, not an OTP record: plaintext codes, hashes,
    session IDs, IPs, PII extra fields and unbounded exports are forbidden.
    The outcome never grants a canonical identity or changes any cache keys.
    """
    if (
        type(source_rows) is not list
        or not 1 <= len(source_rows) <= MAX_ACCOUNTS
        or type(challenge_rows) is not list
        or len(challenge_rows) > MAX_CHALLENGES
        or type(expected_accounts) is not int
        or not 1 <= expected_accounts <= MAX_ACCOUNTS
        or type(expected_challenges) is not int
        or not 0 <= expected_challenges <= MAX_CHALLENGES
        or type(now_ts) is not int or now_ts <= 0
        or type(cache_integrity_confirmed) is not bool
        or type(session_store_scope_confirmed) is not bool
    ):
        raise PhoneIdentityInputError("invalid offline OTP review scope")

    source = {}
    canonical_owners = set()
    for row in source_rows:
        if type(row) is not dict or frozenset(row) != LEGACY_FIELDS:
            raise PhoneIdentityInputError("invalid offline account schema")
        ident, mobile, active = (
            row["account_id"], row["mobile_number"], row["is_active"]
        )
        if (
            type(ident) is not int or ident <= 0
            or type(mobile) is not str
            or LEGACY_STORAGE_RE.fullmatch(mobile) is None
            or type(active) is not bool
        ):
            raise PhoneIdentityInputError("invalid offline account identity")
        candidate = to_candidate_e164(mobile)
        if ident in source or candidate in canonical_owners:
            raise PhoneIdentityInputError("duplicated offline account identity")
        source[ident] = (mobile, active)
        canonical_owners.add(candidate)

    unknown = mismatched = inactive = 0
    active_challenges = expired_unconsumed = unconfirmed_deletes = 0
    password_reset_grants = future_issued = exhausted_active = 0
    namespace_counts = {name: 0 for name in sorted(ALLOWED_NAMESPACES)}

    for challenge in challenge_rows:
        if type(challenge) is not dict or frozenset(challenge) != CHALLENGE_FIELDS:
            raise PhoneIdentityInputError("invalid offline challenge schema")
        ident = challenge["account_id"]
        number = challenge["mobile_number"]
        namespace = challenge["namespace"]
        issued = challenge["issued_at"]
        expiry = challenge["expires_at"]
        attempts = challenge["attempts"]
        limit = challenge["max_attempts"]
        consumed = challenge["consumed"]
        deleted = challenge["cache_delete_confirmed"]
        grant = challenge["password_reset_grant_until"]
        if (
            type(ident) is not int or ident <= 0
            or type(number) is not str
            or LEGACY_STORAGE_RE.fullmatch(number) is None
            or type(namespace) is not str
            or namespace not in ALLOWED_NAMESPACES
            or type(issued) is not int or issued <= 0
            or type(expiry) is not int or expiry <= issued
            or type(attempts) is not int or attempts < 0
            or type(limit) is not int or limit <= 0
            or type(consumed) is not bool
            or type(deleted) is not bool
            or (grant is not None and (type(grant) is not int or grant <= 0))
            or (namespace != "web_password_reset" and grant is not None)
        ):
            raise PhoneIdentityInputError("invalid offline challenge values")
        namespace_counts[namespace] += 1
        owner = source.get(ident)
        if owner is None:
            unknown += 1
        elif owner[0] != number:
            mismatched += 1
        if owner is not None and not owner[1]:
            inactive += 1
        if issued > now_ts:
            future_issued += 1
        if attempts >= limit and not consumed and expiry > now_ts:
            exhausted_active += 1
        if not consumed and expiry > now_ts:
            active_challenges += 1
        if not consumed and expiry <= now_ts:
            expired_unconsumed += 1
        # API 'consumed' is safe only with independently evidenced cache
        # deletion. This is NOT a proof that deletion and compare were
        # atomic under two concurrent verifiers.
        if namespace == "api_app_login" and consumed and not deleted:
            unconfirmed_deletes += 1
        if namespace == "web_password_reset" and grant and grant > now_ts:
            password_reset_grants += 1

    reasons = []
    if len(source) != expected_accounts or len(challenge_rows) != expected_challenges:
        reasons.append("declared_snapshot_scope_mismatch")
    if unknown or mismatched:
        reasons.append("challenge_legacy_account_binding_mismatch")
    if inactive:
        reasons.append("inactive_account_challenge_requires_owner_review")
    if active_challenges:
        reasons.append("outstanding_unexpired_legacy_challenge")
    if expired_unconsumed:
        reasons.append("expired_challenge_cleanup_unverified")
    if unconfirmed_deletes:
        reasons.append("api_challenge_deletion_unverified")
    if password_reset_grants:
        reasons.append("password_reset_session_grant_outstanding")
    if future_issued:
        reasons.append("challenge_issued_after_review_clock")
    if exhausted_active:
        reasons.append("exhausted_challenge_cleanup_unverified")
    if not cache_integrity_confirmed:
        reasons.append("legacy_cache_integrity_unverified")
    if not session_store_scope_confirmed:
        reasons.append("web_session_scope_unverified")
    return {
        "schema_version": 1,
        "phase": "7.6",
        "mode": "offline_otp_session_drain_evidence_only",
        "declared_accounts": expected_accounts,
        "accounts_examined": len(source),
        "declared_challenges": expected_challenges,
        "challenges_examined": len(challenge_rows),
        "challenge_counts_by_namespace": namespace_counts,
        "unknown_challenge_accounts": unknown,
        "mismatched_legacy_account_bindings": mismatched,
        "inactive_account_challenges": inactive,
        "outstanding_unexpired_challenges": active_challenges,
        "expired_unconsumed_challenges": expired_unconsumed,
        "api_consumed_without_deletion_proof": unconfirmed_deletes,
        "outstanding_password_reset_grants": password_reset_grants,
        "future_issued_challenges": future_issued,
        "exhausted_active_challenges": exhausted_active,
        "cache_integrity_operator_claimed": cache_integrity_confirmed,
        "session_scope_operator_claimed": session_store_scope_confirmed,
        "metadata_drain_structurally_clean": not reasons,
        "stop_reasons": sorted(reasons),
        "legacy_auth_cache_keys_changed": False,
        "concurrent_verify_atomicity_proven": False,
        "web_plaintext_session_code_eliminated": False,
        "otp_replay_security_signoff_obtained": False,
        "canonical_login_cutover_authorized": False,
        "operator_security_review_required": True,
        "database_reads": 0,
        "cache_reads": 0,
        "sessions_read": 0,
        "writes_performed": 0,
    }
