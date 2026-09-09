"""Synthetic checks for the bounded environment lifecycle validator."""
from pathlib import Path
import importlib.util
import json
import hashlib
import tempfile
import os
import getpass
import platform
from unittest import mock
from types import SimpleNamespace


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
s1\tlinux\tagent\t%s\tlocal\t
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
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
""" % (home, home)


def context(decl):
    placement = place.load_placement()
    rules = place.agent_rules.load_rule_dirs(placement, [str(ROOT / "rules")])
    # Add the binding only in synthetic source; real integration supplies it.
    binding = ({"id": "environment-inventory-required", "title": "Inventory", "tools": ["codex"], "summary": "inventory"}, "inventory binding\n", {})
    rules.append(binding)
    skills = place.agent_rules.load_skill_dirs([str(ROOT / "skills")])
    sites, workspaces, locations, exceptions = place.parse_declaration(decl)
    return {"placement": placement, "rules": rules, "sites": sites, "workspaces": workspaces,
            "locations": locations, "exceptions": exceptions, "skills": skills}


def catalog(path, decl, state="active", descriptor="codex"):
    item = {"id": "env", "purposes": ["normal-development"], "state": state,
            "refs": [{"source": "p", "site": "s1", "workspace": "w1"}],
            "agents": [{"descriptor": descriptor,
                        "principal": {"source": "p", "site": "s1", "field": "user"},
                        "configRoot": {"source": "p", "site": "s1", "tool": descriptor}}]}
    path.write_text(json.dumps({"schemaVersion": 1, "sources": {"p": {"type": "placement-tsv", "host": "test", "paths": {"default": str(decl)}}}, "environments": [item]}), encoding="utf-8")


def evidence(ctx, root, decl, descriptor="codex"):
    skill = hashlib.sha256(ctx["skills"]["maintain-environment-inventory"]["SKILL.md"]).hexdigest()
    binding = next(rule[1] for rule in ctx["rules"] if rule[0]["id"] == "environment-inventory-required")
    binding = hashlib.sha256(binding.encode("utf-8") if isinstance(binding, str) else binding).hexdigest()
    result = []
    for session in ("continuing", "startup"):
        record = root / (session + ".json"); record.write_text("observed\n", encoding="utf-8")
        result.append({"descriptor": descriptor, "skillId": "maintain-environment-inventory", "session": session,
             "observedAt": "2026-09-09T00:00:00Z", "condition": "construction", "applied": True,
             "record": str(record), "recordSha256": hashlib.sha256(record.read_bytes()).hexdigest(),
             "principal": ctx["sites"]["s1"]["user"], "configRoot": ctx["placement"]["tools"][descriptor]["configHome"]["default"].replace("$HOME", str(root / "home")),
             "environmentId": "env", "declarationSha256": hashlib.sha256(decl.read_bytes()).hexdigest(),
             "skillSha256": skill, "bindingSha256": binding})
    return result


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    data = root / "catalog.json"; catalog(data, decl)
    ctx = context(decl)
    # Before projection, lifecycle detects missing managed bytes; after repair it passes.
    runtime = {"user": "agent", "home": str(home), "host": "linux", "platform": "Linux", "configRoots": {"codex": ctx["placement"]["tools"]["codex"]["configHome"]["default"].replace("$HOME", str(home))}}
    resolve = lambda name: "/bin/codex" if name == "codex" else None
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=evidence(ctx, root, decl), resolver=resolve)
    assert any("missing:" in error for error in errors), errors
    place.apply_projection(ctx["rules"], ctx["placement"], list(ctx["locations"].values()), ctx["exceptions"], ctx["sites"], ctx["workspaces"], ctx["skills"])
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=evidence(ctx, root, decl), resolver=resolve)
    assert not errors, errors
    marker = home / ".codex" / "skills" / "maintain-environment-inventory" / ".agent-rules-skill"
    marker.write_text("drift\n", encoding="utf-8")
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=evidence(ctx, root, decl), resolver=resolve)
    assert any("managed skill" in error or "differs from canonical" in error for error in errors), errors


# A catalog's effective config root must be the root where placement verifies
# managed bytes. A mismatch blocks normal start before its runner is called.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    user = __import__("pwd").getpwuid(os.getuid()).pw_name if os.name == "posix" else getpass.getuser()
    decl = root / "placement.md"
    text = declaration(home).replace("linux\tagent", platform.system() + "\t" + user)
    decl.write_text(text + """<!-- BEGIN INVENTORY TSV -->
