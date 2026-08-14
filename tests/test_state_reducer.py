import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from control.state_reducer import PROJECT_STATE_SCHEMA, ProjectStateReductionError, reduce_project_state

ROOT = Path(__file__).resolve().parents[1]
V2 = json.loads((ROOT / "schemas" / "project-state.v2.schema.json").read_text(encoding="utf-8"))
V1 = json.loads((ROOT / "schemas" / "project-state.v1.schema.json").read_text(encoding="utf-8"))
SHA = "0123456789abcdef0123456789abcdef01234567"
SHA2 = "89abcdef0123456789abcdef0123456789abcdef"
SHA3 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CONTROL_SHA = "d2d8c478f845ccbc1c099b450e29b457fc0d3a13"
PRODUCT_REPO = "Dsamofalov/hwm_predictor"
PRODUCT_REF = "refs/heads/main"
WORKFLOW = ".github/workflows/ci.yml"
CORE_GATE = "HWM / Core"
FULL_GATE = "HWM / Full"


def provenance(kind="git_ref", repo=PRODUCT_REPO, sha=SHA, reference=PRODUCT_REF):
    item = {"kind": kind, "repo": repo, "sha": sha}
    if reference is not None:
        item["reference"] = reference
    return [item]


def product(status="known"):
    base = {"status": status, "repository": PRODUCT_REPO, "ref": PRODUCT_REF}
    if status == "known":
        return {**base, "sha": SHA, "provenance": provenance()}
    if status == "unknown":
        return {**base, "reason": "exact refs/heads/main is unavailable"}
    return {**base, "error": {"code": "PROVIDER_UNAVAILABLE", "message": "provider unavailable", "retryable": True}}


def checkpoint_reference(gate, *, workflow=WORKFLOW, run=101, suite=201, check_run=301, status_id=401):
    return (
        f"workflow={workflow};run={run};suite={suite};gate={gate};"
        f"check_run={check_run};status_id={status_id}"
    )


def checkpoint(status="known", sha=SHA, gate=CORE_GATE):
    if status == "known":
        return {
            "status": "known",
            "sha": sha,
            "provenance": provenance(
                kind="github_actions_run",
                sha=sha,
                reference=checkpoint_reference(gate),
            ),
        }
    if status == "unknown":
        return {"status": "unknown", "reason": "no exact successful checkpoint evidence found"}
    return {"status": "error", "error": {"code": "UPSTREAM_FAILURE", "message": "provider failed", "retryable": True}}


def checkpoint_envelope(core="known", full="known"):
    return {
        "repository": PRODUCT_REPO,
        "workflow": WORKFLOW,
        "last_core_green": checkpoint(core, SHA, CORE_GATE),
        "last_full_green": checkpoint(full, SHA2, FULL_GATE),
    }


def auxiliary(sha=SHA3):
    return {
        "kind": "evidence_manifest",
        "repo": "Dsamofalov/hwm-control",
        "sha": sha,
        "reference": "evidence/remediation.json",
    }


def inputs():
    return {
        "generated_at": "2026-08-14T12:50:00Z",
        "provenance": provenance(repo="Dsamofalov/hwm-control", sha=CONTROL_SHA, reference="refs/heads/main"),
        "product_head": product(),
        "checkpoints": checkpoint_envelope(),
        "last_post_merge_green": checkpoint("unknown"),
        "last_live_evidenced": checkpoint("unknown"),
        "requirements": {
            "M14": {"status": "blocked", "missing_gates": ["z-gate", "a-gate"]},
            "M01": {"status": "complete", "missing_gates": []},
        },
        "tasks": {"ready": [9, 2], "claimed": [5], "blocked": [8, 6]},
        "knowledge": {"status": "unknown", "reason": "Knowledge materialization not built."},
        "graph": {"status": "unknown", "reason": "Graph materialization not built."},
    }


