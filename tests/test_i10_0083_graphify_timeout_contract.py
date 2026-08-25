import copy
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1_PATH = ROOT / "contracts" / "graphify-supply-chain.v1.json"
V2_PATH = ROOT / "contracts" / "graphify-supply-chain.v2.json"

V1_BLOB = "a22feb23061d96e920f4a8974bdbb94de9e8988e"
ADR0007_BLOB = "2e8169e8728797c89771696bcb24365e5b10d923"
GRAPH_SCHEMA_BLOBS = {
    "schemas/graph-snapshot.v1.schema.json": "5f96d6bf7da37a08b975cbedc1feccdbfe1ace12",
    "schemas/graph-metadata.v1.schema.json": "dee33775e362d48a6a7fa5cd34b0660aceeea679",
    "schemas/graph-health.v1.schema.json": "b3495ee2ddab379330625ee06e5377fc8d7105d8",
    "schemas/graph-query.v1.schema.json": "5ac42a42e8f51a0dc3c250e472e4c23ae5b6f5c4",
}
EXACT_COMMAND = ["python", "-m", "graphify", "extract", ".", "--code-only", "--no-cluster", "--no-viz"]
CORE_SCHEMA_MAP = {
    "bootstrap_baseline": "hwm-infra-baseline/bootstrap-v0",
    "job": "hwm-job/v1",
    "result": "hwm-result/v1",
    "task": "hwm-task/v1",
    "claim": "hwm-claim/v1",
    "knowledge_delta": "hwm-knowledge-delta/v1",
    "project_state": "hwm-project-state/v2",
}
TIMEOUT_KEYS = {
    "builder_wall_clock_timeout_seconds",
    "timeout_clock",
    "timeout_start_boundary",
    "timeout_end_boundary",
    "timeout_scope",
    "timeout_health_state",
    "timeout_usable",
    "timeout_process_tree_policy",
    "partial_output_policy",
    "timeout_partial_snapshot_metadata_policy",
    "timeout_partial_canonical_artifact_policy",
    "timeout_snapshot_identity",
    "timeout_publication_policy",
    "timeout_consumer_fallback",
    "retry_policy",
    "retry_partial_output_reuse",
    "retry_exact_inputs_policy",
    "timeout_change_policy",
    "github_actions_job_containment_policy",
}


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


class GraphifyTimeoutContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1 = json.loads(V1_PATH.read_text(encoding="utf-8"))
        cls.v2 = json.loads(V2_PATH.read_text(encoding="utf-8"))

    def test_v1_and_historical_adr_are_byte_immutable(self):
        self.assertEqual(git_blob_sha(V1_PATH), V1_BLOB)
        self.assertEqual(
            git_blob_sha(ROOT / "docs" / "ADR" / "0007-i10-graphify-supply-chain-and-graph-contracts.md"),
            ADR0007_BLOB,
        )

    def test_v2_marker_supersession_and_all_v1_pins_are_preserved(self):
        self.assertEqual(self.v2["schema"], "hwm-graphify-supply-chain/v2")
        self.assertEqual(self.v2["supersedes"], "hwm-graphify-supply-chain/v1")

        predecessor_view = copy.deepcopy(self.v2)
        predecessor_view["schema"] = "hwm-graphify-supply-chain/v1"
        predecessor_view.pop("supersedes")
        for key in TIMEOUT_KEYS:
            predecessor_view["execution"].pop(key)
        self.assertEqual(predecessor_view, self.v1)

        self.assertEqual(self.v2["max_snapshot_bytes"], 67108864)
        self.assertEqual(self.v2["execution"]["command"], EXACT_COMMAND)
        self.assertEqual(self.v2["provider_environment_deny"], self.v1["provider_environment_deny"])
        self.assertEqual(self.v2["execution"]["semantic_docs_models"], "forbidden")
        self.assertEqual(self.v2["execution"]["mcp_server"], "forbidden")
        self.assertEqual(self.v2["execution"]["remote_database_push"], "forbidden")
        self.assertEqual(self.v2["install"]["phase_b_network"], self.v1["install"]["phase_b_network"])

    def test_timeout_is_exact_required_nondefaulted_monotonic_900_seconds(self):
        execution = self.v2["execution"]
        self.assertTrue(TIMEOUT_KEYS.issubset(execution.keys()))
        timeout = execution["builder_wall_clock_timeout_seconds"]
        self.assertIs(type(timeout), int)
        self.assertEqual(timeout, 900)
        self.assertEqual(execution["timeout_clock"], "monotonic")
        self.assertEqual(
            execution["timeout_start_boundary"],
            "verified-wheelhouse-ready, network-denied, read-only-exact-source-ready",
        )
        self.assertEqual(execution["timeout_end_boundary"], "canonical-artifact-emission-complete")
        self.assertFalse(any("default" in key.lower() for key in execution))

    def test_timeout_covers_complete_builder_and_fails_closed(self):
        execution = self.v2["execution"]
        self.assertEqual(
            execution["timeout_scope"],
            [
                "offline-installation",
                "exact-structural-graphify-invocation",
                "output-parsing",
                "normalization",
                "schema-validation",
                "digest-calculation",
                "canonical-artifact-emission",
            ],
        )
        self.assertEqual(execution["timeout_health_state"], "timeout_incomplete_build")
        self.assertIs(execution["timeout_usable"], False)
        self.assertEqual(execution["timeout_process_tree_policy"], "terminate")
        self.assertEqual(execution["partial_output_policy"], "discard")
        self.assertEqual(execution["timeout_partial_snapshot_metadata_policy"], "reject")
        self.assertEqual(execution["timeout_partial_canonical_artifact_policy"], "delete")
        self.assertIsNone(execution["timeout_snapshot_identity"])
        self.assertEqual(execution["timeout_publication_policy"], "forbidden")
        self.assertEqual(execution["timeout_consumer_fallback"], "deterministic-raw-source")
        self.assertEqual(execution["retry_policy"], "clean-disposable-reexecution-only")
        self.assertEqual(execution["retry_partial_output_reuse"], "forbidden")
        self.assertEqual(execution["retry_exact_inputs_policy"], "same-exact-inputs")
        self.assertEqual(execution["timeout_change_policy"], "new-versioned-contract-amendment-required")
        self.assertEqual(
            execution["github_actions_job_containment_policy"],
            "may-exceed-900-seconds-only-to-record-fail-closed-health-result; semantic-builder-timeout-remains-900-seconds",
        )

        health = json.loads((ROOT / "schemas" / "graph-health.v1.schema.json").read_text(encoding="utf-8"))
        states = health["properties"]["state"]["enum"]
        self.assertEqual([state for state in states if state.startswith("timeout_")], ["timeout_incomplete_build"])

    def test_existing_graph_schemas_and_closed_core_schema_map_are_unchanged(self):
        for relative, expected_blob in GRAPH_SCHEMA_BLOBS.items():
            with self.subTest(relative=relative):
                self.assertEqual(git_blob_sha(ROOT / relative), expected_blob)

        status = json.loads((ROOT / "BUILD_STATUS.json").read_text(encoding="utf-8"))
        self.assertEqual(status["current_schema_versions"], CORE_SCHEMA_MAP)
        self.assertEqual(set(status["current_schema_versions"]), set(CORE_SCHEMA_MAP))


if __name__ == "__main__":
    unittest.main()
