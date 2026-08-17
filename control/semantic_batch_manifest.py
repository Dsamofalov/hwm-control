from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]

MANIFEST_SCHEMA = "hwm-semantic-batch-manifest/v1"
RESULT_SCHEMA = "hwm-semantic-batch-result/v1"
COVERAGE_SCHEMA = "hwm-semantic-coverage/v1"

SCHEMA_FILES = {
    "manifest": "semantic-batch-manifest.v1.schema.json",
    "result": "semantic-batch-result.v1.schema.json",
    "coverage": "semantic-coverage.v1.schema.json",
}

PUBLIC_DATA = {
    "policy": "hwm-public-data/v1",
    "classification": "public-disclosure-safe",
    "forbidden_categories": [
        "api_secrets_tokens",
        "cookies",
        "browser_profiles",
        "account_credentials",
        "private_keys",
        "session_state",
        "personal_data",
        "sensitive_raw_evidence",
        "secret_bearing_environment_or_config",
    ],
    "on_violation": "reject",
}

AUTHORITY_DENY_LIST = [
    "product_sha",
    "control_sha",
    "context_sha",
    "authoritative_project_state",
    "github_issue_lifecycle",
    "task_ownership",
    "task_readiness",
    "dependency_completion",
    "ci_status",
    "branch_protection_ruleset_state",
    "source_freshness",
    "provenance_acceptance",
    "deterministic_coverage_acceptance",
    "requirement_completion",
    "merge_authority",
]

AUTHORITY_BOUNDARY = {
    "classification": "derived_non_authoritative",
    "may_override": [],
    "denied_authorities": AUTHORITY_DENY_LIST,
}

_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+"),
    re.compile(r"(?i)\bset-cookie\s*:\s*\S+"),
    re.compile(
        r"(?i)\b(?:password|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"session(?:id|_token)?|client[_-]?secret)\s*[:=]\s*['\"]?[^\s'\"]{8,}"
    ),
]


class SemanticBatchError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _schema(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "schemas" / SCHEMA_FILES[name]).read_text(encoding="utf-8"))


def _validate_schema(name: str, value: Any) -> None:
    Draft202012Validator(_schema(name), format_checker=FormatChecker()).validate(value)


