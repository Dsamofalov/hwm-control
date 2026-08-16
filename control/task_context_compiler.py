from __future__ import annotations

import copy
import json
from typing import Any, Mapping

from .task_context_core import (
    AUTH_CLASSES, CompilationError, CompilationResult, ExactBlob, ExactSourceMismatch,
    ExactSourceProvider, OptionalSourceUnknown, SourceFetchError, _issue_snapshot,
    _public, _select, _text, _validate, canonical_bytes, request_digest, sha256,
    validate_request, git_blob_sha,
)

def _fetch(provider: ExactSourceProvider, source_id: str, binding: Mapping[str, Any], *, repo: str | None = None, commit: str | None = None, required: bool = True) -> ExactBlob:
    repository, revision = repo or binding["repository"], commit or binding["commit"]
    try:
        blob = provider.fetch_blob(repository, revision, binding["path"])
    except OptionalSourceUnknown:
        if required: raise CompilationError(f"required exact source unknown: {source_id}")
        raise
    except SourceFetchError:
        if required: raise CompilationError(f"required source retrieval failed: {source_id}")
        raise
    actual_blob, actual_digest = git_blob_sha(blob.content), sha256(blob.content)
    if blob.blob_sha is not None and blob.blob_sha != actual_blob:
        raise ExactSourceMismatch(f"provider blob identity mismatch: {source_id}")
    if actual_blob != binding["blob_sha"] or actual_digest != binding["content_sha256"]:
        raise ExactSourceMismatch(f"exact source digest mismatch: {source_id}")
    return blob


def _validate_payloads(kind: str, text: str, task_id: int | None = None) -> None:
    if kind == "state":
        _validate("state", json.loads(text)); return
    if kind == "conflicts":
        _validate("conflicts", json.loads(text)); return
    if kind == "delta":
        value = json.loads(text); _validate("delta", value)
        if value["task_id"] != task_id: raise CompilationError("Knowledge Delta task mismatch")
        return
    if kind == "claims":
        for line in text.splitlines():
            if line.strip(): _validate("claim", json.loads(line))


def _prov(repo: str, commit: str, binding: Mapping[str, Any]) -> dict[str, Any]:
    return {"kind": "git_blob", "repository": repo, "commit": commit, "path": binding["path"], "blob_sha": binding["blob_sha"], "content_sha256": binding["content_sha256"]}


def _resolved(source_id: str, authority: str, media: str, priority: int, required: bool, truncate: bool, provenance: Mapping[str, Any], content: str) -> dict[str, Any]:
    raw = content.encode("utf-8")
    return {"source_id": source_id, "authority_class": authority, "media_type": media, "priority": priority, "required": required,
            "truncation_allowed": truncate, "provenance": dict(provenance), "_content": content, "_bytes": len(raw), "_sha": sha256(raw)}


def _unavailable(binding: Mapping[str, Any], provenance: Mapping[str, Any], status: str, detail: Any) -> dict[str, Any]:
    out = {"source_id": binding["source_id"], "authority_class": "product_source", "media_type": binding["media_type"], "priority": binding["priority"],
           "required": binding["required"], "truncation_allowed": binding["truncation_allowed"], "provenance": dict(provenance), "status": status}
    out["reason" if status == "unknown" else "error"] = detail
    return out



