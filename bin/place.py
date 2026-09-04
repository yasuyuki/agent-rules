#!/usr/bin/env python3
"""Project rules and skills onto the sites and workspaces a declaration names.

    place.py check  --declaration <path> --rules <dir> [--skills <dir>]
    place.py apply  --declaration <path> --rules <dir> [--skills <dir>]
    place.py mirror --skills <dir> --dest <dir> [--check]
    place.py selfcheck

Rules and skills are the two managed kinds; a LOCATIONS row says which one it
carries in its `kind` column. Both are copied from a canonical source and
compared byte for byte, so drift is a check failure rather than a silent
divergence between tools.

Optional --site / --workspace / --scope restrict which location rows apply.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PLACEMENT = ROOT / "placement.json"
FIXTURE_DECL = ROOT / "tests" / "fixtures" / "place" / "declaration.md"

spec = importlib.util.spec_from_file_location("agent_rules", HERE / "rules.py")
agent_rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_rules)


class PlacementError(RuntimeError):
    pass


def markdown_tsv(path, name, source=None):
    text = source if source is not None else Path(path).read_text(encoding="utf-8")
    match = re.search(
        r"<!-- BEGIN %s TSV -->\s*```tsv\n(.*?)```\s*<!-- END %s TSV -->"
        % (re.escape(name), re.escape(name)),
        text,
        re.S,
    )
    if not match:
        raise PlacementError("%s: missing %s TSV" % (path, name))
    lines = [line.rstrip("\r") for line in match.group(1).splitlines() if line]
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        if len(values) < len(header):
            values.extend([""] * (len(header) - len(values)))
        if len(values) != len(header):
            raise PlacementError("%s: malformed %s TSV row: %s" % (path, name, line))
        rows.append(dict(zip(header, values)))
    return rows


def load_placement():
    with open(PLACEMENT, encoding="utf-8") as handle:
        return json.load(handle)


def expand_home(template, home):
    home = Path(home).as_posix()
    return Path(template.replace("$HOME", home))


def parse_declaration(path, text=None):
    source = text if text is not None else Path(path).read_text(encoding="utf-8")
    sites = {row["id"]: row for row in markdown_tsv(path, "SITES", source)}
    workspaces = {row["id"]: row for row in markdown_tsv(path, "WORKSPACES", source)}
    locations = markdown_tsv(path, "LOCATIONS", source)
    exceptions = markdown_tsv(path, "EXCEPTIONS", source)
    if len(sites) != len(list(markdown_tsv(path, "SITES", source))):
        raise PlacementError("duplicate site id")
    by_id = {}
    for row in locations:
        if row["id"] in by_id:
            raise PlacementError("duplicate location id: %s" % row["id"])
        if row["requirement"] not in ("required", "absent"):
            raise PlacementError("location %s: requirement must be required or absent" % row["id"])
        if row["requirement"] == "absent" and not row.get("reason", "").strip():
            raise PlacementError("location %s: absent needs a reason" % row["id"])
        if row["scope"] not in ("home", "workspace", "hooks"):
            raise PlacementError("location %s: unknown scope" % row["id"])
        row["kind"] = row.get("kind", "").strip() or "rules"
        if row["kind"] not in ("rules", "skills"):
            raise PlacementError("location %s: unknown kind" % row["id"])
        if row["kind"] == "skills" and row["scope"] == "hooks":
            raise PlacementError("location %s: hooks scope has no skills kind" % row["id"])
        if row["scope"] == "workspace":
            if row["anchor"] not in workspaces:
                raise PlacementError("location %s: unknown workspace %s" % (row["id"], row["anchor"]))
        elif row["anchor"] not in sites:
            raise PlacementError("location %s: unknown site %s" % (row["id"], row["anchor"]))
        by_id[row["id"]] = row
    exception_map = {}
    if exceptions and "artifact" not in exceptions[0]:
        raise PlacementError("%s: EXCEPTIONS names an artifact id; the column 'rule' is now 'artifact'" % path)
    for row in exceptions:
        key = (row["artifact"], row["location_id"])
        if key in exception_map:
            raise PlacementError("duplicate exception: %s/%s" % key)
        if row["location_id"] not in by_id:
            raise PlacementError("exception for unknown location %s" % row["location_id"])
        if row["requirement"] not in ("required", "absent"):
            raise PlacementError("exception %s/%s: bad requirement" % key)
        if row["requirement"] == "absent" and not row.get("reason", "").strip():
            raise PlacementError("exception %s/%s: absent needs a reason" % key)
        exception_map[key] = row
    return sites, workspaces, by_id, exception_map


def site_of(location, workspaces):
    if location["scope"] == "workspace":
        return workspaces[location["anchor"]]["site"]
    return location["anchor"]


def filter_locations(locations, workspaces, site=None, workspace=None, scope=None):
    scopes = {item.strip() for item in scope.split(",")} if scope else None
    out = []
    for loc in locations.values():
        if site and site_of(loc, workspaces) != site:
            continue
        if workspace and not (loc["scope"] == "workspace" and loc["anchor"] == workspace):
            continue
        if scopes and loc["scope"] not in scopes:
            continue
        out.append(loc)
    return out


def artifact_applies(artifact_id, location, exceptions):
    """Shared gate for both managed kinds: an EXCEPTIONS row wins, otherwise the
    location's own requirement decides."""
    key = (artifact_id, location["id"])
    if key in exceptions:
        return exceptions[key]["requirement"] == "required"
    if location["requirement"] != "required":
        return False
    return location["scope"] in ("home", "workspace")


