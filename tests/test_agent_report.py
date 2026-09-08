"""Bounded contract tests for the standalone agent report collector."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bin" / "agent_report.py"
spec = importlib.util.spec_from_file_location("agent_report", SOURCE)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


GOOD = {"files": [], "skills": [], "unknowns": []}


class ReportToolTests(unittest.TestCase):
    def make_runner(self, directory):
        script = directory / "fake_agent.py"
        script.write_text(
            """import json, os, sys
marker = sys.argv[1]
expected_cwd = sys.argv[2]
args = sys.argv[3:]
if args == ['--version']:
    print(marker + ' 1.2.3')
    sys.exit()
if not os.path.samefile(os.getcwd(), expected_cwd):
    print('wrong cwd', file=sys.stderr); sys.exit(11)
if marker == 'codex':
    expected = ['exec', '--json', '--ephemeral', '--sandbox', 'read-only', '--skip-git-repo-check', '--color', 'never']
    if args[:-1] != expected or 'Target directory: ' not in args[-1]:
        print('unexpected codex query', file=sys.stderr); sys.exit(12)
    payload = json.dumps({'files': [{'name': '<unsafe>', 'path': '技能 loaded.txt', 'source': '<source>', 'role': 'r', 'scope': 's', 'state': 'loaded'}], 'skills': [{'name': '読み込み済み', 'path': '技能 loaded.txt', 'source': 'catalog', 'role': 'r', 'scope': 's', 'state': 'loaded'}, {'name': 'available', 'path': '', 'source': 'catalog', 'role': 'r', 'scope': 's', 'state': 'available'}], 'unknowns': []})
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'raw conversation/log'}}))
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': payload}}))
    print(json.dumps({'type': 'turn.completed'}))
elif marker == 'bad':
    print('not json')
elif marker == 'auth':
    print('do not reveal this stderr', file=sys.stderr)
    sys.exit(9)
elif marker == 'external':
    print(json.dumps({'files': [{'name': '<unsafe>', 'path': 'space \\u2603.txt', 'source': '<source>', 'role': 'r', 'scope': 's', 'state': 'loaded'}], 'skills': [], 'unknowns': []}))
else:
    expected = {'claude': ['--print', '--output-format', 'json', '--tools', '', '--permission-mode', 'dontAsk', '--no-session-persistence'], 'cursor': ['--print', '--output-format', 'json', '--mode', 'ask']}[marker]
    if args[:-1] != expected or 'Target directory: ' not in args[-1]:
        print('unexpected query', file=sys.stderr); sys.exit(12)
    payload = json.dumps({'files': [{'name': '<unsafe>', 'path': 'space \\u2603.txt', 'source': '<source>', 'role': 'r', 'scope': 's', 'state': 'loaded'}], 'skills': [], 'unknowns': []})
    print(json.dumps({'type': 'result', 'result': payload}))
""",
            encoding="utf-8",
        )
        return script

    def invoke(self, standalone, target, output, config, *extra):
        return subprocess.run(
            [sys.executable, str(standalone), str(target), "--output", str(output),
             "--launch-config", str(config), *extra],
            text=True, capture_output=True,
        )

    def test_standalone_builtin_cli_queries_and_escaping(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            standalone = directory / "agent_report.py"
            shutil.copy2(SOURCE, standalone)
            before = standalone.read_bytes()
            target = directory / "対象 日本語"; target.mkdir()
            (target / "技能 loaded.txt").touch()
            (target / "unrequested_plugin.py").write_text("raise RuntimeError('must not load')", encoding="utf-8")
            runner = self.make_runner(directory)
            config = directory / "launch.json"
            config.write_text(json.dumps({name: [sys.executable, str(runner), name, str(target)]
                                          for name in ("codex", "claude", "cursor")}), encoding="utf-8")
            output = directory / "report.html"
            result = self.invoke(standalone, target, output, config)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual({"codex: collected", "claude: collected", "cursor: collected"}, set(result.stdout.splitlines()))
            page = output.read_text(encoding="utf-8")
            self.assertIn("&lt;unsafe&gt;", page)
            self.assertNotIn("<unsafe>", page)
            self.assertNotIn("do not reveal this stderr", page)
            self.assertNotIn("raw conversation/log", page)
            self.assertIn("読み込み済み", page)
            self.assertIn("available", page)
            self.assertEqual(before, standalone.read_bytes())

    def test_external_plugin_uses_same_contract_and_is_rendered(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw); target = directory / "target"; target.mkdir()
            standalone = directory / "agent_report.py"; shutil.copy2(SOURCE, standalone)
            plugin_dir = directory / "plugins"; plugin_dir.mkdir()
            (plugin_dir / "external.py").write_text("""PLUGIN_API_VERSION = 1
