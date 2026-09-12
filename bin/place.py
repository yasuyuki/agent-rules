#!/usr/bin/env python3
"""Project rules and skills onto the sites and workspaces a declaration names.

    place.py check  --declaration <path> [--rules <dir>] [--skills <dir>] [--site <id> --readiness]
    place.py apply  --declaration <path> [--rules <dir>] [--skills <dir>]
    place.py list   --declaration <path>
    place.py start  [--config <path> | --declaration <path> [--rules <dir>] [--skills <dir>]] <workspace> <tool> [-- <tool-argv>...]
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
import uuid
from pathlib import Path

# Keep every public command usable from a read-only source checkout.  This is
# material to classify's read-only contract: local imports must not emit pyc.
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PLACEMENT = ROOT / "placement.json"
FIXTURE_DECL = ROOT / "tests" / "fixtures" / "place" / "declaration.md"

spec = importlib.util.spec_from_file_location("agent_rules", HERE / "rules.py")
agent_rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_rules)

inventory_spec = importlib.util.spec_from_file_location("environment_inventory", HERE / "environment_inventory.py")
environment_inventory = importlib.util.module_from_spec(inventory_spec)
inventory_spec.loader.exec_module(environment_inventory)

classification_spec = importlib.util.spec_from_file_location("work_classification", HERE / "work_classification.py")
work_classification = importlib.util.module_from_spec(classification_spec)
classification_spec.loader.exec_module(work_classification)


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


def location_conventions(placement, location, kind):
    if location.get("kind", "rules") != kind:
        return []
    return conventions_for(placement, location["tool"], kind)


def expected_writes(rules, placement, locations, exceptions, sites, workspaces, skills=None):
    files, sections = {}, {}
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        tool = loc["tool"]
        if tool not in placement["tools"]:
            raise PlacementError("location %s: unknown tool %s" % (loc["id"], tool))
        for conv_id in location_conventions(placement, loc, "skills"):
            for skill_id, tree in sorted((skills or {}).items()):
                if not skill_applies(skill_id, loc, exceptions):
                    continue
                root = location_file(loc, conv_id, skill_id, placement, sites, workspaces)
                if root is None:
                    continue
                for relative, content in tree.items():
                    files[root.joinpath(*relative.split("/"))] = content
                files[root / agent_rules.SKILL_MARKER] = marker_bytes(skill_id)
        for conv_id in location_conventions(placement, loc, "rules"):
            spec = placement["conventions"][conv_id]
            if spec.get("mode") == "section":
                dest = location_file(loc, conv_id, "", placement, sites, workspaces)
                if dest is not None:
                    sections.setdefault(dest, {})
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
    if isinstance(content, str):
        content = content.encode("utf-8")
    while True:
        temporary = path.with_name(path.name + ".place." + uuid.uuid4().hex + ".tmp")
        try:
            stream = temporary.open("xb")
            break
        except FileExistsError:
            continue
    try:
        with stream:
            stream.write(content)
        executable = getattr(content, "executable", None)
        if os.name == "posix" and executable is not None:
            temporary.chmod((temporary.stat().st_mode & 0o666) | executable)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def executable_differs(path, content):
    executable = getattr(content, "executable", None)
    return (os.name == "posix" and executable is not None
            and path.stat().st_mode & 0o111 != executable)


def affected_targets(files, sections, locations, placement, sites, workspaces):
    targets = list(files) + list(sections)
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        for conv_id in location_conventions(placement, loc, "rules") + location_conventions(
            placement, loc, "skills"
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
        for parent in target.absolute().parents:
            if is_link(parent):
                raise PlacementError("affected target ancestor is a link: %s" % parent)
        if is_link(target):
            raise PlacementError("affected target is a link: %s" % target)
        if target.is_dir() and any(is_link(path) for path in target.rglob("*")):
            raise PlacementError("affected target contains a link: %s" % target)


def snapshot(targets):
    shots = {}
    for target in targets:
        if target.is_file():
            shots[target] = (target.stat(), target.read_bytes())
        elif target.is_dir():
            shots[target] = (target.stat(), snapshot(target.iterdir()))
        else:
            shots[target] = None
    return shots


def restore(shots):
    for target, data in shots.items():
        if data is None or is_link(target) or (
            target.exists() and target.is_dir() != isinstance(data[1], dict)
        ):
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
        if data is None:
            continue
        metadata, content = data
        if isinstance(content, bytes):
            target.parent.mkdir(parents=True, exist_ok=True)
            # Leave unchanged files in place: rewriting them loses identity,
            # Windows ACLs/attributes and other metadata outside our ownership.
            if not target.is_file() or target.read_bytes() != content:
                target.write_bytes(content)
        else:
            target.mkdir(parents=True, exist_ok=True)
            restore({path: None for path in target.iterdir() if path not in content})
            restore(content)
        if stat.S_IMODE(target.stat().st_mode) != stat.S_IMODE(metadata.st_mode):
            target.chmod(stat.S_IMODE(metadata.st_mode))
        current = target.stat()
        if current.st_mtime_ns != metadata.st_mtime_ns:
            os.utime(target, ns=(current.st_atime_ns, metadata.st_mtime_ns))


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
        for rel in (Path(".local") / "bin" / name, Path("bin") / name, Path(".opencode") / "bin" / name,
                    Path(".grok") / "bin" / name):
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


def check_state(rules, placement, locations, exceptions, sites, workspaces, all_locations, skills=None, *, check_installed=True):
    errors = []
    reachable = [loc for loc in locations if site_reachable(sites[site_of(loc, workspaces)])]
    files, sections = expected_writes(rules, placement, reachable, exceptions, sites, workspaces, skills)
    # A section file may be shared by several tools (for example AGENTS.md).
    # A tool-scoped lifecycle check owns its own files and required artifacts,
    # but it must recognize the canonical sections legitimately contributed by
    # other declared tools to that same selected file.
    all_location_values = all_locations.values() if isinstance(all_locations, dict) else all_locations
    for location in all_location_values:
        if location.get("tool") not in placement["tools"]:
            continue
        _shared_files, shared_sections = expected_writes(
            rules, placement, [location], exceptions, sites, workspaces, skills
        )
        for dest, blocks in shared_sections.items():
            if dest in sections:
                sections[dest].update(blocks)
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
        elif executable_differs(dest, content):
            errors.append("executable bits differ from canonical: %s" % dest)
    expected_resolved = {path.resolve(strict=False) for path in files}
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        if not site_reachable(sites[site_of(loc, workspaces)]):
            continue
        for conv_id in location_conventions(placement, loc, "rules"):
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
        for conv_id in location_conventions(placement, loc, "skills"):
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
            if blocks:
                errors.append("missing: %s" % dest)
            continue
        text = dest.read_text(encoding="utf-8")
        try:
            agent_rules.require_balanced_markers(text, str(dest))
        except SystemExit as exc:
            errors.append(str(exc))
            continue
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
    for site_id, site in (sites.items() if check_installed else []):
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
        for conv_id in location_conventions(placement, loc, "rules"):
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
        for conv_id in location_conventions(placement, loc, "skills"):
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
        if blocks or dest.exists():
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
    preflight_targets([dest])
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
        elif executable_differs(path, content):
            errors.append("executable bits differ from canonical: %s" % path)
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


def source_dirs(primary, additional):
    out = []
    seen = set()
    for value in [primary, *(additional or [])]:
        resolved = str(Path(value).resolve())
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


def load_context(args):
    if not args.declaration:
        raise PlacementError("--declaration is required")
    placement = load_placement()
    rules = agent_rules.load_rule_dirs(
        placement, source_dirs(ROOT / "rules", args.rules)
    )
    skills = agent_rules.load_skill_dirs(
        source_dirs(ROOT / "skills", getattr(args, "skills", None))
    )
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


def check(args, *, context=None):
    if getattr(args, "readiness", False):
        if getattr(args, "workspace", None) or getattr(args, "scope", None):
            raise PlacementError("--readiness cannot be combined with --workspace or --scope")
        if not getattr(args, "site", None):
            raise PlacementError("--readiness requires --site")
        placement, rules, sites, workspaces, locations, exceptions, selected, skills = context if context is not None else load_context(args)
        if args.site not in sites:
            raise PlacementError("unknown site: " + args.site)
        inventory_preflight(args, (placement, rules, sites, workspaces, locations, exceptions, selected, skills),
                            args.site, mode="readiness")
        print("readiness: OK")
        return 0
    placement, rules, sites, workspaces, locations, exceptions, selected, skills = context if context is not None else load_context(args)
    errors, printed = check_state(rules, placement, selected, exceptions, sites, workspaces, locations, skills, check_installed=context is None)
    for path in printed:
        print(path)
    for error in errors:
        print("FAIL: " + error, file=sys.stderr)
    print("place: %s" % ("OK" if not errors else "FAILED (%d)" % len(errors)))
    return 0 if not errors else 1


def apply(args, *, context=None):
    placement, rules, sites, workspaces, locations, exceptions, selected, skills = context if context is not None else load_context(args)
    files, sections = expected_writes(rules, placement, selected, exceptions, sites, workspaces, skills)
    targets = affected_targets(files, sections, selected, placement, sites, workspaces)
    preflight_targets(targets)
    for dest in files:
        if dest.name == agent_rules.SKILL_MARKER and dest.parent.exists():
            if not dest.is_file() or dest.read_bytes() != marker_bytes(dest.parent.name):
                raise PlacementError("refusing to overwrite unmanaged skill: %s" % dest.parent)
    shots = snapshot(targets)
    try:
        apply_projection(rules, placement, selected, exceptions, sites, workspaces, skills)
        forced_failure = os.environ.get("PLACE_FORCE_POSTCHECK_FAILURE")
        if forced_failure == "interrupt":
            raise KeyboardInterrupt()
        if forced_failure:
            raise PlacementError("forced post-check failure")
        errors, _ = check_state(rules, placement, selected, exceptions, sites, workspaces, locations, skills, check_installed=context is None)
        if errors:
            raise PlacementError("post-check failed: " + "; ".join(errors))
    except (Exception, KeyboardInterrupt, SystemExit):
        restore(shots)
        raise
    print("place: applied")
    return 0


def list_workspaces(args):
    _sites, workspaces, locations, _exceptions = parse_declaration(args.declaration)
    print("workspace\tpath\ttools")
    for workspace_id, workspace in sorted(workspaces.items()):
        tools = sorted(declared_tools(locations, workspaces, workspace["site"]))
        print("%s\t%s\t%s" % (workspace_id, workspace["path"], ",".join(tools)))
    return 0


def list_catalog(args):
    try:
        _catalog, _sources, records = environment_inventory.load_catalog(args.catalog, args.purpose, probe=args.probe)
        if args.probe:
            environment_inventory.probe_records(records)
    except environment_inventory.CatalogError as exc:
        raise PlacementError(str(exc)) from None
    if args.json:
        print(json.dumps(records, ensure_ascii=False, sort_keys=True))
        return 0
    print("id\tpurposes\tstate\tcandidate\treason\tconnection\tprincipal\tworkspaces\tentrypoint\tresolution\tobservation")
    for record in records:
        principals = "; ".join(
            "%s/%s:%s@%s HOME=%s" % (ref["source"], ref["site"]["id"],
                                    ref["site"].get("user", "?"), ref["site"].get("host", "?"),
                                    ref["site"].get("home", "?"))
            for ref in record["refs"] if ref.get("site")
        ) or "unverified"
        workspaces = ",".join(
            "%s/%s=%s" % (ref["source"], workspace["id"], workspace["path"])
            for ref in record["refs"] for workspace in ref.get("siteWorkspaces", [])
        )
        roots = ["%s:runsRoot=%s" % (ref["source"], ref["values"]["runsRoot"])
                 for ref in record["refs"] if "runsRoot" in ref.get("values", {})]
        workspaces = "; ".join([value for value in [workspaces, *roots] if value]) or "-"
        resolution = "; ".join("%s:%s" % (ref["source"], ref["resolution"]) for ref in record["refs"])
        print("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" % (record["id"], ",".join(record["purposes"]) or "unclassified", record["state"], "yes" if record["candidate"] else "no", record["candidateReason"], json.dumps(record["connection"], ensure_ascii=False, separators=(",", ":")), principals, workspaces, json.dumps(record["entrypoint"], ensure_ascii=False, separators=(",", ":")), resolution, json.dumps(record["observation"], ensure_ascii=False, separators=(",", ":"))))
    return 0


def check_catalog(args):
    errors, records = environment_inventory.check_catalog(args.catalog, args.environment, args.probe)
    for error in errors:
        print("FAIL: " + error, file=sys.stderr)
    print("catalog: %s" % ("OK" if not errors else "FAILED (%d)" % len(errors)))
    return 0 if not errors else 1


def classify_work(args):
    """Classify work without probing or changing any environment."""
    try:
        results = work_classification.classify(
            args.catalog, args.work, args.prefer_environment
        )
    except work_classification.WorkClassificationError as exc:
        raise PlacementError(str(exc)) from None
    if args.json:
        print(json.dumps(results, ensure_ascii=False, sort_keys=True))
    else:
        print(work_classification.render_table(results))
    return 0


def inventory_binding(args, context, site_id):
    """Resolve one site's three-column inventory binding."""
    declaration = Path(args.declaration).resolve()
    text = declaration.read_text(encoding="utf-8")
    if "<!-- BEGIN INVENTORY TSV -->" not in text:
        return None
    rows = markdown_tsv(declaration, "INVENTORY", text)
    required = {"site", "catalog", "environment"}
    if any(set(row) != required for row in rows):
        raise PlacementError("INVENTORY needs exactly site, catalog, environment columns")
    if len({row["site"] for row in rows}) != len(rows):
        raise PlacementError("duplicate INVENTORY site")
    if any(row["site"] not in context[2] for row in rows):
        raise PlacementError("unknown INVENTORY site")
    binding = next((row for row in rows if row["site"] == site_id), None)
    if binding is None:
        raise PlacementError("INVENTORY has no binding for selected site: " + site_id)
    if any(not binding[key].strip() for key in required):
        raise PlacementError("INVENTORY binding has an empty required value")
    catalog = Path(binding["catalog"])
    return declaration, (catalog if catalog.is_absolute() else declaration.parent / catalog), binding["environment"]