def rule_applies(meta, location, exceptions, placement):
    if location["kind"] != "rules":
        return False
    if not artifact_applies(meta["id"], location, exceptions):
        return False
    return location["tool"] in agent_rules.selected_tools(meta, placement)


def skill_applies(skill_id, location, exceptions):
    return location["kind"] == "skills" and artifact_applies(skill_id, location, exceptions)


def location_file(location, conv_id, rule_id, placement, sites, workspaces):
    spec = placement["conventions"][conv_id]
    if location["scope"] == "workspace":
        root = Path(workspaces[location["anchor"]]["path"])
        return root / spec["path"].format(id=rule_id)
    if location["scope"] == "home":
        template = spec.get("home_path")
        if not template:
            raise PlacementError(
                "location %s: convention %s has no home_path" % (location["id"], conv_id)
            )
        home = sites[location["anchor"]]["home"]
        config = expand_home(
            placement["tools"][location["tool"]]["configHome"]["default"], home
        )
        return config / template.format(id=rule_id)
    return None


def conventions_for(placement, tool, kind):
    return placement["tools"].get(tool, {}).get("reads", {}).get(kind, [])


def expected_writes(rules, placement, locations, exceptions, sites, workspaces, skills=None):
    files, sections = {}, {}
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        tool = loc["tool"]
        if tool not in placement["tools"]:
            raise PlacementError("location %s: unknown tool %s" % (loc["id"], tool))
        for conv_id in conventions_for(placement, tool, "skills"):
            for skill_id, tree in sorted((skills or {}).items()):
                if not skill_applies(skill_id, loc, exceptions):
                    continue
                root = location_file(loc, conv_id, skill_id, placement, sites, workspaces)
                if root is None:
                    continue
                for relative, content in tree.items():
                    files[root.joinpath(*relative.split("/"))] = content
                files[root / agent_rules.SKILL_MARKER] = marker_bytes(skill_id)
        for conv_id in conventions_for(placement, tool, "rules"):
            spec = placement["conventions"][conv_id]
            for meta, common, bindings in rules:
                if not rule_applies(meta, loc, exceptions, placement):
                    continue
                dest = location_file(loc, conv_id, meta["id"], placement, sites, workspaces)
                if dest is None:
                    continue
                body = agent_rules.body_for_convention(
                    meta, common, bindings, conv_id, placement
                )
                if spec.get("mode") == "section":
                    sections.setdefault(dest, {})[meta["id"]] = body
                    continue
                if spec.get("frontmatter"):
                    header = "".join(
                        "%s: %s\n" % (key, meta["summary"] if value == "@summary" else value)
                        for key, value in spec["frontmatter"].items()
                    )
                    body = "---\n%s---\n\n%s" % (header, body)
                files[dest] = body.encode("utf-8")
    return files, sections


def marker_bytes(skill_id):
    """Ownership stamp. A rule is reclaimable because its file name carries the
    `agent-rules--` prefix; a skill directory has to keep the name the agent
    invokes, so the claim goes inside the directory instead."""
    return ("%s\n" % skill_id).encode("utf-8")


