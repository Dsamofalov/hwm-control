import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR9_PATH = ROOT / "docs" / "ADR" / "0009-controlled-protected-path-installer-contract.md"
ADR10_PATH = ROOT / "docs" / "ADR" / "0010-defer-protected-path-credentials-and-use-in-job-runtime-acquisition.md"
INFRA_PATH = ROOT / "docs" / "INFRA_SPEC.md"
RUNTIME_PATH = ROOT / "contracts" / "graphify-acceptance-runtime.v1.json"
SUPPLY_V2_PATH = ROOT / "contracts" / "graphify-supply-chain.v2.json"
KD73_PATH = ROOT / "knowledge-deltas" / "I10-0073.json"
KD87_PATH = ROOT / "knowledge-deltas" / "I10-0087.json"

INFRA_PREDECESSOR_BLOB = "53b84182af75292ca2531e0ef275292bf596d6dd"
INFRA_PREDECESSOR_SIZE = 77477
ADR9_BLOB = "3a8bb58ca4886590fd82d5920f6078a7710c9899"
SUPPLY_V2_BLOB = "f42132a2f52d1d7af84155a56a86fca2fe4d8605"
KD73_BLOB = "fd84a5df1bb91a0b56693469d8e74532b6fd8584"
KD87_BLOB = "a19481504e9bf8cdd0d08c6dd0a7c071c54de5f4"

ARTIFACT_URL = "https://github.com/actions/python-versions/releases/download/3.12.10-14343898437/python-3.12.10-linux-24.04-x64.tar.gz"
RELEASE_URL = "https://github.com/actions/python-versions/releases/tag/3.12.10-14343898437"
HASHES_URL = "https://github.com/actions/python-versions/releases/download/3.12.10-14343898437/hashes.sha256"
ARTIFACT_SHA256 = "b9bd943c5fc9244f796deef42c59d29ab9278d8a718851c67de6b44846320f33"


