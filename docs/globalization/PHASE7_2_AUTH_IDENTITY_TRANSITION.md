# Phase 7.2 — Login/OTP continuity and reversible identity-shadow preparation

**State:** offline shadow reconciliation plus selected mocked runtime compatibility
tests. No international login, new OTP provider, schema migration, live account
changes or deployment. Baseline `986a6a03aa0eed3923a482c3a4bd8e2510e69026`;
Phase 7.1 post-merge run `42217669033` had three successful jobs.

## Verified current contracts

Thirty source anchors in
`docs/globalization/PHASE7_2_AUTH_CONSUMER_INVENTORY.json` are checked
by CI, together with selected runtime functions:

- `CustomUser.mobile_number` is a unique max-11-character
  `USERNAME_FIELD`. Supported existing identities have the literal
  ASCII `09xxxxxxxxx` shape. Web password login and password reset
  continue querying that legacy username, not canonical E.164.
- `BaseSignupForm.clean_mobile_number` may reuse an *inactive* account
  only when the account has no forbidden role and is not admin.
  The test checks inactive reuse, active denial, admin denial and a
  conflicting stylist role. Existing role attachment is not changed.
- Web OTP sessions contain the old normalized Iranian mobile.
  The per-purpose cooldown key also uses that legacy number.
  API OTP record/hash/resend/rate keys bind purpose, mobile and code;
  the API verifier resolves a matching **active** user after successful
  challenge verification. A shadow conversion must not silently change
  the key namespace or authenticate a different account.
- `apps/accounts/views.py` soft deletion rewrites the former login
  identifier to a non-`09` pseudonumber and marks the account inactive
  with an unusable password. It may preserve the historical original
  number in the deletion audit. Treat these as sensitive, unresolved
  cases: do NOT auto-reuse, merge, reconnect or reactivate.
- SMS.ir remains responsible for provider-specific phone formatting,
  and the current API policy still announces IR. Foreign carrier/numbering
  support and SMS provider expansion remain separate work (Phase 14).

This inventory does not prove completeness of dynamic consumers, installed
mobile clients, third-party integrations or all real device/browser flows.

## Pure source-to-shadow contract

`loomera/globalization/phone_identity_transition.py` provides
`compare_phone_identity_shadow`. It compares two finite in-memory
lists and **never contacts a database**. Input remains personal data.
Use ONLY synthetics or an independently authorized isolated export.

Each `source` row must have exactly:
`{"account_id": 101, "mobile_number": "09123456789", "is_active": true}`.

Each `shadow` row retains **all** those fields, adding ONLY
`"canonical_mobile_number": "+989123456789"`.

The source remains the old exact ASCII `09` value, not an overwritten ISO
or E.164 value. The shadow mapping is `to_candidate_e164(source_number)`,
which is only a syntax proposal, not a telecom validation. Source and
shadow must agree in cardinality, account IDs, original mobile strings,
active/inactive totals and every per-row active flag. Duplicate IDs,
duplicate canonical targets, invalid stored numbers, inactive-account
activation, missing/extra rows and any candidate mismatch are hard stops.
Deleted placeholder identities cannot pass as valid mobile numbers.

Reports contain **only counts, flags and fixed reason codes**. A zero-
difference report means `shadow_identity_structurally_clean=true` only.
`production_identity_cutover_authorized`,
`shadow_uniqueness_migration_authorized`,
`existing_sessions_transition_verified`, and
`historical_otp_cache_key_bridge_verified` always remain `false`.

## Opt-in offline CLI with sensitive-data gates

Raw phone values are personal data even when names/addresses are absent.
Do not submit a real export to ChatGPT, GitHub or CI. Run the following
only in a controlled, separately authorized environment:

```sh
LOOMERA_PHASE7_AUTHORIZED_OFFLINE_PHONE_EXPORT=I_CONFIRM_AUTHORIZED_SENSITIVE_OFFLINE_COPY \
python manage.py audit_phase7_phone_shadow \
  --manifest /secure/phone-manifest.json \
  --source /secure/legacy-accounts.json \
  --shadow /secure/iso-shadow.json \
  --acknowledge-sensitive-offline-copy --json
```

**Before any file read**, both acknowledgments must be present. Files
are limited to 5,000,000 bytes each, UTF-8 JSON, unique object keys,
no non-finite values, and exact allowed fields. The manifest declares
operator authorization, not independently established permission.
The SHA-256 checks match the exact bytes of the two data files.

Source-file schema:

```json
{
  "schema_version": 1,
  "representation": "existing_user_mobile_number",
  "rows": [
    {"account_id": 101, "mobile_number": "09123456789", "is_active": true}
  ]
}
```

Shadow-file schema:

```json
{
  "schema_version": 1,
  "representation": "existing_user_plus_canonical_shadow",
  "rows": [
    {
      "account_id": 101,
      "mobile_number": "09123456789",
      "is_active": true,
      "canonical_mobile_number": "+989123456789"
    }
  ]
}
```

Operator manifest example; replace the *illustrative* hashes with
actual SHA-256 of the complete files:

```json
{
  "schema_version": 1,
  "operation": "compare_phone_e164_shadow_only",
  "scope": "authorized_isolated_phone_identity_export",
  "authorization_reference": "OWNER-REVIEW-REFERENCE",
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "shadow_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "expected_accounts": 1,
  "expected_active_accounts": 1,
  "expected_inactive_accounts": 0,
  "default_country": "IR",
  "contains_phone_personal_data": true
}
```

Malformed files, checksum drift and missing acknowledgments fail before
emitting a report. Structural mismatches emit only aggregate counts and
exit nonzero. No account identifiers, raw phones, canonical identifiers,
phone hashes, OTP values or authorization references are output.

## Future staged migration plan — NOT executed

1. **Data provenance:** independently approve access-controlled snapshot
   scope and checksum; count every active/inactive/deleted record, resolve
   placeholder numbers and canonical collisions under a written owner policy.
   Never silently exclude soft-deleted records from uniqueness planning.
2. **Expand:** only through a future separately approved migration add a
   nullable and versioned canonical shadow identity field. Keep the legacy
   username as the source of truth and preserve existing uniqueness and
   all IDs. Rehearse bounded backfills and cross-service concurrency on
   an isolated PostGIS copy.
3. **Dual-read and write safety:** require a versioned lookup contract that
   rejects ambiguity rather than choosing the first matching user.
   Account signup, deletion, reactivation and role changes must be
   transactional and explicitly test concurrent updates.
4. **OTP/session boundary:** prove stable cooldowns, attempt limits,
   rate-limits, HMAC binding, replay protection, old sessions and
   backward-compatible clients before changing any username or cache key.
   An unavailable cache or inconsistent shadow must fail closed.
5. **Cutover/rollback:** security and data owners explicitly sign off,
   with a tested rollback restoring lookups to unchanged legacy values.
   Check all row IDs, statuses, OTP nonce lifecycle, browser/API flows
   and backup hashes. Never automatically reverse-map aliases or merge
   inactive/deleted identities. Production deployment is separate.

**Remaining blockers:** authorized representative phone snapshot, data-owner
collision reconciliation, telecom numbering-plan validation, tested OTP
key/session bridge, complete mobile/third-party consumer review, Phase 3
manual accessibility acceptance and production release authorization.
