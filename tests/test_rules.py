from pathlib import Path
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "bin" / "rules.py"
PLACE = ROOT / "bin" / "place.py"

# Keep lifecycle regressions on the existing Windows/Linux CI test entry point.
lifecycle_result = subprocess.run(
    [sys.executable, str(ROOT / "tests" / "test_inventory_lifecycle.py")],
    cwd=ROOT, text=True, capture_output=True,
)
if lifecycle_result.returncode:
    raise AssertionError("inventory lifecycle failed\n" + lifecycle_result.stdout + lifecycle_result.stderr)

inventory_result = subprocess.run(
    [sys.executable, str(ROOT / "tests" / "test_environment_inventory.py")],
    cwd=ROOT, text=True, capture_output=True,
)
if inventory_result.returncode:
    raise AssertionError("environment inventory failed\n" + inventory_result.stdout + inventory_result.stderr)

classification_result = subprocess.run(
    [sys.executable, str(ROOT / "tests" / "test_work_classification.py")],
    cwd=ROOT, text=True, capture_output=True,
)
if classification_result.returncode:
    raise AssertionError("work classification failed\n" + classification_result.stdout + classification_result.stderr)

# Exercise native Windows junctions as well as POSIX symlinks in the existing
# cross-platform CI entry point.
projection = subprocess.run(
    [sys.executable, str(ROOT / "bin" / "place.py"), "selfcheck"],
    cwd=ROOT, text=True, capture_output=True,
)
if projection.returncode:
    raise AssertionError(
        f"place selfcheck failed\n{projection.stdout}\n{projection.stderr}"
    )

spec = importlib.util.spec_from_file_location("agent_rules", RULES)
agent_rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_rules)

place_spec = importlib.util.spec_from_file_location("agent_rules_place", PLACE)
place = importlib.util.module_from_spec(place_spec)
place_spec.loader.exec_module(place)


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
        "reads": {"rules": ["agents-md-section"], "skills": []},
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


# rules.py renders rules only. A skills convention names directories, so its
# `{id}` sits in a path component rather than in a file name and the managed
# prefix/suffix would be empty -- matching, and deleting, every hand-placed
# skill in the tool's skills directory.
with tempfile.TemporaryDirectory() as directory:
    workspace = Path(directory)
    hand_placed = workspace / ".claude" / "skills" / "hand-placed"
    hand_placed.mkdir(parents=True)
    (hand_placed / "SKILL.md").write_text("---\nname: hand-placed\n---\n", encoding="utf-8")
    run(workspace, "render")
    if not (hand_placed / "SKILL.md").is_file():
        raise AssertionError("render removed a skill from a skills directory")
    run(workspace, "verify")


# Windows checkouts may use CRLF. Parse metadata without changing copied bytes.
with tempfile.TemporaryDirectory() as directory:
    skill_dir = Path(directory) / "example"
    skill_dir.mkdir()
    for newline in (b"\n", b"\r\n"):
        payload = newline.join([
            b"---", b"name: example", b"description: Example skill", b"---", b"Body", b"",
        ])
        (skill_dir / "SKILL.md").write_bytes(payload)
        assert agent_rules.load_skills(directory)["example"]["SKILL.md"] == payload


# A UPSTREAM.tsv that cannot be read says nothing about authorship. Reading it as
# "nothing is vendored" would publish someone else's skill through place.py mirror,
# so a missing file or a lost header stops the caller.
header = "\t".join(agent_rules.SKILL_MANIFEST_HEADER)
row = "grilling\tsomeone/skills\trefs/heads/main\tskills/grilling\tdeadbeef\tMIT"
with tempfile.TemporaryDirectory() as directory:
    skills_dir = Path(directory)
    manifest = skills_dir / agent_rules.SKILL_MANIFEST

    try:
        agent_rules.vendored_ids([str(skills_dir)])
    except SystemExit:
        pass
    else:
        raise AssertionError("a missing manifest passed for an empty one")

    manifest.write_text(f"{header}\n{row}\n", encoding="utf-8", newline="\n")
    if agent_rules.vendored_ids([str(skills_dir)]) != {"grilling"}:
        raise AssertionError("a well-formed manifest did not yield its ids")

    manifest.write_text(f"{row}\n", encoding="utf-8", newline="\n")
    try:
        agent_rules.vendored_ids([str(skills_dir)])
    except SystemExit:
        pass
    else:
        raise AssertionError("a manifest without its header passed")


