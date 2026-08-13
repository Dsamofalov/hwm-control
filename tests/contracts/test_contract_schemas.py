import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[2]
NAMES = (
    "job.v1.schema.json",
    "result.v1.schema.json",
    "task.v1.schema.json",
    "claim.v1.schema.json",
    "knowledge-delta.v1.schema.json",
    "project-state.v1.schema.json",
)
SCHEMAS = {n: json.loads((ROOT / "schemas" / n).read_text(encoding="utf-8")) for n in NAMES}
FC = FormatChecker()
SHA = "0123456789abcdef0123456789abcdef01234567"
SHA2 = "89abcdef0123456789abcdef0123456789abcdef"
UNKNOWN = {"status": "unknown", "reason": "No authoritative evidence is available."}
KNOWN = {
    "status": "known",
    "sha": SHA,
    "provenance": [{"kind": "github_actions_run", "repo": "Dsamofalov/hwm_predictor", "sha": SHA, "reference": "run:123"}],
}

MIN = {
    "job.v1.schema.json": {
        "schema": "hwm-job/v1", "request_id": "req-00001", "operation": "get_project_bootstrap",
        "product_repo": "Dsamofalov/hwm_predictor", "product_sha": SHA, "parameters": {},
    },
    "result.v1.schema.json": {
        "schema": "hwm-result/v1", "request_id": "req-00001", "operation": "get_project_bootstrap",
        "status": "success", "source": {"product_repo": "Dsamofalov/hwm_predictor", "product_sha": SHA},
        "result": {"outputs": []},
    },
    "task.v1.schema.json": {
        "schema": "hwm-task/v1", "task_id": 2, "title": "Define contracts", "objective_requirement": "I02",
        "state": "ready", "scope": {"allowed": ["schemas/**"], "forbidden": ["hwm_predictor/**"]},
        "goal": "Define versioned contracts.", "done_when": ["Schemas validate."], "required_gates": ["bootstrap"],
        "dependencies": [], "evidence_inputs": [], "risk": {"level": "low", "domains": ["contract"]},
    },
    "claim.v1.schema.json": {
        "schema": "hwm-claim/v1", "task_id": 2, "branch": "agent/infra-0002-contract-schemas",
        "base_repo": "Dsamofalov/hwm-control", "base_sha": SHA,
        "claimed_at": "2026-08-13T21:27:18Z", "lease_expires_at": "2026-08-14T21:27:18Z",
    },
    "knowledge-delta.v1.schema.json": {
        "schema": "hwm-knowledge-delta/v1", "task_id": 2, "goal": "Define contracts.",
        "verified_facts": [], "decisions": [], "rejected_alternatives": [], "changed_components": [],
        "tests": [], "evidence": [], "followups": [], "unresolved": [],
    },
    "project-state.v1.schema.json": {
        "schema": "hwm-project-state/v1", "generated_at": "2026-08-13T21:30:00Z",
        "provenance": [{"kind": "git_ref", "repo": "Dsamofalov/hwm-control", "sha": SHA}],
        "product": {
            "repo": "Dsamofalov/hwm_predictor", "head": SHA, "last_core_green": UNKNOWN,
            "last_full_green": UNKNOWN, "last_post_merge_green": UNKNOWN, "last_live_evidenced": UNKNOWN,
        },
        "requirements": {}, "tasks": {"ready": [], "claimed": [], "blocked": []},
        "knowledge": {"status": "unknown", "reason": "Knowledge materialization not built."},
        "graph": {"status": "unknown", "reason": "Graph materialization not built."},
    },
}