class Adapter:
    id = 'external'; name = 'External'; cli_candidates = ['external-cli']; restrictions = 'trusted test adapter'
    def version_args(self): return ['--version']
    def query_args(self, target): return ['query']
    def parse_version(self, stdout): return '1.2.3'
    def parse_response(self, stdout):
        import json
        return json.loads(stdout)
def get_platforms(): return [Adapter()]
""", encoding="utf-8")
            runner = self.make_runner(directory)
            config = directory / "launch.json"
            config.write_text(json.dumps({"external": [sys.executable, str(runner), "external", str(target)]}), encoding="utf-8")
            output = directory / "report.html"
            result = self.invoke(standalone, target, output, config, "--plugin-dir", str(plugin_dir), "--platform", "external")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            page = output.read_text(encoding="utf-8")
            self.assertIn("External", page)
            self.assertIn("trusted test adapter", page)
            self.assertIn("&lt;unsafe&gt;", page)

    def test_plugin_load_failures_happen_before_cli_invocation(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw); target = directory / "target"; target.mkdir(); plugins = directory / "plugins"; plugins.mkdir()
            duplicate = plugins / "duplicate.py"
            duplicate.write_text("""PLUGIN_API_VERSION = 1
class A:
 id='codex'; name='x'; cli_candidates=['x']; restrictions='x'
 def version_args(self): return []
 def query_args(self, target): return ['x']
 def parse_version(self, value): return '1.0'
 def parse_response(self, value): return {}
def get_platforms(): return [A()]
""", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                with mock.patch.object(report, "run", side_effect=AssertionError("CLI invoked")):
                    report.load_platforms([plugins], target)
            duplicate.unlink()
            (plugins / "bad.py").write_text("""PLUGIN_API_VERSION = 1
class A:
 id='bad'; name='x'; cli_candidates=['x']; restrictions='x'
 def version_args(self, unexpected): return []
 def query_args(self, target): return ['x']
 def parse_version(self, value): return '1.0'
 def parse_response(self, value): return {}
def get_platforms(): return [A()]
""", encoding="utf-8")
            with self.assertRaises(TypeError):
                with mock.patch.object(report, "run", side_effect=AssertionError("CLI invoked")):
                    report.load_platforms([plugins], target)
            (plugins / "bad.py").write_text("PLUGIN_API_VERSION = True\ndef get_platforms(): return []\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Plugin load failed"):
                with mock.patch.object(report, "run", side_effect=AssertionError("CLI invoked")):
                    report.load_platforms([plugins], target)
            (plugins / "bad.py").write_text("""PLUGIN_API_VERSION = 1
class A:
 id='argv'; name='x'; cli_candidates=[True]; restrictions='x'
 def version_args(self): return []
 def query_args(self, target): return ['x']
 def parse_version(self, value): return '1.0'
 def parse_response(self, value): return {}
def get_platforms(): return [A()]
""", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Expected argument array"):
                report.load_platforms([plugins], target)
            (plugins / "bad.py").write_text("this is not python !!!", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Plugin load failed"):
                with mock.patch.object(report, "run", side_effect=AssertionError("CLI invoked")):
                    report.load_platforms([plugins], target)

    def test_registered_builtin_and_external_adapters_share_a_prepared_contract(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw); plugin_dir = directory / "plugins"; plugin_dir.mkdir()
            (plugin_dir / "external.py").write_text("""PLUGIN_API_VERSION = 1
class A:
 id='external'; name='External'; restrictions='r'; cli_candidates=['external-cli']
 def version_args(self): return ['--version']
 def query_args(self, target): return ['query']
 def parse_version(self, text): return '1.0'
 def parse_response(self, text): return {'files': [], 'skills': [], 'unknowns': []}
