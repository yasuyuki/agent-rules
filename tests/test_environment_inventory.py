"""Focused regressions for private environment-catalog resolution."""

from pathlib import Path
import importlib.util
import json
import subprocess
import tempfile
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "environment_inventory.py"
spec = importlib.util.spec_from_file_location("environment_inventory", MODULE)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def placement(path):
    path.write_text("""<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
s2\tUbuntu\tagent\t/home/agent\twsl\t
s4\tUbuntu-24.04\tagent\t/home/agent\twsl\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
work\ts4\tdirect\t/work\t
```
<!-- END WORKSPACES TSV -->
""", encoding="utf-8")


def write_catalog(path, sources, environment):
    environments = environment if isinstance(environment, list) else [environment]
    path.write_text(json.dumps({
        "schemaVersion": 1,
        "sources": sources,
        "environments": environments,
    }), encoding="utf-8")


def environment(**overrides):
    item = {
        "id": "ubuntu-24",
        "purposes": ["rule-experiment"],
        "state": "active",
        "refs": [{"source": "placement", "site": "s4", "workspace": "work"}],
        "entrypoint": None,
        "agents": [],
    }
    item.update(overrides)
    return item


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    declaration = root / "PLACEMENT.md"
    placement(declaration)
    local_source = {
        "type": "placement-tsv", "host": "controller",
        "paths": {"default": str(declaration)},
    }
    unavailable_source = {
        "type": "placement-tsv", "host": "remote", "paths": {},
    }

    # Sources used only by an agent must still make catalog check fail closed.
    path = root / "agent-source.json"
    write_catalog(path, {"placement": local_source, "agent-runtime": unavailable_source}, environment(agents=[{
        "descriptor": "codex",
        "principal": {"source": "agent-runtime", "site": "s4", "field": "user"},
        "configRoot": {"source": "agent-runtime", "site": "s4", "tool": "codex"},
    }]))
    errors, _records = inventory.check_catalog(path)
    assert any(error.startswith("unverified source agent-runtime:") for error in errors), errors

    # Legacy source/site form is normalized for both full and targeted checks;
    # its source must never disappear from the selected dependency set.
    path = root / "legacy-source.json"
    legacy = {
        "id": "legacy", "purposes": ["recovery"], "state": "retained",
        "source": "legacy-runtime", "site": "s4", "agents": [], "entrypoint": None,
    }
    write_catalog(path, {"legacy-runtime": unavailable_source}, legacy)
    for target in (None, "legacy"):
        errors, _records = inventory.check_catalog(path, environment_id=target)
        assert any(error.startswith("unverified source legacy-runtime:") for error in errors), errors

    # A placement entrypoint's source is also required, even though its site is
    # already represented by a different, readable placement declaration.
    path = root / "entrypoint-source.json"
    write_catalog(path, {"placement": local_source, "entry-runtime": unavailable_source}, environment(entrypoint={
        "kind": "placement-start", "source": "entry-runtime", "workspace": "work",
    }))
    errors, _records = inventory.check_catalog(path)
    assert any(error.startswith("unverified source entry-runtime:") for error in errors), errors
    assert any(error.startswith("unverified entrypoint for ubuntu-24:") for error in errors), errors

    # A WSL site declared by a placement reference remains registered even
    # when that environment has no separate connection object.  The target
    # environment's normal WSL probe must not report it as unregistered.
    path = root / "placement-wsl.json"
    registered = environment(id="ubuntu", refs=[{"source": "placement", "site": "s2"}])
    target = environment(connection={"transport": "wsl", "distro": "Ubuntu-24.04"})
    write_catalog(path, {"placement": local_source}, [registered, target])
    _catalog, _sources, records = inventory.load_catalog(path)

    def wsl_runner(argv, **_kwargs):
        names = "Ubuntu-24.04\nUbuntu\n" if "--running" not in argv else "Ubuntu-24.04\n"
        return subprocess.CompletedProcess(argv, 0, names, "")

    inventory.probe_records(records, runner=wsl_runner, platform_name="nt")
    observation = records[1]["observation"]
    assert observation["installed"] is True
    assert observation["unregisteredDistros"] == []
    # A targeted preflight reads only its selected environment, so it cannot
    # make a complete unregistered-distro claim about omitted environments.
    probe_records = inventory.probe_records
    with mock.patch.object(inventory, "probe_records", side_effect=lambda records, runner, **kwargs: probe_records(records, runner, platform_name="nt", **kwargs)):
        errors, targeted_records = inventory.check_catalog(
            path, environment_id="ubuntu-24", probe=True, runner=wsl_runner,
        )
    assert not errors, errors
    targeted_observation = targeted_records[0]["observation"]
    assert targeted_observation["installed"] is True
    assert targeted_observation["running"] is True
    assert "unregisteredDistros" not in targeted_observation

    # This parser accepts only exact Host blocks.  Within those blocks it
    # follows OpenSSH's first-value behavior and keeps executable directives
    # prohibited.
    config = root / "probe.conf"
    config.write_text("""Host target
  HostName first.example
Host target
  HostName ignored.example
  User agent
""", encoding="utf-8")
    probe = {"transport": "ssh", "target": "target", "configPaths": {"default": str(config)}}
    resolved = inventory._ssh_probe_config(probe, "windows")
    assert resolved["target"] == "first.example"
    assert resolved["user"] == "agent"

    config.write_text("""Host *
  HostName different.example
Host target
  User agent
""", encoding="utf-8")
    try:
        inventory._ssh_probe_config(probe, "windows")
    except inventory.CatalogError as exc:
        assert "Host pattern" in str(exc)
    else:
        raise AssertionError("wildcard SSH config changed the explicit probe target")

    config.write_text("""Host target
  HostName %h.internal
""", encoding="utf-8")
    try:
        inventory._ssh_probe_config(probe, "windows")
    except inventory.CatalogError as exc:
        assert "value syntax" in str(exc)
    else:
        raise AssertionError("SSH token expansion was treated as a literal target")

    config.write_text("""Host target
  HostName \"quoted.example\"
""", encoding="utf-8")
    try:
        inventory._ssh_probe_config(probe, "windows")
    except inventory.CatalogError as exc:
        assert "value syntax" in str(exc)
    else:
        raise AssertionError("quoted SSH target was accepted without OpenSSH parsing")

    config.write_text("""Host target
  ProxyCommand command-that-must-not-run
""", encoding="utf-8")
    try:
        inventory._ssh_probe_config(probe, "windows")
    except inventory.CatalogError as exc:
        assert "proxycommand" in str(exc)
    else:
        raise AssertionError("executable SSH config directive was accepted")
