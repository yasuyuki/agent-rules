#!/usr/bin/env python3
"""Project rules onto the sites and workspaces a declaration names.

    place.py check  --declaration <path> --rules <dir> [--rules <dir>]
    place.py apply  --declaration <path> --rules <dir> [--rules <dir>] --backup-root <dir>
    place.py selfcheck

Optional --site / --workspace / --scope restrict which location rows apply.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
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


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
        if row["scope"] not in ("home", "workspace", "skills", "hooks"):
            raise PlacementError("location %s: unknown scope" % row["id"])
        if row["scope"] == "workspace":
            if row["anchor"] not in workspaces:
                raise PlacementError("location %s: unknown workspace %s" % (row["id"], row["anchor"]))
        elif row["anchor"] not in sites:
            raise PlacementError("location %s: unknown site %s" % (row["id"], row["anchor"]))
        by_id[row["id"]] = row
    exception_map = {}
    for row in exceptions:
        key = (row["rule"], row["location_id"])
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


def rule_applies(meta, location, exceptions, placement):
    key = (meta["id"], location["id"])
    if key in exceptions:
        return exceptions[key]["requirement"] == "required"
    if location["requirement"] != "required":
        return False
    if location["scope"] not in ("home", "workspace"):
        return False
    return location["tool"] in agent_rules.selected_tools(meta, placement)


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


def expected_writes(rules, placement, locations, exceptions, sites, workspaces):
    files, sections = {}, {}
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        tool = loc["tool"]
        if tool not in placement["tools"]:
            raise PlacementError("location %s: unknown tool %s" % (loc["id"], tool))
        for conv_id in placement["tools"][tool]["reads"]:
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


def overlap_roots(locations, sites, workspaces):
    roots = []
    for loc in locations:
        if loc["scope"] == "workspace":
            roots.append(Path(workspaces[loc["anchor"]]["path"]))
        elif loc["scope"] == "home":
            roots.append(Path(sites[loc["anchor"]]["home"]))
    return roots


def affected_targets(files, sections, locations, placement, sites, workspaces):
    targets = list(files) + list(sections)
    for loc in locations:
        if loc["scope"] not in ("home", "workspace"):
            continue
        for conv_id in placement["tools"].get(loc["tool"], {}).get("reads", []):
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


def preflight_targets(targets, backup_root, extra_roots=()):
    backup = backup_root.resolve(strict=False)
    for target in list(targets) + list(extra_roots):
        resolved = target.resolve(strict=False)
        if backup == resolved or backup in resolved.parents or resolved in backup.parents:
            raise PlacementError("backup root overlaps affected target: %s" % target)
    for target in targets:
        if target.is_symlink():
            raise PlacementError("affected target is a symlink: %s" % target)
        if target.is_dir() and any(path.is_symlink() for path in target.rglob("*")):
            raise PlacementError("affected target contains a symlink: %s" % target)


def snapshot(targets, backup_root):
    manifest, store = [], backup_root / "items"
    store.mkdir(parents=True)
    for number, target in enumerate(targets):
        entry = {"path": str(target), "store": str(number), "kind": "missing"}
        destination = store / str(number)
        if target.is_file():
            entry.update(kind="file", sha256=sha256(target))
            shutil.copy2(target, destination)
        elif target.is_dir():
            entry["kind"] = "dir"
            shutil.copytree(target, destination)
            entry["files"] = {
                str(path.relative_to(target)): sha256(path)
                for path in target.rglob("*")
                if path.is_file()
            }
        manifest.append(entry)
    (backup_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def restore(manifest, backup_root):
    for entry in manifest:
        target = Path(entry["path"])
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        source = backup_root / "items" / entry["store"]
        if entry["kind"] == "file":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif entry["kind"] == "dir":
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)


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


def check_state(rules, placement, locations, exceptions, sites, workspaces, all_locations):
    errors = []
    reachable = [loc for loc in locations if site_reachable(sites[site_of(loc, workspaces)])]
    files, sections = expected_writes(rules, placement, reachable, exceptions, sites, workspaces)
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
        for conv_id in placement["tools"].get(loc["tool"], {}).get("reads", []):
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
    for site_id, site in sites.items():
        if not site_reachable(site):
            continue
        declared = declared_tools(all_locations, workspaces, site_id)
        for tool, spec in placement["tools"].items():
            if detect_cli(site, spec) and tool not in declared:
                errors.append("%s: installed CLI '%s' has no required or absent location" % (site_id, tool))
    return errors, printed


def apply_projection(rules, placement, locations, exceptions, sites, workspaces):
    files, sections = expected_writes(rules, placement, locations, exceptions, sites, workspaces)
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
        for conv_id in placement["tools"].get(loc["tool"], {}).get("reads", []):
            directory = managed_dir(loc, conv_id, placement, sites, workspaces)
            spec = placement["conventions"][conv_id]
            if directory is None or not directory.is_dir():
                continue
            template = spec.get("home_path") if loc["scope"] == "home" else spec.get("path", "")
            if "{id}" not in template:
                continue
            _, prefix, suffix = agent_rules.managed_names(template)
            owned = {path.resolve(strict=False) for path in files}
            for path in list(directory.iterdir()):
                if path.is_file() and path.name.startswith(prefix) and path.name.endswith(suffix) and path.resolve(strict=False) not in owned:
                    path.unlink()
    for dest, content in files.items():
        atomic_write(dest, content)
    for dest, blocks in sections.items():
        atomic_write(dest, render_sections(dest, blocks))


def load_context(args):
    if not args.declaration:
        raise PlacementError("--declaration is required")
    if not args.rules:
        raise PlacementError("--rules is required")
    placement = load_placement()
    rules = agent_rules.load_rule_dirs(placement, args.rules)
    sites, workspaces, locations, exceptions = parse_declaration(args.declaration)
    selected = filter_locations(
        locations, workspaces, getattr(args, "site", None), getattr(args, "workspace", None), getattr(args, "scope", None)
    )
    return placement, rules, sites, workspaces, locations, exceptions, selected


def check(args):
    placement, rules, sites, workspaces, locations, exceptions, selected = load_context(args)
    errors, printed = check_state(rules, placement, selected, exceptions, sites, workspaces, locations)
    for path in printed:
        print(path)
    for error in errors:
        print("FAIL: " + error, file=sys.stderr)
    print("place: %s" % ("OK" if not errors else "FAILED (%d)" % len(errors)))
    return 0 if not errors else 1


def apply(args):
    backup_root = Path(args.backup_root)
    if backup_root.exists():
        raise PlacementError("backup root must not already exist: %s" % backup_root)
    placement, rules, sites, workspaces, locations, exceptions, selected = load_context(args)
    files, sections = expected_writes(rules, placement, selected, exceptions, sites, workspaces)
    targets = affected_targets(files, sections, selected, placement, sites, workspaces)
    preflight_targets(targets, backup_root, overlap_roots(selected, sites, workspaces))
    backup_root.mkdir(parents=True)
    manifest = snapshot(targets, backup_root)
    try:
        apply_projection(rules, placement, selected, exceptions, sites, workspaces)
        if os.environ.get("PLACE_FORCE_POSTCHECK_FAILURE"):
            raise PlacementError("forced post-check failure")
        errors, _ = check_state(rules, placement, selected, exceptions, sites, workspaces, locations)
        if errors:
            raise PlacementError("post-check failed: " + "; ".join(errors))
    except Exception:
        restore(manifest, backup_root)
        raise
    print("place: applied; backup at %s" % backup_root)
    return 0


def write_rule(directory, rule_id, title, tools=None):
    directory.mkdir(parents=True, exist_ok=True)
    tools_line = "tools: [%s]\n" % ", ".join(tools) if tools else ""
    (directory / ("%s.rule.md" % rule_id)).write_text(
        "---\nid: %s\ntitle: %s\nsummary: %s\n%s---\n\n%s body.\n" % (rule_id, title, title, tools_line, title),
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
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".local" / "bin" / "claude").write_text("", encoding="utf-8")
        (home / ".local" / "bin" / "cursor-agent").write_text("", encoding="utf-8")
        public_rules, private_rules = root / "public-rules", root / "private-rules"
        write_rule(public_rules, "alpha", "Alpha")
        write_rule(public_rules, "beta", "Beta", ["cursor-agent"])
        write_rule(private_rules, "gamma", "Gamma")
        declaration = source.replace("{ROOT}", str(root).replace("\\", "/"))
        decl_path = root / "PLACEMENT.md"
        decl_path.write_text(declaration, encoding="utf-8", newline="\n")
        ns = argparse.Namespace(
            declaration=str(decl_path),
            rules=[str(public_rules), str(private_rules)],
            backup_root=str(root / "backup"),
            site=None,
            workspace=None,
            scope=None,
        )
        if apply(ns):
            raise PlacementError("selfcheck apply failed")
        if check(ns):
            raise PlacementError("selfcheck check failed after apply")
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
        generated = workspace / ".cursor" / "rules" / "agent-rules--beta.mdc"
        generated.write_bytes(generated.read_bytes() + b"changed\n")
        if not check(ns):
            raise PlacementError("selfcheck accepted drift")
        apply(argparse.Namespace(
            declaration=str(decl_path),
            rules=ns.rules,
            backup_root=str(root / "backup-fix"),
            site=None,
            workspace=None,
            scope=None,
        ))
        if check(ns):
            raise PlacementError("selfcheck apply did not repair drift")
        try:
            apply(argparse.Namespace(
                declaration=str(decl_path),
                rules=ns.rules,
                backup_root=str(workspace / "overlap"),
                site=None,
                workspace=None,
                scope=None,
            ))
        except PlacementError:
            pass
        else:
            raise PlacementError("selfcheck accepted overlapping backup")
        os.environ["PLACE_FORCE_POSTCHECK_FAILURE"] = "1"
        try:
            try:
                apply(argparse.Namespace(
                    declaration=str(decl_path),
                    rules=ns.rules,
                    backup_root=str(root / "rollback"),
                    site=None,
                    workspace=None,
                    scope=None,
                ))
            except PlacementError:
                pass
            else:
                raise PlacementError("selfcheck forced failure did not raise")
        finally:
            os.environ.pop("PLACE_FORCE_POSTCHECK_FAILURE", None)
        if check(ns):
            raise PlacementError("selfcheck rollback did not restore")
    print("place: selfcheck OK")
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser):
        subparser.add_argument("--declaration")
        subparser.add_argument("--rules", action="append")
        subparser.add_argument("--site")
        subparser.add_argument("--workspace")
        subparser.add_argument("--scope")

    check_p = sub.add_parser("check")
    add_common(check_p)
    apply_p = sub.add_parser("apply")
    add_common(apply_p)
    apply_p.add_argument("--backup-root", required=True)
    sub.add_parser("selfcheck")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return check(args)
        if args.command == "apply":
            return apply(args)
        return selfcheck(args)
    except PlacementError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
