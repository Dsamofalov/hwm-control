import json
import unittest
from pathlib import Path

from control.state_reducer import reduce_project_state

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_SHA = "8fd669336b36064e842252d69fb4016cc526a9d4"
CONTROL_SHA = "49fc7d9549a6f88ed3a2cd2dd9f6d94aa0c2306e"
RUN = 31727700552
SUITE = 86074732000


def product_provenance():
    return [{"kind": "git_ref", "repo": "Dsamofalov/hwm_predictor", "sha": PRODUCT_SHA, "reference": "refs/heads/main"}]


def checkpoint(gate, check_run, status_id):
    return {
        "status": "known",
        "sha": PRODUCT_SHA,
        "provenance": [{
            "kind": "github_actions_run",
            "repo": "Dsamofalov/hwm_predictor",
            "sha": PRODUCT_SHA,
            "reference": f"workflow=.github/workflows/ci.yml;run={RUN};suite={SUITE};gate={gate};check_run={check_run};status_id={status_id}",
        }],
    }


class MaterializedProjectStateTests(unittest.TestCase):
    def test_current_json_is_exact_reducer_output_and_canonical_bytes(self):
        core = checkpoint("HWM / Core", 94546993956, 52198023145)
        full = checkpoint("HWM / Full", 94546273227, 52197856764)
        expected = reduce_project_state(
            generated_at="2026-08-16T20:15:48Z",
            provenance=[
                {"kind": "git_ref", "repo": "Dsamofalov/hwm-control", "sha": CONTROL_SHA, "reference": "refs/heads/main"},
                *product_provenance(),
                *core["provenance"],
                *full["provenance"],
            ],
            product_head={
                "status": "known",
                "repository": "Dsamofalov/hwm_predictor",
                "ref": "refs/heads/main",
                "sha": PRODUCT_SHA,
                "provenance": product_provenance(),
            },
            checkpoints={
                "repository": "Dsamofalov/hwm_predictor",
                "workflow": ".github/workflows/ci.yml",
                "last_core_green": core,
                "last_full_green": full,
            },
            last_post_merge_green={"status": "unknown", "reason": "No authoritative I03 post-merge checkpoint input is available."},
            last_live_evidenced={"status": "unknown", "reason": "No authoritative I03 live-evidence checkpoint input is available."},
            requirements={},
            tasks={"ready": [], "claimed": [49], "blocked": [50]},
            knowledge={"status": "unknown", "reason": "No authoritative I03 knowledge-health input is available."},
            graph={"status": "unknown", "reason": "No authoritative I03 graph-health input is available."},
        )
        path = ROOT / "state" / "current.json"
        raw = path.read_bytes()
        canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
        self.assertEqual(raw, canonical)
        self.assertEqual(json.loads(raw), expected)


if __name__ == "__main__":
    unittest.main()
