import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control.validate_bootstrap import validate  # noqa: E402


class BootstrapValidationTests(unittest.TestCase):
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
        (root / "BUILD_STATUS.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def status_variant(self, root: Path, *, completed=None, active=None, milestone=None) -> dict:
        data = copy.deepcopy(self.read_status(root))
        if completed is not None:
            data["completed_task_ids"] = completed
        if active is not None:
            data["active_task_ids"] = active
        if milestone is not None:
            data["current_infrastructure_milestone"] = milestone
        return data

    def test_current_repository_passes(self):
        self.assertEqual(validate(ROOT), [])

    def test_completed_i02_baseline_passes(self):
        temp = self.make_copy()
        data = self.status_variant(
            temp,
            completed=["I00", "I01", "I02"],
            active=[],
            milestone="I03",
        )
        self.write_status(temp, data)
        self.assertEqual(validate(temp), [])

    def test_active_i03_task_passes(self):
        temp = self.make_copy()
        data = self.status_variant(
            temp,
            completed=["I00", "I01", "I02"],
            active=["I03-0021"],
            milestone="I03",
        )
        self.write_status(temp, data)
        self.assertEqual(validate(temp), [])

    def test_completed_i03_task_passes(self):
        temp = self.make_copy()
        data = self.status_variant(
            temp,
            completed=["I00", "I01", "I02", "I03-0021"],
            active=[],
            milestone="I03",
        )
        self.write_status(temp, data)
        self.assertEqual(validate(temp), [])

    def test_nonempty_blockers_list_passes(self):
        temp = self.make_copy()
        data = self.read_status(temp)
        data["blockers"] = ["external dependency"]
        self.write_status(temp, data)
        self.assertEqual(validate(temp), [])

    def test_build_status_extra_top_level_key_fails(self):
        temp = self.make_copy()
        data = self.read_status(temp)
        data["history"] = []
        self.write_status(temp, data)
        self.assertTrue(any("top-level keys" in error for error in validate(temp)))

    def test_missing_or_reordered_i00_i01_i02_prefix_fails(self):
        temp = self.make_copy()
        for completed in (["I00", "I02"], ["I01", "I00", "I02"]):
            with self.subTest(completed=completed):
                data = self.status_variant(temp, completed=completed, active=[])
                self.write_status(temp, data)
                self.assertTrue(any("exact I00,I01,I02 prefix" in error for error in validate(temp)))

    def test_invalid_task_id_fails(self):
        temp = self.make_copy()
        data = self.status_variant(temp, active=["I03-21"])
        self.write_status(temp, data)
        self.assertTrue(any("invalid format" in error for error in validate(temp)))

    def test_duplicate_task_id_fails(self):
        temp = self.make_copy()
        data = self.status_variant(temp, active=["I03-0021", "I03-0021"])
        self.write_status(temp, data)
        self.assertTrue(any("unique task ids" in error for error in validate(temp)))

    def test_overlap_active_completed_fails(self):
        temp = self.make_copy()
        data = self.status_variant(
            temp,
            completed=["I00", "I01", "I02", "I03-0021"],
            active=["I03-0021"],
        )
        self.write_status(temp, data)
        self.assertTrue(any("must not overlap" in error for error in validate(temp)))

    def test_active_task_from_other_milestone_fails(self):
        temp = self.make_copy()
        data = self.status_variant(temp, active=["I04-0001"], milestone="I03")
        self.write_status(temp, data)
        self.assertTrue(any("does not belong to current milestone" in error for error in validate(temp)))

    def test_milestone_format_and_floor_are_strict(self):
        temp = self.make_copy()
        for milestone in ("I3", "I02"):
            with self.subTest(milestone=milestone):
                data = self.status_variant(temp, active=[], milestone=milestone)
                self.write_status(temp, data)
                self.assertTrue(any("milestone" in error for error in validate(temp)))

    def test_schema_version_drift_fails(self):
        temp = self.make_copy()
        data = self.read_status(temp)
        data["current_schema_versions"]["job"] = "hwm-job/v999"
        self.write_status(temp, data)
        self.assertTrue(any("schema versions" in error for error in validate(temp)))

    def test_relevant_head_drift_fails(self):
        temp = self.make_copy()
        data = self.read_status(temp)
        data["exact_relevant_heads"]["product_main_reference"] = "0" * 40
        self.write_status(temp, data)
        self.assertTrue(any("product main reference mismatch" in error for error in validate(temp)))

    def test_blockers_must_be_list(self):
        temp = self.make_copy()
        data = self.read_status(temp)
        data["blockers"] = "blocked"
        self.write_status(temp, data)
        self.assertTrue(any("blockers must be a list" in error for error in validate(temp)))

    def test_baseline_byte_change_fails_nonzero(self):
        temp = self.make_copy()
        baseline = temp / "baseline" / "I00_BASELINE.json"
        baseline.write_bytes(baseline.read_bytes() + b"\n")
        proc = subprocess.run(
            [sys.executable, str(temp / "control" / "validate_bootstrap.py"), str(temp)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("SHA-256 mismatch", proc.stderr)

    def test_provenance_drift_fails(self):
        temp = self.make_copy()
        path = temp / "baseline" / "I00_IMPORT_PROVENANCE.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source_path"] = "wrong/path.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(any("provenance source_path mismatch" in error for error in validate(temp)))

    def test_missing_infra_spec_fails(self):
        temp = self.make_copy()
        (temp / "docs" / "INFRA_SPEC.md").unlink()
        self.assertTrue(any("INFRA_SPEC.md" in error for error in validate(temp)))


if __name__ == "__main__":
    unittest.main()