def _contains_forbidden_data(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _ensure_public(label: str, text: str) -> None:
    if _contains_forbidden_data(text):
        raise SemanticBatchError("PUBLIC_DATA_VIOLATION", f"hwm-public-data/v1 violation in {label}")


def _sorted_unique(values: Sequence[str]) -> bool:
    return list(values) == sorted(values) and len(values) == len(set(values))


def _source_identity_projection(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_type": source["source_type"],
        "repository": source["repository"],
        "commit": source["commit"],
        "path": source["path"],
        "blob_sha": source["blob_sha"],
        "content_sha256": source["content_sha256"],
        "media_type": source["media_type"],
    }


def stable_source_id(source: Mapping[str, Any]) -> str:
    return "src1-" + sha256_bytes(canonical_bytes(_source_identity_projection(source)))


def trigger_satisfied(trigger: Mapping[str, Any] | None) -> bool:
    if not isinstance(trigger, Mapping):
        return False
    kind = trigger.get("kind")
    if kind == "milestone_boundary":
        return bool(trigger.get("milestone")) and bool(trigger.get("boundary_id"))
    if kind == "unprocessed_kd_threshold":
        try:
            return (
                int(trigger["unprocessed_count"]) >= int(trigger["count_threshold"])
                or int(trigger["unprocessed_utf8_bytes"]) >= int(trigger["byte_threshold"])
            )
        except (KeyError, TypeError, ValueError):
            return False
    if kind == "task_context_budget_need":
        try:
            return int(trigger["required_utf8_bytes"]) > int(trigger["budget_utf8_bytes"])
        except (KeyError, TypeError, ValueError):
            return False
    if kind == "knowledge_health_signal":
        return (
            trigger.get("status") in {"degraded", "coverage_gap"}
            and isinstance(trigger.get("affected_count"), int)
            and not isinstance(trigger.get("affected_count"), bool)
            and trigger["affected_count"] > 0
        )
    return False


def _normalize_source(readback: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "source_type", "repository", "commit", "path", "blob_sha", "content",
        "media_type", "authority_class", "epistemic_status",
    }
    missing = sorted(required - set(readback))
    if missing:
        raise SemanticBatchError("SOURCE_INVALID", f"source readback missing fields: {missing}")
    content = readback["content"]
    if not isinstance(content, str):
        raise SemanticBatchError("SOURCE_INVALID", "source content must be text")
    raw = content.encode("utf-8")
    _ensure_public(str(readback.get("path", "<source>")), content)
    observed_blob = git_blob_sha(raw)
    if observed_blob != readback["blob_sha"]:
        raise SemanticBatchError(
            "SOURCE_BLOB_MISMATCH",
            f"source Git blob mismatch: {readback.get('repository')}:{readback.get('path')}",
        )
    observed_sha256 = sha256_bytes(raw)
    declared_sha256 = readback.get("content_sha256")
    if declared_sha256 is not None and declared_sha256 != observed_sha256:
        raise SemanticBatchError(
            "SOURCE_DIGEST_MISMATCH",
            f"source content SHA-256 mismatch: {readback.get('repository')}:{readback.get('path')}",
        )
    entry = {
        "source_type": readback["source_type"],
        "repository": readback["repository"],
        "commit": readback["commit"],
        "path": readback["path"],
        "blob_sha": readback["blob_sha"],
        "content_sha256": observed_sha256,
        "content_utf8_bytes": len(raw),
        "media_type": readback["media_type"],
        "authority_class": readback["authority_class"],
        "epistemic_status": readback["epistemic_status"],
        "conflict_ids": sorted(readback.get("conflict_ids", [])),
        "supersedes_source_ids": sorted(readback.get("supersedes_source_ids", [])),
        "superseded_by_source_ids": sorted(readback.get("superseded_by_source_ids", [])),
        "knowledge_delta_task_key": readback.get("knowledge_delta_task_key"),
        "public_data": copy.deepcopy(PUBLIC_DATA),
    }
    entry["source_id"] = stable_source_id(entry)
    supplied = readback.get("source_id")
    if supplied is not None and supplied != entry["source_id"]:
        raise SemanticBatchError("SOURCE_ID_MISMATCH", "supplied source_id is not stable identity")
    return entry


def _historical_semantics(
    sources: Sequence[Mapping[str, Any]], conflicts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    source_ids = {source["source_id"] for source in sources}
    normalized_conflicts = []
    seen_conflicts: set[str] = set()
    for item in sorted(conflicts, key=lambda row: row["conflict_id"]):
        conflict_id = item["conflict_id"]
        members = sorted(item["source_ids"])
        if conflict_id in seen_conflicts or len(members) < 2 or len(members) != len(set(members)):
            raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "invalid conflict group")
        if not set(members).issubset(source_ids):
            raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "conflict references unknown source")
        normalized_conflicts.append({"conflict_id": conflict_id, "source_ids": members, "status": "unresolved"})
        seen_conflicts.add(conflict_id)
    membership: dict[str, set[str]] = {sid: set() for sid in source_ids}
    for group in normalized_conflicts:
        for sid in group["source_ids"]:
            membership[sid].add(group["conflict_id"])
    for source in sources:
        if set(source["conflict_ids"]) != membership[source["source_id"]]:
            raise SemanticBatchError(
                "HISTORICAL_SEMANTICS_MISMATCH",
                f"conflict membership mismatch for {source['source_id']}",
            )
    by_id = {source["source_id"]: source for source in sources}
    edges: list[dict[str, str]] = []
    for source in sources:
        for old_id in source["supersedes_source_ids"]:
            if old_id not in source_ids or old_id == source["source_id"]:
                raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "invalid supersession target")
            old = by_id[old_id]
            if source["source_id"] not in old["superseded_by_source_ids"]:
                raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "supersession relation must be reciprocal")
            edges.append({
                "source_id": old_id,
                "superseded_by_source_id": source["source_id"],
                "relation": "superseded",
            })
    for source in sources:
        for new_id in source["superseded_by_source_ids"]:
            if new_id not in source_ids or source["source_id"] not in by_id[new_id]["supersedes_source_ids"]:
                raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "superseded_by relation must be reciprocal")
    edges.sort(key=lambda row: (row["source_id"], row["superseded_by_source_id"]))
    if len(edges) != len({(e["source_id"], e["superseded_by_source_id"]) for e in edges}):
        raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "duplicate supersession edge")
    return {"conflicts": normalized_conflicts, "supersessions": edges, "silent_winner_selection": False}


def _partition_projection(
    source_ids: Sequence[str], sources_by_id: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "sources": [
            {
                "source_id": source_id,
                "content_sha256": sources_by_id[source_id]["content_sha256"],
                "content_utf8_bytes": sources_by_id[source_id]["content_utf8_bytes"],
            }
            for source_id in source_ids
        ]
    }