# A portable checkout can validate policy and launch a declared local CLI
# without work-records, bin/dev.py, or a maintainer-specific configuration.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    home = root / "home"
    workspace = root / "workspace"
    home.mkdir()
    workspace.mkdir()
    declaration = root / "declaration.md"
    declaration.write_text(
        """<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
local\tlocal\ttester\t{home}\tlocal\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
work\ts4\tdirect\t/tmp\t
work\tlocal\tdirect\t{workspace}\t
```
<!-- END WORKSPACES TSV -->
<!-- BEGIN LOCATIONS TSV -->
```tsv
id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind
home-codex\thome\tlocal\tcodex\trequired\t\t\t\t
home-claude\thome\tlocal\tclaude\trequired\t\t\t\t
work-codex\tworkspace\twork\tcodex\trequired\t\t\t\t
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
""".format(home=home, workspace=workspace),
        encoding="utf-8",
    )
    common = dict(
        declaration=str(declaration), rules=None, skills=None,
        site=None, workspace=None, scope=None,
    )
    listed = subprocess.run(
        [sys.executable, str(PLACE), "list", "--declaration", str(declaration)],
        text=True, capture_output=True,
    )
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.splitlines() == [
        "workspace\tpath\ttools",
        "work\t%s\tclaude,codex" % workspace,
    ]
    assert place.apply(type("Args", (), common)()) == 0
    args = type("Args", (), dict(
        common, workspace_id="work", tool="codex", tool_args=["--version"],
    ))()
    agents = workspace / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace("-->\n", "-->\ndrift\n", 1),
        encoding="utf-8",
    )
    refused = []
    try:
        place.start(
            args,
            resolver=lambda name: "/usr/bin/" + name,
            runner=lambda argv, **kwargs: refused.append((argv, kwargs)),
        )
    except place.PlacementError:
        pass
    else:
        raise AssertionError("start accepted drifted policy")
    assert refused == []
    assert place.apply(type("Args", (), common)()) == 0

    calls = []
    result = place.start(
        args,
        resolver=lambda name: "/usr/bin/" + name,
        runner=lambda argv, **kwargs: (
            calls.append((argv, kwargs))
            or subprocess.CompletedProcess(argv, 7)
        ),
    )
    assert result == 7
    assert calls == [
        (["/usr/bin/codex", "--version"], {"cwd": str(workspace)})
    ]


