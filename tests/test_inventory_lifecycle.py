"""Regression checks for inventory readiness and target-only normal start."""
from pathlib import Path
import importlib.util
import json
import os
import platform
import tempfile
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
for name, path in (("place", ROOT / "bin" / "place.py"), ("lifecycle", ROOT / "bin" / "inventory_lifecycle.py")):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    globals()[name] = module


def declaration(home):
    return """<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
s1\t%s\t%s\t%s\tlocal\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
w1\ts1\tdirect\t%s/work\t
```
<!-- END WORKSPACES TSV -->
<!-- BEGIN LOCATIONS TSV -->
```tsv
id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind
h1\thome\ts1\tcodex\trequired\t\t\t\tskills
h2\thome\ts1\tcodex\trequired\t\t\t\trules
c1\thome\ts1\tclaude\trequired\t\t\t\tskills
c2\thome\ts1\tclaude\trequired\t\t\t\trules
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
<!-- BEGIN INVENTORY TSV -->
```tsv
site\tcatalog\tenvironment
s1\tcatalog.json\tenv
```
<!-- END INVENTORY TSV -->
""" % (platform.system(), __import__("getpass").getuser(), home, home)


def context(decl):
    placement = place.load_placement()
    rules = place.agent_rules.load_rule_dirs(placement, [str(ROOT / "rules")])
    rules.append(({"id": "environment-inventory-required", "title": "Inventory", "tools": ["codex", "claude"], "summary": "inventory"}, "inventory binding\n", {}))
    skills = place.agent_rules.load_skill_dirs([str(ROOT / "skills")])
    sites, workspaces, locations, exceptions = place.parse_declaration(decl)
    return placement, rules, sites, workspaces, locations, exceptions, [], skills


def catalog(path, decl, state="active"):
    document = {"schemaVersion": 1, "sources": {"p": {"type": "placement-tsv", "host": "test", "paths": {"default": str(decl)}}}, "environments": [{
        "id": "env", "purposes": ["normal-development"], "state": state,
        "refs": [{"source": "p", "site": "s1", "workspace": "w1"}],
        "agents": [
            {"descriptor": "codex", "principal": {"source": "p", "site": "s1", "field": "user"}, "configRoot": {"source": "p", "site": "s1", "tool": "codex"}},
            {"descriptor": "claude", "principal": {"source": "p", "site": "s1", "field": "user"}, "configRoot": {"source": "p", "site": "s1", "tool": "claude"}},
        ],
    }]}
    path.write_text(json.dumps(document), encoding="utf-8")


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    data = root / "catalog.json"; catalog(data, decl)
    document = json.loads(data.read_text(encoding="utf-8"))
    document["environments"][0]["agents"][1]["configRoot"]["source"] = "unavailable-claude"
    data.write_text(json.dumps(document), encoding="utf-8")
    ctx = context(decl)
    place.apply_projection(ctx[1], ctx[0], list(ctx[4].values()), ctx[5], ctx[2], ctx[3], ctx[7])
    old_home, old_codex_home, old_context = os.environ.get("HOME"), os.environ.get("CODEX_HOME"), place.load_context
    old_runtime = place.current_runtime
    os.environ["HOME"] = str(home)
    os.environ.pop("CODEX_HOME", None)
    place.load_context = lambda args: ctx
    # Windows Path.home uses USERPROFILE, so inject the synthetic runtime rather
    # than relying on HOME to override the real host's identity.
    place.current_runtime = lambda _context: {
        "user": __import__("getpass").getuser(), "home": str(home),
        "host": platform.system(), "platform": platform.system(),
        "configRoots": {name: tool["configHome"]["default"].replace("$HOME", str(home))
                        for name, tool in ctx[0]["tools"].items()},
    }
    args = SimpleNamespace(declaration=str(decl), workspace_id="w1", tool="codex", tool_args=["--version"])
    calls = []
    try:
        # No evidence file is involved.  A broken Claude projection cannot
        # prevent an otherwise ready Codex start.
        claude_marker = home / ".claude" / "skills" / "maintain-environment-inventory" / place.agent_rules.SKILL_MARKER
        claude_marker.unlink()
        result = place.start(args, runner=lambda argv, **kwargs: (calls.append((argv, kwargs)) or SimpleNamespace(returncode=0)), resolver=lambda name: "/bin/" + name)
        assert result == 0 and calls[-1][0] == ["/bin/codex", "--version"]
        readiness = SimpleNamespace(declaration=str(decl), site="s1", workspace=None, scope=None, readiness=True)
        try:
            place.check(readiness)
        except place.PlacementError as exc:
            assert "claude" in str(exc) or "invalid agent configRoot" in str(exc)
        else:
            raise AssertionError("readiness accepted a broken registered CLI")
        catalog(data, decl, state="pending")
        try:
            place.start(args, runner=lambda *_a, **_k: None, resolver=lambda name: "/bin/" + name)
        except place.PlacementError as exc:
            assert "active state" in str(exc)
        else:
            raise AssertionError("pending environment started")
        # Pending readiness is allowed and remains read-only; repair is still
        # reported as needed rather than silently changing the state.
        before = data.read_bytes()
        try: place.check(readiness)
        except place.PlacementError: pass
        assert data.read_bytes() == before
    finally:
        place.load_context = old_context
        place.current_runtime = old_runtime
        if old_home is None: os.environ.pop("HOME", None)
        else: os.environ["HOME"] = old_home
        if old_codex_home is None: os.environ.pop("CODEX_HOME", None)
        else: os.environ["CODEX_HOME"] = old_codex_home


