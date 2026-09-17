"""Tests for the deliberately small local Markdown reference checker."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).with_name("docs_check.py")
SPEC = importlib.util.spec_from_file_location("docs_check", SOURCE)
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


class DocsCheckTests(unittest.TestCase):
    def write(self, root, name, text):
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def check(self, files):
        with tempfile.TemporaryDirectory() as directory:
            for name, text in files.items():
                self.write(directory, name, text)
            self.track(directory)
            return checker.check_documents(directory)

    def track(self, root):
        subprocess.run(["git", "init", "--quiet", root], check=True)
        subprocess.run(["git", "-C", root, "add", "--all"], check=True)

    def test_existing_maintained_documents_have_valid_supported_links(self):
        self.assertEqual(checker.check_documents(SOURCE.parents[1]), [])

    def test_deleted_target_leaves_unchanged_source_reference_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write(directory, "README.md", "[old index](docs/renamed.md)\n")
            target = Path(directory) / "docs/renamed.md"
            self.write(directory, "docs/renamed.md", "# Former target\n")
            self.track(directory)
            target.unlink()  # A rename/deletion must recheck this unchanged index.
            problems = checker.check_documents(directory)
        self.assertEqual([(problem.message, problem.target) for problem in problems],
                         [("missing local target", "docs/renamed.md")])

    def test_missing_and_present_heading_fragments(self):
        problems = self.check({
            "README.md": "[good](docs/guide.md#overview) [bad](docs/guide.md#missing)\n",
            "docs/guide.md": "# Overview\n## Overview\n",
        })
        self.assertEqual([(problem.message, problem.target) for problem in problems],
                         [("missing heading", "docs/guide.md#missing")])

    def test_heading_keeps_inline_code_and_fragment_is_a_literal_anchor(self):
        problems = self.check({
            "README.md": "[good](docs/guide.md#use-check) [case](docs/guide.md#Use-check)\n",
            "docs/guide.md": "# Use `check`\n",
        })
        self.assertEqual([(problem.message, problem.target) for problem in problems],
                         [("missing heading", "docs/guide.md#Use-check")])

    def test_code_examples_placeholders_external_and_outside_paths_are_excluded(self):
        problems = self.check({
            "README.md": """[web](https://example.test/missing) [placeholder]({path})
`[inline](missing.md)`
```markdown
[example](missing.md#missing)
```
[outside](../private.md)
""",
        })
        self.assertEqual(problems, [])

    def test_short_inner_fence_does_not_end_a_longer_fenced_example(self):
        problems = self.check({
            "README.md": """````markdown
[example](missing.md)
```
[still an example](also-missing.md)
````
""",
        })
        self.assertEqual(problems, [])

    def test_skill_and_rule_sources_are_maintained_documents(self):
        problems = self.check({
            "README.md": "# Index\n",
            "skills/example/SKILL.md": "[missing](guide.md)\n",
            "rules/example.rule.md": "[missing](guide.md)\n",
        })
        self.assertEqual([(problem.source.as_posix(), problem.message) for problem in problems], [
            ("rules/example.rule.md", "missing local target"),
            ("skills/example/SKILL.md", "missing local target"),
        ])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_source_symlink_escaping_repository_is_not_read(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            self.write(directory, "README.md", "# Index\n")
            external = Path(outside) / "escape.md"
            external.write_text("[private link](missing.md)\n", encoding="utf-8")
            escaped = Path(directory) / "docs/escape.md"
            escaped.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(external, escaped)
            self.track(directory)
            self.assertEqual(checker.check_documents(directory), [])


if __name__ == "__main__":
    unittest.main()
