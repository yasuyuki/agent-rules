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
    rules.append(({"id": "environment-inventory-required", "title": "Inventory", "tools": ["codex", "claude", "grok"], "summary": "inventory"}, "inventory binding\n", {}))
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

# A saved start choice is the only implicit input: it resolves its paths from
# its own directory, checks only the selected CLI, and gives the child the
# inventory host without leaking it into the caller.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    data = root / "catalog.json"; catalog(data, decl)
    extra = root / "extra-rules"; extra.mkdir()
    (extra / "environment-inventory-required.rule.md").write_text(
        "---\nid: environment-inventory-required\ntitle: Inventory\nsummary: inventory\n---\n\ninventory binding\n",
        encoding="utf-8")
    ctx = place.load_context(SimpleNamespace(declaration=str(decl), rules=[str(extra)], skills=None))
    place.apply_projection(ctx[1], ctx[0], list(ctx[4].values()), ctx[5], ctx[2], ctx[3], ctx[7])
    # A different registered CLI is broken, but it is not part of this launch.
    (home / ".claude" / "skills" / "maintain-environment-inventory" / place.agent_rules.SKILL_MARKER).unlink()
    config = root / "placement-start.json"
    config.write_text(json.dumps({"version": 1, "declaration": "placement.md",
                                  "rules": ["extra-rules"],
                                  "inventory_host": "inventory.test"}), encoding="utf-8")
    calls = []
    old_cwd = os.getcwd(); old_host = os.environ.get("ENVIRONMENT_INVENTORY_HOST")
    old_runtime = place.current_runtime
    place.current_runtime = lambda _context: {
        "user": __import__("getpass").getuser(), "home": str(home),
        "host": platform.system(), "platform": platform.system(),
        "configRoots": {name: tool["configHome"]["default"].replace("$HOME", str(home))
                        for name, tool in ctx[0]["tools"].items()},
    }
    os.environ.pop("ENVIRONMENT_INVENTORY_HOST", None)
    try:
        os.chdir(root)
        result = place.main(["start", "w1", "codex", "--version"],
                            runner=lambda argv, **kwargs: (calls.append((argv, kwargs)) or SimpleNamespace(returncode=0)),
                            resolver=lambda name: "/bin/" + name)
        assert result == 0 and calls[-1][0] == ["/bin/codex", "--version"]
        assert Path(calls[-1][1]["cwd"]) == home / "work"
        assert calls[-1][1]["env"]["ENVIRONMENT_INVENTORY_HOST"] == "inventory.test"
        assert "ENVIRONMENT_INVENTORY_HOST" not in os.environ
        os.chdir(home)
        assert place.main(["start", "--config", str(config), "w1", "codex", "--resume"],
                          runner=lambda argv, **kwargs: (calls.append((argv, kwargs)) or SimpleNamespace(returncode=0)),
                          resolver=lambda name: "/bin/" + name) == 0
        assert calls[-1][0] == ["/bin/codex", "--resume"]
        os.chdir(root)
        assert place.main(["start", "--config", str(config), "--declaration", str(decl), "w1", "codex"],
                          resolver=lambda _name: None) == 1
        assert place.main(["start", "--rules", "extra-rules", "w1", "codex"],
                          resolver=lambda _name: None) == 1
        os.environ["ENVIRONMENT_INVENTORY_HOST"] = "other.inventory"
        assert place.main(["start", "w1", "codex"], resolver=lambda _name: None) == 1
        os.environ.pop("ENVIRONMENT_INVENTORY_HOST", None)
        config.write_text("[]", encoding="utf-8")
        assert place.main(["start", "w1", "codex"], resolver=lambda _name: None) == 1
        config.write_text(json.dumps({"version": 1, "declaration": "placement.md", "rules": None}), encoding="utf-8")
        assert place.main(["start", "w1", "codex"], resolver=lambda _name: None) == 1
        config.write_bytes(b"\xff")
        assert place.main(["start", "w1", "codex"], resolver=lambda _name: None) == 1
        # An explicit declaration retains its established behavior and ignores
        # a malformed implicit config in the current directory.
        assert place.main(["start", "--declaration", str(decl), "--rules", str(extra), "w1", "codex"],
                          runner=lambda *_a, **_k: SimpleNamespace(returncode=0),
                          resolver=lambda name: "/bin/" + name) == 0
    finally:
        place.current_runtime = old_runtime
        os.chdir(old_cwd)
        if old_host is None: os.environ.pop("ENVIRONMENT_INVENTORY_HOST", None)
        else: os.environ["ENVIRONMENT_INVENTORY_HOST"] = old_host


for argv in (
    ["check", "--declaration", "unused", "--readiness"],
    ["check", "--catalog", "unused", "--site", "s1", "--readiness"],
    ["check", "--declaration", "unused", "--site", "s1", "--readiness", "--environment", "env"],
):
    assert place.main(argv) == 1, argv


