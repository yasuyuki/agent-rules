"""Negative controls for the structured native-result verifier (no model calls)."""
import json
from pathlib import Path
import unittest

from native_e2e import (CLAUDE_RESULT_SCHEMA, SCENARIO, answer, claude_terminal_issue,
                        codex_command_diagnostics, command, decode_events,
                        negative_rule_issue, skill_answer_issue)


class NativeResultTests(unittest.TestCase):
    def test_pair_scenario_contains_only_funded_vendors(self):
        self.assertEqual(SCENARIO["pair"], ("claude", "codex"))

    def test_claude_rule_probe_uses_structured_output_without_tools(self):
        prompt = 'Return only JSON {"challenge":"fresh"}.'
        argv = command("claude", Path("/tmp/claude"), "claude-haiku-4-5-20251001",
                       Path("/tmp/consumer"), prompt)
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]),
                         json.loads(CLAUDE_RESULT_SCHEMA))
        self.assertEqual(argv[argv.index("--tools") + 1], "")

    def test_claude_skill_probe_keeps_tools_and_prompt_order(self):
        prompt = 'Use the probe skill.'
        argv = command("claude", Path("/tmp/claude"), "claude-haiku-4-5-20251001",
                       Path("/tmp/consumer"), prompt, "proof.py")
        self.assertNotIn("--json-schema", argv)
        self.assertLess(argv.index(prompt), argv.index("--allowedTools"))
        self.assertIn("Skill,Read,Bash", argv)

    def test_terminal_result_only(self):
        prompt = '{"rule":"RULE_echoed","challenge":"fresh"}'
        lines = [
            {"type": "user", "message": {"content": prompt}},
            {"type": "result", "subtype": "success", "structured_output": {"challenge": "fresh"},
             "result": "unstructured SECRET", "is_error": False},
        ]
        text, success, tool = decode_events("claude", "\n".join(map(json.dumps, lines)))
        self.assertTrue(success)
        self.assertFalse(tool)
        self.assertFalse(answer(text, "fresh", "rule", "RULE_echoed"))

    def test_auth_error_is_not_negative_success(self):
        event = {"type": "result", "subtype": "error_max_structured_output_retries",
                 "structured_output": {"challenge": "fresh"}, "is_error": True}
        text, success, _ = decode_events("claude", json.dumps(event))
        self.assertFalse(success)
        self.assertTrue(answer(text, "fresh", "rule", None))

    def test_claude_missing_structured_result_does_not_use_free_text(self):
        event = {"type": "result", "subtype": "success", "result": '{"challenge":"fresh"}'}
        text, success, _ = decode_events("claude", json.dumps(event))
        self.assertEqual(text, "")
        self.assertFalse(success)
        self.assertFalse(answer(text, "fresh", "rule", None))
        self.assertEqual(claude_terminal_issue(json.dumps(event)), "structured output missing")

    def test_claude_terminal_failure_categories_hide_content(self):
        event = {"type": "result", "subtype": "error_max_structured_output_retries",
                 "result": "SECRET"}
        issue = claude_terminal_issue(json.dumps(event))
        self.assertEqual(issue, "structured output retry limit")
        self.assertNotIn("SECRET", issue)

    def test_claude_skill_result_uses_terminal_text_and_tool_evidence(self):
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "one",
                "name": "Bash", "input": {"command": "python3 proof.py"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "one"}]}},
            {"type": "result", "subtype": "success",
             "result": '{"challenge":"fresh","skill":"SKILL_good"}'},
        ]
        text, success, used_tool = decode_events("claude", "\n".join(map(json.dumps, events)), "proof.py")
        self.assertTrue(success)
        self.assertTrue(used_tool)
        self.assertTrue(answer(text, "fresh", "skill", "SKILL_good"))

    def test_negative_rule_diagnostics_do_not_expose_response(self):
        self.assertIsNone(negative_rule_issue('{"challenge":"fresh"}', "fresh", False))
        cases = (
            ('not JSON SECRET', "terminal response was not JSON"),
            ('[]', "terminal response was not an object"),
            ('{"challenge":"stale SECRET"}', "challenge did not match"),
            ('{"challenge":"fresh","rule":"SECRET"}', "rule field was present"),
        )
        for response, expected in cases:
            self.assertEqual(negative_rule_issue(response, "fresh", False), expected)
            self.assertNotIn("SECRET", expected)
        self.assertEqual(negative_rule_issue('{"challenge":"fresh"}', "fresh", True),
                         "tool ran during rule probe")

    def test_skill_diagnostics_do_not_expose_response(self):
        self.assertIsNone(skill_answer_issue('{"challenge":"fresh","skill":"SKILL_good"}',
                                             "fresh", "SKILL_good"))
        cases = (
            ('not JSON SECRET', "terminal response was not JSON"),
            ('[]', "terminal response was not an object"),
            ('{"challenge":"stale SECRET","skill":"SKILL_good"}', "challenge did not match"),
            ('{"challenge":"fresh"}', "skill field was absent"),
            ('{"challenge":"fresh","skill":"SECRET"}', "skill field did not match"),
        )
        for response, expected in cases:
            self.assertEqual(skill_answer_issue(response, "fresh", "SKILL_good"), expected)
            self.assertNotIn("SECRET", expected)

    def test_stale_challenge_and_missing_terminal(self):
        self.assertFalse(answer('{"challenge":"old","rule":"RULE_x"}', "fresh", "rule", "RULE_x"))
        with self.assertRaises(ValueError):
            decode_events("codex", json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": '{"challenge":"fresh"}'}}))

    def test_codex_tool_and_terminal_are_distinct(self):
        events = [
            {"type": "item.completed", "item": {"type": "command_execution", "command": "python3 proof.py", "exit_code": 0}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": '{"challenge":"fresh"}'}},
            {"type": "turn.completed"},
        ]
        text, success, tool = decode_events("codex", "\n".join(map(json.dumps, events)))
        self.assertEqual(text, '{"challenge":"fresh"}')
        self.assertTrue(success)
        self.assertTrue(tool)
        self.assertFalse(decode_events("codex", "\n".join(map(json.dumps, events)), "other.py")[2])
        self.assertEqual(codex_command_diagnostics("\n".join(map(json.dumps, events)), "proof.py"),
                         {"codex_command_attempted": True,
                          "codex_proof_command_attempted": True,
                          "codex_proof_command_failed": False})

    def test_codex_failed_command_diagnostics_hide_command(self):
        events = [{"type": "item.completed", "item": {"type": "command_execution",
                   "command": "python3 proof.py SECRET", "exit_code": 1, "status": "failed"}}]
        result = codex_command_diagnostics(json.dumps(events[0]), "proof.py")
        self.assertTrue(result["codex_proof_command_failed"])
        self.assertNotIn("SECRET", str(result))

    def test_agy_requires_successful_terminal_and_matching_tool(self):
        events = [
            {"event": "step_update", "step_update": {"step_type": "tool", "state": "DONE",
                "tool_info": {"name": "run_command", "parameters": {"CommandLine": "python3 proof.py"}}}},
            {"event": "result", "result": {"status": "SUCCESS", "response": '{"challenge":"fresh"}'}},
        ]
        text, success, tool = decode_events("agy", "\n".join(map(json.dumps, events)), "proof.py")
        self.assertEqual(text, '{"challenge":"fresh"}')
        self.assertTrue(success)
        self.assertTrue(tool)


if __name__ == "__main__":
    unittest.main()
