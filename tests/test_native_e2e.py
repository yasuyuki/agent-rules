"""Negative controls for the structured native-result verifier (no model calls)."""
import json
from pathlib import Path
import unittest

from native_e2e import (CLAUDE_RESULT_SCHEMA, SCENARIO, answer, command, decode_events,
                        negative_rule_issue, skill_answer_issue)


class NativeResultTests(unittest.TestCase):
    def test_pair_scenario_contains_only_funded_vendors(self):
        self.assertEqual(SCENARIO["pair"], ("claude", "codex"))

    def test_claude_prompt_precedes_variadic_allowed_tools(self):
        prompt = 'Return only JSON {"challenge":"fresh"}.'
        argv = command("claude", Path("/tmp/claude"), "claude-haiku-4-5-20251001",
                       Path("/tmp/consumer"), prompt)
        self.assertLess(argv.index(prompt), argv.index("--allowedTools"))
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]),
                         json.loads(CLAUDE_RESULT_SCHEMA))

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
