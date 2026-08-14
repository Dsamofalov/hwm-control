#!/usr/bin/env python3
"""Deterministic bootstrap validator for temporary BUILD_STATUS lifecycle after I02."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ALLOWED_BUILD_STATUS_KEYS = {
    "current_infrastructure_milestone",
    "completed_task_ids",
    "active_task_ids",
    "current_schema_versions",
    "exact_relevant_heads",
    "blockers",
}
SOURCE_REPO = "Dsamofalov/hwm_predictor"
SOURCE_PATH = "docs/infra-bootstrap/I00_BASELINE.json"
SOURCE_MERGE = "8fd669336b36064e842252d69fb4016cc526a9d4"
SOURCE_BLOB = "856020a759e2018741d83af13f1536732f6a1ed7"
FUNCTIONAL_SHA = "3df0d5ee4434d3cc401dba1b765a4dca068c15c1"
BASELINE_SCHEMA = "hwm-infra-baseline/bootstrap-v0"
EXPECTED_SCHEMA_VERSIONS = {
    "bootstrap_baseline": BASELINE_SCHEMA,
    "job": "hwm-job/v1",
    "result": "hwm-result/v1",
    "task": "hwm-task/v1",
    "claim": "hwm-claim/v1",
    "knowledge_delta": "hwm-knowledge-delta/v1",
    "project_state": "hwm-project-state/v1",
}
COMPLETED_PREFIX = ["I00", "I01", "I02"]
MILESTONE_RE = re.compile(r"^I(\d{2})$")
TASK_ID_RE = re.compile(r"^I(\d{2})-(\d{4})$")


def load_json(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return None


def _validate_task_list(name: str, value: object, errors: list[str]) -> list[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"BUILD_STATUS {name} must be a list of strings")
        return None
    if len(value) != len(set(value)):
        errors.append(f"BUILD_STATUS {name} must contain unique task ids")
    return value


def _validate_build_status(status: dict, errors: list[str]) -> None:
    keys = set(status)
    if keys != ALLOWED_BUILD_STATUS_KEYS:
        errors.append(
            "BUILD_STATUS top-level keys must be exactly temporary bootstrap keys: "
            + ",".join(sorted(ALLOWED_BUILD_STATUS_KEYS))
        )

    milestone = status.get("current_infrastructure_milestone")
    milestone_match = MILESTONE_RE.fullmatch(milestone) if isinstance(milestone, str) else None
    if milestone_match is None:
        errors.append("BUILD_STATUS current infrastructure milestone must match IXX")
    else:
        milestone_number = int(milestone_match.group(1))
        if milestone_number < 3:
            errors.append("BUILD_STATUS current infrastructure milestone must not be earlier than I03")

    completed = _validate_task_list("completed_task_ids", status.get("completed_task_ids"), errors)
    active = _validate_task_list("active_task_ids", status.get("active_task_ids"), errors)

    if completed is not None:
        if completed[: len(COMPLETED_PREFIX)] != COMPLETED_PREFIX:
            errors.append("BUILD_STATUS completed task ids must start with exact I00,I01,I02 prefix")
        for task_id in completed[len(COMPLETED_PREFIX) :]:
            if TASK_ID_RE.fullmatch(task_id) is None:
                errors.append(f"BUILD_STATUS completed task id has invalid format: {task_id}")

    if active is not None:
        for task_id in active:
            match = TASK_ID_RE.fullmatch(task_id)
            if match is None:
                errors.append(f"BUILD_STATUS active task id has invalid format: {task_id}")
            elif milestone_match is not None and int(match.group(1)) != int(milestone_match.group(1)):
                errors.append(f"BUILD_STATUS active task {task_id} does not belong to current milestone {milestone}")

    if completed is not None and active is not None:
        overlap = sorted(set(completed).intersection(active))
        if overlap:
            errors.append("BUILD_STATUS completed and active task ids must not overlap: " + ",".join(overlap))

    if status.get("current_schema_versions") != EXPECTED_SCHEMA_VERSIONS:
        errors.append("BUILD_STATUS schema versions do not match I02 contracts")

    heads = status.get("exact_relevant_heads")
    if not isinstance(heads, dict):
        errors.append("BUILD_STATUS exact relevant heads must be an object")
    else:
        if heads.get("product_main_reference") != SOURCE_MERGE:
            errors.append("BUILD_STATUS product main reference mismatch")
        if heads.get("authoritative_functional_checkpoint") != FUNCTIONAL_SHA:
            errors.append("BUILD_STATUS functional checkpoint mismatch")

    if not isinstance(status.get("blockers"), list):
        errors.append("BUILD_STATUS blockers must be a list")


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    baseline_path = root / "baseline" / "I00_BASELINE.json"
    provenance_path = root / "baseline" / "I00_IMPORT_PROVENANCE.json"
    status_path = root / "BUILD_STATUS.json"
    spec_path = root / "docs" / "INFRA_SPEC.md"
    issue_template = root / ".github" / "ISSUE_TEMPLATE" / "infrastructure-task.md"

    for path in (baseline_path, provenance_path, status_path, spec_path, issue_template):
        if not path.is_file():
            errors.append(f"missing required bootstrap file: {path.relative_to(root)}")

    baseline = load_json(baseline_path, errors) if baseline_path.is_file() else None
    provenance = load_json(provenance_path, errors) if provenance_path.is_file() else None
    status = load_json(status_path, errors) if status_path.is_file() else None

    if baseline is not None:
        if baseline.get("schema") != BASELINE_SCHEMA:
            errors.append("baseline schema changed")
        if baseline.get("baseline_id") != "I00":
            errors.append("baseline id changed")
        if baseline.get("product_functional_development_frozen") is not True:
            errors.append("product freeze marker is not true")

    if baseline_path.is_file():
        actual = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
        print(f"actual_sha256={actual}")
    else:
        actual = None

    if provenance is not None:
        expected_pairs = {
            "source_repository": SOURCE_REPO,
            "source_path": SOURCE_PATH,
            "source_product_merge_commit": SOURCE_MERGE,
            "source_artifact_git_blob": SOURCE_BLOB,
            "imported_path": "baseline/I00_BASELINE.json",
        }
        for key, expected in expected_pairs.items():
            if provenance.get(key) != expected:
                errors.append(f"provenance {key} mismatch")
        if provenance.get("original_product_artifact_immutable") is not True:
            errors.append("provenance must mark original artifact immutable")
        if provenance.get("imported_copy_is_mutable_current_state") is not False:
            errors.append("imported baseline must not be mutable current state")
        if actual is not None and provenance.get("sha256") != actual:
            errors.append(
                f"baseline SHA-256 mismatch: recorded={provenance.get('sha256')} actual={actual}"
            )

    if isinstance(status, dict):
        _validate_build_status(status, errors)
    elif status is not None:
        errors.append("BUILD_STATUS must be a JSON object")

    if spec_path.is_file():
        spec = spec_path.read_text(encoding="utf-8")
        required_markers = [
            "# HWM Autonomous Development Infrastructure — Architecture & Bootstrap Plan",
            "# 7. Trust boundaries",
            "# 16. Infrastructure bootstrap without repeating the old mistakes",
            "# 30. Suggested initial infrastructure milestones",
            "# 36. Immediate next step",
        ]
        for marker in required_markers:
            if marker not in spec:
                errors.append(f"INFRA_SPEC missing authoritative marker: {marker}")

    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    errors = validate(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("bootstrap lifecycle validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
