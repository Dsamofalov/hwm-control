import copy
import hashlib
import json
import math
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
ROOT = Path(__file__).resolve().parents[2]
REQ_SCHEMA = json.loads((ROOT / "schemas" / "task-context-request.v1.schema.json").read_text(encoding="utf-8"))
PACK_SCHEMA = json.loads((ROOT / "schemas" / "task-context-pack.v1.schema.json").read_text(encoding="utf-8"))
FC = FormatChecker()
SHA_A = "0123456789abcdef0123456789abcdef01234567"
SHA_B = "89abcdef0123456789abcdef0123456789abcdef"
SHA_C = "1111111111111111111111111111111111111111"
SHA_D = "2222222222222222222222222222222222222222"
H_A = "a" * 64
H_B = "b" * 64
H_C = "c" * 64
AUTH_ORDER = [
    "authoritative_current_state",
    "authoritative_git_github_ci",
    "product_source",
    "knowledge_delta",
    "historical_ledger",
]
EXISTING_SCHEMA_BLOBS = {
    "claim.v1.schema.json": "8175cde74663a21b04f34ab7a0ef564e2f72728a",
    "historical-claim.v1.schema.json": "760ec13321ee48378d23b5b00dbf141f642c6696",
    "historical-conflicts.v1.schema.json": "1b7222f43f1cdfdd6a8649074de053ceee6b2ee0",
    "historical-ledger-publish-request.v1.schema.json": "f92ce12c09f0e7a3d8892a5d29688d7f36942eab",
    "historical-ledger-publish-result.v1.schema.json": "02a4b93c9dfbe4c2c8c205903d3a914aa96d5400",
    "job.v1.schema.json": "787d029d1b0ab3513c3af2ecc10cd32a192a5f7a",
    "knowledge-delta.v1.schema.json": "fb10f7b0abbf43a3ddb427614017a3edca4aeea3",
    "project-state.v1.schema.json": "4f965686d95262fc463f2678527c33cfe336a666",
    "project-state.v2.schema.json": "c0a0c7ec79cebf099e2932e2769ebd856cf0210a",
    "publish-request.bootstrap-v1.schema.json": "34a6724c7064864f48a214a94f9006da8e4944eb",
    "publish-result.bootstrap-v1.schema.json": "ee952b5f3a1a2e0a71dbe4d647539f645ab416d9",
    "result.v1.schema.json": "317b00d4de5c036fc6ee4e26b8422239c8bf362e",
    "task.v1.schema.json": "279ca806550758375ee1ec46c99edb41261c3ab4",
}
class ContractError(ValueError):
    pass
