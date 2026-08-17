import copy
import hashlib
import json
import unittest

from jsonschema import Draft202012Validator

from control.semantic_batch_input_config import (
    INPUT_CONFIG_PATH,
    INPUT_CONFIG_SCHEMA_PATH,
    SemanticBatchError,
    canonical_bytes,
    expected_input_config_sha256,
    generate_manifest_from_input_config,
    load_input_config,
    materialize_manifest_generator_inputs,
    validate_input_config,
    validate_source_content_readbacks,
)

ROOT = INPUT_CONFIG_PATH.parents[1]
CLAIMS = b'{"authority":"historical","claim_id":"hc1-5c814891680dd82b0d956ddd0663bf985566b16dafe4951f2e989248682f740b","predicate":"development_lane","provenance":{"blob_sha":"61ad23b52b3115bea8bf67c5b1fb6b07932b6748","commit":"8fd669336b36064e842252d69fb4016cc526a9d4","content_sha256":"edd0151823e2681190ba8209b95efea58a8d1d524f3a102ed9e18041f5ddb350","locator":{"end_line":5,"kind":"line_range","start_line":5},"path":"ABILITY_MERGE_CANON.md","repository":"Dsamofalov/hwm_predictor","source_class":"specification_history"},"relations":{"conflicts_with":[],"superseded_by":[],"supersedes":[]},"schema":"hwm-historical-claim/v1","status":"supported","subject":"product:ability-development-governance","validity":{"valid_from":"2026-08-13T00:00:00Z","valid_until":null},"value":"> Ability development no longer uses a dedicated `ability` source branch or a merge-back lane. The ability domain is a logical module and ownership boundary inside normal development on `main`."}\n{"authority":"historical","claim_id":"hc1-6619df5bcece7c7b85a21afccdb81aa40a2fa6ad6cd9b36deab1c6507a2713e9","predicate":"development_lane","provenance":{"blob_sha":"40e1eac296094a7528d58bc4ec8734673619d866","commit":"8fd669336b36064e842252d69fb4016cc526a9d4","content_sha256":"c3bdf6e12c9d63f970e59619691a7b005184937a08e014b81eacd0d8269a0491","locator":{"end_line":16,"kind":"line_range","start_line":16},"path":"changelog.md","repository":"Dsamofalov/hwm_predictor","source_class":"changelog"},"relations":{"conflicts_with":[],"superseded_by":[],"supersedes":[]},"schema":"hwm-historical-claim/v1","status":"supported","subject":"product:ability-development-governance","validity":{"valid_from":"2026-08-13T00:00:00Z","valid_until":null},"value":"- Ability is now a logical module/ownership boundary, not a dedicated Git development lane. All future ability implementation, evidence, tests, registry/risk updates and docs are committed directly to `main`."}\n'
CONFLICTS = b'{"conflicts":[],"schema":"hwm-historical-conflicts/v1"}\n'
EXPECTED_CONFIG_ID = "sbic1-e3ef5c9f6753c8413cdac51b244ac7c4916302c82d75af722658dff7cdbc52d9"
EXPECTED_KD_FRONTIER_SHA256 = "f7aa42bd6573a40e92dc61b755d17aac6a219d8218c8bdfca99cec2991bc9fad"
EXPECTED_SOURCE_FRONTIER_SHA256 = "0313558479287a3afa6025bd2dbc5ee65ac149eae184b7ab03f4e6f970245f57"


def reidentify(value):
    candidate = copy.deepcopy(value)
    candidate["config_id"] = "sbic1-" + "0" * 64
    candidate["config_sha256"] = "0" * 64
    projection = copy.deepcopy(candidate)
    projection.pop("config_id")
    projection.pop("config_sha256")
    digest = hashlib.sha256(canonical_bytes(projection)).hexdigest()
    candidate["config_id"] = "sbic1-" + digest
    candidate["config_sha256"] = digest
    return candidate


def exact_contents(config):
    out = {}
    for source in config["source_snapshot"]["sources"]:
        if source["repository"] == "Dsamofalov/hwm-control":
            data = (ROOT / source["path"]).read_bytes()
        elif source["path"] == "claims/claims.jsonl":
            data = CLAIMS
        elif source["path"] == "claims/conflicts.json":
            data = CONFLICTS
        else:
            raise AssertionError(source)
        out[source["source_id"]] = data
    return out


class SemanticBatchInputConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = load_input_config()

    def test_schema_and_config_are_strict_canonical_and_versioned(self):
        schema = json.loads(INPUT_CONFIG_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.config)
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["$defs"]["source"]["additionalProperties"])
        self.assertEqual(INPUT_CONFIG_PATH.read_bytes(), canonical_bytes(self.config))
        self.assertEqual(EXPECTED_CONFIG_ID, self.config["config_id"])
        self.assertEqual(
            EXPECTED_CONFIG_ID.removeprefix("sbic1-"),
            expected_input_config_sha256(self.config),
        )

    def test_owner_approved_frontier_is_fully_materialized(self):
        snapshot = self.config["source_snapshot"]
        self.assertEqual("I09-0066", snapshot["freeze_boundary_task_key"])
        self.assertEqual(19, snapshot["source_count"])
        self.assertEqual(176188, snapshot["total_utf8_bytes"])
        self.assertEqual(
            EXPECTED_SOURCE_FRONTIER_SHA256,
            snapshot["canonical_source_frontier_sha256"],
        )
        self.assertEqual(
            [f"{i:04d}:knowledge-delta:{key}" for i, key in enumerate((
                "I06-0009", "I07-0010", "I08-0035", "I08-0037", "I08-0038",
                "I08-0040", "I08-0042", "I09-0045", "I09-0046", "I09-0047",
                "I09-0048", "I09-0049", "I09-0054", "I09-0056", "I09-0062",
                "I09-0064", "I09-0066",
            ), 1)] + [
                "0018:historical-ledger:claims",
                "0019:historical-ledger:conflicts",
            ],
            [source["ordering_key"] for source in snapshot["sources"]],
        )
        for source in snapshot["sources"]:
            self.assertEqual("public-disclosure-safe", source["public_data_classification"])
            for field in (
                "repository", "source_commit", "path", "git_blob_sha",
                "content_sha256", "utf8_bytes", "media_type", "source_id",
                "ordering_key",
            ):
                self.assertIn(field, source)

    def test_trigger_evidence_is_exact_zero_previous_coverage(self):
        trigger = self.config["trigger"]
        self.assertEqual("knowledge_health/coverage", trigger["policy_kind"])
        zero = trigger["previous_accepted_semantic_coverage"]
        self.assertEqual(0, zero["accepted_semantic_batch_count"])
        self.assertEqual(0, zero["accepted_semantic_coverage_count"])
        self.assertEqual([], zero["accepted_batch_ids"])
        self.assertEqual([], zero["accepted_coverage_artifacts"])
        self.assertEqual(17, trigger["uncovered_knowledge_delta_count"])
        self.assertEqual(174209, trigger["uncovered_knowledge_delta_utf8_bytes"])
        self.assertEqual(
            EXPECTED_KD_FRONTIER_SHA256,
            trigger["canonical_frontier_sha256"],
        )
        self.assertEqual(
            "1a57aadca03dfe936b08d55de65602314a7b5aeb57e34fbeb3f7923f0eda8dd1",
            trigger["evidence_sha256"],
        )

    def test_exact_readback_and_generator_inputs_replay_byte_identically(self):
        contents = exact_contents(self.config)
        validate_source_content_readbacks(self.config, contents)
        runtime_heads = copy.deepcopy(
            self.config["source_snapshot"]["exact_source_heads"]
        )
        first = materialize_manifest_generator_inputs(
            self.config, runtime_heads=runtime_heads, source_contents=contents
        )
        second = materialize_manifest_generator_inputs(
            self.config, runtime_heads=runtime_heads, source_contents=contents
        )
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        manifest_a = generate_manifest_from_input_config(
            self.config, runtime_heads=runtime_heads, source_contents=contents
        )
        manifest_b = generate_manifest_from_input_config(
            self.config, runtime_heads=runtime_heads, source_contents=contents
        )
        self.assertEqual(canonical_bytes(manifest_a), canonical_bytes(manifest_b))
        self.assertEqual(19, len(manifest_a["required_coverage_set"]))
        self.assertEqual(
            [58083, 59449, 58656],
            [part["input_utf8_bytes"] for part in manifest_a["partition_plan"]["partitions"]],
        )

    def test_partition_policy_and_oversize_result_are_exact(self):
        self.assertEqual(
            {
                "max_partition_utf8_bytes": 65536,
                "unit": "utf-8-bytes",
                "oversized_single_source": "fail-closed:P5R1_PARTITION_SOURCE_OVERSIZE",
            },
            self.config["partition_policy"],
        )
        self.assertEqual(
            22048,
            max(source["utf8_bytes"] for source in self.config["source_snapshot"]["sources"]),
        )

    def test_source_blob_head_trigger_limit_and_config_identity_are_bound(self):
        mutations = []
        a = copy.deepcopy(self.config)
        a["source_snapshot"]["exact_source_heads"]["context"]["commit"] = "f" * 40
        mutations.append(a)
        b = copy.deepcopy(self.config)
        b["source_snapshot"]["sources"][0]["git_blob_sha"] = "f" * 40
        mutations.append(b)
        c = copy.deepcopy(self.config)
        c["trigger"]["manifest_projection"]["affected_count"] += 1
        mutations.append(c)
        d = copy.deepcopy(self.config)
        d["partition_policy"]["max_partition_utf8_bytes"] = 65535
        mutations.append(d)
        for candidate in mutations:
            with self.subTest(candidate=candidate):
                with self.assertRaises(SemanticBatchError):
                    validate_input_config(candidate)

    def test_reidentified_duplicate_extra_field_public_data_and_authority_fail_closed(self):
        duplicate = copy.deepcopy(self.config)
        duplicate["source_snapshot"]["sources"][1]["source_id"] = (
            duplicate["source_snapshot"]["sources"][0]["source_id"]
        )
        with self.assertRaises(SemanticBatchError):
            validate_input_config(reidentify(duplicate))

        extra = copy.deepcopy(self.config)
        extra["source_snapshot"]["sources"][0]["unexpected"] = True
        with self.assertRaises(SemanticBatchError):
            validate_input_config(reidentify(extra))

        public = copy.deepcopy(self.config)
        public["source_snapshot"]["sources"][0]["public_data_classification"] = "unknown"
        with self.assertRaises(SemanticBatchError):
            validate_input_config(reidentify(public))

        stale = copy.deepcopy(self.config)
        stale["authority_boundary"]["state_current"]["path"] = "state/not-current.json"
        with self.assertRaises(SemanticBatchError) as ctx:
            validate_input_config(reidentify(stale))
        self.assertEqual("AUTHORITY_BOUNDARY_MISMATCH", ctx.exception.code)

    def test_state_current_and_i09_0048_context_are_not_sources_or_authority(self):
        pairs = {
            (source["repository"], source["path"])
            for source in self.config["source_snapshot"]["sources"]
        }
        self.assertNotIn(("Dsamofalov/hwm-control", "state/current.json"), pairs)
        self.assertNotIn(("Dsamofalov/hwm-context", "tasks/I09-0048/context.json"), pairs)
        self.assertEqual(
            "historical_snapshot_only_not_current_authority",
            self.config["authority_boundary"]["state_current"]["role"],
        )
        self.assertEqual(
            "excluded_first_batch_selector",
            self.config["authority_boundary"]["task_context_i09_0048"]["role"],
        )

    def test_source_content_mismatch_and_symbolic_runtime_head_fail_closed(self):
        contents = exact_contents(self.config)
        source_id = self.config["source_snapshot"]["sources"][0]["source_id"]
        contents[source_id] += b"x"
        with self.assertRaises(SemanticBatchError):
            validate_source_content_readbacks(self.config, contents)

        good = exact_contents(self.config)
        runtime_heads = copy.deepcopy(
            self.config["source_snapshot"]["exact_source_heads"]
        )
        runtime_heads["control"]["commit"] = "main"
        with self.assertRaises(SemanticBatchError) as ctx:
            materialize_manifest_generator_inputs(
                self.config, runtime_heads=runtime_heads, source_contents=good
            )
        self.assertEqual("RUNTIME_HEADS_MISMATCH", ctx.exception.code)

    def test_runtime_head_change_changes_future_manifest_identity_not_source_snapshot(self):
        contents = exact_contents(self.config)
        first_heads = copy.deepcopy(
            self.config["source_snapshot"]["exact_source_heads"]
        )
        second_heads = copy.deepcopy(first_heads)
        second_heads["control"]["commit"] = "f" * 40
        first = generate_manifest_from_input_config(
            self.config, runtime_heads=first_heads, source_contents=contents
        )
        second = generate_manifest_from_input_config(
            self.config, runtime_heads=second_heads, source_contents=contents
        )
        self.assertNotEqual(first["batch_id"], second["batch_id"])
        self.assertEqual(
            "d9c0745741315cfd5f3d322e77949d1040dabb9a",
            self.config["source_snapshot"]["exact_source_heads"]["control"]["commit"],
        )


if __name__ == "__main__":
    unittest.main()