# The private inventory is data-only: resolve its declared sources, retain a
# placement-only site, and prove that an ordinary list never probes transport.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    declaration = root / "placement.md"
    declaration.write_text("""<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
s4\tubuntu\tagent\t/home/agent\tremote\tssh
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
work\ts4\tdirect\t/tmp\t
```
<!-- END WORKSPACES TSV -->
<!-- BEGIN LOCATIONS TSV -->
```tsv
id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
""", encoding="utf-8")
    apparatus = root / "apparatus.json"
    apparatus.write_text(json.dumps({"executor": "ubuntu", "runsRoot": "/work/runs"}), encoding="utf-8")
    catalog = root / "catalog.json"
    catalog.write_text(json.dumps({"schemaVersion": 1, "sources": {
        "root": {"type": "placement-tsv", "host": "controller", "paths": {"default": str(declaration)}},
        "apparatus": {"type": "json-pointer", "host": "controller", "paths": {"default": str(apparatus)}, "pointers": {"executor": "/executor", "runsRoot": "/runsRoot"}},
    }, "environments": [{"id": "ubuntu-24", "purposes": ["rule-experiment"], "state": "active", "refs": [
        {"source": "root", "site": "s4"}, {"source": "apparatus", "fields": {"executor": "executor", "runsRoot": "runsRoot"}}],
        "entrypoint": {"kind": "apparatus", "paths": {"default": str(apparatus)}},
        "connection": {"transport": "ssh", "target": "example"},
        "agents": [{"descriptor": "codex", "principal": {"source": "root", "site": "s4", "field": "user"}, "configRoot": {"source": "root", "site": "s4", "field": "home"}}]
    }]}), encoding="utf-8")
    listed = subprocess.run([sys.executable, str(PLACE), "list", "--catalog", str(catalog), "--purpose", "rule-experiment", "--json"], text=True, capture_output=True)
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)[0]["id"] == "ubuntu-24"
    errors, records = place.environment_inventory.check_catalog(catalog, runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected probe")))
    assert not errors and records
    calls = []
    errors, _records = place.environment_inventory.check_catalog(catalog, probe=True, runner=lambda argv, **kwargs: (calls.append(argv) or subprocess.CompletedProcess(argv, 1, "", "")))
    assert errors == ["probe unresolved for ubuntu-24: SSH observation requires a successful referenced source probe"] and calls == []

    wsl_calls = []
    def wsl_runner(argv, **kwargs):
        wsl_calls.append(argv)
        output = "Ubuntu-24.04\nUbuntu\n" if "--running" not in argv else "Ubuntu-24.04\n"
        return subprocess.CompletedProcess(argv, 0, output, "")
    probe_target = [{"connection": {"transport": "wsl", "distro": "Ubuntu-24.04"}}]
    place.environment_inventory.probe_records(probe_target, runner=wsl_runner, platform_name="nt")
    assert probe_target[0]["observation"].get("installed") is True
    assert probe_target[0]["observation"].get("running") is True
    assert wsl_calls == [["wsl.exe", "--list", "--quiet"], ["wsl.exe", "--list", "--running", "--quiet"]]

    ssh_config = root / "probe.conf"
    ssh_config.write_text("Host remote\n  HostName example.test\n  User agent\n  Port 22\n  IdentityFile /tmp/id\n  UserKnownHostsFile /tmp/known\n  ConnectTimeout 5\n", encoding="utf-8")
    remote_catalog = root / "remote-catalog.json"
    remote_catalog.write_text(json.dumps({"schemaVersion": 1, "sources": {"remote": {
        "type": "placement-tsv", "host": "remote", "path": "/policy/PLACEMENT.md", "paths": {},
        "probe": {"transport": "ssh", "target": "remote", "configPaths": {"default": str(ssh_config)}}}},
        "environments": [{"id": "remote", "purposes": ["normal-development"], "state": "active", "refs": [{"source": "remote", "site": "s4"}], "entrypoint": {"kind": "placement-start", "source": "remote", "workspace": "work"}, "agents": []}]}), encoding="utf-8")
    remote_calls = []
    def remote_runner(argv, **kwargs):
        remote_calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, declaration.read_text(encoding="utf-8"), "")
    errors, remote_records = place.environment_inventory.check_catalog(remote_catalog, probe=True, runner=remote_runner)
    assert not errors and remote_records[0]["refs"][0]["resolution"] == "resolved"
    assert remote_calls[0][-1] == "cat -- /policy/PLACEMENT.md"
    assert remote_calls[0][:3] == ["ssh", "-F", os.devnull]

    broken = json.loads(catalog.read_text(encoding="utf-8"))
    observer = os.environ.get("ENVIRONMENT_INVENTORY_HOST") or ("windows" if os.name == "nt" else "linux")
    broken["environments"][0]["entrypoint"] = {"kind": "apparatus", "paths": {observer + "-other": "/not-present"}}
    broken_path = root / "broken-entrypoint.json"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")
    _catalog, _sources, broken_records = place.environment_inventory.load_catalog(broken_path)
    assert broken_records[0]["entrypoint"]["resolution"].startswith("unverified: no path")
    broken_errors, _records = place.environment_inventory.check_catalog(broken_path, environment_id="ubuntu-24")
    assert any("unverified entrypoint" in error for error in broken_errors)

    invalid = json.loads(catalog.read_text(encoding="utf-8"))
    invalid["schemaVersion"] = True
    broken_path.write_text(json.dumps(invalid), encoding="utf-8")
    invalid_errors, _ = place.environment_inventory.check_catalog(broken_path)
    assert invalid_errors and "schemaVersion" in invalid_errors[0]
    broken_path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
    invalid_errors, _ = place.environment_inventory.check_catalog(broken_path)
    assert invalid_errors and "duplicate JSON key" in invalid_errors[0]

    # Windows writes UTF-16LE WSL names to pipes. A stopped installed distro
    # remains a selection candidate, while reachability is deliberately unknown.
    utf16_calls = []
    def utf16_wsl_runner(argv, **kwargs):
        utf16_calls.append(argv)
        names = "Ubuntu-24.04\n開発環境\n" if "--running" not in argv else "開発環境\n"
        return subprocess.CompletedProcess(argv, 0, names.encode("utf-16-le"), b"")
    stopped = [{"connection": {"transport": "wsl", "distro": "Ubuntu-24.04"}}]
    place.environment_inventory.probe_records(stopped, runner=utf16_wsl_runner, platform_name="nt")
    assert stopped[0]["observation"].get("installed") is True
    assert stopped[0]["observation"].get("running") is False
    assert stopped[0]["observation"].get("reachable") is None
    assert stopped[0]["observation"].get("unregisteredDistros") == ["開発環境"]
    assert utf16_calls == [["wsl.exe", "--list", "--quiet"], ["wsl.exe", "--list", "--running", "--quiet"]]

    def failed_running_runner(argv, **kwargs):
        code = 1 if "--running" in argv else 0
        return subprocess.CompletedProcess(argv, code, "Ubuntu-24.04\n".encode("utf-16-le"), b"")
    unknown_running = [{"connection": {"transport": "wsl", "distro": "Ubuntu-24.04"}}]
    place.environment_inventory.probe_records(unknown_running, runner=failed_running_runner, platform_name="nt")
    assert unknown_running[0]["observation"].get("installed") is True
    assert unknown_running[0]["observation"].get("running") is None

    bad_workspace = json.loads(catalog.read_text(encoding="utf-8"))
    bad_workspace["environments"][0]["entrypoint"] = {"kind": "placement-start", "source": "root", "workspace": "missing"}
    bad_workspace_path = root / "bad-workspace.json"
    bad_workspace_path.write_text(json.dumps(bad_workspace), encoding="utf-8")
    try:
        place.environment_inventory.load_catalog(bad_workspace_path)
    except place.environment_inventory.CatalogError as exc:
        assert "entrypoint workspace" in str(exc)
    else:
        raise AssertionError("placement entrypoint accepted an unknown workspace")

    null_entrypoint = json.loads(catalog.read_text(encoding="utf-8"))
    null_entrypoint["environments"][0]["entrypoint"] = None
    null_path = root / "null-entrypoint.json"
    null_path.write_text(json.dumps(null_entrypoint), encoding="utf-8")
    null_errors, null_records = place.environment_inventory.check_catalog(null_path, environment_id="ubuntu-24")
    assert not null_errors and null_records[0]["entrypoint"] is None

    scoped = json.loads(catalog.read_text(encoding="utf-8"))
    scoped["sources"]["unrelated"] = {"type": "placement-tsv", "host": "other", "paths": "malformed"}
    scoped["environments"].append({"id": "other", "purposes": ["operator"], "state": "active", "refs": [{"source": "unrelated", "site": "s4"}], "entrypoint": None, "agents": []})
    scoped_path = root / "scoped.json"
    scoped_path.write_text(json.dumps(scoped), encoding="utf-8")
    scoped_errors, scoped_records = place.environment_inventory.check_catalog(scoped_path, environment_id="ubuntu-24")
    assert not scoped_errors and [record["id"] for record in scoped_records] == ["ubuntu-24"]