# Readiness is an environment operation.  A normal unbound project may still
# use placement, but it cannot claim a readiness result.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"
    decl.write_text(declaration(home).split("<!-- BEGIN INVENTORY TSV -->")[0], encoding="utf-8")
    readiness = SimpleNamespace(declaration=str(decl), site="s1", workspace=None, scope=None,
                                rules=None, skills=None, readiness=True)
    try:
        place.check(readiness)
    except place.PlacementError as exc:
        assert "requires an INVENTORY binding" in str(exc)
    else:
        raise AssertionError("unbound declaration reported readiness")


# Construction remains a maintenance path, not an identity bypass.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    data = root / "catalog.json"; catalog(data, decl, state="pending")
    ctx = context(decl)
    place.apply_projection(ctx[1], ctx[0], list(ctx[4].values()), ctx[5], ctx[2], ctx[3], ctx[7])
    errors, _record = lifecycle.validate_lifecycle(
        data, ctx, "env", mode="construction", constructing_agent="codex", required_site="s1",
        place_module=place, declaration_path=decl,
        current_principal={"user": "other", "home": str(home), "host": platform.system(),
                           "platform": platform.system(), "configRoots": {"codex": str(home / ".codex")}},
        resolver=lambda _name: (_ for _ in ()).throw(AssertionError("foreign runtime resolved CLI")),
    )
    assert any("unverified from current runtime" in error for error in errors), errors
    managed_codex = ctx[0]["tools"]["codex"]["configHome"]["default"].replace("$HOME", str(home))
    runtime = {"user": __import__("getpass").getuser(), "home": str(home), "host": platform.system(),
               "platform": platform.system(), "configRoots": {"codex": managed_codex}}
    errors, _record = lifecycle.validate_lifecycle(
        data, ctx, "env", mode="construction", constructing_agent="codex", required_site="s1",
        place_module=place, declaration_path=decl, current_principal=runtime,
        resolver=lambda name: "/bin/codex" if name == "codex" else None,
    )
    assert not errors, errors
    catalog(data, decl)
    document = json.loads(data.read_text(encoding="utf-8"))
    environment = document["environments"][0]
    environment["source"] = "p"; environment["site"] = "s1"; environment["workspace"] = "w1"
    environment.pop("refs")
    data.write_text(json.dumps(document), encoding="utf-8")
    errors, _record = lifecycle.validate_lifecycle(
        data, ctx, "env", mode="normal", target_agent="codex", required_site="s1",
        place_module=place, declaration_path=decl, current_principal=runtime,
        resolver=lambda name: "/bin/codex" if name == "codex" else None,
    )
    assert not errors, errors
    errors, _record = lifecycle.validate_lifecycle(
        data, ctx, "env", mode="construction", constructing_agent="codex", required_site="other-site",
        place_module=place, declaration_path=decl,
        current_principal={"user": "other", "home": str(home), "host": platform.system(),
                           "platform": platform.system(), "configRoots": {"codex": str(home / ".codex")}},
    )
    assert any("selected site other-site" in error for error in errors), errors

    document = json.loads(data.read_text(encoding="utf-8"))
    document["environments"][0]["state"] = "active"
    document["environments"][0]["agents"] = [document["environments"][0]["agents"][0]]
    data.write_text(json.dumps(document), encoding="utf-8")
    roots = {name: spec["configHome"]["default"].replace("$HOME", str(home))
             for name, spec in ctx[0]["tools"].items()}
    errors, _record = lifecycle.validate_lifecycle(
        data, ctx, "env", mode="readiness", required_site="s1", place_module=place,
        declaration_path=decl,
        current_principal={**runtime, "configRoots": roots},
        resolver=lambda name: "/bin/" + name if name in {"codex", "claude"} else None,
    )
    assert any("installed supported CLI claude is unregistered" in error for error in errors), errors


