import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("rulesync_backend", ROOT / "bin" / "rulesync_backend.py")
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
RULESYNC = Path(os.environ.get("RULESYNC_EXECUTABLE", ROOT / "node_modules" / ".bin" / ("rulesync.cmd" if os.name == "nt" else "rulesync")))
if not RULESYNC.is_file():
    raise RuntimeError("Rulesync 16.39.1 is required; run npm ci or set RULESYNC_EXECUTABLE")


class RulesyncBackendTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project with spaces"
        self.root.mkdir()
        self.src = self.root / "src"
        (self.src / "rules").mkdir(parents=True)
        (self.src / "skills" / "demo").mkdir(parents=True)
        self.rule("a", "Hello")
        self.skill("demo", "Demo")
        self.config = self.root / "config.json"
        self.write_config()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, roots=None):
        self.config.write_text(json.dumps({"version": 1, "input_roots": roots or ["src"], "targets": ["codexcli", "claudecode", "grokcli"], "output_root": "out", "global": False, "features": ["rules", "skills"]}))

    def rule(self, name, text):
        (self.src / "rules" / f"{name}.md").write_text(f"---\ndescription: {name}\n---\n# {text}\n")

    def skill(self, name, text):
        directory = self.src / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {text}\n---\n# {text}\n")
        (directory / "reference.md").write_text(f"support for {text}\n")
        executable = directory / "tool.sh"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)

    def apply(self):
        return backend.apply(self.config, str(RULESYNC))

    def test_actual_generation_update_delete_noop_and_check(self):
        self.assertTrue(self.apply())
        out = self.root / "out"
        self.assertTrue((out / "AGENTS.md").is_file())
        self.assertTrue((out / ".claude/rules/a.md").is_file())
        self.assertTrue((out / ".grok/skills/demo/SKILL.md").is_file())
        self.assertTrue((out / ".agents/skills/demo/reference.md").is_file())
        self.assertEqual((out / ".agents/skills/demo/tool.sh").stat().st_mode & 0o777,
                         (self.src / "skills/demo/tool.sh").stat().st_mode & 0o777)
        self.assertTrue(backend.check(self.config, str(RULESYNC)))
        old_mtime = (out / "AGENTS.md").stat().st_mtime_ns
        self.assertFalse(self.apply())
        self.assertEqual(old_mtime, (out / "AGENTS.md").stat().st_mtime_ns)
        self.rule("a", "Updated")
        self.assertTrue(self.apply())
        self.assertIn("Updated", (out / "AGENTS.md").read_text())
        (self.src / "rules/a.md").unlink()
        self.assertTrue(self.apply())
        self.assertFalse((out / "AGENTS.md").exists())
        self.assertTrue(backend.check(self.config, str(RULESYNC)))

    def test_cursor_project_ownership_update_delete_and_global_skills(self):
        data = json.loads(self.config.read_text())
        data['targets'] = ['codexcli', 'cursor']
        self.config.write_text(json.dumps(data))
        rule = self.src / 'rules/a.md'
        rule.write_text('---\ndescription: Example\ncursor: {alwaysApply: true}\n---\n# Hello\n')
        out = self.root / 'out'
        native = out / '.cursor/rules/a.mdc'
        native.parent.mkdir(parents=True)
        native.write_text('handwritten')
        with self.assertRaisesRegex(backend.BackendError, 'unowned file'):
            self.apply()
        self.assertEqual(native.read_text(), 'handwritten')
        native.unlink()
        self.assertTrue(self.apply())
        self.assertIn('alwaysApply: true', native.read_text())
        self.assertTrue((out / 'AGENTS.md').is_file())
        self.assertTrue((out / '.cursor/skills/demo/reference.md').is_file())
        before = native.stat().st_mtime_ns
        self.assertFalse(self.apply())
        self.assertEqual(before, native.stat().st_mtime_ns)
        self.assertTrue(backend.check(self.config, str(RULESYNC)))
        original = native.read_bytes()
        native.write_text('external edit')
        with self.assertRaisesRegex(backend.BackendError, 'externally modified'):
            self.apply()
        native.write_bytes(original)
        rule.write_text('---\ndescription: Updated\ncursor: {alwaysApply: true}\n---\n# Updated\n')
        self.assertTrue(self.apply())
        self.assertIn('Updated', native.read_text())
        rule.unlink()
        self.assertTrue(self.apply())
        self.assertFalse(native.exists())
        self.assertTrue(backend.check(self.config, str(RULESYNC)))
        data['targets'] = ['cursor']
        data['global'] = True
        data['output_root'] = 'global-out'
        data['features'] = ['skills']
        self.config.write_text(json.dumps(data))
        self.assertTrue(self.apply())
        self.assertTrue((self.root / 'global-out/.cursor/skills/demo/SKILL.md').is_file())
        self.assertFalse((self.root / 'global-out/.cursor/rules').exists())

    def test_rejects_unowned_file_and_same_name_skill(self):
        out = self.root / "out"
        (out / "AGENTS.md").parent.mkdir(parents=True)
        (out / "AGENTS.md").write_text("mine")
        with self.assertRaisesRegex(backend.BackendError, "unowned file"):
            self.apply()
        (out / "AGENTS.md").unlink()
        foreign = out / ".agents/skills/demo"
        foreign.mkdir(parents=True)
        (foreign / "note.txt").write_text("mine")
        with self.assertRaisesRegex(backend.BackendError, "same-name skill"):
            self.apply()

    def test_grok_refuses_existing_claude_policy(self):
        data = json.loads(self.config.read_text())
        data["targets"] = ["grokcli"]
        self.config.write_text(json.dumps(data))
        (self.src / "rules/a.md").write_text("---\ndescription: root\nroot: true\n---\n# Grok\n")
        output = self.root / "out"
        output.mkdir()
        policy = output / "CLAUDE.md"
        policy.write_text("user policy")
        with self.assertRaisesRegex(backend.BackendError, "existing CLAUDE.md"):
            self.apply()
        self.assertEqual(policy.read_text(), "user policy")

    def test_rejects_links_duplicate_sources_and_external_edit(self):
        linked = self.root / "linked"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(self.src)],
                           check=True, capture_output=True)
        else:
            linked.symlink_to(self.src, target_is_directory=True)
        self.write_config(["linked"])
        with self.assertRaisesRegex(backend.BackendError, "symlink"):
            self.apply()
        self.write_config()
        self.assertTrue(self.apply())
        (self.root / "out/AGENTS.md").write_text("changed")
        with self.assertRaisesRegex(backend.BackendError, "externally modified"):
            self.apply()
        second = self.root / "second"
        shutil.copytree(self.src, second)
        self.write_config(["src", "second"])
        with self.assertRaisesRegex(backend.BackendError, "duplicate rule"):
            self.apply()

    def test_output_link_does_not_create_metadata_in_foreign_tree(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        output = self.root / "out"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(output), str(foreign)],
                           check=True, capture_output=True)
        else:
            output.symlink_to(foreign, target_is_directory=True)
        with self.assertRaisesRegex(backend.BackendError, "symlink"):
            self.apply()
        self.assertEqual(list(foreign.iterdir()), [])

    def test_rolls_back_a_commit_failure_and_can_retry(self):
        self.assertTrue(self.apply())
        self.rule("a", "Changed")
        original = backend._write_atomic
        calls = [0]
        def fail_once(*args):
            calls[0] += 1
            if calls[0] == 3:
                raise OSError("injected after a successful replacement")
            return original(*args)
        backend._write_atomic = fail_once
        try:
            with self.assertRaises(OSError):
                self.apply()
        finally:
            backend._write_atomic = original
        self.assertIn("Hello", (self.root / "out/AGENTS.md").read_text())
        self.assertTrue(self.apply())
        self.assertIn("Changed", (self.root / "out/AGENTS.md").read_text())

    def test_conflicting_shared_output_is_explicit(self):
        # Root rules make both Codex and Grok emit AGENTS.md.  The normal
        # shared case is byte-identical and therefore accepted.
        (self.src / "rules/a.md").unlink()
        self.rule("root", "Shared")
        path = self.src / "rules/root.md"
        path.write_text("---\ndescription: root\nroot: true\n---\n# Shared\n")
        with self.assertRaisesRegex(backend.BackendError, "Grok also discovers"):
            self.apply()
        data = json.loads(self.config.read_text())
        data["targets"] = ["codexcli", "grokcli"]
        self.config.write_text(json.dumps(data))
        self.assertTrue(self.apply())
        self.assertIn("Shared", (self.root / "out/AGENTS.md").read_text())

        second = self.root / "conflict"
        (second / "rules").mkdir(parents=True)
        (second / "rules/codex.md").write_text("---\ndescription: codex\nroot: true\ntargets: [codexcli]\n---\n# Codex\n")
        (second / "rules/grok.md").write_text("---\ndescription: grok\nroot: true\ntargets: [grokcli]\n---\n# Grok\n")
        # Use a separate config because roots must not silently overlay.
        self.write_config(["conflict"])
        with self.assertRaisesRegex(backend.BackendError, "shared-output conflict"):
            self.apply()

    def test_global_uses_isolated_home_output_tree(self):
        data = json.loads(self.config.read_text())
        data["global"] = True
        self.config.write_text(json.dumps(data))
        self.assertTrue(self.apply())
        self.assertTrue((self.root / "out/.codex/AGENTS.md").is_file())

    def test_opencode_root_generation_update_delete_noop_check_and_global(self):
        data = json.loads(self.config.read_text())
        data["targets"] = ["opencode"]
        self.config.write_text(json.dumps(data))
        (self.src / "rules/a.md").write_text("---\ndescription: root\nroot: true\n---\n# OpenCode\n")
        self.assertTrue(self.apply())
        out = self.root / "out"
        self.assertTrue((out / "AGENTS.md").is_file())
        self.assertTrue((out / ".opencode/skills/demo/SKILL.md").is_file())
        self.assertTrue(backend.check(self.config, str(RULESYNC)))
        mtime = (out / "AGENTS.md").stat().st_mtime_ns
        self.assertFalse(self.apply())
        self.assertEqual(mtime, (out / "AGENTS.md").stat().st_mtime_ns)
        self.rule("a", "Updated OpenCode")
        (self.src / "rules/a.md").write_text("---\ndescription: root\nroot: true\n---\n# Updated OpenCode\n")
        self.assertTrue(self.apply())
        self.assertIn("Updated OpenCode", (out / "AGENTS.md").read_text())
        (self.src / "rules/a.md").unlink()
        self.assertTrue(self.apply())
        self.assertFalse((out / "AGENTS.md").exists())
        self.assertTrue(backend.check(self.config, str(RULESYNC)))
        data["global"] = True
        data["output_root"] = "global-out"
        self.config.write_text(json.dumps(data))
        out = self.root / "global-out"
        self.rule("global", "Global OpenCode")
        (self.src / "rules/global.md").write_text("---\ndescription: global\nroot: true\n---\n# Global OpenCode\n")
        self.assertTrue(self.apply())
        self.assertTrue((out / ".config/opencode/AGENTS.md").is_file())
        self.assertTrue((out / ".config/opencode/skills/demo/SKILL.md").is_file())

    def test_opencode_rejects_nonroot_settings_and_memories_before_output_write(self):
        data = json.loads(self.config.read_text())
        data["targets"] = ["opencode"]
        self.config.write_text(json.dumps(data))
        out = self.root / "out"
        out.mkdir()
        sentinel = out / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaisesRegex(backend.BackendError, "unsupported path.*opencode"):
            self.apply()
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertFalse((out / backend.MANIFEST).exists())

    def test_opencode_allowlist_is_root_only_and_has_no_settings_or_memory_prefixes(self):
        self.assertTrue(backend._allowed("opencode", "AGENTS.md"))
        self.assertTrue(backend._allowed("opencode", ".opencode/skills/demo/SKILL.md"))
        self.assertTrue(backend._allowed("opencode", ".config/opencode/AGENTS.md", True))
        self.assertTrue(backend._allowed("opencode", ".config/opencode/skills/demo/SKILL.md", True))
        for rel in ("opencode.json", "opencode.jsonc", ".opencode/memories/a.md",
                    ".opencode/skills-copy/a.md", ".config/opencode.jsonc",
                    ".config/opencode/memories/a.md", ".config/opencode/skills-copy/a.md"):
            self.assertFalse(backend._allowed("opencode", rel, rel.startswith(".config/")))

    def test_opencode_unowned_external_edit_and_junction_are_refused(self):
        data = json.loads(self.config.read_text())
        data["targets"] = ["opencode"]
        self.config.write_text(json.dumps(data))
        (self.src / "rules/a.md").write_text("---\ndescription: root\nroot: true\n---\n# OpenCode\n")
        out = self.root / "out"
        out.mkdir()
        (out / "AGENTS.md").write_text("mine")
        with self.assertRaisesRegex(backend.BackendError, "unowned file"):
            self.apply()
        (out / "AGENTS.md").unlink()
        self.assertTrue(self.apply())
        (out / "AGENTS.md").write_text("edited")
        with self.assertRaisesRegex(backend.BackendError, "externally modified"):
            self.apply()
        foreign = self.root / "foreign"
        foreign.mkdir()
        linked = self.root / "linked-out"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(foreign)], check=True, capture_output=True)
        else:
            linked.symlink_to(foreign, target_is_directory=True)
        data["output_root"] = "linked-out"
        self.config.write_text(json.dumps(data))
        with self.assertRaisesRegex(backend.BackendError, "symlink or junction"):
            self.apply()

    def test_hard_exit_transaction_recovers_before_retry(self):
        self.assertTrue(self.apply())
        (self.src / "rules/a.md").unlink()  # stale owned deletion
        self.rule("b", "After crash")       # then a replacement write
        self.skill("new", "New skill")      # creates previously absent output skill dirs
        script = """
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('backend', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
old = m._write_atomic; count = [0]
def crash(*args):
    old(*args); count[0] += 1
    if count[0] == 2: os._exit(23)
m._write_atomic = crash
m.apply(sys.argv[2], sys.argv[3])
"""
        child_env = os.environ.copy()
        result = subprocess.run([sys.executable, "-c", script, str(ROOT / "bin/rulesync_backend.py"), str(self.config), str(RULESYNC)], env=child_env)
        self.assertEqual(result.returncode, 23)
        with self.assertRaisesRegex(backend.BackendError, "pending Rulesync transaction"):
            backend.check(self.config, str(RULESYNC))
        self.assertTrue(self.apply())
        self.assertIn("After crash", (self.root / "out/AGENTS.md").read_text())
        self.assertTrue((self.root / "out/.agents/skills/new/SKILL.md").is_file())


    def handover_plan(self, files, backup=None, output=None, desired=None):
        output = output or (self.root / "out")
        backup = backup or (self.root / "handover-backup")
        if desired is None:
            desired = backend._generate(backend._load_config(self.config), str(RULESYNC))
        entries = []
        for path in files:
            entries.append({"path": path.relative_to(output).as_posix(),
                            "sha256": backend._digest(path.read_bytes()),
                            "mode": path.stat().st_mode & 0o777})
        plan = self.root / "handover-plan.json"
        plan.write_text(json.dumps({"version": 1, "output_root": str(output),
                                    "files": entries,
                                    "evidence": "old writer stopped; handwritten source preserved",
                                    "backup_root": str(backup),
                                    "desired_sha256": backend._digest(backend._manifest_bytes(desired))}))
        return plan, backup

    def test_handover_real_generation_preserves_before_state_and_then_checks(self):
        config = backend._load_config(self.config)
        desired = backend._generate(config, str(RULESYNC))
        out = self.root / "out"
        legacy = []
        for rel, (data, mode) in desired.items():
            path = out / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"legacy " + data)
            path.chmod(0o644)
            legacy.append(path)
        plan, backup = self.handover_plan(legacy)
        self.assertTrue(backend.handover(self.config, plan, str(RULESYNC)))
        self.assertTrue((backup / "before/AGENTS.md").read_bytes().startswith(b"legacy "))
        if os.name != "nt":
            self.assertEqual((backup / "before/AGENTS.md").stat().st_mode & 0o777, 0o644)
        self.assertEqual((backup / "plan.json").read_bytes(), plan.read_bytes())
        self.assertTrue((backup / "config.json").is_file())
        self.assertTrue((backup / "desired-ownership.json").is_file())
        self.assertTrue(backend.check(self.config, str(RULESYNC)))
        self.assertFalse(backend.apply(self.config, str(RULESYNC)))
        with self.assertRaisesRegex(backend.BackendError, "existing ownership manifest"):
            backend.handover(self.config, plan, str(RULESYNC))

    def test_handover_allows_reviewed_stale_claude_and_rejects_bad_or_unreviewed_state(self):
        out = self.root / "out"
        out.mkdir()
        agents, claude = out / "AGENTS.md", out / "CLAUDE.md"
        agents.write_text("old agents")
        agents.chmod(0o644)
        claude.write_text("old claude")
        claude.chmod(0o600)
        plan, backup = self.handover_plan([agents, claude], desired={"AGENTS.md": (b"new agents", 0o755)})
        original = backend._generate
        backend._generate = lambda config, executable: {"AGENTS.md": (b"new agents", 0o755)}
        try:
            self.assertTrue(backend.handover(self.config, plan, str(RULESYNC)))
        finally:
            backend._generate = original
        self.assertEqual(agents.read_bytes(), b"new agents")
        if os.name != "nt":
            self.assertEqual(agents.stat().st_mode & 0o777, 0o755)
        self.assertFalse(claude.exists())
        self.assertEqual((backup / "before/CLAUDE.md").read_text(), "old claude")

        second = self.root / "second-out"
        second.mkdir()
        foreign = second / "AGENTS.md"
        foreign.write_text("foreign")
        bad_plan, _ = self.handover_plan([], self.root / "other-backup", second, {"AGENTS.md": (b"new", 0o600)})
        data = json.loads(self.config.read_text()); data["output_root"] = "second-out"; self.config.write_text(json.dumps(data))
        backend._generate = lambda config, executable: {"AGENTS.md": (b"new", 0o600)}
        try:
            with self.assertRaisesRegex(backend.BackendError, "unowned file"):
                backend.handover(self.config, bad_plan, str(RULESYNC))
        finally:
            backend._generate = original

    def test_handover_preserves_an_edit_that_races_backup_completion(self):
        out = self.root / "out"
        out.mkdir()
        agents = out / "AGENTS.md"
        agents.write_text("old")
        plan, backup = self.handover_plan([agents], desired={"AGENTS.md": (b"new", 0o600)})
        original_generate, original_backup = backend._generate, backend._write_handover_backup
        backend._generate = lambda config, executable: {"AGENTS.md": (b"new", 0o600)}
        def edit_after_backup(*args):
            original_backup(*args)
            agents.write_text("racing user edit")
        backend._write_handover_backup = edit_after_backup
        try:
            with self.assertRaisesRegex(backend.BackendError, "externally modified"):
                backend.handover(self.config, plan, str(RULESYNC))
        finally:
            backend._generate, backend._write_handover_backup = original_generate, original_backup
        self.assertEqual(agents.read_text(), "racing user edit")
        self.assertTrue((backup / "before/AGENTS.md").is_file())

    def test_handover_rejects_wrong_root_metadata_symlink_and_backup_collision(self):
        out = self.root / "out"
        out.mkdir()
        agents = out / "AGENTS.md"
        agents.write_text("old")
        plan, backup = self.handover_plan([agents])
        data = json.loads(plan.read_text())
        data["output_root"] = str(self.root / "wrong")
        plan.write_text(json.dumps(data))
        with self.assertRaisesRegex(backend.BackendError, "output_root"):
            backend.handover(self.config, plan, str(RULESYNC))
        data["output_root"] = str(out)
        data["files"][0]["path"] = backend.MANIFEST
        plan.write_text(json.dumps(data))
        with self.assertRaisesRegex(backend.BackendError, "invalid handover plan"):
            backend.handover(self.config, plan, str(RULESYNC))
        data["files"][0]["path"] = "AGENTS.md"
        data["files"][0]["sha256"] = backend._digest(agents.read_bytes())
        data["files"][0]["mode"] = agents.stat().st_mode & 0o777
        plan.write_text(json.dumps(data))
        if os.name != "nt":
            linked = self.root / "linked-backup"
            linked.symlink_to(self.root, target_is_directory=True)
            data["backup_root"] = str(linked)
            plan.write_text(json.dumps(data))
            with self.assertRaisesRegex(backend.BackendError, "symlink"):
                backend.handover(self.config, plan, str(RULESYNC))
        data["backup_root"] = str(backup)
        plan.write_text(json.dumps(data))
        if os.name != "nt":
            metadata = out / backend.MANIFEST
            metadata.symlink_to(self.root / "missing-manifest")
            with self.assertRaisesRegex(backend.BackendError, "symlink"):
                backend.handover(self.config, plan, str(RULESYNC))
            metadata.unlink()
        backup.mkdir()
        with self.assertRaisesRegex(backend.BackendError, "backup already exists"):
            backend.handover(self.config, plan, str(RULESYNC))


if __name__ == "__main__":
    unittest.main()
