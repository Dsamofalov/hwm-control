from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from control.semantic_batch_manifest import (
    PUBLIC_DATA,
    SemanticBatchError,
    canonical_bytes,
    generate_manifest,
    git_blob_sha,
    sha256_bytes,
    stable_source_id,
)

ROOT = Path(__file__).resolve().parents[1]
INPUT_CONFIG_SCHEMA = "hwm-semantic-batch-input-config/v1"
INPUT_CONFIG_PATH = ROOT / "semantic-batch-inputs" / "I09-0067-first.json"
INPUT_CONFIG_SCHEMA_PATH = ROOT / "schemas" / "semantic-batch-input-config.v1.schema.json"
PARTITION_LIMIT = 65536

_HEAD_REPOS = {
    "control": "Dsamofalov/hwm-control",
    "context": "Dsamofalov/hwm-context",
    "product": "Dsamofalov/hwm_predictor",
}
_FIRST_KD_TASK_KEYS = (
    "I06-0009", "I07-0010", "I08-0035", "I08-0037", "I08-0038", "I08-0040",
    "I08-0042", "I09-0045", "I09-0046", "I09-0047", "I09-0048", "I09-0049",
    "I09-0054", "I09-0056", "I09-0062", "I09-0064", "I09-0066",
)
_SOURCE_KEYS = {
    "ordering_key", "source_id", "source_type", "repository", "source_commit", "path",
    "git_blob_sha", "content_sha256", "utf8_bytes", "media_type",
    "knowledge_delta_task_key", "public_data_classification",
}
_VALIDATION_KEYS = {
    "exact_source_readback_required", "source_existence_required", "blob_sha_required",
    "content_sha256_required", "utf8_byte_size_required", "strict_ordering_required",
    "duplicate_source_ids_forbidden", "public_data_default_deny", "trigger_evidence_required",
    "deterministic_replay_required",
}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _fail(code: str, message: str) -> None:
    raise SemanticBatchError(code, message)


def _identity_projection(config: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(config))
    out.pop("config_id", None)
    out.pop("config_sha256", None)
    return out


def expected_input_config_sha256(config: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(_identity_projection(config)))


def _manifest_source(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "source_type": source["source_type"],
        "repository": source["repository"],
        "commit": source["source_commit"],
        "path": source["path"],
        "blob_sha": source["git_blob_sha"],
        "content_sha256": source["content_sha256"],
        "content_utf8_bytes": source["utf8_bytes"],
        "media_type": source["media_type"],
        "authority_class": (
            "knowledge_delta" if source["source_type"] == "knowledge_delta"
            else "historical_ledger"
        ),
        "epistemic_status": "supported",
        "conflict_ids": [],
        "supersedes_source_ids": [],
        "superseded_by_source_ids": [],
        "knowledge_delta_task_key": source["knowledge_delta_task_key"],
        "public_data": copy.deepcopy(PUBLIC_DATA),
    }


def canonical_source_frontier_sha256(sources: list[Mapping[str, Any]]) -> str:
    projection = [
        {
            "ordering_key": source["ordering_key"],
            "source_id": source["source_id"],
            "repository": source["repository"],
            "commit": source["source_commit"],
            "path": source["path"],
            "blob_sha": source["git_blob_sha"],
            "content_sha256": source["content_sha256"],
            "content_utf8_bytes": source["utf8_bytes"],
            "media_type": source["media_type"],
        }
        for source in sources
    ]
    return sha256_bytes(canonical_bytes(projection))


def _kd_frontier(sources: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "task_key": source["knowledge_delta_task_key"],
            "source_id": source["source_id"],
            "content_sha256": source["content_sha256"],
            "content_utf8_bytes": source["utf8_bytes"],
        }
        for source in sources
        if source["knowledge_delta_task_key"] is not None
    ]


def _trigger_evidence(config: Mapping[str, Any]) -> dict[str, Any]:
    trigger = config["trigger"]
    return {
        key: copy.deepcopy(trigger[key])
        for key in (
            "previous_accepted_semantic_coverage",
            "ordered_uncovered_knowledge_delta_frontier",
            "uncovered_knowledge_delta_count",
            "uncovered_knowledge_delta_utf8_bytes",
            "canonical_frontier_sha256",
            "exact_source_readback_heads",
        )
    }