def canonical_bytes(value, *, trailing_lf=False):
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return raw + (b"\n" if trailing_lf else b"")
def git_blob_sha(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()
def sha256(data):
    return hashlib.sha256(data).hexdigest()
def issue_snapshot_digest(snapshot):
    identity = copy.deepcopy(snapshot)
    identity.pop("snapshot_sha256", None)
    return sha256(canonical_bytes(identity))
def bind_request_id(request):
    identity = copy.deepcopy(request)
    identity.pop("request_id", None)
    digest = sha256(canonical_bytes(identity))
    request["request_id"] = "tcr1-" + digest
    return digest
def task_suffix(task_key):
    return int(task_key.rsplit("-", 1)[1])
def source_rank(source):
    return (
        0 if source["required"] else 1,
        AUTH_ORDER.index(source["authority_class"]),
        source["priority"],
        source["source_id"],
    )
def longest_utf8_prefix(text, limit):
    if limit <= 0:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    cut = raw[:limit]
    while cut:
        try:
            return cut.decode("utf-8")
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""
def select_for_budget(candidates, budgets):
    """Executable vector for the contract algorithm; this is not compiler runtime."""
    ordered = sorted(candidates, key=source_rank)
    class_remaining = dict(budgets["per_authority_bytes"])
    total_remaining = budgets["total_content_bytes"]
    seen = {}
    out = []
    for candidate in ordered:
        raw = candidate["content"].encode("utf-8")
        digest = sha256(raw)
        dedup = (candidate["authority_class"], candidate["media_type"], digest)
        if dedup in seen:
            out.append((candidate["source_id"], "omitted", 0, "deduplicated", seen[dedup]))
            continue
        seen[dedup] = candidate["source_id"]
        allowance = min(
            budgets["per_source_max_bytes"],
            class_remaining[candidate["authority_class"]],
            total_remaining,
        )
        if allowance <= 0:
            out.append((candidate["source_id"], "omitted", 0, "budget_exhausted", None))
            continue
        if len(raw) <= allowance:
            emitted = candidate["content"]
            status = "included"
        elif candidate["truncation_allowed"]:
            emitted = longest_utf8_prefix(candidate["content"], allowance)
            status = "truncated" if emitted else "omitted"
        else:
            emitted = ""
            status = "omitted"
        count = len(emitted.encode("utf-8"))
        if count == 0 and status == "omitted":
            out.append((candidate["source_id"], status, 0, "budget_exhausted", None))
            continue
        total_remaining -= count
        class_remaining[candidate["authority_class"]] -= count
        out.append((candidate["source_id"], status, count, None, None))
    return out
def validate_schema(schema, value):
    Draft202012Validator(schema, format_checker=FC).validate(value)
def validate_request_semantics(request):
    validate_schema(REQ_SCHEMA, request)
    if request["task"]["issue_repository"] != request["issue_snapshot"]["repository"]:
        raise ContractError("task/Issue repository mismatch")
    if request["task"]["issue_number"] != request["issue_snapshot"]["issue_number"]:
        raise ContractError("task/Issue number mismatch")
    if task_suffix(request["task"]["task_key"]) != request["task"]["issue_number"]:
        raise ContractError("task key does not encode Issue number")
    if issue_snapshot_digest(request["issue_snapshot"]) != request["issue_snapshot"]["snapshot_sha256"]:
        raise ContractError("Issue snapshot digest mismatch")
    identity = copy.deepcopy(request)
    supplied = identity.pop("request_id")
    if supplied != "tcr1-" + sha256(canonical_bytes(identity)):
        raise ContractError("request identity mismatch")
    if request["freshness"]["issue_snapshot_sha256"] != request["issue_snapshot"]["snapshot_sha256"]:
        raise ContractError("freshness Issue binding mismatch")
    if request["freshness"]["project_state_commit"] != request["project_state"]["commit"]:
        raise ContractError("freshness project-state binding mismatch")
    if request["freshness"]["historical_ledger_commit"] != request["historical_ledger"]["commit"]:
        raise ContractError("freshness ledger binding mismatch")
    if request["historical_ledger"]["commit"] != request["freshness"]["context_main_sha"]:
        raise ContractError("ledger must be bound to requested exact context main")
    if request["project_state"]["commit"] != request["freshness"]["control_main_sha"]:
        raise ContractError("project state must be bound to requested exact control main")
    labels = request["issue_snapshot"]["labels"]
    assignees = request["issue_snapshot"]["assignees"]
    if labels != sorted(labels) or assignees != sorted(assignees):
        raise ContractError("set-like Issue fields are not canonical")
    kd = request["knowledge_deltas"]["inputs"]
    if kd != sorted(kd, key=lambda x: (x["task_key"], x["path"], x["content_sha256"])):
        raise ContractError("Knowledge Delta inputs are not canonical")
    for item in kd:
        if task_suffix(item["task_key"]) != item["task_id"]:
            raise ContractError("Knowledge Delta task identity mismatch")
        if item["path"] != f"knowledge-deltas/{item['task_key']}.json":
            raise ContractError("Knowledge Delta path identity mismatch")
    ps = request["product_sources"]["inputs"]
    if ps != sorted(ps, key=lambda x: x["source_id"]):
        raise ContractError("product source inputs are not canonical")
    if len({x["source_id"] for x in ps}) != len(ps):
        raise ContractError("duplicate product source identity")
def validate_pack_semantics(request, pack):
    validate_request_semantics(request)
    validate_schema(PACK_SCHEMA, pack)
    expected_request_sha = sha256(canonical_bytes(request))
    if pack["request_binding"] != {
        "request_id": request["request_id"],
        "request_sha256": expected_request_sha,
    }:
        raise ContractError("pack request binding mismatch")
    for name in ("task", "issue_snapshot", "product", "project_state", "historical_ledger", "knowledge_deltas", "public_data"):
        if pack[name] != request[name]:
            raise ContractError(f"pack {name} differs from request binding")
    checks = pack["freshness"]["checks"]
    if any(item["expected"] != item["observed"] for item in checks):
        raise ContractError("stale freshness proof")
    required_checks = {
        ("control.main", request["freshness"]["control_main_sha"]),
        ("context.main", request["freshness"]["context_main_sha"]),
        ("issue.snapshot", request["issue_snapshot"]["snapshot_sha256"]),
        ("project.state", request["project_state"]["commit"]),
        ("historical.ledger", request["historical_ledger"]["commit"]),
    }
    if {(x["source_id"], x["expected"]) for x in checks} != required_checks:
        raise ContractError("freshness proof does not cover exact required bindings")
    if pack["sources"] != sorted(pack["sources"], key=source_rank):
        raise ContractError("pack source ordering mismatch")
    by_id = {item["source_id"]: item for item in pack["sources"]}
    for item in pack["sources"]:
        if item["required"] and item["status"] in {"omitted", "unknown", "error"}:
            raise ContractError("required source is unavailable")
        if item["status"] == "truncated" and not item["truncation_allowed"]:
            raise ContractError("source truncated without permission")
        if item["status"] in {"included", "truncated"}:
            emitted = item["content"].encode("utf-8")
            if len(emitted) != item["emitted_byte_count"]:
                raise ContractError("emitted byte count mismatch")
            if sha256(emitted) != item["emitted_sha256"]:
                raise ContractError("emitted digest mismatch")
            if item["status"] == "included" and item["emitted_byte_count"] != item["original_byte_count"]:
                raise ContractError("included item byte count mismatch")
        if item["status"] == "omitted" and item["omission_reason"] == "deduplicated":
            target = by_id.get(item["duplicate_of"])
            if target is None or source_rank(target) >= source_rank(item):
                raise ContractError("dedup target is not the earlier stable winner")
    emitted = sum(item.get("emitted_byte_count", 0) for item in pack["sources"])
    if emitted != pack["selection"]["emitted_content_bytes"]:
        raise ContractError("selection emitted-byte accounting mismatch")
    if emitted > request["selection"]["budgets"]["total_content_bytes"]:
        raise ContractError("total budget exceeded")
    for authority in AUTH_ORDER:
        used = sum(
            item.get("emitted_byte_count", 0)
            for item in pack["sources"]
            if item["authority_class"] == authority
        )
        if used > request["selection"]["budgets"]["per_authority_bytes"][authority]:
            raise ContractError("authority budget exceeded")
    if any(item.get("emitted_byte_count", 0) > request["selection"]["budgets"]["per_source_max_bytes"] for item in pack["sources"]):
        raise ContractError("per-source budget exceeded")
    if pack["serialization"]["context_markdown"] != "not_defined_in_v1":
        raise ContractError("Markdown projection is not a v1 artifact")
