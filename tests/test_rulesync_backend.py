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


if __name__ == "__main__":
    unittest.main()
