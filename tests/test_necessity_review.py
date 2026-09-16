"""Restricted reviewer process behavior, with no Codex invocation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock


BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import necessity_review as review


class NecessityReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = {"model": "fixture", "effort": "low", "deadline_seconds": 1,
                    "max_output_bytes": 4096, "max_input_bytes": 4096}
        self.request = {"candidate_id": "candidate-1"}

    def test_blocking_stdin_obeys_single_deadline(self):
        payload = "x" * (2 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, "deadline"):
            review.bounded_run([sys.executable, "-c", "import time; time.sleep(10)"], payload,
                               cwd=self.root, env=os.environ.copy(), deadline=.1, limit=100)

    def test_output_budget_is_shared_between_pipes(self):
        code = "import sys; sys.stdout.write('x'*80); sys.stderr.write('y'*80)"
        with self.assertRaisesRegex(ValueError, "output limit"):
            review.bounded_run([sys.executable, "-c", code], "", cwd=self.root,
                               env=os.environ.copy(), deadline=1, limit=100)

    @unittest.skipUnless(os.name == "posix", "process groups are POSIX-specific")
    def test_descendant_holding_pipe_is_killed_within_deadline(self):
        pid_file = self.root / "descendant.pid"
        code = (
            "import pathlib, subprocess, sys; "
            "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']); "
            "pathlib.Path(sys.argv[1]).write_text(str(p.pid))"
        )
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, "output remained"):
            review.bounded_run([sys.executable, "-c", code, str(pid_file)], "", cwd=self.root,
                               env=os.environ.copy(), deadline=.15, limit=100)
        self.assertLess(time.monotonic() - started, .5)
        pid = int(pid_file.read_text())
        state = Path("/proc") / str(pid) / "stat"
        # A process may briefly remain as a reaped zombie, but cannot still run.
        until = time.monotonic() + .3
        while state.exists() and state.read_text().split()[2] not in {"Z"} and time.monotonic() < until:
            time.sleep(.01)
        if state.exists():
            self.assertEqual(state.read_text().split()[2], "Z")

    def test_environment_has_startup_essentials_without_ambient_secret(self):
        with mock.patch.dict(os.environ, {"PATH": "/bin", "HOME": "/home/test", "CODEX_HOME": "/codex",
                                          "PRODUCT_TOKEN": "never-pass-this"}, clear=True):
            env = review._review_env()
        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["CODEX_HOME"], "/codex")
        self.assertNotIn("PRODUCT_TOKEN", env)
        self.assertEqual(env["AGENT_RULES_NECESSITY_REVIEWER"], "1")

    def test_invocation_retains_hooks_and_disables_listed_mcp_only(self):
        calls = []
        verdict = {"candidate_id": "candidate-1", "action": "continue", "disposition": "normal",
                   "reason": "normal edit", "protections": "keep tests", "owner_or_entry": "",
                   "next_step": "continue"}

        def run(argv, text, **kwargs):
            calls.append((argv, text, kwargs))
            if argv[-3:] == ["mcp", "list", "--json"]:
                return json.dumps({"mcp_servers": [{"name": "safe name"}, {"name": "x.y"}]}), ""
            return json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(verdict)}}) + "\n", ""

        with mock.patch.object(review.managed_entry, "resolve_executable", return_value="codex.cmd"), \
             mock.patch.object(review, "bounded_run", side_effect=run):
            result = review.review(self.request, self.cfg)
        self.assertEqual(result["candidate_id"], "candidate-1")
        argv = calls[1][0]
        self.assertNotIn("--ignore-user-config", argv)
        self.assertIn("--sandbox", argv)
        configs = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "-c"]
        self.assertIn('mcp_servers."safe name".enabled=false', configs)
        self.assertIn('mcp_servers."x.y".enabled=false', configs)
        self.assertIn("features.plugins=false", configs)
        self.assertIn("features.multi_agent=false", configs)
        self.assertIn("web_search=\"disabled\"", configs)
        self.assertEqual(calls[0][0][-3:], ["mcp", "list", "--json"])
        self.assertEqual(calls[0][0][1], "-c")
        self.assertNotIn("--strict-config", calls[0][0])
        self.assertNotIn("-C", calls[0][0])

    def test_schema_invalid_or_invalid_mcp_json_withholds_verdict(self):
        bad = {"candidate_id": "candidate-1", "action": "continue", "disposition": "normal"}
        with self.assertRaises(ValueError):
            review.validate(bad, "candidate-1")
        with mock.patch.object(review, "bounded_run", return_value=("not-json", "")):
            with self.assertRaisesRegex(ValueError, "MCP list emitted invalid JSON"):
                review.mcp_names("codex", self.cfg, self.root, {})


if __name__ == "__main__":
    unittest.main()