def current_runtime(context):
    import getpass
    import platform
    if os.name == "posix":
        import pwd
        user = pwd.getpwuid(os.getuid()).pw_name
    else:
        user = getpass.getuser()
    home = str(Path.home())
    config_roots = {}
    for name, tool in context[0]["tools"].items():
        spec = tool["configHome"]
        config_roots[name] = os.environ.get(spec.get("env", "")) or spec["default"].replace("$HOME", home)
    return {"user": user, "home": home,
                 "host": os.environ.get("WSL_DISTRO_NAME") or platform.system(),
                 "platform": platform.system(),
                 "configRoots": config_roots}


def inventory_preflight(args, context, site_id, *, resolver=shutil.which,
                        mode="normal", constructing_agent=None, target_tool=None):
    """Check one target before start, or every registered CLI for readiness."""
    binding = inventory_binding(args, context, site_id)
    if binding is None:
        if mode == "readiness":
            raise PlacementError("--readiness requires an INVENTORY binding for the selected site")
        return
    declaration, catalog, environment = binding
    from types import SimpleNamespace
    lifecycle_spec = importlib.util.spec_from_file_location("inventory_lifecycle", HERE / "inventory_lifecycle.py")
    lifecycle = importlib.util.module_from_spec(lifecycle_spec)
    lifecycle_spec.loader.exec_module(lifecycle)
    errors, _record = lifecycle.validate_lifecycle(
        catalog, context, environment,
        place_module=SimpleNamespace(**globals()), resolver=resolver,
        current_principal=current_runtime(context), declaration_path=declaration,
        mode=mode, constructing_agent=constructing_agent, target_agent=target_tool,
        required_site=site_id,
    )
    if errors:
        raise PlacementError("inventory lifecycle check failed: " + "; ".join(errors))


