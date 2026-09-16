"""Behavioral tests for native event handling; no model or user configuration."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import necessity_hook as hook
import necessity_review as review


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = dict(version=1, shell="bash", scopes=[str(self.root)], excludes=[], state_dir=str(self.root / "state"),
                        model="fixture", effort="low", deadline_seconds=2, max_input_bytes=65536,
                        max_output_bytes=65536, reviews_per_session=5, retention_seconds=3600, max_sessions=10)
        self.calls = []
        self.disposition = "disposable"
        self.action = "continue"

    def reviewer(self, request, config):
        self.calls.append(request)
        return dict(candidate_id=request["candidate_id"], action=self.action, disposition=self.disposition,
                    reason="Needed bounded fixture for the explicit request.", protections="Preserve cleanup and evidence.",
                    owner_or_entry="", next_step="Continue the requested fixture.")

    def event(self, event, **kw):
        return hook.handle(dict(hook_event_name=event, cwd=str(self.root), session_id="root", turn_id="turn1", **kw), self.cfg, self.reviewer)

    def lane_event(self, lane, event, session_id="root", **kw):
        return hook.handle(dict(hook_event_name=event, cwd=str(self.root), session_id=session_id, agent_id=lane,
                                turn_id="turn1", **kw), self.cfg, self.reviewer)

    def lane_state(self, lane, session_id="root"):
        sid = hook.digest([str(self.root.resolve()), session_id, lane])
        db = sqlite3.connect(self.root / "state" / "necessity.sqlite3")
        encoded = db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()[0]
        db.close()
        return json.loads(encoded)

    def prompt(self, text="Verify a bounded subprocess fixture and return its result."):
        return self.event("UserPromptSubmit", prompt=text)

    def command(self, cmd="python3 -c 'import subprocess; from pathlib import Path; Path(\"result\").write_text(\"pending\"); subprocess.run([\"true\"]); print(\"done\")'", **kw):
        return self.event("PreToolUse", tool_name="Bash", tool_use_id="tool1", tool_input={"command": cmd}, **kw)

    def test_negative_no_model_and_no_permission_grant(self):
        self.prompt()
        self.assertEqual(self.command("git status --short"), {})
        self.assertEqual(self.command("git commit -m '" + "long literal " * 500 + "'"), {})
        self.assertEqual(self.calls, [])
        result = self.command()
        self.assertNotIn("permissionDecision", result["hookSpecificOutput"])
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_and_changed_contract(self):
        self.prompt()
        self.command()
        self.command()
        self.assertEqual(len(self.calls), 1)
        self.prompt("Only read repository status. Do not construct any fixture.")
        self.command()
        self.assertEqual(len(self.calls), 2)

    def test_missing_or_expired_continuation_does_not_certify_history(self):
        self.assertEqual(self.event("SessionStart", source="startup"), {})
        empty = self.event("SessionStart", source="resume")
        self.assertIn("missing history", empty["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.calls, [])
        self.prompt()
        self.command()
        with patch.object(hook.time, "time", return_value=time.time() + self.cfg["retention_seconds"] + 1):
            expired = self.event("SessionStart", source="compact")
        self.assertIn("unassessed", expired["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(len(self.calls), 1)

    def test_capacity_refuses_new_lane_without_evicting_pending(self):
        self.cfg["max_sessions"] = 1
        self.prompt()
        self.action, self.disposition = "unassessed", "unassessed"
        self.command()
        with self.assertRaisesRegex(ValueError, "capacity"):
            hook.handle(dict(hook_event_name="SessionStart", cwd=str(self.root), session_id="other",
                             source="resume"), self.cfg, self.reviewer)
        restored = self.event("SessionStart", source="resume")
        self.assertIn(self.calls[0]["candidate_id"], restored["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(len(self.calls), 1)

    def test_denial_stop_once_resume_pending(self):
        self.prompt()
        self.action, self.disposition = "unassessed", "unassessed"
        result = self.command()
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.event("Stop", stop_hook_active=False)["decision"], "block")
        self.assertEqual(self.event("Stop", stop_hook_active=True), {})
        self.assertEqual(self.event("Stop", stop_hook_active=False), {})
        # A compact/resume must restore the unresolved judgment, but it must not
        # reset the Stop notification and create another Stop loop.
        self.assertIn("additionalContext", self.event("SessionStart", source="compact")["hookSpecificOutput"])
        self.assertEqual(self.event("Stop", stop_hook_active=False), {})

    def test_worker_inherits_unique_parent_request_context(self):
        self.prompt("Parent request: construct the bounded fixture.")
        self.lane_event("worker", "PreToolUse", tool_name="Bash", tool_use_id="worker-one",
                        tool_input={"command": self.command.__defaults__[0]})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["contract"], "Parent request: construct the bounded fixture.")
        self.assertEqual(self.calls[0]["current_prompt"], "Parent request: construct the bounded fixture.")
        self.assertTrue(self.lane_state("worker")["request_origin"].startswith("inherited:"))

    def test_inherited_context_refreshes_when_parent_prompt_changes(self):
        self.prompt("Parent request: first bounded fixture.")
        command = self.command.__defaults__[0]
        self.lane_event("worker", "PreToolUse", tool_name="Bash", tool_use_id="worker-one", tool_input={"command": command})
        self.prompt("Parent request: revised bounded fixture requirements.")
        self.lane_event("worker", "PreToolUse", tool_name="Bash", tool_use_id="worker-two", tool_input={"command": command})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1]["current_prompt"], "Parent request: revised bounded fixture requirements.")

    def test_cross_family_and_ambiguous_requests_are_unassessed(self):
        self.prompt("Root family request.")
        cross_family = self.lane_event("worker", "PreToolUse", session_id="other-session", tool_name="Bash",
                                       tool_use_id="cross", tool_input={"command": self.command.__defaults__[0]})
        self.assertEqual(cross_family["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse(self.calls)
        self.lane_event("other-parent", "UserPromptSubmit", prompt="A different direct request.")
        ambiguous = self.lane_event("worker", "PreToolUse", tool_name="Bash", tool_use_id="ambiguous",
                                    tool_input={"command": self.command.__defaults__[0]})
        self.assertEqual(ambiguous["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse(self.calls)
        self.assertEqual(self.lane_state("worker")["request_origin"], "ambiguous")

    def test_explicit_child_prompt_supersedes_inherited_context(self):
        self.prompt("Parent request: bounded fixture.")
        command = self.command.__defaults__[0]
        self.lane_event("worker", "PreToolUse", tool_name="Bash", tool_use_id="worker-one", tool_input={"command": command})
        self.lane_event("worker", "UserPromptSubmit", prompt="Child request: inspect only this fixture.")
        self.lane_event("worker", "PreToolUse", tool_name="Bash", tool_use_id="worker-two", tool_input={"command": command})
        self.prompt("Parent request: changed again.")
        self.lane_event("worker", "PreToolUse", tool_name="Bash", tool_use_id="worker-three", tool_input={"command": command})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1]["contract"], "Child request: inspect only this fixture.")
        self.assertEqual(self.calls[-1]["current_prompt"], "Child request: inspect only this fixture.")
        self.assertEqual(self.lane_state("worker")["request_origin"], "direct")

    def test_missing_contract_secret_and_bad_schema_never_approve(self):
        self.assertEqual(self.command()["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse(self.calls)
        self.prompt("Store token=ghp_examplecredential then continue")
        self.assertEqual(self.command()["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse(self.calls)
        self.prompt()
        self.disposition = "invented"
        result = self.command()
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("ghp_example", json.dumps(result))

    def test_child_and_excluded_scope_do_not_review(self):
        self.prompt()
        with patch.dict(os.environ, {"AGENT_RULES_NECESSITY_REVIEWER": "1"}):
            self.assertEqual(self.command()["hookSpecificOutput"]["permissionDecision"], "deny")
        self.cfg["excludes"] = [str(self.root)]
        self.assertEqual(self.command(), {})
        self.assertEqual(self.calls, [])

    def test_invalid_and_unsupported_are_not_safe(self):
        self.prompt()
        result = self.event("PreToolUse", tool_name="Bash", tool_use_id="bad", tool_input={"command": "unknown syntax", "shell": "unknown-shell"})
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertFalse(self.calls)

    def test_generated_script_and_content_change(self):
        self.prompt()
        script = self.root / "fixture"
        script.write_text("print('hello')")
        self.event("PostToolUse", tool_name="apply_patch", tool_use_id="write1",
                   tool_input={"command": "*** Begin Patch\n*** Add File: fixture\n+print('hello')\n*** End Patch"}, tool_response={"exit_code": 0})
        self.command("python3 fixture")
        self.assertEqual(len(self.calls), 1)
        script.write_text("print('changed')")
        self.command("python3 fixture")
        self.assertEqual(len(self.calls), 2)

    def test_two_concurrent_same_candidates_invoke_once(self):
        self.prompt()
        started, finish = threading.Event(), threading.Event()
        def blocking(request, cfg):
            started.set()
            finish.wait(2)
            return self.reviewer(request, cfg)
        payload = dict(hook_event_name="PreToolUse", cwd=str(self.root), session_id="root", turn_id="turn1", tool_name="Bash", tool_use_id="same", tool_input={"command": "python3 -c 'import subprocess; from pathlib import Path; Path(\"result\").write_text(\"pending\"); subprocess.run([\"true\"]); print(1)'"})
        errors = []
        def first():
            try:
                hook.handle(payload, self.cfg, blocking)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=first)
        thread.start()
        self.assertTrue(started.wait(2))
        try:
            second = hook.handle(payload, self.cfg, self.reviewer)
            self.assertEqual(second["hookSpecificOutput"]["permissionDecision"], "deny")
        finally:
            finish.set()
            thread.join(3)
        self.assertFalse(errors)
        self.assertEqual(len(self.calls), 1)

    def test_schema_candidate_and_enum(self):
        value = self.reviewer({"candidate_id": "one"}, {})
        review.validate(value, "one")
        with self.assertRaises(ValueError):
            review.validate(value, "two")

    def test_bounded_subprocess_timeout_and_output(self):
        with self.assertRaisesRegex(ValueError, "deadline"):
            review.bounded_run([sys.executable, "-c", "import time; time.sleep(5)"], "", cwd=self.root, env=os.environ.copy(), deadline=0.1, limit=100)
        with self.assertRaisesRegex(ValueError, "output limit"):
            review.bounded_run([sys.executable, "-c", "print('x'*10000)"], "", cwd=self.root, env=os.environ.copy(), deadline=2, limit=100)

    @unittest.skipUnless(os.environ.get("AGENT_RULES_NECESSITY_LIVE") == "1", "explicit limited Codex connection only")
    def test_live_reviewer_round_trip_not_native_hook_delivery(self):
        # One candidate and the existing review role; this does not execute the
        # candidate, trust hooks, or prove native hook loading/delivery.
        self.cfg.update(model="gpt-5.6-terra", effort="low", deadline_seconds=600, reviews_per_session=1)
        if os.environ.get("AGENT_RULES_NECESSITY_CODEX_EXECUTABLE"):
            self.cfg["codex_executable"] = os.environ["AGENT_RULES_NECESSITY_CODEX_EXECUTABLE"]
        self.prompt("Review a proposed one-off subprocess fixture. No existing fixture was found. The requested acceptance needs creating a disposable result file, running a child once, returning its result and cleanup. Judge the supplied candidate only; do not execute it.")
        payload = dict(hook_event_name="PreToolUse", cwd=str(self.root), session_id="root", turn_id="live",
                       tool_name="Bash", tool_use_id="live-one", tool_input={"command": "python3 -c 'import subprocess; from pathlib import Path; Path(\"result\").write_text(\"pending\"); subprocess.run([\"true\"], check=True); print(\"fixture complete\")'"})
        output = hook.handle(payload, self.cfg, review.review)
        db = sqlite3.connect(self.root / "state" / "necessity.sqlite3")
        record = json.loads(db.execute("SELECT result FROM candidates").fetchone()[0])
        db.close()
        evidence = {"kind": "direct-adapter-real-review-not-native-delivery", "model": self.cfg["model"],
                    "effort": self.cfg["effort"], "result": record, "hook_output": output}
        target = os.environ.get("AGENT_RULES_NECESSITY_LIVE_RESULT")
        if target:
            Path(target).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertIn(record["action"], {"continue", "revise"}, record)
        self.assertIn("candidate_id", record)
        self.assertIsNotNone(record["usage"], "usage unavailable, not zero")


if __name__ == "__main__":
    unittest.main()