def _build_partitions(
    sources: Sequence[Mapping[str, Any]], max_partition_utf8_bytes: int
) -> list[dict[str, Any]]:
    if (
        not isinstance(max_partition_utf8_bytes, int)
        or isinstance(max_partition_utf8_bytes, bool)
        or max_partition_utf8_bytes < 1
        or max_partition_utf8_bytes > 1_000_000
    ):
        raise SemanticBatchError("PARTITION_INVALID", "invalid partition byte limit")
    by_id = {source["source_id"]: source for source in sources}
    groups: list[list[str]] = []
    current: list[str] = []
    current_bytes = 0
    for source in sources:
        size = source["content_utf8_bytes"]
        if size > max_partition_utf8_bytes:
            raise SemanticBatchError(
                "PARTITION_SOURCE_OVERSIZE",
                f"single source exceeds deterministic partition limit: {source['source_id']}",
            )
        if current and current_bytes + size > max_partition_utf8_bytes:
            groups.append(current)
            current = []
            current_bytes = 0
        current.append(source["source_id"])
        current_bytes += size
    if current:
        groups.append(current)
    partitions: list[dict[str, Any]] = []
    for group in groups:
        projection = _partition_projection(group, by_id)
        digest = sha256_bytes(canonical_bytes(projection))
        partitions.append({
            "partition_id": "smp1-" + digest,
            "partition_sha256": digest,
            "source_ids": group,
            "input_utf8_bytes": sum(by_id[source_id]["content_utf8_bytes"] for source_id in group),
        })
    return partitions


def _manifest_identity_projection(manifest: Mapping[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(manifest))
    candidate.pop("batch_id", None)
    candidate.pop("manifest_sha256", None)
    return candidate


def expected_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(_manifest_identity_projection(manifest)))


