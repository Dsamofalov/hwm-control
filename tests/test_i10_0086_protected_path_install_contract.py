import copy
import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
REQUEST_PATH = ROOT / "schemas" / "protected-path-install-request.bootstrap-v1.schema.json"
RESULT_PATH = ROOT / "schemas" / "protected-path-install-result.bootstrap-v1.schema.json"
ADR_PATH = ROOT / "docs" / "ADR" / "0009-controlled-protected-path-installer-contract.md"
INFRA_PATH = ROOT / "docs" / "INFRA_SPEC.md"

ORDINARY_REQUEST_BLOB = "34a6724c7064864f48a214a94f9006da8e4944eb"
ORDINARY_RESULT_BLOB = "ee952b5f3a1a2e0a71dbe4d647539f645ab416d9"
KD73_BLOB = "fd84a5df1bb91a0b56693469d8e74532b6fd8584"
INFRA_PREDECESSOR_BLOB = "1a6917297f0068e8b530abc18b273c3918e13b0f"
INFRA_PREDECESSOR_SIZE = 69503
INFRA_TARGET_BLOB = "53b84182af75292ca2531e0ef275292bf596d6dd"
CORE_SCHEMA_MAP = {
    "bootstrap_baseline": "hwm-infra-baseline/bootstrap-v0",
    "job": "hwm-job/v1",
    "result": "hwm-result/v1",
    "task": "hwm-task/v1",
    "claim": "hwm-claim/v1",
    "knowledge_delta": "hwm-knowledge-delta/v1",
    "project_state": "hwm-project-state/v2",
}


