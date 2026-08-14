"""Deterministic exact Core/Full checkpoint extraction from GitHub CI evidence."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Protocol

from control.product_head import ProviderError, ProviderNotFound

PRODUCT_REPOSITORY = "Dsamofalov/hwm_predictor"
WORKFLOW_PATH = ".github/workflows/ci.yml"
CORE_GATE = "HWM / Core"
FULL_GATE = "HWM / Full"
_GATE_CHECK = {CORE_GATE: "core", FULL_GATE: "full"}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_URL_RE = re.compile(
    r"^https://github\.com/Dsamofalov/hwm_predictor/actions/runs/([1-9][0-9]*)$"
)
_JOB_URL_RE = re.compile(
    r"^https://github\.com/Dsamofalov/hwm_predictor/actions/runs/([1-9][0-9]*)/job/([1-9][0-9]*)$"
)
_STATUS_STATES = {"error", "failure", "pending", "success"}
_CHECK_CONCLUSIONS = {"action_required", "cancelled", "failure", "neutral", "skipped", "stale", "success", "timed_out"}


class CheckpointProvider(Protocol):
    """Provider returns complete, fully paginated public GitHub snapshots."""

    def list_workflow_runs(self, repository: str, workflow_path: str) -> Any: ...
    def list_check_runs(self, repository: str, check_suite_id: int) -> Any: ...
    def list_commit_statuses(self, repository: str, sha: str) -> Any: ...


def _safe_message(message: Any) -> str:
    text = " ".join(str(message).replace("\r", " ").replace("\n", " ").split())
    lowered = text.lower()
    if any(marker in lowered for marker in ("authorization:", "bearer ", "token=", "cookie:")):
        return "sanitized upstream provider failure"
    return (text or "upstream provider failure")[:2000]


def _error(code: str, message: Any, retryable: bool = False) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {"code": code, "message": _safe_message(message), "retryable": bool(retryable)},
    }


def _unknown(gate: str) -> dict[str, Any]:
    return {"status": "unknown", "reason": f"no exact successful checkpoint evidence found for {gate}"}


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _runs(payload: Any) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    if not isinstance(payload, list):
        return None, _error("MALFORMED_UPSTREAM_RESPONSE", "workflow run listing is not a list")
    seen: dict[int, tuple[Any, ...]] = {}
    result: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            return None, _error("MALFORMED_UPSTREAM_RESPONSE", "workflow run entry is not an object")
        run_id = item.get("id")
        sha = item.get("head_sha")
        suite_id = item.get("check_suite_id")
        created = _time(item.get("created_at"))
        valid = (
            isinstance(run_id, int) and not isinstance(run_id, bool) and run_id > 0
            and isinstance(suite_id, int) and not isinstance(suite_id, bool) and suite_id > 0
            and item.get("path") == WORKFLOW_PATH and item.get("event") == "push"
            and item.get("status") == "completed"
            and isinstance(sha, str) and _SHA_RE.fullmatch(sha) is not None
            and created is not None
        )
        if not valid:
            return None, _error("MALFORMED_UPSTREAM_RESPONSE", "workflow run identity is incomplete or inconsistent")
        identity = (sha, suite_id, item["created_at"])
        if run_id in seen:
            if seen[run_id] != identity:
                return None, _error("AMBIGUOUS_UPSTREAM_EVIDENCE", "duplicate workflow run id has inconsistent identity")
            continue
        seen[run_id] = identity
        result.append({"id": run_id, "head_sha": sha, "check_suite_id": suite_id, "created_at": item["created_at"], "created_key": created})
    result.sort(key=lambda r: (r["created_key"], r["id"]), reverse=True)
    return result, None


def _check_evidence(payload: Any, run: dict[str, Any], gate: str) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(payload, list):
        return "error", None, _error("MALFORMED_UPSTREAM_RESPONSE", "check-run listing is not a list")
    expected_name = _GATE_CHECK[gate]
    matching: list[dict[str, Any]] = []
    seen_ids: dict[int, tuple[Any, ...]] = {}
    for item in payload:
        if not isinstance(item, dict):
            return "error", None, _error("MALFORMED_UPSTREAM_RESPONSE", "check-run entry is not an object")
        if item.get("name") != expected_name:
            continue
        check_id = item.get("id")
        sha = item.get("head_sha")
        suite = item.get("check_suite")
        details = item.get("details_url")
        match = _JOB_URL_RE.fullmatch(details) if isinstance(details, str) else None
        conclusion = item.get("conclusion")
        valid = (
            isinstance(check_id, int) and not isinstance(check_id, bool) and check_id > 0
            and sha == run["head_sha"] and isinstance(suite, dict) and suite.get("id") == run["check_suite_id"]
            and item.get("status") == "completed" and conclusion in _CHECK_CONCLUSIONS
            and match is not None and int(match.group(1)) == run["id"] and int(match.group(2)) == check_id
        )
        if not valid:
            return "error", None, _error("MALFORMED_UPSTREAM_RESPONSE", f"{gate} aggregate check identity is malformed")
        identity = (sha, run["check_suite_id"], conclusion, details)
        if check_id in seen_ids:
            if seen_ids[check_id] != identity:
                return "error", None, _error("AMBIGUOUS_UPSTREAM_EVIDENCE", "duplicate aggregate check id has inconsistent identity")
            continue
        seen_ids[check_id] = identity
        matching.append({"id": check_id, "conclusion": conclusion})
    if not matching:
        return "missing", None, None
    successful = [c for c in matching if c["conclusion"] == "success"]
    failing = [c for c in matching if c["conclusion"] != "success"]
    if successful and failing:
        return "error", None, _error("AMBIGUOUS_UPSTREAM_EVIDENCE", f"{gate} has conflicting aggregate checks in one run")
    if not successful:
        return "failed", matching[0], None
    if len(successful) > 1:
        ids = {c["id"] for c in successful}
        if len(ids) > 1:
            return "error", None, _error("AMBIGUOUS_UPSTREAM_EVIDENCE", f"{gate} has multiple successful aggregate checks in one run")
    return "success", successful[0], None


def _status_evidence(payload: Any, run: dict[str, Any], gate: str) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(payload, list):
        return "error", None, _error("MALFORMED_UPSTREAM_RESPONSE", "commit status listing is not a list")
    matching: list[dict[str, Any]] = []
    seen_ids: dict[int, tuple[Any, ...]] = {}
    for item in payload:
        if not isinstance(item, dict):
            return "error", None, _error("MALFORMED_UPSTREAM_RESPONSE", "commit status entry is not an object")
        if item.get("context") != gate:
            continue
        status_id = item.get("id")
        state = item.get("state")
        target = item.get("target_url")
        match = _RUN_URL_RE.fullmatch(target) if isinstance(target, str) else None
        valid = (
            isinstance(status_id, int) and not isinstance(status_id, bool) and status_id > 0
            and state in _STATUS_STATES and match is not None
        )
        if not valid:
            return "error", None, _error("MALFORMED_UPSTREAM_RESPONSE", f"{gate} status identity is malformed")
        identity = (state, target)
        if status_id in seen_ids:
            if seen_ids[status_id] != identity:
                return "error", None, _error("AMBIGUOUS_UPSTREAM_EVIDENCE", "duplicate status id has inconsistent identity")
            continue
        seen_ids[status_id] = identity
        if int(match.group(1)) == run["id"]:
            matching.append({"id": status_id, "state": state})
    if not matching:
        return "missing", None, None
    successful = [s for s in matching if s["state"] == "success"]
    non_success = [s for s in matching if s["state"] != "success"]
    if successful and non_success:
        # Multiple status updates for the same run are legitimate (pending -> success).
        successful.sort(key=lambda s: s["id"], reverse=True)
        return "success", successful[0], None
    if successful:
        successful.sort(key=lambda s: s["id"], reverse=True)
        return "success", successful[0], None
    return "failed", max(matching, key=lambda s: s["id"]), None


def _known(gate: str, run: dict[str, Any], check: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    sha = run["head_sha"]
    return {
        "status": "known",
        "sha": sha,
        "provenance": [{
            "kind": "github_actions_run",
            "repo": PRODUCT_REPOSITORY,
            "sha": sha,
            "reference": (
                f"workflow={WORKFLOW_PATH};run={run['id']};suite={run['check_suite_id']};"
                f"gate={gate};check_run={check['id']};status_id={status['id']}"
            ),
        }],
    }


def extract_core_full_checkpoints(provider: CheckpointProvider) -> dict[str, Any]:
    """Return last exact Core and Full green checkpoints independently.

    The provider must fully paginate each GitHub listing. Runs are ordered by
    ``created_at`` descending, then numeric run id descending as a stable tie-break.
    A gate is known only when the fixed workflow run, its aggregate check-run, and
    its exact ``HWM / Core`` or ``HWM / Full`` commit status all bind to one SHA/run.
    Product HEAD is intentionally not an input and is never a fallback.
    """
    base = {"repository": PRODUCT_REPOSITORY, "workflow": WORKFLOW_PATH}
    try:
        raw_runs = provider.list_workflow_runs(PRODUCT_REPOSITORY, WORKFLOW_PATH)
    except ProviderNotFound:
        return {**base, "last_core_green": _unknown(CORE_GATE), "last_full_green": _unknown(FULL_GATE)}
    except ProviderError as exc:
        err = _error(exc.code, exc.message, exc.retryable)
        return {**base, "last_core_green": err, "last_full_green": {**err, "error": dict(err["error"])}}

    runs, run_error = _runs(raw_runs)
    if run_error is not None:
        return {**base, "last_core_green": run_error, "last_full_green": {**run_error, "error": dict(run_error["error"])}}
    assert runs is not None

    found: dict[str, dict[str, Any] | None] = {CORE_GATE: None, FULL_GATE: None}
    errors: dict[str, dict[str, Any] | None] = {CORE_GATE: None, FULL_GATE: None}
    check_cache: dict[int, Any] = {}
    status_cache: dict[str, Any] = {}

    for run in runs:
        if all(found[g] is not None or errors[g] is not None for g in found):
            break
        suite_id = run["check_suite_id"]
        sha = run["head_sha"]
        if suite_id not in check_cache:
            try:
                check_cache[suite_id] = provider.list_check_runs(PRODUCT_REPOSITORY, suite_id)
            except ProviderNotFound:
                check_cache[suite_id] = []
            except ProviderError as exc:
                err = _error(exc.code, exc.message, exc.retryable)
                for gate in found:
                    if found[gate] is None and errors[gate] is None:
                        errors[gate] = err
                break
        if sha not in status_cache:
            try:
                status_cache[sha] = provider.list_commit_statuses(PRODUCT_REPOSITORY, sha)
            except ProviderNotFound:
                status_cache[sha] = []
            except ProviderError as exc:
                err = _error(exc.code, exc.message, exc.retryable)
                for gate in found:
                    if found[gate] is None and errors[gate] is None:
                        errors[gate] = err
                break

        for gate in found:
            if found[gate] is not None or errors[gate] is not None:
                continue
            c_state, check, c_error = _check_evidence(check_cache[suite_id], run, gate)
            if c_error is not None:
                errors[gate] = c_error
                continue
            s_state, status, s_error = _status_evidence(status_cache[sha], run, gate)
            if s_error is not None:
                errors[gate] = s_error
                continue
            if c_state == "success" and s_state == "success":
                assert check is not None and status is not None
                found[gate] = _known(gate, run, check, status)
            elif (c_state == "success") != (s_state == "success") and c_state not in {"missing"} and s_state not in {"missing"}:
                errors[gate] = _error("INCONSISTENT_UPSTREAM_EVIDENCE", f"{gate} aggregate check and commit status disagree")
            # missing/failed evidence is not guessed; continue to older runs.

    return {
        **base,
        "last_core_green": found[CORE_GATE] or errors[CORE_GATE] or _unknown(CORE_GATE),
        "last_full_green": found[FULL_GATE] or errors[FULL_GATE] or _unknown(FULL_GATE),
    }