def _inventory_site_runtime(context, site_id):
    """Require this process to be the declared site before catalog mutation."""
    site = context[2][site_id]
    actual = current_runtime(context)
    host_matches = actual.get("host") == site.get("host") or (
        site.get("host") == "Linux" and actual.get("platform") == "Linux"
    )
    if (actual.get("user") != site.get("user") or
            os.path.normcase(os.path.normpath(actual.get("home", ""))) != os.path.normcase(os.path.normpath(site.get("home", ""))) or
            not host_matches):
        raise PlacementError("selected site does not match the current runtime")


def _inventory_runtime(context, site_id, tool):
    """Also require this tool's derived configuration root."""
    if tool not in context[0]["tools"]:
        raise PlacementError("unknown tool: " + tool)
    _inventory_site_runtime(context, site_id)
    site = context[2][site_id]
    actual = current_runtime(context)
    expected_root = context[0]["tools"][tool]["configHome"]["default"].replace("$HOME", site["home"])
    if os.path.normcase(os.path.normpath(actual.get("configRoots", {}).get(tool, ""))) != os.path.normcase(os.path.normpath(expected_root)):
        raise PlacementError("selected site does not match the current runtime")


def _inventory_claim_scope(context, site_id, environment_id):
    """Scope a durable claim to the verified runtime that owns this site."""
    host = current_runtime(context).get("host")
    if not isinstance(host, str) or not host:
        raise PlacementError("selected site does not match the current runtime")
    return "\x1f".join((environment_id, site_id, host))


