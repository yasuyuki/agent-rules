"""Regression checks for the disposable public placement verification helper."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills" / "verify-agent-rules" / "scripts" / "verify.py"

spec = importlib.util.spec_from_file_location("verification_skill", HELPER)
verify = importlib.util.module_from_spec(spec)
assert spec.loader is not None
previous_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(verify)
finally:
    sys.dont_write_bytecode = previous_bytecode


class VerificationSkillTests(unittest.TestCase):
    def run_helper(self, repo=ROOT, *, doctor_only=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        result, evidence = verify.run(repo, temporary.name, doctor_only)
        self.assertEqual(evidence.parent, Path(temporary.name))
        self.assertTrue((evidence / "result.json").is_file())
        self.assertEqual(json.loads((evidence / "result.json").read_text(encoding="utf-8")), result)
        return result, evidence

    def assert_evidence_survives_cleanup(self, result, evidence):
        self.assertTrue(result["cleanup"]["ok"])
        scratch = result["cleanup"]["scratch"]
        if scratch is not None:
            self.assertFalse(Path(scratch).exists())
        self.assertTrue(result["evidence_retained"])
        self.assertTrue((evidence / "result.json").is_file())
        for artifact in result["artifacts"]:
            self.assertTrue((evidence / artifact).exists(), artifact)

    def test_real_public_cli_passes_and_preserves_handwritten_collision(self):
        result, evidence = self.run_helper()

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["feature_status"], "pass")
        self.assertTrue(all(item["ok"] for item in result["assertions"]))
        names = {item["name"] for item in result["assertions"]}
        self.assertIn("updated .codex/skills/hand-written/extra.txt", names)
        self.assertIn("collision preserves output tree", names)
        self.assert_evidence_survives_cleanup(result, evidence)

    def test_zero_exit_with_wrong_persisted_output_fails_and_keeps_evidence(self):
        original_command = verify.command
        changed = False

        def corrupt_first_apply(argv, cwd):
            nonlocal changed
            result = original_command(argv, cwd)
            if not changed and len(argv) > 2 and argv[2] == "apply":
                agents = Path(cwd) / "project" / "AGENTS.md"
                agents.write_text(
                    agents.read_text(encoding="utf-8").replace(verify.BLUE, "wrong persisted value"),
                    encoding="utf-8",
                )
                changed = True
            return result

        with mock.patch.object(verify, "command", side_effect=corrupt_first_apply):
            result, evidence = self.run_helper()

        self.assertTrue(changed)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["feature_status"], "fail")
        self.assertIn("AssertionError: initial section content", result["error"])
        self.assert_evidence_survives_cleanup(result, evidence)
        self.assertIn("initial", result["artifacts"])

    def test_missing_public_source_is_blocked(self):
        with tempfile.TemporaryDirectory() as missing:
            result, evidence = self.run_helper(Path(missing))

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["feature_status"], "not-run")
        self.assertIn("Missing public input", result["error"])
        self.assertEqual(result["commands"], [])
        self.assert_evidence_survives_cleanup(result, evidence)

    def test_doctor_only_is_not_run_and_never_passes(self):
        result, evidence = self.run_helper(doctor_only=True)

        self.assertEqual(result["status"], "not-run")
        self.assertEqual(result["feature_status"], "not-run")
        self.assertEqual(result["commands"], [])
        self.assertIn("target", result)
        self.assert_evidence_survives_cleanup(result, evidence)

    def test_linked_catalog_root_is_blocked_before_reading_outside(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "bin").mkdir()
            (root / "bin/place.py").write_text("", encoding="utf-8")
            (root / "placement.json").write_text("{}", encoding="utf-8")
            (root / "rules").mkdir()
            outside = root / "outside"
            outside.mkdir()
            try:
                (root / "skills").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest("Symlink creation unavailable: " + str(exc))
            with mock.patch.object(verify, "command") as command:
                result, evidence = self.run_helper(root)
            command.assert_not_called()
            self.assertEqual(result["status"], "blocked")
            self.assertIn("Linked public input", result["error"])
            self.assert_evidence_survives_cleanup(result, evidence)


if __name__ == "__main__":
    unittest.main()
