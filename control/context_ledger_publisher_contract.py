#!/usr/bin/env python3
"""Forward-only I08-P1 contract for trusted hwm-context historical-ledger publication.

This module is contract/policy only. The privileged runtime is repository-local in
Dsamofalov/hwm-context and uses that repository's job-scoped GITHUB_TOKEN.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping

REQUEST_SCHEMA = "hwm-historical-ledger-publish-request/v1"
RESULT_SCHEMA = "hwm-historical-ledger-publish-result/v1"
BOOTSTRAP_REQUEST_SCHEMA = "hwm-publish-request/bootstrap-v1"
ALLOWED_REPOSITORY = "Dsamofalov/hwm-context"
TRANSPORT_ISSUE = 2
ALLOWED_AUTHOR = {"login": "Dsamofalov", "github_account_id": 25666939}
DEFAULT_BRANCH = "main"
ALLOWED_PATHS = frozenset({"claims/claims.jsonl", "claims/conflicts.json"})
CI_WORKFLOW = "repository-bootstrap-ci.yml"
REQUIRED_CHECK = "bootstrap"
MAX_BLOB_BYTES = 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQ_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,95}$")
BRANCH_RE = re.compile(r"^publisher/historical-ledger/[a-z0-9][a-z0-9._-]{7,95}$")
FORBIDDEN_PUBLIC_MARKERS = (
    b"-----begin private key-----", b"-----begin openssh private key-----",
    b"github_pat_", b"ghp_", b"authorization: bearer ", b"cookie:",
)

class HistoricalLedgerPublishError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def request_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def validate_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise HistoricalLedgerPublishError("INVALID_SCHEMA", "request must be an object")
    top = {"schema", "request_id", "repository", "transport_issue", "expected_base", "publication_branch", "changes", "ci"}
    if set(request) != top:
        raise HistoricalLedgerPublishError("INVALID_SCHEMA", "request fields do not match historical-ledger-v1")
    if request.get("schema") == BOOTSTRAP_REQUEST_SCHEMA:
        raise HistoricalLedgerPublishError("INVALID_SCHEMA", "bootstrap-v1 is not valid for hwm-context publication")
    if request.get("schema") != REQUEST_SCHEMA:
        raise HistoricalLedgerPublishError("INVALID_SCHEMA", "request schema mismatch")
    if not isinstance(request.get("request_id"), str) or REQ_RE.fullmatch(request["request_id"]) is None:
        raise HistoricalLedgerPublishError("INVALID_SCHEMA", "request_id is malformed")
    if request.get("repository") != ALLOWED_REPOSITORY:
        raise HistoricalLedgerPublishError("REPOSITORY_NOT_ALLOWED", "wrong repository")
    if request.get("transport_issue") != TRANSPORT_ISSUE:
        raise HistoricalLedgerPublishError("INVALID_TRANSPORT", "wrong transport Issue")
    if not _sha(request.get("expected_base")):
        raise HistoricalLedgerPublishError("INVALID_SCHEMA", "expected_base must be exact SHA")
    branch = request.get("publication_branch")
    if branch in {"main", DEFAULT_BRANCH} or not isinstance(branch, str) or BRANCH_RE.fullmatch(branch) is None:
        raise HistoricalLedgerPublishError("FORBIDDEN_TARGET", "publication branch is not scoped")
    changes = request.get("changes")
    if not isinstance(changes, list) or len(changes) != 2:
        raise HistoricalLedgerPublishError("INVALID_SCHEMA", "exactly two changes required")
    seen: set[str] = set()
    for change in changes:
        if not isinstance(change, dict):
            raise HistoricalLedgerPublishError("INVALID_SCHEMA", "change must be object")
        op = change.get("op")
        expected_keys = {"op", "path", "blob_sha", "mode"} if op == "add" else {"op", "path", "blob_sha", "mode", "expected_blob_sha"} if op == "replace" else set()
        if not expected_keys or set(change) != expected_keys:
            raise HistoricalLedgerPublishError("INVALID_SCHEMA", "invalid add/replace shape")
        path = change.get("path")
        if path not in ALLOWED_PATHS:
            raise HistoricalLedgerPublishError("FORBIDDEN_PATH", "path is outside canonical historical-ledger outputs")
        if path in seen:
            raise HistoricalLedgerPublishError("INVALID_SCHEMA", "duplicate path")
        seen.add(path)
        if change.get("mode") != "100644":
            raise HistoricalLedgerPublishError("BLOB_NOT_REGULAR", "only regular 100644 blobs are valid")
        if not _sha(change.get("blob_sha")):
            raise HistoricalLedgerPublishError("INVALID_SCHEMA", "blob_sha is malformed")
        if op == "replace" and not _sha(change.get("expected_blob_sha")):
            raise HistoricalLedgerPublishError("INVALID_SCHEMA", "replace expected_blob_sha is malformed")
    if seen != ALLOWED_PATHS:
        raise HistoricalLedgerPublishError("FORBIDDEN_PATH", "both canonical paths are required exactly once")
    if request.get("ci") != {"workflow": CI_WORKFLOW, "required_check": REQUIRED_CHECK}:
        raise HistoricalLedgerPublishError("INVALID_SCHEMA", "exact bootstrap workflow/check are required")
    return request


def verify_expected_base(request: Mapping[str, Any], observed_protected_head: str) -> None:
    if request.get("expected_base") != observed_protected_head:
        raise HistoricalLedgerPublishError("EXPECTED_HEAD_MISMATCH", "protected main is stale relative to expected_base")


def validate_public_blob(data: bytes) -> None:
    if len(data) > MAX_BLOB_BYTES or b"\x00" in data:
        raise HistoricalLedgerPublishError("UNSAFE_PAYLOAD", "candidate blob violates bounded text payload policy")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HistoricalLedgerPublishError("UNSAFE_PAYLOAD", "candidate blob is not UTF-8") from exc
    lowered = data.lower()
    if any(marker in lowered for marker in FORBIDDEN_PUBLIC_MARKERS):
        raise HistoricalLedgerPublishError("UNSAFE_PAYLOAD", "candidate blob matches forbidden credential marker")


def classify_replay(request: Mapping[str, Any], prior_requests: Iterable[Mapping[str, Any]], prior_results: Iterable[Mapping[str, Any]]) -> str:
    fp = request_fingerprint(request)
    request_id = request.get("request_id")
    for prior in prior_requests:
        if prior.get("request_id") == request_id and request_fingerprint(prior) != fp:
            raise HistoricalLedgerPublishError("REQUEST_ID_REUSE", "request_id reused with changed payload")
    for result in prior_results:
        if result.get("request_id") != request_id:
            continue
        if result.get("request_fingerprint") != fp:
            raise HistoricalLedgerPublishError("REQUEST_ID_REUSE", "request_id already has result for changed payload")
        return "replay"
    return "new"


def result_success(request: Mapping[str, Any], *, commit_sha: str, pr_number: int, run_id: int) -> dict[str, Any]:
    validate_request(dict(request))
    if not _sha(commit_sha) or not isinstance(pr_number, int) or pr_number < 1 or not isinstance(run_id, int) or run_id < 1:
        raise HistoricalLedgerPublishError("INVALID_RESULT", "success evidence is malformed")
    return {
        "schema": RESULT_SCHEMA,
        "request_id": request["request_id"],
        "status": "success",
        "repository": ALLOWED_REPOSITORY,
        "transport_issue": TRANSPORT_ISSUE,
        "expected_base": request["expected_base"],
        "publication_branch": request["publication_branch"],
        "request_fingerprint": request_fingerprint(request),
        "idempotent_replay": False,
        "commit_sha": commit_sha,
        "pr_number": pr_number,
        "ci_dispatch": {"workflow": CI_WORKFLOW, "run_id": run_id, "head_sha": commit_sha, "required_check": REQUIRED_CHECK},
        "error": None,
    }
