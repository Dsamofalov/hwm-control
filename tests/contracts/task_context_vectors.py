from task_context_contract_core import *  # noqa: F401,F403

def base_request():
    issue = {
        "repository": "Dsamofalov/hwm-control",
        "issue_number": 45,
        "snapshot_sha256": H_A,
        "updated_at": "2026-08-15T10:41:54Z",
        "state": "open",
        "state_reason": None,
        "lifecycle": "claimed",
        "title_sha256": H_B,
        "body_sha256": H_C,
        "labels": ["architecture", "claimed", "contract", "infrastructure", "trusted"],
        "assignees": [],
        "milestone_number": 10,
    }
    issue["snapshot_sha256"] = issue_snapshot_digest(issue)
    budgets = {
        "total_content_bytes": 1024,
        "per_source_max_bytes": 512,
        "per_authority_bytes": {
            "authoritative_current_state": 256,
            "authoritative_git_github_ci": 128,
            "product_source": 512,
            "knowledge_delta": 256,
            "historical_ledger": 256,
        },
    }
    req = {
        "schema": "hwm-task-context-request/v1",
        "request_id": "tcr1-" + "0" * 64,
        "task": {
            "task_key": "I09-0045",
            "issue_repository": "Dsamofalov/hwm-control",
            "issue_number": 45,
        },
        "issue_snapshot": issue,
        "product": {
            "repository": "Dsamofalov/hwm_predictor",
            "commit": SHA_C,
            "head_policy": "exact_revision_only",
        },
        "project_state": {
            "schema": "hwm-project-state/v2",
            "repository": "Dsamofalov/hwm-control",
            "commit": SHA_A,
            "path": "state/current.json",
            "blob_sha": SHA_B,
            "content_sha256": H_B,
        },
        "historical_ledger": {
            "repository": "Dsamofalov/hwm-context",
            "commit": SHA_B,
            "head_policy": "must_equal_current",
            "claims": {
                "path": "claims/claims.jsonl",
                "blob_sha": SHA_C,
                "content_sha256": H_A,
            },
            "conflicts": {
                "path": "claims/conflicts.json",
                "blob_sha": SHA_D,
                "content_sha256": H_C,
            },
        },
        "knowledge_deltas": {
            "set_mode": "explicit_exact_set",
            "inputs": [{
                "task_key": "I08-0038",
                "task_id": 38,
                "repository": "Dsamofalov/hwm-control",
                "commit": SHA_A,
                "path": "knowledge-deltas/I08-0038.json",
                "blob_sha": SHA_D,
                "content_sha256": H_C,
            }],
        },
        "product_sources": {
            "set_mode": "explicit_exact_set",
            "inputs": [{
                "source_id": "product.solver",
                "path": "solver.py",
                "blob_sha": SHA_D,
                "content_sha256": H_B,
                "media_type": "text/x-python",
                "priority": 10,
                "required": False,
                "truncation_allowed": True,
            }],
        },
        "selection": {
            "algorithm": "hwm-task-context-selection/v1",
            "authority_order": AUTH_ORDER,
            "ranking_keys": ["required_desc", "authority_order", "priority_asc", "source_id_asc"],
            "tie_break": "source_id_lexicographic",
            "dedup_identity": "authority_class+media_type+content_sha256",
            "budget_metric": "utf8_content_bytes",
            "overflow_rule": "greedy_ranked_utf8_prefix",
            "budgets": budgets,
        },
        "freshness": {
            "policy": "hwm-exact-bound-freshness/v1",
            "control_main_sha": SHA_A,
            "context_main_sha": SHA_B,
            "issue_snapshot_sha256": issue["snapshot_sha256"],
            "project_state_commit": SHA_A,
            "historical_ledger_commit": SHA_B,
            "on_mismatch": "reject",
            "no_implicit_head_substitution": True,
        },
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
    }
    bind_request_id(req)
    return req
def base_pack(req=None):
    req = req or base_request()
    content = "alpha\n"
    emitted = content.encode("utf-8")
    source = {
        "source_id": "product.solver",
        "authority_class": "product_source",
        "media_type": "text/x-python",
        "priority": 10,
        "required": False,
        "truncation_allowed": True,
        "provenance": {
            "kind": "git_blob",
            "repository": req["product"]["repository"],
            "commit": req["product"]["commit"],
            "path": "solver.py",
            "blob_sha": SHA_D,
            "content_sha256": sha256(emitted),
        },
        "status": "included",
        "original_byte_count": len(emitted),
        "emitted_byte_count": len(emitted),
        "content_sha256": sha256(emitted),
        "emitted_sha256": sha256(emitted),
        "content": content,
    }
    selection = copy.deepcopy(req["selection"])
    selection.update({
        "candidate_count": 1,
        "unique_candidate_count": 1,
        "emitted_source_count": 1,
        "emitted_content_bytes": len(emitted),
    })
    pack = {
        "schema": "hwm-task-context-pack/v1",
        "request_binding": {
            "request_id": req["request_id"],
            "request_sha256": sha256(canonical_bytes(req)),
        },
        "task": copy.deepcopy(req["task"]),
        "issue_snapshot": copy.deepcopy(req["issue_snapshot"]),
        "product": copy.deepcopy(req["product"]),
        "project_state": copy.deepcopy(req["project_state"]),
        "historical_ledger": copy.deepcopy(req["historical_ledger"]),
        "knowledge_deltas": copy.deepcopy(req["knowledge_deltas"]),
        "authority_model": {
            "classes": [
                "authoritative_current_state",
                "authoritative_git_github_ci",
                "historical_ledger",
                "knowledge_delta",
                "product_source",
                "derived_task_context",
                "llm_semantic_output",
            ],
            "current_state_is_authoritative": True,
            "historical_is_not_current_state": True,
            "derived_context_is_not_authority": True,
            "llm_is_not_deterministic_authority": True,
        },
        "selection": selection,
        "freshness": {
            "policy": "hwm-exact-bound-freshness/v1",
            "status": "fresh",
            "checks": [
                {"source_id": "control.main", "expected": req["freshness"]["control_main_sha"], "observed": req["freshness"]["control_main_sha"], "status": "match"},
                {"source_id": "context.main", "expected": req["freshness"]["context_main_sha"], "observed": req["freshness"]["context_main_sha"], "status": "match"},
                {"source_id": "historical.ledger", "expected": req["historical_ledger"]["commit"], "observed": req["historical_ledger"]["commit"], "status": "match"},
                {"source_id": "issue.snapshot", "expected": req["issue_snapshot"]["snapshot_sha256"], "observed": req["issue_snapshot"]["snapshot_sha256"], "status": "match"},
                {"source_id": "project.state", "expected": req["project_state"]["commit"], "observed": req["project_state"]["commit"], "status": "match"},
            ],
            "on_mismatch": "reject",
            "no_implicit_head_substitution": True,
        },
        "sources": [source],
        "public_data": copy.deepcopy(req["public_data"]),
        "serialization": {
            "profile": "hwm-canonical-json/v1",
            "artifact": "context.json",
            "encoding": "UTF-8",
            "bom": False,
            "object_key_order": "lexicographic_unicode_codepoint",
            "separators": "comma_colon_no_whitespace",
            "trailing_lf": True,
            "unicode_normalization": "none",
            "non_finite_numbers": "reject",
            "compiler_controlled_array_order": "contract_defined",
            "context_markdown": "not_defined_in_v1",
        },
    }
    return pack
