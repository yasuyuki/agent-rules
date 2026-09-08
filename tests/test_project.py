"""End-to-end coverage for the installed project-only CLI.

These tests deliberately use subprocesses and ``-m agent_rules_manager.project``:
the checkout is not added to ``PYTHONPATH`` and no implementation modules are
imported here.  Run this file with an interpreter where the wheel is installed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


MODULE = "agent_rules_manager.project"


class ProjectCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "third party project"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, cwd=None, input=None, env=None):
        merged = os.environ.copy()
        merged.pop("PYTHONPATH", None)
        if env:
            merged.update(env)
        return subprocess.run(
            [sys.executable, "-m", MODULE, *args],
            cwd=cwd or self.root,
            input=input,
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=merged,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def write_config(self, *, tools=("codex",), rules=(".agent-rules/rules",), skills=(".agent-rules/skills",), root=None):
        root = root or self.root
        config = root / ".agent-rules" / "config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        for value in (*rules, *skills):
            (root / value).mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"version": 1, "tools": list(tools), "rules": list(rules), "skills": list(skills)}), encoding="utf-8")
        return config

    def rule(self, rule_id="project-rule", *, tools=None, root=None):
        root = root or self.root
        suffix = "\ntools: [%s]" % ", ".join(tools) if tools else ""
        path = root / ".agent-rules" / "rules" / (rule_id + ".rule.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nid: %s\ntitle: Project rule\nsummary: A project rule%s\n---\nOnly this project's rule.\n" % (rule_id, suffix), encoding="utf-8")
        return path

    def skill(self, skill_id="project-skill", root=None):
        root = root or self.root
        path = root / ".agent-rules" / "skills" / skill_id / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nname: %s\ndescription: A project skill\n---\nUse this skill.\n" % skill_id, encoding="utf-8")
        return path

    def test_interactive_init_defaults_and_rerun_does_not_overwrite(self):
        result = self.run_cli("init", input="codex claude\n\n\n")
        self.assert_ok(result)
        config = self.root / ".agent-rules" / "config.json"
        self.assertEqual(json.loads(config.read_text(encoding="utf-8")), {
            "version": 1, "tools": ["codex", "claude"],
            "rules": [".agent-rules/rules"], "skills": [".agent-rules/skills"],
        })
        before = config.read_bytes()
        rerun = self.run_cli("init", "--non-interactive", "--tools", "codex")
        self.assertNotEqual(rerun.returncode, 0)
        self.assertIn("config already exists", rerun.stderr)
        self.assertEqual(config.read_bytes(), before)

    def test_interactive_cancel_leaves_no_partial_files(self):
        result = self.run_cli("init", input="codex\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cancelled.", result.stderr)
        self.assertFalse((self.root / ".agent-rules").exists())

    def test_apply_check_idempotence_and_drift_for_own_sources(self):
        self.write_config(tools=("codex", "claude", "cursor-agent"))
        self.rule(tools=("codex", "cursor-agent"))
        self.skill()
        apply = self.run_cli("apply")
        self.assert_ok(apply)
        agents = self.root / "AGENTS.md"
        codex_skill = self.root / ".codex" / "skills" / "project-skill"
        claude_skill = self.root / ".claude" / "skills" / "project-skill"
        cursor_rule = self.root / ".cursor" / "rules" / "agent-rules--project-rule.mdc"
        self.assertIn("Only this project's rule.", agents.read_text(encoding="utf-8"))
        self.assertFalse((self.root / ".claude" / "rules" / "agent-rules--project-rule.md").exists())
        self.assertEqual(
            re.findall(r"<!-- agent-rules:(begin|end) ([a-z0-9-]+) -->", agents.read_text(encoding="utf-8")),
            [("begin", "project-rule"), ("end", "project-rule")],
        )
        self.assertNotIn("git-commit-policy", agents.read_text(encoding="utf-8"))
        self.assertTrue(cursor_rule.is_file())
        self.assertTrue(cursor_rule.read_text(encoding="utf-8").startswith(
            "---\ndescription: A project rule\nalwaysApply: true\n---\n\n# Project rule\n"
        ))
        self.assertTrue((codex_skill / "SKILL.md").is_file())
        self.assertTrue((claude_skill / ".agent-skills").is_file())
        self.assertFalse((self.root / ".agents").exists())
        first = {path: path.read_bytes() for path in (agents, codex_skill / "SKILL.md", codex_skill / ".agent-skills", claude_skill / "SKILL.md")}
        self.assert_ok(self.run_cli("apply"))
        self.assertEqual({path: path.read_bytes() for path in first}, first)
        agents.write_text(agents.read_text(encoding="utf-8") + "unmanaged trailing text\n", encoding="utf-8")
        self.assert_ok(self.run_cli("check"))
        agents.write_text(agents.read_text(encoding="utf-8").replace("Only this project's rule.", "managed drift"), encoding="utf-8")
        check = self.run_cli("check")
        self.assertNotEqual(check.returncode, 0)
        self.assertIn("differs from canonical", check.stderr)
        self.assert_ok(self.run_cli("apply"))
        self.assert_ok(self.run_cli("check"))
        self.assertIn("unmanaged trailing text", agents.read_text(encoding="utf-8"))

    def test_deleting_final_sources_reconciles_stale_rule_and_skill(self):
        self.write_config()
        self.rule()
        self.skill()
        agents = self.root / "AGENTS.md"
        agents.write_text("# Local instructions\n\nKeep this.\n", encoding="utf-8")
        self.assert_ok(self.run_cli("apply"))
        (self.root / ".agent-rules" / "rules" / "project-rule.rule.md").unlink()
        (self.root / ".agent-rules" / "skills" / "project-skill" / "SKILL.md").unlink()
        (self.root / ".agent-rules" / "skills" / "project-skill").rmdir()
        check = self.run_cli("check")
        self.assertNotEqual(check.returncode, 0)
        self.assertIn("unexpected section", check.stderr)
        self.assertIn("unexpected managed skill", check.stderr)
        self.assert_ok(self.run_cli("apply"))
        text = agents.read_text(encoding="utf-8")
        self.assertIn("Keep this.", text)
        self.assertNotIn("agent-rules:begin", text)
        self.assertFalse((self.root / ".codex" / "skills" / "project-skill").exists())
        self.assert_ok(self.run_cli("check"))

    def test_empty_kinds_leave_existing_content_unmanaged(self):
        config = self.write_config()
        self.rule()
        self.skill()
        self.assert_ok(self.run_cli("apply"))
        agents = self.root / "AGENTS.md"
        skill = self.root / ".codex" / "skills" / "project-skill" / "SKILL.md"
        agents_before, skill_before = agents.read_bytes(), skill.read_bytes()
        config.write_text(json.dumps({"version": 1, "tools": ["codex"], "rules": [], "skills": [".agent-rules/skills"]}), encoding="utf-8")
        self.assert_ok(self.run_cli("apply"))
        self.assertEqual(agents.read_bytes(), agents_before)
        config.write_text(json.dumps({"version": 1, "tools": ["codex"], "rules": [".agent-rules/rules"], "skills": []}), encoding="utf-8")
        self.assert_ok(self.run_cli("apply"))
        self.assertEqual(skill.read_bytes(), skill_before)

    def test_unmanaged_same_name_skill_is_refused(self):
        self.write_config()
        self.skill()
        target = self.root / ".codex" / "skills" / "project-skill"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("someone else's skill", encoding="utf-8")
        result = self.run_cli("apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite unmanaged skill", result.stderr)
        self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "someone else's skill")

    def test_windows_skill_newlines_are_preserved(self):
        self.write_config(rules=())
        source = self.skill()
        content = source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        source.write_bytes(content)
        self.assert_ok(self.run_cli("apply"))
        target = self.root / ".codex" / "skills" / "project-skill" / "SKILL.md"
        self.assertEqual(target.read_bytes(), content)
        self.assert_ok(self.run_cli("check"))

    def test_invalid_config_sources_and_duplicate_ids_fail(self):
        cases = []
        config = self.root / ".agent-rules" / "config.json"
        config.parent.mkdir()
        config.write_text("{", encoding="utf-8")
        cases.append((self.run_cli("check"), "FAIL:"))
        config.write_text(json.dumps({"version": 2, "tools": ["codex"], "rules": [], "skills": []}), encoding="utf-8")
        cases.append((self.run_cli("check"), "unsupported config version"))
        config.write_text(json.dumps({"version": 1, "tools": ["codex"], "rules": ["missing"], "skills": []}), encoding="utf-8")
        cases.append((self.run_cli("check"), "source directory is missing"))
        self.write_config(rules=(".agent-rules/rules", ".agent-rules/more-rules"), skills=(".agent-rules/skills",))
        self.rule("same")
        other = self.root / ".agent-rules" / "more-rules" / "same.rule.md"
        other.write_text((self.root / ".agent-rules" / "rules" / "same.rule.md").read_text(encoding="utf-8"), encoding="utf-8")
        cases.append((self.run_cli("check"), "duplicate rule id"))
        self.write_config(rules=(".",), skills=())
        cases.append((self.run_cli("check"), "source overlaps a managed destination"))
        for result, message in cases:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)

    def test_opencode_notes_unsupported_skills(self):
        self.write_config(tools=("opencode",))
        self.rule()
        self.skill()
        result = self.run_cli("apply")
        self.assert_ok(result)
        self.assertIn("opencode does not support skills placement", result.stdout)
        self.assertTrue((self.root / "AGENTS.md").is_file())
        self.assertTrue((self.root / ".agents" / "rules" / "agent-rules--project-rule.md").is_file())
        self.assertFalse((self.root / ".agents" / "skills").exists())

    def test_external_config_with_spaces_and_japanese_path(self):
        external = Path(self.temp.name) / "外部 project space"
        external.mkdir()
        config = self.write_config(root=external)
        self.rule(root=external)
        self.skill(root=external)
        elsewhere = Path(self.temp.name) / "elsewhere"
        elsewhere.mkdir()
        self.assert_ok(self.run_cli("apply", "--config", str(config), cwd=elsewhere))
        self.assertTrue((external / "AGENTS.md").is_file())
        self.assertTrue((external / ".codex" / "skills" / "project-skill" / "SKILL.md").is_file())

    def test_apply_rolls_back_forced_failure_and_malformed_markers(self):
        self.write_config(tools=("codex", "claude"))
        rule = self.rule()
        self.assert_ok(self.run_cli("apply"))
        agents = self.root / "AGENTS.md"
        claude = self.root / ".claude" / "rules" / "agent-rules--project-rule.md"
        before = agents.read_bytes()
        claude_before = claude.read_bytes()
        rule.write_text(rule.read_text(encoding="utf-8").replace("Only this project's rule.", "Changed source."), encoding="utf-8")
        forced = self.run_cli("apply", env={"PLACE_FORCE_POSTCHECK_FAILURE": "1"})
        self.assertNotEqual(forced.returncode, 0)
        self.assertEqual(agents.read_bytes(), before)
        self.assertEqual(claude.read_bytes(), claude_before)
        claude.write_text("local Claude drift\n", encoding="utf-8")
        claude_malformed = claude.read_bytes()
        agents.write_text("local\n<!-- agent-rules:begin broken -->\n", encoding="utf-8")
        malformed = agents.read_bytes()
        result = self.run_cli("apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed agent-rules markers", result.stderr)
        self.assertEqual(agents.read_bytes(), malformed)
        self.assertEqual(claude.read_bytes(), claude_malformed)

    @unittest.skipIf(os.name == "nt", "symlink creation may require Windows privileges")
    def test_symlink_source_boundary_is_rejected(self):
        config = self.write_config()
        rules = config.parent / "rules"
        rules.rmdir()
        outside = Path(self.temp.name) / "outside-rules"
        outside.mkdir()
        rules.symlink_to(outside, target_is_directory=True)
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("affected target is a link", result.stderr)


if __name__ == "__main__":
    unittest.main()
