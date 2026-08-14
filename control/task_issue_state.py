"""Deterministic GitHub Issue execution-state policy for I04.

This module defines the durable Issue-level execution projection only. Atomic claim
compare-and-set, leases, scheduling, and concurrency belong to I05+.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

READY = "ready"
CLAIMED = "claimed"
BLOCKED = "blocked"
COMPLETED = "completed"

EXECUTION_STATES = frozenset({READY, CLAIMED, BLOCKED, COMPLETED})
ACTIVE_LIFECYCLE_LABELS = frozenset({READY, CLAIMED, BLOCKED})
_ALLOWED_TRANSITIONS = frozenset(
    {
        (READY, CLAIMED),
        (READY, BLOCKED),
        (BLOCKED, READY),
        (CLAIMED, COMPLETED),
    }
)
_COMPLETION_PREREQUISITES = (
    "pull_request_merged",
    "required_ci_green",
    "post_merge_ci_green",
)


class TaskIssueStateError(ValueError):
    """Issue state is ambiguous, malformed, or violates the I04 policy."""


@dataclass(frozen=True)
class TransitionEvidence:
    """Deterministic facts required to authorize a lifecycle transition.

    ``milestone_state`` is accepted only as a best-effort UI projection. It is
    intentionally never used as an execution or dependency gate.
    """

    required_dependencies: tuple[int, ...] = ()
    dependency_states: Mapping[int, str] | None = None
    blocker_evidence_present: bool = False
    blockers_cleared: bool = True
    completion_prerequisites: Mapping[str, bool] | None = None
    recovery: bool = False
    recovery_record_complete: bool = False
    milestone_state: str | None = None


def _label_name(label: Any) -> str:
    if isinstance(label, str):
        if not label:
            raise TaskIssueStateError("Issue label name must be non-empty")
        return label
    if isinstance(label, Mapping) and set(label) >= {"name"}:
        name = label["name"]
        if isinstance(name, str) and name:
            return name
    raise TaskIssueStateError("Issue labels must be strings or objects with a non-empty name")


def interpret_issue_state(issue: Mapping[str, Any]) -> str:
    """Return the single authoritative execution state for a GitHub Issue snapshot.

    Open Issues derive state from exactly one active lifecycle label. A completed
    task is represented by a closed Issue with ``state_reason=completed`` and no
    active lifecycle label. Milestone fields and other UI projections are ignored.
    """

    if not isinstance(issue, Mapping):
        raise TaskIssueStateError("Issue snapshot must be an object")
    github_state = issue.get("state")
    if github_state not in {"open", "closed"}:
        raise TaskIssueStateError("Issue state must be open or closed")

    raw_labels = issue.get("labels")
    if not isinstance(raw_labels, Sequence) or isinstance(raw_labels, (str, bytes, bytearray)):
        raise TaskIssueStateError("Issue labels must be a sequence")
    names = [_label_name(label) for label in raw_labels]
    active = sorted(ACTIVE_LIFECYCLE_LABELS.intersection(names))

    if github_state == "open":
        if len(active) != 1:
            raise TaskIssueStateError(
                "Open Issue must have exactly one of ready, claimed, blocked"
            )
        if issue.get("state_reason") not in {None, "reopened"}:
            raise TaskIssueStateError("Open Issue has incompatible state_reason")
        return active[0]

    if active:
        raise TaskIssueStateError("Completed Issue must not retain an active lifecycle label")
    if issue.get("state_reason") != "completed":
        raise TaskIssueStateError(
            "Closed Issue is not an authoritative completed task without state_reason=completed"
        )
    return COMPLETED


def dependencies_satisfied(
    required_dependencies: Iterable[int],
    dependency_states: Mapping[int, str] | None,
) -> bool:
    """Return whether every required dependency is deterministically completed.

    Missing, malformed, or unknown dependency observations are rejected instead of
    being guessed. An empty dependency set is satisfied without requiring a map.
    """

    required = tuple(required_dependencies)
    if len(required) != len(set(required)):
        raise TaskIssueStateError("Required dependencies must be unique")
    if any(not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in required):
        raise TaskIssueStateError("Required dependencies must be positive Issue numbers")
    if not required:
        return True
    if not isinstance(dependency_states, Mapping):
        raise TaskIssueStateError("Dependency states are required for dependency-gated transition")

    for issue_number in required:
        if issue_number not in dependency_states:
            raise TaskIssueStateError(
                f"Dependency #{issue_number} state is unavailable; refusing to guess"
            )
        state = dependency_states[issue_number]
        if state not in EXECUTION_STATES:
            raise TaskIssueStateError(
                f"Dependency #{issue_number} has unknown execution state: {state!r}"
            )
        if state != COMPLETED:
            return False
    return True


def _completion_prerequisites_satisfied(values: Mapping[str, bool] | None) -> bool:
    if not isinstance(values, Mapping):
        raise TaskIssueStateError("Completion prerequisites are required")
    if set(values) != set(_COMPLETION_PREREQUISITES):
        raise TaskIssueStateError(
            "Completion prerequisites must be exactly: "
            + ", ".join(_COMPLETION_PREREQUISITES)
        )
    if any(not isinstance(values[key], bool) for key in _COMPLETION_PREREQUISITES):
        raise TaskIssueStateError("Completion prerequisites must be boolean")
    return all(values[key] for key in _COMPLETION_PREREQUISITES)


def validate_transition(before: str, after: str, evidence: TransitionEvidence) -> None:
    """Validate one I04 execution-state transition.

    Claimed-task recovery is a state-preserving recovery operation, not a
    lifecycle transition: ``claimed -> claimed`` is accepted only with an explicit,
    complete durable recovery record. The atomic replacement-claim mechanism is
    deliberately outside this module.
    """

    if before not in EXECUTION_STATES or after not in EXECUTION_STATES:
        raise TaskIssueStateError("Transition endpoints must be known execution states")
    if not isinstance(evidence, TransitionEvidence):
        raise TaskIssueStateError("Transition evidence must use TransitionEvidence")

    # Best-effort UI projection by contract. Never gate execution on it.
    _ = evidence.milestone_state

    if before == CLAIMED and after == CLAIMED:
        if evidence.recovery and evidence.recovery_record_complete:
            return
        raise TaskIssueStateError(
            "claimed -> claimed is allowed only as explicit durable recovery"
        )
    if evidence.recovery:
        raise TaskIssueStateError("Recovery must preserve claimed execution state")

    if (before, after) not in _ALLOWED_TRANSITIONS:
        raise TaskIssueStateError(f"Forbidden task Issue transition: {before} -> {after}")

    deps_met = dependencies_satisfied(
        evidence.required_dependencies,
        evidence.dependency_states,
    )

    if (before, after) == (READY, CLAIMED):
        if not deps_met:
            raise TaskIssueStateError("Cannot claim a task with unmet dependencies")
        return

    if (before, after) == (READY, BLOCKED):
        if deps_met and not evidence.blocker_evidence_present:
            raise TaskIssueStateError(
                "ready -> blocked requires a known unmet dependency or explicit blocker evidence"
            )
        return

    if (before, after) == (BLOCKED, READY):
        if not deps_met:
            raise TaskIssueStateError("Blocked task cannot become ready with unmet dependencies")
        if not evidence.blockers_cleared:
            raise TaskIssueStateError("Blocked task cannot become ready while blockers remain")
        return

    if (before, after) == (CLAIMED, COMPLETED):
        if not deps_met:
            raise TaskIssueStateError("Cannot complete a task with unmet dependencies")
        if not _completion_prerequisites_satisfied(evidence.completion_prerequisites):
            raise TaskIssueStateError("Cannot complete before all required merge/CI prerequisites")
        return

    raise AssertionError("unreachable transition branch")
