import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from control.validate_bootstrap import validate

ROOT = Path(__file__).resolve().parents[1]


class ProjectStateV2BootstrapTests(unittest.TestCase):
    def make_copy(self) -> Path:
        temp = Path(tempfile.mkdtemp()) / "repo"
        shutil.copytree(ROOT, temp, ignore=shutil.ignore_patterns(".git"))
        self.addCleanup(lambda: shutil.rmtree(temp.parent, ignore_errors=True))
        return temp

    @staticmethod
    def read_status(root: Path) -> dict:
        return json.loads((root / "BUILD_STATUS.json").read_text(encoding="utf-8"))

    @staticmethod
    def write_status(root: Path, data: dict) -> None:
        (root / "BUILD_STATUS.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_build_status_project_state_v2_passes(self):
        self.assertEqual(validate(ROOT), [])
        self.assertEqual(self.read_status(ROOT)["current_schema_versions"]["project_state"], "hwm-project-state/v2")

    def test_stale_project_state_v1_after_transition_fails(self):
        temp = self.make_copy()
        data = copy.deepcopy(self.read_status(temp))
        data["current_schema_versions"]["project_state"] = "hwm-project-state/v1"
        self.write_status(temp, data)
        self.assertTrue(any("schema versions" in error for error in validate(temp)))


if __name__ == "__main__":
    unittest.main()