def _inventory_locations(context, site_id, tool):
    placement, rules, sites, workspaces, locations, exceptions, _selected, skills = context
    if tool not in placement["tools"]:
        raise PlacementError("unknown tool: " + tool)
    selected = [location for location in locations.values()
                if location["tool"] == tool and site_of(location, workspaces) == site_id]
    if {location["kind"] for location in selected} != {"rules", "skills"}:
        raise PlacementError("tool %s needs declared rules and skills locations on site %s" % (tool, site_id))
    # This forces the exact public artifact sources to be parsed before a
    # catalog record can claim them.  It does not install or repair anything.
    expected_writes(rules, placement, selected, exceptions, sites, workspaces, skills)
    return selected


def _inventory_output_paths(context, locations):
    """The finite managed outputs that readiness actually observes."""
    placement, _rules, sites, workspaces, _all, _exceptions, _selected, _skills = context
    files, sections = expected_writes(context[1], placement, locations, context[5], sites, workspaces, context[7])
    targets = list(files) + list(sections)
    for location in locations:
        for kind in ("rules", "skills"):
            for convention in location_conventions(placement, location, kind):
                if placement["conventions"][convention].get("mode") != "section":
                    directory = managed_dir(location, convention, placement, sites, workspaces)
                    if directory is not None:
                        targets.append(directory)
        for relative in [part for part in location.get("legacy", "").split("|") if part]:
            root = (Path(workspaces[location["anchor"]]["path"]) if location["scope"] == "workspace"
                    else expand_home(placement["tools"][location["tool"]]["configHome"]["default"],
                                     sites[location["anchor"]]["home"]))
            targets.append(root / relative)
    return list(dict.fromkeys(Path(target) for target in targets))


def _inventory_source_paths(args):
    return [Path(args.declaration), PLACEMENT]


def _inventory_loader_inputs(args):
    return environment_inventory.snapshot_loader_inputs(
        source_dirs(ROOT / "rules", getattr(args, "rules", None)),
        source_dirs(ROOT / "skills", getattr(args, "skills", None)),
    )


