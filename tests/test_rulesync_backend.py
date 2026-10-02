import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_antigravity_project_shares_codex_output_and_global_uses_config_rules(self):
        data = json.loads(self.config.read_text())
        data['targets'] = ['codexcli', 'antigravity-cli']
        self.config.write_text(json.dumps(data))
        (self.src / 'rules/a.md').write_text('---\nroot: false\ntargets: ["codexcli"]\n---\n# Hello\n')
        self.assertTrue(self.apply())
        out = self.root / 'out'
        self.assertIn('Hello', (out / 'AGENTS.md').read_text())
        self.assertTrue((out / '.agents/skills/demo/SKILL.md').is_file())
        self.assertFalse((out / '.gemini').exists())
        self.assertTrue(backend.check(self.config, str(RULESYNC)))
        (self.src / 'rules/a.md').write_text('---\nroot: true\ntargets: ["antigravity-cli"]\n---\n# Global\n')
        (self.src / 'rules/b.md').write_text('---\nroot: true\ntargets: ["codexcli"]\n---\n# Codex only\n')
        (self.src / 'rules/c.md').write_text('---\nroot: true\ntargets:\n  - codexcli\n  - antigravity-cli\n---\n# Listed\n')
        data.update(targets=['antigravity-cli'], output_root='global-out', **{'global': True})
        self.config.write_text(json.dumps(data))
        home = self.root / 'global-out'
        # A manifest from the single-file layout owns GEMINI.md; apply retires it.
        gemini = home / '.gemini/GEMINI.md'
        gemini.parent.mkdir(parents=True)
        gemini.write_text('# Old\n')
        (home / backend.MANIFEST).write_text(json.dumps({'version': 1, 'files': [{
            'path': '.gemini/GEMINI.md', 'sha256': backend._digest(gemini.read_bytes()),
            'mode': gemini.stat().st_mode & 0o777}]}))
        self.assertTrue(self.apply())
        self.assertFalse(gemini.exists())
        self.assertEqual((home / '.gemini/config/rules/a.md').read_text(), '---\ntrigger: always_on\n---\n# Global\n')
        self.assertIn('# Listed', (home / '.gemini/config/rules/c.md').read_text())
        self.assertFalse((home / '.gemini/config/rules/b.md').exists())
        self.assertTrue((home / '.gemini/antigravity-cli/skills/demo/reference.md').is_file())
        self.assertFalse(self.apply())
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


    def test_retired_skill_actual_generation_can_readd(self):
        self.skill("generic", "Retained")
        support = self.src / "skills/demo/references/deep/example.md"
        support.parent.mkdir(parents=True)
        support.write_text("nested support")
        self.assertTrue(self.apply())
        out = self.root / "out"
        native = out / ".agents/skills"
        (native / "unrelated").mkdir()
        saved = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file() and "/demo/" in p.as_posix()}
        shutil.rmtree(self.src / "skills/demo")
        self.assertTrue(self.apply())
        for prefix in (".agents", ".claude", ".grok"):
            self.assertTrue((out / prefix / "skills/demo").is_dir())
            self.assertFalse(any(p.is_file() for p in (out / prefix / "skills/demo").rglob("*")))
            self.assertTrue((out / prefix / "skills/generic/SKILL.md").is_file())
        self.assertTrue((native / "unrelated").is_dir())
        self.skill("demo", "Demo")
        support.parent.mkdir(parents=True)
        support.write_text("nested support")
        self.assertTrue(self.apply())
        for rel, data in saved.items():
            self.assertEqual((out / rel).read_bytes(), data)
        self.assertEqual((native / "demo/tool.sh").stat().st_mode & 0o777,
                         (self.src / "skills/demo/tool.sh").stat().st_mode & 0o777)
        self.assertTrue(backend.check(self.config, str(RULESYNC)))

    def absent_retired_skill_fixture(self):
        data = json.loads(self.config.read_text())
        data["targets"] = ["codexcli"]
        self.config.write_text(json.dumps(data))
        agents = self.src / "skills/demo/agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "support.md").write_text("Demo support\n")
        self.assertTrue(self.apply())
        shutil.rmtree(self.src / "skills/demo")
        self.assertTrue(self.apply())
        out = self.root / "out"
        root = out / ".agents/skills/demo"
        manifest = out / backend.MANIFEST
        self.assertEqual({entry["path"] for entry in json.loads(manifest.read_text())["skill_directories"][0]["directories"]},
                         {".agents/skills/demo", ".agents/skills/demo/agents"})
        shutil.rmtree(root)
        return out, root, manifest

    def test_apply_retires_absent_deselected_tree_and_check_stays_readonly(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        before = manifest.read_bytes()
        with self.assertRaisesRegex(backend.BackendError, "owned skill directory is not plain"):
            backend.check(self.config, str(RULESYNC))
        self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse((out / backend.JOURNAL).exists())
        self.assertTrue(self.apply())
        self.assertNotIn("skill_directories", json.loads(manifest.read_text()))
        self.assertFalse(root.exists())
        self.assertTrue(backend.check(self.config, str(RULESYNC)))
        self.assertFalse(self.apply())
        root.mkdir()
        self.skill("demo", "Demo")
        retired_manifest = manifest.read_bytes()
        with self.assertRaisesRegex(backend.BackendError, "unowned same-name skill"):
            self.apply()
        self.assertEqual(manifest.read_bytes(), retired_manifest)
        self.assertEqual(list(root.iterdir()), [])

    def test_absent_retirement_requires_zero_desired_and_owned_files(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        before = manifest.read_bytes()
        self.skill("demo", "Demo")
        with self.assertRaisesRegex(backend.BackendError, "owned skill directory is not plain"):
            self.apply()
        self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(root.exists())
        self.assertTrue((self.src / "skills/demo/SKILL.md").is_file())
        shutil.rmtree(self.src / "skills/demo")
        self.assertTrue(self.apply())
        self.skill("demo", "Demo")
        self.assertTrue(self.apply())
        shutil.rmtree(root)
        shutil.rmtree(self.src / "skills/demo")
        before = manifest.read_bytes()
        with self.assertRaisesRegex(backend.BackendError, "externally modified owned file"):
            self.apply()
        self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(root.exists())

    def test_absent_retirement_preserves_present_records_and_refuses_foreign_tree(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        record = json.loads(manifest.read_text())["skill_directories"][0]
        root.mkdir()
        recorded_inode = next(entry["inode"] for entry in record["directories"] if entry["path"] == record["path"])
        if root.stat().st_ino == recorded_inode:
            root.rename(root.with_name("held-replacement"))
            root.mkdir()
        self.assertNotEqual(root.stat().st_ino, recorded_inode)
        (root / "agents").mkdir()
        before = manifest.read_bytes()
        with self.assertRaisesRegex(backend.BackendError, "identity changed"):
            self.apply()
        self.assertEqual(manifest.read_bytes(), before)
        shutil.rmtree(root)
        self.assertTrue(self.apply())
        self.skill("demo", "Demo")
        self.assertTrue(self.apply())
        shutil.rmtree(self.src / "skills/demo")
        self.assertTrue(self.apply())
        before = manifest.read_bytes()
        identities = {path: path.stat().st_ino for path in (root,)}
        self.assertFalse(self.apply())
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual({path: path.stat().st_ino for path in identities}, identities)
        foreign = root / "foreign.txt"
        foreign.write_text("foreign")
        with self.assertRaisesRegex(backend.BackendError, "unowned contents"):
            self.apply()
        self.assertEqual(foreign.read_text(), "foreign")
        self.assertEqual(manifest.read_bytes(), before)
        foreign.unlink()
        foreign.mkdir()
        with self.assertRaisesRegex(backend.BackendError, "unowned directory"):
            self.apply()
        self.assertTrue(foreign.is_dir())
        self.assertEqual(manifest.read_bytes(), before)

    def test_absent_retirement_refuses_parent_link(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        parent = root.parent
        saved = parent.with_name("saved-skills")
        parent.rename(saved)
        foreign = self.root / "foreign"
        foreign.mkdir()
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(parent), str(foreign)], check=True, capture_output=True)
        else:
            parent.symlink_to(foreign, target_is_directory=True)
        before = manifest.read_bytes()
        with self.assertRaisesRegex(backend.BackendError, "retired skill ancestor is not plain"):
            self.apply()
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual(list(foreign.iterdir()), [])
        self.assertFalse((out / backend.JOURNAL).exists())

    def test_absent_retirement_refuses_mounted_ancestor_below_output(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        before = manifest.read_bytes()
        original = os.path.ismount
        def mounted(path):
            return path == root.parent or original(path)
        with patch.object(backend.os.path, "ismount", mounted):
            with self.assertRaisesRegex(backend.BackendError, "retired skill ancestor is mounted"):
                self.apply()
        self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(root.exists())
        self.assertFalse((out / backend.JOURNAL).exists())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mountinfo only")
    def test_absent_retirement_refuses_same_device_bind_mount_with_escaped_path(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        before = manifest.read_bytes()
        original = Path.read_text
        mountpoint = str(root.parent).replace("\\", "\\134").replace(" ", "\\040")
        def mounted(path, *args, **kwargs):
            if path == Path("/proc/self/mountinfo"):
                return f"123 456 0:1 / {mountpoint} rw - tmpfs tmpfs rw\n"
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", mounted), patch.object(backend.os.path, "ismount", return_value=False):
            with self.assertRaisesRegex(backend.BackendError, "retired skill ancestor is mounted"):
                self.apply()
        self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(root.exists())
        self.assertFalse((out / backend.JOURNAL).exists())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mountinfo only")
    def test_absent_retirement_refuses_unreadable_or_malformed_mountinfo(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        before = manifest.read_bytes()
        original = Path.read_text
        for content, expected in ((None, "cannot inspect retired skill directory"),
                                  ("malformed", "invalid Linux mount information"),
                                  ("", "invalid Linux mount information")):
            with self.subTest(content=content):
                def unreadable(path, *args, **kwargs):
                    if path == Path("/proc/self/mountinfo"):
                        if content is None:
                            raise PermissionError("mountinfo denied")
                        return content
                    return original(path, *args, **kwargs)
                with patch.object(Path, "read_text", unreadable):
                    with self.assertRaisesRegex(backend.BackendError, expected):
                        self.apply()
                self.assertEqual(manifest.read_bytes(), before)
                self.assertFalse(root.exists())
                self.assertFalse((out / backend.JOURNAL).exists())

    def test_absent_retirement_permission_failure_is_not_absence(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        before = manifest.read_bytes()
        original = Path.lstat
        def denied(path, *args, **kwargs):
            if path == root / "agents":
                raise PermissionError("denied descendant")
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", denied):
            with self.assertRaisesRegex(backend.BackendError, "cannot inspect retired skill directory.*denied descendant"):
                self.apply()
        self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(root.exists())
        self.assertFalse((out / backend.JOURNAL).exists())

    def test_absent_retirement_rechecks_recorded_descendants(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        before = manifest.read_bytes()
        original = Path.lstat
        def descendant_present(path, *args, **kwargs):
            if path == root / "agents":
                return original(root.parent)
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", descendant_present):
            with self.assertRaisesRegex(backend.BackendError, "retired skill directory is not absent"):
                self.apply()
        self.assertEqual(manifest.read_bytes(), before)
        self.assertFalse(root.exists())

    def test_absent_retirement_transaction_rechecks_tree_and_parent_identity(self):
        for replace_parent in (False, True):
            with self.subTest(replace_parent=replace_parent):
                out, root, manifest = self.absent_retired_skill_fixture()
                before = manifest.read_bytes()
                original = backend._write_atomic
                def race(path, *args):
                    original(path, *args)
                    if path.name == backend.JOURNAL:
                        if replace_parent:
                            root.parent.rename(root.parent.with_name("old-skills"))
                            root.parent.mkdir()
                        else:
                            root.mkdir()
                with patch.object(backend, "_write_atomic", race):
                    with self.assertRaisesRegex(backend.BackendError, "retired skill directory ancestry changed"):
                        self.apply()
                self.assertEqual(manifest.read_bytes(), before)
                self.assertFalse((out / backend.JOURNAL).exists())
                self.assertEqual(list(root.iterdir()) if root.exists() else list(root.parent.iterdir()), [])
                shutil.rmtree(out)
                self.skill("demo", "Demo")

    def test_absent_retirement_crash_after_manifest_recovers_before_retry(self):
        out, root, manifest = self.absent_retired_skill_fixture()
        before = manifest.read_bytes()
        self.rule("a", "After retirement crash")
        script = """
import importlib.util, os, pathlib, sys
spec = importlib.util.spec_from_file_location('backend', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
old = pathlib.Path.unlink
def crash(path, *args, **kwargs):
    if path.name == m.JOURNAL: os._exit(23)
    return old(path, *args, **kwargs)
pathlib.Path.unlink = crash
m.apply(sys.argv[2], sys.argv[3])
"""
        result = subprocess.run([sys.executable, "-c", script, str(ROOT / "bin/rulesync_backend.py"), str(self.config), str(RULESYNC)])
        self.assertEqual(result.returncode, 23)
        self.assertNotIn("skill_directories", json.loads(manifest.read_text()))
        with self.assertRaisesRegex(backend.BackendError, "pending Rulesync transaction"):
            backend.check(self.config, str(RULESYNC))
        original = backend._validate_reconcile
        recovered = []
        def validate(*args, **kwargs):
            recovered.append(manifest.read_bytes())
            return original(*args, **kwargs)
        with patch.object(backend, "_validate_reconcile", validate):
            self.assertTrue(self.apply())
        self.assertEqual(recovered, [before])
        self.assertFalse(root.exists())
        self.assertFalse((out / backend.JOURNAL).exists())
        self.assertIn("After retirement crash", (out / "AGENTS.md").read_text())
        self.assertTrue(backend.check(self.config, str(RULESYNC)))

    def removed_skill_fixture(self):
        out = self.root / "transaction"
        out.mkdir()
        plain_mode = 0o666 if os.name == "nt" else 0o644
        executable_mode = 0o666 if os.name == "nt" else 0o755
        desired = {".agents/skills/category/demo/SKILL.md": (b"skill", plain_mode),
                   ".agents/skills/category/demo/references/deep.txt": (b"support", executable_mode),
                   ".agents/skills/category/other/SKILL.md": (b"retained", plain_mode)}
        backend._apply_reconcile(out, desired, {})
        root = out / ".agents/skills/category/demo"
        if os.name != "nt":
            root.chmod(0o750)
            (root / "references").chmod(0o710)
        owned = {rel: {"sha256": backend._digest(data), "mode": mode} for rel, (data, mode) in desired.items()}
        retained = {rel: value for rel, value in desired.items() if "/other/" in rel}
        return out, root, desired, owned, retained

    def test_retired_skill_foreign_empty_directory_blocks_and_rolls_back(self):
        out, root, desired, owned, retained = self.removed_skill_fixture()
        (root / "unowned-empty").mkdir()
        modes = {p: p.stat().st_mode & 0o777 for p in (root, root / "references")}
        with self.assertRaisesRegex(backend.BackendError, "unowned directory"):
            backend._apply_reconcile(out, retained, owned)
        for rel, (data, mode) in desired.items():
            self.assertEqual((out / rel).read_bytes(), data)
            self.assertEqual((out / rel).stat().st_mode & 0o777, mode)
        for directory, mode in modes.items():
            self.assertEqual(directory.stat().st_mode & 0o777, mode)
        self.assertTrue((root / "unowned-empty").is_dir())
        self.assertFalse((out / backend.JOURNAL).exists())

    def test_retired_skill_unowned_file_and_fresh_empty_skill_refused(self):
        out, root, desired, owned, retained = self.removed_skill_fixture()
        config = backend._load_config(self.config)
        (root / "foreign.txt").write_text("foreign")
        with self.assertRaisesRegex(backend.BackendError, "unowned contents"):
            backend._validate_reconcile(out, retained, owned, config)
        self.assertEqual((root / "foreign.txt").read_text(), "foreign")
        (root / "foreign.txt").unlink()
        backend._apply_reconcile(out, retained, owned)
        shutil.rmtree(root)
        root.mkdir()
        with self.assertRaisesRegex(backend.BackendError, "unowned same-name"):
            backend._validate_reconcile(out, desired, {rel: owned[rel] for rel in retained}, config)

    def test_retired_skill_crash_after_manifest_recovers_ownership_and_files(self):
        out, root, desired, owned, retained = self.removed_skill_fixture()
        modes = {p.relative_to(out).as_posix(): p.stat().st_mode & 0o777 for p in (root, root / "references")}
        script = """
import importlib.util, json, os, pathlib, sys
spec = importlib.util.spec_from_file_location('backend', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
old = pathlib.Path.unlink
def crash(path, *args, **kwargs):
    if path.name == m.JOURNAL: os._exit(23)
    return old(path, *args, **kwargs)
pathlib.Path.unlink = crash
out = pathlib.Path(sys.argv[2])
owned = json.loads(sys.argv[3])
retained_path = '.agents/skills/category/other/SKILL.md'
retained = {retained_path: (b'retained', owned[retained_path]['mode'])}
m._apply_reconcile(out, retained, owned)
"""
        result = subprocess.run([sys.executable, "-c", script, str(ROOT / "bin/rulesync_backend.py"), str(out), json.dumps(owned)])
        self.assertEqual(result.returncode, 23)
        self.assertTrue(root.exists())
        backend._recover(out, backend._load_config(self.config))
        for rel, (data, mode) in desired.items():
            self.assertEqual((out / rel).read_bytes(), data)
            self.assertEqual((out / rel).stat().st_mode & 0o777, mode)
        for rel, mode in modes.items():
            self.assertEqual((out / rel).stat().st_mode & 0o777, mode)
        self.assertFalse((out / backend.JOURNAL).exists())

    def test_retired_skill_identity_replacement_and_bad_manifest_refused(self):
        out, root, desired, owned, retained = self.removed_skill_fixture()
        backend._apply_reconcile(out, retained, owned)
        config = backend._load_config(self.config)
        state = backend._read_manifest(out, config)
        moved = root.with_name("original")
        root.rename(moved)
        root.mkdir()
        with self.assertRaisesRegex(backend.BackendError, "identity changed"):
            backend._validate_reconcile(out, desired, state, config)
        root.rmdir()
        moved.rename(root)
        value = json.loads((out / backend.MANIFEST).read_text())
        for rel, inode in ((".agents/skills", 42), ("../escape", 42),
                           (".agents/skills/category/demo", 0),
                           (".agents/skills/category/demo", True)):
            changed = json.loads(json.dumps(value))
            changed["skill_directories"][0]["directories"][0]["path"] = rel
            changed["skill_directories"][0]["directories"][0]["inode"] = inode
            (out / backend.MANIFEST).write_text(json.dumps(changed))
            with self.assertRaisesRegex(backend.BackendError, "invalid ownership manifest"):
                backend._read_manifest(out, config)

    def test_retired_skill_partial_support_removal_then_full_removal_readd(self):
        out, root, desired, owned, retained = self.removed_skill_fixture()
        config = backend._load_config(self.config)
        without_support = {rel: value for rel, value in desired.items() if not rel.endswith("deep.txt")}
        backend._apply_reconcile(out, without_support, owned)
        first = backend._read_manifest(out, config)
        self.assertTrue((root / "references").is_dir())
        self.assertFalse(backend._apply_reconcile(out, without_support, first))
        backend._validate_reconcile(out, retained, first, config)
        backend._apply_reconcile(out, retained, first)
        removed = backend._read_manifest(out, config)
        backend._validate_reconcile(out, desired, removed, config)
        backend._apply_reconcile(out, desired, removed)
        readded = backend._read_manifest(out, config)
        self.assertFalse(backend._apply_reconcile(out, desired, readded))
        for rel, (data, mode) in desired.items():
            self.assertEqual((out / rel).read_bytes(), data)
            self.assertEqual((out / rel).stat().st_mode & 0o777, mode)

    def test_retired_skill_new_support_directory_is_immediately_idempotent(self):
        out, root, desired, owned, retained = self.removed_skill_fixture()
        data = json.loads(self.config.read_text())
        data["output_root"] = str(out)
        self.config.write_text(json.dumps(data))
        config = backend._load_config(self.config)
        without_support = {rel: value for rel, value in desired.items() if not rel.endswith("deep.txt")}
        backend._apply_reconcile(out, without_support, owned)
        state = backend._read_manifest(out, config)
        expanded = dict(without_support)
        plain_mode = 0o666 if os.name == "nt" else 0o644
        expanded[".agents/skills/category/demo/new/nested.txt"] = (b"new support", plain_mode)
        backend._validate_reconcile(out, expanded, state, config)
        backend._apply_reconcile(out, expanded, state)
        state = backend._read_manifest(out, config)
        from unittest.mock import patch
        with patch.object(backend, "_generate", return_value=expanded):
            self.assertTrue(backend.check(self.config, str(RULESYNC)))
            self.assertFalse(self.apply())
        backend._apply_reconcile(out, without_support, state)
        state = backend._read_manifest(out, config)
        backend._apply_reconcile(out, retained, state)
        state = backend._read_manifest(out, config)
        backend._validate_reconcile(out, expanded, state, config)
        backend._apply_reconcile(out, expanded, state)
        self.assertEqual((root / "new/nested.txt").read_bytes(), b"new support")
        self.assertFalse(backend._apply_reconcile(out, expanded, backend._read_manifest(out, config)))

    def test_retired_skill_noop_foreign_contents_and_links_refused(self):
        out, root, desired, owned, retained = self.removed_skill_fixture()
        backend._apply_reconcile(out, retained, owned)
        config = backend._load_config(self.config)
        state = backend._read_manifest(out, config)
        self.assertFalse(backend._apply_reconcile(out, retained, state))
        foreign = root / "foreign.txt"
        foreign.write_text("foreign")
        with self.assertRaisesRegex(backend.BackendError, "unowned contents"):
            backend._validate_reconcile(out, desired, state, config)
        self.assertEqual(foreign.read_text(), "foreign")
        foreign.unlink()
        foreign.mkdir()
        with self.assertRaisesRegex(backend.BackendError, "unowned directory"):
            backend._validate_reconcile(out, desired, state, config)
        foreign.rmdir()
        target = self.root / "foreign-target"
        target.mkdir()
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(foreign), str(target)], check=True, capture_output=True)
        else:
            foreign.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(backend.BackendError, "symlink or junction"):
            backend._validate_reconcile(out, desired, state, config)
        self.assertTrue(target.is_dir())

    def test_retired_skill_manifest_cleanup_failure_rolls_back(self):
        from unittest.mock import patch
        out, root, desired, owned, retained = self.removed_skill_fixture()
        manifest_before = (out / backend.MANIFEST).read_bytes()
        identities = {path: (path.stat().st_dev, path.stat().st_ino, path.stat().st_mode) for path in (root, root / "references")}
        original = Path.unlink
        calls = [0]
        def fail_once(path, *args, **kwargs):
            if path.name == backend.JOURNAL:
                calls[0] += 1
                if calls[0] == 1:
                    raise OSError("cleanup failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", fail_once):
            with self.assertRaisesRegex(OSError, "cleanup failure"):
                backend._apply_reconcile(out, retained, owned)
        self.assertEqual((out / backend.MANIFEST).read_bytes(), manifest_before)
        for path, identity in identities.items():
            self.assertEqual((path.stat().st_dev, path.stat().st_ino, path.stat().st_mode), identity)
        for rel, (data, mode) in desired.items():
            self.assertEqual((out / rel).read_bytes(), data)
        self.assertFalse((out / backend.JOURNAL).exists())

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

    def recovery_fixture(self, current=b"before"):
        out = self.root / "recovery"
        out.mkdir()
        path = out / "AGENTS.md"
        path.write_bytes(current)
        mode = path.stat().st_mode & 0o777
        before, after = (b"before", mode), (b"after", mode)
        journal = backend._journal_bytes({path: before}, {path: after}, out, [])
        (out / backend.JOURNAL).write_bytes(journal)
        return out, path, journal, {"targets": ["codexcli"], "global": False}

    def test_recovery_before_state_preserves_file_identity(self):
        out, path, journal, config = self.recovery_fixture()
        identity = path.stat()
        with patch.object(backend, "_write_atomic", side_effect=PermissionError("replacement denied")):
            backend._recover(out, config)
        self.assertEqual(path.read_bytes(), b"before")
        self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns),
                         (identity.st_ino, identity.st_mtime_ns))
        self.assertFalse((out / backend.JOURNAL).exists())

    def test_recovery_restores_after_state(self):
        out, path, journal, config = self.recovery_fixture(b"after")
        backend._recover(out, config)
        self.assertEqual(path.read_bytes(), b"before")
        self.assertFalse((out / backend.JOURNAL).exists())

    def test_recovery_failure_retains_journal_and_can_resume(self):
        out, path, journal, config = self.recovery_fixture(b"after")
        second = out / ".claude/rules/a.md"
        second.parent.mkdir(parents=True)
        second.write_bytes(b"after")
        mode = second.stat().st_mode & 0o777
        journal = backend._journal_bytes(
            {path: (b"before", mode), second: (b"before", mode)},
            {path: (b"after", mode), second: (b"after", mode)}, out, [])
        (out / backend.JOURNAL).write_bytes(journal)
        write = backend._write_atomic
        def fail_second(target, *args):
            if target == second:
                raise PermissionError("recovery denied")
            write(target, *args)
        with patch.object(backend, "_write_atomic", side_effect=fail_second):
            with self.assertRaisesRegex(backend.BackendError, "recovery denied"):
                backend._recover(out, {"targets": ["codexcli", "claudecode"], "global": False})
        self.assertEqual(path.read_bytes(), b"before")
        self.assertEqual(second.read_bytes(), b"after")
        self.assertEqual((out / backend.JOURNAL).read_bytes(), journal)
        identity = path.stat()
        backend._recover(out, {"targets": ["codexcli", "claudecode"], "global": False})
        self.assertEqual(path.stat().st_ino, identity.st_ino)
        self.assertEqual(second.read_bytes(), b"before")
        self.assertFalse((out / backend.JOURNAL).exists())

    def test_recovery_refuses_later_user_edit(self):
        out, path, journal, config = self.recovery_fixture(b"user edit")
        with self.assertRaisesRegex(backend.BackendError, "external edit"):
            backend._recover(out, config)
        self.assertEqual(path.read_bytes(), b"user edit")
        self.assertEqual((out / backend.JOURNAL).read_bytes(), journal)

    def test_apply_reports_original_and_rollback_causes(self):
        out = self.root / "failed-apply"
        out.mkdir()
        path = out / "AGENTS.md"
        path.write_bytes(b"before")
        mode = path.stat().st_mode & 0o777
        other = out / ".claude/rules/a.md"
        other.parent.mkdir(parents=True)
        desired = {"AGENTS.md": (b"after", mode), ".claude/rules/a.md": (b"new", mode)}
        owned = {"AGENTS.md": {"sha256": backend._digest(b"before"), "mode": mode}}
        write = backend._write_atomic
        def fail(target, data, permissions):
            if target == other:
                raise PermissionError("original apply denied")
            if target == path and data == b"before":
                raise PermissionError("rollback restore denied")
            write(target, data, permissions)
        with patch.object(backend, "_write_atomic", side_effect=fail):
            with self.assertRaises(backend.BackendError) as caught:
                backend._apply_reconcile(out, desired, owned)
        self.assertIn("original apply denied", str(caught.exception))
        self.assertIn("rollback restore denied", str(caught.exception))
        self.assertIn("AGENTS.md", str(caught.exception))
        self.assertTrue((out / backend.JOURNAL).exists())
        backend._recover(out, {"targets": ["codexcli", "claudecode"], "global": False})
        self.assertEqual(path.read_bytes(), b"before")
        self.assertFalse(other.exists())
        self.assertFalse((out / backend.JOURNAL).exists())


if __name__ == "__main__":
    unittest.main()
