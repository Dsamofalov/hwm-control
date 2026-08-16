import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control import task_context_compiler as tc

CONTROL_SHA = "1" * 40
CONTEXT_SHA = "2" * 40
PRODUCT_SHA = "3" * 40
KD_SHA = "4" * 40
OTHER_SHA = "5" * 40


def jbytes(value, lf=False):
    return tc.canonical_bytes(value, trailing_lf=lf)


def project_state_bytes():
    prov = {"kind": "git_ref", "repo": "Dsamofalov/hwm-control", "sha": CONTROL_SHA}
    checkpoint = {"status": "unknown", "reason": "No exact checkpoint is bound in this fixture."}
    value = {
        "schema": "hwm-project-state/v2",
        "generated_at": "2026-08-16T06:00:00Z",
        "provenance": [prov],
        "product": {
            "repo": "Dsamofalov/hwm_predictor",
            "head": {"status": "known", "sha": PRODUCT_SHA, "provenance": [prov]},
            "last_core_green": checkpoint,
            "last_full_green": checkpoint,
            "last_post_merge_green": checkpoint,
            "last_live_evidenced": checkpoint,
        },
        "requirements": {},
        "tasks": {"ready": [47], "claimed": [46], "blocked": [48, 49, 50]},
        "knowledge": {"status": "healthy", "source_sha": CONTROL_SHA, "unresolved_conflicts": 0},
        "graph": {"status": "unknown", "reason": "Graphify belongs to I10."},
    }
    return jbytes(value, lf=True)


def historical_claims_bytes():
    claim = {
        "schema": "hwm-historical-claim/v1",
        "claim_id": "hc1-" + "a" * 64,
        "authority": "historical",
        "subject": "historical:solver",
        "predicate": "historical.note",
        "value": "Historical evidence only.",
        "provenance": {
            "source_class": "git_history",
            "repository": "Dsamofalov/hwm_predictor",
            "commit": PRODUCT_SHA,
            "path": "solver.py",
            "locator": {"kind": "line_range", "start_line": 1, "end_line": 1},
            "blob_sha": "6" * 40,
            "content_sha256": "a" * 64,
        },
        "validity": {"valid_from": None, "valid_until": None},
        "status": "unverified",
        "relations": {"supersedes": [], "superseded_by": [], "conflicts_with": []},
    }
    return jbytes(claim, lf=True)


def historical_conflicts_bytes():
    return jbytes({"schema": "hwm-historical-conflicts/v1", "conflicts": []}, lf=True)


def knowledge_delta_bytes(task_id=45):
    return jbytes({
        "schema": "hwm-knowledge-delta/v1",
        "task_id": task_id,
        "goal": "Bound deterministic rationale.",
        "verified_facts": [],
        "decisions": [],
        "rejected_alternatives": [],
        "changed_components": [],
        "tests": [],
        "evidence": [],
        "followups": [],
        "unresolved": [],
    }, lf=True)


def issue_raw():
    return {
        "title": "I09-P1 compiler fixture",
        "body": "Deterministic public Issue body.",
        "updated_at": "2026-08-16T06:00:00Z",
        "state": "open",
        "state_reason": None,
        "labels": ["trusted", "claimed", "infrastructure"],
        "assignees": [],
        "milestone_number": 10,
    }


def bind_blob(data):
    return tc.git_blob_sha(data), tc.sha256_bytes(data)


class FakeProvider:
    def __init__(self, *, product_content=b"print('exact')\n"):
        self.heads = {
            "Dsamofalov/hwm-control": CONTROL_SHA,
            "Dsamofalov/hwm-context": CONTEXT_SHA,
            "Dsamofalov/hwm_predictor": OTHER_SHA,
        }
        self.issue = issue_raw()
        self.calls = []
        self.blobs = {}
        self.unknown = set()
        self.errors = {}
        self.add("Dsamofalov/hwm-control", CONTROL_SHA, "state/project-state.json", project_state_bytes())
        self.add("Dsamofalov/hwm-context", CONTEXT_SHA, "claims/claims.jsonl", historical_claims_bytes())
        self.add("Dsamofalov/hwm-context", CONTEXT_SHA, "claims/conflicts.json", historical_conflicts_bytes())
        self.add("Dsamofalov/hwm-control", KD_SHA, "knowledge-deltas/I09-0045.json", knowledge_delta_bytes())
        self.add("Dsamofalov/hwm_predictor", PRODUCT_SHA, "solver.py", product_content)

    def add(self, repo, commit, path, data):
        self.blobs[(repo, commit, path)] = tc.ExactBlob(data, tc.git_blob_sha(data))

    def observe_head(self, repository):
        self.calls.append(("head", repository))
        return self.heads[repository]

    def fetch_issue(self, repository, issue_number):
        self.calls.append(("issue", repository, issue_number))
        return copy.deepcopy(self.issue)

    def fetch_blob(self, repository, commit, path):
        key = (repository, commit, path)
        self.calls.append(("blob",) + key)
        if key in self.unknown:
            raise tc.OptionalSourceUnknown("Optional exact source was not deterministically available.")
        if key in self.errors:
            raise self.errors[key]
        if key not in self.blobs:
            raise tc.OptionalSourceUnknown("Exact source is missing.")
        return self.blobs[key]