for invalid in (
    SimpleNamespace(declaration="ignored", site="s1", workspace="w1", scope=None, readiness=True),
    SimpleNamespace(declaration="ignored", site="s1", workspace=None, scope="home", readiness=True),
):
    try:
        place.check(invalid)
    except place.PlacementError as exc:
        assert "cannot be combined" in str(exc)
    else:
        raise AssertionError("readiness accepted a partial placement restriction")


# Target launch never accepts a catalog config-root override, and rejects it
# before resolving or running the child CLI.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    data = root / "catalog.json"; catalog(data, decl)
    document = json.loads(data.read_text(encoding="utf-8"))
    document["environments"][0]["agents"][0]["configRoot"] = {"source": "p", "site": "s1", "field": "home"}
    data.write_text(json.dumps(document), encoding="utf-8")
    ctx = context(decl)
    errors, _ = lifecycle.validate_lifecycle(
        data, ctx, "env", mode="normal", target_agent="codex", required_site="s1", place_module=place,
        declaration_path=decl, current_principal={},
        resolver=lambda _name: (_ for _ in ()).throw(AssertionError("bad config root resolved CLI")),
    )
    assert any("effective config root" in error for error in errors), errors


# JSON scalar runtime facts must identify exactly the explicitly referenced
# placement site; a foreign/mixed source must fail before CLI lookup.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    runtime_json = root / "runtime.json"; managed = str(home / ".codex")
    runtime_json.write_text(json.dumps({"principal": __import__("getpass").getuser(), "root": managed}), encoding="utf-8")
    data = root / "catalog.json"
    data.write_text(json.dumps({"schemaVersion": 1, "sources": {
        "p": {"type": "placement-tsv", "host": "test", "paths": {"default": str(decl)}},
        "r": {"type": "json-pointer", "host": "test", "paths": {"default": str(runtime_json)}, "pointers": {"principal": "/principal", "root": "/root"}},
    }, "environments": [{"id": "env", "purposes": ["normal-development"], "state": "active", "refs": [{"source": "p", "site": "s1"}, {"source": "r", "fields": {"principal": "principal", "configRoot": "root"}}], "agents": [{"descriptor": "codex", "principal": {"source": "r", "field": "principal"}, "configRoot": {"source": "r", "field": "root"}}]}]}), encoding="utf-8")
    ctx = context(decl); place.apply_projection(ctx[1], ctx[0], list(ctx[4].values()), ctx[5], ctx[2], ctx[3], ctx[7])
    runtime = {"user": __import__("getpass").getuser(), "home": str(home), "host": platform.system(), "platform": platform.system(), "configRoots": {"codex": managed}}
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="normal", target_agent="codex", required_site="s1", place_module=place, declaration_path=decl, current_principal=runtime, resolver=lambda _n: "/bin/codex")
    assert not errors, errors
    runtime_json.write_text(json.dumps({"principal": runtime["user"], "root": str(root / "wrong")}), encoding="utf-8")
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="normal", target_agent="codex", required_site="s1", place_module=place, declaration_path=decl, current_principal=runtime, resolver=lambda _n: (_ for _ in ()).throw(AssertionError("mixed JSON runtime resolved CLI")))
    assert any("JSON runtime values do not match" in error for error in errors), errors


