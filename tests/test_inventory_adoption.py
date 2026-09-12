"""Real-Git coverage for source-bound runtime adoption."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("place", ROOT / "bin" / "place.py")
place = importlib.util.module_from_spec(spec)
spec.loader.exec_module(place)


def declaration(home, catalog="catalog.json"):
    return """<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
s1\tLinux\tagent\t%s\tlocal\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
w1\ts1\tdirect\t%s/work\t
```
<!-- END WORKSPACES TSV -->
<!-- BEGIN LOCATIONS TSV -->
```tsv
id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind
c1\thome\ts1\tcodex\trequired\t\t\t\tskills
c2\thome\ts1\tcodex\trequired\t\t\t\trules
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
<!-- BEGIN INVENTORY TSV -->
```tsv
site\tcatalog\tenvironment
s1\t%s\tenv
```
<!-- END INVENTORY TSV -->
""" % (home, home, catalog)


class InventoryAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"; (self.home / "work").mkdir(parents=True)
        self.declaration = self.root / "PLACEMENT.md"
        self.catalog = self.root / "catalog.json"
        self.config = self.root / "placement-start.json"
        self.declaration.write_text(declaration(self.home), encoding="utf-8")
        self.catalog.write_text(json.dumps({"schemaVersion": 1,
            "sources": {"p": {"type": "placement-tsv", "host": "test",
                                "paths": {"default": str(self.declaration)}}},
            "environments": [{"id": "env", "purposes": ["normal-development"], "state": "pending",
                "refs": [{"source": "p", "site": "s1", "workspace": "w1"}],
                "agents": [{"descriptor": "codex",
                    "principal": {"source": "p", "site": "s1", "field": "user"},
                    "configRoot": {"source": "p", "site": "s1", "tool": "codex"}}]}]}), encoding="utf-8")
        private_rules = self.root / "private-rules"; private_rules.mkdir()
        (private_rules / "environment-inventory-required.rule.md").write_text(
            "---\nid: environment-inventory-required\ntitle: Inventory\nsummary: inventory\ntools:\n  - codex\n---\n\ninventory binding\n",
            encoding="utf-8")
        self.config.write_text(json.dumps({"version": 1, "declaration": "PLACEMENT.md",
                                           "rules": ["private-rules"]}), encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("add", "PLACEMENT.md", "catalog.json")
        self.git("commit", "-qm", "inputs")
        self.catalog_bytes = self.catalog.read_bytes()
        self.old_runtime = place.current_runtime
        roots = {name: tool["configHome"]["default"].replace("$HOME", str(self.home))
                 for name, tool in place.load_placement()["tools"].items()}
        place.current_runtime = lambda _context: {"user": "agent", "home": str(self.home),
            "host": "Linux", "platform": "Linux", "configRoots": roots}

    def tearDown(self):
        place.current_runtime = self.old_runtime
        self.temp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def adopt(self):
        return place.main(["inventory", "adopt", "--config", str(self.config), "--site", "s1"],
                          resolver=lambda name: "/bin/" + name if name == "codex" else None)

    def start(self):
        calls = []
        result = place.main(["start", "--config", str(self.config), "w1", "codex"],
                            resolver=lambda name: "/bin/" + name if name == "codex" else None,
                            runner=lambda argv, **kwargs: (calls.append((argv, kwargs)) or SimpleNamespace(returncode=0)))
        return result, calls

    def test_environment_request_resolves_saved_site_and_refuses_unknown_target(self):
        before = self.config.read_bytes()
        command = ["inventory", "adopt", "--config", str(self.config),
                   "--environment", "missing", "--source-ref", "HEAD"]
        self.assertEqual(place.main(command), 1)
        self.assertEqual(self.config.read_bytes(), before)
        command[5] = "env"
        self.assertEqual(place.main([*command, "--check-inputs"]), 0)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.root / "catalog.json.lock").exists())
        self.assertFalse((self.root / "catalog.json.claim").exists())
        self.assertFalse((self.home / ".codex/AGENTS.md").exists())
        self.assertEqual(place.main(command, resolver=lambda name: "/bin/" + name if name == "codex" else None), 0)
        result = json.loads(self.config.read_text(encoding="utf-8"))["adoption"]
        self.assertEqual(result["environment"], "env")
        self.assertEqual(result["site"], "s1")
        self.assertEqual(self.catalog.read_bytes(), self.catalog_bytes)

    def test_adopt_keeps_catalog_and_allows_exact_pending_start(self):
        self.assertEqual(self.adopt(), 0)
        self.assertEqual(self.catalog.read_bytes(), self.catalog_bytes)
        active = self.config.read_bytes()
        document = json.loads(active)
        self.assertEqual(document["version"], 2)
        self.assertEqual(document["adoption"]["state"], "active")
        self.assertEqual(self.adopt(), 0)
        self.assertEqual(self.config.read_bytes(), active)
        result, calls = self.start()
        self.assertEqual(result, 0)
        self.assertEqual(calls[-1][0], ["/bin/codex"])
        explicit = place.main(["start", "--declaration", str(self.declaration), "w1", "codex"],
                              resolver=lambda name: "/bin/" + name if name == "codex" else None,
                              runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
        self.assertEqual(explicit, 1)
        self.assertEqual(self.catalog.read_bytes(), self.catalog_bytes)

    def test_dirty_tracked_declaration_refuses_before_config_mutation(self):
        original = self.config.read_bytes()
        self.declaration.write_bytes(self.declaration.read_bytes() + b"\nchanged\n")
        self.assertEqual(self.adopt(), 1)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.catalog.read_bytes(), self.catalog_bytes)

    def test_catalog_revision_accepts_git_filtered_crlf_declaration(self):
        self.git("config", "core.autocrlf", "true")
        (self.root / ".gitattributes").write_text("PLACEMENT.md text eol=crlf\n", encoding="utf-8")
        self.git("add", ".gitattributes"); self.git("commit", "-qm", "declare checkout eol")
        self.git("rm", "--cached", "-q", "PLACEMENT.md")
        self.git("reset", "--hard", "-q", "HEAD")
        self.assertIn(b"\r\n", self.declaration.read_bytes())
        self.assertEqual(self.adopt(), 0)

    def test_stale_or_dirty_inputs_refuse_without_catalog_write(self):
        self.assertEqual(self.adopt(), 0)
        active = self.config.read_bytes()
        rule = self.root / "private-rules" / "environment-inventory-required.rule.md"
        original_rule = rule.read_bytes(); rule.write_bytes(original_rule + b"\nchanged\n")
        self.assertEqual(self.start()[0], 1)
        rule.write_bytes(original_rule)
        self.catalog.write_bytes(self.catalog_bytes + b" ")
        self.assertEqual(self.adopt(), 1)
        self.assertEqual(self.config.read_bytes(), active)
        self.catalog.write_bytes(self.catalog_bytes)
        (self.root / "unrelated").write_text("next\n", encoding="utf-8")
        self.git("add", "unrelated"); self.git("commit", "-qm", "head moves")
        self.assertEqual(self.start()[0], 1)
        self.assertEqual(self.catalog.read_bytes(), self.catalog_bytes)

    def test_pending_readiness_failure_and_config_cas_preserve_state(self):
        old_apply = place.apply
        try:
            place.apply = lambda *_args, **_kwargs: (_ for _ in ()).throw(place.PlacementError("projection failed"))
            self.assertEqual(self.adopt(), 1)
        finally:
            place.apply = old_apply
        pending = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(pending["adoption"]["state"], "pending")
        self.assertEqual(self.catalog.read_bytes(), self.catalog_bytes)
        raw = self.config.read_bytes(); document = json.loads(raw)
        self.config.write_text(json.dumps({"version": 1, "declaration": "other.md"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "saved launch inputs changed"):
            place.inventory_adoption.write_state(place, self.config, raw, document, {}, "pending")

    def test_external_runtime_policy_is_bound_and_later_stales(self):
        with tempfile.TemporaryDirectory() as external_directory:
            external = Path(external_directory) / "PLACEMENT.md"
            external.write_text(declaration(self.home, str(self.catalog)), encoding="utf-8")
            document = json.loads(self.catalog.read_text(encoding="utf-8"))
            document["sources"]["p"]["paths"]["default"] = str(external)
            self.catalog.write_text(json.dumps(document), encoding="utf-8")
            self.git("add", "catalog.json"); self.git("commit", "-qm", "external policy")
            self.catalog_bytes = self.catalog.read_bytes()
            self.config.write_text(json.dumps({"version": 1, "declaration": str(external),
                                               "rules": ["private-rules"]}), encoding="utf-8")
            self.assertEqual(self.adopt(), 0)
            adopted = json.loads(self.config.read_text(encoding="utf-8"))["adoption"]
            self.assertEqual(adopted["sourceScope"], "catalog")
            self.assertEqual(adopted["declarationSource"], "external-runtime-policy")
            self.assertTrue(adopted["declarationDigest"])
            self.assertEqual(self.start()[0], 0)
            external.write_bytes(external.read_bytes() + b"\npolicy changed\n")
            self.assertEqual(self.start()[0], 1)
            self.assertEqual(self.catalog.read_bytes(), self.catalog_bytes)


if __name__ == "__main__":
    unittest.main()
