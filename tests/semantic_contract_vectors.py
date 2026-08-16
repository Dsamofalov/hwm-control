from __future__ import annotations

import copy
import hashlib

from control import semantic_contract as sc

A40 = "a" * 40
B40 = "b" * 40
C40 = "c" * 40
D40 = "d" * 40
A64 = "a" * 64
B64 = "b" * 64
C64 = "c" * 64


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(source_id: str, content: str, *, commit: str = A40, blob: str = B40):
    return {
        "source_id": source_id,
        "authority_class": "historical_ledger" if source_id.startswith("history.") else "product_source",
        "media_type": "text/plain",
        "content": content,
        "content_sha256": _sha(content),
        "provenance": {
            "kind": "git_blob",
            "repository": "Dsamofalov/hwm-context" if source_id.startswith("history.") else "Dsamofalov/hwm_predictor",
            "commit": commit,
            "path": f"fixtures/{source_id}.txt",
            "blob_sha": blob,
            "content_sha256": _sha(content),
        },
    }


def valid_input(*, conflict: bool = False, ambiguous: bool = False):
    prompt_text = (
        "Produce only schema-valid derived context/wiki JSON. Preserve provenance, "
        "conflicts, supersessions, ambiguity, and non-authoritative classification."
    )
    sources = [
        _git("history.alpha", "Earlier claim: route A.", commit=A40, blob=B40),
        _git("history.beta", "Conflicting claim: route B.", commit=A40, blob=C40),
        _git("product.spec", "Current product source says deterministic context remains authoritative.", commit=D40, blob=A40),
    ]
    sources.sort(key=lambda item: item["source_id"])
    conflicts = []
    if conflict:
        conflicts = [{
            "conflict_id": "hc-route-choice",
            "source_ids": ["history.alpha", "history.beta"],
            "status": "unresolved",
        }]
    supersessions = [{
        "source_id": "history.alpha",
        "superseded_by_source_id": "product.spec",
        "relation": "superseded",
    }]
    value = {
        "schema": "hwm-semantic-transform-input/v1",
        "transform_id": "str1-" + "0" * 64,
        "task_context": {
            "schema": "hwm-task-context-pack/v1",
            "repository": "Dsamofalov/hwm-context",
            "commit": D40,
            "path": "tasks/I09-0049/context.json",
            "blob_sha": B40,
            "content_sha256": C64,
            "task_key": "I09-0049",
            "request_id": "tcr1-" + B64,
        },
        "inputs": sources,
        "historical_semantics": {
            "conflicts": conflicts,
            "supersessions": supersessions,
            "silent_winner_selection": False,
        },
        "llm_provenance": {
            "contract": {
                "contract_id": "hwm-semantic-transformation-contract/v1",
                "input_schema": "hwm-semantic-transform-input/v1",
                "output_schema": "hwm-semantic-transform-output/v1",
                "verifier": "hwm-semantic-verifier/v1",
            },
            "prompt": {
                "template_id": "i09.semantic.context-wiki",
                "version": "v1",
                "template_sha256": A64,
                "rendered_text": prompt_text,
                "rendered_sha256": _sha(prompt_text),
            },
            "model": {
                "provider": "openai",
                "model_id": "pinned-model-example",
                "configuration": {
                    "temperature": 0,
                    "top_p": 1,
                    "max_output_tokens": 1024,
                    "seed": 7,
                    "response_format": "json_schema",
                    "strict": True,
                },
            },
        },
        "budgets": {
            "input_max_utf8_bytes": 10000,
            "input_max_tokens": 4096,
            "output_max_utf8_bytes": 10000,
            "output_max_tokens": 1024,
            "timeout_ms": 30000,
            "max_attempts": 2,
        },
        "budget_observation": {
            "input_utf8_bytes": len(prompt_text.encode("utf-8")) + sum(len(s["content"].encode("utf-8")) for s in sources),
            "input_tokens": 211,
            "tokenizer": "pinned-tokenizer-example",
        },
        "execution_policy": {
            "timeout_scope": "per_attempt",
            "retryable_failures": ["timeout", "transient_provider_error", "malformed_output"],
            "nonretryable_failures": [
                "unsupported_schema_version",
                "public_data_violation",
                "provenance_mismatch",
                "authority_promotion_attempt",
                "verifier_rejected",
            ],
            "retry_identity": "exact_same_input_prompt_model_configuration",
            "backoff_ms": 0,
            "on_retry_exhausted": "degraded_fallback",
            "on_unsupported_output": "reject_no_retry",
            "on_verifier_rejection": "fail_closed_no_semantic_materialization",
            "fallback_mode": "deterministic_task_context_only",
            "deterministic_task_context_usable": True,
        },
        "requested_outputs": ["context_summary", "wiki_sections"],
        "public_data": {
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
        },
        "authority_boundary": {
            "classification": "derived_non_authoritative",
            "may_override": [],
            "denied_authorities": [
                "current_product_head",
                "current_control_head",
                "current_context_head",
                "authoritative_project_state",
                "github_issue_lifecycle",
                "task_ownership",
                "ci_status",
                "branch_protection_ruleset_state",
                "source_freshness",
                "provenance_acceptance",
                "deterministic_gate_outcomes",
                "merge_authority",
            ],
            "deterministic_task_context_independent": True,
        },
    }
    value["transform_id"] = sc.expected_transform_id(value)
    return value