def is_link(path):
    """True for a symlink and for a Windows junction. `Path.is_symlink()` reports
    False for a junction, so a projection would walk through one and write into
    the link target instead of the managed root."""
    if path.is_symlink():
        return True
    if hasattr(os.path, "isjunction"):
        return os.path.isjunction(path)
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError, ValueError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def managed_skill_dirs(directory):
    """Child directories of a managed skills root that this projection owns."""
    if not directory.is_dir():
        return []
    return [
        path for path in sorted(directory.iterdir())
        if path.is_dir() and not is_link(path) and (path / agent_rules.SKILL_MARKER).is_file()
    ]


def managed_dir(location, conv_id, placement, sites, workspaces):
    spec = placement["conventions"][conv_id]
    if spec.get("mode") == "section":
        return None
    template = spec.get("home_path") if location["scope"] == "home" else spec.get("path", "")
    if not template or "{id}" not in template:
        return None
    sample = location_file(location, conv_id, "x", placement, sites, workspaces)
    return sample.parent if sample else None


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".place.tmp")
    if isinstance(content, str):
        content = content.encode("utf-8")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def affected_targets(files, sections, locations, placement, sites, workspaces):
    targets = list(files) + list(sections)
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        for conv_id in conventions_for(placement, loc["tool"], "rules") + conventions_for(
            placement, loc["tool"], "skills"
        ):
            directory = managed_dir(loc, conv_id, placement, sites, workspaces)
            if directory:
                targets.append(directory)
        for rel in [part for part in loc.get("legacy", "").split("|") if part]:
            root = (
                Path(workspaces[loc["anchor"]]["path"])
                if loc["scope"] == "workspace"
                else expand_home(
                    placement["tools"][loc["tool"]]["configHome"]["default"],
                    sites[loc["anchor"]]["home"],
                )
            )
            targets.append(root / rel)
    unique = []
    seen = set()
    for path in targets:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(Path(path))
    return unique


def preflight_targets(targets):
    for target in targets:
        if is_link(target):
            raise PlacementError("affected target is a link: %s" % target)
        if target.is_dir() and any(is_link(path) for path in target.rglob("*")):
            raise PlacementError("affected target contains a link: %s" % target)


def snapshot(targets):
    shots = {}
    for target in targets:
        if target.is_file():
            shots[target] = target.read_bytes()
        elif target.is_dir():
            shots[target] = {
                path.relative_to(target).as_posix(): path.read_bytes()
                for path in target.rglob("*")
                if path.is_file()
            }
        else:
            shots[target] = None
    return shots


def restore(shots):
    for target, data in shots.items():
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        if data is None:
            continue
        if isinstance(data, bytes):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            continue
        target.mkdir(parents=True, exist_ok=True)
        for rel, content in data.items():
            dest = target.joinpath(*rel.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)


def site_reachable(site):
    if site.get("reach") == "absent":
        return False
    try:
        return Path(site["home"]).exists()
    except OSError:
        return False


def detect_cli(site, spec):
    home = Path(site["home"])
    entry = spec["entrypoint"]
    names = [entry]
    if os.name == "nt":
        names.append(entry + ".exe")
    for name in names:
        for rel in (Path(".local") / "bin" / name, Path("bin") / name, Path(".opencode") / "bin" / name):
            try:
                if (home / rel).is_file():
                    return True
            except OSError:
                continue
    return False


def hooks_errors(location, target, placement):
    """An existing hooks file still has to declare hooks."""
    kind = placement["tools"].get(location["tool"], {}).get("hooks", {}).get("kind")
    if kind == "none":
        return ["%s: %s has no hooks surface" % (location["id"], location["tool"])]
    if kind != "settings":
        return []
    try:
        settings = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return ["%s: unreadable settings %s (%s)" % (location["id"], target, error)]
    if not isinstance(settings, dict) or not settings.get("hooks"):
        return ["%s: no hooks declared in %s" % (location["id"], target)]
    return []


def declared_tools(locations, workspaces, site_id):
    found = set()
    for loc in locations.values():
        if site_of(loc, workspaces) == site_id:
            found.add(loc["tool"])
    return found


def render_sections(path, blocks):
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    agent_rules.require_balanced_markers(text, str(path))
    text = agent_rules.remove_stale_sections(text, set(blocks))
    for rule_id in sorted(blocks):
        text = agent_rules.splice(text, rule_id, blocks[rule_id])
    return text.encode("utf-8")


