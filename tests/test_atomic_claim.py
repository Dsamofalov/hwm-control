from __future__ import annotations

import threading
import unittest

from control.atomic_claim import (
    AtomicClaimPrototype,
    ClaimConflict,
    ClaimRequest,
    ClaimValidationError,
    RecoveryEvidence,
    lease_is_stale,
)
from control.task_issue_state import BLOCKED, CLAIMED, COMPLETED, READY


HEAD_A = "a" * 40
HEAD_B = "b" * 40
REPO = "Dsamofalov/hwm-control"
BRANCH = "agent/infra-0008-atomic-claim-prototype"


def issue(labels=(READY,), *, number=8, milestone_state="open"):
    return {
        "issue_number": number,
        "state": "open",
        "state_reason": None,
        "labels": [{"name": label} for label in labels],
        "milestone": {"state": milestone_state},
    }


def request(
    *,
    branch=BRANCH,
    base_sha=HEAD_A,
    claimed_at="2026-08-14T17:00:00Z",
    lease_expires_at="2026-08-14T18:00:00Z",
    agent_id="agent-a",
):
    return ClaimRequest(
        task_id=8,
        branch=branch,
        base_repo=REPO,
        base_sha=base_sha,
        claimed_at=claimed_at,
        lease_expires_at=lease_expires_at,
        agent_id=agent_id,
    )


