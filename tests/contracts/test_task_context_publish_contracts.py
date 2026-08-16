import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUEST_SCHEMA_PATH = ROOT / "schemas" / "task-context-publish-request.v1.schema.json"
RESULT_SCHEMA_PATH = ROOT / "schemas" / "task-context-publish-result.v1.schema.json"
P0_REQUEST_SCHEMA_PATH = ROOT / "schemas" / "task-context-request.v1.schema.json"
P0_PACK_SCHEMA_PATH = ROOT / "schemas" / "task-context-pack.v1.schema.json"
DOC_PATH = ROOT / "docs" / "I09_TASK_CONTEXT_PUBLISH_CONTRACT.md"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TaskContextPublishContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = load(REQUEST_SCHEMA_PATH)
        cls.result = load(RESULT_SCHEMA_PATH)
        cls.p0_request = load(P0_REQUEST_SCHEMA_PATH)
        cls.p0_pack = load(P0_PACK_SCHEMA_PATH)
        cls.doc = DOC_PATH.read_text(encoding="utf-8")

    def test_forward_only_schema_markers_are_separate(self):
        self.assertEqual(self.request["title"], "hwm-task-context-publish-request/v1")
        self.assertEqual(self.result["title"], "hwm-task-context-publish-result/v1")
        self.assertEqual(self.request["properties"]["schema"]["const"], "hwm-task-context-publish-request/v1")
        self.assertEqual(self.result["properties"]["schema"]["const"], "hwm-task-context-publish-result/v1")
        self.assertEqual(self.p0_request["properties"]["schema"]["const"], "hwm-task-context-request/v1")
        self.assertEqual(self.p0_pack["properties"]["schema"]["const"], "hwm-task-context-pack/v1")

    def test_request_is_closed_exact_repo_transport_and_candidate(self):
        self.assertFalse(self.request["additionalProperties"])
        props = self.request["properties"]
        self.assertEqual(props["repository"]["const"], "Dsamofalov/hwm-context")
        self.assertEqual(props["transport_issue"]["const"], 27)
        candidate = props["candidate"]["properties"]
        self.assertEqual(candidate["parent_count"]["const"], 1)
        self.assertEqual(candidate["tree_policy"]["const"], "base-plus-exact-task-context-blob")
        ci = props["ci"]["properties"]
        self.assertEqual(ci["workflow"]["const"], "repository-bootstrap-ci.yml")
        self.assertEqual(ci["required_check"]["const"], "bootstrap")
        self.assertEqual(ci["status_integration_id"]["const"], 15368)

    def test_artifact_is_only_context_json_regular_add_replace(self):
        variants = self.request["properties"]["artifact"]["oneOf"]
        self.assertEqual({variant["properties"]["op"]["const"] for variant in variants}, {"add", "replace"})
        for variant in variants:
            self.assertFalse(variant["additionalProperties"])
            props = variant["properties"]
            self.assertEqual(props["mode"]["const"], "100644")
            self.assertEqual(props["pack_schema"]["const"], "hwm-task-context-pack/v1")
            pattern = re.compile(props["path"]["pattern"])
            self.assertIsNotNone(pattern.fullmatch("tasks/I09-0047/context.json"))
            for forbidden in (
                "tasks/I09-0047/context.md",
                "tasks/I09-0047/extra.json",
                "tasks/arbitrary/context.json",
                ".github/workflows/x.yml",
            ):
                self.assertIsNone(pattern.fullmatch(forbidden))

    def test_task_binding_is_exact_issue_and_source_request_shape(self):
        task = self.request["properties"]["task"]["properties"]
        self.assertEqual(task["issue_repository"]["const"], "Dsamofalov/hwm-control")
        self.assertEqual(task["task_key"]["pattern"], "^I[0-9]{2}-[0-9]{4}$")
        self.assertEqual(task["source_request_id"]["pattern"], "^tcr1-[0-9a-f]{64}$")
        self.assertEqual(task["source_request_sha256"]["pattern"], "^[0-9a-f]{64}$")

    def test_result_has_typed_success_error_and_status_provenance(self):
        self.assertFalse(self.result["additionalProperties"])
        props = self.result["properties"]
        self.assertEqual(props["status"]["enum"], ["success", "error"])
        status = props["required_status"]["oneOf"][1]["properties"]
        self.assertEqual(status["context"]["const"], "bootstrap")
        self.assertEqual(status["integration_id"]["const"], 15368)
        self.assertEqual(status["creator_login"]["const"], "github-actions[bot]")
        self.assertEqual(status["creator_id"]["const"], 41898282)
        errors = props["error"]["oneOf"][1]["properties"]["code"]["enum"]
        for required in (
            "INVALID_SCHEMA",
            "FORBIDDEN_PATH",
            "BLOB_NOT_REGULAR",
            "EXPECTED_HEAD_MISMATCH",
            "REQUEST_ID_REUSE",
            "STRICT_GATE_REJECTED",
        ):
            self.assertIn(required, errors)

    def test_documented_authority_separation_and_no_context_markdown(self):
        for phrase in (
            "must not:\n\n- receive `statuses:write`",
            "write protected `main`",
            "approve or merge a PR",
            "execute, import or check out candidate content",
            "The strict gate runs only from protected-main workflow code",
            "isolated `statuses:write`",
            "broad `tasks/**` filtering is forbidden",
            "`context.md`",
            "never treats a generated acceptance PR as implementation merge authority",
        ):
            self.assertIn(phrase, self.doc)


if __name__ == "__main__":
    unittest.main()
