import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control.knowledge_delta_gate import validate_repository_knowledge_deltas  # noqa: E402


class KnowledgeDeltaGateTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp()) / "repo"
        (root / "schemas").mkdir(parents=True)
        (root / "knowledge-deltas").mkdir()
        shutil.copy2(
            ROOT / "schemas" / "knowledge-delta.v1.schema.json",
            root / "schemas" / "knowledge-delta.v1.schema.json",
        )
        self.addCleanup(lambda: shutil.rmtree(root.parent, ignore_errors=True))
        self.write_status(root)
        return root

    @staticmethod
    def valid_delta(task_id: int = 9) -> dict:
        return {
            "schema": "hwm-knowledge-delta/v1",
            "task_id": task_id,
            "goal": "Require a deterministic Knowledge Delta merge gate.",
            "verified_facts": [
                {
                    "statement": "The merged v1 contract already carries task, rationale, test, and provenance surfaces.",
                    "provenance": [
                        {
                            "kind": "commit",
                            "reference": "authoritative I06 base",
                            "repo": "Dsamofalov/hwm-control",
                            "sha": "f871c38b571da51daf3439a6d8aa93348fd645a4",
                        }
                    ],
                }
            ],
            "decisions": [
                {
                    "decision": "Bind canonical task ids to the Issue number stored in delta.task_id.",
                    "rationale": "GitHub Issue numbers are unique durable task identifiers in the I04 execution projection.",
                }
            ],
            "rejected_alternatives": [],
            "changed_components": ["control/knowledge_delta_gate.py"],
            "tests": [{"name": "deterministic gate test", "status": "pass"}],
            "evidence": [{"kind": "issue", "reference": "Dsamofalov/hwm-control#9"}],
            "followups": [],
            "unresolved": [],
        }

    @staticmethod
    def status(*, active=None, completed=None, milestone_state=None) -> dict:
        value = {
            "completed_task_ids": completed
            if completed is not None
            else ["I00", "I01", "I02", "I05-0008"],
            "active_task_ids": active if active is not None else ["I06-0009"],
        }
        if milestone_state is not None:
            value["milestone_state"] = milestone_state
        return value

    def write_status(self, root: Path, **kwargs) -> None:
        (root / "BUILD_STATUS.json").write_text(
            json.dumps(self.status(**kwargs), indent=2) + "\n", encoding="utf-8"
        )

    @staticmethod
    def write_delta(root: Path, task_key: str, data: dict) -> Path:
        path = root / "knowledge-deltas" / f"{task_key}.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return path

    def test_minimal_valid_delta_passes(self):
        root = self.make_repo()
        self.write_delta(root, "I06-0009", self.valid_delta())
        self.assertEqual(validate_repository_knowledge_deltas(root), [])

    def test_complete_valid_delta_and_correct_task_binding_pass(self):
        root = self.make_repo()
        delta = self.valid_delta()
        delta["rejected_alternatives"] = [
            {"alternative": "Create v2 only to add enforcement.", "reason": "No serialization incompatibility exists."}
        ]
        delta["evidence"].append({"kind": "public_ref", "reference": "docs/INFRA_SPEC.md#20"})
        self.write_delta(root, "I06-0009", delta)
        self.assertEqual(validate_repository_knowledge_deltas(root), [])

    def test_missing_required_delta_fails(self):
        root = self.make_repo()
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("missing required Knowledge Delta for I06-0009" in error for error in errors))

    def test_malformed_json_fails(self):
        root = self.make_repo()
        (root / "knowledge-deltas" / "I06-0009.json").write_text("{", encoding="utf-8")
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("invalid Knowledge Delta JSON" in error for error in errors))

    def test_non_object_delta_fails(self):
        root = self.make_repo()
        (root / "knowledge-deltas" / "I06-0009.json").write_text(
            json.dumps([self.valid_delta()]), encoding="utf-8"
        )
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("must be a JSON object" in error for error in errors))

    def test_wrong_schema_version_fails(self):
        root = self.make_repo()
        delta = self.valid_delta()
        delta["schema"] = "hwm-knowledge-delta/v2"
        self.write_delta(root, "I06-0009", delta)
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("schema error" in error and "schema" in error for error in errors))

    def test_missing_or_empty_rationale_and_evidence_fail(self):
        root = self.make_repo()
        for field in ("decisions", "verified_facts", "changed_components", "tests"):
            with self.subTest(field=field):
                delta = self.valid_delta()
                delta[field] = []
                self.write_delta(root, "I06-0009", delta)
                errors = validate_repository_knowledge_deltas(root)
                self.assertTrue(any("must record at least one" in error for error in errors))

    def test_mismatched_task_issue_binding_fails(self):
        root = self.make_repo()
        self.write_delta(root, "I06-0009", self.valid_delta(task_id=10))
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("bound to Issue #9" in error for error in errors))

    def test_invalid_provenance_fails_without_guessing(self):
        root = self.make_repo()
        delta = self.valid_delta()
        delta["verified_facts"][0]["provenance"][0]["sha"] = "not-a-sha"
        self.write_delta(root, "I06-0009", delta)
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("schema error" in error and "sha" in error for error in errors))

    def test_duplicate_or_noncanonical_representation_fails(self):
        root = self.make_repo()
        delta = self.valid_delta()
        self.write_delta(root, "I06-0009", delta)
        (root / "knowledge-deltas" / "copy.json").write_text(
            json.dumps(delta), encoding="utf-8"
        )
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("non-canonical Knowledge Delta filename" in error for error in errors))

    def test_duplicate_issue_binding_is_ambiguous(self):
        root = self.make_repo()
        self.write_delta(root, "I06-0009", self.valid_delta())
        self.write_delta(root, "I07-0009", self.valid_delta())
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("ambiguous Knowledge Delta Issue #9 binding" in error for error in errors))

    def test_unrelated_task_delta_does_not_satisfy_gate(self):
        root = self.make_repo()
        self.write_delta(root, "I06-0010", self.valid_delta(task_id=10))
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("missing required Knowledge Delta for I06-0009" in error for error in errors))

    def test_invalid_required_task_id_fails_without_guessing(self):
        root = self.make_repo()
        self.write_status(root, active=["I06-nine"])
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("invalid format" in error for error in errors))

    def test_milestone_projection_is_irrelevant(self):
        root = self.make_repo()
        self.write_delta(root, "I06-0009", self.valid_delta())
        for projection in ("open", "closed", "nonsense"):
            with self.subTest(projection=projection):
                self.write_status(root, milestone_state=projection)
                self.assertEqual(validate_repository_knowledge_deltas(root), [])

    def test_completion_state_still_requires_delta(self):
        root = self.make_repo()
        self.write_status(
            root,
            active=[],
            completed=["I00", "I01", "I02", "I05-0008", "I06-0009"],
        )
        errors = validate_repository_knowledge_deltas(root)
        self.assertTrue(any("missing required Knowledge Delta for I06-0009" in error for error in errors))
        self.write_delta(root, "I06-0009", self.valid_delta())
        self.assertEqual(validate_repository_knowledge_deltas(root), [])

    def test_actual_repository_gate_is_part_of_full_unittest_discovery(self):
        self.assertEqual(validate_repository_knowledge_deltas(ROOT), [])


if __name__ == "__main__":
    unittest.main()
