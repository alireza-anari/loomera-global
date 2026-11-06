# Phase 6.4 — offline weekday shadow comparison and operator stop/rollback gates

Status: **implemented as an offline read-only rehearsal**, NOT a schema
migration, ISO cutover, credential verification, staging or Production approval.
Baseline main: `53638f29dc3ce0df5d7a8dbb6b389baecd04de50`, Phase 6.3
post-merge CI run `42200663139` (all three jobs succeeded).

## The only supported use

`python manage.py audit_weekday_cutover_files --manifest /secure/manifest.json --source /secure/source.json --shadow /secure/shadow.json --acknowledge-offline-sanitized-copy --json`

The invoking operator must additionally set the environment variable
`LOOMERA_PHASE6_OFFLINE_SANITIZED_CONFIRMATION` to the literal
`I_CONFIRM_AUTHORIZED_OFFLINE_SANITIZED_COPY`. Both independent acknowledgments
are required **before any file is opened**. This is an operator declaration,
**not** independent proof of authorization. The command never opens a database
connection and never modifies either input file. Do not pass a live DB URL
or run against live data. Run only on an authorized isolated sanitized export
stored outside the repository, with controlled access. Never commit exports.

Input files must be valid UTF-8 JSON, at most 4,000,000 bytes each, without
duplicate keys or NaN/Infinity. Unexpected fields are **rejected** rather than
silently accepted. Reports contain only aggregate counts and constant reason
codes; do not include raw rows, identifiers, dates, time windows or zone names.
Even a fully clean report explicitly sets `cutover_authorized=false`,
`migration_approved=false`, and `rollback_approved=false`.

### Source JSON, schema version 1

```json
{
  "schema_version": 1,
  "representation": "legacy_saturday_1",
  "rows": [
    {
      "row_id": 101,
      "salon_id": 10,
      "day_of_week": 1,
      "is_closed": false,
      "open_time": "09:00",
      "close_time": "17:00",
      "timezone_name": "Asia/Tehran"
    }
  ]
}
```

The example is schematic; an actual isolated dataset needs exactly one
record for all seven days of every included salon, including closed days.
Dates/hours are illustrative and no real user data is supplied.

### ISO shadow JSON, schema version 1

```json
{
  "schema_version": 1,
  "representation": "legacy_with_iso_shadow",
  "rows": [
    {
      "row_id": 101,
      "salon_id": 10,
      "day_of_week": 1,
      "is_closed": false,
      "open_time": "09:00",
      "close_time": "17:00",
      "timezone_name": "Asia/Tehran",
      "iso_weekday": 6
    }
  ]
}
```

**Never** replace the legacy `day_of_week` integer with ISO in this preview.
The shadow adds only `iso_weekday` and must preserve all original columns,
row identities and timezone strings byte-for-byte after JSON normalization.
The proposed ISO mapping is Monday=1 through Sunday=7; in particular
Saturday legacy 1 maps to ISO 6 and Friday legacy 7 maps to ISO 5.

### Operator manifest, schema version 1

Compute SHA-256 from the **exact bytes** of the two JSON files using a trusted
local checksum tool, then fill in the 64 lowercase hexadecimal digits. Input
paths themselves are not embedded in the report.

```json
{
  "schema_version": 1,
  "source_kind": "operator_authorized_sanitized_offline_copy",
  "authorization_reference": "OWNER-APPROVAL-REFERENCE",
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "shadow_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "expected_rows": 7,
  "expected_salons": 1,
  "sample_start": "2024-01-01",
  "sample_days": 1461,
  "timezone_provenance": "operator_verified",
  "contains_customer_pii": false,
  "operation": "shadow_iso_weekday_preview_only"
}
```

Manifest values are **operator-provided claims**; the CLI can verify file
digests and syntax, not the truth of the authorization reference, whether
the export was actually sanitized, or the truth of timezone provenance.
If not independently verified, use `unverified`, which blocks parity
status. The maximum sample horizon is 1,461 dates, at least 7 dates, with
at most 100,000 date×salon probes. For a clean preview, sample at least
366 days (year boundary); choose dates that include DST transitions for
businesses in relevant zones. Timezone *instant* parity still requires
Phase 5 evidence and cannot be inferred from weekday labels.

## Deterministic stop policy

Reject immediately without a raw-data echo for invalid structure, unknown
keys or PII-bearing extra fields, malformed/oversized JSON, duplicate JSON
keys, missing operator markers, bad manifest fields or altered SHA-256.
The command exits nonzero with a generic failure message. This is not a
diagnostic channel for customer details.

Emit aggregate blockers and exit nonzero for any of:

- incorrect declared total or salon count, missing/extra/duplicate row IDs,
  duplicate `(salon_id, day_of_week)` or `(salon_id, iso_weekday)` pairs,
  or missing days from the seven-day schedule;
- invalid legacy/ISO values (including booleans), source/ISO mapping drift,
  changed source fields or differing date-based opening/closed windows;
- non-IANA/empty timezone, invalid HH:MM, reversed/overnight shifts,
  closed rows carrying ambiguous non-null time values;
- missing verified timezone provenance or a sample shorter than one year.

No automatic deduplication, timezone fallback, date interpretation,
record rewrite or conversion is allowed. The legacy column remains
the business source of truth.

## Operator-controlled runbook (proposed; no automated writes)

**Before:** independently approve a sanitized PostGIS export and record its
isolation, access owner, retention limit, stable row IDs and snapshot hashes.
Run this tool from offline files; reconcile aggregate counts with a separate
read-only snapshot SQL audit. Have data and release owners sign off on
unresolved legacy anomalies, missing days and potential timezone ambiguity.

**Expand + dry run:** a future separately reviewed PR MAY add a nullable
ISO shadow column, but not switch existing lookup semantics. Rehearse
bounded batches and compare old and shadow projections, including concurrent
write behavior, representative DST/year boundaries, fixtures and both API/
JavaScript client contracts. The present command cannot create this field.

**Stop:** if any checksum, record coverage, mapping, opening-time, closed-day,
permission, consumer or timezone mismatch occurs, block cutover, freeze
the planned rollout, preserve evidence and escalate to the responsible owner.
Zero detected differences means only a clean *offline preview*.

**Rollback (future, not executable here):** before any contract removal,
disable shadow reads/writes behind an operator-controlled feature switch,
retain original legacy values and restore the approved backup only under
the signed runbook. After a real cutover, prove the ISO→legacy reverse
mapping against the immutable before snapshot using IDs and canonical
business dates before even considering rollback. Never apply an in-place
mapping twice. Record rollback RTO/RPO, checksum proof, concurrency plan
and explicit approval outside the application.

## Remaining blockers

The authorized real snapshot is not supplied. Owner authorization,
timezone provenance, Phase 5 representative historical booking audit,
live/staging browser and device checks, Phase 3 manual keyboard,
400%-zoom and screen-reader signoff, and complete dynamic consumer review
are not complete. This PR does **not** authorize migration or deployment.