def check_state(rules, placement, locations, exceptions, sites, workspaces, all_locations, skills=None):
    errors = []
    reachable = [loc for loc in locations if site_reachable(sites[site_of(loc, workspaces)])]
    files, sections = expected_writes(rules, placement, reachable, exceptions, sites, workspaces, skills)
    printed = []
    for loc in locations:
        if loc["scope"] == "workspace":
            printed.append(workspaces[loc["anchor"]]["path"])
        else:
            printed.append(sites[loc["anchor"]]["home"])
        site = sites[site_of(loc, workspaces)]
        if not site_reachable(site):
            continue
        if loc["tool"] not in placement["tools"]:
            errors.append("%s: unknown tool %s" % (loc["id"], loc["tool"]))
    for dest, content in sorted(files.items(), key=lambda item: str(item[0])):
        actual = dest.read_bytes() if dest.is_file() else None
        if actual is None:
            errors.append("missing: %s" % dest)
        elif actual != content:
            errors.append("differs from canonical: %s" % dest)
    expected_resolved = {path.resolve(strict=False) for path in files}
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        if not site_reachable(sites[site_of(loc, workspaces)]):
            continue
        for conv_id in conventions_for(placement, loc["tool"], "rules"):
            spec = placement["conventions"][conv_id]
            directory = managed_dir(loc, conv_id, placement, sites, workspaces)
            if directory is None or not directory.is_dir():
                continue
            template = spec.get("home_path") if loc["scope"] == "home" else spec["path"]
            _, prefix, suffix = agent_rules.managed_names(template)
            for path in sorted(directory.iterdir()):
                if (
                    path.is_file()
                    and path.name.startswith(prefix)
                    and path.name.endswith(suffix)
                    and path.resolve(strict=False) not in expected_resolved
                ):
                    errors.append("unexpected managed rule: %s" % path)
        for conv_id in conventions_for(placement, loc["tool"], "skills"):
            directory = managed_dir(loc, conv_id, placement, sites, workspaces)
            if directory is None:
                continue
            for path in managed_skill_dirs(directory):
                if (path / agent_rules.SKILL_MARKER).resolve(strict=False) not in expected_resolved:
                    errors.append("unexpected managed skill: %s" % path)
                    continue
                for inner in sorted(path.rglob("*")):
                    if inner.is_file() and inner.resolve(strict=False) not in expected_resolved:
                        errors.append("unexpected file in managed skill: %s" % inner)
    for dest, blocks in sorted(sections.items(), key=lambda item: str(item[0])):
        if not dest.exists():
            errors.append("missing: %s" % dest)
            continue
        text = dest.read_text(encoding="utf-8")
        markers = list(agent_rules.MARKER.findall(text))
        begins = [rule_id for kind, rule_id in markers if kind == "begin"]
        for rule_id in sorted((set(begins) | {rule_id for kind, rule_id in markers if kind == "end"}) - set(blocks)):
            errors.append("unexpected section '%s' in %s" % (rule_id, dest))
        for rule_id in sorted(blocks):
            actual = agent_rules.extract_all(text, rule_id)
            if not actual:
                errors.append("missing section '%s' in %s" % (rule_id, dest))
            elif len(actual) > 1:
                errors.append("duplicate section '%s' in %s" % (rule_id, dest))
            elif actual[0] != blocks[rule_id]:
                errors.append("section '%s' differs from canonical in %s" % (rule_id, dest))
    for loc in reachable:
        if loc["scope"] != "hooks" or loc["requirement"] != "required":
            continue
        target = loc.get("path", "").strip()
        if not target:
            errors.append("%s: required %s location has no path" % (loc["id"], loc["scope"]))
            continue
        try:
            present = Path(target).exists()
        except OSError:
            errors.append("unreadable: %s" % target)
            continue
        if not present:
            errors.append("missing: %s" % target)
            continue
        if loc["scope"] == "hooks":
            errors.extend(hooks_errors(loc, target, placement))
    for site_id, site in sites.items():
        if not site_reachable(site):
            continue
        declared = declared_tools(all_locations, workspaces, site_id)
        for tool, spec in placement["tools"].items():
            if detect_cli(site, spec) and tool not in declared:
                errors.append("%s: installed CLI '%s' has no required or absent location" % (site_id, tool))
    return errors, printed


