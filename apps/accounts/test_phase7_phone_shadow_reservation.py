"""Phase 7.3: deterministic + threaded, synthetic-only shadow claim rehearsal."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import inspect
import json
from pathlib import Path
from threading import Barrier

from django.test import SimpleTestCase

from loomera.globalization.phone_identity import (
    PhoneIdentityInputError,
    to_candidate_e164,
)
from loomera.globalization.phone_identity_transition import (
    compare_phone_identity_shadow,
)
from loomera.globalization.phone_shadow_reservation import (
    OfflinePhoneShadowReservation,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "docs/globalization/PHASE7_3_STORAGE_CONTRACT.json"


def source():
    return [
        {"account_id": 101, "mobile_number": "09123456789", "is_active": True},
        {"account_id": 102, "mobile_number": "09123456780", "is_active": False},
        {"account_id": 103, "mobile_number": "09123456781", "is_active": True},
    ]


def proposal(row, *, version=0):
    return {
        "account_id": row["account_id"],
        "expected_version": version,
        "mobile_number": row["mobile_number"],
        "is_active": row["is_active"],
        "canonical_mobile_number": to_candidate_e164(row["mobile_number"]),
    }


class Phase73ShadowStorageContractTests(SimpleTestCase):
    def test_null_by_default_and_no_live_database_authority(self):
        ledger = OfflinePhoneShadowReservation(source())
        result = ledger.audit()
        self.assertEqual(result["source_accounts"], 3)
        self.assertEqual(result["active_accounts"], 2)
        self.assertEqual(result["inactive_accounts"], 1)
        self.assertEqual(result["shadow_claimed_accounts"], 0)
        self.assertEqual(result["shadow_unclaimed_accounts"], 3)
        self.assertTrue(result["shadow_index_consistent"])
        for flag in (
            "live_database_uniqueness_verified",
            "multi_process_race_safety_verified",
            "migration_approved",
            "authentication_cutover_authorized",
        ):
            self.assertFalse(result[flag])
        self.assertEqual(result["database_reads"], 0)
        self.assertEqual(result["database_writes"], 0)

    def test_successful_claim_preserves_existing_legacy_number_and_state(self):
        rows = source()
        original = deepcopy(rows)
        ledger = OfflinePhoneShadowReservation(rows)
        result = ledger.claim_one(**proposal(rows[0]))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["reason"], "none")
        self.assertEqual(result["applied"], 1)
        self.assertEqual(rows, original)
        report = ledger.audit()
        self.assertTrue(report["shadow_index_consistent"])
        self.assertEqual(report["shadow_claimed_accounts"], 1)
        self.assertEqual(report["active_accounts"], 2)
        self.assertEqual(report["inactive_accounts"], 1)

    def test_full_batch_claim_preserves_phase72_identity_mapping(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        proposed = [proposal(row) for row in reversed(rows)]
        status = ledger.claim_batch(proposed)
        self.assertEqual(status["status"], "applied")
        self.assertEqual(status["applied"], 3)
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 3)
        self.assertEqual(ledger.audit()["shadow_claimed_inactive_accounts"], 1)
        shadow = [
            {**row, "canonical_mobile_number": to_candidate_e164(row["mobile_number"])}
            for row in rows
        ]
        comparison = compare_phone_identity_shadow(
            rows, shadow, expected_accounts=3,
            expected_active_accounts=2, expected_inactive_accounts=1,
        )
        self.assertTrue(comparison["shadow_identity_structurally_clean"])
        self.assertFalse(comparison["production_identity_cutover_authorized"])

    def test_batch_is_all_or_nothing_when_last_version_is_stale(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        first = proposal(rows[0])
        second = proposal(rows[1], version=1)
        result = ledger.claim_batch([first, second])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "stale_row_version")
        self.assertEqual(result["applied"], 0)
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 0)
        self.assertEqual(
            ledger.claim_batch([first, proposal(rows[1])])["applied"], 2
        )

    def test_duplicate_account_in_single_batch_is_rejected_atomically(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        same = proposal(rows[0])
        result = ledger.claim_batch([same, same])
        self.assertEqual(result["reason"], "duplicate_batch_account")
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 0)

    def test_versioned_replay_never_succeeds_after_commit(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        first = proposal(rows[0])
        self.assertEqual(ledger.claim_batch([first])["status"], "applied")
        self.assertEqual(
            ledger.claim_batch([first])["reason"], "stale_row_version"
        )
        self.assertEqual(
            ledger.claim_batch([proposal(rows[0], version=1)])["reason"],
            "already_claimed",
        )
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 1)

    def test_rollback_one_is_versioned_and_leaves_legacy_state_intact(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        self.assertEqual(ledger.claim_one(**proposal(rows[1]))["status"], "applied")
        kwargs = {
            "account_id": 102, "mobile_number": "09123456780",
            "is_active": False, "expected_version": 1,
        }
        self.assertEqual(ledger.rollback_one(**kwargs)["status"], "applied")
        audit = ledger.audit()
        self.assertEqual(audit["shadow_claimed_accounts"], 0)
        self.assertEqual(audit["active_accounts"], 2)
        self.assertEqual(audit["inactive_accounts"], 1)
        self.assertEqual(ledger.rollback_one(**kwargs)["reason"], "stale_row_version")
        self.assertEqual(
            ledger.claim_one(**proposal(rows[1], version=1))["reason"],
            "stale_row_version",
        )
        self.assertEqual(
            ledger.claim_one(**proposal(rows[1], version=2))["status"],
            "applied",
        )
        self.assertEqual(ledger.audit()["shadow_claimed_inactive_accounts"], 1)

    def test_rollback_without_shadow_is_denied(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        self.assertEqual(
            ledger.rollback_one(
                account_id=101, mobile_number=rows[0]["mobile_number"],
                is_active=True, expected_version=0,
            )["reason"], "shadow_not_present"
        )

    def test_shadow_candidate_cannot_capture_another_users_number(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        wrong = proposal(rows[1])
        wrong["canonical_mobile_number"] = proposal(rows[0])["canonical_mobile_number"]
        result = ledger.claim_batch([wrong])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "canonical_source_mismatch")
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 0)

    def test_inactive_identity_is_not_a_free_canonical_identifier(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        self.assertEqual(
            ledger.claim_one(**proposal(rows[1]))["status"], "applied"
        )
        bad = proposal(rows[0])
        bad["canonical_mobile_number"] = proposal(rows[1])["canonical_mobile_number"]
        self.assertEqual(
            ledger.claim_one(**bad)["reason"], "canonical_source_mismatch"
        )
        self.assertEqual(ledger.audit()["shadow_claimed_inactive_accounts"], 1)

    def test_rejects_inactive_to_active_and_legacy_login_drift(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        wrong_active = proposal(rows[1])
        wrong_active["is_active"] = True
        self.assertEqual(
            ledger.claim_batch([wrong_active])["reason"],
            "source_identity_or_state_drift",
        )
        wrong_number = proposal(rows[0])
        wrong_number["mobile_number"] = "09123456780"
        self.assertEqual(
            ledger.claim_batch([wrong_number])["reason"],
            "source_identity_or_state_drift",
        )
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 0)

    def test_stale_rollback_and_wrong_user_cannot_release_a_claim(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        self.assertEqual(ledger.claim_one(**proposal(rows[0]))["status"], "applied")
        self.assertEqual(
            ledger.rollback_one(
                account_id=101, expected_version=0,
                mobile_number="09123456789", is_active=True,
            )["reason"], "stale_row_version",
        )
        self.assertEqual(
            ledger.rollback_one(
                account_id=101, expected_version=1,
                mobile_number="09123456780", is_active=True,
            )["reason"], "source_identity_or_state_drift",
        )
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 1)

    def test_invalid_candidate_boolean_version_foreign_number_and_extra_pii(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        invalids = [
            {"expected_version": True},
            {"expected_version": -1},
            {"canonical_mobile_number": "+4915123456789"},
            {"canonical_mobile_number": "989123456789"},
            {"canonical_mobile_number": "not_a_phone"},
            {"account_id": True},
            {"is_active": 1},
            {"email": "private@example.com"},
        ]
        for update in invalids:
            bad = {**proposal(rows[0]), **update}
            with self.subTest(field=next(iter(update))):
                result = ledger.claim_batch([bad])
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["applied"], 0)
                self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 0)

    def test_invalid_source_and_duplicate_legacy_accounts_fail_closed(self):
        valid = source()
        cases = [
            [valid[0], dict(valid[0], account_id=202)],
            [valid[0], dict(valid[0])],
            [dict(valid[0], account_id=True)],
            [dict(valid[0], mobile_number="+989123456789")],
            [dict(valid[0], mobile_number="98000000001")],
            [dict(valid[0], mobile_number="۰۹۱۲۳۴۵۶۷۸۹")],
            [dict(valid[0], is_active=1)],
            [dict(valid[0], email="private@example.com")],
        ]
        for items in cases:
            with self.subTest(case=len(items), first=items[0].keys()):
                with self.assertRaises(PhoneIdentityInputError):
                    OfflinePhoneShadowReservation(items)
        for invalid in (None, {}, [], [None], "untrusted"):
            with self.subTest(invalid_type=type(invalid)):
                with self.assertRaises(PhoneIdentityInputError):
                    OfflinePhoneShadowReservation(invalid)

    def test_invalid_batch_length_rejected_before_mutation(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        for bad in ([], {}, None, [proposal(rows[0])] * 4):
            with self.subTest(bad_type=type(bad)):
                with self.assertRaises(PhoneIdentityInputError):
                    ledger.claim_batch(bad)
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 0)

    def test_two_threads_same_version_only_one_claim_wins(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        gate = Barrier(3, timeout=15)

        def contender():
            gate.wait()
            return ledger.claim_one(**proposal(rows[0]))

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(contender)
            b = pool.submit(contender)
            gate.wait()
            results = (a.result(timeout=15), b.result(timeout=15))
        self.assertEqual(sorted(x["status"] for x in results),
                         ["applied", "blocked"])
        self.assertEqual(
            [x["reason"] for x in results if x["status"] == "blocked"],
            ["stale_row_version"],
        )
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 1)
        self.assertTrue(ledger.audit()["shadow_index_consistent"])

    def test_two_concurrent_batches_with_overlap_do_not_partially_commit(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        gate = Barrier(3, timeout=15)

        def attempt(indices):
            gate.wait()
            return ledger.claim_batch([proposal(rows[i]) for i in indices])

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(attempt, (0, 1))
            b = pool.submit(attempt, (1, 2))
            gate.wait()
            outcomes = (a.result(timeout=15), b.result(timeout=15))
        self.assertEqual(sorted(x["status"] for x in outcomes),
                         ["applied", "blocked"])
        self.assertEqual(sum(x["applied"] for x in outcomes), 2)
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 2)
        self.assertEqual(
            [x["reason"] for x in outcomes if x["status"] == "blocked"],
            ["stale_row_version"],
        )
        self.assertTrue(ledger.audit()["shadow_index_consistent"])

    def test_concurrent_disjoint_claims_are_both_allowed(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        gate = Barrier(3, timeout=15)

        def attempt(index):
            gate.wait()
            return ledger.claim_one(**proposal(rows[index]))

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(attempt, 0)
            b = pool.submit(attempt, 1)
            gate.wait()
            outcomes = (a.result(timeout=15), b.result(timeout=15))
        self.assertEqual([x["status"] for x in outcomes], ["applied", "applied"])
        self.assertEqual(ledger.audit()["shadow_claimed_accounts"], 2)
        self.assertTrue(ledger.audit()["shadow_index_consistent"])

    def test_outputs_never_include_personal_phone_ids_or_hashes(self):
        rows = source()
        ledger = OfflinePhoneShadowReservation(rows)
        results = [
            ledger.audit(),
            ledger.claim_one(**proposal(rows[0])),
            ledger.claim_one(**proposal(rows[0])),
            ledger.rollback_one(
                account_id=101, expected_version=1,
                mobile_number="09123456789", is_active=True,
            ),
            ledger.audit(),
        ]
        encoded = json.dumps(results, ensure_ascii=False)
        for secret in (
            "09123456789", "+989123456789", "09123456780",
            '"account_id":', '"mobile_number":', '"canonical_mobile_number":',
        ):
            self.assertNotIn(secret, encoded)

    def test_pure_module_has_no_django_orm_cache_sms_or_sql(self):
        from loomera.globalization import phone_shadow_reservation
        text = inspect.getsource(phone_shadow_reservation)
        for forbidden in (
            "django.db", ".objects.", "cursor.execute(",
            "send_otp_sms(", "login(request", "cache.get(",
            "cache.set(", "transaction.atomic(", "RunSQL(", "RunPython(",
        ):
            self.assertNotIn(forbidden, text)

    def test_storage_contract_declares_future_only_index_and_cas(self):
        manifest = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["phase"], "7.3")
        self.assertEqual(manifest["storage_proposal"]["canonical_field_max_length"], 16)
        self.assertTrue(manifest["storage_proposal"]["nullable_until_cutover"])
        self.assertTrue(manifest["storage_proposal"]["unique_across_inactive"])
        self.assertTrue(manifest["write_protocol"]["expected_row_version_required"])
        self.assertTrue(manifest["write_protocol"]["transactional_all_or_nothing"])
        self.assertTrue(manifest["write_protocol"]["database_unique_index_required"])
        self.assertFalse(manifest["evidence"]["database_unique_index_applied"])
        self.assertFalse(manifest["evidence"]["multi_process_race_verified"])
        self.assertFalse(manifest["evidence"]["schema_migration_approved"])
        self.assertFalse(manifest["evidence"]["production_cutover_authorized"])
        for entry in manifest["legacy_source_anchors"]:
            self.assertIn(
                entry["anchor"],
                (ROOT / entry["path"]).read_text(encoding="utf-8"),
            )
