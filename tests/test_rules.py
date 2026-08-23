from pathlib import Path
import importlib.util
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
