# Phase 7.34 — live OTP required-deletion acknowledgement hardening

**Targeted live verification safety fix; not an atomic OTP verifier, release approval, or Production deployment.**

Pinned baseline `main`: `e6bae24c6af33b3b461665e05dbe1780acd815e0`.
Phase 7.33 postmerge CI run `43730502132` was still in progress when this branch began; it must be independently confirmed before this PR merges.

## Confirmed live vulnerability

In `apps/api/v1/auth_otp.py`, `_cache_delete(required=True)` previously discarded the actual `cache.delete(key)` return value and returned True even if deletion reported False. The verifier invoked the helper without testing the returned value. If two verifiers had both obtained the valid challenge before one deleted it, the second could proceed toward session creation after an unsuccessful delete.

The same verifier could also proceed after a cache-deletion exception under an explicit local fail-open policy because the helper returned False, which was ignored. Backend failure and missing acknowledgements must never be accepted as proof of a consumed OTP.

## Bounded runtime fix

- `_cache_delete` now captures the backend return, preserving True/nonzero success and best-effort optional cleanup semantics.
- `required=True` with False/0/None rejects verification with `ApiOtpRateLimitUnavailable` even if the local compatibility policy is fail-open.
- A backend exception still follows the configured helper policy for backward compatibility, **but** `verify_api_otp_code` explicitly checks the required-deletion return and rejects any False result regardless of the policy.
- `ApiOtpVerifyAPIView` already maps `ApiOtpRateLimitUnavailable` to a stable HTTP 503 error before looking up or logging in the user. It no longer passes a correct OTP with a known unsuccessful deletion.
- No raw code, password, record, Redis URL, mobile number, or backend exception detail is logged or returned by the new failure path.

## Tests and limits

Add focused helper tests for confirmed success, false/none/zero, optional cleanup and both failure-policy modes. Extend actual API view tests to prove HTTP 503 and **no login** on false acknowledgements or local fail-open deletion exceptions. Add a deterministic two-worker barrier test: both verifiers read the same synthetic record, but when only the first delete confirms success, exactly one verifier proceeds and the second fails closed. Include tests in Fast CI, security regression and release-readiness registries.

**Important: this fix is NOT atomic compare-and-delete.** A new OTP generation can replace the record between GET and DELETE; the stale verifier could delete that newer generation and still pass. Wrong-attempt update and rate/cooldown state likewise use non-atomic read/write. Redis failover, raw admin/stale socket ingress, ambiguous acknowledgements, SQL session/account handoff and external SMS delivery remain unresolved. There is no retry or alternative login path added, and no migration or deployment performed.

**Production release remains BLOCKED** pending a reviewed fully atomic legacy-aware issue/verify/attempt/rate protocol, multi-node authoritative writer fencing, safe migration/drain, account/session and SMS outbox consistency, and independent operational/security signoff.