def valid_output(inp=None, *, conflict: bool = False, partial: bool = False, ambiguous: bool = False):
    inp = copy.deepcopy(inp or valid_input(conflict=conflict, ambiguous=ambiguous))
    conflict_ids = ["hc-route-choice"] if conflict else []
    labels = ["conflict", "superseded"] if conflict else ["superseded"]
    if ambiguous:
        labels = sorted(set(labels + ["ambiguous"]))
    artifact = {
        "artifact_id": "context.primary",
        "kind": "context_summary",
        "title": "Derived context summary",
        "content": "Derived convenience summary; consult exact deterministic sources for authority.",
        "source_ids": ["history.alpha", "product.spec"],
        "historical_labels": sorted(labels),
        "conflict_ids": conflict_ids,
        "superseded_source_ids": ["history.alpha"],
    }
    content_bytes = len(artifact["content"].encode("utf-8"))
    return {
        "schema": "hwm-semantic-transform-output/v1",
        "transform_id": inp["transform_id"],
        "input_sha256": sc.input_sha256(inp),
        "classification": "derived_non_authoritative",
        "status": "partial" if partial else "complete",
        "finish_reason": "max_output_tokens" if partial else "stop",
        "provenance_binding": {
            "task_context_content_sha256": inp["task_context"]["content_sha256"],
            "prompt_rendered_sha256": inp["llm_provenance"]["prompt"]["rendered_sha256"],
            "model_configuration_sha256": sc.model_configuration_sha256(inp),
        },
        "source_provenance": sc.source_provenance_projection(inp),
        "historical_semantics": copy.deepcopy(inp["historical_semantics"]),
        "artifacts": [artifact],
        "usage": {
            "input_tokens": inp["budget_observation"]["input_tokens"],
            "output_tokens": 333 if partial else 123,
            "output_utf8_bytes": content_bytes,
            "attempts": 1,
        },
        "public_data": copy.deepcopy(inp["public_data"]),
        "authority_boundary": copy.deepcopy(inp["authority_boundary"]),
    }


def corpus():
    valid = valid_input()
    conflicting = valid_input(conflict=True)
    ambiguous = valid_input(ambiguous=True)
    truncated = valid_output(valid, partial=True)
    invalid = valid_output(valid)
    invalid.pop("provenance_binding")
    unsupported = valid_output(valid)
    unsupported["schema"] = "hwm-semantic-transform-output/v2"
    rejected = valid_output(conflicting, conflict=True)
    rejected["historical_semantics"]["conflicts"] = []
    return {
        "valid": (valid, valid_output(valid)),
        "invalid": (valid, invalid),
        "ambiguous": (ambiguous, valid_output(ambiguous, ambiguous=True)),
        "conflicting": (conflicting, valid_output(conflicting, conflict=True)),
        "truncated": (valid, truncated),
        "unsupported": (valid, unsupported),
        "verifier_rejected": (conflicting, rejected),
    }