class MinimalStateReducerTests(unittest.TestCase):
    def reduce(self, **updates):
        values = inputs()
        values.update(updates)
        return reduce_project_state(**values)

    def test_product_head_known_preserves_exact_sha_and_provenance(self):
        source = product("known")
        state = self.reduce(product_head=source)
        self.assertEqual(state["product"]["head"], {"status": "known", "sha": SHA, "provenance": source["provenance"]})

    def test_product_head_sha_provenance_mismatch_is_rejected(self):
        value = product("known")
        value["provenance"][0]["sha"] = SHA2
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value)

    def test_product_head_wrong_provenance_repo_is_rejected(self):
        value = product("known")
        value["provenance"][0]["repo"] = "Dsamofalov/hwm-control"
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value)

    def test_product_head_wrong_provenance_ref_is_rejected(self):
        value = product("known")
        value["provenance"][0]["reference"] = "refs/heads/ability"
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value)

    def test_product_head_auxiliary_plus_exact_binding_passes(self):
        value = product("known")
        value["provenance"] = [auxiliary(), *value["provenance"]]
        state = self.reduce(product_head=value)
        self.assertEqual(state["product"]["head"]["provenance"], value["provenance"])

    def test_product_head_only_auxiliary_provenance_is_rejected(self):
        value = product("known")
        value["provenance"] = [auxiliary()]
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value)

    def test_product_head_unknown_preserves_sanitized_reason_without_guessed_sha(self):
        state = self.reduce(product_head=product("unknown"))
        self.assertEqual(state["product"]["head"], {"status": "unknown", "reason": "exact refs/heads/main is unavailable"})
        self.assertNotIn("sha", state["product"]["head"])
        self.assertNotIn("provenance", state["product"]["head"])

    def test_product_head_error_preserves_structured_error(self):
        state = self.reduce(product_head=product("error"))
        self.assertEqual(
            state["product"]["head"],
            {"status": "error", "error": {"code": "PROVIDER_UNAVAILABLE", "message": "provider unavailable", "retryable": True}},
        )

    def test_product_head_error_message_is_sanitized_to_single_line(self):
        value = product("error")
        value["error"]["message"] = " provider\n temporarily   unavailable "
        state = self.reduce(product_head=value)
        self.assertEqual(state["product"]["head"]["error"]["message"], "provider temporarily unavailable")

    def test_unknown_never_uses_cached_or_extra_sha(self):
        value = product("unknown")
        value["cached_sha"] = SHA
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value)

    def test_product_identity_mismatch_is_rejected(self):
        value = product("known")
        value["ref"] = "refs/heads/other"
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value)

    def test_valid_exact_core_binding_passes(self):
        state = self.reduce(checkpoints=checkpoint_envelope("known", "unknown"))
        self.assertEqual(state["product"]["last_core_green"]["sha"], SHA)

    def test_valid_exact_full_binding_passes(self):
        state = self.reduce(checkpoints=checkpoint_envelope("unknown", "known"))
        self.assertEqual(state["product"]["last_full_green"]["sha"], SHA2)

    def test_core_stale_provenance_sha_is_rejected(self):
        value = checkpoint_envelope()
        value["last_core_green"]["provenance"][0]["sha"] = SHA3
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_full_stale_provenance_sha_is_rejected(self):
        value = checkpoint_envelope()
        value["last_full_green"]["provenance"][0]["sha"] = SHA3
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_checkpoint_wrong_workflow_in_provenance_is_rejected(self):
        value = checkpoint_envelope()
        value["last_core_green"]["provenance"][0]["reference"] = checkpoint_reference(
            CORE_GATE, workflow=".github/workflows/other.yml"
        )
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_core_provenance_with_full_gate_is_rejected(self):
        value = checkpoint_envelope()
        value["last_core_green"]["provenance"][0]["reference"] = checkpoint_reference(FULL_GATE)
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_full_provenance_with_core_gate_is_rejected(self):
        value = checkpoint_envelope()
        value["last_full_green"]["provenance"][0]["reference"] = checkpoint_reference(CORE_GATE)
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_checkpoint_auxiliary_plus_exact_binding_passes(self):
        value = checkpoint_envelope()
        value["last_core_green"]["provenance"] = [auxiliary(), *value["last_core_green"]["provenance"]]
        state = self.reduce(checkpoints=value)
        self.assertEqual(state["product"]["last_core_green"]["provenance"], value["last_core_green"]["provenance"])

    def test_checkpoint_only_auxiliary_provenance_is_rejected(self):
        value = checkpoint_envelope()
        value["last_core_green"]["provenance"] = [auxiliary()]
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_checkpoint_wrong_repo_in_provenance_is_rejected(self):
        value = checkpoint_envelope()
        value["last_full_green"]["provenance"][0]["repo"] = "Dsamofalov/hwm-control"
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_checkpoint_reference_requires_exact_extractor_identity_format(self):
        value = checkpoint_envelope()
        value["last_core_green"]["provenance"][0]["reference"] = (
            f"gate={CORE_GATE};workflow={WORKFLOW};run=101;suite=201;check_run=301;status_id=401"
        )
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_core_known_and_full_known_are_preserved_independently(self):
        state = self.reduce(checkpoints=checkpoint_envelope("known", "known"))
        self.assertEqual(state["product"]["last_core_green"]["sha"], SHA)
        self.assertEqual(state["product"]["last_full_green"]["sha"], SHA2)

    def test_core_unknown_full_known_are_independent(self):
        state = self.reduce(checkpoints=checkpoint_envelope("unknown", "known"))
        self.assertEqual(state["product"]["last_core_green"]["status"], "unknown")
        self.assertEqual(state["product"]["last_full_green"]["status"], "known")
        self.assertEqual(state["product"]["last_full_green"]["sha"], SHA2)

    def test_core_known_full_unknown_are_independent(self):
        state = self.reduce(checkpoints=checkpoint_envelope("known", "unknown"))
        self.assertEqual(state["product"]["last_core_green"]["status"], "known")
        self.assertEqual(state["product"]["last_full_green"]["status"], "unknown")

    def test_checkpoint_error_propagates_without_product_fallback(self):
        state = self.reduce(checkpoints=checkpoint_envelope("error", "known"), product_head=product("known"))
        self.assertEqual(state["product"]["last_core_green"]["status"], "error")
        self.assertEqual(state["product"]["last_core_green"]["error"]["code"], "UPSTREAM_FAILURE")
        self.assertNotEqual(state["product"]["last_core_green"].get("sha"), state["product"]["head"]["sha"])

    def test_product_unknown_does_not_fall_back_to_checkpoint_sha(self):
        state = self.reduce(product_head=product("unknown"), checkpoints=checkpoint_envelope("known", "known"))
        self.assertEqual(state["product"]["head"]["status"], "unknown")
        self.assertNotIn("sha", state["product"]["head"])

    def test_product_known_does_not_fall_back_to_checkpoint_provenance(self):
        value = product("known")
        value["provenance"] = [auxiliary()]
        checkpoints = checkpoint_envelope()
        checkpoints["last_core_green"]["sha"] = SHA
        checkpoints["last_core_green"]["provenance"][0]["sha"] = SHA
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value, checkpoints=checkpoints)

    def test_checkpoint_known_does_not_fall_back_to_product_provenance(self):
        checkpoints = checkpoint_envelope()
        checkpoints["last_core_green"]["provenance"] = [auxiliary()]
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=product("known"), checkpoints=checkpoints)

    def test_malformed_lifecycle_shape_is_rejected(self):
        value = product("known")
        value["reason"] = "ambiguous"
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value)

    def test_checkpoint_envelope_mismatch_is_rejected(self):
        value = checkpoint_envelope()
        value["workflow"] = ".github/workflows/other.yml"
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(checkpoints=value)

    def test_required_v2_fields_and_exact_marker(self):
        state = self.reduce()
        self.assertEqual(state["schema"], PROJECT_STATE_SCHEMA)
        self.assertEqual(
            set(state),
            {"schema", "generated_at", "provenance", "product", "requirements", "tasks", "knowledge", "graph"},
        )
        self.assertEqual(
            set(state["product"]),
            {"repo", "head", "last_core_green", "last_full_green", "last_post_merge_green", "last_live_evidenced"},
        )

    def test_output_validates_against_v2_schema(self):
        Draft202012Validator(V2, format_checker=FormatChecker()).validate(self.reduce())

    def test_v1_is_not_a_silent_target(self):
        state = self.reduce()
        self.assertEqual(state["schema"], "hwm-project-state/v2")
        errors = list(Draft202012Validator(V1, format_checker=FormatChecker()).iter_errors(state))
        self.assertTrue(errors)

    def test_disclosure_unsafe_known_provenance_is_rejected(self):
        value = product("known")
        value["provenance"][0]["reference"] = "Authorization: secret"
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(product_head=value)

    def test_identical_inputs_produce_identical_output(self):
        values = inputs()
        first = reduce_project_state(**copy.deepcopy(values))
        second = reduce_project_state(**copy.deepcopy(values))
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, separators=(",", ":")),
            json.dumps(second, ensure_ascii=False, separators=(",", ":")),
        )

    def test_set_like_input_order_is_canonicalized(self):
        first = self.reduce()
        values = inputs()
        values["requirements"] = {
            "M01": {"status": "complete", "missing_gates": []},
            "M14": {"status": "blocked", "missing_gates": ["a-gate", "z-gate"]},
        }
        values["tasks"] = {"ready": [2, 9], "claimed": [5], "blocked": [6, 8]}
        second = reduce_project_state(**values)
        self.assertEqual(first, second)

    def test_non_contract_requirement_is_rejected_by_output_validation(self):
        values = inputs()
        values["requirements"] = {"bad": {"status": "complete", "missing_gates": []}}
        with self.assertRaises(ProjectStateReductionError):
            reduce_project_state(**values)

    def test_post_merge_and_live_inputs_are_not_synthesized_or_gate_constrained(self):
        post = checkpoint("error")
        live = checkpoint("known", SHA2, CORE_GATE)
        state = self.reduce(last_post_merge_green=post, last_live_evidenced=live)
        self.assertEqual(state["product"]["last_post_merge_green"], post)
        self.assertEqual(state["product"]["last_live_evidenced"], live)


if __name__ == "__main__":
    unittest.main()