def base_request(provider=None, *, product_required=False, truncation_allowed=True):
    provider = provider or FakeProvider()
    raw = provider.issue
    snapshot = tc._derive_issue_snapshot(raw, "Dsamofalov/hwm-control", 46)
    state_blob, state_sha = bind_blob(provider.blobs[("Dsamofalov/hwm-control", CONTROL_SHA, "state/project-state.json")].content)
    claims_blob, claims_sha = bind_blob(provider.blobs[("Dsamofalov/hwm-context", CONTEXT_SHA, "claims/claims.jsonl")].content)
    conflicts_blob, conflicts_sha = bind_blob(provider.blobs[("Dsamofalov/hwm-context", CONTEXT_SHA, "claims/conflicts.json")].content)
    kd_blob, kd_content = bind_blob(provider.blobs[("Dsamofalov/hwm-control", KD_SHA, "knowledge-deltas/I09-0045.json")].content)
    product_blob, product_content = bind_blob(provider.blobs[("Dsamofalov/hwm_predictor", PRODUCT_SHA, "solver.py")].content)
    req = {
        "schema": "hwm-task-context-request/v1",
        "request_id": "tcr1-" + "0" * 64,
        "task": {"task_key": "I09-0046", "issue_repository": "Dsamofalov/hwm-control", "issue_number": 46},
        "issue_snapshot": snapshot,
        "product": {"repository": "Dsamofalov/hwm_predictor", "commit": PRODUCT_SHA, "head_policy": "exact_revision_only"},
        "project_state": {
            "schema": "hwm-project-state/v2", "repository": "Dsamofalov/hwm-control", "commit": CONTROL_SHA,
            "path": "state/project-state.json", "blob_sha": state_blob, "content_sha256": state_sha,
        },
        "historical_ledger": {
            "repository": "Dsamofalov/hwm-context", "commit": CONTEXT_SHA, "head_policy": "must_equal_current",
            "claims": {"path": "claims/claims.jsonl", "blob_sha": claims_blob, "content_sha256": claims_sha},
            "conflicts": {"path": "claims/conflicts.json", "blob_sha": conflicts_blob, "content_sha256": conflicts_sha},
        },
        "knowledge_deltas": {"set_mode": "explicit_exact_set", "inputs": [{
            "task_key": "I09-0045", "task_id": 45, "repository": "Dsamofalov/hwm-control", "commit": KD_SHA,
            "path": "knowledge-deltas/I09-0045.json", "blob_sha": kd_blob, "content_sha256": kd_content,
        }]},
        "product_sources": {"set_mode": "explicit_exact_set", "inputs": [{
            "source_id": "product.solver", "path": "solver.py", "blob_sha": product_blob,
            "content_sha256": product_content, "media_type": "text/x-python", "priority": 10,
            "required": product_required, "truncation_allowed": truncation_allowed,
        }]},
        "selection": {
            "algorithm": "hwm-task-context-selection/v1",
            "authority_order": tc.AUTHORITY_ORDER,
            "ranking_keys": ["required_desc", "authority_order", "priority_asc", "source_id_asc"],
            "tie_break": "source_id_lexicographic",
            "dedup_identity": "authority_class+media_type+content_sha256",
            "budget_metric": "utf8_content_bytes",
            "overflow_rule": "greedy_ranked_utf8_prefix",
            "budgets": {
                "total_content_bytes": 100000,
                "per_source_max_bytes": 20000,
                "per_authority_bytes": {
                    "authoritative_current_state": 30000,
                    "authoritative_git_github_ci": 30000,
                    "product_source": 30000,
                    "knowledge_delta": 30000,
                    "historical_ledger": 30000,
                },
            },
        },
        "freshness": {
            "policy": "hwm-exact-bound-freshness/v1", "control_main_sha": CONTROL_SHA,
            "context_main_sha": CONTEXT_SHA, "issue_snapshot_sha256": snapshot["snapshot_sha256"],
            "project_state_commit": CONTROL_SHA, "historical_ledger_commit": CONTEXT_SHA,
            "on_mismatch": "reject", "no_implicit_head_substitution": True,
        },
        "public_data": {
            "policy": "hwm-public-data/v1", "classification": "public-disclosure-safe",
            "forbidden_categories": [
                "api_secrets_tokens", "cookies", "browser_profiles", "account_credentials", "private_keys",
                "session_state", "personal_data", "sensitive_raw_evidence", "secret_bearing_environment_or_config",
            ],
            "on_violation": "reject",
        },
    }
    req["request_id"] = tc.expected_request_id(req)
    return req