def git_blob_sha_bytes(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def git_blob_sha(path: Path) -> str:
    return git_blob_sha_bytes(path.read_bytes())


class ProtectedPathAuthorityReconciliationTests(unittest.TestCase):
    def _text(self, path: Path) -> str:
        self.assertTrue(path.is_file(), f"missing reconciliation artifact: {path.relative_to(ROOT)}")
        return path.read_text(encoding="utf-8")

    def _json(self, path: Path):
        return json.loads(self._text(path))

    def test_reconciliation_artifacts_are_materialized(self):
        self.assertTrue(ADR10_PATH.is_file(), "ADR 0010 must be materialized")
        self.assertTrue(RUNTIME_PATH.is_file(), "exact runtime contract must be materialized")
        self.assertIn(
            "# 39. Protected-path credential reconciliation and in-job runtime acquisition",
            INFRA_PATH.read_text(encoding="utf-8"),
        )

    def test_runtime_identity_is_exact_and_forward_only(self):
        contract = self._json(RUNTIME_PATH)
        self.assertEqual(contract["schema"], "hwm-graphify-acceptance-runtime/v1")
        self.assertEqual(contract["producer"], "actions/python-versions")
        self.assertEqual(contract["repository"], "actions/python-versions")
        self.assertEqual(contract["release"]["tag"], "3.12.10-14343898437")
        self.assertEqual(contract["release"]["url"], RELEASE_URL)
        self.assertEqual(contract["artifact"]["filename"], "python-3.12.10-linux-24.04-x64.tar.gz")
        self.assertEqual(contract["artifact"]["url"], ARTIFACT_URL)
        self.assertEqual(contract["artifact"]["size_bytes"], 121612690)
        self.assertEqual(contract["artifact"]["sha256"], ARTIFACT_SHA256)
        self.assertEqual(contract["artifact"]["official_release_hash_manifest"], HASHES_URL)
        self.assertEqual(
            contract["runtime"],
            {
                "implementation": "CPython",
                "version": "3.12.10",
                "platform": "linux",
                "distribution": "Ubuntu 24.04",
                "architecture": "x86_64",
                "executable_report_exact": "CPython 3.12.10",
            },
        )

    def test_acquisition_is_anonymous_exact_single_redirect_and_fail_closed(self):
        acquisition = self._json(RUNTIME_PATH)["acquisition"]
        self.assertEqual(acquisition["transport"], "anonymous HTTPS GET")
        self.assertTrue(acquisition["exact_artifact_url_only"])
        self.assertEqual(acquisition["max_redirects"], 1)
        self.assertEqual(acquisition["final_redirect_host"], "release-assets.githubusercontent.com")
        self.assertFalse(acquisition["authorization_header"])
        self.assertFalse(acquisition["cookies"])
        self.assertFalse(acquisition["credentials"])
        self.assertTrue(acquisition["exact_filename_required"])
        self.assertTrue(acquisition["exact_byte_size_required"])
        self.assertTrue(acquisition["exact_sha256_required"])
        self.assertEqual(
            acquisition["fail_closed_on"],
            ["unexpected_redirect", "unexpected_host", "unexpected_content_length", "unexpected_hash"],
        )
        self.assertFalse(acquisition["mirror_fallback"])
        self.assertFalse(acquisition["mutable_manifest_lookup"])
        self.assertFalse(acquisition["actions_setup_python"])
        self.assertFalse(acquisition["toolcache_fallback"])
        self.assertFalse(acquisition["current_main_version_manifest_lookup"])

    def test_runtime_target_cache_and_extraction_policy_is_bounded(self):
        workspace = self._json(RUNTIME_PATH)["workspace"]
        self.assertEqual(workspace["preexisting_runtime_or_cache_target"], "reject")
        self.assertEqual(workspace["extraction_root"], "RUNNER_TEMP")
        self.assertEqual(workspace["install_root"], "RUNNER_TEMP/task-local")
        self.assertFalse(workspace["global_or_shared_cache"])
        self.assertFalse(workspace["cross_run_reuse"])
        self.assertEqual(
            workspace["safe_bounded_extraction"],
            {
                "path_traversal": "reject",
                "symlink": "reject",
                "special_file": "reject",
            },
        )
        self.assertTrue(workspace["delete_runtime_after_acceptance"])

    def test_network_setup_version_provenance_and_timer_boundaries_are_exact(self):
        contract = self._json(RUNTIME_PATH)
        self.assertEqual(
            contract["network_boundary"]["deny_network_before"],
            ["artifact_setup", "product_parsing", "graphify_invocation"],
        )
        self.assertEqual(contract["setup"]["procedure"], "verified archive bounded setup only")
        self.assertTrue(contract["setup"]["execute_only_verified_archive_setup"])
        self.assertEqual(contract["verification"]["executable_report_exact"], "CPython 3.12.10")
        self.assertTrue(contract["verification"]["record_artifact_and_runtime_provenance"])
        self.assertTrue(contract["timer_boundary"]["runtime_acquisition_and_setup_before_builder_timer"])
        self.assertEqual(contract["timer_boundary"]["semantic_builder_timer_seconds"], 900)

    def test_runtime_contract_grants_no_provider_or_credential_capability(self):
        contract = self._json(RUNTIME_PATH)
        self.assertEqual(
            contract["capabilities"],
            {
                "provider_credentials": False,
                "api_credentials": False,
                "model_credentials": False,
                "database_credentials": False,
                "protected_path_mutation": False,
            },
        )

    def test_adr_0010_records_live_authority_failure_and_dormancy(self):
        adr = self._text(ADR10_PATH)
        for marker in (
            "P0A contract was internally coherent but operationally unimplementable with `GITHUB_TOKEN` for `.github/workflows/**`",
            "P0B installation PR and CI proved only static/unit behavior",
            "Live acceptance is authoritative",
            "#87 is superseded/not-planned, not completed",
            "dormant historical/fail-closed state",
            "must not be invoked after this reconciliation",
            "Credentialed protected-path mutation is deferred to I11",
            "No such credential is authorized now",
            "#85 must avoid `.github/**`",
            "Exact runtime acquisition moves into ordinary read-only CI code",
            "#73 resumes only after completed #85",
        ):
            self.assertIn(marker, adr)
        for marker in (
            "credential type",
            "exact `Workflows` permission",
            "repository scope",
            "private-key/secret storage",
            "rotation",
            "revocation",
            "duration/review date",
            "audit and cleanup",
        ):
            self.assertIn(marker, adr)

    def test_infra_spec_39_is_exact_append_only_successor_and_supersedes_only_route(self):
        data = INFRA_PATH.read_bytes()
        self.assertGreater(len(data), INFRA_PREDECESSOR_SIZE)
        prefix = data[:INFRA_PREDECESSOR_SIZE]
        suffix = data[INFRA_PREDECESSOR_SIZE:]
        self.assertEqual(git_blob_sha_bytes(prefix), INFRA_PREDECESSOR_BLOB)
        self.assertTrue(suffix.startswith(b"\n# 39. Protected-path credential reconciliation and in-job runtime acquisition\n"))
        self.assertEqual(suffix.count(b"\n# 39."), 1)
        self.assertNotIn(b"\r\n", suffix)
        self.assertTrue(data.endswith(b"\n"))
        self.assertFalse(data.endswith(b"\n\n"))
        text = data.decode("utf-8")
        for marker in (
            "supersedes §38 only as the active implementation route",
            "§38 and ADR 0009 remain historical audit evidence",
            "#87 must not be treated as completed",
            "P0B bootstrap exception must never be reused",
            "must not be repaired using `GITHUB_TOKEN`",
            "connector, PAT, GitHub App, deploy key, or substitute credential",
            "in-job runtime acquisition is the mandatory current #85 route",
            "general protected-path mutation is deferred to I11",
            "ordinary publisher and existing rulesets remain unchanged",
            "#85 must depend on completed I10-0089, not on completed #87",
        ):
            self.assertIn(marker, text)

    def test_historical_authority_and_downstream_boundaries_remain_immutable(self):
        self.assertEqual(git_blob_sha(ADR9_PATH), ADR9_BLOB)
        self.assertEqual(git_blob_sha(SUPPLY_V2_PATH), SUPPLY_V2_BLOB)
        self.assertEqual(git_blob_sha(KD73_PATH), KD73_BLOB)
        self.assertEqual(git_blob_sha(KD87_PATH), KD87_BLOB)
        status = self._json(ROOT / "BUILD_STATUS.json")
        self.assertIn("I10-0073", status["active_task_ids"])
        self.assertNotIn("I10-0087", status["completed_task_ids"])
        self.assertIn("I10-0089", set(status["active_task_ids"]) | set(status["completed_task_ids"]))
        self.assertEqual(
            status["exact_relevant_heads"]["product_main_reference"],
            "8fd669336b36064e842252d69fb4016cc526a9d4",
        )

    def test_architecture_text_has_no_setup_python_manifest_or_credential_widening(self):
        adr = self._text(ADR10_PATH)
        infra = self._text(INFRA_PATH)[INFRA_PREDECESSOR_SIZE:]
        for text in (adr, infra):
            self.assertIn("Do not use `actions/setup-python`", text)
            self.assertIn("no runtime lookup through the current `main` version-manifest", text)
            self.assertIn("no provider/API/model/database credentials", text)
            self.assertIn("900-second semantic builder timer", text)


if __name__ == "__main__":
    unittest.main()
