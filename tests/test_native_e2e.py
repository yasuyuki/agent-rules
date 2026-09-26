"""Negative controls for the structured native-result verifier (no model calls)."""
import json
import unittest

from native_e2e import SCENARIO, answer, decode_events, failure_category


class NativeResultTests(unittest.TestCase):
    def test_pair_scenario_contains_only_funded_vendors(self):
        self.assertEqual(SCENARIO["pair"], ("claude", "codex"))

    def test_failure_category_never_emits_raw_error_or_key(self):
        error = "authentication_error: invalid api key sk-ant-secret"
        self.assertEqual(failure_category("", error), "authentication")
        self.assertEqual(failure_category("", "unexpected private detail"), "unclassified")

    def test_terminal_result_only(self):
        prompt = '{"rule":"RULE_echoed","challenge":"fresh"}'
        lines = [
            {"type": "user", "message": {"content": prompt}},
            {"type": "result", "result": '{"challenge":"fresh"}', "is_error": False},
        ]
        text, success, tool = decode_events("claude", "\n".join(map(json.dumps, lines)))
        self.assertTrue(success)
        self.assertFalse(tool)
        self.assertFalse(answer(text, "fresh", "rule", "RULE_echoed"))

    def test_auth_error_is_not_negative_success(self):
        event = {"type": "result", "result": '{"challenge":"fresh"}', "is_error": True}
        text, success, _ = decode_events("claude", json.dumps(event))
        self.assertFalse(success)
        self.assertTrue(answer(text, "fresh", "rule", None))

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
