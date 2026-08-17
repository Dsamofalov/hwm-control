import json
import unittest

from control.semantic_batch_input_config import (
    INPUT_CONFIG_PATH,
    ROOT,
    generate_manifest_from_input_config,
    load_input_config,
    materialize_manifest_generator_inputs,
    validate_source_content_readbacks,
)
from control.semantic_batch_manifest import canonical_bytes, classify_replay
from control.semantic_batch_result import validate_coverage, validate_result, verify_batch

CLAIMS = '{"authority":"historical","claim_id":"hc1-5c814891680dd82b0d956ddd0663bf985566b16dafe4951f2e989248682f740b","predicate":"development_lane","provenance":{"blob_sha":"61ad23b52b3115bea8bf67c5b1fb6b07932b6748","commit":"8fd669336b36064e842252d69fb4016cc526a9d4","content_sha256":"edd0151823e2681190ba8209b95efea58a8d1d524f3a102ed9e18041f5ddb350","locator":{"end_line":5,"kind":"line_range","start_line":5},"path":"ABILITY_MERGE_CANON.md","repository":"Dsamofalov/hwm_predictor","source_class":"specification_history"},"relations":{"conflicts_with":[],"superseded_by":[],"supersedes":[]},"schema":"hwm-historical-claim/v1","status":"supported","subject":"product:ability-development-governance","validity":{"valid_from":"2026-08-13T00:00:00Z","valid_until":null},"value":"> Ability development no longer uses a dedicated `ability` source branch or a merge-back lane. The ability domain is a logical module and ownership boundary inside normal development on `main`."}\n{"authority":"historical","claim_id":"hc1-6619df5bcece7c7b85a21afccdb81aa40a2fa6ad6cd9b36deab1c6507a2713e9","predicate":"development_lane","provenance":{"blob_sha":"40e1eac296094a7528d58bc4ec8734673619d866","commit":"8fd669336b36064e842252d69fb4016cc526a9d4","content_sha256":"c3bdf6e12c9d63f970e59619691a7b005184937a08e014b81eacd0d8269a0491","locator":{"end_line":16,"kind":"line_range","start_line":16},"path":"changelog.md","repository":"Dsamofalov/hwm_predictor","source_class":"changelog"},"relations":{"conflicts_with":[],"superseded_by":[],"supersedes":[]},"schema":"hwm-historical-claim/v1","status":"supported","subject":"product:ability-development-governance","validity":{"valid_from":"2026-08-13T00:00:00Z","valid_until":null},"value":"- Ability is now a logical module/ownership boundary, not a dedicated Git development lane. All future ability implementation, evidence, tests, registry/risk updates and docs are committed directly to `main`."}\n'
CONFLICTS = '{"conflicts":[],"schema":"hwm-historical-conflicts/v1"}\n'
RUNTIME_HEADS = {
    "control": {"repository": "Dsamofalov/hwm-control", "commit": "ba52cde04ff0792917484e869af22fcf913ac2c9"},
    "context": {"repository": "Dsamofalov/hwm-context", "commit": "d651f40d0bb3a3ef0e52fca95e5400ed3db3d772"},
    "product": {"repository": "Dsamofalov/hwm_predictor", "commit": "8fd669336b36064e842252d69fb4016cc526a9d4"},
}


class FirstSemanticBatchMaterializationTests(unittest.TestCase):
    def _source_contents(self, config):
        contents = {}
        for source in config["source_snapshot"]["sources"]:
            if source["repository"] == "Dsamofalov/hwm-control":
                data = (ROOT / source["path"]).read_bytes()
            elif source["path"] == "claims/claims.jsonl":
                data = CLAIMS.encode("utf-8")
            elif source["path"] == "claims/conflicts.json":
                data = CONFLICTS.encode("utf-8")
            else:
                self.fail(f"unexpected frozen source: {source}")
            contents[source["source_id"]] = data
        return contents

    def test_first_batch_exact_readback_and_verifier_acceptance(self):
        config = load_input_config(INPUT_CONFIG_PATH)
        source_contents = self._source_contents(config)
        validate_source_content_readbacks(config, source_contents)

        generated = generate_manifest_from_input_config(
            config,
            runtime_heads=RUNTIME_HEADS,
            source_contents=source_contents,
        )
        manifest_path = ROOT / "semantic-batches" / "I09-0067" / "manifest.json"
        coverage_path = ROOT / "semantic-batches" / "I09-0067" / "coverage.json"
        result_path = ROOT / "semantic-batches" / "I09-0067" / "result.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(canonical_bytes(generated), manifest_path.read_bytes())
        self.assertEqual(
            manifest["batch_id"],
            "smb1-6bbf7987de53b0922795a707dfe07e86b6b4c86b6d6ed0393e87fe27cf8f5ecc",
        )
        self.assertEqual(len(manifest["required_coverage_set"]), 19)
        self.assertEqual(
            [p["input_utf8_bytes"] for p in manifest["partition_plan"]["partitions"]],
            [58083, 59449, 58656],
        )
        self.assertTrue(all(row["status"] == "processed" for row in coverage["rows"]))
        self.assertEqual(coverage["coverage_sha256"], "d7933da80707fa78ed9f60d4861db286a416d995d3fcd896c234fb3244a1fdca")
        self.assertEqual(result["result_sha256"], "757109138c1af88363f1124d886e671dbf81c740d17cf5b103adc73cff7bdf6f")
        self.assertTrue(all(a["epistemic_status"] == "unverified" for a in result["artifacts"]))
        self.assertEqual(result["historical_semantics"], manifest["historical_semantics"])
        self.assertEqual(result["historical_semantics"]["supersessions"], [])

        validate_coverage(manifest, coverage)
        validate_result(manifest, coverage, result)
        source_readbacks = materialize_manifest_generator_inputs(
            config,
            runtime_heads=RUNTIME_HEADS,
            source_contents=source_contents,
        )["source_readbacks"]
        verification = verify_batch(manifest, coverage, result, source_readbacks)
        self.assertTrue(verification["accepted"])
        self.assertEqual(verification["classification"], "derived_non_authoritative")

        self.assertEqual(classify_replay(manifest, manifest, kind="manifest"), "idempotent_replay")
        self.assertEqual(classify_replay(coverage, coverage, kind="coverage"), "idempotent_replay")
        self.assertEqual(classify_replay(result, result, kind="result"), "idempotent_replay")


if __name__ == "__main__":
    unittest.main()
