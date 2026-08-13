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

    def test_current_repository_passes(self):
        self.assertEqual(validate(ROOT), [])

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

    def test_build_status_extra_history_key_fails(self):
        temp = self.make_copy()
        path = temp / "BUILD_STATUS.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["history"] = []
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(any("top-level keys" in e for e in validate(temp)))

    def test_missing_infra_spec_fails(self):
        temp = self.make_copy()
        (temp / "docs" / "INFRA_SPEC.md").unlink()
        self.assertTrue(any("INFRA_SPEC.md" in e for e in validate(temp)))


if __name__ == "__main__":
    unittest.main()