def _catalog_placement_source(document, catalog_path, declaration, site_id, environment_id):
    """Find the one catalog source/reference derived from this declaration/site."""
    if document.get("schemaVersion") != 1 or not isinstance(document.get("sources"), dict) or not isinstance(document.get("environments"), list):
        raise PlacementError("catalog schemaVersion, sources, or environments is invalid")
    declaration = Path(declaration).resolve()
    matching = []
    for source_id, source in document["sources"].items():
        if not isinstance(source_id, str) or not isinstance(source, dict) or source.get("type") != "placement-tsv":
            continue
        paths = source.get("paths")
        observer = os.environ.get("ENVIRONMENT_INVENTORY_HOST") or ("windows" if os.name == "nt" else "linux")
        value = paths.get(observer, paths.get("default")) if isinstance(paths, dict) else None
        if not isinstance(value, str):
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = Path(catalog_path).parent / candidate
        try:
            same = candidate.resolve() == declaration
        except OSError:
            same = False
        if same:
            # Do not let an alternate symlink spelling of the declaration turn
            # a catalog update into a write based on an unsafe source path.
            environment_inventory.snapshot_inputs([candidate])
            matching.append(source_id)
    if len(matching) != 1:
        raise PlacementError("catalog needs exactly one placement source for the selected declaration")
    environments = [item for item in document["environments"]
                    if isinstance(item, dict) and item.get("id") == environment_id]
    if len(environments) != 1:
        raise PlacementError("unknown or duplicate catalog environment")
    environment = environments[0]
    state = environment.get("state")
    if state not in {"pending", "active"}:
        raise PlacementError("catalog environment is not pending or active")
    refs = environment_inventory._environment_refs(environment)
    matching_refs = [ref for ref in refs if isinstance(ref, dict) and
                     ref.get("source") == matching[0] and ref.get("site") == site_id]
    if len(matching_refs) != 1:
        raise PlacementError("catalog environment needs exactly one selected declaration/site reference")
    return environment, matching[0]


def _registered_agent(tool, source_id, site_id):
    return {
        "descriptor": tool,
        "principal": {"source": source_id, "site": site_id, "field": "user"},
        "configRoot": {"source": source_id, "site": site_id, "tool": tool},
    }


def inventory_prepare_agent(args):
    try:
        initial_snapshots = environment_inventory.snapshot_inputs(_inventory_source_paths(args))
        initial_loaders = _inventory_loader_inputs(args)
    except environment_inventory.CatalogError as exc:
        raise PlacementError(str(exc)) from None
    context = load_context(args)
    try:
        environment_inventory._assert_snapshots(initial_snapshots)
        environment_inventory._assert_loader_inputs(initial_loaders)
    except environment_inventory.CatalogError as exc:
        raise PlacementError(str(exc)) from None
    if not args.site or args.site not in context[2]:
        raise PlacementError("unknown site")
    _inventory_runtime(context, args.site, args.tool)
    selected = _inventory_locations(context, args.site, args.tool)
    binding = inventory_binding(args, context, args.site)
    if binding is None:
        raise PlacementError("inventory prepare-agent requires an INVENTORY binding")
    declaration, catalog, environment_id = binding
    snapshots = dict(initial_snapshots)
    outputs = environment_inventory.snapshot_inputs(_inventory_output_paths(context, selected))
    snapshots.update({path: value for path, value in outputs.items() if path not in snapshots})
    try:
        with environment_inventory.locked_catalog(
                catalog, _inventory_claim_scope(context, args.site, environment_id)) as (catalog_path, raw, document):
            # Parse the selected record using the normal catalog contract before
            # making a bounded update.  This does not probe or require a CLI.
            environment_inventory.load_catalog(catalog_path, environment_id=environment_id)
            environment, source_id = _catalog_placement_source(document, catalog_path, declaration, args.site, environment_id)
            agent = _registered_agent(args.tool, source_id, args.site)
            existing = [item for item in environment.get("agents", [])
                        if isinstance(item, dict) and item.get("descriptor") == args.tool]
            if existing and (len(existing) != 1 or existing[0] != agent):
                raise PlacementError("catalog has a conflicting registered agent")
            if existing and environment["state"] == "active":
                print("inventory: agent already active")
                return 0
            if existing:
                print("inventory: agent already pending")
                return 0
            if not existing:
                if not isinstance(environment.get("agents"), list):
                    raise PlacementError("catalog environment agents is invalid")
                environment["agents"].append(agent)
            environment["state"] = "pending"
            environment_inventory.replace_catalog(catalog_path, raw, document, snapshots, initial_loaders)
    except environment_inventory.CatalogError as exc:
        raise PlacementError(str(exc)) from None
    print("inventory: agent pending")
    return 0


