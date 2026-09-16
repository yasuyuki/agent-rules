"""Non-executing, parser-backed observations for necessity selection."""
from __future__ import annotations

import ast
import importlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

KEYS = ("features", "coverage", "writes", "executes", "responsibilities")


def _result(): return {key: [] for key in KEYS}
def _add(result, key, value):
    if value and value not in result[key]: result[key].append(value)
def _literal(node): return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None
def _call_name(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""
def _path(node):
    if value := _literal(node): return value
    if isinstance(node, ast.Call) and _call_name(node.func) in {"Path", "pathlib.Path"} and node.args: return _literal(node.args[0])
    return None
def _finalize(result):
    roles = set(result["responsibilities"])
    if len(roles) > 1 and roles != {"process", "report"}:
        _add(result, "features", "multiple-responsibilities")


def _analyse_python(source, result):
    if source.startswith("-c "): source = source[3:]
    try: tree = ast.parse(source)
    except SyntaxError:
        _add(result, "coverage", "python:unassessed (syntax error)"); return
    generated = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call): continue
        name, first = _call_name(node.func), _literal(node.args[0]) if node.args else None
        if name in {"eval", "exec"}:
            if first is None: _add(result, "coverage", "python:unassessed (dynamic eval)")
            else: _analyse_python(first, result)
        elif name in {"open", "Path.open"}:
            mode = _literal(node.args[1]) if len(node.args) > 1 else None
            _add(result, "responsibilities", "state")
            if mode and any(flag in mode for flag in ("w", "a", "x", "+")) and first:
                _add(result, "writes", first); generated.add(first)
        elif name.endswith(("write_text", "write_bytes", "touch", "mkdir")):
            path = _path(node.func.value) if isinstance(node.func, ast.Attribute) else None
            _add(result, "responsibilities", "state")
            if path: _add(result, "writes", path); generated.add(path)
        elif name.endswith(("read_text", "read_bytes")):
            _add(result, "responsibilities", "state")
        elif name in {"subprocess.run", "subprocess.Popen", "os.system", "os.execv", "os.execve"}:
            _add(result, "responsibilities", "process")
            if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)) and node.args[0].elts:
                words = [_literal(item) for item in node.args[0].elts]
                if words[0]: _add(result, "executes", words[0])
                if len(words) > 1 and words[1] in generated:
                    _add(result, "executes", words[1]); _add(result, "features", "generated-file-execution")
            elif first: _add(result, "executes", first)
        elif name in {"time.sleep", "asyncio.sleep"} or name.endswith(".wait"): _add(result, "responsibilities", "wait")
        elif name.endswith(("unlink", "rmdir")) or name in {"os.remove", "os.unlink", "shutil.rmtree"}: _add(result, "responsibilities", "cleanup")
        elif name in {"print", "logging.info", "logging.warning", "logging.error"}: _add(result, "responsibilities", "report")


def _bash_heredoc(node):
    heredoc, output = getattr(node, "heredoc", None), getattr(node, "output", None)
    if not heredoc or not output: return None
    value, delimiter = getattr(heredoc, "value", ""), getattr(output, "word", "")
    suffix = f"\n{delimiter}"
    return value[:-len(suffix)] if suffix and value.endswith(suffix) else value


