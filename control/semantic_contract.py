from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = {
    "input": "semantic-transform-input.v1.schema.json",
    "output": "semantic-transform-output.v1.schema.json",
    "result": "semantic-verification-result.v1.schema.json",
}
INPUT_SCHEMA = "hwm-semantic-transform-input/v1"
OUTPUT_SCHEMA = "hwm-semantic-transform-output/v1"
RESULT_SCHEMA = "hwm-semantic-verification-result/v1"
VERIFIER_ID = "hwm-semantic-verifier/v1"

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

_REASONS = {
    "SCHEMA_INVALID": "schema_invalid",
    "UNSUPPORTED_SCHEMA_VERSION": "unsupported_schema_version",
    "INPUT_BINDING_MISMATCH": "input_binding_mismatch",
    "PROVENANCE_MISMATCH": "provenance_mismatch",
    "AUTHORITY_PROMOTION_ATTEMPT": "authority_promotion_attempt",
    "HISTORICAL_SEMANTICS_MISMATCH": "historical_semantics_mismatch",
    "SILENT_CONFLICT_SELECTION": "silent_conflict_selection",
    "BUDGET_EXCEEDED": "budget_exceeded",
    "PUBLIC_DATA_VIOLATION": "public_data_violation",
    "TRUNCATION_INVALID": "truncation_invalid",
    "VERIFIER_REJECTED": "verifier_rejected",
    "TIMEOUT": "timeout",
    "TRANSIENT_PROVIDER_ERROR": "transient_provider_error",
    "MALFORMED_OUTPUT": "malformed_output",
    "RETRY_EXHAUSTED": "retry_exhausted",
}


class SemanticContractError(ValueError):
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


def _schema(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "schemas" / SCHEMA_FILES[name]).read_text(encoding="utf-8"))


def _validate_schema(name: str, value: Any) -> None:
    Draft202012Validator(
        _schema(name), format_checker=FormatChecker()
    ).validate(value)


def expected_transform_id(value: Mapping[str, Any]) -> str:
    candidate = copy.deepcopy(dict(value))
    candidate.pop("transform_id", None)
    return "str1-" + sha256_bytes(canonical_bytes(candidate))


def input_sha256(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(dict(value)))


def model_configuration_sha256(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(dict(value)["llm_provenance"]["model"]))


