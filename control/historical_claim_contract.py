#!/usr/bin/env python3
"""Deterministic Phase-6 historical claim/ledger contract primitives.

This module is intentionally not an importer. It validates already-resolved exact
Git source bindings and renders canonical materialized ledger bytes.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

CLAIM_SCHEMA = "hwm-historical-claim/v1"
CONFLICT_SCHEMA = "hwm-historical-conflicts/v1"
CLAIMS_PATH = "claims/claims.jsonl"
CONFLICTS_PATH = "claims/conflicts.json"
MATERIALIZED_REPOSITORY = "Dsamofalov/hwm-context"
INITIAL_REQUIRED_SOURCE_CLASSES = frozenset({"changelog", "specification_history"})
SOURCE_CLASSES = frozenset({
    "git_history", "changelog", "ability_changelog", "status_doc",
    "handoff_doc", "specification_history", "evidence_doc",
})
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CLAIM_ID_RE = re.compile(r"^hc1-[0-9a-f]{64}$")
FORBIDDEN_CURRENT_PREDICATE_PREFIX = "current."
FORBIDDEN_CURRENT_SUBJECT_PREFIX = "current:"


class HistoricalClaimContractError(ValueError):
    """Fail-closed contract violation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identity_payload(claim: Mapping[str, Any]) -> dict[str, Any]:
    provenance = claim["provenance"]
    return {
        "identity_schema": "hwm-historical-claim-identity/v1",
        "subject": claim["subject"],
        "predicate": claim["predicate"],
        "value": claim["value"],
        "source": {
            "repository": provenance["repository"],
            "commit": provenance["commit"],
            "path": provenance["path"],
            "locator": provenance["locator"],
            "blob_sha": provenance["blob_sha"],
            "content_sha256": provenance["content_sha256"],
        },
        "validity": claim["validity"],
    }


def compute_claim_id(claim: Mapping[str, Any]) -> str:
    payload = canonical_json(_identity_payload(claim)).encode("utf-8")
    return "hc1-" + hashlib.sha256(payload).hexdigest()


def compute_conflict_id(a: str, b: str) -> str:
    pair = sorted((a, b))
    if pair[0] == pair[1] or not all(CLAIM_ID_RE.fullmatch(x) for x in pair):
        raise HistoricalClaimContractError("conflict requires two distinct valid claim ids")
    raw = canonical_json({"claim_ids": pair}).encode("utf-8")
    return "hcf1-" + hashlib.sha256(raw).hexdigest()


def git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise HistoricalClaimContractError("validity timestamps must be UTC RFC3339 strings ending in Z or null")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise HistoricalClaimContractError("invalid validity timestamp") from exc


def validate_claim_semantics(claim: Mapping[str, Any]) -> None:
    if claim.get("schema") != CLAIM_SCHEMA or claim.get("authority") != "historical":
        raise HistoricalClaimContractError("historical claim schema/authority mismatch")
    subject, predicate = claim.get("subject"), claim.get("predicate")
    if not isinstance(subject, str) or not subject or subject.startswith(FORBIDDEN_CURRENT_SUBJECT_PREFIX):
        raise HistoricalClaimContractError("historical claim cannot target current-state authority")
    if not isinstance(predicate, str) or not predicate or predicate.startswith(FORBIDDEN_CURRENT_PREDICATE_PREFIX):
        raise HistoricalClaimContractError("historical claim cannot target current-state authority")
    if not isinstance(claim.get("value"), str) or not claim["value"]:
        raise HistoricalClaimContractError("historical claim value must be a non-empty string")
    provenance = claim.get("provenance")
    if not isinstance(provenance, Mapping):
        raise HistoricalClaimContractError("missing provenance")
    if provenance.get("source_class") not in SOURCE_CLASSES:
        raise HistoricalClaimContractError("unknown historical source class")
    if not isinstance(provenance.get("repository"), str) or not REPO_RE.fullmatch(provenance["repository"]):
        raise HistoricalClaimContractError("malformed source repository")
    if not isinstance(provenance.get("commit"), str) or not SHA40_RE.fullmatch(provenance["commit"]):
        raise HistoricalClaimContractError("malformed source commit")
    path = provenance.get("path")
    if (not isinstance(path, str) or not path or path.startswith("/") or path.endswith("/") or "//" in path
            or any(part == ".." for part in path.split("/"))):
        raise HistoricalClaimContractError("malformed source path")
    if not isinstance(provenance.get("blob_sha"), str) or not SHA40_RE.fullmatch(provenance["blob_sha"]):
        raise HistoricalClaimContractError("malformed source blob sha")
    if not isinstance(provenance.get("content_sha256"), str) or not SHA64_RE.fullmatch(provenance["content_sha256"]):
        raise HistoricalClaimContractError("malformed source content digest")
    locator = provenance.get("locator")
    if not isinstance(locator, Mapping) or locator.get("kind") not in {"line_range", "symbol"}:
        raise HistoricalClaimContractError("malformed source locator")
    if locator["kind"] == "line_range":
        start, end = locator.get("start_line"), locator.get("end_line")
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start < 1 or end < start:
            raise HistoricalClaimContractError("invalid source line range")
    else:
        if not isinstance(locator.get("symbol"), str) or not locator["symbol"]:
            raise HistoricalClaimContractError("invalid stable symbol identity")
    validity = claim.get("validity")
    if not isinstance(validity, Mapping) or set(validity) != {"valid_from", "valid_until"}:
        raise HistoricalClaimContractError("invalid validity interval")
    start, end = _parse_time(validity["valid_from"]), _parse_time(validity["valid_until"])
    if start is not None and end is not None and end < start:
        raise HistoricalClaimContractError("validity interval ends before it begins")
    status = claim.get("status")
    if status not in {"supported", "superseded", "contradicted", "unverified"}:
        raise HistoricalClaimContractError("invalid historical claim status")
    relations = claim.get("relations")
    if not isinstance(relations, Mapping) or set(relations) != {"supersedes", "superseded_by", "conflicts_with"}:
        raise HistoricalClaimContractError("invalid historical claim relations")
    for key in relations:
        ids = relations[key]
        if not isinstance(ids, list) or len(ids) != len(set(ids)) or not all(isinstance(x, str) and CLAIM_ID_RE.fullmatch(x) for x in ids):
            raise HistoricalClaimContractError(f"invalid {key} relation list")
        if claim.get("claim_id") in ids:
            raise HistoricalClaimContractError("self relations are forbidden")
    if status == "supported" and (relations["superseded_by"] or relations["conflicts_with"]):
        raise HistoricalClaimContractError("supported claim relation/status mismatch")
    if status == "superseded" and (not relations["superseded_by"] or relations["conflicts_with"]):
        raise HistoricalClaimContractError("superseded claim requires superseded_by and no conflict")
    if status == "contradicted" and (relations["supersedes"] or relations["superseded_by"] or not relations["conflicts_with"]):
        raise HistoricalClaimContractError("contradicted claim requires only conflict links")
    if status == "unverified" and any(relations.values()):
        raise HistoricalClaimContractError("unverified claim cannot participate in support/supersession/conflict relations")
    claim_id = claim.get("claim_id")
    if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id) or claim_id != compute_claim_id(claim):
        raise HistoricalClaimContractError("claim_id does not match deterministic identity payload")


