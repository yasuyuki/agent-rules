from pathlib import Path
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "bin" / "rules.py"

spec = importlib.util.spec_from_file_location("agent_rules", RULES)
agent_rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_rules)


def run(workspace: Path, command: str, expected: int = 0) -> None:
    result = subprocess.run(
        [sys.executable, str(RULES), command, str(workspace)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"{command} returned {result.returncode}, expected {expected}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


with tempfile.TemporaryDirectory() as directory:
    workspace = Path(directory)
    run(workspace, "render")
    run(workspace, "verify")

    overlay = workspace / ".cursor" / "rules" / "local-overlay.mdc"
    overlay.write_text("local\n", encoding="utf-8")
    (workspace / "CLAUDE.md").write_text("local Claude instructions\n", encoding="utf-8")
    (workspace / ".cursorrules").write_text("local Cursor instructions\n", encoding="utf-8")
    run(workspace, "verify")

    legacy = workspace / ".cursor" / "rules" / "agent-rules--legacy.mdc"
    legacy.write_text("legacy\n", encoding="utf-8")
    run(workspace, "verify", expected=1)
    run(workspace, "render")
    assert not legacy.exists()
    assert overlay.read_text(encoding="utf-8") == "local\n"
    run(workspace, "verify")

    generated = workspace / ".cursor" / "rules" / "agent-rules--agent-delegation.mdc"
    generated.write_text(generated.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    run(workspace, "verify", expected=1)

    run(workspace, "render")
    run(workspace, "verify")

body = "# Demo\n"
block = agent_rules.splice("", "demo", body)
duplicate = block + "\n" + block
assert len(agent_rules.extract_all(duplicate, "demo")) == 2
normalized = agent_rules.splice(duplicate, "demo", body)
assert agent_rules.extract_all(normalized, "demo") == [body]

with tempfile.TemporaryDirectory() as directory:
    workspace = Path(directory)
    run(workspace, "render")
    agents = workspace / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    block = agent_rules.splice("", "unknown", "# Unknown\n")
    agents.write_text(text + "\n" + block, encoding="utf-8")
    run(workspace, "verify", expected=1)
    run(workspace, "render")
    run(workspace, "verify")

    text = agents.read_text(encoding="utf-8")
    agents.write_text(text + "\n<!-- agent-rules:begin orphan -->\n", encoding="utf-8")
    run(workspace, "verify", expected=1)
    run(workspace, "render", expected=1)


# A sixth tool that only reads existing conventions does not require a rules.py change.
with tempfile.TemporaryDirectory() as directory:
    dest = Path(directory) / "src"
    (dest / "bin").mkdir(parents=True)
    shutil.copy(RULES, dest / "bin" / "rules.py")
    shutil.copytree(ROOT / "rules", dest / "rules")
    placement = json.loads((ROOT / "placement.json").read_text(encoding="utf-8"))
    placement["tools"]["extra"] = {
        "entrypoint": "extra",
        "credential": "$HOME/.extra/auth.json",
        "configHome": {"default": "$HOME/.extra"},
        "reads": ["agents-md-section"],
        "hooks": {"kind": "unverified"},
    }
    (dest / "placement.json").write_text(json.dumps(placement), encoding="utf-8")
    extra_rules = dest / "bin" / "rules.py"
    workspace = Path(directory) / "ws"
    for command in ("render", "verify"):
        result = subprocess.run(
            [sys.executable, str(extra_rules), command, str(workspace)],
            cwd=dest,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"sixth-tool {command} returned {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )


# cli-status.sh (entrypoint, credential) pairs must match placement.json when the
# sibling checkout is present. Public CI of this repo alone skips the file.
cli_status = ROOT.parent / "wsl-agent-lifecycle" / "cli-status.sh"
if cli_status.is_file():
    text = cli_status.read_text(encoding="utf-8")
    match = re.search(r'\nclis="(.*?)"', text, re.S)
    if not match:
        raise AssertionError("cli-status.sh: missing clis assignment")
    pairs = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        name, credential = line.split(None, 1)
        pairs[name] = credential
    placement = json.loads((ROOT / "placement.json").read_text(encoding="utf-8"))
    for name, credential in pairs.items():
        tool = placement["tools"][name]
        if tool["entrypoint"] != name or tool["credential"] != credential:
            raise AssertionError(
                f"{name}: placement.json {(tool['entrypoint'], tool['credential'])} "
                f"!= cli-status.sh {(name, credential)}"
            )
    if set(pairs) != set(placement["tools"]):
        raise AssertionError(
            f"tool ids differ: placement {sorted(placement['tools'])} "
            f"cli-status {sorted(pairs)}"
        )
