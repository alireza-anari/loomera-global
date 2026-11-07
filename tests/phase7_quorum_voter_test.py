"""Phase 7.17 three real isolated Redis voter CAS and write gateway fixture tests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

import redis

from loomera.globalization.otp_quorum_voter_rehearsal import (
    PORTS, PREFIX, SyntheticVoter, SyntheticVote,
)
from loomera.globalization.otp_quorum_write_gateway_rehearsal import (
    SyntheticQuorumWriteGateway, SyntheticGateWrite,
    PREFIX as DATA_PREFIX,
)


class Phase717ThreeWitnessTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get("LOOMERA_PHASE717_TEST_REDIS"), "1")
        self.id, self.a, self.b, self.c = (uuid4().hex for _ in range(4))
        self.clients = {
            node: redis.Redis.from_url(
                f"redis://127.0.0.1:{port}/15", socket_timeout=5,
            ) for node, port in PORTS.items()
        }
        self.voters = tuple(
            SyntheticVoter(self.clients[node], fixture_id=self.id, voter=node)
            for node in ("a", "b", "c")
        )
        self.data = redis.Redis.from_url(
            "redis://127.0.0.1:6403/15", socket_timeout=5,
        )
        for c in (*self.clients.values(), self.data):
            self.assertTrue(c.ping())
        self.gate = SyntheticQuorumWriteGateway(
            self.data, fixture_id=self.id, node="original", voters=self.voters,
        )

    def tearDown(self):
        try:
            for v in self.voters:
                v.cleanup_owned_fixture()
            self.gate.cleanup_owned_fixture()
        finally:
            for c in (*self.clients.values(), self.data):
                c.close()

    def seed(self):
        for voter in self.voters:
            self.assertEqual(voter.seed_for_test(token=self.a),
                             SyntheticVote("seeded", 1, self.a))

    def vote(self, index: int, token=None):
        return self.voters[index].vote_promote(
            expected_old_token=self.a, new_token=token or self.b,
        )

    def test_seed_all_three_distinct_nodes(self):
        self.seed()
        for v in self.voters:
            self.assertEqual(v.inspect(), SyntheticVote("ready", 1, self.a))

    def test_uninitialized_inspection_never_autoseeds(self):
        for v in self.voters:
            self.assertEqual(v.inspect().status, "missing")
            self.assertEqual(self.clients[v.voter].exists(v.key), 0)

    def test_explicit_seed_grant_required(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE717_ALLOW_SEED": "0"}):
            with self.assertRaises(RuntimeError):
                self.voters[0].seed_for_test(token=self.a)

    def test_double_seed_does_not_change_ttl_or_token(self):
        self.seed()
        before = [self.clients[v.voter].pttl(v.key) for v in self.voters]
        self.assertEqual(self.voters[0].seed_for_test(token=self.b).status,
                         "already_seeded")
        self.assertEqual(self.voters[0].inspect().token, self.a)
        for v, ms in zip(self.voters, before):
            self.assertLessEqual(self.clients[v.voter].pttl(v.key), ms)

    def test_one_vote_alone_is_not_quorum(self):
        self.seed()
        self.assertEqual(self.vote(0), SyntheticVote("vote_recorded", 2, self.b))
        self.assertEqual(
            self.gate.quorum_observation(candidate_token=self.b).status,
            "majority_unavailable",
        )

    def test_two_matching_votes_observed_not_authorizing(self):
        self.seed()
        self.vote(0)
        self.vote(1)
        result = self.gate.quorum_observation(candidate_token=self.b)
        self.assertEqual(result.status, "synthetic_majority_observed_only")
        self.assertEqual(result.matching_votes, 2)
        self.assertFalse(result.can_write_production)

    def test_third_matching_vote_counts_three(self):
        self.seed()
        for i in range(3):
            self.vote(i)
        self.assertEqual(
            self.gate.quorum_observation(candidate_token=self.b).matching_votes,
            3,
        )

    def test_new_token_refuses_same_old_token(self):
        self.seed()
        self.assertEqual(
            self.voters[0].vote_promote(
                expected_old_token=self.a, new_token=self.a,
            ).status, "stale_epoch",
        )

    def test_wrong_old_token_refuses_vote(self):
        self.seed()
        self.assertEqual(
            self.voters[0].vote_promote(
                expected_old_token=self.c, new_token=self.b,
            ).status, "stale_epoch",
        )

    def test_retry_same_vote_is_idempotent_but_not_a_new_grant(self):
        self.seed()
        self.vote(0)
        self.assertEqual(self.vote(0), SyntheticVote("already_voted", 2, self.b))
        self.assertEqual(self.voters[0].inspect().token, self.b)

    def test_conflicting_vote_cannot_replace_first(self):
        self.seed()
        self.vote(0)
        self.assertEqual(
            self.vote(0, token=self.c),
            SyntheticVote("conflicting_vote", 2, self.b),
        )
        self.assertEqual(self.voters[0].inspect().token, self.b)

    def test_conflicting_third_vote_fails_closed(self):
        self.seed()
        self.vote(0)
        self.vote(1)
        self.vote(2, token=self.c)
        self.assertEqual(
            self.gate.quorum_observation(candidate_token=self.b).status,
            "conflicting_candidate_observed",
        )

    def test_competing_candidates_one_voter_cas_one_winner(self):
        self.seed()
        barrier = Barrier(3, timeout=15)

        def contender(candidate):
            client = redis.Redis.from_url(
                "redis://127.0.0.1:6405/15", socket_timeout=5,
            )
            try:
                v = SyntheticVoter(client, fixture_id=self.id, voter="a")
                barrier.wait(timeout=15)
                return v.vote_promote(
                    expected_old_token=self.a, new_token=candidate,
                )
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(contender, self.b)
            b = executor.submit(contender, self.c)
            barrier.wait(timeout=15)
            result = [a.result(timeout=15), b.result(timeout=15)]
        self.assertEqual(
            sorted(r.status for r in result),
            ["conflicting_vote", "vote_recorded"],
        )
        winner = next(x for x in result if x.status == "vote_recorded")
        self.assertEqual(self.voters[0].inspect().token, winner.token)

    def test_fresh_clients_observe_committed_vote(self):
        self.seed()
        self.vote(1)
        client = redis.Redis.from_url("redis://127.0.0.1:6406/15")
        try:
            v = SyntheticVoter(client, fixture_id=self.id, voter="b")
            self.assertEqual(v.inspect(), SyntheticVote("voted", 2, self.b))
        finally:
            client.close()

    def test_halt_after_vote_terminal_and_no_reopen(self):
        self.seed()
        self.vote(0)
        self.assertEqual(
            self.voters[0].terminal_halt(expected_token=self.b),
            SyntheticVote("halted", 3, self.b),
        )
        self.assertEqual(self.voters[0].inspect().status, "halted")
        self.assertEqual(
            self.voters[0].terminal_halt(expected_token=self.b).status,
            "already_halted",
        )
        self.assertEqual(self.vote(0).status, "already_halted")

    def test_halt_needs_grant(self):
        self.seed()
        self.vote(0)
        with patch.dict(os.environ, {"LOOMERA_PHASE717_ALLOW_TEST_HALT": "0"}):
            with self.assertRaises(RuntimeError):
                self.voters[0].terminal_halt(expected_token=self.b)

    def test_halt_with_old_token_denied(self):
        self.seed()
        self.vote(0)
        self.assertEqual(
            self.voters[0].terminal_halt(expected_token=self.a).status,
            "stale_epoch",
        )

    def test_halted_voter_forces_stop_even_with_two_other_votes(self):
        self.seed()
        for i in range(3):
            self.vote(i)
        self.voters[0].terminal_halt(expected_token=self.b)
        self.assertEqual(
            self.gate.quorum_observation(candidate_token=self.b).status,
            "terminal_halt_observed",
        )

    def test_missing_one_voter_with_two_votes_is_bounded_majority(self):
        self.seed()
        self.vote(0)
        self.vote(1)
        self.clients["c"].delete(self.voters[2].key)
        result = self.gate.quorum_observation(candidate_token=self.b)
        self.assertEqual(result.status, "synthetic_majority_observed_only")
        self.assertFalse(result.consensus_safety_proven)

    def test_missing_two_voters_denies(self):
        self.seed()
        self.vote(0)
        for i in (1, 2):
            self.clients[self.voters[i].voter].delete(self.voters[i].key)
        self.assertEqual(
            self.gate.quorum_observation(candidate_token=self.b).status,
            "majority_unavailable",
        )

    def test_corrupt_voter_claim_denies(self):
        self.seed()
        self.vote(0)
        self.vote(1)
        self.clients["b"].hset(self.voters[1].key, "epoch", "02")
        self.assertEqual(self.voters[1].inspect().status, "corrupt")
        self.assertEqual(self.gate.quorum_observation(candidate_token=self.b).status,
                         "majority_unavailable")

    def test_expired_ttl_or_wrong_type_denied(self):
        self.seed()
        self.clients["a"].persist(self.voters[0].key)
        self.assertEqual(self.voters[0].inspect().status, "corrupt")
        self.clients["a"].delete(self.voters[0].key)
        self.clients["a"].setex(self.voters[0].key, 60, "wrong")
        self.assertEqual(self.voters[0].inspect().status, "corrupt")

    def test_gated_old_master_never_writes_even_with_two_votes(self):
        self.seed()
        self.vote(0)
        self.vote(1)
        self.assertEqual(
            self.gate.write_promoted_fixture(
                candidate_token=self.b, expected_sequence=0,
            ),
            SyntheticGateWrite("old_writer_denied_by_gateway"),
        )

    def test_seed_data_never_grants_otp_or_session(self):
        self.seed()
        self.assertEqual(self.gate.seed_test_data(initial_token=self.a),
                         SyntheticGateWrite("initialized", 1, 0))
        for v in self.voters:
            self.assertFalse(v.inspect().authenticated)
        self.assertFalse(self.gate.seed_test_data(initial_token=self.a).authenticated)

    def test_initial_data_keys_only_two_exact_fixture_keys_deleted(self):
        self.seed()
        self.gate.seed_test_data(initial_token=self.a)
        other = DATA_PREFIX + uuid4().hex + ":fence"
        self.data.setex(other, 60, "unrelated synthetic fixture")
        try:
            self.gate.cleanup_owned_fixture()
            self.assertEqual(self.data.exists(*self.gate.keys), 0)
            self.assertEqual(self.data.get(other), b"unrelated synthetic fixture")
        finally:
            self.data.delete(other)

    def test_malformed_voter_reply_is_unavailable(self):
        class WrongReply:
            def __init__(self, original):
                self.connection_pool = original.connection_pool

            def eval(self, *args):
                return ["vote_recorded", "2", "none"]

        fake = SyntheticVoter(
            WrongReply(self.clients["a"]), fixture_id=self.id, voter="a",
        )
        self.assertEqual(fake.inspect().status, "backend_unavailable")

    def test_backend_timeout_after_vote_not_a_grant(self):
        self.seed()

        class CommitThenTimeout:
            def __init__(self, original):
                self.actual = original
                self.connection_pool = original.connection_pool

            def eval(self, *args):
                self.actual.eval(*args)
                raise redis.exceptions.TimeoutError("synthetic postcommit fault")

        fake = SyntheticVoter(
            CommitThenTimeout(self.clients["a"]),
            fixture_id=self.id, voter="a",
        )
        result = fake.vote_promote(expected_old_token=self.a, new_token=self.b)
        self.assertEqual(result.status, "backend_unavailable")
        self.assertFalse(result.can_grant_write)
        self.assertEqual(self.voters[0].inspect(), SyntheticVote("voted", 2, self.b))

    def test_wrong_endpoint_and_credentials_rejected(self):
        for url, voter_id in (
            ("redis://127.0.0.1:6379/15", "a"),
            ("redis://127.0.0.1:6405/14", "a"),
            ("redis://localhost:6405/15", "a"),
            ("redis://127.0.0.1:6406/15", "a"),
            ("redis://u:p@127.0.0.1:6405/15", "a"),
        ):
            cli = redis.Redis.from_url(url)
            try:
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    SyntheticVoter(cli, fixture_id=self.id, voter=voter_id)
            finally:
                cli.close()

    def test_id_and_token_validation(self):
        for value in ("otp", "A"*32, True, None, "b"*31):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.voters[0].vote_promote(
                    expected_old_token=value, new_token=self.b,
                )
        with self.assertRaises(ValueError):
            self.voters[0].vote_promote(
                expected_old_token=self.a, new_token=self.b, expected_epoch=True,
            )

    def test_test_grant_checked_each_call(self):
        with patch.dict(os.environ, {"LOOMERA_PHASE717_TEST_REDIS": "0"}):
            with self.assertRaises(RuntimeError):
                self.voters[0].inspect()

    def test_exact_data_node_port_guard(self):
        wrong = redis.Redis.from_url("redis://127.0.0.1:6404/15")
        try:
            with self.assertRaises(RuntimeError):
                SyntheticQuorumWriteGateway(
                    wrong, fixture_id=self.id, node="original", voters=self.voters,
                )
        finally:
            wrong.close()


if __name__ == "__main__":
    unittest.main()
