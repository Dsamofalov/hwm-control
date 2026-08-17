from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from jsonschema.exceptions import ValidationError

from control.semantic_batch_manifest import (
    AUTHORITY_BOUNDARY, COVERAGE_SCHEMA, PUBLIC_DATA, RESULT_SCHEMA, SemanticBatchError,
    _ensure_public, _sorted_unique, _validate_schema, canonical_bytes, classify_replay,
    sha256_bytes, validate_manifest, validate_source_readbacks,
)


def _coverage_projection(coverage: Mapping[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(coverage))
    candidate.pop("coverage_id", None)
    candidate.pop("coverage_sha256", None)
    return candidate


def expected_coverage_sha256(coverage: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(_coverage_projection(coverage)))


def finalize_coverage(
    manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    validate_manifest(manifest)
    coverage = {
        "schema": COVERAGE_SCHEMA,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "coverage_id": "scv1-" + "0" * 64,
        "coverage_sha256": "0" * 64,
        "classification": "derived_non_authoritative",
        "rows": sorted((copy.deepcopy(dict(row)) for row in rows), key=lambda row: row["source_id"]),
        "authority_boundary": copy.deepcopy(AUTHORITY_BOUNDARY),
        "public_data": copy.deepcopy(PUBLIC_DATA),
    }
    digest = expected_coverage_sha256(coverage)
    coverage["coverage_sha256"] = digest
    coverage["coverage_id"] = "scv1-" + digest
    validate_coverage(manifest, coverage)
    return coverage


def validate_coverage(manifest: Mapping[str, Any], coverage: Mapping[str, Any]) -> None:
    validate_manifest(manifest)
    if not isinstance(coverage, Mapping) or coverage.get("schema") != COVERAGE_SCHEMA:
        raise SemanticBatchError("UNSUPPORTED_SCHEMA_VERSION", "unsupported semantic coverage schema")
    try:
        _validate_schema("coverage", coverage)
        canonical_bytes(coverage)
    except (ValidationError, TypeError, ValueError) as exc:
        raise SemanticBatchError("COVERAGE_INVALID", f"semantic coverage invalid: {exc}") from exc
    if coverage["batch_id"] != manifest["batch_id"] or coverage["manifest_sha256"] != manifest["manifest_sha256"]:
        raise SemanticBatchError("COVERAGE_BINDING_MISMATCH", "coverage does not bind exact manifest")
    digest = expected_coverage_sha256(coverage)
    if coverage["coverage_sha256"] != digest or coverage["coverage_id"] != "scv1-" + digest:
        raise SemanticBatchError("COVERAGE_IDENTITY_MISMATCH", "coverage identity/digest mismatch")
    rows = list(coverage["rows"])
    row_ids = [row["source_id"] for row in rows]
    if not _sorted_unique(row_ids):
        raise SemanticBatchError("COVERAGE_DUPLICATE", "coverage rows must be source_id-sorted and unique")
    required = list(manifest["required_coverage_set"])
    if row_ids != required:
        missing = sorted(set(required) - set(row_ids))
        extra = sorted(set(row_ids) - set(required))
        raise SemanticBatchError("COVERAGE_INCOMPLETE", f"coverage set mismatch; missing={missing} extra={extra}")


def build_artifact(
    *, kind: str, content: str, source_bindings: Sequence[Mapping[str, str]],
    epistemic_status: str, historical_labels: Sequence[str] = (),
    conflict_ids: Sequence[str] = (), superseded_source_ids: Sequence[str] = (),
) -> dict[str, Any]:
    _ensure_public("semantic artifact", content)
    bindings = sorted((copy.deepcopy(dict(item)) for item in source_bindings), key=lambda item: item["source_id"])
    payload = {
        "kind": kind,
        "content": content,
        "content_sha256": sha256_bytes(content.encode("utf-8")),
        "source_bindings": bindings,
        "epistemic_status": epistemic_status,
        "historical_labels": sorted(set(historical_labels)),
        "conflict_ids": sorted(set(conflict_ids)),
        "superseded_source_ids": sorted(set(superseded_source_ids)),
    }
    payload["artifact_id"] = "art1-" + sha256_bytes(canonical_bytes(payload))
    return payload


def _result_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(result))
    candidate.pop("result_id", None)
    candidate.pop("result_sha256", None)
    return candidate


def expected_result_sha256(result: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(_result_projection(result)))


def _partition_result_digest(source_results: Sequence[Mapping[str, Any]], source_ids: Sequence[str]) -> str:
    by_id = {row["source_id"]: row for row in source_results}
    return sha256_bytes(canonical_bytes([by_id[source_id] for source_id in source_ids]))


def finalize_result(
    manifest: Mapping[str, Any], coverage: Mapping[str, Any], *,
    source_results: Sequence[Mapping[str, Any]], artifacts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    validate_coverage(manifest, coverage)
    sorted_results = sorted((copy.deepcopy(dict(row)) for row in source_results), key=lambda row: row["source_id"])
    partition_results = [
        {
            "partition_id": partition["partition_id"],
            "partition_sha256": partition["partition_sha256"],
            "source_ids": copy.deepcopy(partition["source_ids"]),
            "result_sha256": _partition_result_digest(sorted_results, partition["source_ids"]),
        }
        for partition in manifest["partition_plan"]["partitions"]
    ]
    result = {
        "schema": RESULT_SCHEMA,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "result_id": "sbr1-" + "0" * 64,
        "result_sha256": "0" * 64,
        "coverage_sha256": coverage["coverage_sha256"],
        "classification": "derived_non_authoritative",
        "source_results": sorted_results,
        "artifacts": sorted((copy.deepcopy(dict(item)) for item in artifacts), key=lambda item: item["artifact_id"]),
        "historical_semantics": copy.deepcopy(manifest["historical_semantics"]),
        "partition_results": partition_results,
        "authority_boundary": copy.deepcopy(AUTHORITY_BOUNDARY),
        "public_data": copy.deepcopy(PUBLIC_DATA),
    }
    digest = expected_result_sha256(result)
    result["result_sha256"] = digest
    result["result_id"] = "sbr1-" + digest
    validate_result(manifest, coverage, result)
    return result


def validate_result(manifest: Mapping[str, Any], coverage: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    validate_coverage(manifest, coverage)
    if not isinstance(result, Mapping) or result.get("schema") != RESULT_SCHEMA:
        raise SemanticBatchError("UNSUPPORTED_SCHEMA_VERSION", "unsupported semantic batch result schema")
    try:
        _validate_schema("result", result)
        canonical_bytes(result)
    except (ValidationError, TypeError, ValueError) as exc:
        raise SemanticBatchError("RESULT_INVALID", f"semantic batch result invalid: {exc}") from exc
    if (
        result["batch_id"] != manifest["batch_id"]
        or result["manifest_sha256"] != manifest["manifest_sha256"]
        or result["coverage_sha256"] != coverage["coverage_sha256"]
    ):
        raise SemanticBatchError("RESULT_BINDING_MISMATCH", "result does not bind exact manifest/coverage")
    digest = expected_result_sha256(result)
    if result["result_sha256"] != digest or result["result_id"] != "sbr1-" + digest:
        raise SemanticBatchError("RESULT_IDENTITY_MISMATCH", "result identity/digest mismatch")

    source_results = list(result["source_results"])
    source_result_ids = [row["source_id"] for row in source_results]
    if not _sorted_unique(source_result_ids):
        raise SemanticBatchError("RESULT_DUPLICATE_SOURCE", "source results must be source_id-sorted and unique")
    if source_result_ids != list(manifest["required_coverage_set"]):
        raise SemanticBatchError("RESULT_SOURCE_SET_MISMATCH", "result must cover exact manifest source set")

    source_by_id = {source["source_id"]: source for source in manifest["sources"]}
    coverage_by_id = {row["source_id"]: row for row in coverage["rows"]}
    for row in source_results:
        source = source_by_id[row["source_id"]]
        expected = {
            "source_id": source["source_id"],
            "coverage_status": coverage_by_id[source["source_id"]]["status"],
            "source_content_sha256": source["content_sha256"],
            "epistemic_status": source["epistemic_status"],
            "conflict_ids": source["conflict_ids"],
            "supersedes_source_ids": source["supersedes_source_ids"],
            "superseded_by_source_ids": source["superseded_by_source_ids"],
        }
        if row != expected:
            raise SemanticBatchError(
                "SEMANTICS_PRESERVATION_MISMATCH",
                f"result source projection changed exact semantics: {source['source_id']}",
            )
    if result["historical_semantics"] != manifest["historical_semantics"]:
        raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "result changed conflicts/supersessions")

    known_ids = set(source_by_id)
    for artifact in result["artifacts"]:
        if artifact["content_sha256"] != sha256_bytes(artifact["content"].encode("utf-8")):
            raise SemanticBatchError("ARTIFACT_DIGEST_MISMATCH", "artifact content digest mismatch")
        _ensure_public(artifact["artifact_id"], artifact["content"])
        projection = copy.deepcopy(dict(artifact))
        artifact_id = projection.pop("artifact_id")
        if artifact_id != "art1-" + sha256_bytes(canonical_bytes(projection)):
            raise SemanticBatchError("ARTIFACT_IDENTITY_MISMATCH", "artifact identity mismatch")
        binding_ids = [item["source_id"] for item in artifact["source_bindings"]]
        if not _sorted_unique(binding_ids) or not set(binding_ids).issubset(known_ids):
            raise SemanticBatchError("ARTIFACT_PROVENANCE_MISMATCH", "artifact source bindings invalid")
        for binding in artifact["source_bindings"]:
            if binding["content_sha256"] != source_by_id[binding["source_id"]]["content_sha256"]:
                raise SemanticBatchError("ARTIFACT_PROVENANCE_MISMATCH", "artifact source digest mismatch")
        referenced_conflicts = set()
        referenced_superseded = set()
        for source_id in binding_ids:
            source = source_by_id[source_id]
            referenced_conflicts.update(source["conflict_ids"])
            if source["superseded_by_source_ids"]:
                referenced_superseded.add(source_id)
        if referenced_conflicts and (
            "conflict" not in artifact["historical_labels"]
            or not referenced_conflicts.issubset(set(artifact["conflict_ids"]))
        ):
            raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "artifact lost conflict marking")
        if referenced_superseded and (
            "superseded" not in artifact["historical_labels"]
            or not referenced_superseded.issubset(set(artifact["superseded_source_ids"]))
        ):
            raise SemanticBatchError("HISTORICAL_SEMANTICS_MISMATCH", "artifact lost supersession marking")

    expected_partitions = list(manifest["partition_plan"]["partitions"])
    actual_partitions = list(result["partition_results"])
    if [item["partition_id"] for item in actual_partitions] != [item["partition_id"] for item in expected_partitions]:
        raise SemanticBatchError("PARTITION_RESULT_MISMATCH", "partition result identities/order mismatch")
    seen: list[str] = []
    for expected, actual in zip(expected_partitions, actual_partitions):
        if (
            actual["partition_id"] != expected["partition_id"]
            or actual["partition_sha256"] != expected["partition_sha256"]
            or actual["source_ids"] != expected["source_ids"]
        ):
            raise SemanticBatchError("PARTITION_RESULT_MISMATCH", "partition result provenance mismatch")
        expected_digest = _partition_result_digest(source_results, expected["source_ids"])
        if actual["result_sha256"] != expected_digest:
            raise SemanticBatchError("PARTITION_RESULT_DIGEST_MISMATCH", "partition result digest mismatch")
        seen.extend(actual["source_ids"])
    if seen != list(manifest["required_coverage_set"]) or len(seen) != len(set(seen)):
        raise SemanticBatchError("PARTITION_REASSEMBLY_MISMATCH", "partition union has overlap/omission/order drift")


def verify_batch(
    manifest: Mapping[str, Any], coverage: Mapping[str, Any], result: Mapping[str, Any],
    source_readbacks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validate_manifest(manifest)
    validate_source_readbacks(manifest, source_readbacks)
    validate_coverage(manifest, coverage)
    validate_result(manifest, coverage, result)
    return {
        "accepted": True,
        "batch_id": manifest["batch_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "coverage_sha256": coverage["coverage_sha256"],
        "result_sha256": result["result_sha256"],
        "classification": "derived_non_authoritative",
        "authority_boundary": copy.deepcopy(AUTHORITY_BOUNDARY),
    }