def inventory_activate(args, *, resolver=shutil.which):
    try:
        initial_snapshots = environment_inventory.snapshot_inputs(_inventory_source_paths(args))
        initial_loaders = _inventory_loader_inputs(args)
    except environment_inventory.CatalogError as exc:
        raise PlacementError(str(exc)) from None
    context = load_context(args)
    try:
        environment_inventory._assert_snapshots(initial_snapshots)
        environment_inventory._assert_loader_inputs(initial_loaders)
    except environment_inventory.CatalogError as exc:
        raise PlacementError(str(exc)) from None
    if not args.site or args.site not in context[2]:
        raise PlacementError("unknown site")
    _inventory_site_runtime(context, args.site)
    binding = inventory_binding(args, context, args.site)
    if binding is None:
        raise PlacementError("inventory activate requires an INVENTORY binding")
    declaration, catalog, environment_id = binding
    try:
        with environment_inventory.locked_catalog(
                catalog, _inventory_claim_scope(context, args.site, environment_id)) as (catalog_path, raw, document):
            environment_inventory.load_catalog(catalog_path, environment_id=environment_id)
            environment, _source_id = _catalog_placement_source(document, catalog_path, declaration, args.site, environment_id)
            descriptors = [agent.get("descriptor") for agent in environment.get("agents", []) if isinstance(agent, dict)]
            if not descriptors:
                raise PlacementError("catalog environment has no registered agents")
            locations = []
            for descriptor in descriptors:
                locations.extend(_inventory_locations(context, args.site, descriptor))
            snapshots = dict(initial_snapshots)
            outputs = environment_inventory.snapshot_inputs(_inventory_output_paths(context, locations))
            snapshots.update({path: value for path, value in outputs.items() if path not in snapshots})
            from types import SimpleNamespace
            lifecycle_spec = importlib.util.spec_from_file_location("inventory_lifecycle", HERE / "inventory_lifecycle.py")
            lifecycle = importlib.util.module_from_spec(lifecycle_spec)
            lifecycle_spec.loader.exec_module(lifecycle)
            errors, _record = lifecycle.validate_lifecycle(
                catalog_path, context, environment_id, mode="readiness",
                place_module=SimpleNamespace(**globals()), resolver=resolver,
                current_principal=current_runtime(context), declaration_path=declaration,
                required_site=args.site,
            )
            if errors:
                raise PlacementError("inventory readiness failed: " + "; ".join(errors))
            if environment["state"] == "active":
                environment_inventory._assert_snapshots(snapshots)
                environment_inventory._assert_loader_inputs(initial_loaders)
                if catalog_path.read_bytes() != raw:
                    raise PlacementError("catalog changed; retry the operation")
                print("inventory: already active")
                return 0
            environment["state"] = "active"
            environment_inventory.replace_catalog(catalog_path, raw, document, snapshots, initial_loaders)
    except environment_inventory.CatalogError as exc:
        raise PlacementError(str(exc)) from None
    print("inventory: active")
    return 0


