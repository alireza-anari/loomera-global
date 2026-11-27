# Phase 7 exit package A — installed canonical phone storage

Baseline main 9272e8ea29c13390bc34de12b771a6fc76c15602; Issue #165.
This is actual installed account schema work, not a synthetic-only shadow protocol. No production migration or deployment authorized.

## Design and compatibility

Migration accounts/0005_canonical_phone_storage expands the existing unique USERNAME_FIELD mobile_number to 16 characters and creates nullable, unique, database-generated canonical_mobile_number. Retain MaxLengthValidator(11) to preserve legacy model validation until package B. A generated column avoids stale separately written claims for model saves, QuerySet.update, bulk writes and account deletion. Keep primary keys, foreign keys, raw legacy usernames, password hashes and active status unchanged. No auth/OTP/provider paths changed.

Projection accepts exactly ASCII 09 + 9 digits as +989 + 9 digits, or canonical +E.164 syntax of 8–15 digits (Iran only mobile +989...). No raw trimming, Unicode alias guessing or generic country inference in SQL. Invalid/raw historical placeholders produce NULL, and NULL is never an eligible canonical login. New foreign values can be represented at the storage layer in controlled tests; they are not supported signup/login/SMS inputs. Syntax is not allocation or ownership validation. Package B must deliberately reconcile country-aware normalization and supported numbering plans, form/admin/client validation and all identity lookup/write paths before enabling international auth. Direct programmatic writes still have the historic ability to bypass model validation, so arbitrary noncanonical values are not claimed; do not treat nullable projection as a universal admission policy.

Canonical uniqueness spans active/inactive users; two distinct usernames for the same canonical Iranian number conflict at the database. Account deletion rekeys the legacy username to a reserved non-09 tombstone and the canonical field becomes NULL automatically. Existing account IDs/relations remain intact. Loaded ORM objects may need refresh_from_db after update before consuming their generated field.

## Preflight and migration operations

PostgreSQL: one atomic migration, ACCESS EXCLUSIVE locks on user and deletion request tables before preflight (requires a maintenance window; table rewrite and unique index build can be expensive). SQLite is a development/test compatibility path only; other DB vendors refuse. Only exact legacy ASCII Iranian usernames or verified anonymized tombstones are eligible for the initial expansion. Tombstones require the reserved 94–98 prefix, inactive status, unusable password and matching completed/anonymized deletion record with timestamp. Unknown or aliased values (including Unicode digits) block, emitting only unresolved row count. No silent repair, automatic account merge or truncation. Accepted legacy usernames are already unique and mapping is injective. Existing offline collision audit remains a separate authorized evidence step. Production snapshot, runtime locks and real migration duration not verified.

Before any real migration: owner-approved backup and restore rehearsal, aggregate inventory/collision reconciliation, verify PostgreSQL version and privileges, maintenance/drain all writers, dry-run against a representative approved isolated copy, verify row counts/identity hashes and operational recovery. Do not run automatically against production from this PR. Review table rewrite/lock duration, rollback and service compatibility. Reverse is guarded by the same preflight before removal/shrink: any new nonlegacy username blocks downgrade. After international identities exist, use forward repair or an approved reversible migration strategy; never truncate or auto-rekey.

## Evidence and boundaries

New TransactionTestCase suite runs in existing disposable PostgreSQL CI: real installed migration graph forward/reverse, active/inactive/deleted fixtures, no rewrite of username/password/id or deletion relation, generated field projection, database uniqueness and concurrency, bulk writes/rekeys, redacted invalid preflight and refusal of unsafe rollback. Existing auth/security and historical rehearsal tests remain in CI; source anchors reflect intentional width expansion, not a relaxation of legacy login semantics.

Package A does not prove production readiness, international authentication or SMS delivery. No numbering-plan library selected yet; package B must choose and verify policy/library before admission. No actual data accessed, backup inspected or deployment performed. Phase 14 owns international SMS provider expansion; Phase 3 manual acceptance and other release gates remain. Phase 7 development exit requires package B/C; release remains BLOCKED.