# The bounded update commands derive the agent's runtime references from the
# selected declaration.  They neither install a CLI nor turn a failed
# readiness check into an active catalog record.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"
    declaration_text = declaration(home).replace(
        "c2\thome\ts1\tclaude\trequired\t\t\t\trules\n",
        "c2\thome\ts1\tclaude\trequired\t\t\t\trules\n"
        "g1\thome\ts1\tgrok\trequired\t\t\t\tskills\n"
        "g2\thome\ts1\tgrok\trequired\t\t\t\trules\n",
    )
    decl.write_text(declaration_text, encoding="utf-8")
    data = root / "catalog.json"; catalog(data, decl, state="active")
    document = json.loads(data.read_text(encoding="utf-8"))
    document["preserved"] = {"outside": True}
    document["environments"][0]["preserved"] = "value"
    data.write_text(json.dumps(document), encoding="utf-8")
    ctx = context(decl)
    ctx = (ctx[0], [rule for rule in ctx[1] if rule[0].get("id") != "environment-inventory-required"] +
           [({"id": "environment-inventory-required", "title": "Inventory", "tools": ["codex", "claude", "grok"], "summary": "inventory"}, "inventory binding\n", {})],
           *ctx[2:])
    roots = {name: tool["configHome"]["default"].replace("$HOME", str(home))
             for name, tool in ctx[0]["tools"].items()}
    runtime = {"user": __import__("getpass").getuser(), "home": str(home),
               "host": platform.system(), "platform": platform.system(), "configRoots": roots}
    args = SimpleNamespace(declaration=str(decl), site="s1", tool="grok", rules=None, skills=None)
    old_runtime = place.current_runtime
    old_context = place.load_context
    try:
        place.load_context = lambda _args: ctx
        place.current_runtime = lambda _context: runtime
        before = data.read_bytes()
        unknown = SimpleNamespace(**vars(args)); unknown.tool = "unknown"
        try:
            place.inventory_prepare_agent(unknown)
        except place.PlacementError:
            pass
        else:
            raise AssertionError("unknown tool was registered")
        assert data.read_bytes() == before
        conflicting = json.loads(before)
        conflicting["environments"][0]["agents"].append({
            "descriptor": "grok", "principal": {"source": "p", "site": "s1", "field": "user"},
            "configRoot": {"source": "p", "site": "s1", "field": "home"},
        })
        data.write_text(json.dumps(conflicting), encoding="utf-8")
        conflict_bytes = data.read_bytes()
        try:
            place.inventory_prepare_agent(args)
        except place.PlacementError:
            pass
        else:
            raise AssertionError("conflicting agent was replaced")
        assert data.read_bytes() == conflict_bytes
        data.write_bytes(before)
        wrong_runtime = dict(runtime, configRoots=dict(runtime["configRoots"], grok=str(home / "wrong")))
        place.current_runtime = lambda _context: wrong_runtime
        try:
            place.inventory_prepare_agent(args)
        except place.PlacementError:
            pass
        else:
            raise AssertionError("wrong config root was registered")
        assert data.read_bytes() == before
        def changed_context(_args):
            decl.write_text(decl.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return ctx
        place.load_context = changed_context
        try:
            place.inventory_prepare_agent(args)
        except place.PlacementError as exc:
            assert "inputs changed" in str(exc)
        else:
            raise AssertionError("declaration change during context load was accepted")
        assert data.read_bytes() == before
        place.load_context = lambda _args: ctx
        place.current_runtime = lambda _context: runtime
        assert place.inventory_prepare_agent(args) == 0
        prepared = json.loads(data.read_text(encoding="utf-8"))
        environment = prepared["environments"][0]
        assert environment["state"] == "pending"
        assert environment["preserved"] == "value" and prepared["preserved"] == {"outside": True}
        grok = [agent for agent in environment["agents"] if agent["descriptor"] == "grok"]
        assert grok == [{"descriptor": "grok", "principal": {"source": "p", "site": "s1", "field": "user"},
                         "configRoot": {"source": "p", "site": "s1", "tool": "grok"}}]
        prepared_bytes = data.read_bytes()
        assert place.inventory_prepare_agent(args) == 0
        assert data.read_bytes() == prepared_bytes
        # No projection yet: activation reports failure and leaves pending.
        try:
            place.inventory_activate(args, resolver=lambda name: "/bin/" + name if name in {"codex", "claude", "grok"} else None)
        except place.PlacementError:
            pass
        else:
            raise AssertionError("activation accepted missing managed outputs")
        assert json.loads(data.read_text(encoding="utf-8"))["environments"][0]["state"] == "pending"
        place.apply_projection(ctx[1], ctx[0], list(ctx[4].values()), ctx[5], ctx[2], ctx[3], ctx[7])
        original_replace = place.environment_inventory.replace_catalog
        def stale_replace(*values):
            decl.write_text(decl.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            return original_replace(*values)
        place.environment_inventory.replace_catalog = stale_replace
        try:
            place.inventory_activate(args, resolver=lambda name: "/bin/" + name if name in {"codex", "claude", "grok"} else None)
        except place.PlacementError as exc:
            assert "inputs changed" in str(exc)
        else:
            raise AssertionError("activation published after a stale declaration change")
        finally:
            place.environment_inventory.replace_catalog = original_replace
        assert json.loads(data.read_text(encoding="utf-8"))["environments"][0]["state"] == "pending"
        assert place.main(["inventory", "activate", "--declaration", str(decl), "--site", "s1"],
                          resolver=lambda name: "/bin/" + name if name in {"codex", "claude", "grok"} else None) == 0
        assert json.loads(data.read_text(encoding="utf-8"))["environments"][0]["state"] == "active"
    finally:
        place.current_runtime = old_runtime
        place.load_context = old_context


print("test_inventory_lifecycle: OK")
