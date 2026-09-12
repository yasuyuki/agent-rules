"""Saved launch inputs publish completely and never replace another writer."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("start_config_place", ROOT / "bin/place.py")
place = importlib.util.module_from_spec(spec)
spec.loader.exec_module(place)


class SavedStartTests(unittest.TestCase):
    def test_publish_read_repeat_and_preserve(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            declaration = root / "placement.md"
            declaration.write_text("""<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
s1\tlocal\ttester\t{home}\tlocal\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
work\ts1\tdirect\t{home}\t
```
<!-- END WORKSPACES TSV -->
<!-- BEGIN LOCATIONS TSV -->
```tsv
id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind
work-codex\tworkspace\twork\tcodex\trequired\t\t\t\trules
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
""".format(home=root.as_posix()), encoding="utf-8")
            output = root / "placement-start.json"
            argv = ["save-start-config", "--config", str(output), "--declaration", str(declaration)]
            self.assertEqual(place.main(argv), 0)
            original = output.read_bytes()
            self.assertEqual(place.main(argv), 0)
            self.assertEqual(output.read_bytes(), original)
            args = SimpleNamespace(config=str(output), declaration=None, rules=None, skills=None,
                                   site=None, workspace=None, scope=None)
            self.assertIsNone(place.start_config(args))
            self.assertEqual(Path(args.declaration), declaration)
            # The existing reader and normal start consume exactly these inputs.
            place.apply(args)
            args.workspace_id, args.tool, args.tool_args = "work", "codex", ["--resume"]
            args.declaration, args.rules, args.skills = None, None, None
            calls = []
            self.assertEqual(place.start(args, resolver=lambda _: "fixture-codex",
                runner=lambda argv, **kw: calls.append((argv, kw)) or SimpleNamespace(returncode=7)), 7)
            self.assertEqual(calls[0][0], ["fixture-codex", "--resume"])
            self.assertEqual(Path(calls[0][1]["cwd"]), root)
            for contents in (b"not-json", b'{"version":1,"unknown":"keep"}', b'{}'):
                output.write_bytes(contents)
                self.assertEqual(place.main(argv), 1)
                self.assertEqual(output.read_bytes(), contents)
            output.unlink()
            with patch.object(place.os, "link", side_effect=OSError("injected publication failure")):
                self.assertEqual(place.main(argv), 1)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".place-start-*")), [])
            link = os.link
            def competing_writer(source, target):
                Path(target).write_bytes(b'{"other":"writer"}')
                return link(source, target)
            with patch.object(place.os, "link", side_effect=competing_writer):
                self.assertEqual(place.main(argv), 1)
            self.assertEqual(output.read_bytes(), b'{"other":"writer"}')
            self.assertEqual(list(root.glob(".place-start-*")), [])
            output.unlink()
            declaration.write_text("invalid declaration", encoding="utf-8")
            self.assertEqual(place.main(argv), 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
