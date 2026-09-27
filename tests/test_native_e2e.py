"""Negative controls for the structured native-result verifier (no model calls)."""
import json
import io
import http.client
import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

from native_e2e import (SCENARIO, answer, claude_structure_diagnostics,
                        claude_terminal_issue,
                        codex_command_diagnostics, codex_tool_probe, codex_wire_metadata,
                        command, decode_events,
                        negative_rule_issue, skill_answer_issue)


class NativeResultTests(unittest.TestCase):
    def test_pair_scenario_contains_only_funded_vendors(self):
        self.assertEqual(SCENARIO["pair"], ("claude", "codex"))

    def test_claude_rule_probe_disallows_tools_and_requires_json(self):
        prompt = 'Return only JSON {"challenge":"fresh"}.'
        argv = command("claude", Path("/tmp/claude"), "claude-haiku-4-5-20251001",
                       Path("/tmp/consumer"), prompt)
        self.assertNotIn("--json-schema", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("exactly one compact JSON object", argv[argv.index("--append-system-prompt") + 1])

    def test_claude_skill_probe_keeps_tools_and_prompt_order(self):
        prompt = 'Use the probe skill.'
        argv = command("claude", Path("/tmp/claude"), "claude-haiku-4-5-20251001",
                       Path("/tmp/consumer"), prompt, "proof.py")
        self.assertNotIn("--json-schema", argv)
        self.assertLess(argv.index(prompt), argv.index("--allowedTools"))
        self.assertIn("Skill,Read,Bash", argv)

    def test_codex_skill_probe_uses_unattended_default_effort(self):
        argv = command("codex", Path("/tmp/codex"), "gpt-6-luna",
                       Path("/tmp/consumer"), "Use the skill.", "proof.py")
        self.assertEqual(argv[argv.index("--ask-for-approval") + 1], "never")
        self.assertLess(argv.index("--ask-for-approval"), argv.index("exec"))
        self.assertNotIn("--skip-git-repo-check", argv)
        self.assertNotIn('model_reasoning_effort="none"', argv)
        self.assertNotIn('model_reasoning_effort="none"', command(
            "codex", Path("/tmp/codex"), "gpt-6-luna", Path("/tmp/consumer"), "Rule probe."))

    def test_codex_wire_relay_keeps_only_safe_tool_metadata(self):
        secret = "secret-test-token"
        payload = {"model": "gpt-6-luna", "stream": True,
                   "input": "private prompt", "tools": [
                       {"type": "function", "name": "exec_command", "description": "private tool body"}]}
        event = b'event: response.output_item.done\ndata: {"type":"response.output_item.done","item":{"type":"function_call","name":"exec_command","call_id":"call-1","arguments":"{\\"cmd\\":\\"python3 private output\\"}"}}\n\n'

        class FakeUpstream:
            status = 200
            headers = {"Content-Type": "text/event-stream"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def __iter__(self):
                return iter(io.BytesIO(event))

        class FakeOpener:
            def open(self, request, timeout):
                self_request = json.loads(request.data)
                assert self_request["input"] == "private prompt"
                assert request.get_header("Authorization") == "Bearer " + secret
                return FakeUpstream()

        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}), \
                patch("native_e2e.urllib.request.build_opener", return_value=FakeOpener()):
            with codex_wire_metadata() as (base_url, calls):
                parsed = urlsplit(base_url)
                connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                connection.request("POST", "/v1/responses", body=json.dumps(payload),
                                   headers={"Authorization": "Bearer " + secret,
                                            "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.read(), event)
                connection.close()
        self.assertEqual(calls[0]["tool_count"], 1)
        self.assertEqual(calls[0]["tools"], [("function", "exec_command")])
        self.assertEqual(calls[0]["response_tool_names"], ["exec_command"])
        self.assertEqual(calls[0]["response_call_shapes"], [{
            "name": "exec_command", "call_id_present": True,
            "arguments_json_object": True, "argument_keys": ["cmd"],
            "cmd_is_string": True, "cmd_mentions_python3": True}])
        self.assertTrue(calls[0]["auth_matches_test_key"])
        for sensitive in (secret, "private prompt", "private tool body", "private output"):
            self.assertNotIn(sensitive, json.dumps(calls))
        argv = command("codex", Path("/tmp/codex"), "gpt-6-luna",
                       Path("/tmp/consumer"), "probe", api_base_url=base_url)
        self.assertIn(f'openai_base_url="{base_url}"', argv)

    def test_codex_wire_relay_forwards_response_child_without_path_in_artifact(self):
        secret = "secret-test-token"

        class FakeUpstream:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self, _size):
                if not hasattr(self, "sent"):
                    self.sent = True
                    return b'{"private":"response"}'
                return b""

        class FakeOpener:
            def open(self, request, timeout):
                assert request.full_url.endswith(("/v1/responses/secret-response-id", "/v1/models"))
                return FakeUpstream()

        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}), \
                patch("native_e2e.urllib.request.build_opener", return_value=FakeOpener()):
            with codex_wire_metadata() as (base_url, calls):
                parsed = urlsplit(base_url)
                connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                connection.request("GET", "/v1/responses/secret-response-id",
                                   headers={"Authorization": "Bearer " + secret})
                response = connection.getresponse()
                self.assertEqual(response.read(), b'{"private":"response"}')
                connection.close()
                connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
                connection.request("GET", "/v1/models",
                                   headers={"Authorization": "Bearer " + secret})
                response = connection.getresponse()
                self.assertEqual(response.read(), b'{"private":"response"}')
                connection.close()
        self.assertEqual(calls, [
            {"auxiliary_method": "GET", "path_kind": "responses",
             "known_resource": "responses", "response_http_status": 200},
            {"auxiliary_method": "GET", "path_kind": "models",
             "known_resource": "models", "response_http_status": 200}])

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

    def test_claude_structured_output_tool_is_not_rule_probe_tool_use(self):
        lines = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use",
                "id": "structured", "name": "StructuredOutput", "input": {"challenge": "fresh"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result",
                "tool_use_id": "structured"}]}},
            {"type": "result", "subtype": "success", "structured_output": {"challenge": "fresh"}},
        ]
        text, success, tool = decode_events("claude", "\n".join(map(json.dumps, lines)))
        self.assertTrue(success)
        self.assertFalse(tool)
        self.assertIsNone(negative_rule_issue(text, "fresh", tool))

    def test_claude_completed_structured_tool_is_not_terminal_fallback(self):
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use",
                "id": "structured", "name": "StructuredOutput", "input": {"challenge": "fresh"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result",
                "tool_use_id": "structured", "is_error": False}]}},
            {"type": "result", "subtype": "success", "result": "not JSON"},
        ]
        text, success, used_tool = decode_events("claude", "\n".join(map(json.dumps, events)))
        self.assertTrue(success)
        self.assertFalse(used_tool)
        self.assertEqual(negative_rule_issue(text, "fresh", used_tool), "terminal response was not JSON")
        events[1]["message"]["content"][0]["is_error"] = True
        text, _, _ = decode_events("claude", "\n".join(map(json.dumps, events)))
        self.assertEqual(negative_rule_issue(text, "fresh", False), "terminal response was not JSON")

    def test_claude_shape_diagnostics_do_not_retain_output(self):
        events = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "one",
                "name": "StructuredOutput", "input": {"challenge": "SECRET"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "one"}]}},
            {"type": "result", "subtype": "success", "result": "SECRET not JSON"},
        ]
        diagnostics = claude_structure_diagnostics("\n".join(map(json.dumps, events)))
        self.assertFalse(diagnostics["claude_terminal_json"])
        self.assertNotIn("SECRET", str(diagnostics))

    def test_auth_error_is_not_negative_success(self):
        event = {"type": "result", "subtype": "error_max_structured_output_retries",
                 "structured_output": {"challenge": "fresh"}, "is_error": True}
        text, success, _ = decode_events("claude", json.dumps(event))
        self.assertFalse(success)
        self.assertTrue(answer(text, "fresh", "rule", None))

    def test_claude_missing_structured_result_uses_only_terminal_text(self):
        event = {"type": "result", "subtype": "success", "result": '{"challenge":"fresh"}'}
        text, success, _ = decode_events("claude", json.dumps(event))
        self.assertEqual(text, '{"challenge":"fresh"}')
        self.assertTrue(success)
        self.assertTrue(answer(text, "fresh", "rule", None))
        event["result"] = "free text SECRET"
        text, success, _ = decode_events("claude", json.dumps(event))
        self.assertTrue(success)
        self.assertEqual(negative_rule_issue(text, "fresh", False), "terminal response was not JSON")

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
        self.assertIsNone(negative_rule_issue('```json\n{"challenge":"fresh"}\n```', "fresh", False))
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
                          "codex_item_types": ["agent_message", "command_execution"],
                          "codex_error_event_count": 0,
                          "codex_error_signals": [],
                          "codex_error_keyword_sequences": [],
                          "codex_stderr_signals": [],
                          "codex_file_change_started": False,
                          "codex_file_change_completed": False,
                          "codex_file_change_statuses": [],
                          "codex_file_change_probe_path": False,
                          "codex_proof_command_attempted": True,
                          "codex_proof_command_failed": False,
                          "codex_proof_exit_codes": [0],
                          "codex_proof_error_class": "none",
                          "codex_proof_command_shape": {"python3": True, "skill_path": False,
                                                        "challenge_arg": False, "output_arg": False},
                          "codex_other_tool_attempted": False,
                          "codex_turn_completed": True,
                          "codex_turn_failed": False,
                          "codex_terminal_json": True,
                          "codex_terminal_mentions_tool": False,
                          "codex_terminal_refusal_hint": False})

    def test_codex_failed_command_diagnostics_hide_command(self):
        events = [{"type": "item.completed", "item": {"type": "command_execution",
                   "command": "python3 proof.py SECRET", "exit_code": 2, "status": "failed",
                   "aggregated_output": "python3: can't open file SECRET: No such file or directory"}}]
        result = codex_command_diagnostics(json.dumps(events[0]), "proof.py")
        self.assertTrue(result["codex_proof_command_failed"])
        self.assertEqual(result["codex_proof_exit_codes"], [2])
        self.assertEqual(result["codex_proof_error_class"], "missing_path")

    def test_codex_error_words_exclude_secret_and_url(self):
        event = {"type": "error", "message": "sse stream error for sk-secret https://private.example:502 before completion"}
        result = codex_command_diagnostics(json.dumps(event), "proof.py")
        self.assertEqual(result["codex_error_keyword_sequences"],
                         [["sse", "stream", "error", "502", "before", "completion"]])
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("SECRET", str(result))

    def test_codex_file_change_diagnostics_hide_paths_and_content(self):
        event = {"type": "item.completed", "item": {"type": "file_change",
                 "status": "failed", "changes": [{"path": "/tmp/SECRET/probe.txt",
                                                 "kind": "add", "diff": "SECRET"}]}}
        result = codex_command_diagnostics(json.dumps(event), "probe.txt")
        self.assertTrue(result["codex_file_change_completed"])
        self.assertEqual(result["codex_file_change_statuses"], ["failed"])
        self.assertTrue(result["codex_file_change_probe_path"])
        self.assertNotIn("SECRET", str(result))

    def test_codex_preplacement_probe_needs_command_completion_and_exact_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)

            def native(_vendor, _cli, _model, _workspace, _user, _home, prompt,
                       proof_name=None, diagnostics=None, api_base_url=None):
                challenge = re.search(r"exactly ([0-9a-f]{32})", prompt).group(1)
                (workspace / proof_name).write_text(challenge + "\n")
                diagnostics.update(codex_proof_command_attempted=True,
                                   codex_proof_command_failed=False,
                                   codex_proof_command_shape={"python3": True},
                                   codex_proof_exit_codes=[0], codex_turn_completed=True)
                return "done", True

            with patch("native_e2e.run_native", side_effect=native):
                result = codex_tool_probe(Path("/codex"), "gpt-6-luna", workspace,
                                          "native-e2e", Path("/home/native-e2e"))
            self.assertTrue(result["passed"])
            self.assertNotIn("challenge", str(result))

            def no_tool(*args, **kwargs):
                native(*args, **kwargs)
                kwargs["diagnostics"]["codex_proof_command_attempted"] = False
                return "done", False

            with patch("native_e2e.run_native", side_effect=no_tool):
                result = codex_tool_probe(Path("/codex"), "gpt-6-luna", workspace,
                                          "native-e2e", Path("/home/native-e2e"))
            self.assertFalse(result["passed"])

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