def apply_projection(rules, placement, locations, exceptions, sites, workspaces, skills=None):
    files, sections = expected_writes(rules, placement, locations, exceptions, sites, workspaces, skills)
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        root = (
            Path(workspaces[loc["anchor"]]["path"])
            if loc["scope"] == "workspace"
            else expand_home(
                placement["tools"][loc["tool"]]["configHome"]["default"],
                sites[loc["anchor"]]["home"],
            )
        )
        for rel in [part for part in loc.get("legacy", "").split("|") if part]:
            path = root / rel
            if path.is_file():
                path.unlink()
        owned = {path.resolve(strict=False) for path in files}
        for conv_id in conventions_for(placement, loc["tool"], "rules"):
            directory = managed_dir(loc, conv_id, placement, sites, workspaces)
            spec = placement["conventions"][conv_id]
            if directory is None or not directory.is_dir():
                continue
            template = spec.get("home_path") if loc["scope"] == "home" else spec.get("path", "")
            if "{id}" not in template:
                continue
            _, prefix, suffix = agent_rules.managed_names(template)
            for path in list(directory.iterdir()):
                if path.is_file() and path.name.startswith(prefix) and path.name.endswith(suffix) and path.resolve(strict=False) not in owned:
                    path.unlink()
        for conv_id in conventions_for(placement, loc["tool"], "skills"):
            directory = managed_dir(loc, conv_id, placement, sites, workspaces)
            if directory is None:
                continue
            for path in managed_skill_dirs(directory):
                if (path / agent_rules.SKILL_MARKER).resolve(strict=False) not in owned:
                    shutil.rmtree(path)
                    continue
                for inner in sorted(path.rglob("*")):
                    if inner.is_file() and inner.resolve(strict=False) not in owned:
                        inner.unlink()
    for dest, content in files.items():
        atomic_write(dest, content)
    for dest, blocks in sections.items():
        atomic_write(dest, render_sections(dest, blocks))


def mirror(args):
    """Publish the maintainer's own skills to a public checkout.

    A skill listed in UPSTREAM.tsv belongs to someone else's repository. It is
    managed here so every tool gets the same bytes, but republishing it under a
    repository that names itself the maintainer's own would misstate authorship,
    so the mirror carries only what is written here. A manifest that cannot be
    read, or that names a skill this repository does not hold, stops the publish
    rather than passing for an empty list of other people's work."""
    if not args.skills:
        raise PlacementError("--skills is required")
    skills = agent_rules.load_skill_dirs(args.skills)
    vendored = agent_rules.vendored_ids(args.skills)
    stale = sorted(vendored - set(skills))
    if stale:
        raise PlacementError(
            "%s names skills that are not here: %s" % (agent_rules.SKILL_MANIFEST, ", ".join(stale))
        )
    own = {skill_id: tree for skill_id, tree in skills.items() if skill_id not in vendored}
    dest = Path(args.dest) / "skills"
    expected = {}
    for skill_id, tree in own.items():
        for relative, content in tree.items():
            expected[dest / skill_id / Path(*relative.split("/"))] = content
    errors = []
    for path, content in sorted(expected.items(), key=lambda item: str(item[0])):
        actual = path.read_bytes() if path.is_file() else None
        if actual is None:
            errors.append("missing: %s" % path)
        elif actual != content:
            errors.append("differs from canonical: %s" % path)
    if dest.is_dir():
        for path in sorted(dest.iterdir()):
            if path.is_dir() and path.name not in own:
                errors.append("unexpected skill in mirror: %s" % path)
        for path in sorted(dest.rglob("*")):
            if path.is_file() and path not in expected:
                errors.append("unexpected file in mirror: %s" % path)
    if args.check:
        for error in errors:
            print("FAIL: " + error, file=sys.stderr)
        print("mirror: %s" % ("OK" if not errors else "FAILED (%d)" % len(errors)))
        return 0 if not errors else 1
    if dest.is_dir():
        for path in sorted(dest.iterdir()):
            if path.is_dir() and path.name not in own:
                shutil.rmtree(path)
        for path in sorted(dest.rglob("*")):
            if path.is_file() and path not in expected:
                path.unlink()
    for path, content in sorted(expected.items(), key=lambda item: str(item[0])):
        atomic_write(path, content)
    print("mirror: %d skills" % len(own))
    return 0


def load_context(args):
    if not args.declaration:
        raise PlacementError("--declaration is required")
    if not args.rules:
        raise PlacementError("--rules is required")
    placement = load_placement()
    rules = agent_rules.load_rule_dirs(placement, args.rules)
    skills = agent_rules.load_skill_dirs(getattr(args, "skills", None))
    claimed = sorted({meta["id"] for meta, _, _ in rules} & set(skills))
    if claimed:
        raise PlacementError(
            "id claimed by both a rule and a skill: %s" % ", ".join(claimed)
        )
    sites, workspaces, locations, exceptions = parse_declaration(args.declaration)
    selected = filter_locations(
        locations, workspaces, getattr(args, "site", None), getattr(args, "workspace", None), getattr(args, "scope", None)
    )
    return placement, rules, sites, workspaces, locations, exceptions, selected, skills


