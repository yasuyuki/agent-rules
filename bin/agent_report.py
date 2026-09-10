#!/usr/bin/env python3
"""Standalone agent self-report collector. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import html
import importlib.util
import inspect
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import subprocess
import sys

PLUGIN_API_VERSION = 1
CATEGORIES = ("files", "skills", "unknowns")
FIELDS = ("name", "path", "source", "role", "scope", "state")
STATES = ("loaded", "available", "applicable", "inactive", "unavailable", "unknown")


def prompt(target: Path) -> str:
    return """Perform a read-only diagnostic of THIS NEW SESSION, not any previous conversation.
Do not modify files, run commands, invoke skills, delegate, or contact external services.
Use only the configuration/instruction metadata and skill catalog already visible to you.
Do not read every skill to enumerate it. Available does NOT mean its body was loaded.
Report instruction/configuration files and skills you know about, including plugin skills.
Do not guess paths or claim a file is loaded merely because it might exist.
Record inaccessible, omitted or unknowable configuration and scope in unknowns.
Return ONLY one JSON object with arrays files, skills, unknowns (empty arrays are valid).
Each item has string fields name, path, source, role, scope, state.
path is a concrete local filesystem path or empty; source identifies non-file origins.
Resolve skill aliases only if their root mapping is visible; otherwise leave path empty.
state is loaded, available, applicable, inactive, unavailable, or unknown.
For skills use loaded only if the BODY is already in context; otherwise available or unknown.
Report metadata only: never include file bodies, setting values, credentials, environment
variable values, system prompt text, conversation logs, or instructions to the reader.
Use concise role/scope descriptions. Include every known catalog entry, without opening it.
Target directory: """ + str(target)


def json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


class Builtin:
    def __init__(self, identifier, name, candidates, restrictions):
        self.id = identifier
        self.name = name
        self.cli_candidates = candidates
        self.restrictions = restrictions

    def version_args(self):
        return ["--version"]

    def parse_version(self, stdout):
        # Retain the version token, never arbitrary CLI output.
        match = re.search(r"\b\d+\.\d+(?:\.\d+)?(?:[-+][\w.-]+)?\b", stdout)
        if not match:
            raise ValueError("No version token")
        return match.group()

    def query_args(self, target):
        question = prompt(target)
        if self.id == "codex":
            return ["exec", "--json", "--ephemeral", "--sandbox", "read-only",
                    "--skip-git-repo-check", "--color", "never", question]
        if self.id == "claude":
            return ["--print", "--output-format", "json", "--tools", "",
                    "--permission-mode", "dontAsk", "--no-session-persistence", question]
        return ["--print", "--output-format", "json", "--mode", "ask", question]

    def parse_response(self, stdout):
        if self.id == "codex":
            messages = []
            completed = False
            for line in stdout.splitlines():
                event = json_object(line)
                if event.get("type") in ("error", "turn.failed"):
                    raise ValueError("Failed turn")
                if event.get("type") == "turn.completed":
                    completed = True
                item = event.get("item", {})
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    messages.append(item["text"])
            if not completed or not messages:
                raise ValueError("Missing completed response")
            return json_object(messages[-1])
        envelope = json_object(stdout)
        if envelope.get("type") != "result" or envelope.get("is_error") is True:
            raise ValueError("Failed result")
        if envelope.get("subtype", "success") != "success":
            raise ValueError("Failed result subtype")
        return json_object(envelope["result"])


def get_platforms():
    return [
        Builtin("codex", "Codex", ["codex"],
                "read-only sandbox; ephemeral session; prompt requests no tools"),
        Builtin("claude", "Claude Code", ["claude"],
                "no built-in tools; dontAsk permissions; no session persistence; prompt requests no tools"),
        Builtin("cursor", "Cursor Agent", ["agent", "cursor-agent"],
                "ask mode; prompt requests no tools"),
    ]


def argv(value, allow_empty=False):
    if (not isinstance(value, list) or (not value and not allow_empty)
            or any(not isinstance(x, str) or "\0" in x for x in value)
            or (value and not value[0])):
        raise ValueError("Expected argument array")
    return value


def load_platforms(directories, target):
    """Validate every adapter and prepare arguments before running any CLI."""
    groups = [("builtin", get_platforms())]
    for directory in directories:
        root = Path(directory).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Plugin directory is not a directory")
        for path in sorted(root.glob("*.py")):
            path = path.resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("Plugin file must be inside selected directory")
            # Only explicitly selected directories; no sys.path mutation or download.
            spec = importlib.util.spec_from_file_location(f"agent_report_plugin_{len(groups)}", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            try:
                spec.loader.exec_module(module)
                if type(getattr(module, "PLUGIN_API_VERSION", None)) is not int or module.PLUGIN_API_VERSION != 1:
                    raise ValueError("Unsupported plugin API")
                groups.append((str(path), module.get_platforms()))
            except BaseException as exc:
                if isinstance(exc, KeyboardInterrupt):
                    raise
                raise ValueError("Plugin load failed (details suppressed)") from None
    result = {}
    for source, adapters in groups:
        if not isinstance(adapters, (list, tuple)) or not adapters:
            raise ValueError("get_platforms must return a nonempty list or tuple")
        for adapter in adapters:
            identifier = adapter.id
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", identifier):
                raise ValueError("Invalid platform identifier")
            if identifier in result:
                raise ValueError("Duplicate platform identifier")
            metadata = {field: getattr(adapter, field) for field in ("name", "restrictions")}
            for value in metadata.values():
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Invalid adapter metadata")
            candidates = list(argv(adapter.cli_candidates))
            if any(not x or "/" in x or "\\" in x for x in candidates):
                raise ValueError("CLI candidates must be PATH command names")
            for method, args in (("version_args", ()), ("query_args", (target,)),
                                 ("parse_version", ("",)), ("parse_response", ("",))):
                inspect.signature(getattr(adapter, method)).bind(*args)
            result[identifier] = {"adapter": adapter, "plugin": source,
                                  **metadata,
                                  "cli_candidates": candidates,
                                  "version_args": list(argv(adapter.version_args(), True)),
                                  "query_args": list(argv(adapter.query_args(target)))}
    return result


def validate_data(value):
    if not isinstance(value, dict) or set(value) - set(CATEGORIES):
        raise ValueError("Invalid report object")
    clean = {category: [] for category in CATEGORIES}
    for category in CATEGORIES:
        if category not in value:
            clean["unknowns"].append(dict(name=category, path="", source="collector",
                                           role="Category omitted from response", scope="session", state="unknown"))
            continue
        if not isinstance(value[category], list):
            raise ValueError("Invalid category")
        for item in value[category]:
            if not isinstance(item, dict) or set(item) - set(FIELDS):
                raise ValueError("Invalid metadata item")
            if not isinstance(item.get("name"), str) or not item["name"].strip():
                raise ValueError("Missing item name")
            if any(not isinstance(v, str) for v in item.values()):
                raise ValueError("Non-string metadata")
            normalized = {key: item.get(key, "unknown" if key in ("state", "role", "scope") else "") for key in FIELDS}
            if normalized["state"] not in STATES:
                raise ValueError("Invalid reported state")
            clean[category].append(normalized)
    return clean


def path_status(value, target):
    if not value:
        return "not checkable"
    # Do not mistake foreign paths, aliases or non-file sources for missing files.
    if ("\0" in value or re.match(r"^[a-zA-Z][\w+.-]*://", value)
            or (os.name != "nt" and (PureWindowsPath(value).drive or "\\" in value))
            or value.startswith("$") or any(x in value for x in ("*", "?"))):
        return "not checkable"
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = target / path
        path.stat()
        return "exists"
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except (OSError, ValueError, RuntimeError):
        return "not checkable"


def run(command, target, timeout):
    # Windows may implicitly pass batch files to cmd.exe even with shell=False.
    # Use an explicit native interpreter prefix for npm-style .cmd shims instead.
    if os.name == "nt" and command[0].lower().endswith((".cmd", ".bat")):
        raise OSError("Batch launchers are not supported")
    return subprocess.run(command, cwd=target, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          encoding="utf-8", errors="replace", timeout=timeout, shell=False)


def collect(registry, selected, launch, target, timeout=None):
    reports = []
    for identifier in selected:
        entry = registry[identifier]
        adapter = entry["adapter"]
        cli = next((found for candidate in entry["cli_candidates"] if (found := shutil.which(candidate))), None)
        prefix = launch.get(identifier)
        launcher = shutil.which(prefix[0]) if prefix else cli
        report = dict(id=identifier, name=entry["name"], plugin=entry["plugin"],
                      restrictions=entry["restrictions"], cli=cli or "not found on PATH",
                      launcher=launcher or "not found on PATH", version="unknown",
                      version_status="not collected", status="not installed", data=None)
        reports.append(report)
        if not launcher:
            if prefix:
                report["status"] = "launcher not found"
            continue
        command = [launcher, *prefix[1:]] if prefix else [cli]
        try:
            version = run(command + entry["version_args"], target, timeout)
            if version.returncode:
                report["version_status"] = f"exit {version.returncode}"
            else:
                parsed = adapter.parse_version(version.stdout)
                if not isinstance(parsed, str) or not re.fullmatch(r"[0-9][\w.+-]*", parsed):
                    raise ValueError("Invalid version")
                report.update(version=parsed, version_status="collected")
        except Exception:
            report["version_status"] = "unavailable"
        try:
            response = run(command + entry["query_args"], target, timeout)
        except subprocess.TimeoutExpired:
            report["status"] = "timeout"
            continue
        except OSError:
            report["status"] = "launch failed"
            continue
        if response.returncode:
            report["status"] = f"query failed (exit {response.returncode})"
            continue
        try:
            data = validate_data(adapter.parse_response(response.stdout))
            for items in data.values():
                for item in items:
                    item["existence"] = path_status(item["path"], target)
            report["data"] = data
            report["status"] = "partial" if data["unknowns"] else "collected"
        except Exception:
            report["status"] = "response conversion failed"
    return reports


def render(reports, target):
    escape = lambda value: html.escape(str(value), quote=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>Agent configuration report</title>',
             '<style>body{font:16px system-ui;margin:2rem;color:#18263b;background:#f6f8fc}'
             'section{background:white;padding:1rem;margin:1rem 0;border:1px solid #ccd4e0}'
             'table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.5rem;'
             'border-bottom:1px solid #ddd;overflow-wrap:anywhere}input,select{padding:.5rem}'
             '.table{overflow:auto}dt{font-weight:bold}dd{overflow-wrap:anywhere}</style>',
             '<h1>Agent configuration report</h1>',
             '<p>New-session self-reports, not an authoritative configuration audit. '
             'File existence does not prove application or body loading. Empty successful arrays '
             'mean the agent reported no entries; failures and omissions are separate. '
             'Metadata may still be private: review before sharing.</p>',
             '<dl>']
    for key, value in (("UTC", now), ("Host", platform.node()), ("OS", platform.platform()),
                       ("User", getpass.getuser()), ("Python", platform.python_version()), ("Target", target)):
        parts.append(f'<dt>{key}</dt><dd>{escape(value)}</dd>')
    parts.append('</dl><label>Search <input id="search" type="search"></label> '
                 '<label>Reported state <select id="state"><option value="">All</option>' +
                 ''.join(f'<option>{state}</option>' for state in STATES) + '</select></label> '
                 '<label>Path check <select id="existence"><option value="">All</option>'
                 '<option>exists</option><option>missing</option><option>not checkable</option></select></label>')
    for report in reports:
        parts.append(f'<section><h2>{escape(report["name"])}</h2><dl>')
        for key in ("id", "plugin", "cli", "launcher", "version", "version_status", "restrictions", "status"):
            parts.append(f'<dt>{key}</dt><dd>{escape(report[key])}</dd>')
        parts.append('</dl>')
        if report["data"] is None:
            parts.append('<p>No inventory collected.</p>')
        else:
            for category, items in report["data"].items():
                parts.append(f'<h3>{category} ({len(items)})</h3>')
                if not items:
                    parts.append('<p>Reported empty.</p>')
                    continue
                parts.append('<div class="table"><table><thead><tr>' + ''.join(
                    f'<th>{key}</th>' for key in (*FIELDS, "existence")) + '</tr></thead><tbody>')
                for item in items:
                    parts.append(f'<tr data-state="{escape(item["state"])}" data-existence="{escape(item["existence"])}">' +
                                 ''.join(f'<td>{escape(item[key])}</td>' for key in (*FIELDS, "existence")) + '</tr>')
                parts.append('</tbody></table></div>')
        parts.append('</section>')
    parts.append('''<script>
const search=document.getElementById('search'),state=document.getElementById('state'),existence=document.getElementById('existence');
function filter(){document.querySelectorAll('tr[data-state]').forEach(row=>{
row.hidden=!(row.textContent.toLowerCase().includes(search.value.toLowerCase())&&
(!state.value||row.dataset.state===state.value)&&(!existence.value||row.dataset.existence===existence.value));});}
[search,state,existence].forEach(control=>control.addEventListener('input',filter));
</script></html>''')
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--output", required=True, type=Path, help="New HTML file (never overwrites)")
    parser.add_argument("--platform", action="append", help="Platform ID; repeat (default: auto-detect all)")
    parser.add_argument("--plugin-dir", action="append", default=[], help="Trusted Python plugin directory; repeat")
    parser.add_argument("--launch-config", type=Path, help="JSON object mapping platform IDs to argv prefixes")
    parser.add_argument("--timeout", type=float, help="Optional seconds per CLI invocation; no automatic retries")
    args = parser.parse_args()
    try:
        target = args.target.resolve(strict=True)
        if not target.is_dir() or args.output.exists() or not args.output.parent.is_dir():
            raise ValueError("Target must be a directory; output must be a new file in an existing directory")
        if args.timeout is not None and (not 0 < args.timeout < float("inf")):
            raise ValueError("Timeout must be positive and finite")
        registry = load_platforms(args.plugin_dir, target)
        selected = list(dict.fromkeys(args.platform or registry))
        if any(key not in registry for key in selected):
            raise ValueError("Unknown platform")
        launch = json.loads(args.launch_config.read_text(encoding="utf-8")) if args.launch_config else {}
        if not isinstance(launch, dict) or any(key not in registry for key in launch):
            raise ValueError("Invalid launch configuration")
        for prefix in launch.values():
            argv(prefix)
    except Exception:
        parser.error("Invalid input or plugin contract (details suppressed to avoid disclosing data)")
    reports = collect(registry, selected, launch, target, args.timeout)
    try:
        with args.output.open("x", encoding="utf-8") as output:
            output.write(render(reports, target))
    except OSError:
        print("Cannot write report", file=sys.stderr)
        return 2
    for report in reports:
        print(f'{report["id"]}: {report["status"]}')
    return 0 if all(r["status"] in ("collected", "partial") or
                    (args.platform is None and r["status"] == "not installed") for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
