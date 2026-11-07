"""Phase 7.17 offline quorum intersection, invalid attestation and release guards."""
from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

from django.test import SimpleTestCase

from loomera.globalization.otp_quorum_evidence_policy import (
    SyntheticVoterClaim, SyntheticQuorumReview, review_synthetic_quorum,
)
from loomera.globalization import otp_quorum_voter_rehearsal as voter
from loomera.globalization import otp_quorum_write_gateway_rehearsal as gateway

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/globalization/PHASE7_17_EXIT_MATRIX.json"
TOKEN_A, TOKEN_B, TOKEN_C = "a"*32, "b"*32, "c"*32


def claims(*states):
    return tuple(
        SyntheticVoterClaim(chr(97 + i), state, epoch, token)
        for i, (state, epoch, token) in enumerate(states)
    )


YES = claims(("voted", 2, TOKEN_B), ("voted", 2, TOKEN_B),
             ("ready", 1, TOKEN_A))


class Phase717QuorumEvidenceTests(SimpleTestCase):
    def assess(self, evidence=YES, token=TOKEN_B, owner="promoted", epoch=2):
        return review_synthetic_quorum(
            evidence, target_epoch=epoch,
            candidate_token=token, candidate_owner=owner,
        )

    def test_two_of_three_is_synthetic_observation_not_login(self):
        result = self.assess()
        self.assertEqual(
            result, SyntheticQuorumReview(
                "synthetic_majority_observed_only", matching_votes=2,
            ),
        )
        self.assertTrue(result.operator_review_required)
        for name in (
            "authenticated", "otp_consume_allowed", "session_created",
            "can_write_production", "can_issue_otp", "can_retry_session",
            "raw_old_primary_fenced", "consensus_safety_proven",
            "legacy_fallback_authorized",
        ):
            self.assertFalse(getattr(result, name), name)

    def test_three_votes_still_only_synthetic(self):
        result = self.assess(claims(
            ("voted", 2, TOKEN_B), ("voted", 2, TOKEN_B),
            ("voted", 2, TOKEN_B),
        ))
        self.assertEqual(result.matching_votes, 3)
        self.assertFalse(result.can_write_production)

    def test_one_vote_is_not_majority(self):
        result = self.assess(claims(
            ("voted", 2, TOKEN_B), ("ready", 1, TOKEN_A),
            ("ready", 1, TOKEN_A),
        ))
        self.assertEqual(result.status, "majority_unavailable")
        self.assertEqual(result.matching_votes, 1)

    def test_zero_votes_denied(self):
        result = self.assess(claims(
            ("ready", 1, TOKEN_A), ("ready", 1, TOKEN_A),
            ("ready", 1, TOKEN_A),
        ))
        self.assertEqual(result.status, "majority_unavailable")

    def test_two_unavailable_nodes_deny(self):
        result = self.assess(claims(
            ("voted", 2, TOKEN_B), ("unavailable", 0, "none"),
            ("unavailable", 0, "none"),
        ))
        self.assertEqual(result.status, "majority_unavailable")

    def test_one_unavailable_with_two_matching_votes_is_observation_only(self):
        result = self.assess(claims(
            ("voted", 2, TOKEN_B), ("voted", 2, TOKEN_B),
            ("unavailable", 0, "none"),
        ))
        self.assertEqual(result.status, "synthetic_majority_observed_only")
        self.assertFalse(result.raw_old_primary_fenced)

    def test_any_halted_voter_requires_manual_stop(self):
        for i in range(3):
            samples = list(YES)
            samples[i] = replace(samples[i], state="halted", epoch=3)
            with self.subTest(i=i):
                self.assertEqual(self.assess(tuple(samples)).status,
                                 "terminal_halt_observed")

    def test_any_conflicting_vote_is_rejected(self):
        for i in range(3):
            samples = list(YES)
            samples[i] = replace(samples[i], state="voted", epoch=2, token=TOKEN_C)
            with self.subTest(i=i):
                self.assertEqual(self.assess(tuple(samples)).status,
                                 "conflicting_candidate_observed")

    def test_old_token_is_not_new_quorum(self):
        result = self.assess(token=TOKEN_A)
        self.assertEqual(result.status, "conflicting_candidate_observed")

    def test_valid_candidate_owner_only(self):
        for owner in ("original", "unknown", "PROMOTED", "", True):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                self.assess(owner=owner)

    def test_only_epoch_two_supported(self):
        for epoch in (0, 1, 3, True, "2", None):
            with self.subTest(epoch=epoch), self.assertRaises(ValueError):
                self.assess(epoch=epoch)

    def test_wrong_candidate_token_rejected(self):
        for token in (None, 1, True, "b"*31, "B"*32, "x"*32):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.assess(token=token)

    def test_three_exact_claims_required(self):
        for item in (None, [], YES[:2], YES + YES[:1]):
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.assess(item)

    def test_untyped_voter_claims_rejected(self):
        items = list(YES)
        items[1] = {"node": "b", "otp": "000000"}
        with self.assertRaises(TypeError):
            self.assess(tuple(items))

    def test_duplicate_identity_denied(self):
        items = list(YES)
        items[1] = replace(items[1], node="a")
        with self.assertRaises(ValueError):
            self.assess(tuple(items))

    def test_out_of_order_nodes_denied(self):
        with self.assertRaises(ValueError):
            self.assess((YES[1], YES[0], YES[2]))

    def test_unknown_state_denied(self):
        items = list(YES)
        items[0] = replace(items[0], state="leader")
        with self.assertRaises(ValueError):
            self.assess(tuple(items))

    def test_boolean_epoch_denied(self):
        items = list(YES)
        items[0] = replace(items[0], epoch=True)
        with self.assertRaises(ValueError):
            self.assess(tuple(items))

    def test_invalid_epoch_bounds_denied(self):
        for val in (-1, 4, 1_000_000_000):
            items = list(YES)
            items[0] = replace(items[0], epoch=val)
            with self.subTest(val=val), self.assertRaises(ValueError):
                self.assess(tuple(items))

    def test_noncanonical_token_denied(self):
        items = list(YES)
        items[0] = replace(items[0], token="X"*32)
        with self.assertRaises(ValueError):
            self.assess(tuple(items))

    def test_inconsistent_ready_epoch_denied(self):
        items = list(YES)
        items[2] = replace(items[2], epoch=2)
        with self.assertRaises(ValueError):
            self.assess(tuple(items))

    def test_inconsistent_vote_epoch_denied(self):
        items = list(YES)
        items[0] = replace(items[0], epoch=1)
        with self.assertRaises(ValueError):
            self.assess(tuple(items))

    def test_inconsistent_missing_node_denied(self):
        items = list(YES)
        items[2] = replace(items[2], state="missing")
        with self.assertRaises(ValueError):
            self.assess(tuple(items))

    def test_unavailable_witness_claim_never_proves_live_consensus(self):
        result = self.assess(claims(
            ("voted", 2, TOKEN_B), ("voted", 2, TOKEN_B),
            ("corrupt", 0, "none"),
        ))
        self.assertFalse(result.consensus_safety_proven)

    def test_code_has_strict_test_ports_and_no_prod_imports(self):
        code = inspect.getsource(voter) + inspect.getsource(gateway)
        for anchor in ("LOOMERA_PHASE717_TEST_REDIS", "6403", "6404",
                       "6405", "6406", "6407", "LOOMERA_PHASE717_ALLOW_SEED"):
            self.assertIn(anchor, code)
        for forbidden in (
            "FLUSHALL", "FLUSHDB", "request.session",
            "apps.accounts.models", "login(request", ".objects.",
        ):
            self.assertNotIn(forbidden, code)

    def test_live_auth_and_session_never_import_rehearsals(self):
        for path in (
            "apps/api/v1/auth_otp.py", "apps/api/v1/auth_views.py",
            "apps/accounts/views.py", "apps/accounts/models.py",
        ):
            with self.subTest(path=path):
                code = (ROOT/path).read_text(encoding="utf-8")
                self.assertNotIn("otp_quorum_voter_rehearsal", code)
                self.assertNotIn("otp_quorum_write_gateway_rehearsal", code)
                self.assertNotIn("otp_quorum_evidence_policy", code)

    def test_live_api_otp_replay_race_still_unfixed(self):
        code = (ROOT/"apps/api/v1/auth_otp.py").read_text(encoding="utf-8")
        verifier = code[code.index("def verify_api_otp_code("):]
        self.assertIn("record = _cache_get(key)", verifier)
        self.assertIn("secrets.compare_digest", verifier)

    def test_release_is_blocked_and_no_real_session_writes(self):
        m = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(m["phase"], "7.17")
        self.assertEqual(
            m["baseline_main_sha"],
            "db76ca191a03a7a591bb33a57bfbd99b155fdb5f",
        )
        for k in (
            "real_multihost_consensus_verified",
            "raw_redis_old_primary_fenced",
            "atomic_witness_to_redis_write_verified",
            "live_auth_wired", "real_accounts_accessed",
            "real_sessions_created", "legacy_otp_replay_race_fixed",
            "production_cutover_authorized", "deployed",
        ):
            self.assertIs(m[k], False, k)
        self.assertTrue(m["release_gate"].startswith("BLOCKED"))