def check(args):
    placement, rules, sites, workspaces, locations, exceptions, selected, skills = load_context(args)
    errors, printed = check_state(rules, placement, selected, exceptions, sites, workspaces, locations, skills)
    for path in printed:
        print(path)
    for error in errors:
        print("FAIL: " + error, file=sys.stderr)
    print("place: %s" % ("OK" if not errors else "FAILED (%d)" % len(errors)))
    return 0 if not errors else 1


def apply(args):
    placement, rules, sites, workspaces, locations, exceptions, selected, skills = load_context(args)
    files, sections = expected_writes(rules, placement, selected, exceptions, sites, workspaces, skills)
    targets = affected_targets(files, sections, selected, placement, sites, workspaces)
    preflight_targets(targets)
    shots = snapshot(targets)
    try:
        apply_projection(rules, placement, selected, exceptions, sites, workspaces, skills)
        forced_failure = os.environ.get("PLACE_FORCE_POSTCHECK_FAILURE")
        if forced_failure == "interrupt":
            raise KeyboardInterrupt()
        if forced_failure:
            raise PlacementError("forced post-check failure")
        errors, _ = check_state(rules, placement, selected, exceptions, sites, workspaces, locations, skills)
        if errors:
            raise PlacementError("post-check failed: " + "; ".join(errors))
    except (Exception, KeyboardInterrupt):
        restore(shots)
        raise
    print("place: applied")
    return 0


def write_rule(directory, rule_id, title, tools=None):
    directory.mkdir(parents=True, exist_ok=True)
    tools_line = "tools: [%s]\n" % ", ".join(tools) if tools else ""
    (directory / ("%s.rule.md" % rule_id)).write_text(
        "---\nid: %s\ntitle: %s\nsummary: %s\n%s---\n\n%s body.\n" % (rule_id, title, title, tools_line, title),
        encoding="utf-8",
        newline="\n",
    )


def make_link(link, target):
    """A directory link of the shape this platform actually produces: a junction
    on Windows, where `mklink /J` is what the skill docs told people to use, and
    a symlink elsewhere."""
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def write_skill(directory, skill_id, description):
    target = directory / skill_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        "---\nname: %s\ndescription: %s\n---\n\n%s body.\n" % (skill_id, description, skill_id),
        encoding="utf-8",
        newline="\n",
    )


