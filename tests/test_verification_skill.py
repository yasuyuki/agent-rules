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
    def run_helper(self, repo=ROOT, *, doctor_only=False, environment_repo=None, agent="unknown"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        result, evidence = verify.run(repo, temporary.name, doctor_only, environment_repo, agent)
        self.assertEqual(evidence.parent, Path(temporary.name).resolve())
        self.assertTrue((evidence / "result.json").is_file())
        self.assertEqual(json.loads((evidence / "result.json").read_text(encoding="utf-8")), result)
        return result, evidence

    def environment_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        rule = root / "examples/single-environment/rules/example-private.rule.md"
        rule.parent.mkdir(parents=True)
        rule.write_text(
            "---\nid: example-private\ntitle: Example private rule\nsummary: fixture\n---\n"
            "This is a synthetic example of a private rule that lives outside the\n"
            "agent-rules canonical source, in the environment's own `rule_sources`. Real\n"
            "private rules go in a directory like this one, referenced by an env.json\n"
            "config's `rule_sources`, and are projected alongside the canonical rules\n"
            "from `agent_rules_root`.\n", encoding="utf-8")
        subprocess = verify.subprocess
        for argv in (["git", "init"], ["git", "add", "."],
                     ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"]):
            completed = subprocess.run(argv, cwd=root, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
        return root

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

    def test_dependency_profile_composes_and_mirrors(self):
        result, evidence = self.run_helper(environment_repo=self.environment_fixture(), agent="test-agent")

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["agent"], "test-agent")
        self.assertEqual(result["feature_states"], {"placement": "pass", "composition": "pass", "mirror": "pass"})
        self.assertIn("environment_dependency", result["target"])
        self.assertTrue(all(item["ok"] for item in result["assertions"]))
        self.assert_evidence_survives_cleanup(result, evidence)

    def test_dependency_mirror_zero_exit_with_wrong_bytes_fails(self):
        original_command = verify.command
        changed = False

        def corrupt_mirror(argv, cwd):
            nonlocal changed
            result = original_command(argv, cwd)
            if not changed and len(argv) > 2 and argv[2] == "mirror" and "--check" not in argv:
                path = Path(cwd) / "mirror/skills/verify-agent-rules/SKILL.md"
                path.write_text("wrong mirror bytes\n", encoding="utf-8")
                changed = True
            return result

        with mock.patch.object(verify, "command", side_effect=corrupt_mirror):
            result, evidence = self.run_helper(environment_repo=self.environment_fixture())

        self.assertTrue(changed)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["feature_states"]["placement"], "pass")
        self.assertEqual(result["feature_states"]["composition"], "pass")
        self.assertEqual(result["feature_states"]["mirror"], "fail")
        self.assertIn("mirror initial non-vendored bytes and execute bits", result["error"])
        self.assertIn("mirror-initial", result["artifacts"])
        self.assertTrue((evidence / "mirror-initial/skills/verify-agent-rules/SKILL.md").is_file())
        self.assert_evidence_survives_cleanup(result, evidence)

    def test_missing_dependency_is_blocked_before_drive(self):
        root = self.environment_fixture()
        (root / "examples/single-environment/rules/example-private.rule.md").unlink()
        result, evidence = self.run_helper(environment_repo=root)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["commands"], [])
        self.assertIn("Missing environment dependency input", result["error"])
        self.assert_evidence_survives_cleanup(result, evidence)

    def test_linked_dependency_path_is_rejected_before_reads(self):
        root = self.environment_fixture()
        rule_dir = root / "examples/single-environment/rules"
        outside = root / "outside"
        outside.mkdir()
        try:
            rule_dir.rename(outside / "rules")
            rule_dir.symlink_to(outside / "rules", target_is_directory=True)
        except OSError as exc:
            self.skipTest("Symlink creation unavailable: " + str(exc))
        result, evidence = self.run_helper(environment_repo=root)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["commands"], [])
        self.assertIn("Linked dependency input", result["error"])
        self.assert_evidence_survives_cleanup(result, evidence)

    def test_dependency_uses_only_selected_rule_not_sibling_link(self):
        root = self.environment_fixture()
        sibling = root / "examples/single-environment/rules/unselected.rule.md"
        try:
            sibling.symlink_to(root / "missing-private-source.rule.md")
        except OSError as exc:
            self.skipTest("Symlink creation unavailable: " + str(exc))
        result, evidence = self.run_helper(environment_repo=root)
        self.assertEqual(result["status"], "pass")
        self.assertTrue((evidence / "dependency-example-private.rule.md").is_file())
        self.assertFalse((evidence / "unselected.rule.md").exists())
        self.assert_evidence_survives_cleanup(result, evidence)


if __name__ == "__main__":
    unittest.main()