def _analyse_bash(source, result):
    try:
        nodes = importlib.import_module("bashlex").parse(source)
    except ImportError:
        _add(result, "coverage", "bash:unassessed (bashlex unavailable)"); return
    except Exception:
        _add(result, "coverage", "bash:unassessed (parse failure)"); return
    generated = set()
    def visit(node):
        kind = getattr(node, "kind", "")
        if kind == "commandsubstitution":
            _add(result, "responsibilities", "process"); _add(result, "features", "command-substitution"); visit(node.command); return
        if kind == "redirect":
            if getattr(node, "type", "") not in {"<", "<<", "<<<"}:
                path = getattr(getattr(node, "output", None), "word", "")
                if path: _add(result, "writes", path); generated.add(path); _add(result, "responsibilities", "state")
            return
        if kind != "command":
            for part in getattr(node, "parts", []) or []: visit(part)
            for part in getattr(node, "list", []) or []: visit(part)
            return
        parts = getattr(node, "parts", [])
        words = [part.word for part in parts if getattr(part, "kind", "") == "word"]
        redirects = [part for part in parts if getattr(part, "kind", "") == "redirect"]
        if not words: return
        head = Path(words[0]).name.lower()
        if head == "wsl": _add(result, "coverage", "bash:unassessed (wsl nested shell)")
        elif head in {"bash", "sh", "zsh"}:
            command_flag = next((w for w in words[1:] if w.startswith("-") and not w.startswith("--") and "c" in w), None)
            if command_flag:
                at = words.index(command_flag)
                if len(words) > at + 1: _analyse_bash(words[at + 1], result)
                else: _add(result, "coverage", "bash:unassessed (missing -c source)")
            elif len(words) > 1 and words[1].startswith("-"):
                _add(result, "coverage", "bash:unassessed (interpreter flags)")
            elif len(words) > 1:
                _add(result, "responsibilities", "process"); _add(result, "executes", words[1])
                if words[1] in generated: _add(result, "features", "generated-file-execution")
            else: _add(result, "responsibilities", "process"); _add(result, "executes", words[0])
        elif head in {"python", "python3", "py"}:
            if "-c" in words and len(words) > words.index("-c") + 1: _analyse_python(words[words.index("-c") + 1], result)
            elif "-m" in words: _add(result, "coverage", "python:unassessed (module execution)")
            else:
                heredoc = next((_bash_heredoc(item) for item in redirects if _bash_heredoc(item) is not None), None)
                if heredoc is not None: _analyse_python(heredoc, result)
                elif len(words) > 1 and words[1].startswith("-"): _add(result, "coverage", "python:unassessed (interpreter flags)")
                elif len(words) > 1:
                    _add(result, "responsibilities", "process"); _add(result, "executes", words[1])
                    if words[1] in generated: _add(result, "features", "generated-file-execution")
        elif head == "sleep": _add(result, "responsibilities", "wait")
        elif head in {"rm", "rmdir", "unlink"}: _add(result, "responsibilities", "cleanup")
        elif head in {"echo", "printf"}:
            if not redirects: _add(result, "responsibilities", "report")
        elif head == "cat" and redirects:
            pass
        elif head in {"command", "env", "xargs"}:
            _add(result, "coverage", "bash:unassessed (indirect command)")
        else: _add(result, "responsibilities", "process"); _add(result, "executes", words[0])
        for part in parts: visit(part)
    for node in nodes: visit(node)


def _analyse_powershell(source, result, parser_timeout):
    pwsh, parser = shutil.which("pwsh"), Path(__file__).with_name("necessity_parse.ps1")
    if not pwsh: _add(result, "coverage", "powershell:unsupported (pwsh unavailable)"); return
    if not parser.is_file(): _add(result, "coverage", "powershell:unassessed (parser script unavailable)"); return
    if parser_timeout is None:
        _add(result, "coverage", "powershell:unassessed (missing parser timeout)"); return
    try:
        completed = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(parser)], input=source, text=True, capture_output=True, timeout=parser_timeout, check=False)
        details = json.loads(completed.stdout)
    except subprocess.TimeoutExpired: _add(result, "coverage", "powershell:unassessed (parser timeout)"); return
    except (OSError, json.JSONDecodeError): _add(result, "coverage", "powershell:unassessed (parser failure)"); return
    if completed.returncode or details.get("errors"): _add(result, "coverage", "powershell:unassessed (syntax error)"); return
    for key in ("coverage", "writes", "executes", "responsibilities"):
        for value in details.get(key, []): _add(result, key, value)


def analyze(command: str, shell: str = "bash", parser_timeout: float | None = None) -> dict[str, list[str]]:
    """Return facts only; nonempty coverage means a parser gap."""
    result = _result()
    if not isinstance(command, str): _add(result, "coverage", "input:unsupported (not text)")
    elif Path(shell).name.lower().removesuffix(".exe") in {"python", "python3"}: _analyse_python(command, result)
    elif Path(shell).name.lower().removesuffix(".exe") in {"bash", "sh", "zsh"}: _analyse_bash(command, result)
    elif Path(shell).name.lower().removesuffix(".exe") in {"powershell", "pwsh"}: _analyse_powershell(command, result, parser_timeout)
    else: _add(result, "coverage", f"{shell}:unsupported")
    _finalize(result)
    return result
