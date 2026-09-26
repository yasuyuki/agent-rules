"""Authenticated native probes for an isolated Linux Actions VM.

The controller owns the fixture and expected values. Vendor processes run as a
different, unprivileged local user and can only see the consumer workspace.
This is intentionally separate from the authentication-free package gate.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import time


FIXTURE = Path(__file__).parent / "fixtures/native-e2e"
TARGET = {"claude": "claudecode", "codex": "codexcli", "agy": "codexcli", "cursor": "cursor"}
SECRET = {"claude": "ANTHROPIC_API_KEY", "codex": "OPENAI_API_KEY", "agy": "GEMINI_API_KEY", "cursor": "CURSOR_API_KEY"}
SCENARIO = {"pair": ("claude", "codex"), "all": tuple(TARGET)}
CLAUDE_RESULT_SCHEMA = json.dumps({
    "type": "object",
    "properties": {"challenge": {"type": "string"}, "rule": {"type": "string"},
                   "skill": {"type": "string"}},
    "required": ["challenge"],
    "additionalProperties": False,
})


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
        for event in events:
            if event.get("type") == "result":
                if proof_name is None:
                    structured = event.get("structured_output")
                    has_structured = isinstance(structured, dict)
                    terminal.append((json.dumps(structured) if has_structured else "",
                                     has_structured and event.get("subtype") == "success"
                                     and not event.get("is_error", False)))
                else:
                    terminal.append((event.get("result", ""),
                                     event.get("subtype") == "success"
                                     and not event.get("is_error", False)))
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if (isinstance(block, dict) and block.get("type") == "tool_use"
                            and (proof_name is None or (block.get("name") == "Bash"
                                 and proof_name in str(block.get("input", {}))))):
                        proof_ids.add(block.get("id"))
            if event.get("type") == "user":
                for block in event.get("message", {}).get("content", []):
                    if (isinstance(block, dict) and block.get("type") == "tool_result"
                            and block.get("tool_use_id") in proof_ids and not block.get("is_error")):
                        tools = True
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


def answer(text: str, challenge: str, field: str, expected: str | None) -> bool:
    try:
        value = json.loads(text.strip())
    except (ValueError, TypeError):
        return False
    if not isinstance(value, dict) or value.get("challenge") != challenge:
        return False
    return value.get(field) == expected if expected is not None else field not in value


def negative_rule_issue(text: str, challenge: str, used_tool: bool) -> str | None:
    """Describe a failed negative probe without exposing model output or nonces."""
    try:
        value = json.loads(text.strip())
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
        value = json.loads(text.strip())
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


def claude_terminal_issue(stdout: str, expect_structured: bool = True) -> str:
    """Summarize the terminal event without including model text or API errors."""
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    results = [event for event in events if event.get("type") == "result"]
    if len(results) != 1:
        return "missing or multiple terminal results"
    result = results[0]
    if result.get("subtype") == "error_max_structured_output_retries":
        return "structured output retry limit"
    if (expect_structured and result.get("subtype") == "success"
            and not isinstance(result.get("structured_output"), dict)):
        return "structured output missing"
    return "terminal event failure"


def codex_command_diagnostics(stdout: str, proof_name: str) -> dict[str, bool]:
    """Report command activity without retaining commands or their output."""
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    items = [event.get("item", {}) for event in events
             if event.get("type") in ("item.started", "item.completed")]
    commands = [item for item in items if item.get("type") == "command_execution"]
    proof_commands = [item for item in commands if proof_name in str(item.get("command", ""))]
    return {"codex_command_attempted": bool(commands),
            "codex_proof_command_attempted": bool(proof_commands),
            "codex_proof_command_failed": any(
                item.get("status") == "failed" or
                (isinstance(item.get("exit_code"), int) and item["exit_code"] != 0)
                for item in proof_commands)}


def command(vendor: str, cli: Path, model: str, workspace: Path, prompt: str,
            proof_name: str | None = None) -> list[str]:
    if vendor == "claude":
        base = [str(cli), "-p", "--output-format", "stream-json", "--verbose", "--model", model,
                "--max-turns", "5"]
        if proof_name is None:
            return [*base, "--json-schema", CLAUDE_RESULT_SCHEMA, prompt, "--tools", ""]
        return [*base, prompt, "--tools", "Skill,Read,Bash",
                "--allowedTools", "Skill,Read,Bash(python3 *)"]
    if vendor == "codex":
        return [str(cli), "exec", "--json", "--ephemeral", "--sandbox", "workspace-write",
                "--skip-git-repo-check", "-C", str(workspace), "-m", model, prompt]
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
               diagnostics: dict | None = None) -> tuple[str, bool]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required for native CLI execution")
    env = {"HOME": str(home), "PATH": f"{Path(node).parent}:/usr/local/bin:/usr/bin:/bin",
           "LANG": "C.UTF-8", "CODEX_HOME": str(home / ".codex")}
    if vendor == "agy":
        env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    argv = ["sudo", "-n", f"--preserve-env={SECRET[vendor]}", "-u", user, "env",
            *[f"{key}={value}" for key, value in env.items()],
            *command(vendor, cli, model, workspace, prompt, proof_name)]
    proc = subprocess.Popen(argv, cwd=workspace, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise RuntimeError(f"{vendor} exceeded the per-probe deadline") from None
    if proc.returncode:
        raise RuntimeError(f"{vendor} exited {proc.returncode}; raw output withheld")
    if vendor == "codex" and proof_name is not None and diagnostics is not None:
        diagnostics.update(codex_command_diagnostics(stdout, proof_name))
    try:
        text, success, used_tool = decode_events(vendor, stdout, proof_name)
    except ValueError as exc:
        raise EvidenceUnavailable(f"{vendor} structured terminal result unavailable") from exc
    if not success:
        issue = (claude_terminal_issue(stdout, proof_name is None)
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
        for guarded in (root, FIXTURE.parent.parent, Path.cwd()):
            check = subprocess.run(["sudo", "-n", "-u", args.user, "test", "!", "-r", str(guarded)],
                                   capture_output=True)
            if check.returncode:
                raise RuntimeError("probe user can read a guarded source path")
        if subprocess.run(["sudo", "-n", "-u", args.user, "sudo", "-n", "true"],
                          capture_output=True).returncode == 0:
            raise RuntimeError("probe user has sudo access")
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
                                         args.user, args.home, prompt)
            issue = negative_rule_issue(text, challenge, used_tool)
            if issue:
                raise RuntimeError(f"{vendor} baseline rule probe: {issue}")
        result["phase"] = "apply"
        placement("apply")
        applied = True
        placement("check")
        for vendor in vendors:
            result["phase"] = f"positive-rule-{vendor}"
            challenge = secrets.token_hex(12)
            text, used_tool = run_native(vendor, binaries[vendor], models[vendor], workspace,
                                         args.user, args.home,
                                         f'Rule probe. Return only JSON with rule and challenge; challenge={challenge}.')
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
                prompt = (f'${name}\nExecute this skill\'s instructions. Call the shell tool '
                          f'to run its proof.py with --challenge {challenge} --output {proof}. '
                          f'Read that generated JSON file and return its exact skill and challenge '
                          f'fields as JSON. If you cannot execute the helper, do not guess the skill value.')
            else:
                prompt = (f'Use the {name} skill. Run its proof.py with challenge={challenge} '
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
        paths = [workspace / ".claude/rules/native-probe.md", workspace / "AGENTS.md",
                 workspace / ".cursor/rules/native-probe.mdc"]
        if any(path.exists() for path in paths) or list(workspace.glob("**/" + name)):
            raise RuntimeError("owned native paths remain after rollback")
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
