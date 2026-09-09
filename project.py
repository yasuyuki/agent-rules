"""Project-only onboarding, backed by the existing placement engine."""

from __future__ import annotations

import argparse
import json
from importlib.metadata import version
import os
from pathlib import Path
import sys

from .bin import place


DEFAULT_CONFIG = Path(".agent-rules/config.json")
DEFAULT_SOURCES = {"rules": ".agent-rules/rules", "skills": ".agent-rules/skills"}


def config_path(value=None):
    path = Path(value) if value else Path.cwd() / DEFAULT_CONFIG
    path = path.absolute()
    if path.parent.name != ".agent-rules":
        raise place.PlacementError("config must be inside the project's .agent-rules directory")
    # Reject links before resolving; then use one spelling for both the root
    # and its sources, including Windows short-name aliases such as RUNNER~1.
    place.preflight_targets([path])
    return path.resolve()


def validate(config, path, *, creating=False):
    if not isinstance(config, dict) or set(config) != {"version", "tools", "rules", "skills"}:
        raise place.PlacementError("config requires exactly version, tools, rules and skills")
    if type(config["version"]) is not int or config["version"] != 1:
        raise place.PlacementError("unsupported config version (expected 1)")
    placement = place.load_placement()
    tools = config["tools"]
    if not isinstance(tools, list) or not tools or any(not isinstance(t, str) for t in tools):
        raise place.PlacementError("tools must be a nonempty list of tool ids")
    if len(set(tools)) != len(tools) or set(tools) - set(placement["tools"]):
        raise place.PlacementError("tools must be unique ids from: " + ", ".join(placement["tools"]))
    root = path.parent.parent
    sources = {}
    for kind in DEFAULT_SOURCES:
        values = config[kind]
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise place.PlacementError(kind + " must be a list of nonempty directory paths")
        sources[kind] = []
        for value in values:
            source = Path(value)
            if not source.is_absolute():
                source = root / source
            place.preflight_targets([source])
            source = source.resolve()
            if not source.is_dir() and not (
                creating and value == DEFAULT_SOURCES[kind] and not source.exists()
            ):
                raise place.PlacementError("source directory is missing: %s" % source)
            if source not in sources[kind]:
                sources[kind].append(source)
    # A source must never be a destination, or encompass one. Otherwise an apply
    # could overwrite its own input or ingest its generated skill markers.
    for tool in tools:
        for kind in DEFAULT_SOURCES:
            for conv in place.conventions_for(placement, tool, kind):
                spec = placement["conventions"][conv]
                target = root / spec["path"].format(id="placeholder")
                if spec.get("mode") != "section":
                    target = target.parent
                target = target.resolve()
                for source in sources["rules"] + sources["skills"]:
                    if source == target or source in target.parents or target in source.parents:
                        raise place.PlacementError("source overlaps a managed destination: %s" % source)
    return placement, root, sources


def load_project(path):
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise place.PlacementError("config not found: %s; run agent-rules init in that project" % path)
    placement, root, sources = validate(config, path)
    rules = place.agent_rules.load_rule_dirs(placement, sources["rules"], allow_empty=True)
    skills = place.agent_rules.load_skill_dirs(sources["skills"])
    duplicates = {meta["id"] for meta, _, _ in rules} & set(skills)
    if duplicates:
        raise place.PlacementError("id claimed by both a rule and a skill: " + ", ".join(sorted(duplicates)))
    sites = {"project": {"home": str(root), "reach": "local"}}
    workspaces = {"project": {"site": "project", "kind": "direct", "path": str(root)}}
    locations = {}
    for tool in config["tools"]:
        for kind in DEFAULT_SOURCES:
            if not place.conventions_for(placement, tool, kind):
                if sources[kind]:
                    print("Note: %s does not support %s placement; %s will not be deployed to this tool."
                          % (tool, kind, kind))
                continue
            if not sources[kind]:
                continue
            key = tool + "-" + kind
            locations[key] = {"id": key, "tool": tool, "scope": "workspace",
                              "anchor": "project", "kind": kind, "requirement": "required"}
    print("Sources: %d rules, %d skills." % (len(rules), len(skills)))
    if not rules and not skills:
        print("Sources are empty: no rules or skills to install; existing managed content in selected locations will be reconciled.")
    return placement, rules, sites, workspaces, locations, {}, list(locations.values()), skills


def initialize(args):
    path = config_path(args.config)
    if path.exists():
        raise place.PlacementError("config already exists; edit it explicitly: %s" % path)
    tools = args.tools
    if args.non_interactive and not tools:
        raise place.PlacementError("--non-interactive requires --tools")
    if not args.non_interactive:
        if tools is None:
            print("Available tools: " + ", ".join(place.load_placement()["tools"]))
            tools = input("Tools (comma or space separated, no default): ").replace(",", " ").split()
    config = {"version": 1, "tools": tools}
    for kind, default in DEFAULT_SOURCES.items():
        values = getattr(args, kind)
        if values is None:
            value = default if args.non_interactive else input(
                "%s source directory [%s] (- to leave this kind unmanaged): " % (kind.capitalize(), default)
            ).strip() or default
            values = [] if value == "-" else [value]
        config[kind] = values
    _, root, sources = validate(config, path, creating=True)
    for kind, directories in sources.items():
        config[kind] = []
        for directory in directories:
            try:
                config[kind].append(Path(os.path.relpath(directory, root)).as_posix())
            except ValueError:  # Explicit source on a different Windows drive.
                config[kind].append(str(directory))
    created = []
    wrote_config = False
    try:
        directories = [path.parent] + sources["rules"] + sources["skills"]
        for directory in directories:
            if not directory.exists():
                directory.mkdir()
                created.append(directory)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            wrote_config = True
            handle.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    except BaseException:
        if wrote_config:
            path.unlink()
        for directory in reversed(created):
            directory.rmdir()
        raise
    print("Created %s" % path)
    print("Project: %s" % root)
    print("No tool configuration has been changed. Add your own rules/skills to the source directories, then run agent-rules apply.")
    return 0


def main(argv=None):
    # Piped prompts and paths have the same encoding on Windows and Linux.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=version("agent-rules"))
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create project configuration interactively")
    init.add_argument("--config", help="configuration inside the target project's .agent-rules directory")
    init.add_argument("--tools", nargs="+", help="explicit tool ids")
    init.add_argument("--rules", action="append", help="rule source directory (repeatable)")
    init.add_argument("--skills", action="append", help="skill source directory (repeatable)")
    init.add_argument("--non-interactive", action="store_true", help="use supplied tools and default source paths without prompts")
    for command in ("apply", "check"):
        entry = sub.add_parser(command, help=command + " configured project rules and skills")
        entry.add_argument("--config", help="configuration inside the target project's .agent-rules directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return initialize(args)
        context = load_project(config_path(args.config))
        return getattr(place, args.command)(args, context=context)
    except (EOFError, KeyboardInterrupt):
        print("Cancelled.", file=sys.stderr)
        return 1
    except (OSError, ValueError, place.PlacementError) as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
