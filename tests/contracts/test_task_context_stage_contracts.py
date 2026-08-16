import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from control.task_context_core import git_blob_sha

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


class TaskContextStageContractTests(unittest.TestCase):
    def load(self, name):
        return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))

    def test_stage_schemas_are_valid_closed_forward_only_contracts(self):
        request = self.load("task-context-stage-request.v1.schema.json")
        result = self.load("task-context-stage-result.v1.schema.json")
        Draft202012Validator.check_schema(request)
        Draft202012Validator.check_schema(result)

        self.assertEqual(request["title"], "hwm-task-context-stage-request/v1")
        self.assertEqual(result["title"], "hwm-task-context-stage-result/v1")
        self.assertFalse(request["additionalProperties"])
        self.assertFalse(result["additionalProperties"])
        self.assertEqual(request["properties"]["source_request"]["$ref"], "task-context-request.v1.schema.json")
        self.assertEqual(request["properties"]["repository"]["const"], "Dsamofalov/hwm-context")
        self.assertEqual(request["properties"]["transport_issue"]["const"], 27)
        self.assertEqual(request["properties"]["compiler"]["properties"]["max_blob_bytes"]["const"], 4194304)
        self.assertEqual(result["properties"]["transport"]["properties"]["result_author_login"]["const"], "github-actions[bot]")
        self.assertEqual(result["properties"]["transport"]["properties"]["result_author_id"]["const"], 41898282)

    def test_stage_request_carries_source_request_not_generated_context_bytes(self):
        request = self.load("task-context-stage-request.v1.schema.json")
        top = set(request["properties"])
        self.assertIn("source_request", top)
        for forbidden in ("context_json", "context_bytes", "content", "blob_content", "publication_branch"):
            self.assertNotIn(forbidden, top)

    def test_compiler_identity_and_expected_digests_are_mandatory(self):
        request = self.load("task-context-stage-request.v1.schema.json")
        compiler_required = set(request["properties"]["compiler"]["required"])
        self.assertTrue({
            "commit",
            "compiler_blob_sha",
            "core_blob_sha",
            "request_schema_blob_sha",
            "pack_schema_blob_sha",
            "serialization_profile",
            "pack_schema",
            "max_blob_bytes",
        }.issubset(compiler_required))
        expectations = set(request["properties"]["expectations"]["required"])
        self.assertEqual(
            expectations,
            {"source_request_id", "source_request_sha256", "context_sha256", "git_blob_sha"},
        )

    def test_result_binds_double_compile_readback_and_transport_provenance(self):
        result = self.load("task-context-stage-result.v1.schema.json")
        required = set(result["required"])
        self.assertTrue({"observations", "source_request", "compiler", "artifact", "idempotent_replay", "error", "transport"}.issubset(required))
        artifact_schema = result["properties"]["artifact"]["oneOf"][1]
        self.assertTrue({
            "byte_length",
            "context_sha256",
            "git_blob_sha",
            "unattached",
            "readback_byte_equal",
            "readback_sha256",
            "readback_git_blob_sha",
        }.issubset(set(artifact_schema["required"])))
        compiler = result["properties"]["compiler"]
        self.assertIn("compile_pass_count", compiler["required"])
        self.assertIn("byte_equal", compiler["required"])

    def test_predecessor_i09_contract_blobs_are_unchanged(self):
        expected = {
            "task-context-request.v1.schema.json": "c94d7caa0306799231ec276be2107db3c04946ea",
            "task-context-pack.v1.schema.json": "e17296906dbf4a0717a02fc4be8be197ac977e15",
            "task-context-publish-request.v1.schema.json": "a174addf6ba1f8c294b673a315630ff53f09ad96",
            "task-context-publish-result.v1.schema.json": "dc7a2d75d3bc0e55d83efa3d7dd6aaac08b72f07",
        }
        for name, sha in expected.items():
            with self.subTest(name=name):
                self.assertEqual(git_blob_sha((SCHEMAS / name).read_bytes()), sha)

    def test_adr_records_coarse_permission_and_operational_confinement(self):
        text = (ROOT / "docs" / "ADR" / "0003-trusted-task-context-blob-staging.md").read_text(encoding="utf-8")
        for required in (
            "GitHub does not provide endpoint-level `GITHUB_TOKEN` permission",
            "short-lived repository-scoped built-in `GITHUB_TOKEN`",
            "residual theoretical ref capability is accepted",
            "POST /repos/Dsamofalov/hwm-context/git/blobs",
            "POST /repos/Dsamofalov/hwm-context/issues/27/comments",
            "No PAT, deploy key, GitHub App secret/credential",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
