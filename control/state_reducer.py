"""Minimal deterministic reducer for exact I03 extractor lifecycle outputs."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

PROJECT_STATE_SCHEMA = "hwm-project-state/v2"
PRODUCT_REPOSITORY = "Dsamofalov/hwm_predictor"
PRODUCT_REF = "refs/heads/main"
CHECKPOINT_WORKFLOW = ".github/workflows/ci.yml"
CORE_GATE = "HWM / Core"
FULL_GATE = "HWM / Full"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SENSITIVE_MARKERS = ("authorization:", "bearer ", "token=", "cookie:", "private key")
_ALLOWED_PROVENANCE_KEYS = {"kind", "repo", "sha", "reference"}
_ALLOWED_PROVENANCE_KINDS = {"git_ref", "github_actions_run", "evidence_manifest", "baseline"}
_ALLOWED_LIFECYCLE_KEYS = {
    "known": {"status", "sha", "provenance"},
    "unknown": {"status", "reason"},
    "error": {"status", "error"},
}
_CHECKPOINT_REFERENCE_RE = {
    gate: re.compile(
        rf"^workflow={re.escape(CHECKPOINT_WORKFLOW)};run=[1-9][0-9]*;suite=[1-9][0-9]*;"
        rf"gate={re.escape(gate)};check_run=[1-9][0-9]*;status_id=[1-9][0-9]*$"
    )
    for gate in (CORE_GATE, FULL_GATE)
}

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "project-state.v2.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


class ProjectStateReductionError(ValueError):
    """Input cannot be reduced without guessing or violating the v2 contract."""


def _safe_text(value: Any, *, field: str, single_line: bool) -> str:
    if not isinstance(value, str):
        raise ProjectStateReductionError(f"{field} must be a string")
    text = " ".join(value.replace("\r", " ").replace("\n", " ").split()) if single_line else value.strip()
    if not text:
        raise ProjectStateReductionError(f"{field} must be non-empty")
    lowered = text.lower()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        raise ProjectStateReductionError(f"{field} contains disclosure-unsafe material")
    if len(text) > 2000:
        text = text[:2000]
    return text


def _provenance(items: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ProjectStateReductionError(f"{field} must be a non-empty provenance list")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not set(item) <= _ALLOWED_PROVENANCE_KEYS:
            raise ProjectStateReductionError(f"{field}[{index}] is not contract-shaped provenance")
        if set(item) < {"kind", "repo", "sha"}:
            raise ProjectStateReductionError(f"{field}[{index}] is missing provenance identity")
        if item["kind"] not in _ALLOWED_PROVENANCE_KINDS:
            raise ProjectStateReductionError(f"{field}[{index}].kind is invalid")
        if not isinstance(item["repo"], str) or _REPO_RE.fullmatch(item["repo"]) is None:
            raise ProjectStateReductionError(f"{field}[{index}].repo is invalid")
        if not isinstance(item["sha"], str) or _SHA_RE.fullmatch(item["sha"]) is None:
            raise ProjectStateReductionError(f"{field}[{index}].sha is invalid")
        if "reference" in item:
            reference = _safe_text(item["reference"], field=f"{field}[{index}].reference", single_line=True)
            if len(reference) > 1000:
                raise ProjectStateReductionError(f"{field}[{index}].reference exceeds 1000 characters")
            if reference != item["reference"]:
                raise ProjectStateReductionError(f"{field}[{index}].reference must already be sanitized")
        result.append(copy.deepcopy(item))
    return result


def _require_product_head_binding(provenance: list[dict[str, Any]], *, sha: str) -> None:
    if any(
        item.get("kind") == "git_ref"
        and item.get("repo") == PRODUCT_REPOSITORY
        and item.get("sha") == sha
        and item.get("reference") == PRODUCT_REF
        for item in provenance
    ):
        return
    raise ProjectStateReductionError("product.head known lifecycle lacks exact product git_ref provenance binding")


def _require_checkpoint_binding(provenance: list[dict[str, Any]], *, sha: str, gate: str, field: str) -> None:
    reference_re = _CHECKPOINT_REFERENCE_RE[gate]
    if any(
        item.get("kind") == "github_actions_run"
        and item.get("repo") == PRODUCT_REPOSITORY
        and item.get("sha") == sha
        and isinstance(item.get("reference"), str)
        and reference_re.fullmatch(item["reference"]) is not None
        for item in provenance
    ):
        return
    raise ProjectStateReductionError(f"{field} known lifecycle lacks exact {gate} GitHub Actions provenance binding")


def _error(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"code", "message", "retryable"}:
        raise ProjectStateReductionError(f"{field} must contain code, message, retryable")
    code = value["code"]
    retryable = value["retryable"]
    if not isinstance(code, str) or _ERROR_CODE_RE.fullmatch(code) is None:
        raise ProjectStateReductionError(f"{field}.code is invalid")
    if not isinstance(retryable, bool):
        raise ProjectStateReductionError(f"{field}.retryable must be boolean")
    return {
        "code": code,
        "message": _safe_text(value["message"], field=f"{field}.message", single_line=True),
        "retryable": retryable,
    }


def _lifecycle(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectStateReductionError(f"{field} must be an object")
    status = value.get("status")
    if status not in _ALLOWED_LIFECYCLE_KEYS or set(value) != _ALLOWED_LIFECYCLE_KEYS[status]:
        raise ProjectStateReductionError(f"{field} lifecycle shape is inconsistent")
    if status == "known":
        sha = value["sha"]
        if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
            raise ProjectStateReductionError(f"{field}.sha must be exact lowercase 40-hex")
        return {
            "status": "known",
            "sha": sha,
            "provenance": _provenance(value["provenance"], field=f"{field}.provenance"),
        }
    if status == "unknown":
        return {"status": "unknown", "reason": _safe_text(value["reason"], field=f"{field}.reason", single_line=True)}
    return {"status": "error", "error": _error(value["error"], field=f"{field}.error")}


def _product_head(extractor: Any) -> dict[str, Any]:
    if not isinstance(extractor, dict):
        raise ProjectStateReductionError("product_head extractor result must be an object")
    status = extractor.get("status")
    envelope = {
        "known": {"status", "repository", "ref", "sha", "provenance"},
        "unknown": {"status", "repository", "ref", "reason"},
        "error": {"status", "repository", "ref", "error"},
    }
    if status not in envelope or set(extractor) != envelope[status]:
        raise ProjectStateReductionError("product_head extractor lifecycle shape is inconsistent")
    if extractor["repository"] != PRODUCT_REPOSITORY or extractor["ref"] != PRODUCT_REF:
        raise ProjectStateReductionError("product_head extractor identity does not match the exact product ref")
    payload = {key: copy.deepcopy(extractor[key]) for key in _ALLOWED_LIFECYCLE_KEYS[status]}
    result = _lifecycle(payload, field="product.head")
    if result["status"] == "known":
        _require_product_head_binding(result["provenance"], sha=result["sha"])
    return result


def _checkpoints(extractor: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    required = {"repository", "workflow", "last_core_green", "last_full_green"}
    if not isinstance(extractor, dict) or set(extractor) != required:
        raise ProjectStateReductionError("checkpoint extractor result must be the exact Core/Full envelope")
    if extractor["repository"] != PRODUCT_REPOSITORY or extractor["workflow"] != CHECKPOINT_WORKFLOW:
        raise ProjectStateReductionError("checkpoint extractor identity is inconsistent")
    core = _lifecycle(extractor["last_core_green"], field="product.last_core_green")
    full = _lifecycle(extractor["last_full_green"], field="product.last_full_green")
    if core["status"] == "known":
        _require_checkpoint_binding(core["provenance"], sha=core["sha"], gate=CORE_GATE, field="product.last_core_green")
    if full["status"] == "known":
        _require_checkpoint_binding(full["provenance"], sha=full["sha"], gate=FULL_GATE, field="product.last_full_green")
    return core, full


def _requirements(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectStateReductionError("requirements must be an object")
    result: dict[str, Any] = {}
    for key in sorted(value):
        item = value[key]
        if not isinstance(item, dict) or set(item) != {"status", "missing_gates"}:
            raise ProjectStateReductionError(f"requirements.{key} is not contract-shaped")
        gates = item["missing_gates"]
        if not isinstance(gates, list) or any(not isinstance(gate, str) or not gate for gate in gates):
            raise ProjectStateReductionError(f"requirements.{key}.missing_gates is invalid")
        if len(gates) != len(set(gates)):
            raise ProjectStateReductionError(f"requirements.{key}.missing_gates contains duplicates")
        result[key] = {"status": item["status"], "missing_gates": sorted(gates)}
    return result


def _tasks(value: Any) -> dict[str, list[int]]:
    if not isinstance(value, dict) or set(value) != {"ready", "claimed", "blocked"}:
        raise ProjectStateReductionError("tasks must contain ready, claimed, blocked")
    result: dict[str, list[int]] = {}
    for key in ("ready", "claimed", "blocked"):
        items = value[key]
        if (
            not isinstance(items, list)
            or any(not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in items)
            or len(items) != len(set(items))
        ):
            raise ProjectStateReductionError(f"tasks.{key} is invalid")
        result[key] = sorted(items)
    return result


def reduce_project_state(
    *,
    generated_at: str,
    provenance: list[dict[str, Any]],
    product_head: dict[str, Any],
    checkpoints: dict[str, Any],
    last_post_merge_green: dict[str, Any],
    last_live_evidenced: dict[str, Any],
    requirements: dict[str, Any],
    tasks: dict[str, Any],
    knowledge: dict[str, Any],
    graph: dict[str, Any],
) -> dict[str, Any]:
    """Reduce exact inputs into one schema-valid hwm-project-state/v2 object.

    Time and every non-extractor field are explicit inputs. The reducer never
    reads caches, current Git refs, environment state, or wall-clock time.
    """
    core, full = _checkpoints(checkpoints)
    state = {
        "schema": PROJECT_STATE_SCHEMA,
        "generated_at": generated_at,
        "provenance": _provenance(provenance, field="provenance"),
        "product": {
            "repo": PRODUCT_REPOSITORY,
            "head": _product_head(product_head),
            "last_core_green": core,
            "last_full_green": full,
            "last_post_merge_green": _lifecycle(last_post_merge_green, field="product.last_post_merge_green"),
            "last_live_evidenced": _lifecycle(last_live_evidenced, field="product.last_live_evidenced"),
        },
        "requirements": _requirements(requirements),
        "tasks": _tasks(tasks),
        "knowledge": copy.deepcopy(knowledge),
        "graph": copy.deepcopy(graph),
    }
    try:
        _VALIDATOR.validate(state)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ProjectStateReductionError(f"reduced project state is schema-invalid at {path}: {exc.message}") from exc
    return state
