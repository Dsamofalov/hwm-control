import json
import random
import sys
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control.checkpoint_extractor import (  # noqa: E402
    CORE_GATE, FULL_GATE, PRODUCT_REPOSITORY, WORKFLOW_PATH, extract_core_full_checkpoints,
)
from control.product_head import ProviderError  # noqa: E402

SHA1 = "1111111111111111111111111111111111111111"
SHA2 = "2222222222222222222222222222222222222222"
HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def run(run_id, sha, when, suite=None):
    return {"id": run_id, "head_sha": sha, "check_suite_id": suite or run_id * 10,
            "path": WORKFLOW_PATH, "event": "push", "status": "completed",
            "conclusion": "success", "created_at": when}

def check(check_id, gate, state, run_id, sha, suite=None):
    name = "core" if gate == CORE_GATE else "full"
    return {"id": check_id, "name": name, "head_sha": sha,
            "check_suite": {"id": suite or run_id * 10}, "status": "completed",
            "conclusion": state,
            "details_url": f"https://github.com/{PRODUCT_REPOSITORY}/actions/runs/{run_id}/job/{check_id}"}

def status(status_id, gate, state, run_id):
    return {"id": status_id, "context": gate, "state": state,
            "target_url": f"https://github.com/{PRODUCT_REPOSITORY}/actions/runs/{run_id}"}

class FakeProvider:
    def __init__(self, runs=None, checks=None, statuses=None, runs_error=None, check_errors=None, status_errors=None, head=HEAD):
        self.runs = [] if runs is None else runs
        self.checks = {} if checks is None else checks
        self.statuses = {} if statuses is None else statuses
        self.runs_error = runs_error; self.check_errors = check_errors or {}; self.status_errors = status_errors or {}
        self.head = head; self.calls = []
    def list_workflow_runs(self, repository, workflow_path):
        self.calls.append(("runs", repository, workflow_path))
        if self.runs_error: raise self.runs_error
        return self.runs
    def list_check_runs(self, repository, suite):
        self.calls.append(("checks", repository, suite))
        if suite in self.check_errors: raise self.check_errors[suite]
        return self.checks.get(suite, [])
    def list_commit_statuses(self, repository, sha):
        self.calls.append(("statuses", repository, sha))
        if sha in self.status_errors: raise self.status_errors[sha]
        return self.statuses.get(sha, [])

def cp(result, gate): return result["last_core_green" if gate == CORE_GATE else "last_full_green"]

def both_green(run_id=10, sha=SHA1, when="2026-08-14T10:00:00Z"):
    r = run(run_id, sha, when); suite = r["check_suite_id"]
    return FakeProvider([r], {suite: [check(101, CORE_GATE, "success", run_id, sha, suite), check(102, FULL_GATE, "success", run_id, sha, suite)]},
                        {sha: [status(201, CORE_GATE, "success", run_id), status(202, FULL_GATE, "success", run_id)]})

