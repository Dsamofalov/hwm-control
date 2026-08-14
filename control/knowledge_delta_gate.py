#!/usr/bin/env python3
"""Deterministic Knowledge Delta repository gate for I06.

The gate preserves the merged ``hwm-knowledge-delta/v1`` serialization contract
and adds repository policy around canonical storage and task/Issue binding.  It is
read-only: it does not claim tasks, mutate Issues, schedule work, or generate the
I07 bootstrap.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

DELTA_DIRECTORY = "knowledge-deltas"
DELTA_SCHEMA_PATH = Path("schemas") / "knowledge-delta.v1.schema.json"
TASK_ID_RE = re.compile(r"^I(?P<milestone>\d{2})-(?P<issue>\d{4})$")
DELTA_FILE_RE = re.compile(r"^(?P<task>I\d{2}-\d{4})\.json$")
REQUIRED_FROM_MILESTONE = 6


def _load_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid Knowledge Delta JSON {path}: {exc}")
        return None


def _task_parts(task_id: str, errors: list[str], *, source: str) -> tuple[int, int] | None:
    if not isinstance(task_id, str):
        errors.append(f"{source} task id must be a string")
        return None
    match = TASK_ID_RE.fullmatch(task_id)
    if match is None:
        errors.append(f"{source} task id has invalid format: {task_id!r}")
        return None
    return int(match.group("milestone")), int(match.group("issue"))


def _status_task_ids(status: Mapping[str, Any], errors: list[str]) -> tuple[str, ...]:
    required: list[str] = []
    for field in ("completed_task_ids", "active_task_ids"):
        value = status.get(field)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            errors.append(f"BUILD_STATUS {field} must be a sequence for Knowledge Delta gating")
            continue
        for raw_task_id in value:
            if raw_task_id in {"I00", "I01", "I02"}:
                continue
            parts = _task_parts(raw_task_id, errors, source=f"BUILD_STATUS {field}")
            if parts is None:
                continue
            milestone, _issue = parts
            if milestone >= REQUIRED_FROM_MILESTONE:
                required.append(raw_task_id)
    if len(required) != len(set(required)):
        errors.append("Knowledge Delta required task ids must be unique")
    return tuple(required)


def _load_validator(root: Path, errors: list[str]) -> Draft202012Validator | None:
    schema_path = root / DELTA_SCHEMA_PATH
    if not schema_path.is_file():
        errors.append(f"missing Knowledge Delta schema: {DELTA_SCHEMA_PATH.as_posix()}")
        return None
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid Knowledge Delta schema JSON {DELTA_SCHEMA_PATH.as_posix()}: {exc}")
        return None
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        errors.append(f"invalid Knowledge Delta schema: {exc.message}")
        return None
    return Draft202012Validator(schema)


def _policy_validate_delta(data: Mapping[str, Any], task_key: str, errors: list[str]) -> None:
    parts = _task_parts(task_key, errors, source="Knowledge Delta filename")
    if parts is None:
        return
    _milestone, expected_issue = parts
    actual_issue = data.get("task_id")
    if actual_issue != expected_issue:
        errors.append(
            f"Knowledge Delta {task_key} is bound to Issue #{expected_issue}, "
            f"but delta task_id is {actual_issue!r}"
        )

    decisions = data.get("decisions")
    if isinstance(decisions, list) and not decisions:
        errors.append(f"Knowledge Delta {task_key} must record at least one rationale-bearing decision")

    verified_facts = data.get("verified_facts")
    if isinstance(verified_facts, list) and not verified_facts:
        errors.append(f"Knowledge Delta {task_key} must record at least one verified fact with provenance")

    changed_components = data.get("changed_components")
    if isinstance(changed_components, list) and not changed_components:
        errors.append(f"Knowledge Delta {task_key} must record at least one changed component")

    tests = data.get("tests")
    if isinstance(tests, list) and not tests:
        errors.append(f"Knowledge Delta {task_key} must record at least one test result entry")


def validate_repository_knowledge_deltas(root: Path, status: Mapping[str, Any] | None = None) -> list[str]:
    """Return fail-closed Knowledge Delta gate errors for one repository snapshot.

    Required tasks are derived only from durable ``BUILD_STATUS`` task ids.  The
    best-effort milestone UI state is deliberately not read.  Every I06+ active or
    completed task requires exactly its canonical file
    ``knowledge-deltas/<IXX-NNNN>.json``.  All JSON delta files are schema-checked,
    bound to the Issue number encoded by the canonical task id, and checked for
    duplicate Issue bindings.
    """

    root = Path(root)
    errors: list[str] = []

    if status is None:
        status_path = root / "BUILD_STATUS.json"
        if not status_path.is_file():
            return ["missing BUILD_STATUS.json for Knowledge Delta gating"]
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return [f"invalid BUILD_STATUS.json for Knowledge Delta gating: {exc}"]
    if not isinstance(status, Mapping):
        return ["BUILD_STATUS must be an object for Knowledge Delta gating"]

    required_task_ids = _status_task_ids(status, errors)
    validator = _load_validator(root, errors)

    delta_root = root / DELTA_DIRECTORY
    if not delta_root.exists():
        if required_task_ids:
            errors.append(
                "missing knowledge-deltas directory for required tasks: "
                + ",".join(sorted(required_task_ids))
            )
        return errors
    if not delta_root.is_dir():
        errors.append("knowledge-deltas must be a directory")
        return errors

    canonical_files: dict[str, Path] = {}
    issue_bindings: dict[int, str] = {}
    for path in sorted(delta_root.rglob("*.json")):
        if not path.is_file():
            continue
        relative = path.relative_to(delta_root)
        if path.parent != delta_root:
            errors.append(f"non-canonical nested Knowledge Delta path: {relative.as_posix()}")
            continue
        match = DELTA_FILE_RE.fullmatch(path.name)
        if match is None:
            errors.append(f"non-canonical Knowledge Delta filename: {path.name}")
            continue

        task_key = match.group("task")
        canonical_files[task_key] = path
        data = _load_json(path, errors)
        if not isinstance(data, Mapping):
            if data is not None:
                errors.append(f"Knowledge Delta {task_key} must be a JSON object")
            continue

        if validator is not None:
            schema_errors = sorted(
                validator.iter_errors(data),
                key=lambda item: tuple(str(part) for part in item.absolute_path),
            )
            for error in schema_errors:
                location = ".".join(str(item) for item in error.absolute_path) or "<root>"
                errors.append(f"Knowledge Delta {task_key} schema error at {location}: {error.message}")

        _policy_validate_delta(data, task_key, errors)
        issue = data.get("task_id")
        if isinstance(issue, int) and not isinstance(issue, bool):
            prior = issue_bindings.get(issue)
            if prior is not None and prior != task_key:
                errors.append(
                    f"ambiguous Knowledge Delta Issue #{issue} binding: {prior} and {task_key}"
                )
            else:
                issue_bindings[issue] = task_key

    for task_id in sorted(set(required_task_ids)):
        if task_id not in canonical_files:
            errors.append(
                f"missing required Knowledge Delta for {task_id}: "
                f"{DELTA_DIRECTORY}/{task_id}.json"
            )

    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    errors = validate_repository_knowledge_deltas(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("knowledge delta gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
