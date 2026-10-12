import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from verify import TITLE, judge


class EvidenceTests(unittest.TestCase):
    def test_report_requires_both_executed_projects_and_retained_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            image = evidence / "capture.jpg"
            image.write_bytes(b"synthetic detector fixture")
            report = {"suites": [{"specs": [{"title": TITLE, "ok": True, "tests": [
                {"projectName": project, "status": "expected", "results": [{"status": "passed", "attachments": [
                    {"name": "playlist-undo", "path": str(image)}]}]}
                for project in ("desktop", "narrow")]}]}]}
            self.assertEqual(judge(report, evidence), [str(image), str(image)])
            for mutation in ("missing", "skipped", "wrong", "retry", "error"):
                bad = copy.deepcopy(report)
                spec = bad["suites"][0]["specs"][0]
                if mutation == "missing":
                    spec["tests"].pop()
                elif mutation == "skipped":
                    spec["tests"][0]["results"][0]["status"] = "skipped"
                elif mutation == "wrong":
                    spec["title"] = "help screen exits zero"
                elif mutation == "retry":
                    spec["tests"][0]["results"] *= 2
                else:
                    bad["errors"] = [{"message": "server error"}]
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    judge(bad, evidence)
            image.unlink()
            with self.assertRaises(ValueError):
                judge(report, evidence)

    def test_missing_prerequisite_cannot_pass_and_evidence_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("verify.py")),
                                     "--repo", str(root / "absent"), "--evidence-root", str(root / "evidence"),
                                     "--agent", "detector-test"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            path = Path(result.stdout.strip())
            record = json.loads(path.read_text())
            self.assertEqual(record["feature_result"], "blocked")
            self.assertTrue(record["cleanup"]["ok"])
            self.assertTrue(record["cleanup"]["evidence_retained"])


if __name__ == "__main__":
    unittest.main()