```tsv
site\tcatalog\tenvironment\tevidence
s1\tcatalog.json\tenv\tevidence.json
```
<!-- END INVENTORY TSV -->
""", encoding="utf-8")
    ctx = context(decl); place.apply_projection(ctx["rules"], ctx["placement"], list(ctx["locations"].values()), ctx["exceptions"], ctx["sites"], ctx["workspaces"], ctx["skills"])
    data = root / "catalog.json"; catalog(data, decl)
    document = json.loads(data.read_text(encoding="utf-8"))
    document["environments"][0]["agents"][0]["configRoot"] = {"source": "p", "site": "s1", "field": "home"}
    data.write_text(json.dumps(document), encoding="utf-8")
    old_home, old_codex_home, old_context = os.environ.get("HOME"), os.environ.get("CODEX_HOME"), place.load_context
    os.environ["HOME"] = str(home); os.environ.pop("CODEX_HOME", None)
    home_patch = mock.patch.object(place.Path, "home", return_value=home); home_patch.start()
    place.load_context = lambda args: (ctx["placement"], ctx["rules"], ctx["sites"], ctx["workspaces"], ctx["locations"], ctx["exceptions"], [], ctx["skills"])
    calls = []
    try:
        (root / "evidence.json").write_text(json.dumps(evidence(ctx, root, decl)), encoding="utf-8")
        args = SimpleNamespace(declaration=str(decl), workspace_id="w1", tool="codex", tool_args=["--version"])
        try: place.start(args, runner=lambda *a, **k: calls.append(a), resolver=lambda n: "/bin/codex" if n == "codex" else None)
        except place.PlacementError as exc: assert "effective config root" in str(exc)
        else: raise AssertionError("mismatched config root started CLI")
        assert not calls
        document["environments"][0]["agents"][0]["configRoot"] = {"source": "p", "site": "s1", "tool": "codex"}
        data.write_text(json.dumps(document), encoding="utf-8")
        assert place.start(args, runner=lambda argv, **kwargs: (calls.append((argv, kwargs)) or SimpleNamespace(returncode=0)), resolver=lambda n: "/bin/codex" if n == "codex" else None) == 0
    finally:
        home_patch.stop(); place.load_context = old_context
        if old_home is None: os.environ.pop("HOME", None)
        else: os.environ["HOME"] = old_home
        if old_codex_home is None: os.environ.pop("CODEX_HOME", None)
        else: os.environ["CODEX_HOME"] = old_codex_home


# Scalar JSON runtime values are accepted only when they agree with the
# environment's explicit placement declaration and site.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    runtime_json = root / "runtime.json"
    data = root / "catalog.json"
    data.write_text(json.dumps({"schemaVersion": 1, "sources": {
        "p": {"type": "placement-tsv", "host": "test", "paths": {"default": str(decl)}},
        "runtime": {"type": "json-pointer", "host": "test", "paths": {"default": str(runtime_json)},
                    "pointers": {"principal": "/principal", "configRoot": "/configRoot"}},
    }, "environments": [{"id": "env", "purposes": ["normal-development"], "state": "active",
        "refs": [{"source": "p", "site": "s1"}, {"source": "runtime", "fields": {"principal": "principal", "configRoot": "configRoot"}}],
        "agents": [{"descriptor": "codex", "principal": {"source": "runtime", "field": "principal"},
                    "configRoot": {"source": "runtime", "field": "configRoot"}}],
    }]}), encoding="utf-8")
    ctx = context(decl); place.apply_projection(ctx["rules"], ctx["placement"], list(ctx["locations"].values()), ctx["exceptions"], ctx["sites"], ctx["workspaces"], ctx["skills"])
    managed_root = ctx["placement"]["tools"]["codex"]["configHome"]["default"].replace("$HOME", str(home))
    runtime_json.write_text(json.dumps({"principal": "agent", "configRoot": managed_root}), encoding="utf-8")
    runtime = {"user": "agent", "home": str(home), "host": "linux", "platform": "Linux", "configRoots": {"codex": managed_root}}
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=evidence(ctx, root, decl), resolver=lambda name: "/bin/codex" if name == "codex" else None)
    assert not errors, errors
    runtime_json.write_text(json.dumps({"principal": "agent", "configRoot": str(root / "wrong")}), encoding="utf-8")
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=evidence(ctx, root, decl), resolver=lambda name: (_ for _ in ()).throw(AssertionError("mismatched JSON runtime resolved CLI")))
    assert any("JSON runtime values do not match" in error for error in errors), errors

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    ctx = context(decl); place.apply_projection(ctx["rules"], ctx["placement"], list(ctx["locations"].values()), ctx["exceptions"], ctx["sites"], ctx["workspaces"], ctx["skills"])
    data = root / "catalog.json"; catalog(data, decl, state="pending")
    runtime = {"user": "agent", "home": str(home), "host": "linux", "platform": "Linux", "configRoots": {"codex": ctx["placement"]["tools"]["codex"]["configHome"]["default"].replace("$HOME", str(home))}}
    resolve = lambda name: "/bin/codex" if name == "codex" else None
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="construction", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=[], resolver=resolve)
    assert not errors, errors
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", mode="normal", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=[], resolver=resolve)
    assert any("requires active" in error for error in errors), errors
    catalog(data, decl)
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=evidence(ctx, root, decl), resolver=lambda name: "/bin/claude" if name == "claude" else ("/bin/codex" if name == "codex" else None))
    assert any("installed supported CLI claude is unregistered" in error for error in errors), errors
    catalog(data, decl)
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal={"user": "other", "home": str(home), "host": "linux", "platform": "Linux", "configRoots": {"codex": str(home / ".codex")}}, session_evidence=evidence(ctx, root, decl), resolver=lambda name: (_ for _ in ()).throw(AssertionError("foreign PATH must not resolve")))
    assert any("unverified from current runtime" in error for error in errors), errors


# Each registered CLI has its own effective config root; a single override must
# not be mistaken for a shared runtime root.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    decl = root / "placement.md"; decl.write_text(declaration(home), encoding="utf-8")
    ctx = context(decl)
    for ident, kind in (("h3", "skills"), ("h4", "rules")):
        ctx["locations"][ident] = {"id": ident, "scope": "home", "anchor": "s1", "tool": "claude", "requirement": "required", "reason": "", "legacy": "", "path": "", "kind": kind}
    ctx["rules"][-1][0]["tools"].append("claude")
    place.apply_projection(ctx["rules"], ctx["placement"], list(ctx["locations"].values()), ctx["exceptions"], ctx["sites"], ctx["workspaces"], ctx["skills"])
    data = root / "catalog.json"; catalog(data, decl)
    document = json.loads(data.read_text(encoding="utf-8")); document["environments"][0]["agents"].append({"descriptor": "claude", "principal": {"source": "p", "site": "s1", "field": "user"}, "configRoot": {"source": "p", "site": "s1", "tool": "claude"}})
    data.write_text(json.dumps(document), encoding="utf-8")
    ev = evidence(ctx, root, decl) + evidence(ctx, root, decl, "claude")
    roots = {name: tool["configHome"]["default"].replace("$HOME", str(home)) for name, tool in ctx["placement"]["tools"].items()}
    runtime = {"user": "agent", "home": str(home), "host": "linux", "platform": "Linux", "configRoots": roots}
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=ev, resolver=lambda name: "/bin/" + name if name in {"codex", "claude"} else None)
    assert not errors, errors
    runtime["configRoots"]["claude"] = str(root / "wrong")
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal=runtime, session_evidence=ev, resolver=lambda name: "/bin/" + name if name in {"codex", "claude"} else None)
    assert any("claude runtime principal" in error for error in errors), errors
    ev[0]["environmentId"] = "other"
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal={**runtime, "configRoots": roots}, session_evidence=ev, resolver=lambda name: "/bin/" + name if name in {"codex", "claude"} else None)
    assert any("codex: missing initial" in error for error in errors), errors
    # A declaration edit invalidates otherwise well-formed observations.
    ev = evidence(ctx, root, decl) + evidence(ctx, root, decl, "claude")
    decl.write_text(decl.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal={**runtime, "configRoots": roots}, session_evidence=ev, resolver=lambda name: "/bin/" + name if name in {"codex", "claude"} else None)
    assert any("missing initial" in error for error in errors), errors
    # A mixed source/site must fail before any resolver (including the later
    # installed-CLI scan) can inspect the caller's runtime.
    document["environments"][0]["agents"] = [document["environments"][0]["agents"][0]]
    document["sources"]["other"] = document["sources"]["p"].copy()
    document["environments"][0]["agents"][0]["configRoot"]["source"] = "other"
    data.write_text(json.dumps(document), encoding="utf-8")
    errors, _ = lifecycle.validate_lifecycle(data, ctx, "env", place_module=place, declaration_path=decl, current_principal={**runtime, "configRoots": roots}, session_evidence=[], resolver=lambda name: (_ for _ in ()).throw(AssertionError("mixed reference resolved CLI")))
    assert any("share catalog source and site" in error for error in errors), errors


# The normal public start path has no construction bypass: an explicit INVENTORY
# binding stops before its runner until lifecycle bytes and external evidence are valid.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); home = root / "home"; (home / "work").mkdir(parents=True)
    user = __import__("pwd").getpwuid(os.getuid()).pw_name if os.name == "posix" else getpass.getuser()
    decl = root / "placement.md"
    text = declaration(home).replace("linux\tagent", platform.system() + "\t" + user)
    decl.write_text(text + """<!-- BEGIN INVENTORY TSV -->
