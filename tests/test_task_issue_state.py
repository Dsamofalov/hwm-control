from __future__ import annotations

import unittest

from control.task_issue_state import (
    BLOCKED,
    CLAIMED,
    COMPLETED,
    READY,
    TaskIssueStateError,
    TransitionEvidence,
    dependencies_satisfied,
    interpret_issue_state,
    validate_transition,
)


def issue(*, state="open", state_reason=None, labels=(), milestone_state="open"):
    return {
        "state": state,
        "state_reason": state_reason,
        "labels": [{"name": name} for name in labels],
        "milestone": {"state": milestone_state},
    }


def completion():
    return {
        "pull_request_merged": True,
        "required_ci_green": True,
        "post_merge_ci_green": True,
    }


class TaskIssueStateTests(unittest.TestCase):
    def test_ready_to_claimed_with_completed_dependencies(self):
        validate_transition(
            READY,
            CLAIMED,
            TransitionEvidence(
                required_dependencies=(2, 6),
                dependency_states={2: COMPLETED, 6: COMPLETED},
            ),
        )

    def test_claimed_to_completed_with_all_prerequisites(self):
        validate_transition(
            CLAIMED,
            COMPLETED,
            TransitionEvidence(
                required_dependencies=(2, 6),
                dependency_states={2: COMPLETED, 6: COMPLETED},
                completion_prerequisites=completion(),
            ),
        )

    def test_blocked_to_ready_after_dependency_is_completed(self):
        validate_transition(
            BLOCKED,
            READY,
            TransitionEvidence(
                required_dependencies=(7,),
                dependency_states={7: COMPLETED},
                blockers_cleared=True,
            ),
        )

    def test_claimed_recovery_preserves_claimed_state(self):
        validate_transition(
            CLAIMED,
            CLAIMED,
            TransitionEvidence(recovery=True, recovery_record_complete=True),
        )

    def test_ready_and_claimed_labels_are_ambiguous(self):
        with self.assertRaises(TaskIssueStateError):
            interpret_issue_state(issue(labels=(READY, CLAIMED)))

    def test_ready_and_blocked_labels_are_ambiguous(self):
        with self.assertRaises(TaskIssueStateError):
            interpret_issue_state(issue(labels=(READY, BLOCKED)))

    def test_claimed_and_blocked_labels_are_ambiguous(self):
        with self.assertRaises(TaskIssueStateError):
            interpret_issue_state(issue(labels=(CLAIMED, BLOCKED)))

    def test_completed_issue_cannot_retain_active_lifecycle_label(self):
        with self.assertRaises(TaskIssueStateError):
            interpret_issue_state(
                issue(
                    state="closed",
                    state_reason="completed",
                    labels=(CLAIMED,),
                )
            )

    def test_claim_with_unmet_dependency_is_rejected(self):
        with self.assertRaises(TaskIssueStateError):
            validate_transition(
                READY,
                CLAIMED,
                TransitionEvidence(
                    required_dependencies=(7,),
                    dependency_states={7: BLOCKED},
                ),
            )

    def test_completion_with_failed_prerequisite_is_rejected(self):
        bad = completion()
        bad["post_merge_ci_green"] = False
        with self.assertRaises(TaskIssueStateError):
            validate_transition(
                CLAIMED,
                COMPLETED,
                TransitionEvidence(
                    completion_prerequisites=bad,
                ),
            )

    def test_illegal_backwards_transition_is_rejected(self):
        with self.assertRaises(TaskIssueStateError):
            validate_transition(CLAIMED, READY, TransitionEvidence())

    def test_illegal_skip_transition_is_rejected(self):
        with self.assertRaises(TaskIssueStateError):
            validate_transition(READY, COMPLETED, TransitionEvidence())

    def test_milestone_state_is_not_an_execution_gate(self):
        open_projection = interpret_issue_state(
            issue(labels=(READY,), milestone_state="open")
        )
        closed_projection = interpret_issue_state(
            issue(labels=(READY,), milestone_state="closed")
        )
        self.assertEqual(READY, open_projection)
        self.assertEqual(open_projection, closed_projection)
        validate_transition(
            READY,
            CLAIMED,
            TransitionEvidence(milestone_state="closed"),
        )

    def test_missing_lifecycle_label_is_rejected_without_guessing(self):
        with self.assertRaises(TaskIssueStateError):
            interpret_issue_state(issue(labels=()))

    def test_missing_dependency_observation_is_rejected_without_guessing(self):
        with self.assertRaises(TaskIssueStateError):
            dependencies_satisfied((7,), {})

    def test_closed_noncompleted_issue_is_not_execution_completed(self):
        with self.assertRaises(TaskIssueStateError):
            interpret_issue_state(
                issue(
                    state="closed",
                    state_reason="not_planned",
                    labels=(),
                )
            )

    def test_ready_to_blocked_requires_proven_blocker_when_dependencies_met(self):
        with self.assertRaises(TaskIssueStateError):
            validate_transition(
                READY,
                BLOCKED,
                TransitionEvidence(),
            )

    def test_ready_to_blocked_accepts_unmet_known_dependency(self):
        validate_transition(
            READY,
            BLOCKED,
            TransitionEvidence(
                required_dependencies=(7,),
                dependency_states={7: CLAIMED},
            ),
        )

    def test_ready_to_blocked_accepts_explicit_non_dependency_blocker(self):
        validate_transition(
            READY,
            BLOCKED,
            TransitionEvidence(blocker_evidence_present=True),
        )

    def test_claimed_recovery_requires_complete_durable_record(self):
        with self.assertRaises(TaskIssueStateError):
            validate_transition(
                CLAIMED,
                CLAIMED,
                TransitionEvidence(recovery=True, recovery_record_complete=False),
            )


if __name__ == "__main__":
    unittest.main()