def selfcheck(_args):
    placement = load_placement()
    source = FIXTURE_DECL.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="place-selfcheck-") as temporary:
        root = Path(temporary)
        home, workspace = root / "home", root / "ws"
        home.mkdir()
        (home / ".claude").mkdir()
        settings = home / ".claude" / "settings.json"
        settings.write_text('{"hooks": {"Stop": []}}', encoding="utf-8")
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".local" / "bin" / "claude").write_text("", encoding="utf-8")
        (home / ".local" / "bin" / "cursor-agent").write_text("", encoding="utf-8")
        public_rules, private_rules = root / "public-rules", root / "private-rules"
        write_rule(public_rules, "alpha", "Alpha")
        write_rule(public_rules, "beta", "Beta", ["cursor-agent"])
        write_rule(private_rules, "gamma", "Gamma")
        skills_dir = root / "skills"
        write_skill(skills_dir, "delta", "Delta skill")
        write_skill(skills_dir, "epsilon", "Epsilon skill")
        declaration = source.replace("{ROOT}", str(root).replace("\\", "/"))
        decl_path = root / "PLACEMENT.md"
        decl_path.write_text(declaration, encoding="utf-8", newline="\n")
        ns = argparse.Namespace(
            declaration=str(decl_path),
            rules=[str(public_rules), str(private_rules)],
            skills=[str(skills_dir)],
            site=None,
            workspace=None,
            scope=None,
        )
        if apply(ns):
            raise PlacementError("selfcheck apply failed")
        if check(ns):
            raise PlacementError("selfcheck check failed after apply")

        claude_skills = home / ".claude" / "skills"
        cursor_skills = home / ".cursor" / "skills"
        if not (claude_skills / "delta" / "SKILL.md").is_file():
            raise PlacementError("selfcheck apply did not project a skill")
        if not (claude_skills / "delta" / agent_rules.SKILL_MARKER).is_file():
            raise PlacementError("selfcheck apply did not stamp the ownership marker")
        if (cursor_skills / "epsilon").exists():
            raise PlacementError("selfcheck ignored a skill exception")
        if not (cursor_skills / "delta" / "SKILL.md").is_file():
            raise PlacementError("selfcheck apply did not project a skill for the second tool")
        # One namespace: an exception row names an id, and the location it
        # names decides the kind, so two kinds answering to one id make the
        # declaration unreadable.
        write_skill(skills_dir, "alpha", "Alpha skill")
        try:
            check(ns)
        except PlacementError as exc:
            if "claimed by both a rule and a skill" not in str(exc):
                raise PlacementError("selfcheck stopped the collision for another reason: %s" % exc)
        else:
            raise PlacementError("selfcheck accepted one id claimed by a rule and a skill")
        shutil.rmtree(skills_dir / "alpha")
        if check(ns):
            raise PlacementError("selfcheck still failing after the colliding skill was removed")
        # An unmanaged skill has no marker, so nothing may reclaim it.
        foreign = claude_skills / "hand-placed"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("---\nname: hand-placed\n---\n", encoding="utf-8")
        if check(ns):
            raise PlacementError("selfcheck flagged an unmanaged skill")
        if apply(ns):
            raise PlacementError("selfcheck apply failed with an unmanaged skill present")
        if not (foreign / "SKILL.md").is_file():
            raise PlacementError("selfcheck apply removed an unmanaged skill")
        # A marked directory the declaration no longer names is reclaimable.
        orphan = claude_skills / "retired"
        orphan.mkdir(parents=True)
        (orphan / agent_rules.SKILL_MARKER).write_bytes(marker_bytes("retired"))
        (orphan / "SKILL.md").write_text("---\nname: retired\n---\n", encoding="utf-8")
        if not check(ns):
            raise PlacementError("selfcheck accepted an unexpected managed skill")
        if apply(ns):
            raise PlacementError("selfcheck apply failed while reclaiming a skill")
        if orphan.exists():
            raise PlacementError("selfcheck apply did not reclaim an orphan skill")
        # A stray file inside a managed skill is drift like any other.
        stray = claude_skills / "delta" / "notes.md"
        stray.write_text("stray\n", encoding="utf-8")
        if not check(ns):
            raise PlacementError("selfcheck accepted a stray file in a managed skill")
        if apply(ns):
            raise PlacementError("selfcheck apply failed while removing a stray file")
        if stray.exists():
            raise PlacementError("selfcheck apply did not remove a stray file")
        (claude_skills / "delta" / "SKILL.md").write_bytes(b"drifted\n")
        if not check(ns):
            raise PlacementError("selfcheck accepted skill drift")
        apply(ns)
        if check(ns):
            raise PlacementError("selfcheck apply did not repair skill drift")
        shutil.rmtree(foreign)
        if check(ns):
            raise PlacementError("selfcheck still failing after the unmanaged skill was removed")

        # A link inside a managed root must stop apply, or the projection is
        # written through it into whatever the link points at.
        payload = root / "link-payload"
        payload.mkdir()
        (payload / "keep.md").write_text("keep\n", encoding="utf-8")
        linked = claude_skills / "linked"
        make_link(linked, payload)
        try:
            apply(ns)
        except PlacementError as exc:
            if "is a link" not in str(exc) and "contains a link" not in str(exc):
                raise PlacementError("selfcheck stopped the link for another reason: %s" % exc)
        else:
            raise PlacementError("selfcheck accepted a link inside a managed root")
        if [path.name for path in payload.iterdir()] != ["keep.md"]:
            raise PlacementError("selfcheck wrote through a link into its target")
        if linked.is_symlink():
            linked.unlink()
        else:
            linked.rmdir()
        if check(ns):
            raise PlacementError("selfcheck still failing after the link was removed")

        stale = workspace / ".cursor" / "rules" / "agent-rules--legacy.mdc"
        stale.write_text("nope\n", encoding="utf-8")
        if not check(ns):
            raise PlacementError("selfcheck accepted an unexpected managed file")
        stale.unlink()
        if check(ns):
            raise PlacementError("selfcheck still failing after cleanup")
        (home / ".local" / "bin" / "codex").write_text("", encoding="utf-8")
        if not check(ns):
            raise PlacementError("selfcheck accepted an undeclared installed CLI")
        (home / ".local" / "bin" / "codex").unlink()
        settings.write_text('{"theme": "dark"}', encoding="utf-8")
        if not check(ns):
            raise PlacementError("selfcheck accepted a hooks location without hooks")
        settings.write_text('{"hooks": {"Stop": []}}', encoding="utf-8")
        if check(ns):
            raise PlacementError("selfcheck still failing after hooks returned")
        generated = workspace / ".cursor" / "rules" / "agent-rules--beta.mdc"
        generated.write_bytes(generated.read_bytes() + b"changed\n")
        if not check(ns):
            raise PlacementError("selfcheck accepted drift")
        apply(ns)
        if check(ns):
            raise PlacementError("selfcheck apply did not repair drift")
        leftover = workspace / "unmanaged.md"
        leftover.write_text("keep\n", encoding="utf-8")
        os.environ["PLACE_FORCE_POSTCHECK_FAILURE"] = "1"
        try:
            try:
                apply(ns)
            except PlacementError:
                pass
            else:
                raise PlacementError("selfcheck forced failure did not raise")
        finally:
            os.environ.pop("PLACE_FORCE_POSTCHECK_FAILURE", None)
        if leftover.read_text(encoding="utf-8") != "keep\n":
            raise PlacementError("selfcheck rollback did not restore")
        leftover.unlink()
        if check(ns):
            raise PlacementError("selfcheck still failing after rollback")
        leftover.write_text("keep\n", encoding="utf-8")
        os.environ["PLACE_FORCE_POSTCHECK_FAILURE"] = "interrupt"
        try:
            try:
                apply(ns)
            except KeyboardInterrupt:
                pass
            else:
                raise PlacementError("selfcheck forced interrupt did not raise")
        finally:
            os.environ.pop("PLACE_FORCE_POSTCHECK_FAILURE", None)
        if leftover.read_text(encoding="utf-8") != "keep\n":
            raise PlacementError("selfcheck interrupt did not restore")
        leftover.unlink()
        if check(ns):
            raise PlacementError("selfcheck still failing after interrupt restore")

        # The mirror names itself the maintainer's own skills, so it publishes
        # only what the vendored manifest accounts for. A manifest that is absent
        # or out of date stops the publish instead of passing for an empty one.
        manifest = Path(skills_dir) / agent_rules.SKILL_MANIFEST
        mirror_ns = argparse.Namespace(skills=[str(skills_dir)], dest=str(root / "mirror"), check=False)
        try:
            mirror(mirror_ns)
        except SystemExit:
            pass
        else:
            raise PlacementError("selfcheck published without a vendored manifest")
        header = "\t".join(agent_rules.SKILL_MANIFEST_HEADER)
        manifest.write_text(
            "%s\nepsilon\tsomeone/skills\trefs/heads/main\tskills/epsilon\tdeadbeef\tMIT\n" % header,
            encoding="utf-8",
            newline="\n",
        )
        if mirror(mirror_ns):
            raise PlacementError("selfcheck mirror failed")
        published = sorted(path.name for path in (root / "mirror" / "skills").iterdir())
        if published != ["delta"]:
            raise PlacementError("selfcheck mirror published a vendored skill: %s" % published)
        manifest.write_text(
            "%s\nzeta\tsomeone/skills\trefs/heads/main\tskills/zeta\tdeadbeef\tMIT\n" % header,
            encoding="utf-8",
            newline="\n",
        )
        try:
            mirror(mirror_ns)
        except PlacementError:
            pass
        else:
            raise PlacementError("selfcheck published with a manifest naming an absent skill")
    print("place: selfcheck OK")
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser):
        subparser.add_argument("--declaration")
        subparser.add_argument("--rules", action="append")
        subparser.add_argument("--skills", action="append")
        subparser.add_argument("--site")
        subparser.add_argument("--workspace")
        subparser.add_argument("--scope")

    check_p = sub.add_parser("check")
    add_common(check_p)
    apply_p = sub.add_parser("apply")
    add_common(apply_p)
    mirror_p = sub.add_parser("mirror")
    mirror_p.add_argument("--skills", action="append")
    mirror_p.add_argument("--dest", required=True)
    mirror_p.add_argument("--check", action="store_true")
    sub.add_parser("selfcheck")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return check(args)
        if args.command == "apply":
            return apply(args)
        if args.command == "mirror":
            return mirror(args)
        return selfcheck(args)
    except PlacementError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