def _contains_forbidden_data(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _ensure_public(label: str, text: str) -> None:
    if _contains_forbidden_data(text):
        raise SemanticContractError(
            "PUBLIC_DATA_VIOLATION",
            f"hwm-public-data/v1 violation in {label}",
        )


def _source_projection(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "authority_class": source["authority_class"],
        "media_type": source["media_type"],
        "content_sha256": source["content_sha256"],
        "provenance": copy.deepcopy(source["provenance"]),
    }


def source_provenance_projection(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        _source_projection(source)
        for source in sorted(value["inputs"], key=lambda item: item["source_id"])
    ]


def _ordered_unique(values: list[str]) -> bool:
    return values == sorted(values) and len(values) == len(set(values))


def validate_semantic_input(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or value.get("schema") != INPUT_SCHEMA:
        raise SemanticContractError(
            "UNSUPPORTED_SCHEMA_VERSION",
            "semantic input schema/version is unsupported",
        )
    try:
        _validate_schema("input", value)
        canonical_bytes(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise SemanticContractError("SCHEMA_INVALID", f"semantic input invalid: {exc}") from exc

    if value["transform_id"] != expected_transform_id(value):
        raise SemanticContractError(
            "INPUT_BINDING_MISMATCH", "transform_id does not bind exact canonical input"
        )

    prompt = value["llm_provenance"]["prompt"]
    if sha256_bytes(prompt["rendered_text"].encode("utf-8")) != prompt["rendered_sha256"]:
        raise SemanticContractError(
            "PROVENANCE_MISMATCH", "rendered prompt digest mismatch"
        )
    _ensure_public("rendered_prompt", prompt["rendered_text"])

    budgets = value["budgets"]
    observation = value["budget_observation"]
    model_config = value["llm_provenance"]["model"]["configuration"]
    if model_config["max_output_tokens"] != budgets["output_max_tokens"]:
        raise SemanticContractError(
            "PROVENANCE_MISMATCH",
            "model max_output_tokens must equal semantic output token budget",
        )

    sources = list(value["inputs"])
    source_ids = [source["source_id"] for source in sources]
    if not _ordered_unique(source_ids):
        raise SemanticContractError(
            "PROVENANCE_MISMATCH", "semantic input sources must be unique and source_id-sorted"
        )

    calculated_bytes = len(prompt["rendered_text"].encode("utf-8"))
    for source in sources:
        raw = source["content"].encode("utf-8")
        calculated_bytes += len(raw)
        if sha256_bytes(raw) != source["content_sha256"]:
            raise SemanticContractError(
                "PROVENANCE_MISMATCH", f"source digest mismatch: {source['source_id']}"
            )
        _ensure_public(source["source_id"], source["content"])

    if observation["input_utf8_bytes"] != calculated_bytes:
        raise SemanticContractError(
            "BUDGET_EXCEEDED", "input byte observation does not equal contract byte metric"
        )
    if observation["input_utf8_bytes"] > budgets["input_max_utf8_bytes"]:
        raise SemanticContractError("BUDGET_EXCEEDED", "input byte budget exceeded")
    if observation["input_tokens"] > budgets["input_max_tokens"]:
        raise SemanticContractError("BUDGET_EXCEEDED", "input token budget exceeded")

    known = set(source_ids)
    conflicts = value["historical_semantics"]["conflicts"]
    conflict_ids = [item["conflict_id"] for item in conflicts]
    if not _ordered_unique(conflict_ids):
        raise SemanticContractError(
            "HISTORICAL_SEMANTICS_MISMATCH",
            "historical conflicts must be unique and conflict_id-sorted",
        )
    for conflict in conflicts:
        if not _ordered_unique(conflict["source_ids"]):
            raise SemanticContractError(
                "HISTORICAL_SEMANTICS_MISMATCH",
                f"conflict source_ids must be unique and sorted: {conflict['conflict_id']}",
            )
        if not set(conflict["source_ids"]).issubset(known):
            raise SemanticContractError(
                "HISTORICAL_SEMANTICS_MISMATCH",
                f"conflict references an unknown source: {conflict['conflict_id']}",
            )

    supersessions = value["historical_semantics"]["supersessions"]
    if supersessions != sorted(
        supersessions, key=lambda item: (item["source_id"], item["superseded_by_source_id"])
    ):
        raise SemanticContractError(
            "HISTORICAL_SEMANTICS_MISMATCH", "supersessions must be deterministically sorted"
        )
    for relation in supersessions:
        pair = {relation["source_id"], relation["superseded_by_source_id"]}
        if len(pair) != 2 or not pair.issubset(known):
            raise SemanticContractError(
                "HISTORICAL_SEMANTICS_MISMATCH",
                "supersession must reference two distinct known sources",
            )

    if not _ordered_unique(list(value["requested_outputs"])):
        raise SemanticContractError(
            "SCHEMA_INVALID", "requested_outputs must be lexicographically sorted"
        )


def _fallback(reason: str | None) -> dict[str, Any]:
    return {
        "mode": "deterministic_task_context_only",
        "deterministic_task_context_usable": True,
        "semantic_materialization": "none",
        "reason": reason,
    }


def _result(
    semantic_input: Mapping[str, Any],
    *,
    output_sha256: str | None,
    decision: str,
    codes: list[str],
    reason: str | None,
) -> dict[str, Any]:
    result = {
        "schema": RESULT_SCHEMA,
        "transform_id": str(semantic_input.get("transform_id", "str1-" + "0" * 64)),
        "input_sha256": input_sha256(semantic_input),
        "output_sha256": output_sha256,
        "decision": decision,
        "materialization_allowed": decision == "accept",
        "codes": ["ACCEPT"] if decision == "accept" else sorted(set(codes)),
        "fallback": _fallback(None if decision == "accept" else reason),
    }
    _validate_schema("result", result)
    return result


def degraded_fallback_result(
    semantic_input: Mapping[str, Any], failure: str, attempts: int
) -> dict[str, Any]:
    validate_semantic_input(semantic_input)
    policy = semantic_input["execution_policy"]
    budgets = semantic_input["budgets"]
    retryable = set(policy["retryable_failures"])
    if failure not in retryable:
        raise SemanticContractError(
            "VERIFIER_REJECTED", "degraded retry-exhaustion helper accepts retryable failures only"
        )
    if attempts != budgets["max_attempts"]:
        raise SemanticContractError(
            "RETRY_EXHAUSTED", "degraded fallback requires exact max_attempts exhaustion"
        )
    code = {
        "timeout": "TIMEOUT",
        "transient_provider_error": "TRANSIENT_PROVIDER_ERROR",
        "malformed_output": "MALFORMED_OUTPUT",
    }[failure]
    return _result(
        semantic_input,
        output_sha256=None,
        decision="degraded_fallback",
        codes=[code, "RETRY_EXHAUSTED"],
        reason="retry_exhausted",
    )


def verify_semantic_output(
    semantic_input: Mapping[str, Any], semantic_output: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        validate_semantic_input(semantic_input)
    except SemanticContractError as exc:
        return _result(
            semantic_input,
            output_sha256=None,
            decision="reject",
            codes=[exc.code],
            reason=_REASONS.get(exc.code, "verifier_rejected"),
        )

    output_digest: str | None
    try:
        output_digest = sha256_bytes(canonical_bytes(semantic_output))
    except (TypeError, ValueError):
        output_digest = None

    if not isinstance(semantic_output, Mapping) or semantic_output.get("schema") != OUTPUT_SCHEMA:
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["UNSUPPORTED_SCHEMA_VERSION"],
            reason="unsupported_schema_version",
        )

    if semantic_output.get("classification") not in (None, "derived_non_authoritative"):
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["AUTHORITY_PROMOTION_ATTEMPT"],
            reason="authority_promotion_attempt",
        )
    boundary = semantic_output.get("authority_boundary")
    if isinstance(boundary, Mapping):
        if boundary.get("classification") not in (None, "derived_non_authoritative"):
            return _result(
                semantic_input,
                output_sha256=output_digest,
                decision="reject",
                codes=["AUTHORITY_PROMOTION_ATTEMPT"],
                reason="authority_promotion_attempt",
            )
        if boundary.get("may_override") not in (None, []):
            return _result(
                semantic_input,
                output_sha256=output_digest,
                decision="reject",
                codes=["AUTHORITY_PROMOTION_ATTEMPT"],
                reason="authority_promotion_attempt",
            )

    try:
        _validate_schema("output", semantic_output)
        canonical_bytes(semantic_output)
    except (ValidationError, TypeError, ValueError):
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["SCHEMA_INVALID"],
            reason="schema_invalid",
        )

    exact_input_sha = input_sha256(semantic_input)
    if (
        semantic_output["transform_id"] != semantic_input["transform_id"]
        or semantic_output["input_sha256"] != exact_input_sha
    ):
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["INPUT_BINDING_MISMATCH"],
            reason="input_binding_mismatch",
        )

    expected_binding = {
        "task_context_content_sha256": semantic_input["task_context"]["content_sha256"],
        "prompt_rendered_sha256": semantic_input["llm_provenance"]["prompt"]["rendered_sha256"],
        "model_configuration_sha256": model_configuration_sha256(semantic_input),
    }
    if semantic_output["provenance_binding"] != expected_binding:
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["PROVENANCE_MISMATCH"],
            reason="provenance_mismatch",
        )

    expected_sources = source_provenance_projection(semantic_input)
    if semantic_output["source_provenance"] != expected_sources:
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["PROVENANCE_MISMATCH"],
            reason="provenance_mismatch",
        )

    if semantic_output["historical_semantics"] != semantic_input["historical_semantics"]:
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["HISTORICAL_SEMANTICS_MISMATCH"],
            reason="historical_semantics_mismatch",
        )

    budgets = semantic_input["budgets"]
    usage = semantic_output["usage"]
    if (
        usage["input_tokens"] != semantic_input["budget_observation"]["input_tokens"]
        or usage["output_tokens"] > budgets["output_max_tokens"]
        or usage["attempts"] > budgets["max_attempts"]
    ):
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["BUDGET_EXCEEDED"],
            reason="budget_exceeded",
        )

    artifacts = semantic_output["artifacts"]
    ids = [artifact["artifact_id"] for artifact in artifacts]
    if not _ordered_unique(ids):
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["SCHEMA_INVALID"],
            reason="schema_invalid",
        )

    known_sources = {source["source_id"] for source in semantic_input["inputs"]}
    known_conflicts = {
        item["conflict_id"]: set(item["source_ids"])
        for item in semantic_input["historical_semantics"]["conflicts"]
    }
    superseded = {
        item["source_id"]
        for item in semantic_input["historical_semantics"]["supersessions"]
    }
    calculated_output_bytes = 0
    for artifact in artifacts:
        calculated_output_bytes += len(artifact["content"].encode("utf-8"))
        if not _ordered_unique(artifact["source_ids"]):
            return _result(
                semantic_input,
                output_sha256=output_digest,
                decision="reject",
                codes=["PROVENANCE_MISMATCH"],
                reason="provenance_mismatch",
            )
        if not set(artifact["source_ids"]).issubset(known_sources):
            return _result(
                semantic_input,
                output_sha256=output_digest,
                decision="reject",
                codes=["PROVENANCE_MISMATCH"],
                reason="provenance_mismatch",
            )
        for key in ("historical_labels", "conflict_ids", "superseded_source_ids"):
            if list(artifact[key]) != sorted(artifact[key]):
                return _result(
                    semantic_input,
                    output_sha256=output_digest,
                    decision="reject",
                    codes=["SCHEMA_INVALID"],
                    reason="schema_invalid",
                )
        try:
            _ensure_public(f"artifact:{artifact['artifact_id']}:title", artifact["title"])
            _ensure_public(f"artifact:{artifact['artifact_id']}:content", artifact["content"])
        except SemanticContractError:
            return _result(
                semantic_input,
                output_sha256=output_digest,
                decision="reject",
                codes=["PUBLIC_DATA_VIOLATION"],
                reason="public_data_violation",
            )

        artifact_sources = set(artifact["source_ids"])
        for conflict_id, conflict_sources in known_conflicts.items():
            if artifact_sources.intersection(conflict_sources):
                if (
                    conflict_id not in artifact["conflict_ids"]
                    or "conflict" not in artifact["historical_labels"]
                ):
                    return _result(
                        semantic_input,
                        output_sha256=output_digest,
                        decision="reject",
                        codes=["SILENT_CONFLICT_SELECTION"],
                        reason="silent_conflict_selection",
                    )
        referenced_superseded = artifact_sources.intersection(superseded)
        if referenced_superseded:
            if (
                "superseded" not in artifact["historical_labels"]
                or not referenced_superseded.issubset(set(artifact["superseded_source_ids"]))
            ):
                return _result(
                    semantic_input,
                    output_sha256=output_digest,
                    decision="reject",
                    codes=["HISTORICAL_SEMANTICS_MISMATCH"],
                    reason="historical_semantics_mismatch",
                )

    if (
        calculated_output_bytes != usage["output_utf8_bytes"]
        or calculated_output_bytes > budgets["output_max_utf8_bytes"]
    ):
        return _result(
            semantic_input,
            output_sha256=output_digest,
            decision="reject",
            codes=["BUDGET_EXCEEDED"],
            reason="budget_exceeded",
        )

    return _result(
        semantic_input,
        output_sha256=output_digest,
        decision="accept",
        codes=["ACCEPT"],
        reason=None,
    )