def get_platforms(): return [A()]
""", encoding="utf-8")
            registry = report.load_platforms([plugin_dir], directory)
            for identifier, entry in registry.items():
                with self.subTest(identifier=identifier):
                    self.assertEqual({"adapter", "plugin", "name", "restrictions", "cli_candidates", "version_args", "query_args"}, set(entry))
                    self.assertTrue(all(isinstance(arg, str) for arg in entry["cli_candidates"] + entry["version_args"] + entry["query_args"]))
            self.assertEqual("external", registry["external"]["adapter"].id)

    def test_validation_empty_omitted_and_path_statuses(self):
        self.assertEqual(GOOD, report.validate_data(GOOD))
        missing = report.validate_data({"files": [], "unknowns": []})
        self.assertEqual("skills", missing["unknowns"][0]["name"])
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw)
            existing = target / "space ☃.txt"; existing.touch()
            self.assertEqual("exists", report.path_status("space ☃.txt", target))
            self.assertEqual("missing", report.path_status("missing file", target))
            self.assertEqual("missing" if sys.platform.startswith("win") else "not checkable", report.path_status(r"C:\\missing", target))
            with mock.patch.object(Path, "stat", side_effect=PermissionError):
                self.assertEqual("not checkable", report.path_status("space ☃.txt", target))

    def test_collect_isolates_auth_malformed_and_partial_responses(self):
        class Adapter:
            def __init__(self, identifier):
                self.id = identifier; self.name = identifier; self.cli_candidates = [identifier]; self.restrictions = "r"
            def version_args(self): return ["--version"]
            def query_args(self, target): return ["query"]
            def parse_version(self, value): return "1.0"
            def parse_response(self, value): return report.json_object(value)
        registry = {name: {"adapter": Adapter(name), "plugin": "external.py" if name == "bad" else "builtin",
                           "name": name, "restrictions": "r", "cli_candidates": [name],
                           "version_args": ["--version"], "query_args": ["query"]}
                    for name in ("ok", "auth", "bad", "partial", "missing")}
        responses = [
            subprocess.CompletedProcess([], 0, "1.0", ""), subprocess.CompletedProcess([], 0, json.dumps(GOOD), ""),
            subprocess.CompletedProcess([], 0, "1.0", ""), subprocess.CompletedProcess([], 7, "", "sensitive stderr"),
            subprocess.CompletedProcess([], 0, "1.0", ""), subprocess.CompletedProcess([], 0, "not-json", ""),
            subprocess.CompletedProcess([], 0, "1.0", ""), subprocess.CompletedProcess([], 0, json.dumps({"files": [], "skills": []}), ""),
        ]
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(report.shutil, "which", side_effect=lambda x: None if x in ("missing", "absent-launcher") else x), mock.patch.object(report, "run", side_effect=responses):
            got = report.collect(registry, list(registry), {"missing": ["absent-launcher"]}, Path(raw))
        self.assertEqual(["collected", "query failed (exit 7)", "response conversion failed", "partial", "launcher not found"], [x["status"] for x in got])
        page = report.render(got, Path("/target"))
        self.assertNotIn("sensitive stderr", page)

    def test_response_error_envelopes_invalid_schema_and_incomplete_codex_turn_fail(self):
        claude = report.Builtin("claude", "Claude", ["claude"], "r")
        codex = report.Builtin("codex", "Codex", ["codex"], "r")
        with self.assertRaises(ValueError):
            claude.parse_response(json.dumps({"type": "result", "is_error": True, "result": "{}"}))
        with self.assertRaises(ValueError):
            codex.parse_response(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}}))
        class SchemaAdapter:
            id = "schema"; name = "schema"; restrictions = "r"; cli_candidates = ["schema"]
            def parse_response(self, text): return {"files": [{"name": True}], "skills": [], "unknowns": []}
        entry = {"adapter": SchemaAdapter(), "plugin": "external.py", "name": "schema", "restrictions": "r", "cli_candidates": ["schema"], "version_args": ["--version"], "query_args": ["query"]}
        replies = [subprocess.CompletedProcess([], 0, "1.0", ""), subprocess.CompletedProcess([], 0, "ignored", "")]
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(report.shutil, "which", return_value="schema"), mock.patch.object(report, "run", side_effect=replies):
            self.assertEqual("response conversion failed", report.collect({"schema": entry}, ["schema"], {}, Path(raw))[0]["status"])

    def test_timeout_launch_error_and_existing_output_do_not_write_or_overwrite(self):
        adapter = report.Builtin("codex", "Codex", ["codex"], "r")
        entry = {"adapter": adapter, "plugin": "builtin", "name": "Codex", "restrictions": "r", "cli_candidates": ["codex"], "version_args": ["--version"], "query_args": ["query"]}
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(report.shutil, "which", return_value="codex"):
            target = Path(raw)
            with mock.patch.object(report, "run", side_effect=[subprocess.CompletedProcess([], 0, "1.0", ""), subprocess.TimeoutExpired(["codex"], 1)]):
                self.assertEqual("timeout", report.collect({"codex": entry}, ["codex"], {}, target, 1)[0]["status"])
            with mock.patch.object(report, "run", side_effect=[subprocess.CompletedProcess([], 0, "1.0", ""), OSError()]):
                self.assertEqual("launch failed", report.collect({"codex": entry}, ["codex"], {}, target, 1)[0]["status"])
            existing = target / "exists.html"; existing.write_text("keep", encoding="utf-8")
            result = subprocess.run([sys.executable, str(SOURCE), str(target), "--output", str(existing)], text=True, capture_output=True)
            self.assertEqual(2, result.returncode)
            self.assertEqual("keep", existing.read_text(encoding="utf-8"))
        target = Path.cwd()
        with mock.patch.object(report.os, "name", "nt"), mock.patch.object(report.subprocess, "run") as runner:
            with self.assertRaisesRegex(OSError, "Batch launchers"):
                report.run(["unsafe.cmd"], target, None)
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