def verify_source_binding(
    claim: Mapping[str, Any], *, repository: str, commit: str, path: str,
    source_bytes: bytes | None, revision_candidates: int = 1,
    resolved_symbols: Sequence[str] = (),
) -> None:
    """Verify one independently resolved exact source revision; never resolve/guess it."""
    validate_claim_semantics(claim)
    if revision_candidates == 0 or source_bytes is None:
        raise HistoricalClaimContractError("source revision is missing")
    if revision_candidates != 1:
        raise HistoricalClaimContractError("source revision is ambiguous")
    provenance = claim["provenance"]
    if (repository, commit, path) != (provenance["repository"], provenance["commit"], provenance["path"]):
        raise HistoricalClaimContractError("source revision is stale or mismatched")
    if git_blob_sha(source_bytes) != provenance["blob_sha"] or content_sha256(source_bytes) != provenance["content_sha256"]:
        raise HistoricalClaimContractError("source content binding mismatch")
    locator = provenance["locator"]
    if locator["kind"] == "line_range":
        line_count = len(source_bytes.splitlines())
        if locator["end_line"] > line_count:
            raise HistoricalClaimContractError("source line range does not exist in exact content")
    else:
        matches = sum(1 for symbol in resolved_symbols if symbol == locator["symbol"])
        if matches != 1:
            raise HistoricalClaimContractError("stable symbol identity is missing or ambiguous")


def _deduplicate(claims: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    serialized: dict[str, str] = {}
    for raw in claims:
        claim = dict(raw)
        validate_claim_semantics(claim)
        cid = claim["claim_id"]
        current = canonical_json(claim)
        if cid in by_id and serialized[cid] != current:
            raise HistoricalClaimContractError("same claim_id has inconsistent duplicate serialization")
        if cid not in by_id:
            by_id[cid] = claim
            serialized[cid] = current
    return by_id


def validate_ledger(claims: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = _deduplicate(claims)
    for cid, claim in by_id.items():
        rel = claim["relations"]
        for target in rel["supersedes"]:
            if target not in by_id:
                raise HistoricalClaimContractError("dangling supersession target")
            if cid not in by_id[target]["relations"]["superseded_by"] or by_id[target]["status"] != "superseded":
                raise HistoricalClaimContractError("supersession relation is not mirrored by retained old claim")
        for source in rel["superseded_by"]:
            if source not in by_id or cid not in by_id[source]["relations"]["supersedes"]:
                raise HistoricalClaimContractError("dangling or ambiguous superseded_by relation")
        for other in rel["conflicts_with"]:
            if other not in by_id:
                raise HistoricalClaimContractError("dangling contradiction target")
            if cid not in by_id[other]["relations"]["conflicts_with"]:
                raise HistoricalClaimContractError("contradiction relation must be symmetric")
            if claim["status"] != "contradicted" or by_id[other]["status"] != "contradicted":
                raise HistoricalClaimContractError("conflict-linked claims must remain separately contradicted")
    return [by_id[cid] for cid in sorted(by_id)]


def build_conflict_index(claims: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = validate_ledger(claims)
    pairs: set[tuple[str, str]] = set()
    for claim in ordered:
        for other in claim["relations"]["conflicts_with"]:
            pairs.add(tuple(sorted((claim["claim_id"], other))))
    conflicts = [
        {"conflict_id": compute_conflict_id(a, b), "claim_ids": [a, b]}
        for a, b in sorted(pairs)
    ]
    return {"schema": CONFLICT_SCHEMA, "conflicts": conflicts}


def materialize_ledger(claims: Iterable[Mapping[str, Any]]) -> dict[str, bytes]:
    ordered = validate_ledger(claims)
    claims_bytes = b"".join((canonical_json(claim) + "\n").encode("utf-8") for claim in ordered)
    conflicts_bytes = (canonical_json(build_conflict_index(ordered)) + "\n").encode("utf-8")
    return {CLAIMS_PATH: claims_bytes, CONFLICTS_PATH: conflicts_bytes}
