from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
AUTH_ORDER = [
    "authoritative_current_state",
    "authoritative_git_github_ci",
    "product_source",
    "knowledge_delta",
    "historical_ledger",
]
AUTH_CLASSES = [
    "authoritative_current_state",
    "authoritative_git_github_ci",
    "historical_ledger",
    "knowledge_delta",
    "product_source",
    "derived_task_context",
    "llm_semantic_output",
]
ACTIVE = {"ready", "claimed", "blocked"}
SCHEMAS = {
    "request": "task-context-request.v1.schema.json",
    "pack": "task-context-pack.v1.schema.json",
    "state": "project-state.v2.schema.json",
    "claim": "historical-claim.v1.schema.json",
    "conflicts": "historical-conflicts.v1.schema.json",
    "delta": "knowledge-delta.v1.schema.json",
}


class CompilationError(ValueError):
    pass


class OptionalSourceUnknown(LookupError):
    pass


class ExactSourceMismatch(CompilationError):
    pass


class SourceFetchError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


@dataclass(frozen=True)
class ExactBlob:
    content: bytes
    blob_sha: str | None = None


@dataclass(frozen=True)
class CompilationResult:
    pack: dict[str, Any]
    context_json: bytes
    artifact_name: str = "context.json"


class ExactSourceProvider(Protocol):
    def observe_head(self, repository: str) -> str: ...
    def fetch_issue(self, repository: str, issue_number: int) -> Mapping[str, Any]: ...
    def fetch_blob(self, repository: str, commit: str, path: str) -> ExactBlob: ...


def _schema(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "schemas" / SCHEMAS[name]).read_text(encoding="utf-8"))


def _validate(name: str, value: Any) -> None:
    Draft202012Validator(_schema(name), format_checker=FormatChecker()).validate(value)


def canonical_bytes(value: Any, trailing_lf: bool = False) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return raw + (b"\n" if trailing_lf else b"")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def issue_snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    value = copy.deepcopy(dict(snapshot)); value.pop("snapshot_sha256", None)
    return sha256(canonical_bytes(value))


def expected_request_id(request: Mapping[str, Any]) -> str:
    value = copy.deepcopy(dict(request)); value.pop("request_id", None)
    return "tcr1-" + sha256(canonical_bytes(value))


def request_digest(request: Mapping[str, Any]) -> str:
    return sha256(canonical_bytes(dict(request)))


def _suffix(key: str) -> int:
    return int(key.rsplit("-", 1)[1])


def _rank(source: Mapping[str, Any]) -> tuple[int, int, int, str]:
    return (0 if source["required"] else 1, AUTH_ORDER.index(source["authority_class"]), source["priority"], source["source_id"])