# A construction preflight for OpenCode recognizes the canonical Codex-only
# section in their shared AGENTS.md, without accepting an unrelated OpenCode
# file or using Codex's required artifacts on OpenCode's behalf.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    ctx = context(decl)
    ctx[1][-1][0]["tools"].append("opencode")
    for ident, tool, kind in (("c3", "codex", "rules"), ("c4", "codex", "skills"),
                              ("o1", "opencode", "rules"), ("o2", "opencode", "skills")):
        ctx[4][ident] = {"id": ident, "scope": "workspace", "anchor": "w1", "tool": tool, "requirement": "required", "reason": "", "legacy": "", "path": "", "kind": kind}
    place.apply_projection(ctx[1], ctx[0], list(ctx[4].values()), ctx[5], ctx[2], ctx[3], ctx[7])
    data = root / "catalog.json"; catalog(data, decl, state="pending")
    document = json.loads(data.read_text())
    document["environments"][0]["agents"] = [{"descriptor": "opencode", "principal": {"source": "p", "site": "s1", "field": "user"}, "configRoot": {"source": "p", "site": "s1", "tool": "opencode"}}]
    data.write_text(json.dumps(document))
    managed_root = ctx[0]["tools"]["opencode"]["configHome"]["default"].replace("$HOME", str(home))
    runtime = {"user": __import__("getpass").getuser(), "home": str(home), "host": platform.system(), "platform": platform.system(), "configRoots": {"opencode": managed_root}}
    resolve = lambda name: "/bin/opencode" if name == "opencode" else None
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="construction", constructing_agent="opencode", place_module=place, declaration_path=decl, current_principal=runtime, resolver=resolve)
    assert not errors, errors
    (home / "work" / ".codex" / "skills" / "maintain-environment-inventory" / place.agent_rules.SKILL_MARKER).unlink()
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="construction", constructing_agent="opencode", place_module=place, declaration_path=decl, current_principal=runtime, resolver=resolve)
    assert not errors, errors
    agents = home / "work" / "AGENTS.md"
    agents.write_text(place.agent_rules.splice(agents.read_text(encoding="utf-8"), "codex-subagent-routing", "drift\n"), encoding="utf-8")
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="construction", constructing_agent="opencode", place_module=place, declaration_path=decl, current_principal=runtime, resolver=resolve)
    assert any("codex-subagent-routing' differs" in error for error in errors), errors
    place.apply_projection(ctx[1], ctx[0], list(ctx[4].values()), ctx[5], ctx[2], ctx[3], ctx[7])
    (home / "work" / ".opencode" / "skills" / "maintain-environment-inventory" / place.agent_rules.SKILL_MARKER).unlink()
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="construction", constructing_agent="opencode", place_module=place, declaration_path=decl, current_principal=runtime, resolver=resolve)
    assert any("missing:" in error for error in errors), errors



# Readiness checks each CLI's actual config override; normal start remains local
# to its target. Mixed references fail before probing a foreign runtime.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    data = root / "catalog.json"; catalog(data, decl)
    ctx = context(decl)
    place.apply_projection(ctx[1], ctx[0], list(ctx[4].values()), ctx[5], ctx[2], ctx[3], ctx[7])
    roots = {name: tool["configHome"]["default"].replace("$HOME", str(home)) for name, tool in ctx[0]["tools"].items()}
    runtime = {"user": __import__("getpass").getuser(), "home": str(home), "host": platform.system(), "platform": platform.system(), "configRoots": roots}
    resolve = lambda name: "/bin/" + name if name in {"codex", "claude"} else None
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, resolver=resolve)
    assert not errors, errors
    runtime["configRoots"]["claude"] = str(root / "wrong")
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, resolver=resolve)
    assert any("claude runtime principal" in error for error in errors), errors
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="normal", target_agent="codex", required_site="s1", place_module=place, declaration_path=decl, current_principal=runtime, resolver=resolve)
    assert not errors, errors
    document = json.loads(data.read_text())
    document["sources"]["other"] = document["sources"]["p"].copy()
    document["environments"][0]["agents"][0]["configRoot"]["source"] = "other"
    data.write_text(json.dumps(document))
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="normal", target_agent="codex", required_site="s1", place_module=place, declaration_path=decl, current_principal=runtime, resolver=lambda _n: (_ for _ in ()).throw(AssertionError("mixed source resolved CLI")))
    assert any("must share catalog source and site" in error for error in errors), errors
    decl.write_text(declaration(home).replace("site\tcatalog\tenvironment\n", "site\tcatalog\tenvironment\tevidence\n"), encoding="utf-8")
    try:
        place.inventory_binding(SimpleNamespace(declaration=str(decl)), ctx, "s1")
    except place.PlacementError as exc:
        assert "exactly site, catalog, environment" in str(exc)
    else:
        raise AssertionError("legacy four-column binding was accepted")

for argv in (
    ["check", "--declaration", "unused", "--readiness"],
    ["check", "--catalog", "unused", "--site", "s1", "--readiness"],
    ["check", "--declaration", "unused", "--site", "s1", "--readiness", "--environment", "env"],
):
    assert place.main(argv) == 1, argv