def save_start_config(args):
    """Save validated launch inputs once, without replacing existing settings."""
    context = load_context(args)
    # Resolve every declaration row before publishing inputs; no placement or
    # process is changed by this operation.
    placement, rules, sites, workspaces, locations, exceptions, _, skills = context
    expected_writes(rules, placement, list(locations.values()), exceptions,
                    sites, workspaces, skills)
    path = Path(args.config).absolute()
    preflight_targets([path])
    if not path.parent.is_dir():
        raise PlacementError("start config parent directory does not exist")
    host = args.inventory_host
    if host is not None and not host.strip():
        raise PlacementError("inventory host must be non-empty")
    if host and os.environ.get("ENVIRONMENT_INVENTORY_HOST") not in (None, host):
        raise PlacementError("start config inventory_host conflicts with ENVIRONMENT_INVENTORY_HOST")
    def relative(value):
        resolved = Path(value).resolve()
        try:
            return os.path.relpath(resolved, path.parent)
        except ValueError:  # Explicit inputs on different Windows volumes.
            return str(resolved)
    document = {"version": 1, "declaration": relative(args.declaration)}
    for key in ("rules", "skills"):
        values = getattr(args, key, None)
        if values:
            document[key] = list(dict.fromkeys(relative(value) for value in values))
    if host:
        document["inventory_host"] = host
    def existing_matches():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise PlacementError("existing start config cannot be replaced; preserve and inspect it") from None
        if existing != document:
            raise PlacementError("existing start config differs; refusing to replace saved inputs")
    if path.exists():
        existing_matches()
        print("start config unchanged")
        return 0
    content = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".place-start-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        preflight_targets([path])
        # A hard link publishes the complete file atomically without replacing a
        # concurrently created config. No multi-file transaction is claimed.
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing_matches()
        print("start config saved")
        return 0
    except OSError as exc:
        raise PlacementError("could not save start config: %s" % (exc.strerror or "file operation failed")) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def start_config(args):
    """Resolve the deliberately selected start configuration, if any."""
    explicit = getattr(args, "config", None)
    declaration = getattr(args, "declaration", None)
    rules = getattr(args, "rules", None)
    skills = getattr(args, "skills", None)
    if explicit and (declaration or rules or skills):
        raise PlacementError("--config cannot be combined with --declaration, --rules, or --skills")
    if declaration:
        return None
    if rules or skills:
        raise PlacementError("--rules and --skills cannot be combined with an implicit start config")
    path = Path(explicit) if explicit else Path.cwd() / "placement-start.json"
    if not path.is_file():
        if explicit:
            raise PlacementError("start config does not exist: %s" % path)
        raise PlacementError("--declaration is required when %s is absent" % path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlacementError("invalid start config %s: %s" % (path, exc)) from None
    if not isinstance(document, dict):
        raise PlacementError("start config must be a JSON object")
    allowed = {"version", "declaration", "rules", "skills", "inventory_host"}
    unknown = set(document) - allowed
    if unknown:
        raise PlacementError("start config has unknown keys: %s" % ", ".join(sorted(unknown)))
    if type(document.get("version")) is not int or document["version"] != 1:
        raise PlacementError("start config version must be 1")
    if not isinstance(document.get("declaration"), str) or not document["declaration"].strip():
        raise PlacementError("start config declaration must be a non-empty string")
    for key in ("rules", "skills"):
        if key not in document:
            continue
        value = document[key]
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise PlacementError("start config %s must be an array of non-empty strings" % key)
    host = document.get("inventory_host")
    if host is not None and (not isinstance(host, str) or not host.strip()):
        raise PlacementError("start config inventory_host must be a non-empty string")
    base = path.resolve().parent
    def resolve(value):
        candidate = Path(value)
        return str(candidate if candidate.is_absolute() else base / candidate)
    args.declaration = resolve(document["declaration"])
    args.rules = [resolve(value) for value in document.get("rules", [])]
    args.skills = [resolve(value) for value in document.get("skills", [])]
    return host


def start(args, runner=subprocess.run, resolver=shutil.which):
    """Run one declared CLI in one local direct workspace.

    Remote transport and GUI orchestration are deliberately outside this portable
    command. Invoke this same entry point on the target host instead of depending
    on an environment-private launcher.
    """
    configured_host = start_config(args)
    old_host = os.environ.get("ENVIRONMENT_INVENTORY_HOST")
    if configured_host and old_host and old_host != configured_host:
        raise PlacementError("start config inventory_host conflicts with ENVIRONMENT_INVENTORY_HOST")
    if configured_host:
        os.environ["ENVIRONMENT_INVENTORY_HOST"] = configured_host
    try:
        return _start(args, runner=runner, resolver=resolver, configured_host=configured_host)
    finally:
        if configured_host:
            if old_host is None:
                os.environ.pop("ENVIRONMENT_INVENTORY_HOST", None)
            else:
                os.environ["ENVIRONMENT_INVENTORY_HOST"] = old_host


def _start(args, runner=subprocess.run, resolver=shutil.which, configured_host=None):
    context = load_context(args)
    placement, rules, sites, workspaces, locations, exceptions, _selected, skills = context
    workspace = workspaces.get(args.workspace_id)
    if workspace is None:
        raise PlacementError("unknown workspace: %s" % args.workspace_id)
    if workspace.get("kind") != "direct":
        raise PlacementError("workspace %s is not a local direct workspace" % args.workspace_id)
    site_id = workspace["site"]
    site = sites[site_id]
    if site.get("launch", "").strip():
        raise PlacementError(
            "workspace %s is remote; run place.py on site %s" % (args.workspace_id, site_id)
        )
    if not site_reachable(site):
        raise PlacementError("workspace %s site is not reachable" % args.workspace_id)
    if not Path(workspace["path"]).is_dir():
        raise PlacementError("workspace path does not exist: %s" % workspace["path"])
    if args.tool not in declared_tools(locations, workspaces, site_id):
        raise PlacementError("tool %s is not declared for site %s" % (args.tool, site_id))
    tool = placement["tools"].get(args.tool)
    if tool is None:
        raise PlacementError("unknown tool: %s" % args.tool)

    inventory_preflight(args, context, site_id, resolver=resolver, target_tool=args.tool)

    selected = [location for location in locations.values()
                if location["tool"] == args.tool and site_of(location, workspaces) == site_id]
    errors, _printed = check_state(
        rules, placement, selected, exceptions, sites, workspaces, locations, skills,
        check_installed=False,
    )
    if errors:
        raise PlacementError("placement check failed: " + "; ".join(errors))

    entrypoint = resolver(tool["entrypoint"])
    if entrypoint is None:
        raise PlacementError("tool does not resolve: %s" % tool["entrypoint"])
    kwargs = {"cwd": workspace["path"]}
    if configured_host:
        kwargs["env"] = os.environ.copy()
    return runner([entrypoint, *args.tool_args], **kwargs).returncode


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
        (payload / "keep.md").write_bytes(b"keep\n")
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

        # A config root can itself be a junction, even before its managed
        # children exist. Reject it before creating anything in the payload.
        config = workspace / ".cursor"
        saved_config = workspace / ".cursor-saved"
        config.rename(saved_config)
        make_link(config, payload)
        try:
            try:
                apply(ns)
            except PlacementError as exc:
                if "ancestor is a link" not in str(exc):
                    raise PlacementError("selfcheck stopped the ancestor for another reason: %s" % exc)
            else:
                raise PlacementError("selfcheck accepted a linked config ancestor")
            if sorted(path.name for path in payload.iterdir()) != ["keep.md"]:
                raise PlacementError("selfcheck wrote through a linked ancestor")
            if (payload / "keep.md").read_bytes() != b"keep\n":
                raise PlacementError("selfcheck changed the link payload")
        finally:
            if config.is_symlink():
                config.unlink()
            else:
                config.rmdir()
            saved_config.rename(config)
        if check(ns):
            raise PlacementError("selfcheck still failing after the ancestor link was removed")

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
        if os.name == "posix":
            script = Path(skills_dir) / "delta" / "check.sh"
            script.write_bytes(b"#!/bin/sh\nexit 0\n")
            script.chmod(0o4755)
            published_script = root / "mirror" / "skills" / "delta" / "check.sh"
            mirror(mirror_ns)
            if published_script.stat().st_mode & 0o7111 != 0o111:
                raise PlacementError("selfcheck mirror lost execute bits or copied special bits")
            subprocess.run([str(published_script)], check=True)
            published_script.chmod(0o644)
            mirror_ns.check = True
            if mirror(mirror_ns) == 0:
                raise PlacementError("selfcheck mirror missed executable drift")
            mirror_ns.check = False
            mirror(mirror_ns)
            subprocess.run([str(published_script)], check=True)
            script.chmod(0o644)
            mirror_ns.check = True
            if mirror(mirror_ns) == 0:
                raise PlacementError("selfcheck mirror missed source executable change")
            mirror_ns.check = False
            mirror(mirror_ns)
            if published_script.stat().st_mode & 0o111:
                raise PlacementError("selfcheck mirror retained removed execute bits")
        published_skill = root / "mirror" / "skills" / "delta"
        shutil.rmtree(published_skill)
        make_link(published_skill, payload)
        try:
            try:
                mirror(mirror_ns)
            except PlacementError:
                pass
            else:
                raise PlacementError("selfcheck mirror accepted a linked skill")
            if sorted(path.name for path in payload.iterdir()) != ["keep.md"]:
                raise PlacementError("selfcheck mirror wrote through a link")
            if (payload / "keep.md").read_bytes() != b"keep\n":
                raise PlacementError("selfcheck mirror changed the link payload")
        finally:
            if published_skill.is_symlink():
                published_skill.unlink()
            else:
                published_skill.rmdir()
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


def main(argv, *, runner=subprocess.run, resolver=shutil.which):
    if argv[:1] == ["branch"]:
        import branch_management
        return branch_management.main(argv[1:])
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
    check_inputs = check_p.add_mutually_exclusive_group(required=True)
    check_inputs.add_argument("--declaration")
    check_inputs.add_argument("--catalog")
    check_p.add_argument("--rules", action="append")
    check_p.add_argument("--skills", action="append")
    check_p.add_argument("--site")
    check_p.add_argument("--workspace")
    check_p.add_argument("--scope")
    check_p.add_argument("--environment")
    check_p.add_argument("--probe", action="store_true")
    check_p.add_argument("--readiness", action="store_true")
    apply_p = sub.add_parser("apply")
    add_common(apply_p)
    list_p = sub.add_parser("list")
    list_inputs = list_p.add_mutually_exclusive_group(required=True)
    list_inputs.add_argument("--declaration")
    list_inputs.add_argument("--catalog")
    list_p.add_argument("--purpose")
    list_p.add_argument("--json", action="store_true")
    list_p.add_argument("--probe", action="store_true")
    classify_p = sub.add_parser("classify", help="read-only work/environment classification")
    classify_p.add_argument("--catalog", required=True)
    classify_p.add_argument("--work", required=True)
    classify_p.add_argument("--prefer-environment")
    classify_p.add_argument("--json", action="store_true")
    inventory_p = sub.add_parser("inventory", help="bounded environment catalog operations")
    inventory_sub = inventory_p.add_subparsers(dest="inventory_command", required=True)
    for name in ("prepare-agent", "activate"):
        operation = inventory_sub.add_parser(name)
        operation.add_argument("--declaration", required=True)
        operation.add_argument("--site", required=True)
        operation.add_argument("--rules", action="append")
        operation.add_argument("--skills", action="append")
        if name == "prepare-agent":
            operation.add_argument("--tool", required=True)
    save_p = sub.add_parser("save-start-config", help="save validated launch inputs without replacing existing settings")
    save_p.add_argument("--config", default="placement-start.json")
    save_p.add_argument("--declaration", required=True)
    save_p.add_argument("--rules", action="append")
    save_p.add_argument("--skills", action="append")
    save_p.add_argument("--inventory-host")
    start_p = sub.add_parser("start")
    start_p.add_argument("--config")
    start_p.add_argument("--declaration")
    start_p.add_argument("--rules", action="append")
    start_p.add_argument("--skills", action="append")
    start_p.add_argument("workspace_id")
    start_p.add_argument("tool")
    start_p.add_argument("tool_args", nargs=argparse.REMAINDER)
    mirror_p = sub.add_parser("mirror")
    mirror_p.add_argument("--skills", action="append")
    mirror_p.add_argument("--dest", required=True)
    mirror_p.add_argument("--check", action="store_true")
    sub.add_parser("branch", help="register work and enforce Git branch operations")
    sub.add_parser("selfcheck")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            if args.catalog:
                if args.readiness:
                    raise PlacementError("--readiness requires --declaration, not --catalog")
                return check_catalog(args)
            if args.readiness and args.environment:
                raise PlacementError("--readiness resolves environment from INVENTORY; do not pass --environment")
            return check(args)
        if args.command == "apply":
            return apply(args)
        if args.command == "list":
            if args.catalog:
                return list_catalog(args)
            return list_workspaces(args)
        if args.command == "classify":
            return classify_work(args)
        if args.command == "inventory":
            if args.inventory_command == "prepare-agent":
                return inventory_prepare_agent(args)
            return inventory_activate(args, resolver=resolver)
        if args.command == "save-start-config":
            return save_start_config(args)
        if args.command == "start":
            if args.tool_args[:1] == ["--"]:
                args.tool_args = args.tool_args[1:]
            return start(args, runner=runner, resolver=resolver)
        if args.command == "mirror":
            return mirror(args)
        return selfcheck(args)
    except PlacementError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
