# Phase 7.1 — Phone Identity Foundation (proposal, no live auth changes)

**Status: foundation, collision-risk audit only.** Baseline main
`1c93cb13bdba14f02953425929f08ff27fe25d83`, with all three
post-merge CI jobs green in run `42213767290`. The previous globalization
Phase 6 still requires authorized representative data, timezone provenance
and manual acceptance; Phase 7.1 work does **not** waive those gates.

## Existing contract (not modified by this PR)

- `apps/accounts/models.py:CustomUser.mobile_number` is the unique,
  max-11-character login identifier and Django `USERNAME_FIELD`.
- `apps/accounts/views.py` authenticates using exactly the form's existing
  mobile value; password reset and OTP look up by the legacy key.
  Signup, role attachment, soft-deletion and inactive-user behavior must
  not change before a separately authorized identity migration.
- `apps/accounts/forms.py` and `apps/api/v1/auth_serializers.py`
  validate Iranian `09...` identities; public API remains region IR.
- `apps/accounts/services/sms.py` intentionally owns SMS.ir-specific
  format, masking and provider behavior. OTP cache keys, resend cooldown,
  attempt budgets, per-IP/per-mobile throttling, privacy and session
  authentication remain unchanged. Provider expansion is Phase 14.

Do **not** repurpose the existing 11-char database column to hold
`+...` identities: doing so would truncate accounts and potentially
create collisions. No migration/field change is included here.

## Candidate E.164 syntax boundary

`loomera/globalization/phone_identity.py:to_candidate_e164` is a pure
proposed adapter **not used** by live accounts/OTP forms/API.

- An existing Iranian `09xxxxxxxxx` mobile resolves to
  `+989xxxxxxxxx`. Strictly supported legacy aliases:
  `9xxxxxxxxx`, `989xxxxxxxxx`, `00989xxxxxxxxx`,
  `+989xxxxxxxxx`, and normalized Persian/Arabic digit inputs,
  allowing simple ASCII spaces and hyphens.
- Other countries require explicit `+` plus 8–15 ASCII digits
  (starting with 1–9). The configured default-country hint does
  **not** invent foreign trunk prefix handling, numbering-plan
  validation, carrier eligibility or confirmed SMS deliverability.
- Any `+98` number must be a valid 10-digit Iranian mobile national
  number beginning with `9`. No punctuation stripping of arbitrary
  input, Unicode lookalikes, non-digits or silent E.164 cutover.
- Canonicalization may map *different raw stored strings* to the same
  identity. **All** collisions, including two inactive accounts, are
  hard stops requiring a human decision. No account records are merged.

## PII-safe offline collision audit

`loomera/globalization/phone_collision_audit.py` counts invalid phone
values, duplicate/invalid account IDs, canonical collisions and whether
collisions involve active identities. It does not return phone numbers,
record IDs, hashes or groups. Up to 50,000 synthetic or strictly
**operator-authorized** isolated account export rows per run.

**Important:** raw phone numbers remain personal data even if all unrelated
customer fields have been removed. Do not upload a real export to ChatGPT,
commit it to GitHub or include it in CI. The operator must use an isolated,
access-controlled environment approved for sensitive information. There is
no claim of independent authorization validation.

The opt-in CLI:
```sh
LOOMERA_PHASE7_AUTHORIZED_OFFLINE_PHONE_EXPORT=I_CONFIRM_AUTHORIZED_SENSITIVE_OFFLINE_COPY \
python manage.py audit_phase7_phone_identity \
  --manifest /secure/phone-manifest.json \
  --input /secure/phone-export.json \
  --acknowledge-sensitive-offline-copy --json
```

Both acknowledgments are required **before opening files**. The two files
must be UTF-8 JSON, each at most 5,000,000 bytes, without duplicate keys
or NaN. Source files are read only; exact bytes must match manifest SHA-256.
A failure never prints a raw number or account ID. The CLI exits nonzero
for malformed input or collision/incomplete snapshot findings.

### Input JSON structure (illustrative, synthetic only)

```json
{
  "schema_version": 1,
  "representation": "existing_user_mobile_number",
  "rows": [
    {"account_id": 101, "mobile_number": "09123456789", "is_active": true}
  ]
}
```

### Manifest JSON structure (illustrative hash to be replaced)

```json
{
  "schema_version": 1,
  "scope": "authorized_isolated_phone_identity_export",
  "authorization_reference": "APPROVAL-REFERENCE",
  "export_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "expected_accounts": 1,
  "default_country": "IR",
  "contains_phone_personal_data": true,
  "operation": "canonical_collision_preview_only"
}
```

Compute the SHA-256 over *exact file bytes*, not parsed JSON.
Every row must have exactly the 3 documented fields. No customer name,
address, contact, email, OTP secret, password, cache token or role data is
permitted. The manifest is an operator declaration; checksum equality
proves byte integrity only, **not** export authenticity/consent.

A `preflight_structurally_clean=true` result is only an aggregate
offline result. It explicitly keeps
`identity_cutover_authorized=false`, `uniqueness_migration_authorized=false`
and `account_merge_authorized=false`.

## Proposed staged future path (not implemented)

1. Review the source inventory across signup, password login/reset, API
   OTP, admin, SMS.ir, customer management, deletion/reactivation and
   all referencing tables. Inventory may be incomplete for dynamic callers.
2. Obtain authorized snapshot provenance and independent collision evidence.
   Resolve accounts with invalid/placeholder identities and any canonical
   collision under the owner's written policy, never automatically.
3. Separately approve a nullable canonical shadow identity field, safety
   constraints, uniqueness strategy, foreign numbering-plan library,
   transactional dual-read/dual-write policy and old-session/OTP key bridging.
4. Before cutover, prove old Iranian users can still sign in, reset
   passwords and verify OTP with unchanged security/rate limits; demonstrate
   full role/client compatibility and a versioned fallback/rollback path.
5. Approve carrier/provider expansion only in Phase 14. No Production
   deployment, raw snapshot handling or account migration in Phase 7.1.

**Blocked:** real-data permission, collision reconciliation, numbering-plan
validation, canonical uniqueness migration, login/OTP client readiness,
manual Phase 3 acceptance and Production authorization.
