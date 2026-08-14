"""Deterministic I07 compiler for the minimal fresh-agent bootstrap."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from control.task_issue_state import TaskIssueStateError, interpret_issue_state

INFRA_REPOSITORY = "Dsamofalov/hwm-control"
INFRA_REF = "refs/heads/main"
PROJECT_STATE_SCHEMA = "hwm-project-state/v2"
CONTEXT_REPOSITORY = "Dsamofalov/hwm-context"
PROJECT_STATE_PATH = "state/current.json"
JSON_OUTPUT_PATH = "bootstrap/current.json"
MARKDOWN_OUTPUT_PATH = "bootstrap/current.md"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TASK_BUCKETS = ("ready", "claimed", "blocked")
_ALLOWED_SOURCE_KEYS = {"repo", "path", "commit_sha", "blob_sha"}

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "project-state.v2.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


class GeneratedBootstrapError(ValueError):
    """Bootstrap inputs are stale, ambiguous, malformed, or inconsistent."""


@dataclass(frozen=True)
class GeneratedBootstrap:
    json_bytes: bytes
    markdown_bytes: bytes

    def files(self) -> dict[str, bytes]:
        return {
            JSON_OUTPUT_PATH: self.json_bytes,
            MARKDOWN_OUTPUT_PATH: self.markdown_bytes,
        }


def _git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _display_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _require_sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise GeneratedBootstrapError(f"{field} must be exact lowercase 40-hex")
    return value


def _validate_state(project_state: Any) -> dict[str, Any]:
    if not isinstance(project_state, dict):
        raise GeneratedBootstrapError("project_state must be an object")
    try:
        _VALIDATOR.validate(project_state)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise GeneratedBootstrapError(
            f"project_state is schema-invalid at {path}: {exc.message}"
        ) from exc
    if project_state.get("schema") != PROJECT_STATE_SCHEMA:
        raise GeneratedBootstrapError("project_state schema is not hwm-project-state/v2")
    return copy.deepcopy(project_state)


def _validate_state_source(source: Any, project_state: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(source, Mapping) or set(source) != _ALLOWED_SOURCE_KEYS:
        raise GeneratedBootstrapError(
            "project_state_source must contain exactly repo, path, commit_sha, blob_sha"
        )
    repo = source["repo"]
    path = source["path"]
    if not isinstance(repo, str) or _REPO_RE.fullmatch(repo) is None:
        raise GeneratedBootstrapError("project_state_source.repo is invalid")
    if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
        raise GeneratedBootstrapError("project_state_source.path is invalid")
    if repo != CONTEXT_REPOSITORY or path != PROJECT_STATE_PATH:
        raise GeneratedBootstrapError("project_state source identity is ambiguous or unsupported")
    commit_sha = _require_sha(source["commit_sha"], field="project_state_source.commit_sha")
    blob_sha = _require_sha(source["blob_sha"], field="project_state_source.blob_sha")
    actual_blob = _git_blob_sha(_canonical_json_bytes(project_state))
    if blob_sha != actual_blob:
        raise GeneratedBootstrapError(
            f"project_state_source.blob_sha mismatch: expected canonical state blob {actual_blob}"
        )
    return {"repo": repo, "path": path, "commit_sha": commit_sha, "blob_sha": blob_sha}


def _issue_projection(issue: Any) -> tuple[int, str, dict[str, Any]]:
    if not isinstance(issue, Mapping):
        raise GeneratedBootstrapError("task issue snapshot must be an object")
    number = issue.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise GeneratedBootstrapError("task issue number must be a positive integer")
    title = issue.get("title")
    url = issue.get("html_url")
    updated_at = issue.get("updated_at")
    if not isinstance(title, str) or not title.strip():
        raise GeneratedBootstrapError(f"task #{number} title is missing")
    if not isinstance(url, str) or url != f"https://github.com/{INFRA_REPOSITORY}/issues/{number}":
        raise GeneratedBootstrapError(f"task #{number} html_url is not the canonical Issue URL")
    if not isinstance(updated_at, str) or not updated_at.endswith("Z"):
        raise GeneratedBootstrapError(f"task #{number} updated_at is missing or ambiguous")
    milestone = issue.get("milestone")
    if not isinstance(milestone, Mapping) or not isinstance(milestone.get("title"), str) or not milestone["title"].strip():
        raise GeneratedBootstrapError(f"task #{number} milestone title is missing")
    try:
        state = interpret_issue_state(issue)
    except TaskIssueStateError as exc:
        raise GeneratedBootstrapError(f"task #{number} lifecycle is invalid: {exc}") from exc
    if state not in _TASK_BUCKETS:
        raise GeneratedBootstrapError(f"task #{number} is not an active ready/claimed/blocked task")
    projection = {
        "number": number,
        "title": title.strip(),
        "html_url": url,
        "updated_at": updated_at,
        "state": state,
        "milestone": milestone["title"].strip(),
    }
    projection["sha256"] = hashlib.sha256(_canonical_json_bytes(projection)).hexdigest()
    return number, state, projection


def _validate_task_issues(
    task_issues: Any,
    *,
    project_state: Mapping[str, Any],
    expected_task_updated_at: Mapping[int, str],
) -> list[dict[str, Any]]:
    if not isinstance(task_issues, Sequence) or isinstance(task_issues, (str, bytes, bytearray)):
        raise GeneratedBootstrapError("task_issues must be a sequence")
    if not isinstance(expected_task_updated_at, Mapping):
        raise GeneratedBootstrapError("expected_task_updated_at must be an Issue-number mapping")

    expected_by_state = {bucket: set(project_state["tasks"][bucket]) for bucket in _TASK_BUCKETS}
    expected_numbers = set().union(*(expected_by_state[bucket] for bucket in _TASK_BUCKETS))
    if set(expected_task_updated_at) != expected_numbers:
        raise GeneratedBootstrapError(
            "expected task revisions must cover exactly project_state active task identities"
        )

    seen: set[int] = set()
    projections: list[dict[str, Any]] = []
    for issue in task_issues:
        number, state, projection = _issue_projection(issue)
        if number in seen:
            raise GeneratedBootstrapError(f"duplicate task issue snapshot #{number}")
        seen.add(number)
        if number not in expected_numbers:
            raise GeneratedBootstrapError(f"unrelated task issue snapshot #{number}")
        if number not in expected_by_state[state]:
            raise GeneratedBootstrapError(
                f"task #{number} lifecycle does not match project_state.tasks.{state}"
            )
        expected_revision = expected_task_updated_at[number]
        if not isinstance(expected_revision, str) or expected_revision != projection["updated_at"]:
            raise GeneratedBootstrapError(f"task #{number} source revision is stale")
        projections.append(projection)

    if seen != expected_numbers:
        missing = sorted(expected_numbers - seen)
        raise GeneratedBootstrapError(f"missing task issue snapshots: {missing}")
    return sorted(projections, key=lambda item: item["number"])


def _milestone_status(task_sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not task_sources:
        return {"status": "unknown", "reason": "no active task Issues in deterministic project state"}
    milestones = sorted({item["milestone"] for item in task_sources})
    if len(milestones) != 1:
        return {
            "status": "error",
            "error": {
                "code": "AMBIGUOUS_ACTIVE_MILESTONE",
                "message": "active task Issues project more than one infrastructure milestone",
                "retryable": False,
            },
            "milestones": milestones,
        }
    milestone = milestones[0]
    return {
        "status": "known",
        "milestone": milestone,
        "tasks": {
            bucket: [item["number"] for item in task_sources if item["state"] == bucket]
            for bucket in _TASK_BUCKETS
        },
        "milestone_open_closed_is_gate": False,
    }


def _hard_invariants(infrastructure_head: str) -> list[dict[str, Any]]:
    source = {"repo": INFRA_REPOSITORY, "sha": infrastructure_head}
    return [
        {
            "id": "exact-source-no-guessing",
            "rule": "Current facts come from deterministic exact sources; unknown/error values are preserved, never guessed.",
            "source": {**source, "path": "docs/INFRA_SPEC.md"},
        },
        {
            "id": "task-lifecycle-exclusive",
            "rule": "An open task Issue has exactly one of ready, claimed, blocked; completed is closed with state_reason=completed and no active lifecycle label.",
            "source": {**source, "path": "docs/I04_TASK_ISSUE_STATE_POLICY.md"},
        },
        {
            "id": "milestone-not-gate",
            "rule": "GitHub milestone open/closed state is a best-effort UI projection, not an execution or dependency gate.",
            "source": {**source, "path": "docs/I04_TASK_ISSUE_STATE_POLICY.md"},
        },
        {
            "id": "one-owner-claim",
            "rule": "Task ownership is one-owner and exact-head CAS-bound; recovery must not guess or create a second owner.",
            "source": {**source, "path": "docs/I05_ATOMIC_CLAIM_POLICY.md"},
        },
        {
            "id": "knowledge-delta-required",
            "rule": "Every I06+ active/completed durable infrastructure task requires its own canonical Knowledge Delta.",
            "source": {**source, "path": "docs/I06_KNOWLEDGE_DELTA_GATE_POLICY.md"},
        },
    ]


def _render_markdown(data: Mapping[str, Any]) -> bytes:
    product = data["product"]
    milestone = data["infrastructure_milestone"]
    lines = [
        "# Generated HWM infrastructure bootstrap",
        "",
        "> Generated from deterministic exact sources. Do not edit volatile facts manually.",
        "",
        f"- Infrastructure HEAD: `{data['infrastructure']['head']}`",
        f"- Product repository: `{product['repo']}`",
        f"- Product HEAD status: `{product['head']['status']}`",
    ]
    if product["head"]["status"] == "known":
        lines.append(f"- Product HEAD: `{product['head']['sha']}`")
    elif product["head"]["status"] == "unknown":
        lines.append(f"- Product HEAD reason: {product['head']['reason']}")
    else:
        lines.append(f"- Product HEAD error: `{product['head']['error']['code']}` — {product['head']['error']['message']}")

    if milestone["status"] == "known":
        lines.append(f"- Infrastructure milestone: `{milestone['milestone']}`")
    elif milestone["status"] == "unknown":
        lines.append(f"- Infrastructure milestone: `unknown` — {milestone['reason']}")
    else:
        lines.append(f"- Infrastructure milestone: `error` — {milestone['error']['code']}")

    lines.extend(["", "## Validated checkpoints", ""])
    for key in ("last_core_green", "last_full_green", "last_post_merge_green", "last_live_evidenced"):
        checkpoint = product["validated_checkpoints"][key]
        if checkpoint["status"] == "known":
            detail = checkpoint["sha"]
        elif checkpoint["status"] == "unknown":
            detail = f"unknown — {checkpoint['reason']}"
        else:
            detail = f"error {checkpoint['error']['code']} — {checkpoint['error']['message']}"
        lines.append(f"- `{key}`: {detail}")

    lines.extend(["", "## Ready tasks", ""])
    if data["ready_tasks"]:
        for task in data["ready_tasks"]:
            lines.append(f"- [#{task['issue']}]({task['context']['url']}) {task['title']}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Hard invariants", ""])
    for invariant in data["hard_invariants"]:
        lines.append(f"- **{invariant['id']}** — {invariant['rule']}")

    lines.extend(["", "## Exact sources", ""])
    lines.append(
        f"- Infrastructure: `{data['sources']['infrastructure']['repo']}` "
        f"`{data['sources']['infrastructure']['ref']}` @ `{data['sources']['infrastructure']['sha']}`"
    )
    state_source = data["sources"]["project_state"]
    lines.append(
        f"- Project state: `{state_source['repo']}/{state_source['path']}` @ `{state_source['commit_sha']}` "
        f"(blob `{state_source['blob_sha']}`)"
    )
    for task in data["sources"]["tasks"]:
        lines.append(
            f"- Task #{task['number']}: `{task['updated_at']}` sha256 `{task['sha256']}`"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_bootstrap(
    *,
    project_state: dict[str, Any],
    project_state_source: Mapping[str, Any],
    expected_project_state_commit_sha: str,
    task_issues: Sequence[Mapping[str, Any]],
    expected_task_updated_at: Mapping[int, str],
    infrastructure_head: str,
    expected_infrastructure_head: str,
    infrastructure_repository: str = INFRA_REPOSITORY,
    infrastructure_ref: str = INFRA_REF,
) -> GeneratedBootstrap:
    """Compile deterministic `bootstrap/current.json` and `.md` bytes.

    The caller supplies current-source expectations observed independently from the
    candidate payload. Any stale/mismatched source fails closed. No wall clock,
    cache, environment, milestone open/closed state, or manual volatile override
    participates in generation.
    """
    if infrastructure_repository != INFRA_REPOSITORY or infrastructure_ref != INFRA_REF:
        raise GeneratedBootstrapError("infrastructure source identity is ambiguous or unsupported")
    infrastructure_head = _require_sha(infrastructure_head, field="infrastructure_head")
    expected_infrastructure_head = _require_sha(
        expected_infrastructure_head, field="expected_infrastructure_head"
    )
    if infrastructure_head != expected_infrastructure_head:
        raise GeneratedBootstrapError("infrastructure source head is stale")

    state = _validate_state(project_state)
    source = _validate_state_source(project_state_source, state)
    expected_state_commit = _require_sha(
        expected_project_state_commit_sha, field="expected_project_state_commit_sha"
    )
    if source["commit_sha"] != expected_state_commit:
        raise GeneratedBootstrapError("project state source commit is stale")

    task_sources = _validate_task_issues(
        task_issues,
        project_state=state,
        expected_task_updated_at=expected_task_updated_at,
    )

    ready_tasks = [
        {
            "issue": task["number"],
            "title": task["title"],
            "context": {"kind": "github_issue", "url": task["html_url"]},
            "source_revision": task["updated_at"],
        }
        for task in task_sources
        if task["state"] == "ready"
    ]

    data = {
        "generated_at": state["generated_at"],
        "sources": {
            "infrastructure": {
                "repo": INFRA_REPOSITORY,
                "ref": INFRA_REF,
                "sha": infrastructure_head,
            },
            "project_state": {
                **source,
                "schema": PROJECT_STATE_SCHEMA,
                "sha256": hashlib.sha256(_canonical_json_bytes(state)).hexdigest(),
            },
            "tasks": task_sources,
        },
        "infrastructure": {"head": infrastructure_head},
        "product": {
            "repo": state["product"]["repo"],
            "head": copy.deepcopy(state["product"]["head"]),
            "validated_checkpoints": {
                key: copy.deepcopy(state["product"][key])
                for key in (
                    "last_core_green",
                    "last_full_green",
                    "last_post_merge_green",
                    "last_live_evidenced",
                )
            },
        },
        "infrastructure_milestone": _milestone_status(task_sources),
        "ready_tasks": ready_tasks,
        "hard_invariants": _hard_invariants(infrastructure_head),
    }
    json_bytes = _display_json_bytes(data)
    markdown_bytes = _render_markdown(data)
    return GeneratedBootstrap(json_bytes=json_bytes, markdown_bytes=markdown_bytes)