def compile_task_context(request: Mapping[str, Any], provider: ExactSourceProvider) -> CompilationResult:
    request = copy.deepcopy(dict(request)); validate_request(request)
    fresh, product = request["freshness"], request["product"]
    control_head, context_head = provider.observe_head(request["project_state"]["repository"]), provider.observe_head(request["historical_ledger"]["repository"])
    if control_head != fresh["control_main_sha"] or context_head != fresh["context_main_sha"]:
        if control_head != fresh["control_main_sha"]:
            raise CompilationError("control main freshness mismatch")
        raise CompilationError("context main freshness mismatch")
    if product["head_policy"] == "must_equal_current":
        observed = provider.observe_head(product["repository"])
        if observed != product["expected_current_head"] or observed != product["commit"]: raise CompilationError("product current HEAD mismatch")

    raw_issue = provider.fetch_issue(request["task"]["issue_repository"], request["task"]["issue_number"])
    issue = _issue_snapshot(raw_issue, request["task"]["issue_repository"], request["task"]["issue_number"])
    if issue != request["issue_snapshot"]: raise CompilationError("Issue snapshot stale or mismatched")
    _public("issue.title", str(raw_issue["title"])); _public("issue.body", str(raw_issue["body"]))
    issue_content = canonical_bytes({"body": str(raw_issue["body"]), "title": str(raw_issue["title"])}).decode()
    candidates = [_resolved("issue.content", "authoritative_git_github_ci", "application/json", 0, True, False,
                            {"kind": "github_issue", "repository": issue["repository"], "issue_number": issue["issue_number"], "snapshot_sha256": issue["snapshot_sha256"]}, issue_content)]

    state = request["project_state"]; blob = _fetch(provider, "project.state", state); text = _text("project.state", blob.content); _public("project.state", text); _validate_payloads("state", text)
    candidates.append(_resolved("project.state", "authoritative_current_state", "application/json", 0, True, False, _prov(state["repository"], state["commit"], state), text))

    ledger = request["historical_ledger"]
    for key, source_id, media, priority, kind in (("claims", "historical.claims", "text/plain", 0, "claims"), ("conflicts", "historical.conflicts", "application/json", 1, "conflicts")):
        binding = ledger[key]; blob = _fetch(provider, source_id, binding, repo=ledger["repository"], commit=ledger["commit"]); text = _text(source_id, blob.content); _public(source_id, text); _validate_payloads(kind, text)
        candidates.append(_resolved(source_id, "historical_ledger", media, priority, True, False, _prov(ledger["repository"], ledger["commit"], binding), text))

    for priority, binding in enumerate(request["knowledge_deltas"]["inputs"]):
        source_id = "knowledge." + binding["task_key"].lower(); blob = _fetch(provider, source_id, binding); text = _text(source_id, blob.content); _public(source_id, text); _validate_payloads("delta", text, binding["task_id"])
        candidates.append(_resolved(source_id, "knowledge_delta", "application/json", priority, True, False, _prov(binding["repository"], binding["commit"], binding), text))

    for binding in request["product_sources"]["inputs"]:
        provenance = _prov(product["repository"], product["commit"], binding)
        try:
            blob = _fetch(provider, binding["source_id"], binding, repo=product["repository"], commit=product["commit"], required=binding["required"])
            text = _text(binding["source_id"], blob.content); _public(binding["source_id"], text)
            candidates.append(_resolved(binding["source_id"], "product_source", binding["media_type"], binding["priority"], binding["required"], binding["truncation_allowed"], provenance, text))
        except OptionalSourceUnknown as exc:
            candidates.append(_unavailable(binding, provenance, "unknown", str(exc) or "Optional exact source unavailable."))
        except ExactSourceMismatch as exc:
            if binding["required"]: raise
            candidates.append(_unavailable(binding, provenance, "error", {"code": "SOURCE_VALIDATION_ERROR", "message": str(exc), "retryable": False}))
        except SourceFetchError as exc:
            candidates.append(_unavailable(binding, provenance, "error", {"code": exc.code, "message": exc.message, "retryable": exc.retryable}))

    sources = _select(candidates, request["selection"]["budgets"])
    selection = copy.deepcopy(request["selection"])
    selection.update(candidate_count=len(sources), unique_candidate_count=len(sources) - sum(x.get("omission_reason") == "deduplicated" for x in sources),
                     emitted_source_count=sum(x["status"] in {"included", "truncated"} for x in sources), emitted_content_bytes=sum(x.get("emitted_byte_count", 0) for x in sources))
    checks = [
        {"source_id": "control.main", "expected": fresh["control_main_sha"], "observed": control_head, "status": "match"},
        {"source_id": "context.main", "expected": fresh["context_main_sha"], "observed": context_head, "status": "match"},
        {"source_id": "historical.ledger", "expected": ledger["commit"], "observed": context_head, "status": "match"},
        {"source_id": "issue.snapshot", "expected": issue["snapshot_sha256"], "observed": issue["snapshot_sha256"], "status": "match"},
        {"source_id": "project.state", "expected": state["commit"], "observed": control_head, "status": "match"},
    ]
    pack = {
        "schema": "hwm-task-context-pack/v1", "request_binding": {"request_id": request["request_id"], "request_sha256": request_digest(request)},
        "task": copy.deepcopy(request["task"]), "issue_snapshot": copy.deepcopy(request["issue_snapshot"]), "product": copy.deepcopy(product),
        "project_state": copy.deepcopy(state), "historical_ledger": copy.deepcopy(ledger), "knowledge_deltas": copy.deepcopy(request["knowledge_deltas"]),
        "authority_model": {"classes": AUTH_CLASSES, "current_state_is_authoritative": True, "historical_is_not_current_state": True, "derived_context_is_not_authority": True, "llm_is_not_deterministic_authority": True},
        "selection": selection, "freshness": {"policy": "hwm-exact-bound-freshness/v1", "status": "fresh", "checks": checks, "on_mismatch": "reject", "no_implicit_head_substitution": True},
        "sources": sources, "public_data": copy.deepcopy(request["public_data"]),
        "serialization": {"profile": "hwm-canonical-json/v1", "artifact": "context.json", "encoding": "UTF-8", "bom": False,
                          "object_key_order": "lexicographic_unicode_codepoint", "separators": "comma_colon_no_whitespace", "trailing_lf": True,
                          "unicode_normalization": "none", "non_finite_numbers": "reject", "compiler_controlled_array_order": "contract_defined", "context_markdown": "not_defined_in_v1"},
    }
    _validate("pack", pack); rendered = canonical_bytes(pack, trailing_lf=True)
    if rendered.startswith(b"\xef\xbb\xbf") or not rendered.endswith(b"\n") or rendered.endswith(b"\n\n"): raise CompilationError("canonical context.json invariant failure")
    return CompilationResult(pack, rendered)

# Contract-facing helper names.
from .task_context_core import (  # noqa: E402,F401
    AUTHORITY_ORDER, canonical_bytes, expected_request_id, git_blob_sha,
    longest_valid_utf8_prefix, sha256_bytes, _derive_issue_snapshot,
)

def _select_sources(candidates, budgets):
    normalized = []
    for item in candidates:
        if "_content" in item or item.get("status") in {"unknown", "error"}:
            normalized.append(copy.deepcopy(item)); continue
        content = item["content"]; raw = content.encode("utf-8")
        value = copy.deepcopy(item); value.pop("content", None)
        value.update(_content=content, _bytes=len(raw), _sha=sha256(raw))
        normalized.append(value)
    return _select(normalized, budgets)
