"""Focused Grok descriptor coverage using only temporary public fixtures."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PLACE = ROOT / "bin" / "place.py"


def load_place():
    spec = importlib.util.spec_from_file_location("grok_test_place", PLACE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GrokPlacementTests(unittest.TestCase):
    def run_place(self, *args, env=None):
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return subprocess.run(
            [sys.executable, str(PLACE), *args],
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=merged,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def write_declaration(self, root, home, workspace):
        declaration = root / "PLACEMENT.md"
        declaration.write_text(
            """<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
local\tlocal\ttester\t{home}\tlocal\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
work\tlocal\tdirect\t{workspace}\t
```
<!-- END WORKSPACES TSV -->
<!-- BEGIN LOCATIONS TSV -->
```tsv
id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind
grok-home-rules\thome\tlocal\tgrok\trequired\t\t\t\trules
grok-workspace-rules\tworkspace\twork\tgrok\trequired\t\t\t\trules
grok-home-skills\thome\tlocal\tgrok\trequired\t\t\t\tskills
grok-workspace-skills\tworkspace\twork\tgrok\trequired\t\t\t\tskills
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
""".format(home=home.as_posix(), workspace=workspace.as_posix()),
            encoding="utf-8",
        )
        return declaration

    def test_grok_apply_check_start_and_unmanaged_skill_rejection(self):
        descriptor = json.loads((ROOT / "placement.json").read_text(encoding="utf-8"))
        grok = descriptor["tools"]["grok"]
        self.assertEqual("grok", grok["entrypoint"])
        self.assertEqual("$HOME/.grok/auth.json", grok["credential"])
        self.assertEqual({"default": "$HOME/.grok", "env": "GROK_HOME"}, grok["configHome"])
        self.assertEqual(["agents-md-section"], grok["reads"]["rules"])
        self.assertEqual(["grok-skills-dir"], grok["reads"]["skills"])
        self.assertNotIn("hooks", grok)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, workspace = root / "home", root / "workspace"
            home.mkdir()
            workspace.mkdir()
            declaration = self.write_declaration(root, home, workspace)
            rules, skills = root / "rules", root / "skills"
            rules.mkdir()
            (rules / "project.rule.md").write_text(
                "---\nid: project\ntitle: Project\nsummary: Project rule\n---\nFollow this project rule.\n",
                encoding="utf-8",
            )
            management_skill = skills / "management-skill"
            management_skill.mkdir(parents=True)
            (management_skill / "SKILL.md").write_text(
                "---\nname: management-skill\ndescription: Fixture management skill\n---\nManage the fixture.\n",
                encoding="utf-8",
            )
            foreign = workspace / ".grok" / "skills" / "foreign-skill"
            foreign.mkdir(parents=True)
            (foreign / "SKILL.md").write_text("foreign skill\n", encoding="utf-8")

            common = ("--declaration", str(declaration), "--rules", str(rules), "--skills", str(skills))
            self.assert_ok(self.run_place("apply", *common))
            self.assert_ok(self.run_place("check", *common))
            for agents in (home / ".grok" / "AGENTS.md", workspace / "AGENTS.md"):
                self.assertIn("Follow this project rule.", agents.read_text(encoding="utf-8"))
            for skill in (home / ".grok" / "skills" / "management-skill", workspace / ".grok" / "skills" / "management-skill"):
                self.assertEqual("Manage the fixture.\n", skill.joinpath("SKILL.md").read_text(encoding="utf-8").split("---\n", 2)[-1])
            self.assertEqual("foreign skill\n", (foreign / "SKILL.md").read_text(encoding="utf-8"))

            collision_source = skills / "collision"
            collision_source.mkdir()
            (collision_source / "SKILL.md").write_text("---\nname: collision\ndescription: Collision\n---\n", encoding="utf-8")
            collision = workspace / ".grok" / "skills" / "collision"
            collision.mkdir()
            (collision / "SKILL.md").write_text("leave untouched\n", encoding="utf-8")
            refused = self.run_place("apply", *common)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("refusing to overwrite unmanaged skill", refused.stderr)
            self.assertEqual("leave untouched\n", (collision / "SKILL.md").read_text(encoding="utf-8"))
            (collision_source / "SKILL.md").unlink()
            collision_source.rmdir()

            executable = home / ".grok" / "bin"
            executable.mkdir()
            marker = root / "grok-started.txt"
            if os.name == "nt":
                (executable / "grok").write_text("fixture discovery marker\n", encoding="utf-8")
                command = executable / "grok.cmd"
                command.write_text(
                    "@echo off\r\necho %CD%> \"" + str(marker) + "\"\r\n"
                    "if \"%~1\"==\"--fail\" exit /b 23\r\nexit /b 0\r\n",
                    encoding="utf-8",
                )
            else:
                command = executable / "grok"
                command.write_text(
                    "#!/bin/sh\npwd > " + shlex.quote(str(marker))
                    + "\nif [ \"$1\" = \"--fail\" ]; then exit 23; fi\n",
                    encoding="utf-8",
                )
                command.chmod(0o755)
            self.assertTrue(load_place().detect_cli({"home": str(home)}, grok))
            started = self.run_place(
                "start", *common, "work", "grok", "--", "--fixture",
                env={"PATH": str(executable) + os.pathsep + os.environ.get("PATH", ""), "PATHEXT": ".CMD;.EXE;.BAT;.COM"},
            )
            self.assert_ok(started)
            self.assertEqual(str(workspace), marker.read_text(encoding="utf-8").strip())
            failed = self.run_place(
                "start", *common, "work", "grok", "--", "--fail",
                env={"PATH": str(executable) + os.pathsep + os.environ.get("PATH", ""), "PATHEXT": ".CMD;.EXE;.BAT;.COM"},
            )
            self.assertEqual(23, failed.returncode, failed.stdout + failed.stderr)


if __name__ == "__main__":
    unittest.main()
