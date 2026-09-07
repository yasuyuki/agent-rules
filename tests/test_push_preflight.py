"""Offline policy fixtures and real-Git collection tests."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("push_preflight", ROOT / "bin/push_preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)

BASE = {
    "current_branch": "feature",
    "candidates": {"branch_push_remote": None, "remote_push_default": None, "branch_remote": None},
    "remotes": {"origin": {"fetch_urls": ["https://github.com/example/project.git"],
                           "push_urls": [], "push_refspecs": [], "mirror": False}},
    "upstream": {"remote": None, "merge": None},
    "repo": {"host": "github", "visibility": "private", "default_branch": "main",
             "license_spdx_id": None, "metadata_error": False},
}


class PolicyTests(unittest.TestCase):
    def test_distinct_remote_endpoints(self):
        for fetch, push in [
            ("https://github.com/example/project.git", "ssh://git@github.com:2222/example/project.git"),
            ("file:///srv/Project.git", "file:///srv/project.git"),
            ("file:///srv/project.git", "file://other/srv/project.git"),
            ("file:///srv/project.git", "file:///srv/project"),
            ("https://github.com/a/b.git?route=one", "https://github.com/a/b.git?route=two"),
            ("ssh://one@host/project.git", "ssh://two@host/project.git"),
        ]:
            with self.subTest(push=push):
                state = copy.deepcopy(BASE)
                state["remotes"]["origin"]["fetch_urls"] = [fetch]
                state["remotes"]["origin"]["push_urls"] = [push]
                self.assertEqual(preflight.decide(state, user_intent="push")["decision"], "ask")

    def test_real_git_remote_rewrites(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                return subprocess.run(["git", "-C", directory, *args], check=True,
                                      text=True, capture_output=True).stdout
            git("init", "-q")
            git("symbolic-ref", "HEAD", "refs/heads/feature")
            git("remote", "add", "origin", "https://github.com/example/project.git")
            native_run = subprocess.run
            def read_only_run(argv, **kwargs):
                if argv[0] == "gh":
                    return subprocess.CompletedProcess(argv, 0, json.dumps({
                        "private": True, "default_branch": "main", "license": None,
                    }), "")
                self.assertNotIn("push", argv[1:])
                return native_run(argv, **kwargs)
            with patch.object(preflight.subprocess, "run", side_effect=read_only_run):
                self.assertEqual(preflight.decide(preflight.collect_state(Path(directory)))["decision"], "push")
            git("config", "url.https://github.com/other/.pushInsteadOf", "https://github.com/example/")
            with patch.object(preflight.subprocess, "run", side_effect=read_only_run):
                result = preflight.decide(preflight.collect_state(Path(directory)))
            self.assertEqual(result["decision"], "ask", result)

    def test_policy_fixtures(self):
        fixtures = json.loads((ROOT / "tests/fixtures/push_preflight.json").read_text())
        for fixture in fixtures:
            with self.subTest(fixture=fixture["name"]):
                state = copy.deepcopy(BASE)
                for key, value in fixture.get("state", {}).items():
                    if isinstance(value, dict):
                        state[key].update(value)
                    else:
                        state[key] = value
                before = copy.deepcopy(state)
                result = preflight.decide(state, **fixture.get("inputs", {}))
                self.assertEqual(result["decision"], fixture["decision"], result)
                self.assertEqual(result["reason"], fixture["reason"])
                self.assertEqual(state, before)
                if result["decision"] == "push":
                    self.assertEqual(result["remote"], fixture.get("remote", "origin"))
                    self.assertEqual(result["destination"], fixture.get("destination", "feature"))
                    self.assertEqual(result["push_argv"], ["git", "push", result["remote"],
                                    "HEAD:refs/heads/" + result["destination"]])
                else:
                    self.assertFalse(result.get("push_argv"))

    def test_cli_local_repository_no_remote(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "-q", directory], check=True)
            subprocess.run(["git", "-C", directory, "symbolic-ref", "HEAD", "refs/heads/feature"], check=True)
            result = subprocess.run([sys.executable, str(ROOT / "bin/push_preflight.py"), directory],
                                    text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout)["decision"], "ask")
            held = subprocess.run([sys.executable, str(ROOT / "bin/push_preflight.py"), directory,
                                   "--user-intent", "hold"], text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(held.stdout)["decision"], "hold")


if __name__ == "__main__":
    unittest.main()
