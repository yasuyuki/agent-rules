"""Focused regressions for private environment-catalog resolution."""

from pathlib import Path
import importlib.util
import json
import os
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
    target = environment(connection={"transport": "wsl", "distro": {
        "source": "placement", "site": "s4", "field": "host",
    }})
    ssh_source = dict(local_source, probe={"transport": "ssh", "target": "outer", "configPaths": {}})
    outer_wsl = environment(
        id="ubuntu-26", purposes=["normal-development"],
        connection={"transport": "ssh", "source": "ssh-runtime", "wslDistro": "Ubuntu-26.04"},
    )
    write_catalog(path, {"placement": local_source, "ssh-runtime": ssh_source}, [registered, target, outer_wsl])
    _catalog, _sources, records = inventory.load_catalog(path)

    def wsl_runner(argv, **_kwargs):
        names = "Ubuntu-24.04\nUbuntu\nUbuntu-26.04\nUnknown\n" if "--running" not in argv else "Ubuntu-24.04\n"
        return subprocess.CompletedProcess(argv, 0, names, "")

    inventory.probe_records(records, runner=wsl_runner, platform_name="nt")
    observation = records[1]["observation"]
    assert observation["installed"] is True
    assert observation["unregisteredDistros"] == ["Unknown"]

    invalid_outer = environment(connection={"transport": "ssh", "source": "ssh-runtime", "wslDistro": ["Ubuntu-26.04"]})
    write_catalog(path, {"placement": local_source, "ssh-runtime": ssh_source}, invalid_outer)
    try:
        inventory.load_catalog(path)
    except inventory.CatalogError as exc:
        assert "outer WSL distro" in str(exc)
    else:
        raise AssertionError("invalid outer WSL distro was accepted")

    invalid_placement_distro = environment(connection={"transport": "wsl", "distro": {
        "source": "placement", "site": "missing", "field": "host",
    }})
    write_catalog(path, {"placement": local_source}, invalid_placement_distro)
    try:
        inventory.load_catalog(path)
    except inventory.CatalogError as exc:
        assert "invalid WSL distro reference" in str(exc)
    else:
        raise AssertionError("invalid placement WSL distro reference was accepted")

    # An observer without a readable legacy WSL source retains the environment
    # as unverified; inaccessible evidence is not a malformed reference.
    unreadable_wsl = environment(connection={"transport": "wsl", "distro": {
        "source": "legacy-runtime", "site": "s4", "field": "host",
    }})
    write_catalog(path, {"placement": local_source, "legacy-runtime": unavailable_source}, unreadable_wsl)
    _catalog, _sources, unreadable_records = inventory.load_catalog(path)
    assert unreadable_records[0]["connection"]["distro"] is None
    assert unreadable_records[0]["connection"]["distroResolution"].startswith("unverified:")

    # Capability metadata is catalog data: legacy omission stays valid, but a
    # malformed declaration is rejected by normal catalog validation too.
    capability_catalog = environment(capabilities={"gui": {
        "status": "available", "reason": "fixture", "evidence": [],
    }})
    write_catalog(path, {"placement": local_source}, capability_catalog)
    _catalog, _sources, capability_records = inventory.load_catalog(path)
    assert capability_records[0]["capabilities"]["gui"]["status"] == "available"
    capability_catalog["capabilities"]["gui"].pop("evidence")
    write_catalog(path, {"placement": local_source}, capability_catalog)
    errors, _records = inventory.check_catalog(path)
    assert any("capability needs evidence" in error for error in errors), errors

    numeric_distro = root / "numeric-distro.json"
    numeric_distro.write_text(json.dumps({"distro": 24}), encoding="utf-8")
    numeric_source = {
        "type": "json-pointer", "host": "controller", "paths": {"default": str(numeric_distro)},
        "pointers": {"distro": "/distro"},
    }
    nonstring_distro = environment(connection={"transport": "wsl", "distro": {
        "source": "numeric", "field": "distro",
    }})
    write_catalog(path, {"placement": local_source, "numeric": numeric_source}, nonstring_distro)
    try:
        inventory.load_catalog(path)
    except inventory.CatalogError as exc:
        assert "non-empty string" in str(exc)
    else:
        raise AssertionError("non-string WSL distro reference was accepted")

    write_catalog(path, {"placement": local_source, "ssh-runtime": ssh_source}, [registered, target, outer_wsl])
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

    # Missing connection settings must fail before invoking any SSH runner,
    # both for config files and for inline declarations.
    fields = {
        "user": ("User", "agent"),
        "port": ("Port", 22),
        "identityFile": ("IdentityFile", "/test/id"),
        "knownHosts": ("UserKnownHostsFile", "/test/known_hosts"),
        "connectTimeout": ("ConnectTimeout", 5),
    }

    def check_probe(declaration):
        source = {"type": "json-pointer", "host": "remote", "paths": {},
                  "path": "/test/source.json", "pointers": {"user": "/user"},
                  "probe": declaration}
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, '{"user":"agent"}', ""))
        result = inventory._sources(path, {"sources": {"remote": source}}, probe=True, runner=runner)
        assert result["remote"]["probed"] is True
        runner.assert_called_once()
        return runner.call_args.args[0]

    for mode in ("config", "inline"):
        for missing in fields:
            for invalid in (None, "", "   "):
                declaration = {"transport": "ssh", "target": "target"}
                values = {key: value for key, (_option, value) in fields.items()}
                if invalid is None:
                    del values[missing]
                else:
                    values[missing] = invalid
                if mode == "config":
                    config.write_text("Host target\n  HostName example.test\n" + "".join(
                        "  %s %s\n" % (fields[key][0], value) for key, value in values.items()), encoding="utf-8")
                    declaration["configPaths"] = {"default": str(config)}
                else:
                    declaration.update(values)
                runner = mock.Mock()
                source = {"type": "json-pointer", "host": "remote", "paths": {},
                          "path": "/test/source.json", "pointers": {"user": "/user"},
                          "probe": declaration}
                try:
                    inventory._sources(path, {"sources": {"remote": source}}, probe=True, runner=runner)
                except inventory.CatalogError as exc:
                    assert missing in str(exc), str(exc)
                else:
                    raise AssertionError("missing SSH %s accepted in %s" % (missing, mode))
                runner.assert_not_called()

    complete = {"transport": "ssh", "target": "example.test",
                **{key: value for key, (_option, value) in fields.items()}}
    argv = check_probe(complete)
    for option, value in fields.values():
        assert "%s=%s" % (option, value) in argv

    # Validate the merged result: inline values may fill omissions, while
    # explicitly supplied config values keep their existing precedence.
    config.write_text("Host target\n  HostName example.test\n  User configured\n", encoding="utf-8")
    argv = check_probe(dict(complete, target="target", configPaths={"default": str(config)}))
    assert "User=configured" in argv and "User=agent" not in argv
    assert argv[-2] == "example.test"

    config.write_text("Host target\n" + "".join(
        "  %s %s\n" % (option, value) for option, value in fields.values()), encoding="utf-8")
    argv = check_probe(probe)
    assert argv[-2] == "target"

    # A write derived from a changed declaration is rejected before the atomic
    # replacement, so unrelated catalog content is never overwritten by stale
    # preparation/readiness inputs.
    stable = root / "stable.json"
    stable.write_text('{"schemaVersion": 1, "unchanged": true}\n', encoding="utf-8")
    input_file = root / "operation-input.txt"
    input_file.write_text("before\n", encoding="utf-8")
    snapshots = inventory.snapshot_inputs([input_file])
    original = stable.read_bytes()
    input_file.write_text("after\n", encoding="utf-8")
    try:
        inventory.replace_catalog(stable, original, {"schemaVersion": 1, "changed": True}, snapshots)
    except inventory.CatalogError as exc:
        assert "inputs changed" in str(exc)
    else:
        raise AssertionError("stale input published a catalog update")
    assert stable.read_bytes() == original

    # Skill source snapshots include executable mode because the loader exposes
    # it to consumers.  Bytes alone cannot prove a stable skill on POSIX.
    if os.name != "nt":
        skill_root = root / "skills"; skill = skill_root / "example"; skill.mkdir(parents=True)
        skill_file = skill / "tool"
        skill_file.write_text("same bytes\n", encoding="utf-8")
        before_mode = skill_file.stat().st_mode
        os.chmod(skill_file, before_mode ^ 0o100)
        try:
            loader_snapshot = inventory.snapshot_loader_inputs([], [skill_root])
            os.chmod(skill_file, skill_file.stat().st_mode ^ 0o100)
            try:
                inventory._assert_loader_inputs(loader_snapshot)
            except inventory.CatalogError as exc:
                assert "inputs changed" in str(exc)
            else:
                raise AssertionError("skill executable mode change was accepted")
        finally:
            os.chmod(skill_file, before_mode)

    # Failure after the durable temporary write leaves no replacement behind.
    snapshots = inventory.snapshot_inputs([input_file])
    with mock.patch.object(inventory.os, "replace", side_effect=OSError("replace failed")):
        try:
            inventory.replace_catalog(stable, original, {"schemaVersion": 1}, snapshots)
        except inventory.CatalogError as exc:
            assert "could not be saved" in str(exc)
        else:
            raise AssertionError("replace failure was accepted")
    assert not list(root.glob("stable.json.*.tmp"))

    # Official writers use the same sibling advisory lock, so a concurrent
    # operation fails closed instead of reading and replacing stale bytes.
    with inventory.locked_catalog(stable, "environment-a"):
        try:
            with inventory.locked_catalog(stable, "environment-a"):
                raise AssertionError("second catalog lock unexpectedly acquired")
        except inventory.CatalogError as exc:
            assert "busy" in str(exc)

    claim = stable.with_name(stable.name + ".claim")
    stale_claim = json.dumps({"version": 1, "scope": os.name + ":environment-a", "nonce": "stale", "catalog": stable.name}).encode("utf-8")
    claim.write_bytes(stale_claim)
    with inventory.locked_catalog(stable, "environment-a"):
        assert claim.is_file()
    assert not claim.exists()
    foreign_claim = json.dumps({"version": 1, "scope": os.name + ":environment-b", "nonce": "live", "catalog": stable.name}).encode("utf-8")
    claim.write_bytes(foreign_claim)
    try:
        with inventory.locked_catalog(stable, "environment-a"):
            raise AssertionError("foreign claim was removed")
    except inventory.CatalogError as exc:
        assert "owning environment" in str(exc)
    assert claim.read_bytes() == foreign_claim
    claim.write_bytes(b"not-json")
    try:
        with inventory.locked_catalog(stable, "environment-a"):
            raise AssertionError("malformed claim was removed")
    except inventory.CatalogError as exc:
        assert "claim is invalid" in str(exc)
    assert claim.read_bytes() == b"not-json"
    claim.unlink()

print("test_environment_inventory: OK")
