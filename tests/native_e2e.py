"""Authenticated native probes for an isolated Linux Actions VM.

The controller owns the fixture and expected values. Vendor processes run as a
different, unprivileged local user and can only see the consumer workspace.
This is intentionally separate from the authentication-free package gate.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit


FIXTURE = Path(__file__).parent / "fixtures/native-e2e"
TARGET = {"claude": "claudecode", "codex": "codexcli", "agy": "codexcli", "cursor": "cursor"}
SECRET = {"claude": "ANTHROPIC_API_KEY", "codex": "OPENAI_API_KEY", "agy": "GEMINI_API_KEY", "cursor": "CURSOR_API_KEY"}
SCENARIO = {"pair": ("claude", "codex"), "all": tuple(TARGET)}


def _safe_wire_name(value: object) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[a-z_]{1,48}", value) else "other"


@contextmanager
def codex_wire_metadata():
    """Forward a real authenticated Responses call; retain only fixed-shape metadata."""
    calls: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass  # Never log a URL, header, request body, or model output.

        def do_GET(self):
            self._forward_auxiliary("GET")

        def _forward_auxiliary(self, method: str):
            path = urlsplit(self.path).path
            resource = path.split("/")[2] if len(path.split("/")) > 2 else ""
            path_kind = ("responses" if path == "/v1/responses" or path.startswith("/v1/responses/")
                         else "models" if path == "/v1/models" or path.startswith("/v1/models/")
                         else "other")
            metadata = {"auxiliary_method": method, "path_kind": path_kind,
                        "known_resource": resource if resource in ("responses", "models", "files", "threads") else "other",
                        "response_http_status": None}
            calls.append(metadata)
            if path_kind == "other":
                metadata["response_http_status"] = 404
                self.send_error(404)
                return
            if not hmac.compare_digest(self.headers.get("Authorization", ""),
                                       "Bearer " + os.environ.get("OPENAI_API_KEY", "")):
                metadata["response_http_status"] = 403
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 2_000_000:
                    raise ValueError("invalid auxiliary request length")
                body = self.rfile.read(length) if length else None
                headers = {key: value for key, value in self.headers.items()
                           if key.lower() not in ("host", "content-length", "accept-encoding",
                                                   "connection", "transfer-encoding")}
                headers["Accept-Encoding"] = "identity"
                request = urllib.request.Request("https://api.openai.com" + self.path,
                                                 data=body, headers=headers, method=method)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=150) as upstream:
                    metadata["response_http_status"] = upstream.status
                    self.send_response(upstream.status)
                    self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    while chunk := upstream.read(8192):
                        self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
                    self.wfile.write(b"0\r\n\r\n")
            except urllib.error.HTTPError as exc:
                metadata["response_http_status"] = exc.code
                body = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                metadata["relay_error_class"] = type(exc).__name__
                self.send_error(502)

        def do_POST(self):
            if self.path != "/v1/responses":
                self._forward_auxiliary("POST")
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
                if length <= 0 or length > 2_000_000:
                    raise ValueError("invalid request length")
                body = self.rfile.read(length)
                request = json.loads(body)
                tools = request.get("tools", [])
                if not isinstance(tools, list):
                    raise ValueError("invalid tools")
                authorized = hmac.compare_digest(
                    self.headers.get("Authorization", ""),
                    "Bearer " + os.environ.get("OPENAI_API_KEY", ""))
                metadata = {
                    "auth_matches_test_key": authorized,
                    "model_is_pinned": request.get("model") == "gpt-6-luna",
                    "tool_count": len(tools),
                    "tools": sorted({(_safe_wire_name(item.get("type")),
                                      _safe_wire_name(item.get("name")))
                                     for item in tools if isinstance(item, dict)}),
                    "tool_choice": _safe_wire_name(request.get("tool_choice")),
                    "stream": request.get("stream") is True,
                    "response_http_status": None,
                    "response_event_types": [],
                    "response_item_types": [],
                    "response_tool_names": [],
                    "response_call_shapes": [],
                    "response_statuses": [],
                    "upstream_done_marker": False,
                    "relay_complete": False,
                }
                calls.append(metadata)
                if not authorized:
                    metadata["response_http_status"] = 403
                    self.send_error(403)
                    return
                headers = {key: value for key, value in self.headers.items()
                           if key.lower() not in ("host", "content-length", "accept-encoding",
                                                   "connection", "transfer-encoding")}
                headers["Accept-Encoding"] = "identity"
                upstream_request = urllib.request.Request(
                    "https://api.openai.com/v1/responses", data=body, headers=headers, method="POST")
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(upstream_request, timeout=150) as upstream:
                    metadata["response_http_status"] = upstream.status
                    self.send_response(upstream.status)
                    self.send_header("Content-Type", upstream.headers.get("Content-Type", "text/event-stream"))
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    event_types, item_types, tool_names = set(), set(), set()
                    call_shapes, response_statuses = [], set()
                    try:
                        for line in upstream:
                            if line.strip() == b"data: [DONE]":
                                metadata["upstream_done_marker"] = True
                            if line.startswith(b"event: "):
                                event_types.add(_safe_wire_name(line[7:].strip().decode("ascii", "ignore").replace(".", "_")))
                            elif line.startswith(b"data: "):
                                try:
                                    event = json.loads(line[6:])
                                    if event.get("type") in ("response.completed", "response.incomplete", "response.failed"):
                                        response = event.get("response", {})
                                        if isinstance(response, dict):
                                            response_statuses.add(_safe_wire_name(response.get("status")))
                                    item = event.get("item", {})
                                    if isinstance(item, dict):
                                        item_types.add(_safe_wire_name(item.get("type")))
                                        if item.get("type") in ("function_call", "custom_tool_call"):
                                            tool_names.add(_safe_wire_name(item.get("name")))
                                            if event.get("type") == "response.output_item.done":
                                                arguments = item.get("arguments")
                                                try:
                                                    parsed = json.loads(arguments)
                                                except (TypeError, ValueError):
                                                    parsed = None
                                                call_shapes.append({
                                                    "name": _safe_wire_name(item.get("name")),
                                                    "call_id_present": isinstance(item.get("call_id"), str),
                                                    "arguments_json_object": isinstance(parsed, dict),
                                                    "argument_keys": sorted(_safe_wire_name(key)
                                                                            for key in parsed) if isinstance(parsed, dict) else [],
                                                    "cmd_is_string": isinstance(parsed.get("cmd"), str)
                                                    if isinstance(parsed, dict) else False,
                                                    "cmd_mentions_python3": "python3" in parsed.get("cmd", "")
                                                    if isinstance(parsed, dict) and isinstance(parsed.get("cmd"), str)
                                                    else False,
                                                })
                                except (ValueError, TypeError):
                                    pass
                            self.wfile.write(f"{len(line):x}\r\n".encode("ascii") + line + b"\r\n")
                        self.wfile.write(b"0\r\n\r\n")
                        metadata["relay_complete"] = True
                    finally:
                        metadata["response_event_types"] = sorted(event_types)
                        metadata["response_item_types"] = sorted(item_types)
                        metadata["response_tool_names"] = sorted(tool_names)
                        metadata["response_call_shapes"] = call_shapes
                        metadata["response_statuses"] = sorted(response_statuses)
            except urllib.error.HTTPError as exc:
                if calls:
                    calls[-1]["response_http_status"] = exc.code
                try:
                    body = exc.read()
                    self.send_response(exc.code)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass
            except Exception as exc:
                # The exception can contain a request URL or headers. Keep only its class.
                calls.append({"relay_error_class": type(exc).__name__})
                try:
                    self.send_error(502)
                except OSError:
                    pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class EvidenceUnavailable(RuntimeError):
    """The native process ran, but did not expose required structured evidence."""


def decode_events(vendor: str, stdout: str, proof_name: str | None = None) -> tuple[str, bool, bool]:
    """Return terminal text, terminal success, completed tool evidence.

    Never search raw output for a nonce: echoed prompts, intermediate reasoning
    and errors are not evidence of a successful native invocation.
    """
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    terminal = []
    tools = False
    if vendor == "claude":
        proof_ids = set()
        result_events = []
        for event in events:
            if event.get("type") == "result":
                result_events.append(event)
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if (isinstance(block, dict) and block.get("type") == "tool_use"
                            and block.get("name") != "StructuredOutput"
                            and (proof_name is None or (block.get("name") == "Bash"
                                 and proof_name in str(block.get("input", {}))))):
                        proof_ids.add(block.get("id"))
            if event.get("type") == "user":
                for block in event.get("message", {}).get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_result" and not block.get("is_error"):
                        if block.get("tool_use_id") in proof_ids:
                            tools = True
        if len(result_events) == 1:
            result_event = result_events[0]
            structured = result_event.get("structured_output")
            if proof_name is None and isinstance(structured, dict):
                text = json.dumps(structured)
            else:
                text = result_event.get("result", "")
            terminal.append((text, result_event.get("subtype") == "success"
                             and not result_event.get("is_error", False)))
    elif vendor == "codex":
        messages = []
        completed = False
        for event in events:
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    messages.append(item.get("text", ""))
                if (item.get("type") == "command_execution" and item.get("exit_code") == 0
                        and (proof_name is None or proof_name in item.get("command", ""))):
                    tools = True
            if event.get("type") == "turn.completed":
                completed = True
        if completed and messages:
            terminal.append((messages[-1], True))
    elif vendor == "agy":
        for event in events:
            if event.get("event") == "result":
                result = event.get("result", {})
                terminal.append((result.get("response", ""), result.get("status") == "SUCCESS"))
            if event.get("event") == "step_update":
                step = event.get("step_update", {})
                info = step.get("tool_info", {})
                if (step.get("step_type") == "tool" and step.get("state") == "DONE"
                        and not info.get("error") and (proof_name is None or proof_name in str(info.get("parameters", {})))):
                    tools = True
    elif vendor == "cursor":
        for event in events:
            if event.get("type") == "result":
                terminal.append((event.get("result", ""), event.get("subtype") == "success" and not event.get("is_error", False)))
            if (event.get("type") == "tool_call" and event.get("subtype") == "completed"
                    and (proof_name is None or proof_name in str(event.get("tool_call", {})))):
                tools = True
    else:
        raise ValueError(vendor)
    if len(terminal) != 1 or not isinstance(terminal[0][0], str):
        raise ValueError("missing or multiple terminal results")
    return terminal[0][0], terminal[0][1], tools


def terminal_json(text: str):
    """Parse an entire JSON reply, optionally enclosed by one Markdown fence."""
    lines = text.strip().splitlines()
    if len(lines) >= 3 and lines[0].lower() in ("```json", "```") and lines[-1] == "```":
        text = "\n".join(lines[1:-1])
    return json.loads(text.strip())


def answer(text: str, challenge: str, field: str, expected: str | None) -> bool:
    try:
        value = terminal_json(text)
    except (ValueError, TypeError):
        return False
    if not isinstance(value, dict) or value.get("challenge") != challenge:
        return False
    return value.get(field) == expected if expected is not None else field not in value


def negative_rule_issue(text: str, challenge: str, used_tool: bool) -> str | None:
    """Describe a failed negative probe without exposing model output or nonces."""
    try:
        value = terminal_json(text)
    except (ValueError, TypeError):
        return "terminal response was not JSON"
    if not isinstance(value, dict):
        return "terminal response was not an object"
    if value.get("challenge") != challenge:
        return "challenge did not match"
    if "rule" in value:
        return "rule field was present"
    if used_tool:
        return "tool ran during rule probe"
    return None


def skill_answer_issue(text: str, challenge: str, expected: str) -> str | None:
    """Categorize terminal skill evidence without retaining its contents."""
    try:
        value = terminal_json(text)
    except (ValueError, TypeError):
        return "terminal response was not JSON"
    if not isinstance(value, dict):
        return "terminal response was not an object"
    if value.get("challenge") != challenge:
        return "challenge did not match"
    if "skill" not in value:
        return "skill field was absent"
    if value["skill"] != expected:
        return "skill field did not match"
    return None


def claude_terminal_issue(stdout: str) -> str:
    """Summarize the terminal event without including model text or API errors."""
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    results = [event for event in events if event.get("type") == "result"]
    if len(results) != 1:
        return "missing or multiple terminal results"
    result = results[0]
    if result.get("subtype") == "error_max_structured_output_retries":
        return "structured output retry limit"
    return "terminal event failure"


def claude_structure_diagnostics(stdout: str) -> dict[str, bool]:
    """Retain only shape evidence when the rule result is not machine-readable."""
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    results = [event for event in events if event.get("type") == "result"]
    raw = results[0].get("result", "") if len(results) == 1 else ""
    try:
        is_json = isinstance(json.loads(raw), dict)
    except (TypeError, ValueError):
        is_json = False
    return {"claude_terminal_json": is_json,
            "claude_terminal_empty": not bool(raw),
            "claude_terminal_fenced": (isinstance(raw, str) and raw.strip().startswith("```")
                                       and raw.strip().endswith("```")),
            "claude_terminal_mentions_challenge": isinstance(raw, str) and "challenge" in raw.lower()}


def codex_command_diagnostics(stdout: str, proof_name: str, stderr: str = "") -> dict[str, object]:
    """Report command activity without retaining commands or their output."""
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    items = [event.get("item", {}) for event in events
             if event.get("type") in ("item.started", "item.completed")]
    commands = [item for item in items if item.get("type") == "command_execution"]
    file_changes = [(event.get("type"), event.get("item", {})) for event in events
                    if event.get("type") in ("item.started", "item.completed")
                    and event.get("item", {}).get("type") == "file_change"]
    proof_commands = [item for item in commands if proof_name in str(item.get("command", ""))]
    completed_proof = [item for item in proof_commands if isinstance(item.get("exit_code"), int)]
    command_text = "\n".join(str(item.get("command", "")) for item in proof_commands)
    output_text = "\n".join(str(item.get("aggregated_output", "")) for item in completed_proof).lower()
    if "permission denied" in output_text or "operation not permitted" in output_text:
        proof_error = "permission"
    elif any(term in output_text for term in ("no such file or directory", "can't open file", "not found")):
        proof_error = "missing_path"
    elif "traceback" in output_text:
        proof_error = "python_error"
    elif "usage:" in output_text or "unrecognized arguments" in output_text:
        proof_error = "arguments"
    else:
        proof_error = "other" if any(item.get("exit_code") != 0 for item in completed_proof) else "none"
    messages = [item.get("text", "") for item in items if item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)]
    terminal = messages[-1] if messages else ""
    errors = [event.get("message", "") for event in events if event.get("type") == "error"]
    error_text = " ".join(value for value in errors if isinstance(value, str)).lower()
    stderr_text = stderr.lower()
    signals = ("tool", "function", "parse", "decode", "invalid", "schema", "sandbox",
               "permission", "network", "connection", "stream", "http", "missing",
               "unsupported", "timeout", "failed", "call", "api", "response", "request")
    diagnostic_words = set(signals) | {"error", "sse", "read", "reading", "terminated",
                                      "disconnected", "before", "completion", "eof", "end",
                                      "body", "closed", "status", "retry", "retrying",
                                      "unexpected", "200", "400", "401", "403", "429", "500", "502"}
    error_keyword_sequences = [
        [word for word in re.findall(r"[a-z]+|[0-9]+", value.lower())
         if word in diagnostic_words][:20]
        for value in errors if isinstance(value, str)]
    item_types = {item.get("type") for item in items}
    safe_types = sorted({value if isinstance(value, str) and
                         re.fullmatch(r"[a-z_]{1,40}", value) else "other"
                         for value in item_types})
    try:
        terminal_is_json = isinstance(terminal_json(terminal), dict)
    except (TypeError, ValueError):
        terminal_is_json = False
    return {"codex_command_attempted": bool(commands),
            "codex_item_types": safe_types,
            "codex_error_event_count": len(errors),
            "codex_error_signals": sorted(signal for signal in signals if signal in error_text),
            "codex_error_keyword_sequences": error_keyword_sequences,
            "codex_stderr_signals": sorted(signal for signal in signals if signal in stderr_text),
            "codex_file_change_started": any(phase == "item.started" for phase, _ in file_changes),
            "codex_file_change_completed": any(phase == "item.completed" for phase, _ in file_changes),
            "codex_file_change_statuses": sorted({
                item.get("status") if item.get("status") in ("completed", "failed", "in_progress")
                else "other" for _, item in file_changes}),
            "codex_file_change_probe_path": any(
                proof_name == Path(change.get("path", "")).name
                for _, item in file_changes for change in item.get("changes", [])
                if isinstance(change, dict) and isinstance(change.get("path"), str)),
            "codex_proof_command_attempted": bool(proof_commands),
            "codex_proof_command_failed": any(
                item.get("status") == "failed" or
                (isinstance(item.get("exit_code"), int) and item["exit_code"] != 0)
                for item in proof_commands),
            "codex_proof_exit_codes": sorted({item["exit_code"] for item in completed_proof}),
            "codex_proof_error_class": proof_error,
            "codex_proof_command_shape": {
                "python3": "python3" in command_text,
                "skill_path": ".agents/skills/" in command_text,
                "challenge_arg": "--challenge" in command_text,
                "output_arg": "--output" in command_text},
            "codex_other_tool_attempted": any(item.get("type") in
                ("mcp_tool_call", "dynamic_tool_call", "web_search") for item in items),
            "codex_turn_completed": any(event.get("type") == "turn.completed" for event in events),
            "codex_turn_failed": any(event.get("type") == "turn.failed" for event in events),
            "codex_terminal_json": terminal_is_json,
            "codex_terminal_mentions_tool": "tool" in terminal.lower(),
            "codex_terminal_refusal_hint": any(term in terminal.lower() for term in
                ("cannot", "can't", "unable", "not available", "don't have access"))}


def command(vendor: str, cli: Path, model: str, workspace: Path, prompt: str,
            proof_name: str | None = None, api_base_url: str | None = None) -> list[str]:
    if vendor == "claude":
        base = [str(cli), "-p", "--output-format", "stream-json", "--verbose", "--model", model,
                "--max-turns", "5"]
        if proof_name is None:
            return [*base, "--append-system-prompt",
                    "For a rule probe, reply with exactly one compact JSON object and no other text. "
                    "Never use tools for a rule probe.", prompt, "--tools", ""]
        return [*base, prompt, "--tools", "Skill,Read,Bash",
                "--allowedTools", "Skill,Read,Bash(python3 *)"]
    if vendor == "codex":
        argv = [str(cli), "--ask-for-approval", "never"]
        if api_base_url is not None:
            argv += ["-c", f'openai_base_url="{api_base_url}"']
        argv += ["exec", "--json", "--ephemeral",
                "--sandbox", "workspace-write", "-C", str(workspace),
                "-m", model]
        return [*argv, prompt]
    if vendor == "agy":
        return [str(cli), "-p", "--output-format", "stream-json", "--model", model,
                "--sandbox", "--print-timeout", "120s", prompt]
    if vendor == "cursor":
        return [str(cli), "-p", "--output-format", "stream-json", "--model", model,
                "--workspace", str(workspace), "--sandbox", "enabled", "--trust", prompt]
    raise ValueError(vendor)


def run_native(vendor: str, cli: Path, model: str, workspace: Path, user: str,
               home: Path, prompt: str, timeout: int = 150,
               proof_name: str | None = None,
               diagnostics: dict | None = None,
               api_base_url: str | None = None) -> tuple[str, bool]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required for native CLI execution")
    env = {"HOME": str(home), "PATH": f"{Path(node).parent}:/usr/local/bin:/usr/bin:/bin",
           "LANG": "C.UTF-8", "CODEX_HOME": str(home / ".codex")}
    if vendor == "agy":
        env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    argv = ["sudo", "-n", f"--preserve-env={SECRET[vendor]}", "-u", user, "env",
            *[f"{key}={value}" for key, value in env.items()],
            *command(vendor, cli, model, workspace, prompt, proof_name, api_base_url)]
    proc = subprocess.Popen(argv, cwd=workspace, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise RuntimeError(f"{vendor} exceeded the per-probe deadline") from None
    if proc.returncode:
        raise RuntimeError(f"{vendor} exited {proc.returncode}; raw output withheld")
    if vendor == "claude" and proof_name is None and diagnostics is not None:
        diagnostics.update(claude_structure_diagnostics(stdout))
    if vendor == "codex" and proof_name is not None and diagnostics is not None:
        diagnostics.update(codex_command_diagnostics(stdout, proof_name, stderr))
    try:
        text, success, used_tool = decode_events(vendor, stdout, proof_name)
    except ValueError as exc:
        raise EvidenceUnavailable(f"{vendor} structured terminal result unavailable") from exc
    if not success:
        issue = (claude_terminal_issue(stdout)
                 if vendor == "claude" else "terminal event failure")
        raise RuntimeError(f"{vendor} {issue}")
    return text, used_tool


def codex_skill_listed(cli: Path, workspace: Path, user: str, home: Path, name: str) -> bool:
    """Check the isolated Codex prompt inventory, never exposing its contents."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required for Codex skill inventory")
    env = {"HOME": str(home), "CODEX_HOME": str(home / ".codex"),
           "PATH": f"{Path(node).parent}:/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
    argv = ["sudo", "-n", "-u", user, "env", *[f"{key}={value}" for key, value in env.items()],
            str(cli), "debug", "prompt-input", f"Use the ${name} skill."]
    try:
        proc = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        raise RuntimeError("codex skill inventory exceeded its deadline") from None
    if proc.returncode:
        raise RuntimeError("codex skill inventory failed; raw output withheld")
    return f"- {name}:" in proc.stdout


def codex_tool_probe(cli: Path, model: str, workspace: Path, user: str,
                     home: Path, api_base_url: str | None = None) -> dict[str, object]:
    """Prove a fresh, pre-placement CLI turn executed Python and wrote a file."""
    challenge = secrets.token_hex(16)
    proof = workspace / f"tool-probe-{secrets.token_hex(8)}.txt"
    python_command = ("python3 -c 'from pathlib import Path; "
                      f'Path("{proof.name}").write_text({json.dumps(challenge + chr(10))})' + "'")
    prompt = ("This checks execution, so use an available shell-capable tool to run "
              "the following Python 3 command. A patch or file-editing tool alone "
              "does not satisfy this check. "
              f"{python_command}\nThe file must contain exactly {challenge} followed "
              "by a newline. Wait for command completion before replying.")
    diagnostics: dict[str, object] = {}
    try:
        run_native("codex", cli, model, workspace, user, home, prompt,
                   proof_name=proof.name, diagnostics=diagnostics,
                   api_base_url=api_base_url)
    except (RuntimeError, EvidenceUnavailable, ValueError) as exc:
        diagnostics["probe_exception"] = type(exc).__name__
    diagnostics["file_matches"] = (
        not proof.is_symlink() and proof.is_file()
        and proof.stat().st_size == len(challenge) + 1
        and proof.read_text() == challenge + "\n")
    diagnostics["tool_completed"] = (
        diagnostics.get("codex_proof_exit_codes") == [0]
        and diagnostics.get("codex_proof_command_attempted") is True
        and diagnostics.get("codex_proof_command_failed") is False
        and diagnostics.get("codex_proof_command_shape", {}).get("python3") is True
        and diagnostics.get("codex_turn_completed") is True)
    diagnostics["passed"] = diagnostics["tool_completed"] and diagnostics["file_matches"]
    if proof.exists():
        proof.unlink()
    return diagnostics


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", choices=(*TARGET, *SCENARIO), required=True)
    parser.add_argument("--cli", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--entry", type=Path, required=True)
    parser.add_argument("--rulesync", type=Path, required=True)
    parser.add_argument("--user", default="native-e2e")
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    vendors = SCENARIO.get(args.vendor, (args.vendor,))
    binaries = {vendor: Path(os.environ.get(f"NATIVE_CLI_{vendor.upper()}", ""))
                for vendor in vendors} if args.vendor in SCENARIO else {args.vendor: args.cli}
    models = {vendor: os.environ.get(f"NATIVE_MODEL_{vendor.upper()}")
              for vendor in vendors} if args.vendor in SCENARIO else {args.vendor: args.model}
    versions = {vendor: os.environ.get(f"NATIVE_VERSION_{vendor.upper()}") for vendor in vendors}
    result = {"scenario": args.vendor, "models": models, "status": "fail", "phase": "preflight",
              "source_sha": os.environ.get("GITHUB_SHA"), "wheel_sha256": os.environ.get("WHEEL_SHA256"),
              "versions": versions, "os": sys.platform}
    root = Path(tempfile.mkdtemp(prefix="native-controller-"))
    workspace = Path(tempfile.mkdtemp(prefix="native-consumer-"))
    source = root / "inputs"
    name = f"e2e-probe-{secrets.token_hex(6)}"
    rule = "RULE_" + secrets.token_hex(16)
    skill = "SKILL_" + secrets.token_hex(16)
    applied = False
    try:
        if sys.platform != "linux":
            raise RuntimeError("isolated native launcher is implemented only for Linux")
        for path in (*binaries.values(), args.entry, args.rulesync):
            if path is None or not path.is_absolute() or not path.is_file():
                raise RuntimeError("an absolute, existing CLI path is required")
        if any(not models[vendor] for vendor in vendors):
            raise RuntimeError("a pinned model ID is required for each native CLI")
        missing = [SECRET[vendor] for vendor in vendors if not os.environ.get(SECRET[vendor])]
        if missing:
            result["status"] = "blocked"
            raise RuntimeError("dedicated environment secret missing: " + ", ".join(missing))
        for vendor in vendors:
            actual = subprocess.run([str(binaries[vendor]), "--version"], capture_output=True,
                                    text=True, timeout=15)
            if actual.returncode or not versions[vendor] or actual.stdout.strip() != versions[vendor]:
                raise RuntimeError(f"{vendor} native CLI version changed after setup")
        root.chmod(0o700)
        workspace.chmod(0o777)
        if subprocess.run(["sudo", "-n", "chown", args.user, str(workspace)],
                          capture_output=True).returncode:
            raise RuntimeError("cannot assign isolated consumer workspace ownership")
        if subprocess.run(["sudo", "-n", "-u", args.user, "git", "init", "--quiet", str(workspace)],
                          capture_output=True).returncode:
            raise RuntimeError("cannot initialize isolated consumer repository")
        for guarded in (root, FIXTURE.parent.parent, Path.cwd()):
            check = subprocess.run(["sudo", "-n", "-u", args.user, "test", "!", "-r", str(guarded)],
                                   capture_output=True)
            if check.returncode:
                raise RuntimeError("probe user can read a guarded source path")
        if subprocess.run(["sudo", "-n", "-u", args.user, "sudo", "-n", "true"],
                          capture_output=True).returncode == 0:
            raise RuntimeError("probe user has sudo access")
        if "codex" in vendors:
            result["phase"] = "preplacement-tool-codex"
            catalog_config = args.home / ".codex" / "config.toml"
            catalog_path = args.home / ".codex" / "native-e2e-models.json"
            profile_check = subprocess.run(
                ["sudo", "-n", "-u", args.user, "test", "!", "-e", str(catalog_config)],
                capture_output=True)
            catalog_check = subprocess.run(
                ["sudo", "-n", "-u", args.user, "test", "-f", str(catalog_path)],
                capture_output=True)
            if profile_check.returncode or catalog_check.returncode:
                raise RuntimeError("Codex isolated catalog setup changed")
            configured = subprocess.run(
                ["sudo", "-n", "-u", args.user, "tee", str(catalog_config)],
                input=f'model_catalog_json = "{catalog_path}"\n',
                capture_output=True, text=True)
            if configured.returncode:
                raise RuntimeError("could not select isolated Codex catalog override")
            result["codex_catalog_configs"] = {
                "standard_responses": {"use_responses_lite": False, "tool_mode": None}}
            with codex_wire_metadata() as (api_base_url, wire_calls):
                probe = codex_tool_probe(
                    binaries["codex"], models["codex"], workspace, args.user, args.home,
                    api_base_url=api_base_url)
            result["codex_wire_metadata"] = wire_calls
            result["codex_tool_probes"] = {"standard_responses": probe}
            if not probe["passed"]:
                raise RuntimeError("Codex pre-placement Python tool execution failed with standard Responses")
            result["codex_catalog_selected"] = "standard_responses"
        rule_dir = source / "rules"
        skill_dir = source / "skills" / name
        rule_dir.mkdir(parents=True)
        skill_dir.mkdir(parents=True)
        rule_file = rule_dir / "native-probe.md"
        rule_file.write_text((FIXTURE / "rule.md").read_text().replace("@RULE_NONCE@", rule[5:]))
        (skill_dir / "SKILL.md").write_text((FIXTURE / "SKILL.md").read_text().replace("@SKILL_NAME@", name))
        (skill_dir / "support.txt").write_text(skill + "\n")
        shutil.copyfile(FIXTURE / "proof.py", skill_dir / "proof.py")
        config = root / "placement.json"
        config.write_text(json.dumps({"version": 1, "input_roots": ["inputs"],
                                      "targets": list(dict.fromkeys(TARGET[vendor] for vendor in vendors)),
                                      "features": ["rules", "skills"],
                                      "output_root": str(workspace), "global": False}))

        def placement(action: str) -> None:
            proc = subprocess.run([str(args.entry), action, "--config", str(config),
                                   "--rulesync", str(args.rulesync)], cwd=workspace,
                                  capture_output=True, text=True, timeout=90)
            if proc.returncode:
                raise RuntimeError(f"agent-rules {action} failed ({proc.returncode}); raw output withheld")

        result["phase"] = "baseline"
        for vendor in vendors:
            challenge = secrets.token_hex(12)
            prompt = f'Return only JSON {{"challenge":"{challenge}"}}. This is a rule probe.'
            text, used_tool = run_native(vendor, binaries[vendor], models[vendor], workspace,
                                         args.user, args.home, prompt, diagnostics=result)
            issue = negative_rule_issue(text, challenge, used_tool)
            if issue:
                raise RuntimeError(f"{vendor} baseline rule probe: {issue}")
        result["phase"] = "apply"
        placement("apply")
        applied = True
        placement("check")
        owned_files = [workspace / item["path"] for item in
                       json.loads((workspace / ".rulesync-ownership.json").read_text())["files"]]
        for vendor in vendors:
            result["phase"] = f"positive-rule-{vendor}"
            challenge = secrets.token_hex(12)
            text, used_tool = run_native(vendor, binaries[vendor], models[vendor], workspace,
                                         args.user, args.home,
                                         f'Rule probe. Return only JSON with rule and challenge; challenge={challenge}.',
                                         diagnostics=result)
            if not answer(text, challenge, "rule", rule) or used_tool:
                raise RuntimeError(f"{vendor} native rule probe failed")
            result["phase"] = f"positive-skill-{vendor}"
            challenge = secrets.token_hex(12)
            proof = workspace / f"proof-{challenge}.json"
            if vendor == "codex":
                result["codex_skill_listed"] = codex_skill_listed(
                    binaries[vendor], workspace, args.user, args.home, name)
                if not result["codex_skill_listed"]:
                    raise EvidenceUnavailable("codex skill absent from isolated prompt inventory")
                prompt = (f'${name}\nThis explicitly invokes the named skill. Read its '
                          f'SKILL.md from the path in your skill inventory, then follow its '
                          f'instructions. Use the exec_command shell tool '
                          f'to run its proof.py with --challenge {challenge} --output {proof}. '
                          f'Read that generated JSON file and return its exact skill and challenge '
                          f'fields as JSON. If you cannot execute the helper, do not guess the skill value.')
            else:
                prompt = (f'/{name} Run this skill\'s proof.py with challenge={challenge} '
                          f'and output={proof}. Return only JSON with skill and challenge.')
            text, used_tool = run_native(vendor, binaries[vendor], models[vendor], workspace,
                                         args.user, args.home, prompt,
                                         proof_name="proof.py", diagnostics=result)
            has_proof = proof.is_file()
            answer_issue = skill_answer_issue(text, challenge, skill)
            valid_answer = answer_issue is None
            if has_proof and valid_answer and not used_tool:
                raise EvidenceUnavailable(f"{vendor} helper tool completion is not observable")
            if not used_tool or not has_proof or not valid_answer:
                raise RuntimeError(f"{vendor} skill evidence: tool={used_tool}, "
                                   f"proof={has_proof}, terminal={valid_answer}, "
                                   f"terminal_issue={answer_issue}")
            if json.loads(proof.read_text()) != {"skill": skill, "challenge": challenge}:
                raise RuntimeError(f"{vendor} native skill proof mismatch")
            proof.unlink()
        result["phase"] = "rollback"
        rule_file.unlink()
        shutil.rmtree(skill_dir)
        placement("apply")
        placement("check")
        if any(path.exists() for path in owned_files):
            raise RuntimeError("owned native files remain after rollback")
        for vendor in vendors:
            result["phase"] = f"negative-rule-{vendor}"
            challenge = secrets.token_hex(12)
            text, used_tool = run_native(vendor, binaries[vendor], models[vendor], workspace,
                                         args.user, args.home,
                                         f'Return only JSON {{"challenge":"{challenge}"}}. This is a rule probe.')
            issue = negative_rule_issue(text, challenge, used_tool)
            if issue:
                raise RuntimeError(f"{vendor} rollback rule probe: {issue}")
            result["phase"] = f"negative-skill-{vendor}"
            challenge = secrets.token_hex(12)
            text, used_tool = run_native(vendor, binaries[vendor], models[vendor], workspace,
                                         args.user, args.home,
                                         f'If the {name} skill is unavailable, return only JSON '
                                         f'{{"challenge":"{challenge}"}}. Do not guess a skill value.')
            if not answer(text, challenge, "skill", None) or used_tool:
                raise RuntimeError(f"{vendor} skill remained visible after rollback")
        for vendor in vendors:
            actual = subprocess.run([str(binaries[vendor]), "--version"], capture_output=True,
                                    text=True, timeout=15)
            if actual.returncode or actual.stdout.strip() != versions[vendor]:
                raise RuntimeError(f"{vendor} native CLI version changed during probes")
        result.update(status="pass", phase="complete")
    except EvidenceUnavailable as exc:
        result.update(status="unverified", reason=str(exc))
    except (Exception, KeyboardInterrupt) as exc:
        result["reason"] = str(exc)
    finally:
        if applied and result["status"] != "pass":
            try:
                if rule_file.exists():
                    rule_file.unlink()
                if skill_dir.exists():
                    shutil.rmtree(skill_dir)
                placement("apply")
                result["failure_rollback"] = "pass"
            except Exception as exc:
                result["failure_rollback"] = "fail"
                result["rollback_reason"] = str(exc)
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        shutil.rmtree(root, ignore_errors=True)
        # The disposable VM owns final workspace cleanup. Never use deletion as
        # evidence that the same-workspace rollback succeeded.
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
