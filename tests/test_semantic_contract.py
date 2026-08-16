from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from control import semantic_contract as sc  # noqa: E402
from semantic_contract_vectors import corpus, valid_input, valid_output  # noqa: E402


class SemanticTransformationContractTests(unittest.TestCase):
    def test_schemas_are_draft_2020_12_and_strict(self):
        for name in sc.SCHEMA_FILES.values():
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertFalse(schema["additionalProperties"])

    def test_valid_structured_input_and_exact_identity_are_accepted(self):
        inp = valid_input()
        self.assertEqual(inp["transform_id"], sc.expected_transform_id(inp))
        sc.validate_semantic_input(inp)
        again = copy.deepcopy(inp)
        sc.validate_semantic_input(again)
        self.assertEqual(sc.input_sha256(inp), sc.input_sha256(again))

    def test_valid_structured_output_is_accepted_and_derived_only(self):
        inp = valid_input()
        out = valid_output(inp)
        result = sc.verify_semantic_output(inp, out)
        self.assertEqual(result["decision"], "accept")
        self.assertTrue(result["materialization_allowed"])
        self.assertEqual(result["codes"], ["ACCEPT"])
        self.assertEqual(out["classification"], "derived_non_authoritative")
        self.assertEqual(out["authority_boundary"]["may_override"], [])

    def test_malformed_output_is_rejected_fail_closed(self):
        inp, out = corpus()["invalid"]
        first = sc.verify_semantic_output(inp, out)
        second = sc.verify_semantic_output(inp, copy.deepcopy(out))
        self.assertEqual(first, second)
        self.assertEqual(first["decision"], "reject")
        self.assertFalse(first["materialization_allowed"])
        self.assertEqual(first["codes"], ["SCHEMA_INVALID"])
        self.assertEqual(first["fallback"]["mode"], "deterministic_task_context_only")

    def test_unsupported_input_and_output_schema_versions_are_rejected(self):
        inp = valid_input()
        bad_input = copy.deepcopy(inp)
        bad_input["schema"] = "hwm-semantic-transform-input/v2"
        with self.assertRaises(sc.SemanticContractError) as ctx:
            sc.validate_semantic_input(bad_input)
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_SCHEMA_VERSION")

        inp, out = corpus()["unsupported"]
        result = sc.verify_semantic_output(inp, out)
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["codes"], ["UNSUPPORTED_SCHEMA_VERSION"])
        self.assertFalse(result["materialization_allowed"])

    def test_missing_source_or_prompt_provenance_is_rejected(self):
        inp = valid_input()
        broken = copy.deepcopy(inp)
        broken["inputs"][0].pop("provenance")
        broken["transform_id"] = sc.expected_transform_id(broken)
        with self.assertRaises(sc.SemanticContractError) as ctx:
            sc.validate_semantic_input(broken)
        self.assertEqual(ctx.exception.code, "SCHEMA_INVALID")

        out = valid_output(inp)
        out["provenance_binding"]["prompt_rendered_sha256"] = "f" * 64
        result = sc.verify_semantic_output(inp, out)
        self.assertEqual(result["codes"], ["PROVENANCE_MISMATCH"])
        self.assertFalse(result["materialization_allowed"])

    def test_authority_promotion_attempt_is_rejected(self):
        inp = valid_input()
        out = valid_output(inp)
        out["classification"] = "authoritative"
        result = sc.verify_semantic_output(inp, out)
        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["codes"], ["AUTHORITY_PROMOTION_ATTEMPT"])
        self.assertFalse(result["materialization_allowed"])
        self.assertTrue(result["fallback"]["deterministic_task_context_usable"])

    def test_conflicting_historical_inputs_cannot_be_silently_resolved(self):
        inp, valid = corpus()["conflicting"]
        self.assertEqual(sc.verify_semantic_output(inp, valid)["decision"], "accept")

        omitted_conflict = copy.deepcopy(valid)
        omitted_conflict["historical_semantics"]["conflicts"] = []
        result = sc.verify_semantic_output(inp, omitted_conflict)
        self.assertEqual(result["codes"], ["HISTORICAL_SEMANTICS_MISMATCH"])
        self.assertFalse(result["materialization_allowed"])

        silent_winner = copy.deepcopy(valid)
        silent_winner["artifacts"][0]["conflict_ids"] = []
        silent_winner["artifacts"][0]["historical_labels"] = ["superseded"]
        result = sc.verify_semantic_output(inp, silent_winner)
        self.assertEqual(result["codes"], ["SILENT_CONFLICT_SELECTION"])
        self.assertFalse(result["materialization_allowed"])

    def test_supersession_and_ambiguity_are_explicit_and_preserved(self):
        inp, out = corpus()["ambiguous"]
        result = sc.verify_semantic_output(inp, out)
        self.assertEqual(result["decision"], "accept")
        artifact = out["artifacts"][0]
        self.assertIn("ambiguous", artifact["historical_labels"])
        self.assertIn("superseded", artifact["historical_labels"])
        self.assertEqual(out["historical_semantics"], inp["historical_semantics"])

    def test_verifier_rejection_is_deterministic_and_fail_closed(self):
        inp, out = corpus()["verifier_rejected"]
        one = sc.verify_semantic_output(inp, out)
        two = sc.verify_semantic_output(copy.deepcopy(inp), copy.deepcopy(out))
        self.assertEqual(one, two)
        self.assertEqual(one["decision"], "reject")
        self.assertFalse(one["materialization_allowed"])
        self.assertEqual(one["fallback"]["semantic_materialization"], "none")
        self.assertTrue(one["fallback"]["deterministic_task_context_usable"])

    def test_partial_truncation_is_explicit_and_budget_overflow_rejected(self):
        inp, partial = corpus()["truncated"]
        accepted = sc.verify_semantic_output(inp, partial)
        self.assertEqual(accepted["decision"], "accept")
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["finish_reason"], "max_output_tokens")

        over = copy.deepcopy(partial)
        over["artifacts"][0]["content"] = "x" * (inp["budgets"]["output_max_utf8_bytes"] + 1)
        over["usage"]["output_utf8_bytes"] = len(over["artifacts"][0]["content"].encode("utf-8"))
        result = sc.verify_semantic_output(inp, over)
        self.assertEqual(result["codes"], ["BUDGET_EXCEEDED"])
        self.assertFalse(result["materialization_allowed"])

        bad_reason = copy.deepcopy(partial)
        bad_reason["finish_reason"] = "stop"
        result = sc.verify_semantic_output(inp, bad_reason)
        self.assertEqual(result["codes"], ["SCHEMA_INVALID"])

    def test_input_token_and_byte_budgets_are_enforced_before_acceptance(self):
        inp = valid_input()
        over_tokens = copy.deepcopy(inp)
        over_tokens["budget_observation"]["input_tokens"] = over_tokens["budgets"]["input_max_tokens"] + 1
        over_tokens["transform_id"] = sc.expected_transform_id(over_tokens)
        with self.assertRaises(sc.SemanticContractError) as ctx:
            sc.validate_semantic_input(over_tokens)
        self.assertEqual(ctx.exception.code, "BUDGET_EXCEEDED")

        wrong_bytes = copy.deepcopy(inp)
        wrong_bytes["budget_observation"]["input_utf8_bytes"] += 1
        wrong_bytes["transform_id"] = sc.expected_transform_id(wrong_bytes)
        with self.assertRaises(sc.SemanticContractError) as ctx:
            sc.validate_semantic_input(wrong_bytes)
        self.assertEqual(ctx.exception.code, "BUDGET_EXCEEDED")

    def test_timeout_retry_and_degraded_fallback_semantics_are_contract_defined(self):
        inp = valid_input()
        policy = inp["execution_policy"]
        self.assertEqual(policy["timeout_scope"], "per_attempt")
        self.assertEqual(policy["retryable_failures"], ["timeout", "transient_provider_error", "malformed_output"])
        self.assertEqual(policy["on_retry_exhausted"], "degraded_fallback")
        self.assertEqual(policy["on_verifier_rejection"], "fail_closed_no_semantic_materialization")
        self.assertEqual(policy["fallback_mode"], "deterministic_task_context_only")
        self.assertEqual(inp["budgets"]["max_attempts"], 2)

        one = sc.degraded_fallback_result(inp, "timeout", 2)
        two = sc.degraded_fallback_result(copy.deepcopy(inp), "timeout", 2)
        self.assertEqual(one, two)
        self.assertEqual(one["decision"], "degraded_fallback")
        self.assertEqual(one["codes"], ["RETRY_EXHAUSTED", "TIMEOUT"])
        self.assertFalse(one["materialization_allowed"])
        self.assertTrue(one["fallback"]["deterministic_task_context_usable"])

        with self.assertRaises(sc.SemanticContractError):
            sc.degraded_fallback_result(inp, "timeout", 1)

    def test_public_data_violation_in_prompt_input_or_output_is_rejected(self):
        inp = valid_input()
        bad_prompt = copy.deepcopy(inp)
        bad_prompt["llm_provenance"]["prompt"]["rendered_text"] = "api_key=abcdefghijklmnop"
        bad_prompt["llm_provenance"]["prompt"]["rendered_sha256"] = sc.sha256_bytes(
            bad_prompt["llm_provenance"]["prompt"]["rendered_text"].encode("utf-8")
        )
        bad_prompt["budget_observation"]["input_utf8_bytes"] = (
            len(bad_prompt["llm_provenance"]["prompt"]["rendered_text"].encode("utf-8"))
            + sum(len(s["content"].encode("utf-8")) for s in bad_prompt["inputs"])
        )
        bad_prompt["transform_id"] = sc.expected_transform_id(bad_prompt)
        with self.assertRaises(sc.SemanticContractError) as ctx:
            sc.validate_semantic_input(bad_prompt)
        self.assertEqual(ctx.exception.code, "PUBLIC_DATA_VIOLATION")

        bad_source = valid_input()
        bad_source["inputs"][0]["content"] = "Authorization: Bearer secret-secret-secret"
        bad_source["inputs"][0]["content_sha256"] = sc.sha256_bytes(bad_source["inputs"][0]["content"].encode())
        bad_source["inputs"][0]["provenance"]["content_sha256"] = bad_source["inputs"][0]["content_sha256"]
        bad_source["budget_observation"]["input_utf8_bytes"] = (
            len(bad_source["llm_provenance"]["prompt"]["rendered_text"].encode())
            + sum(len(s["content"].encode()) for s in bad_source["inputs"])
        )
        bad_source["transform_id"] = sc.expected_transform_id(bad_source)
        with self.assertRaises(sc.SemanticContractError) as ctx:
            sc.validate_semantic_input(bad_source)
        self.assertEqual(ctx.exception.code, "PUBLIC_DATA_VIOLATION")

        inp = valid_input()
        out = valid_output(inp)
        out["artifacts"][0]["content"] = "password=supersecretpassword"
        out["usage"]["output_utf8_bytes"] = len(out["artifacts"][0]["content"].encode())
        result = sc.verify_semantic_output(inp, out)
        self.assertEqual(result["codes"], ["PUBLIC_DATA_VIOLATION"])
        self.assertFalse(result["materialization_allowed"])

    def test_exact_source_provenance_propagation_is_required(self):
        inp = valid_input()
        out = valid_output(inp)
        out["source_provenance"][0]["content_sha256"] = "f" * 64
        result = sc.verify_semantic_output(inp, out)
        self.assertEqual(result["codes"], ["PROVENANCE_MISMATCH"])

    def test_no_live_api_runtime_or_credentials_are_implemented(self):
        source = (ROOT / "control" / "semantic_contract.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "import openai",
            "from openai",
            "import requests",
            "urllib.request",
            "httpx",
            "subprocess",
            "api_key=",
            "authorization: bearer",
        ):
            self.assertNotIn(forbidden, source)

    def test_deterministic_task_context_path_has_no_semantic_dependency(self):
        compiler = ROOT / "control" / "task_context_compiler.py"
        core = ROOT / "control" / "task_context_core.py"
        if compiler.exists():
            self.assertNotIn("semantic_contract", compiler.read_text(encoding="utf-8"))
        if core.exists():
            self.assertNotIn("semantic_contract", core.read_text(encoding="utf-8"))
        # The repository's pre-existing task-context test suite runs in the same
        # Infrastructure CI job. This contract adds no import or call edge from it.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