class AtomicClaimTests(unittest.TestCase):
    def setUp(self):
        self.store = AtomicClaimPrototype(repository=REPO, protected_head=HEAD_A)
        self.deps = (2, 7)
        self.dep_states = {2: COMPLETED, 7: COMPLETED}
        self.now = "2026-08-14T17:30:00Z"

    def claim(self, **kwargs):
        return self.store.claim(
            issue=kwargs.pop("issue", issue()),
            request=kwargs.pop("request", request()),
            now=kwargs.pop("now", self.now),
            required_dependencies=kwargs.pop("required_dependencies", self.deps),
            dependency_states=kwargs.pop("dependency_states", self.dep_states),
            milestone_state=kwargs.pop("milestone_state", "open"),
            **kwargs,
        )

    def test_successful_single_owner_claim(self):
        outcome = self.claim()
        self.assertEqual("claimed", outcome.status)
        self.assertEqual(BRANCH, outcome.record["branch"])
        self.assertEqual(HEAD_A, outcome.record["base_sha"])
        self.assertEqual(outcome.record, self.store.current_claim(8))

    def test_concurrent_contenders_have_exactly_one_winner(self):
        barrier = threading.Barrier(2)
        outcomes = []
        guard = threading.Lock()

        def contender_with_branch(agent_id, branch):
            barrier.wait()
            try:
                result = self.claim(request=request(agent_id=agent_id, branch=branch))
                value = ("winner", result.status)
            except ClaimConflict as exc:
                value = ("conflict", exc.code)
            with guard:
                outcomes.append(value)

        threads = [
            threading.Thread(
                target=contender_with_branch,
                args=("agent-a", "agent/infra-0008-contender-a"),
            ),
            threading.Thread(
                target=contender_with_branch,
                args=("agent-b", "agent/infra-0008-contender-b"),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, sum(kind == "winner" for kind, _ in outcomes))
        self.assertEqual(1, sum(kind == "conflict" for kind, _ in outcomes))
        self.assertIsNotNone(self.store.current_claim(8))

    def test_loser_gets_clean_conflict_without_partial_second_owner(self):
        self.claim()
        with self.assertRaises(ClaimConflict) as caught:
            self.claim(request=request(agent_id="agent-b"))
        self.assertEqual("ALREADY_CLAIMED", caught.exception.code)
        self.assertEqual("agent-a", self.store.current_claim(8)["agent_id"])

    def test_exact_replay_is_idempotent_after_issue_projection_is_claimed(self):
        first = self.claim()
        replay = self.store.claim(
            issue=issue(labels=(CLAIMED,)),
            request=request(),
            now=self.now,
            required_dependencies=self.deps,
            dependency_states=self.dep_states,
        )
        self.assertEqual("replay", replay.status)
        self.assertEqual(first.record, replay.record)

    def test_stale_expected_head_is_clean_conflict(self):
        self.store.set_protected_head(HEAD_B)
        with self.assertRaises(ClaimConflict) as caught:
            self.claim()
        self.assertEqual("STALE_EXPECTED_HEAD", caught.exception.code)
        self.assertIsNone(self.store.current_claim(8))

    def test_unmet_dependency_is_rejected(self):
        with self.assertRaises(ClaimValidationError) as caught:
            self.claim(dependency_states={2: COMPLETED, 7: READY})
        self.assertEqual("CLAIM_POLICY_REJECTED", caught.exception.code)

    def test_missing_dependency_observation_is_rejected(self):
        with self.assertRaises(ClaimValidationError):
            self.claim(dependency_states={2: COMPLETED})

    def test_non_ready_task_is_rejected(self):
        with self.assertRaises(ClaimConflict) as caught:
            self.claim(issue=issue(labels=(BLOCKED,)))
        self.assertEqual("TASK_NOT_READY", caught.exception.code)

    def test_ready_claimed_ambiguity_is_rejected(self):
        with self.assertRaises(ClaimValidationError):
            self.claim(issue=issue(labels=(READY, CLAIMED)))

    def test_ready_blocked_ambiguity_is_rejected(self):
        with self.assertRaises(ClaimValidationError):
            self.claim(issue=issue(labels=(READY, BLOCKED)))

    def test_claimed_blocked_ambiguity_is_rejected(self):
        with self.assertRaises(ClaimValidationError):
            self.claim(issue=issue(labels=(CLAIMED, BLOCKED)))

    def test_malformed_claim_input_is_rejected(self):
        bad = request(lease_expires_at="not-a-time")
        with self.assertRaises(ClaimValidationError) as caught:
            self.claim(request=bad)
        self.assertEqual("MALFORMED_CLAIM", caught.exception.code)

    def test_missing_base_evidence_is_rejected(self):
        with self.assertRaises(ClaimValidationError) as caught:
            self.claim(request=request(base_sha=""))
        self.assertEqual("MISSING_BASE_EVIDENCE", caught.exception.code)

    def test_missing_ownership_branch_is_rejected(self):
        with self.assertRaises(ClaimValidationError) as caught:
            self.claim(request=request(branch=""))
        self.assertEqual("MISSING_OWNERSHIP_EVIDENCE", caught.exception.code)

    def test_branch_task_binding_is_enforced(self):
        with self.assertRaises(ClaimValidationError) as caught:
            self.claim(request=request(branch="agent/infra-0009-atomic-claim-prototype"))
        self.assertEqual("BRANCH_TASK_MISMATCH", caught.exception.code)

    def test_second_owner_after_success_is_rejected_even_with_different_branch(self):
        self.claim()
        with self.assertRaises(ClaimConflict) as caught:
            self.claim(
                request=request(
                    branch="agent/infra-0008-another-owner",
                    agent_id="agent-b",
                )
            )
        self.assertEqual("ALREADY_CLAIMED", caught.exception.code)

    def test_milestone_open_or_closed_does_not_change_eligibility(self):
        open_store = AtomicClaimPrototype(repository=REPO, protected_head=HEAD_A)
        closed_store = AtomicClaimPrototype(repository=REPO, protected_head=HEAD_A)
        open_result = open_store.claim(
            issue=issue(milestone_state="open"),
            request=request(),
            now=self.now,
            required_dependencies=self.deps,
            dependency_states=self.dep_states,
            milestone_state="open",
        )
        closed_result = closed_store.claim(
            issue=issue(milestone_state="closed"),
            request=request(),
            now=self.now,
            required_dependencies=self.deps,
            dependency_states=self.dep_states,
            milestone_state="closed",
        )
        self.assertEqual(open_result.record, closed_result.record)

    def test_lease_is_stale_at_exact_expiry(self):
        record = request().as_record()
        self.assertFalse(lease_is_stale(record, "2026-08-14T17:59:59Z"))
        self.assertTrue(lease_is_stale(record, "2026-08-14T18:00:00Z"))

    def test_valid_stale_lease_recovery_renews_same_branch(self):
        first = self.claim().record
        replacement = request(
            claimed_at="2026-08-14T18:00:00Z",
            lease_expires_at="2026-08-14T19:00:00Z",
            agent_id="recovery-agent",
        )
        outcome = self.store.recover_stale(
            issue=issue(labels=(CLAIMED,)),
            expected_claim=first,
            replacement=replacement,
            recovery=RecoveryEvidence(
                task_id=8,
                base_sha=HEAD_A,
                current_branch=BRANCH,
                reason="original agent lease expired",
            ),
            now="2026-08-14T18:00:00Z",
            required_dependencies=self.deps,
            dependency_states=self.dep_states,
        )
        self.assertEqual("recovered", outcome.status)
        self.assertEqual(BRANCH, outcome.record["branch"])
        self.assertEqual("recovery-agent", outcome.record["agent_id"])

    def test_premature_lease_takeover_is_rejected(self):
        first = self.claim().record
        replacement = request(
            claimed_at="2026-08-14T17:45:00Z",
            lease_expires_at="2026-08-14T19:00:00Z",
            agent_id="recovery-agent",
        )
        with self.assertRaises(ClaimConflict) as caught:
            self.store.recover_stale(
                issue=issue(labels=(CLAIMED,)),
                expected_claim=first,
                replacement=replacement,
                recovery=RecoveryEvidence(8, HEAD_A, BRANCH, "attempted recovery"),
                now="2026-08-14T17:45:00Z",
                required_dependencies=self.deps,
                dependency_states=self.dep_states,
            )
        self.assertEqual("LEASE_ACTIVE", caught.exception.code)

    def test_recovery_without_complete_durable_evidence_is_rejected(self):
        first = self.claim().record
        replacement = request(
            claimed_at="2026-08-14T18:00:00Z",
            lease_expires_at="2026-08-14T19:00:00Z",
            agent_id="recovery-agent",
        )
        with self.assertRaises(ClaimValidationError) as caught:
            self.store.recover_stale(
                issue=issue(labels=(CLAIMED,)),
                expected_claim=first,
                replacement=replacement,
                recovery=RecoveryEvidence(8, HEAD_A, BRANCH, ""),
                now="2026-08-14T18:00:00Z",
                required_dependencies=self.deps,
                dependency_states=self.dep_states,
            )
        self.assertEqual("MISSING_RECOVERY_EVIDENCE", caught.exception.code)

    def test_recovery_rejects_stale_expected_claim(self):
        first = self.claim().record
        wrong = dict(first)
        wrong["agent_id"] = "other"
        replacement = request(
            claimed_at="2026-08-14T18:00:00Z",
            lease_expires_at="2026-08-14T19:00:00Z",
            agent_id="recovery-agent",
        )
        with self.assertRaises(ClaimConflict) as caught:
            self.store.recover_stale(
                issue=issue(labels=(CLAIMED,)),
                expected_claim=wrong,
                replacement=replacement,
                recovery=RecoveryEvidence(8, HEAD_A, BRANCH, "expired"),
                now="2026-08-14T18:00:00Z",
                required_dependencies=self.deps,
                dependency_states=self.dep_states,
            )
        self.assertEqual("STALE_EXPECTED_CLAIM", caught.exception.code)

    def test_recovery_rejects_replacement_branch_to_preserve_single_owner(self):
        first = self.claim().record
        replacement = request(
            branch="agent/infra-0008-replacement-owner",
            claimed_at="2026-08-14T18:00:00Z",
            lease_expires_at="2026-08-14T19:00:00Z",
            agent_id="recovery-agent",
        )
        with self.assertRaises(ClaimValidationError) as caught:
            self.store.recover_stale(
                issue=issue(labels=(CLAIMED,)),
                expected_claim=first,
                replacement=replacement,
                recovery=RecoveryEvidence(8, HEAD_A, BRANCH, "expired"),
                now="2026-08-14T18:00:00Z",
                required_dependencies=self.deps,
                dependency_states=self.dep_states,
            )
        self.assertEqual("REPLACEMENT_BRANCH_NOT_SUPPORTED", caught.exception.code)

    def test_recovery_rejects_unmet_dependency(self):
        first = self.claim().record
        replacement = request(
            claimed_at="2026-08-14T18:00:00Z",
            lease_expires_at="2026-08-14T19:00:00Z",
            agent_id="recovery-agent",
        )
        with self.assertRaises(ClaimValidationError) as caught:
            self.store.recover_stale(
                issue=issue(labels=(CLAIMED,)),
                expected_claim=first,
                replacement=replacement,
                recovery=RecoveryEvidence(8, HEAD_A, BRANCH, "expired"),
                now="2026-08-14T18:00:00Z",
                required_dependencies=self.deps,
                dependency_states={2: COMPLETED, 7: BLOCKED},
            )
        self.assertEqual("CLAIM_POLICY_REJECTED", caught.exception.code)

    def test_claimed_recovery_requires_claimed_issue_projection(self):
        first = self.claim().record
        replacement = request(
            claimed_at="2026-08-14T18:00:00Z",
            lease_expires_at="2026-08-14T19:00:00Z",
            agent_id="recovery-agent",
        )
        with self.assertRaises(ClaimConflict) as caught:
            self.store.recover_stale(
                issue=issue(labels=(READY,)),
                expected_claim=first,
                replacement=replacement,
                recovery=RecoveryEvidence(8, HEAD_A, BRANCH, "expired"),
                now="2026-08-14T18:00:00Z",
                required_dependencies=self.deps,
                dependency_states=self.dep_states,
            )
        self.assertEqual("TASK_NOT_CLAIMED", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