COMPLETE = copy.deepcopy(MIN)
COMPLETE["job.v1.schema.json"].update(
    request_id="01K2TASK217A", operation="build_task_context", task_id=217, parameters={"token_budget": 12000}
)
COMPLETE["result.v1.schema.json"] = {
    "schema": "hwm-result/v1", "request_id": "01K2TASK217A", "operation": "build_task_context", "status": "success",
    "source": {"product_repo": "Dsamofalov/hwm_predictor", "product_sha": SHA,
               "control_repo": "Dsamofalov/hwm-control", "control_sha": SHA2},
    "result": {"outputs": [
        {"name": "context_commit", "kind": "commit_sha", "value": SHA2},
        {"name": "context_path", "kind": "repo_path", "value": "tasks/0217/context.md"},
        {"name": "fresh", "kind": "boolean", "value": True},
    ]},
    "health": {"source_sha_match": True, "schema_valid": True},
}
COMPLETE["task.v1.schema.json"].update(
    task_id=217, title="Implement live replan", objective_requirement="M14", state="claimed",
    scope={"allowed": ["extension/**", "daemon/**"], "forbidden": [".github/workflows/**", "control-plane/**"]},
    goal="Implement the scoped capability.", done_when=["Core passes.", "Full passes."],
    required_gates=["HWM/Core", "HWM/Full", "KnowledgeDelta"], dependencies=[213],
    evidence_inputs=["battle:1672746591"], risk={"level": "medium", "domains": ["live", "decoder"]},
)
COMPLETE["claim.v1.schema.json"]["agent_id"] = "session-20260813-0002"
COMPLETE["knowledge-delta.v1.schema.json"].update(
    task_id=217, goal="Implement scoped capability.",
    verified_facts=[{"statement": "Exact SHA passed Core.", "provenance": [
        {"kind": "ci_run", "reference": "run:31680022438", "repo": "Dsamofalov/hwm_predictor", "sha": SHA}
    ]}],
    decisions=[{"decision": "Use typed operation.", "rationale": "Prevents privileged free-form execution."}],
    rejected_alternatives=[{"alternative": "Free-form shell.", "reason": "Outside trust boundary."}],
    changed_components=["daemon/runtime.py"],
    tests=[{"name": "HWM/Core", "status": "pass", "reference": "run:31680022438"}],
    evidence=[{"kind": "commit", "reference": "functional checkpoint", "repo": "Dsamofalov/hwm_predictor", "sha": SHA}],
    followups=["Add implementation in dependent milestone."],
    unresolved=["Future Git SHA-256 identifiers require an explicit schema revision."],
)
COMPLETE["project-state.v1.schema.json"] = {
    "schema": "hwm-project-state/v1", "generated_at": "2026-08-13T21:30:00Z",
    "provenance": [
        {"kind": "git_ref", "repo": "Dsamofalov/hwm-control", "sha": SHA2, "reference": "refs/heads/main"},
        {"kind": "git_ref", "repo": "Dsamofalov/hwm_predictor", "sha": SHA, "reference": "refs/heads/main"},
    ],
    "product": {
        "repo": "Dsamofalov/hwm_predictor", "head": SHA, "last_core_green": KNOWN, "last_full_green": KNOWN,
        "last_post_merge_green": {"status": "error", "error": {
            "code": "CI_API_ERROR", "message": "Provider unavailable.", "retryable": True}},
        "last_live_evidenced": {"status": "unknown", "reason": "No exact live-evidence SHA is established."},
    },
    "requirements": {"M14": {"status": "partial", "missing_gates": ["authenticated_closed_loop"]}},
    "tasks": {"ready": [217, 218], "claimed": [219], "blocked": [220]},
    "knowledge": {"status": "unhealthy", "source_sha": SHA, "unresolved_conflicts": 2},
    "graph": {"status": "healthy", "source_sha": SHA},
}


def validate(name, obj):
    Draft202012Validator(SCHEMAS[name], format_checker=FC).validate(obj)


