import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from control.state_reducer import ProjectStateReductionError, reduce_project_state

ROOT = Path(__file__).resolve().parents[1]
V1 = json.loads((ROOT / "schemas" / "project-state.v1.schema.json").read_text(encoding="utf-8"))
V2 = json.loads((ROOT / "schemas" / "project-state.v2.schema.json").read_text(encoding="utf-8"))
SHA_HEAD = "1111111111111111111111111111111111111111"
SHA_CORE = "2222222222222222222222222222222222222222"
SHA_FULL = "3333333333333333333333333333333333333333"
SHA_STALE = "4444444444444444444444444444444444444444"
CONTROL_SHA = "9eafc7aeca2dae3f2f7134f05be19da486fd1c2e"
PRODUCT_REPO = "Dsamofalov/hwm_predictor"
PRODUCT_REF = "refs/heads/main"
WORKFLOW = ".github/workflows/ci.yml"


def provenance(kind, sha, reference):
    return [{"kind": kind, "repo": PRODUCT_REPO, "sha": sha, "reference": reference}]


def known_product(sha=SHA_HEAD):
    return {
        "status": "known",
        "repository": PRODUCT_REPO,
        "ref": PRODUCT_REF,
        "sha": sha,
        "provenance": provenance("git_ref", sha, PRODUCT_REF),
    }


def known_checkpoint(sha, gate):
    return {
        "status": "known",
        "sha": sha,
        "provenance": provenance(
            "github_actions_run",
            sha,
            f"workflow={WORKFLOW};run=101;suite=201;gate={gate};check_run=301;status_id=401",
        ),
    }


def unknown(reason):
    return {"status": "unknown", "reason": reason}


def error(code="UPSTREAM_FAILURE"):
    return {"status": "error", "error": {"code": code, "message": "provider failed", "retryable": True}}


def inputs():
    return {
        "generated_at": "2026-08-14T13:20:00Z",
        "provenance": [{"kind": "git_ref", "repo": "Dsamofalov/hwm-control", "sha": CONTROL_SHA, "reference": "refs/heads/main"}],
        "product_head": known_product(),
        "checkpoints": {
            "repository": PRODUCT_REPO,
            "workflow": WORKFLOW,
            "last_core_green": known_checkpoint(SHA_CORE, "HWM / Core"),
            "last_full_green": known_checkpoint(SHA_FULL, "HWM / Full"),
        },
        "last_post_merge_green": unknown("no exact post-merge evidence"),
        "last_live_evidenced": error("LIVE_PROVIDER_FAILURE"),
        "requirements": {
            "M14": {"status": "blocked", "missing_gates": ["live", "core"]},
            "M01": {"status": "partial", "missing_gates": ["full"]},
        },
        "tasks": {"ready": [9, 2], "claimed": [6], "blocked": [8, 7]},
        "knowledge": {"status": "unknown", "reason": "Knowledge materialization not built."},
        "graph": {"status": "unknown", "reason": "Graph materialization not built."},
    }


class StateConsistencyTests(unittest.TestCase):
    def reduce(self, mutate=None):
        values = inputs()
        if mutate is not None:
            mutate(values)
        return reduce_project_state(**values)

    def test_exact_sources_remain_independent_and_schema_valid(self):
        state = self.reduce()
        self.assertEqual(state["schema"], "hwm-project-state/v2")
        self.assertEqual(state["product"]["head"]["sha"], SHA_HEAD)
        self.assertEqual(state["product"]["last_core_green"]["sha"], SHA_CORE)
        self.assertEqual(state["product"]["last_full_green"]["sha"], SHA_FULL)
        self.assertEqual(state["product"]["head"]["provenance"][0]["sha"], SHA_HEAD)
        self.assertEqual(state["product"]["last_core_green"]["provenance"][0]["sha"], SHA_CORE)
        self.assertEqual(state["product"]["last_full_green"]["provenance"][0]["sha"], SHA_FULL)
        Draft202012Validator(V2, format_checker=FormatChecker()).validate(state)
        self.assertTrue(list(Draft202012Validator(V1, format_checker=FormatChecker()).iter_errors(state)))

    def test_product_head_sha_provenance_mismatch_is_rejected(self):
        def stale(values):
            values["product_head"]["provenance"][0]["sha"] = SHA_STALE
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(stale)

    def test_checkpoint_sha_provenance_mismatch_is_rejected(self):
        def stale(values):
            values["checkpoints"]["last_core_green"]["provenance"][0]["sha"] = SHA_STALE
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(stale)

    def test_missing_product_evidence_stays_unknown_without_checkpoint_guess(self):
        def missing(values):
            values["product_head"] = {
                "status": "unknown",
                "repository": PRODUCT_REPO,
                "ref": PRODUCT_REF,
                "reason": "exact ref unavailable",
            }
        state = self.reduce(missing)
        self.assertEqual(state["product"]["head"], {"status": "unknown", "reason": "exact ref unavailable"})
        self.assertNotIn("sha", state["product"]["head"])
        self.assertEqual(state["product"]["last_core_green"]["sha"], SHA_CORE)
        self.assertEqual(state["product"]["last_full_green"]["sha"], SHA_FULL)

    def test_guessed_sha_on_unknown_lifecycle_is_rejected(self):
        def guessed(values):
            values["checkpoints"]["last_full_green"] = {
                "status": "unknown",
                "reason": "no exact Full evidence",
                "sha": SHA_HEAD,
            }
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(guessed)

    def test_core_and_full_lifecycles_do_not_substitute_for_each_other(self):
        def independent(values):
            values["checkpoints"]["last_core_green"] = unknown("no exact Core evidence")
            values["checkpoints"]["last_full_green"] = error("FULL_PROVIDER_FAILURE")
        state = self.reduce(independent)
        self.assertEqual(state["product"]["last_core_green"]["status"], "unknown")
        self.assertEqual(state["product"]["last_full_green"]["status"], "error")
        self.assertNotIn("sha", state["product"]["last_core_green"])
        self.assertNotIn("sha", state["product"]["last_full_green"])
        self.assertEqual(state["product"]["head"]["sha"], SHA_HEAD)

    def test_malformed_mixed_lifecycle_is_rejected(self):
        def malformed(values):
            values["last_post_merge_green"] = {
                "status": "error",
                "error": {"code": "UPSTREAM_FAILURE", "message": "failed", "retryable": True},
                "reason": "ambiguous",
            }
        with self.assertRaises(ProjectStateReductionError):
            self.reduce(malformed)

    def test_set_like_ordering_does_not_change_canonical_output(self):
        first = self.reduce()
        values = inputs()
        values["requirements"] = {
            "M01": {"status": "partial", "missing_gates": ["full"]},
            "M14": {"status": "blocked", "missing_gates": ["core", "live"]},
        }
        values["tasks"] = {"ready": [2, 9], "claimed": [6], "blocked": [7, 8]}
        second = reduce_project_state(**values)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