def generate_manifest(
    *,
    exact_heads: Mapping[str, Mapping[str, str]],
    source_readbacks: Sequence[Mapping[str, Any]],
    conflicts: Sequence[Mapping[str, Any]] = (),
    trigger: Mapping[str, Any],
    max_partition_utf8_bytes: int,
) -> dict[str, Any]:
    if not trigger_satisfied(trigger):
        raise SemanticBatchError("NO_TRIGGER", "no architecture-authorized semantic maintenance signal")
    sources = [_normalize_source(item) for item in source_readbacks]
    sources.sort(key=lambda item: item["source_id"])
    source_ids = [item["source_id"] for item in sources]
    if len(source_ids) != len(set(source_ids)):
        raise SemanticBatchError("SOURCE_DUPLICATE", "duplicate exact semantic source identity")
    for source in sources:
        key = source["knowledge_delta_task_key"]
        if key is not None and (
            source["authority_class"] != "knowledge_delta" or source["source_type"] != "knowledge_delta"
        ):
            raise SemanticBatchError(
                "KNOWLEDGE_DELTA_FRONTIER_INVALID",
                "Knowledge Delta frontier entries must be typed knowledge_delta sources",
            )
        if source["authority_class"] == "knowledge_delta" and key is None:
            raise SemanticBatchError("KNOWLEDGE_DELTA_FRONTIER_INVALID", "knowledge_delta source requires exact task key")
    historical = _historical_semantics(sources, conflicts)
    frontier = [
        {
            "task_key": source["knowledge_delta_task_key"],
            "source_id": source["source_id"],
            "content_sha256": source["content_sha256"],
        }
        for source in sources
        if source["knowledge_delta_task_key"] is not None
    ]
    frontier.sort(key=lambda item: (item["task_key"], item["source_id"]))
    partitions = _build_partitions(sources, max_partition_utf8_bytes)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "batch_id": "smb1-" + "0" * 64,
        "manifest_sha256": "0" * 64,
        "exact_heads": copy.deepcopy(dict(exact_heads)),
        "trigger": copy.deepcopy(dict(trigger)),
        "sources": sources,
        "knowledge_delta_frontier": frontier,
        "historical_semantics": historical,
        "output_schemas": [RESULT_SCHEMA, COVERAGE_SCHEMA],
        "partition_plan": {
            "max_partition_utf8_bytes": max_partition_utf8_bytes,
            "partitions": partitions,
        },
        "required_coverage_set": source_ids,
        "acceptance_policy": {
            "complete_typed_coverage": True,
            "partition_exact_union": True,
            "source_as_untrusted_data": True,
            "new_material_after_freeze": "later_batch",
            "semantic_authority": "derived_non_authoritative",
            "unknown_unverified_preserved": True,
        },
        "public_data": copy.deepcopy(PUBLIC_DATA),
    }
    digest = expected_manifest_sha256(manifest)
    manifest["manifest_sha256"] = digest
    manifest["batch_id"] = "smb1-" + digest
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise SemanticBatchError("UNSUPPORTED_SCHEMA_VERSION", "unsupported semantic batch manifest schema")
    try:
        _validate_schema("manifest", manifest)
        canonical_bytes(manifest)
    except (ValidationError, TypeError, ValueError) as exc:
        raise SemanticBatchError("SCHEMA_INVALID", f"semantic batch manifest invalid: {exc}") from exc
    digest = expected_manifest_sha256(manifest)
    if manifest["manifest_sha256"] != digest or manifest["batch_id"] != "smb1-" + digest:
        raise SemanticBatchError("MANIFEST_IDENTITY_MISMATCH", "batch id/digest mismatch")
    sources = list(manifest["sources"])
    source_ids = [source["source_id"] for source in sources]
    if not _sorted_unique(source_ids):
        raise SemanticBatchError("SOURCE_ORDER_MISMATCH", "manifest sources must be source_id-sorted and unique")
    for source in sources:
        if source["source_id"] != stable_source_id(source):
            raise SemanticBatchError("SOURCE_ID_MISMATCH", "manifest source_id does not bind exact source")
        if not _sorted_unique(source["conflict_ids"]):
            raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "source conflict ids must be sorted")
        if not _sorted_unique(source["supersedes_source_ids"]) or not _sorted_unique(source["superseded_by_source_ids"]):
            raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "supersession ids must be sorted")
    expected_historical = _historical_semantics(sources, manifest["historical_semantics"]["conflicts"])
    if manifest["historical_semantics"] != expected_historical:
        raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "historical semantics not canonical")
    expected_frontier = [
        {
            "task_key": source["knowledge_delta_task_key"],
            "source_id": source["source_id"],
            "content_sha256": source["content_sha256"],
        }
        for source in sources
        if source["knowledge_delta_task_key"] is not None
    ]
    expected_frontier.sort(key=lambda item: (item["task_key"], item["source_id"]))
    if manifest["knowledge_delta_frontier"] != expected_frontier:
        raise SemanticBatchError("KNOWLEDGE_DELTA_FRONTIER_INVALID", "Knowledge Delta frontier mismatch")
    if manifest["required_coverage_set"] != source_ids:
        raise SemanticBatchError("COVERAGE_SET_MISMATCH", "required coverage set must equal exact ordered sources")
    expected_partitions = _build_partitions(sources, manifest["partition_plan"]["max_partition_utf8_bytes"])
    if manifest["partition_plan"]["partitions"] != expected_partitions:
        raise SemanticBatchError("PARTITION_MISMATCH", "partition plan is not deterministic exact partitioning")


def validate_source_readbacks(
    manifest: Mapping[str, Any], source_readbacks: Sequence[Mapping[str, Any]]
) -> None:
    validate_manifest(manifest)
    normalized = [_normalize_source(item) for item in source_readbacks]
    normalized.sort(key=lambda item: item["source_id"])
    expected = list(manifest["sources"])
    if [item["source_id"] for item in normalized] != [item["source_id"] for item in expected]:
        raise SemanticBatchError(
            "SOURCE_EXISTENCE_MISMATCH",
            "source readback set has missing, extra, or substituted source identity",
        )
    for observed, declared in zip(normalized, expected):
        if observed != declared:
            raise SemanticBatchError(
                "SOURCE_PROVENANCE_MISMATCH",
                f"exact source readback mismatch: {declared['source_id']}",
            )


def classify_replay(existing: Mapping[str, Any], candidate: Mapping[str, Any], *, kind: str) -> str:
    if kind == "manifest":
        validate_manifest(existing)
        validate_manifest(candidate)
        identity = "batch_id"
    elif kind == "coverage":
        identity = "coverage_id"
    elif kind == "result":
        identity = "result_id"
    else:
        raise SemanticBatchError("REPLAY_INVALID", "unknown replay artifact kind")
    if existing.get(identity) != candidate.get(identity):
        return "different_identity"
    if canonical_bytes(existing) != canonical_bytes(candidate):
        raise SemanticBatchError("IDENTITY_COLLISION", f"same {identity} with different canonical bytes")
    return "idempotent_replay"