class Contracts(unittest.TestCase):
    def bad(self, name, obj):
        with self.assertRaises(ValidationError):
            validate(name, obj)

    def test_schema_documents(self):
        for name, schema in SCHEMAS.items():
            with self.subTest(name=name):
                Draft202012Validator.check_schema(schema)

    def test_valid_minimal_and_complete(self):
        for corpus in (MIN, COMPLETE):
            for name, obj in corpus.items():
                with self.subTest(name=name, complete=corpus is COMPLETE):
                    validate(name, obj)

    def test_missing_required(self):
        fields = {"job.v1.schema.json": "product_sha", "result.v1.schema.json": "source",
                  "task.v1.schema.json": "scope", "claim.v1.schema.json": "base_sha",
                  "knowledge-delta.v1.schema.json": "unresolved", "project-state.v1.schema.json": "provenance"}
        for name, field in fields.items():
            obj = copy.deepcopy(MIN[name]); del obj[field]
            with self.subTest(name=name): self.bad(name, obj)

    def test_wrong_schema_version(self):
        for name, base in MIN.items():
            obj = copy.deepcopy(base); obj["schema"] = obj["schema"].rsplit("/", 1)[0] + "/v999"
            with self.subTest(name=name): self.bad(name, obj)

    def test_wrong_types(self):
        changes = {"job.v1.schema.json": ("parameters", []), "result.v1.schema.json": ("source", "x"),
                   "task.v1.schema.json": ("dependencies", "213"), "claim.v1.schema.json": ("task_id", "2"),
                   "knowledge-delta.v1.schema.json": ("tests", {}), "project-state.v1.schema.json": ("tasks", [])}
        for name, (field, value) in changes.items():
            obj = copy.deepcopy(MIN[name]); obj[field] = value
            with self.subTest(name=name): self.bad(name, obj)

    def test_closed_top_levels(self):
        for name, base in MIN.items():
            obj = copy.deepcopy(base); obj["unexpected"] = True
            with self.subTest(name=name): self.bad(name, obj)

    def test_invalid_enums(self):
        obj = copy.deepcopy(MIN["job.v1.schema.json"]); obj["operation"] = "run_arbitrary_shell"; self.bad("job.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["task.v1.schema.json"]); obj["state"] = "maybe"; self.bad("task.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["result.v1.schema.json"]); obj["status"] = "partial"; self.bad("result.v1.schema.json", obj)

    def test_invalid_exact_sha_and_provenance(self):
        cases = [
            ("job.v1.schema.json", ("product_sha",), "abc123"),
            ("claim.v1.schema.json", ("base_sha",), "ABC123"),
            ("result.v1.schema.json", ("source", "product_sha"), "unknown"),
            ("project-state.v1.schema.json", ("provenance", 0, "sha"), "HEAD"),
        ]
        for name, path, value in cases:
            obj = copy.deepcopy(MIN[name]); target = obj
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            with self.subTest(name=name): self.bad(name, obj)

    def test_result_status_invariants(self):
        obj = copy.deepcopy(MIN["result.v1.schema.json"]); del obj["result"]; self.bad("result.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["result.v1.schema.json"]); obj["status"] = "error"; del obj["result"]; self.bad("result.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["result.v1.schema.json"]); obj["status"] = "unknown"; del obj["result"]; self.bad("result.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["result.v1.schema.json"]); obj["status"] = "error"; obj["error"] = {
            "code": "FAILED", "message": "Failure.", "retryable": False}; self.bad("result.v1.schema.json", obj)

    def test_unknown_error_and_known_checkpoint_invariants(self):
        obj = copy.deepcopy(MIN["project-state.v1.schema.json"]); obj["product"]["last_live_evidenced"]["sha"] = SHA
        self.bad("project-state.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["project-state.v1.schema.json"]); obj["product"]["last_core_green"] = {"status": "known", "sha": SHA}
        self.bad("project-state.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["project-state.v1.schema.json"]); obj["product"]["last_full_green"] = {"status": "error", "reason": "Ambiguous"}
        self.bad("project-state.v1.schema.json", obj)

    def test_job_is_typed_not_privileged_free_form(self):
        obj = copy.deepcopy(COMPLETE["job.v1.schema.json"]); obj["parameters"]["shell"] = "arbitrary"
        self.bad("job.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["job.v1.schema.json"]); obj["parameters"] = {"command": "arbitrary"}
        self.bad("job.v1.schema.json", obj)

    def test_operation_specific_job_invariants(self):
        obj = copy.deepcopy(COMPLETE["job.v1.schema.json"]); del obj["task_id"]; self.bad("job.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["job.v1.schema.json"]); obj["operation"] = "query_graph"; self.bad("job.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["job.v1.schema.json"]); obj["operation"] = "run_post_merge_validation"; obj["parameters"] = {"validation_scope": "smoke"}
        self.bad("job.v1.schema.json", obj)

    def test_date_time_formats(self):
        obj = copy.deepcopy(MIN["claim.v1.schema.json"]); obj["claimed_at"] = "yesterday"; self.bad("claim.v1.schema.json", obj)
        obj = copy.deepcopy(MIN["project-state.v1.schema.json"]); obj["generated_at"] = "2026/08/13"; self.bad("project-state.v1.schema.json", obj)


if __name__ == "__main__":
    unittest.main()