def _validate_heads(
    heads: Mapping[str, Mapping[str, str]], code: str
) -> dict[str, dict[str, str]]:
    if set(heads) != set(_HEAD_REPOS):
        _fail(code, "exact head set must be control/context/product")
    out: dict[str, dict[str, str]] = {}
    for key in ("control", "context", "product"):
        row = heads[key]
        if (
            set(row) != {"repository", "commit"}
            or row["repository"] != _HEAD_REPOS[key]
            or not _SHA40.fullmatch(row["commit"])
        ):
            _fail(code, f"invalid exact head: {key}")
        out[key] = {"repository": row["repository"], "commit": row["commit"]}
    return out


def validate_input_config(config: Mapping[str, Any]) -> None:
    if not isinstance(config, Mapping) or config.get("schema") != INPUT_CONFIG_SCHEMA:
        _fail("UNSUPPORTED_INPUT_CONFIG", "unsupported semantic batch input config")
    try:
        schema = json.loads(INPUT_CONFIG_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(config)
        canonical_bytes(config)
    except (ValidationError, OSError, TypeError, ValueError, KeyError) as exc:
        _fail(
            "INPUT_CONFIG_SCHEMA_INVALID",
            f"semantic batch input config invalid: {exc}",
        )

    digest = expected_input_config_sha256(config)
    if (
        config["config_sha256"] != digest
        or config["config_id"] != "sbic1-" + digest
    ):
        _fail("INPUT_CONFIG_IDENTITY_MISMATCH", "config id/digest mismatch")

    snapshot = config["source_snapshot"]
    sources = list(snapshot["sources"])
    source_heads = _validate_heads(
        snapshot["exact_source_heads"], "SOURCE_HEADS_MISMATCH"
    )
    if (
        snapshot["freeze_boundary_task_key"] != "I09-0066"
        or snapshot["new_material_after_freeze"] != "later_batch"
    ):
        _fail(
            "FREEZE_POLICY_MISMATCH",
            "first frontier must freeze at I09-0066; later material is a later batch",
        )
    if (
        len(sources) != snapshot["source_count"]
        or sum(source["utf8_bytes"] for source in sources)
        != snapshot["total_utf8_bytes"]
    ):
        _fail("SOURCE_TOTAL_MISMATCH", "source count/bytes mismatch")
    if (
        snapshot["canonical_source_frontier_sha256"]
        != canonical_source_frontier_sha256(sources)
    ):
        _fail(
            "SOURCE_FRONTIER_DIGEST_MISMATCH",
            "canonical source frontier mismatch",
        )

    ordering = [source["ordering_key"] for source in sources]
    source_ids = [source["source_id"] for source in sources]
    locations = [
        (source["repository"], source["source_commit"], source["path"])
        for source in sources
    ]
    if ordering != sorted(ordering) or len(ordering) != len(set(ordering)):
        _fail(
            "SOURCE_ORDER_MISMATCH",
            "ordering keys must be strictly ordered and unique",
        )
    if len(source_ids) != len(set(source_ids)) or len(locations) != len(set(locations)):
        _fail("SOURCE_DUPLICATE", "duplicate exact source")

    for source in sources:
        if set(source) != _SOURCE_KEYS:
            _fail("SOURCE_SHAPE_MISMATCH", f"source shape mismatch: {source.get('path')}")
        if source["public_data_classification"] != "public-disclosure-safe":
            _fail(
                "PUBLIC_DATA_DENY",
                "source classification is not explicit public-disclosure-safe",
            )
        expected_commit = (
            source_heads["control"]["commit"]
            if source["repository"] == _HEAD_REPOS["control"]
            else source_heads["context"]["commit"]
        )
        if source["source_commit"] != expected_commit:
            _fail(
                "SOURCE_HEAD_BINDING_MISMATCH",
                f"source commit is not its configured exact head: {source['path']}",
            )
        row = _manifest_source(source)
        if source["source_id"] != stable_source_id(row):
            _fail(
                "SOURCE_ID_MISMATCH",
                f"source identity mismatch: {source['path']}",
            )
        if source["utf8_bytes"] > PARTITION_LIMIT:
            _fail(
                "PARTITION_SOURCE_OVERSIZE",
                f"single source exceeds deterministic partition limit: {source['source_id']}",
            )

    kd_sources = [
        source for source in sources
        if source["knowledge_delta_task_key"] is not None
    ]
    kd_keys = tuple(source["knowledge_delta_task_key"] for source in kd_sources)
    if kd_keys != _FIRST_KD_TASK_KEYS:
        _fail(
            "KNOWLEDGE_DELTA_FRONTIER_INVALID",
            "first KD task-key frontier is not exact",
        )
    if any(
        source["source_type"] != "knowledge_delta"
        or source["repository"] != _HEAD_REPOS["control"]
        or source["path"]
        != f"knowledge-deltas/{source['knowledge_delta_task_key']}.json"
        for source in kd_sources
    ):
        _fail(
            "KNOWLEDGE_DELTA_FRONTIER_INVALID",
            "KD frontier source typing/path mismatch",
        )

    ledger_sources = [
        source for source in sources
        if source["knowledge_delta_task_key"] is None
    ]
    if [
        (source["repository"], source["path"], source["source_type"])
        for source in ledger_sources
    ] != [
        (_HEAD_REPOS["context"], "claims/claims.jsonl", "repository_file"),
        (_HEAD_REPOS["context"], "claims/conflicts.json", "repository_file"),
    ]:
        _fail(
            "HISTORICAL_LEDGER_FRONTIER_INVALID",
            "historical ledger source frontier is not exact",
        )

    trigger = config["trigger"]
    if trigger["policy_kind"] != "knowledge_health/coverage":
        _fail(
            "TRIGGER_POLICY_MISMATCH",
            "first batch must use knowledge_health/coverage",
        )
    zero = trigger["previous_accepted_semantic_coverage"]
    if zero != {
        "method": "exact_protected_tree_inventory",
        "accepted_semantic_batch_count": 0,
        "accepted_semantic_coverage_count": 0,
        "accepted_batch_ids": [],
        "accepted_coverage_artifacts": [],
    }:
        _fail(
            "PREVIOUS_COVERAGE_NOT_ZERO",
            "zero accepted semantic coverage evidence mismatch",
        )

    kd_frontier = _kd_frontier(sources)
    compact_frontier = [
        {"task_key": row["task_key"], "source_id": row["source_id"]}
        for row in kd_frontier
    ]
    if trigger["ordered_uncovered_knowledge_delta_frontier"] != compact_frontier:
        _fail(
            "TRIGGER_FRONTIER_MISMATCH",
            "trigger ordered KD frontier mismatch",
        )
    if (
        trigger["uncovered_knowledge_delta_count"] != len(kd_frontier)
        or trigger["uncovered_knowledge_delta_utf8_bytes"]
        != sum(row["content_utf8_bytes"] for row in kd_frontier)
    ):
        _fail("TRIGGER_FRONTIER_MISMATCH", "trigger KD count/bytes mismatch")
    if (
        trigger["canonical_frontier_sha256"]
        != sha256_bytes(canonical_bytes(kd_frontier))
    ):
        _fail(
            "TRIGGER_FRONTIER_MISMATCH",
            "trigger KD frontier digest mismatch",
        )
    trigger_heads = _validate_heads(
        trigger["exact_source_readback_heads"], "TRIGGER_HEADS_MISMATCH"
    )
    if trigger_heads != source_heads:
        _fail(
            "TRIGGER_HEADS_MISMATCH",
            "trigger readback heads must equal frozen source heads",
        )
    evidence_digest = sha256_bytes(canonical_bytes(_trigger_evidence(config)))
    if trigger["evidence_sha256"] != evidence_digest:
        _fail(
            "TRIGGER_EVIDENCE_MISMATCH",
            "trigger evidence digest mismatch",
        )
    expected_projection = {
        "kind": "knowledge_health_signal",
        "signal_id": "knowledge-health.coverage:" + evidence_digest,
        "status": "coverage_gap",
        "affected_count": len(kd_frontier),
    }
    if trigger["manifest_projection"] != expected_projection:
        _fail(
            "TRIGGER_PROJECTION_MISMATCH",
            "manifest trigger projection mismatch",
        )

    if config["partition_policy"] != {
        "max_partition_utf8_bytes": 65536,
        "unit": "utf-8-bytes",
        "oversized_single_source": "fail-closed:P5R1_PARTITION_SOURCE_OVERSIZE",
    }:
        _fail("PARTITION_POLICY_MISMATCH", "partition policy mismatch")

    paths = {(source["repository"], source["path"]) for source in sources}
    if (_HEAD_REPOS["control"], "state/current.json") in paths:
        _fail(
            "CURRENT_STATE_AUTHORITY_VIOLATION",
            "state/current.json cannot be a current source",
        )
    if (_HEAD_REPOS["context"], "tasks/I09-0048/context.json") in paths:
        _fail(
            "TASK_CONTEXT_SELECTOR_VIOLATION",
            "I09-0048 task-context cannot be a selector",
        )

    boundary = config["authority_boundary"]
    if boundary != {
        "state_current": {
            "repository": _HEAD_REPOS["control"],
            "source_commit": source_heads["control"]["commit"],
            "path": "state/current.json",
            "role": "historical_snapshot_only_not_current_authority",
        },
        "task_context_i09_0048": {
            "repository": _HEAD_REPOS["context"],
            "source_commit": source_heads["context"]["commit"],
            "path": "tasks/I09-0048/context.json",
            "role": "excluded_first_batch_selector",
        },
    }:
        _fail(
            "AUTHORITY_BOUNDARY_MISMATCH",
            "required stale/current and task-context exclusions mismatch",
        )

    if config["historical_semantics"] != {
        "conflicts": [],
        "supersessions": [],
        "silent_winner_selection": False,
    }:
        _fail(
            "HISTORICAL_SEMANTICS_MISMATCH",
            "frozen historical conflict/supersession metadata mismatch",
        )

    runtime = config["runtime_manifest_binding"]
    if runtime != {
        "manifest_schema": "hwm-semantic-batch-manifest/v1",
        "generator": "control.semantic_batch_manifest.generate_manifest",
        "runtime_exact_heads_required": ["control", "context", "product"],
        "branch_names_forbidden": True,
        "source_snapshot_immutable": True,
        "manifest_materialized_later_in_issue": 67,
    }:
        _fail(
            "RUNTIME_BINDING_MISMATCH",
            "config/manifest boundary mismatch",
        )

    validation = config["validation_policy"]
    if set(validation) != _VALIDATION_KEYS or any(
        validation[key] is not True for key in _VALIDATION_KEYS
    ):
        _fail(
            "VALIDATION_POLICY_MISMATCH",
            "all exact validation rules must be enabled",
        )


def load_input_config(path: Path = INPUT_CONFIG_PATH) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("INPUT_CONFIG_PARSE_ERROR", str(exc))
    validate_input_config(config)
    if raw != canonical_bytes(config):
        _fail(
            "INPUT_CONFIG_NONCANONICAL",
            "config bytes are not canonical JSON",
        )
    return config


def validate_source_content_readbacks(
    config: Mapping[str, Any],
    source_contents: Mapping[str, bytes],
) -> None:
    validate_input_config(config)
    sources = list(config["source_snapshot"]["sources"])
    if set(source_contents) != {source["source_id"] for source in sources}:
        _fail(
            "SOURCE_EXISTENCE_MISMATCH",
            "source readback set has missing/extra/substituted identities",
        )
    for source in sources:
        data = source_contents[source["source_id"]]
        if not isinstance(data, bytes):
            _fail("SOURCE_READBACK_INVALID", "source content must be bytes")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            _fail(
                "SOURCE_UTF8_INVALID",
                f"source not UTF-8: {source['source_id']}",
            )
        if len(data) != source["utf8_bytes"]:
            _fail(
                "SOURCE_SIZE_MISMATCH",
                f"source byte size mismatch: {source['source_id']}",
            )
        if sha256_bytes(data) != source["content_sha256"]:
            _fail(
                "SOURCE_CONTENT_DIGEST_MISMATCH",
                f"source content SHA-256 mismatch: {source['source_id']}",
            )
        if git_blob_sha(data) != source["git_blob_sha"]:
            _fail(
                "SOURCE_BLOB_MISMATCH",
                f"source Git blob mismatch: {source['source_id']}",
            )


def materialize_manifest_generator_inputs(
    config: Mapping[str, Any],
    *,
    runtime_heads: Mapping[str, Mapping[str, str]],
    source_contents: Mapping[str, bytes],
) -> dict[str, Any]:
    validate_input_config(config)
    validate_source_content_readbacks(config, source_contents)
    heads = _validate_heads(runtime_heads, "RUNTIME_HEADS_MISMATCH")
    return {
        "exact_heads": heads,
        "source_readbacks": [
            _manifest_source(source)
            for source in config["source_snapshot"]["sources"]
        ],
        "conflicts": copy.deepcopy(config["historical_semantics"]["conflicts"]),
        "trigger": copy.deepcopy(config["trigger"]["manifest_projection"]),
        "max_partition_utf8_bytes": (
            config["partition_policy"]["max_partition_utf8_bytes"]
        ),
    }


def generate_manifest_from_input_config(
    config: Mapping[str, Any],
    *,
    runtime_heads: Mapping[str, Mapping[str, str]],
    source_contents: Mapping[str, bytes],
) -> dict[str, Any]:
    return generate_manifest(
        **materialize_manifest_generator_inputs(
            config,
            runtime_heads=runtime_heads,
            source_contents=source_contents,
        )
    )