def git_blob_sha_bytes(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def git_blob_sha(path: Path) -> str:
    return git_blob_sha_bytes(path.read_bytes())


class ProtectedPathInstallContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request_schema = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
        cls.result_schema = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
        cls.request_validator = Draft202012Validator(cls.request_schema)
        cls.result_validator = Draft202012Validator(cls.result_schema)

    def valid_request(self):
        return {
            "schema": "hwm-protected-path-install-request/bootstrap-v1",
            "request_id": "i10-0087-protected-install-v1",
            "repository": "Dsamofalov/hwm-lab",
            "architecture_issue": 87,
            "task_id": "I10-0087",
            "installation_branch": "agent/infra-0087-protected-path-installer",
            "expected_head": "1" * 40,
            "protected_main_base_sha": "2" * 40,
            "issue_declared_paths": [
                ".github/workflows/protected-path-installer.yml",
                ".github/actions/protected-installer/action.yml",
            ],
            "changes": [
                {
                    "op": "add",
                    "path": ".github/workflows/protected-path-installer.yml",
                    "blob_sha": "3" * 40,
                    "mode": "100644",
                }
            ],
            "commit_message": "install protected-path installer",
            "trusted_validation": {
                "workflow": "repository-bootstrap-ci.yml",
                "required_check": "bootstrap",
                "protected_source_ref": "refs/heads/main",
            },
        }

    def valid_success(self):
        return {
            "schema": "hwm-protected-path-install-result/bootstrap-v1",
            "request_id": "i10-0087-protected-install-v1",
            "status": "success",
            "repository": "Dsamofalov/hwm-lab",
            "architecture_issue": 87,
            "task_id": "I10-0087",
            "installation_branch": "agent/infra-0087-protected-path-installer",
            "expected_head": "1" * 40,
            "protected_main_base_sha": "2" * 40,
            "observed_head_before": "1" * 40,
            "request_fingerprint": "4" * 64,
            "idempotent_replay": False,
            "new_head": "5" * 40,
            "commit_sha": "5" * 40,
            "changes": [
                {
                    "op": "add",
                    "path": ".github/workflows/protected-path-installer.yml",
                    "blob_sha": "3" * 40,
                    "mode": "100644",
                }
            ],
            "trusted_validation": {
                "workflow": "repository-bootstrap-ci.yml",
                "required_check": "bootstrap",
                "run_id": 123456,
                "head_sha": "5" * 40,
                "source_ref": "refs/heads/main",
            },
        }

    def test_schema_documents_are_strict_forward_only(self):
        Draft202012Validator.check_schema(self.request_schema)
        Draft202012Validator.check_schema(self.result_schema)
        self.assertEqual(
            self.request_schema["properties"]["schema"]["const"],
            "hwm-protected-path-install-request/bootstrap-v1",
        )
        self.assertEqual(
            self.result_schema["properties"]["schema"]["const"],
            "hwm-protected-path-install-result/bootstrap-v1",
        )
        self.assertFalse(self.request_schema["additionalProperties"])
        self.assertFalse(self.result_schema["additionalProperties"])
        self.assertNotEqual(
            self.request_schema["properties"]["schema"]["const"],
            "hwm-publish-request/bootstrap-v1",
        )

    def test_request_binds_repo_issue_task_branch_heads_allowlist_and_validation(self):
        request = self.valid_request()
        self.request_validator.validate(request)
        required = set(self.request_schema["required"])
        self.assertTrue(
            {
                "repository",
                "architecture_issue",
                "task_id",
                "installation_branch",
                "expected_head",
                "protected_main_base_sha",
                "issue_declared_paths",
                "changes",
                "commit_message",
                "trusted_validation",
            }.issubset(required)
        )
        self.assertEqual(
            request["trusted_validation"]["protected_source_ref"], "refs/heads/main"
        )
        self.assertEqual(request["trusted_validation"]["required_check"], "bootstrap")

    def test_request_rejects_untyped_mutation_shapes(self):
        for mutation in (
            {"op": "delete", "path": ".github/workflows/x.yml"},
            {
                "op": "add",
                "path": "control/free_form.py",
                "blob_sha": "3" * 40,
                "mode": "100644",
            },
            {
                "op": "add",
                "path": ".github/workflows/x.yml",
                "blob_sha": "3" * 40,
                "mode": "120000",
            },
            {
                "op": "add",
                "path": ".github/actions/x/../escape",
                "blob_sha": "3" * 40,
                "mode": "100644",
            },
            {
                "op": "add",
                "path": ".github/actions/x\\escape",
                "blob_sha": "3" * 40,
                "mode": "100644",
            },
        ):
            with self.subTest(mutation=mutation):
                request = self.valid_request()
                request["changes"] = [mutation]
                with self.assertRaises(ValidationError):
                    self.request_validator.validate(request)

        request = self.valid_request()
        request["shell"] = "bash -c anything"
        with self.assertRaises(ValidationError):
            self.request_validator.validate(request)

    def test_replace_requires_exact_old_blob(self):
        request = self.valid_request()
        request["changes"] = [
            {
                "op": "replace",
                "path": ".github/workflows/protected-path-installer.yml",
                "blob_sha": "3" * 40,
                "mode": "100644",
            }
        ]
        with self.assertRaises(ValidationError):
            self.request_validator.validate(request)
        request["changes"][0]["expected_blob_sha"] = "6" * 40
        self.request_validator.validate(request)

    def test_result_success_and_error_are_disjoint_and_typed(self):
        success = self.valid_success()
        self.result_validator.validate(success)
        self.assertIn("run_id", self.result_schema["$defs"]["validation"]["required"])

        bad_success = copy.deepcopy(success)
        bad_success["error"] = {
            "code": "INTERNAL_ERROR",
            "message": "not allowed with success",
            "retryable": False,
        }
        with self.assertRaises(ValidationError):
            self.result_validator.validate(bad_success)

        error = {
            "schema": "hwm-protected-path-install-result/bootstrap-v1",
            "request_id": "i10-0087-protected-install-v1",
            "status": "error",
            "repository": "Dsamofalov/hwm-lab",
            "architecture_issue": 87,
            "task_id": "I10-0087",
            "installation_branch": "agent/infra-0087-protected-path-installer",
            "expected_head": "1" * 40,
            "protected_main_base_sha": "2" * 40,
            "observed_head_before": "1" * 40,
            "request_fingerprint": "4" * 64,
            "idempotent_replay": False,
            "error": {
                "code": "SELF_MODIFICATION_FORBIDDEN",
                "message": "protected installer cannot modify itself",
                "retryable": False,
            },
        }
        self.result_validator.validate(error)

    def test_infra_spec_is_exact_append_only_successor(self):
        data = INFRA_PATH.read_bytes()
        self.assertEqual(git_blob_sha_bytes(data), INFRA_TARGET_BLOB)
        self.assertGreater(len(data), INFRA_PREDECESSOR_SIZE)
        prefix = data[:INFRA_PREDECESSOR_SIZE]
        suffix = data[INFRA_PREDECESSOR_SIZE:]
        self.assertEqual(git_blob_sha_bytes(prefix), INFRA_PREDECESSOR_BLOB)
        self.assertTrue(suffix.startswith(b"\n# 38. Controlled protected-path installer\n"))
        self.assertEqual(suffix.count(b"\n# 38."), 1)
        self.assertTrue(data.endswith(b"\n"))
        self.assertFalse(data.endswith(b"\n\n"))
        self.assertNotIn(b"\r\n", suffix)

    def test_policy_documents_define_absolute_denies_and_candidate_nonexecution(self):
        adr = ADR_PATH.read_text(encoding="utf-8")
        infra = INFRA_PATH.read_text(encoding="utf-8")
        for marker in (
            "Candidate-content non-execution",
            "installer self-modification is rejected",
            "ordinary publisher modification is rejected",
            "existing required bootstrap workflow modification is rejected",
            "`CODEOWNERS`, ruleset/settings, and secret/environment paths are rejected",
            "`pull_request_target`",
            "non-reusable bootstrap exception",
            "Exact #87 bootstrap installation allowlist",
            "`control/protected_path_installer_policy.py`",
            "`tests/security/test_protected_path_installer.py`",
        ):
            self.assertIn(marker, adr)
        for marker in (
            "# 38. Controlled protected-path installer",
            "Candidate content remains inert",
            "installer self-modification",
            "ordinary publisher implementation/workflow/policy/contracts",
            "exception expires permanently after #87",
            "#85 may resume only after completed #87",
            "#73 remains paused until completed #85",
        ):
            self.assertIn(marker, infra)

    def test_ordinary_publisher_and_active_73_recovery_bytes_are_immutable(self):
        self.assertEqual(
            git_blob_sha(ROOT / "schemas" / "publish-request.bootstrap-v1.schema.json"),
            ORDINARY_REQUEST_BLOB,
        )
        self.assertEqual(
            git_blob_sha(ROOT / "schemas" / "publish-result.bootstrap-v1.schema.json"),
            ORDINARY_RESULT_BLOB,
        )
        self.assertEqual(
            git_blob_sha(ROOT / "knowledge-deltas" / "I10-0073.json"), KD73_BLOB
        )

    def test_build_status_preserves_core_map_product_checkpoint_and_73_activity(self):
        status = json.loads((ROOT / "BUILD_STATUS.json").read_text(encoding="utf-8"))
        self.assertEqual(status["current_schema_versions"], CORE_SCHEMA_MAP)
        self.assertEqual(
            status["exact_relevant_heads"]["product_main_reference"],
            "8fd669336b36064e842252d69fb4016cc526a9d4",
        )
        self.assertIn("I10-0073", status["active_task_ids"])
        self.assertIn(
            "I10-0086",
            set(status["active_task_ids"]) | set(status["completed_task_ids"]),
        )


if __name__ == "__main__":
    unittest.main()
