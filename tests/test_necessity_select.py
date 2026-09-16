"""Focused regression tests for bounded command selection facts."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("necessity_select", ROOT / "bin" / "necessity_select.py")
selector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selector)


class NecessitySelectTests(unittest.TestCase):
    def test_ordinary_process_and_completion_message_is_negative(self):
        self.assertEqual(selector.analyze("pytest -q; echo done")["features"], [])
        self.assertEqual(selector.analyze("import subprocess; subprocess.run(['pytest']); print('done')", shell="python")["features"], [])
    def test_funkot_shape_tracks_state_process_and_report(self):
        command = '''
from pathlib import Path
import json, subprocess
state = json.loads(Path("state.json").read_text())
Path("state.json").write_text(json.dumps(state))
subprocess.run(["funkot", "reconstruct", "state.json"], check=True)
print("reported")
'''
        facts = selector.analyze(command, shell="python")
        self.assertEqual([], facts["coverage"])
        self.assertIn("state.json", facts["writes"])
        self.assertIn("funkot", facts["executes"])
        self.assertTrue({"state", "process", "report"}.issubset(facts["responsibilities"]))
        self.assertIn("multiple-responsibilities", facts["features"])

    def test_scheduler_shape_tracks_setup_wait_process_result_and_cleanup(self):
        command = '''
from pathlib import Path
import subprocess, time
Path("run.py").write_text("print('job')")
job = subprocess.Popen(["python", "run.py"])
time.sleep(1)
job.wait()
Path("result.json").write_text("{}")
Path("run.py").unlink()
print("result")
'''
        facts = selector.analyze(command, shell="python")
        self.assertTrue({"state", "wait", "process", "cleanup", "report"}.issubset(facts["responsibilities"]))
        self.assertIn("run.py", facts["writes"])
        self.assertIn("run.py", facts["executes"])
        self.assertIn("generated-file-execution", facts["features"])

    def test_legitimate_single_operation_and_long_literal_are_not_candidates(self):
        literal = "x" * 10000
        facts = selector.analyze(
            f"from pathlib import Path\nPath('guide.md').write_text({literal!r})",
            shell="python",
        )
        self.assertEqual(["state"], facts["responsibilities"])
        self.assertEqual([], facts["features"])

    def test_bash_literal_commit_is_not_a_candidate(self):
        facts = selector.analyze('git commit -m "' + "long literal " * 1000 + '"')
        self.assertTrue(
            facts["coverage"] == []
            or facts["coverage"] == ["bash:unassessed (bashlex unavailable)"],
            facts,
        )
        self.assertEqual([], facts["features"])

    def test_unknown_python_syntax_is_not_certified(self):
        facts = selector.analyze("if:", shell="python")
        self.assertEqual(["python:unassessed (syntax error)"], facts["coverage"])

    def test_bash_tracks_generated_script_nested_commands_and_cleanup(self):
        command = "printf 'x' > run; python run; bash -c 'sleep 1; rm run; echo done'"
        facts = selector.analyze(command)
        if facts["coverage"]:
            self.assertIn("bashlex unavailable", facts["coverage"][0])
            return
        self.assertIn("run", facts["writes"])
        self.assertIn("run", facts["executes"])
        self.assertIn("generated-file-execution", facts["features"])
        self.assertTrue({"state", "process", "wait", "cleanup", "report"}.issubset(facts["responsibilities"]))

    def test_bash_heredoc_and_substitution_are_observed(self):
        command = "python <<EOF\nimport subprocess\nsubprocess.run(['echo', 'ok'])\nEOF\necho $(date)"
        facts = selector.analyze(command)
        if facts["coverage"]:
            self.assertIn("bash", facts["coverage"][0])
            return
        self.assertIn("echo", facts["executes"])
        self.assertIn("command-substitution", facts["features"])

    def test_quoted_heredoc_document_write_stays_single_responsibility(self):
        facts = selector.analyze("cat <<'DOC' > guide.md\nlong literal $(not run)\nDOC\n")
        if facts["coverage"]:
            self.assertIn("bash", facts["coverage"][0])
            return
        self.assertEqual(["state"], facts["responsibilities"])
        self.assertEqual([], facts["features"])

    def test_shell_path_and_python_module_flag_do_not_claim_file_execution(self):
        self.assertEqual([], selector.analyze("echo ok", shell="/bin/bash")["coverage"])
        facts = selector.analyze("python -m compileall", shell="/bin/bash")
        self.assertIn("python:unassessed (module execution)", facts["coverage"])
        self.assertNotIn("-m", facts["executes"])

    def test_powershell_parser_receives_source_on_stdin(self):
        runner = mock.Mock(return_value=mock.Mock(returncode=0, stdout='{"errors": 0, "writes": [], "executes": [], "responsibilities": []}'))
        with mock.patch.object(selector.shutil, "which", return_value="pwsh"), mock.patch.object(selector.subprocess, "run", runner):
            facts = selector.analyze("Write-Output '$not executed'", shell="pwsh", parser_timeout=7)
        self.assertEqual([], facts["coverage"])
        args, kwargs = runner.call_args
        self.assertIn("-File", args[0])
        self.assertNotIn("-Command", args[0])
        self.assertEqual("Write-Output '$not executed'", kwargs["input"])
        self.assertEqual(7, kwargs["timeout"])

    def test_powershell_requires_deadline(self):
        with mock.patch.object(selector.shutil, "which", return_value="pwsh"):
            facts = selector.analyze("Write-Output ok", shell="powershell.exe")
        self.assertIn("powershell:unassessed (missing parser timeout)", facts["coverage"])

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh is unavailable")
    def test_native_powershell_ast_does_not_execute_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "must-not-exist-from-parser"
            facts = selector.analyze(
                f"Set-Content -Path 'guide.md' -Value 'long literal'; Invoke-Expression \"Set-Content -Path '{marker}' -Value x\"",
                shell="pwsh", parser_timeout=24,
            )
            self.assertFalse(marker.exists())
            self.assertIn("guide.md", facts["writes"], facts)
            self.assertIn(str(marker), facts["writes"])
        ordinary = selector.analyze("git status --short; Write-Output 'done'", shell="pwsh", parser_timeout=24)
        self.assertEqual(ordinary["features"], [])
        self.assertEqual(ordinary["coverage"], [])


if __name__ == "__main__":
    unittest.main()