```tsv
site\tcatalog\tenvironment\tevidence
s1\tcatalog.json\tenv\tevidence.json
```
<!-- END INVENTORY TSV -->
""", encoding="utf-8")
    ctx = context(decl); place.apply_projection(ctx["rules"], ctx["placement"], list(ctx["locations"].values()), ctx["exceptions"], ctx["sites"], ctx["workspaces"], ctx["skills"])
    data = root / "catalog.json"; catalog(data, decl)
    old_home, old_codex_home, old_context = os.environ.get("HOME"), os.environ.get("CODEX_HOME"), place.load_context
    os.environ["HOME"] = str(home)
    os.environ.pop("CODEX_HOME", None)
    home_patch = mock.patch.object(place.Path, "home", return_value=home)
    home_patch.start()
    place.load_context = lambda args: (ctx["placement"], ctx["rules"], ctx["sites"], ctx["workspaces"], ctx["locations"], ctx["exceptions"], [], ctx["skills"])
    args = SimpleNamespace(declaration=str(decl), workspace_id="w1", tool="codex", tool_args=["--version"])
    calls = []
    try:
        # Missing external evidence blocks before runner.
        (root / "evidence.json").write_text("[]", encoding="utf-8")
        try: place.start(args, runner=lambda *a, **k: calls.append(a), resolver=lambda n: "/bin/codex" if n == "codex" else None)
        except place.PlacementError: pass
        else: raise AssertionError("missing evidence started CLI")
        assert not calls
        ev = evidence(ctx, root, decl)
        (root / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
        assert place.start(args, runner=lambda argv, **kwargs: (calls.append((argv, kwargs)) or SimpleNamespace(returncode=0)), resolver=lambda n: "/bin/codex" if n == "codex" else None) == 0
        assert calls[-1][0] == ["/bin/codex", "--version"]
        catalog(data, decl, state="pending")
        try: place.start(args, runner=lambda *a, **k: calls.append(a), resolver=lambda n: "/bin/codex" if n == "codex" else None)
        except place.PlacementError: pass
        else: raise AssertionError("pending environment started CLI")
        (root / "evidence.json").unlink()
        place.inventory_preflight(args, place.load_context(args), "s1", mode="construction",
                                  constructing_agent="codex", resolver=lambda n: "/bin/codex" if n == "codex" else None)
        (root / "evidence.json").write_text(json.dumps(ev), encoding="utf-8")
        catalog(data, decl)
        marker = home / ".codex" / "skills" / "maintain-environment-inventory" / place.agent_rules.SKILL_MARKER
        marker.unlink()
        try: place.start(args, runner=lambda *a, **k: calls.append(a), resolver=lambda n: "/bin/codex" if n == "codex" else None)
        except place.PlacementError: pass
        else: raise AssertionError("missing skill started CLI")
        catalog(data, decl, state="pending")
        try:
            place.inventory_preflight(args, place.load_context(args), "s1", mode="construction",
                                      constructing_agent="codex", resolver=lambda n: "/bin/codex" if n == "codex" else None)
        except place.PlacementError: pass
        else: raise AssertionError("construction accepted missing skill")
    finally:
        home_patch.stop()
        place.load_context = old_context
        if old_home is None: os.environ.pop("HOME", None)
        else: os.environ["HOME"] = old_home
        if old_codex_home is None: os.environ.pop("CODEX_HOME", None)
        else: os.environ["CODEX_HOME"] = old_codex_home