def longest_utf8_prefix(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    cut = raw[:max(limit, 0)]
    while cut:
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


def validate_request(request: Mapping[str, Any]) -> None:
    _validate("request", request); canonical_bytes(request)
    task, issue, fresh = request["task"], request["issue_snapshot"], request["freshness"]
    if task["issue_repository"] != issue["repository"] or task["issue_number"] != issue["issue_number"]:
        raise CompilationError("task/Issue mismatch")
    if _suffix(task["task_key"]) != task["issue_number"]:
        raise CompilationError("task key/Issue mismatch")
    if issue_snapshot_digest(issue) != issue["snapshot_sha256"]:
        raise CompilationError("Issue snapshot digest mismatch")
    if request["request_id"] != expected_request_id(request):
        raise CompilationError("request identity mismatch")
    if issue["labels"] != sorted(issue["labels"]) or issue["assignees"] != sorted(issue["assignees"]):
        raise CompilationError("Issue set ordering mismatch")
    if fresh["issue_snapshot_sha256"] != issue["snapshot_sha256"]:
        raise CompilationError("freshness Issue mismatch")
    if fresh["project_state_commit"] != request["project_state"]["commit"] or fresh["control_main_sha"] != request["project_state"]["commit"]:
        raise CompilationError("freshness project-state mismatch")
    if fresh["historical_ledger_commit"] != request["historical_ledger"]["commit"] or fresh["context_main_sha"] != request["historical_ledger"]["commit"]:
        raise CompilationError("freshness ledger mismatch")
    kd = request["knowledge_deltas"]["inputs"]
    if kd != sorted(kd, key=lambda x: (x["task_key"], x["path"], x["content_sha256"])):
        raise CompilationError("Knowledge Delta ordering mismatch")
    for item in kd:
        if _suffix(item["task_key"]) != item["task_id"] or item["path"] != f"knowledge-deltas/{item['task_key']}.json":
            raise CompilationError("Knowledge Delta identity mismatch")
    ps = request["product_sources"]["inputs"]
    if ps != sorted(ps, key=lambda x: x["source_id"]) or len({x["source_id"] for x in ps}) != len(ps):
        raise CompilationError("product source set mismatch")


def _issue_snapshot(raw: Mapping[str, Any], repo: str, number: int) -> dict[str, Any]:
    need = {"title", "body", "updated_at", "state", "state_reason", "labels", "assignees", "milestone_number"}
    if need - set(raw):
        raise CompilationError("Issue provider omitted required fields")
    labels, assignees = sorted(map(str, raw["labels"])), sorted(map(str, raw["assignees"]))
    active = sorted(ACTIVE.intersection(labels))
    if raw["state"] == "closed" and raw["state_reason"] == "completed" and not active:
        lifecycle = "completed"
    elif raw["state"] == "open" and raw["state_reason"] is None and len(active) == 1:
        lifecycle = active[0]
    else:
        raise CompilationError("noncanonical Issue lifecycle")
    out = {
        "repository": repo, "issue_number": number, "snapshot_sha256": "0" * 64,
        "updated_at": raw["updated_at"], "state": raw["state"], "state_reason": raw["state_reason"],
        "lifecycle": lifecycle, "title_sha256": sha256(str(raw["title"]).encode()),
        "body_sha256": sha256(str(raw["body"]).encode()), "labels": labels,
        "assignees": assignees, "milestone_number": raw["milestone_number"],
    }
    out["snapshot_sha256"] = issue_snapshot_digest(out)
    return out


_SECRET = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"), re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+"),
    re.compile(r"(?i)\bset-cookie\s*:\s*\S+"),
    re.compile(r"(?i)\b(?:password|api[_-]?key|access[_-]?token|refresh[_-]?token|session(?:id|_token)?|client[_-]?secret)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]


def _public(source_id: str, text: str) -> None:
    if any(p.search(text) for p in _SECRET):
        raise CompilationError(f"public-data policy violation in {source_id}")


def _text(source_id: str, data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        raise CompilationError(f"BOM forbidden in {source_id}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CompilationError(f"invalid UTF-8 in {source_id}") from exc



def _select(candidates: list[dict[str, Any]], budgets: Mapping[str, Any]) -> list[dict[str, Any]]:
    remaining_total = budgets["total_content_bytes"]
    remaining_class = dict(budgets["per_authority_bytes"])
    seen: dict[tuple[str, str, str], str] = {}
    out: list[dict[str, Any]] = []
    for src in sorted(candidates, key=_rank):
        if src.get("status") in {"unknown", "error"}:
            if src["required"]: raise CompilationError("required source unavailable")
            out.append(copy.deepcopy(src)); continue
        identity = (src["authority_class"], src["media_type"], src["_sha"])
        common = {k: copy.deepcopy(v) for k, v in src.items() if not k.startswith("_")}
        if identity in seen:
            common.update(status="omitted", original_byte_count=src["_bytes"], content_sha256=src["_sha"], omission_reason="deduplicated", duplicate_of=seen[identity])
            if src["required"]: raise CompilationError("required source deduplicated/omitted")
            out.append(common); continue
        seen[identity] = src["source_id"]
        allowance = min(budgets["per_source_max_bytes"], remaining_total, remaining_class[src["authority_class"]])
        if src["_bytes"] <= allowance:
            emitted, status = src["_content"], "included"
        elif src["truncation_allowed"]:
            emitted = longest_utf8_prefix(src["_content"], allowance); status = "truncated" if emitted else "omitted"
        else:
            emitted, status = "", "omitted"
        if status == "omitted":
            common.update(status="omitted", original_byte_count=src["_bytes"], content_sha256=src["_sha"], omission_reason="budget_exhausted")
            if src["required"]: raise CompilationError("required source omitted by budget")
            out.append(common); continue
        raw = emitted.encode("utf-8"); count = len(raw)
        remaining_total -= count; remaining_class[src["authority_class"]] -= count
        common.update(status=status, original_byte_count=src["_bytes"], emitted_byte_count=count, content_sha256=src["_sha"], emitted_sha256=sha256(raw), content=emitted)
        if status == "truncated": common["truncation"] = {"rule": "longest_valid_utf8_prefix", "limit_bytes": allowance}
        out.append(common)
    return out



AUTHORITY_ORDER = AUTH_ORDER
sha256_bytes = sha256
_derive_issue_snapshot = _issue_snapshot
longest_valid_utf8_prefix = longest_utf8_prefix
