"""Minimal deterministic I05 atomic claim prototype.

The prototype deliberately contains no scheduler and no GitHub mutation code.  It
models the task-scoped compare-and-set that a storage/GitHub adapter must perform:
validate one authoritative Issue snapshot, compare the exact protected base, and
install exactly one hwm-claim/v1 record plus its ownership-branch binding.

The in-memory implementation is intentionally small and deterministic so the
concurrency, lease, stale-observation, replay, and recovery semantics are
machine-checkable without introducing a second serialization contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import threading
from typing import Any, Mapping

from control.task_issue_state import (
    CLAIMED,
    COMPLETED,
    READY,
    TaskIssueStateError,
    TransitionEvidence,
    dependencies_satisfied,
    interpret_issue_state,
    validate_transition,
)

CLAIM_SCHEMA = "hwm-claim/v1"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^agent/[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_INFRA_BRANCH_RE = re.compile(r"^agent/infra-(\d{4})-[a-z0-9][a-z0-9-]{0,95}$")
_AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ClaimError(ValueError):
    """Base class for deterministic claim rejection."""


class ClaimConflict(ClaimError):
    """A clean CAS conflict; no ownership mutation occurred."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ClaimValidationError(ClaimError):
    """Malformed or policy-invalid input; callers must not guess."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ClaimRequest:
    """One proposed hwm-claim/v1 ownership record."""

    task_id: int
    branch: str
    base_repo: str
    base_sha: str
    claimed_at: str
    lease_expires_at: str
    agent_id: str | None = None

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema": CLAIM_SCHEMA,
            "task_id": self.task_id,
            "branch": self.branch,
            "base_repo": self.base_repo,
            "base_sha": self.base_sha,
            "claimed_at": self.claimed_at,
            "lease_expires_at": self.lease_expires_at,
        }
        if self.agent_id is not None:
            record["agent_id"] = self.agent_id
        return record


@dataclass(frozen=True)
class RecoveryEvidence:
    """Explicit durable evidence for state-preserving stale-lease recovery."""

    task_id: int
    base_sha: str
    current_branch: str
    reason: str

    def complete_for(self, claim: Mapping[str, Any]) -> bool:
        return (
            isinstance(self.reason, str)
            and bool(self.reason.strip())
            and self.task_id == claim.get("task_id")
            and self.base_sha == claim.get("base_sha")
            and self.current_branch == claim.get("branch")
        )


@dataclass(frozen=True)
class ClaimOutcome:
    """Successful claim operation result."""

    status: str
    record: Mapping[str, Any]


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ClaimValidationError("MALFORMED_CLAIM", f"{field} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ClaimValidationError("MALFORMED_CLAIM", f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ClaimValidationError("MALFORMED_CLAIM", f"{field} must be UTC")
    return parsed


def _issue_number(issue: Mapping[str, Any]) -> int:
    if not isinstance(issue, Mapping):
        raise ClaimValidationError("MALFORMED_ISSUE", "Issue snapshot must be an object")
    values = [issue.get(key) for key in ("issue_number", "number") if key in issue]
    if not values:
        raise ClaimValidationError("MALFORMED_ISSUE", "Issue snapshot must contain issue_number or number")
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in values):
        raise ClaimValidationError("MALFORMED_ISSUE", "Issue number must be a positive integer")
    if len(set(values)) != 1:
        raise ClaimValidationError("MALFORMED_ISSUE", "Issue number fields disagree")
    return values[0]


def _validate_request(request: ClaimRequest, now: datetime) -> tuple[datetime, datetime]:
    if not isinstance(request, ClaimRequest):
        raise ClaimValidationError("MALFORMED_CLAIM", "claim request must use ClaimRequest")
    if not isinstance(request.task_id, int) or isinstance(request.task_id, bool) or request.task_id <= 0:
        raise ClaimValidationError("MALFORMED_CLAIM", "task_id must be a positive integer")
    if not isinstance(request.base_repo, str) or _REPO_RE.fullmatch(request.base_repo) is None:
        raise ClaimValidationError("MALFORMED_CLAIM", "base_repo is malformed")
    if not isinstance(request.base_sha, str) or _SHA_RE.fullmatch(request.base_sha) is None:
        raise ClaimValidationError("MISSING_BASE_EVIDENCE", "base_sha must be an exact lowercase 40-hex SHA")
    if not isinstance(request.branch, str) or _BRANCH_RE.fullmatch(request.branch) is None:
        raise ClaimValidationError("MISSING_OWNERSHIP_EVIDENCE", "branch must be a valid agent ownership branch")
    if request.branch.startswith("agent/infra-"):
        match = _INFRA_BRANCH_RE.fullmatch(request.branch)
        if match is None or int(match.group(1)) != request.task_id:
            raise ClaimValidationError("BRANCH_TASK_MISMATCH", "infrastructure ownership branch must bind the same Issue/task id")
    if request.agent_id is not None and (
        not isinstance(request.agent_id, str) or _AGENT_RE.fullmatch(request.agent_id) is None
    ):
        raise ClaimValidationError("MALFORMED_CLAIM", "agent_id is malformed")

    claimed_at = _parse_utc(request.claimed_at, "claimed_at")
    expires_at = _parse_utc(request.lease_expires_at, "lease_expires_at")
    if claimed_at >= expires_at:
        raise ClaimValidationError("MALFORMED_CLAIM", "lease_expires_at must be later than claimed_at")
    if claimed_at > now:
        raise ClaimValidationError("MALFORMED_CLAIM", "claimed_at cannot be in the future")
    if now >= expires_at:
        raise ClaimValidationError("STALE_PROPOSED_LEASE", "a newly installed lease must be active at CAS time")
    return claimed_at, expires_at


def lease_is_stale(record: Mapping[str, Any], now: str) -> bool:
    """Return True at or after lease expiry; malformed records are rejected."""

    if not isinstance(record, Mapping):
        raise ClaimValidationError("MALFORMED_CLAIM", "claim record must be an object")
    expires_at = _parse_utc(record.get("lease_expires_at"), "lease_expires_at")
    observed = _parse_utc(now, "now")
    return observed >= expires_at


class AtomicClaimPrototype:
    """Thread-safe task-scoped CAS prototype.

    The atomic section is keyed by task id, not by caller/session.  A successful
    write installs the sole active claim record and ownership branch binding.
    Contenders that observed the same READY snapshot therefore cannot both win,
    even when they propose different branch names.
    """

    def __init__(self, *, repository: str, protected_head: str):
        if not isinstance(repository, str) or _REPO_RE.fullmatch(repository) is None:
            raise ClaimValidationError("MALFORMED_STORE", "repository is malformed")
        if not isinstance(protected_head, str) or _SHA_RE.fullmatch(protected_head) is None:
            raise ClaimValidationError("MALFORMED_STORE", "protected_head must be an exact SHA")
        self._repository = repository
        self._protected_head = protected_head
        self._claims: dict[int, dict[str, Any]] = {}
        self._branch_owner: dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def protected_head(self) -> str:
        with self._lock:
            return self._protected_head

    def set_protected_head(self, sha: str) -> None:
        """Test/storage-adapter hook for an externally observed protected-head move."""

        if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
            raise ClaimValidationError("MALFORMED_STORE", "protected head must be an exact SHA")
        with self._lock:
            self._protected_head = sha

    def current_claim(self, task_id: int) -> Mapping[str, Any] | None:
        with self._lock:
            record = self._claims.get(task_id)
            return dict(record) if record is not None else None

    def claim(
        self,
        *,
        issue: Mapping[str, Any],
        request: ClaimRequest,
        now: str,
        required_dependencies: tuple[int, ...] = (),
        dependency_states: Mapping[int, str] | None = None,
        milestone_state: str | None = None,
    ) -> ClaimOutcome:
        """Claim one READY task or return a clean conflict.

        `milestone_state` is accepted for evidence parity but intentionally ignored.
        """

        observed_now = _parse_utc(now, "now")
        _validate_request(request, observed_now)
        if request.base_repo != self._repository:
            raise ClaimValidationError("REPOSITORY_MISMATCH", "claim repository does not match the store")
        issue_number = _issue_number(issue)
        if issue_number != request.task_id:
            raise ClaimValidationError("TASK_ISSUE_MISMATCH", "claim task_id does not match the Issue number")

        try:
            issue_state = interpret_issue_state(issue)
        except TaskIssueStateError as exc:
            raise ClaimValidationError("MALFORMED_ISSUE", str(exc)) from exc

        proposed = request.as_record()

        with self._lock:
            existing = self._claims.get(request.task_id)

            # Exact replay is safe only after the durable Issue projection is claimed.
            if existing is not None and existing == proposed and issue_state == CLAIMED:
                return ClaimOutcome("replay", dict(existing))
            if existing is not None:
                raise ClaimConflict("ALREADY_CLAIMED", "task already has an active ownership record")

            if issue_state != READY:
                raise ClaimConflict("TASK_NOT_READY", f"task state is {issue_state!r}, not ready")

            try:
                validate_transition(
                    READY,
                    CLAIMED,
                    TransitionEvidence(
                        required_dependencies=required_dependencies,
                        dependency_states=dependency_states,
                        milestone_state=milestone_state,
                    ),
                )
            except TaskIssueStateError as exc:
                raise ClaimValidationError("CLAIM_POLICY_REJECTED", str(exc)) from exc

            if self._protected_head != request.base_sha:
                raise ClaimConflict("STALE_EXPECTED_HEAD", "protected head no longer matches the observed base SHA")

            other_task = self._branch_owner.get(request.branch)
            if other_task is not None:
                raise ClaimConflict("BRANCH_CONFLICT", "ownership branch is already bound")

            # One critical section installs both task ownership and branch binding.
            self._claims[request.task_id] = dict(proposed)
            self._branch_owner[request.branch] = request.task_id
            return ClaimOutcome("claimed", dict(proposed))

    def recover_stale(
        self,
        *,
        issue: Mapping[str, Any],
        expected_claim: Mapping[str, Any],
        replacement: ClaimRequest,
        recovery: RecoveryEvidence,
        now: str,
        required_dependencies: tuple[int, ...] = (),
        dependency_states: Mapping[int, str] | None = None,
        milestone_state: str | None = None,
    ) -> ClaimOutcome:
        """Renew a stale claimed task on the same ownership branch.

        Replacement-branch takeover is deliberately outside this prototype.  The
        same branch remains the sole ownership token, while the claim record lease
        and optional agent/session identifier are replaced via exact-record CAS.
        """

        observed_now = _parse_utc(now, "now")
        replacement_claimed_at, _ = _validate_request(replacement, observed_now)
        if replacement.base_repo != self._repository:
            raise ClaimValidationError("REPOSITORY_MISMATCH", "claim repository does not match the store")
        issue_number = _issue_number(issue)
        if issue_number != replacement.task_id:
            raise ClaimValidationError("TASK_ISSUE_MISMATCH", "claim task_id does not match the Issue number")

        try:
            state = interpret_issue_state(issue)
        except TaskIssueStateError as exc:
            raise ClaimValidationError("MALFORMED_ISSUE", str(exc)) from exc
        if state != CLAIMED:
            raise ClaimConflict("TASK_NOT_CLAIMED", "stale-lease recovery requires a claimed Issue")

        if not isinstance(expected_claim, Mapping):
            raise ClaimValidationError("MISSING_RECOVERY_EVIDENCE", "expected current claim record is required")

        with self._lock:
            current = self._claims.get(replacement.task_id)
            if current is None:
                raise ClaimConflict("MISSING_CURRENT_CLAIM", "no active ownership record exists")

            # Idempotent replay of the already-installed replacement.
            replacement_record = replacement.as_record()
            if current == replacement_record:
                return ClaimOutcome("replay", dict(current))

            if dict(expected_claim) != current:
                raise ClaimConflict("STALE_EXPECTED_CLAIM", "current claim record changed since observation")

            try:
                deps_met = dependencies_satisfied(required_dependencies, dependency_states)
            except TaskIssueStateError as exc:
                raise ClaimValidationError("CLAIM_POLICY_REJECTED", str(exc)) from exc
            if not deps_met:
                raise ClaimValidationError("CLAIM_POLICY_REJECTED", "recovery requires completed dependencies")

            record_complete = isinstance(recovery, RecoveryEvidence) and recovery.complete_for(current)
            try:
                validate_transition(
                    CLAIMED,
                    CLAIMED,
                    TransitionEvidence(
                        recovery=True,
                        recovery_record_complete=record_complete,
                        milestone_state=milestone_state,
                    ),
                )
            except TaskIssueStateError as exc:
                raise ClaimValidationError("MISSING_RECOVERY_EVIDENCE", str(exc)) from exc

            current_expiry = _parse_utc(current.get("lease_expires_at"), "lease_expires_at")
            if observed_now < current_expiry:
                raise ClaimConflict("LEASE_ACTIVE", "lease has not expired; takeover is premature")
            if replacement_claimed_at < current_expiry:
                raise ClaimValidationError("OVERLAPPING_LEASE", "replacement lease must not begin before old lease expiry")

            # Safe minimum recovery: retain one exact ownership branch and base.
            if (
                replacement.branch != current.get("branch")
                or replacement.base_sha != current.get("base_sha")
                or replacement.base_repo != current.get("base_repo")
            ):
                raise ClaimValidationError(
                    "REPLACEMENT_BRANCH_NOT_SUPPORTED",
                    "I05 prototype recovery renews the same durable ownership branch only",
                )

            self._claims[replacement.task_id] = dict(replacement_record)
            return ClaimOutcome("recovered", dict(replacement_record))