class CheckpointExtractorTests(unittest.TestCase):
    def test_core_and_full_independently_known_on_same_sha(self):
        result = extract_core_full_checkpoints(both_green())
        self.assertEqual(cp(result, CORE_GATE)["sha"], SHA1); self.assertEqual(cp(result, FULL_GATE)["sha"], SHA1)
    def test_core_known_full_unknown(self):
        r = run(10,SHA1,"2026-08-14T10:00:00Z"); s=r["check_suite_id"]
        p=FakeProvider([r],{s:[check(1,CORE_GATE,"success",10,SHA1,s)]},{SHA1:[status(2,CORE_GATE,"success",10)]})
        out=extract_core_full_checkpoints(p); self.assertEqual(cp(out,CORE_GATE)["status"],"known"); self.assertEqual(cp(out,FULL_GATE)["status"],"unknown")
    def test_full_known_core_unknown(self):
        r=run(10,SHA1,"2026-08-14T10:00:00Z"); s=r["check_suite_id"]
        p=FakeProvider([r],{s:[check(1,FULL_GATE,"success",10,SHA1,s)]},{SHA1:[status(2,FULL_GATE,"success",10)]})
        out=extract_core_full_checkpoints(p); self.assertEqual(cp(out,FULL_GATE)["status"],"known"); self.assertEqual(cp(out,CORE_GATE)["status"],"unknown")
    def test_different_exact_green_shas_are_preserved(self):
        r2=run(20,SHA2,"2026-08-14T11:00:00Z"); r1=run(10,SHA1,"2026-08-14T10:00:00Z")
        p=FakeProvider([r2,r1],{r2["check_suite_id"]:[check(20,CORE_GATE,"success",20,SHA2,r2["check_suite_id"])],r1["check_suite_id"]:[check(10,FULL_GATE,"success",10,SHA1,r1["check_suite_id"])]},{SHA2:[status(20,CORE_GATE,"success",20)],SHA1:[status(10,FULL_GATE,"success",10)]})
        out=extract_core_full_checkpoints(p); self.assertEqual(cp(out,CORE_GATE)["sha"],SHA2); self.assertEqual(cp(out,FULL_GATE)["sha"],SHA1)
    def test_current_head_is_never_substituted(self):
        p=both_green(); p.head=HEAD; out=extract_core_full_checkpoints(p); self.assertNotEqual(cp(out,CORE_GATE)["sha"],HEAD)
    def test_older_green_remains_when_newer_gate_failed(self):
        r2=run(20,SHA2,"2026-08-14T11:00:00Z"); r1=run(10,SHA1,"2026-08-14T10:00:00Z")
        p=FakeProvider([r2,r1],{r2["check_suite_id"]:[check(20,CORE_GATE,"failure",20,SHA2,r2["check_suite_id"])],r1["check_suite_id"]:[check(10,CORE_GATE,"success",10,SHA1,r1["check_suite_id"])]},{SHA2:[status(20,CORE_GATE,"failure",20)],SHA1:[status(10,CORE_GATE,"success",10)]})
        self.assertEqual(cp(extract_core_full_checkpoints(p),CORE_GATE)["sha"],SHA1)
    def test_missing_gate_is_explicit_unknown_without_sha(self):
        out=extract_core_full_checkpoints(FakeProvider([]));
        for gate in (CORE_GATE,FULL_GATE): self.assertEqual(cp(out,gate)["status"],"unknown"); self.assertNotIn("sha",cp(out,gate))
    def test_provider_failure_is_error_without_sha(self):
        out=extract_core_full_checkpoints(FakeProvider(runs_error=ProviderError("API_UNAVAILABLE","unavailable",True)))
        for gate in (CORE_GATE,FULL_GATE): self.assertEqual(cp(out,gate)["error"]["code"],"API_UNAVAILABLE"); self.assertNotIn("sha",cp(out,gate))
    def test_malformed_run_is_error_not_guess(self):
        bad=run(10,HEAD,"2026-08-14T10:00:00Z"); bad["head_sha"]=HEAD.upper(); out=extract_core_full_checkpoints(FakeProvider([bad])); self.assertEqual(cp(out,CORE_GATE)["error"]["code"],"MALFORMED_UPSTREAM_RESPONSE")
    def test_malformed_check_identity_errors_only_its_gate(self):
        r=run(10,SHA1,"2026-08-14T10:00:00Z"); s=r["check_suite_id"]; bad=check(1,CORE_GATE,"success",10,SHA1,s); bad["details_url"]="https://example.invalid/"
        p=FakeProvider([r],{s:[bad,check(2,FULL_GATE,"success",10,SHA1,s)]},{SHA1:[status(3,FULL_GATE,"success",10)]}); out=extract_core_full_checkpoints(p)
        self.assertEqual(cp(out,CORE_GATE)["status"],"error"); self.assertEqual(cp(out,FULL_GATE)["status"],"known")
    def test_ambiguous_duplicate_run_identity_is_error(self):
        out=extract_core_full_checkpoints(FakeProvider([run(10,SHA1,"2026-08-14T10:00:00Z"),run(10,SHA2,"2026-08-14T10:00:00Z")]))
        self.assertEqual(cp(out,CORE_GATE)["error"]["code"],"AMBIGUOUS_UPSTREAM_EVIDENCE")
    def test_deterministic_ordering_and_tie_break(self):
        r1=run(10,SHA1,"2026-08-14T10:00:00Z"); r2=run(20,SHA2,"2026-08-14T10:00:00Z")
        checks={r1["check_suite_id"]:[check(1,CORE_GATE,"success",10,SHA1,r1["check_suite_id"])],r2["check_suite_id"]:[check(2,CORE_GATE,"success",20,SHA2,r2["check_suite_id"])]}; statuses={SHA1:[status(1,CORE_GATE,"success",10)],SHA2:[status(2,CORE_GATE,"success",20)]}
        for seed in range(8):
            rs=[r1,r2]; random.Random(seed).shuffle(rs); self.assertEqual(cp(extract_core_full_checkpoints(FakeProvider(rs,checks,statuses)),CORE_GATE)["sha"],SHA2)
    def test_disagreement_is_integrity_error_not_guess(self):
        r=run(10,SHA1,"2026-08-14T10:00:00Z"); s=r["check_suite_id"]; p=FakeProvider([r],{s:[check(1,CORE_GATE,"success",10,SHA1,s)]},{SHA1:[status(2,CORE_GATE,"failure",10)]}); out=extract_core_full_checkpoints(p)
        self.assertEqual(cp(out,CORE_GATE)["error"]["code"],"INCONSISTENT_UPSTREAM_EVIDENCE"); self.assertNotIn("sha",cp(out,CORE_GATE))
    def test_checkpoint_and_provenance_validate_against_project_state_defs(self):
        out=extract_core_full_checkpoints(both_green()); schema=json.loads((ROOT/"schemas"/"project-state.v1.schema.json").read_text())
        cp_schema={"$defs":schema["$defs"],"$ref":"#/$defs/checkpoint"}; pr_schema={"$defs":schema["$defs"],"$ref":"#/$defs/provenance"}
        cv=Draft202012Validator(cp_schema); pv=Draft202012Validator(pr_schema)
        for gate in (CORE_GATE,FULL_GATE): cv.validate(cp(out,gate)); pv.validate(cp(out,gate)["provenance"][0])
if __name__ == "__main__": unittest.main()
