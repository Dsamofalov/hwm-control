#!/usr/bin/env python3
"""Minimal deterministic I01 bootstrap validator. Not a project state builder."""
from __future__ import annotations

import hashlib
import json
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


def load_json(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return None


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    baseline_path = root / "baseline" / "I00_BASELINE.json"
    provenance_path = root / "baseline" / "I00_IMPORT_PROVENANCE.json"
    status_path = root / "BUILD_STATUS.json"
    spec_path = root / "docs" / "INFRA_SPEC.md"
    issue_template = root / ".github" / "ISSUE_TEMPLATE" / "infrastructure-task.md"

    for path in (baseline_path, provenance_path, status_path, spec_path, issue_template):
        if not path.is_file():
            errors.append(f"missing required I01 file: {path.relative_to(root)}")

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

    if status is not None:
        keys = set(status)
        if keys != ALLOWED_BUILD_STATUS_KEYS:
            errors.append(
                "BUILD_STATUS top-level keys must be exactly temporary bootstrap keys: "
                + ",".join(sorted(ALLOWED_BUILD_STATUS_KEYS))
            )
        if status.get("current_infrastructure_milestone") != "I01":
            errors.append("BUILD_STATUS milestone must remain I01 while I01 blockers exist")
        if status.get("completed_task_ids") != ["I00"]:
            errors.append("only I00 may be completed until I01 acceptance is met")
        if status.get("active_task_ids") != ["I01"]:
            errors.append("I01 must be the only active bootstrap task")
        if status.get("current_schema_versions") != {"bootstrap_baseline": BASELINE_SCHEMA}:
            errors.append("BUILD_STATUS schema versions exceed I01 bootstrap scope")
        heads = status.get("exact_relevant_heads", {})
        if heads.get("product_main_reference") != SOURCE_MERGE:
            errors.append("BUILD_STATUS product main reference mismatch")
        if heads.get("authoritative_functional_checkpoint") != FUNCTIONAL_SHA:
            errors.append("BUILD_STATUS functional checkpoint mismatch")
        if not status.get("blockers"):
            errors.append("BUILD_STATUS must record real unresolved I01 blockers")

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
    print("I01 bootstrap validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
