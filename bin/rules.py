#!/usr/bin/env python3
"""Legacy declaration input and section helpers for pinned runtime consumers.

New project placement uses rulesync_backend; this module is not packaged.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RULES_DIR = os.path.join(ROOT, "rules")
PLACEMENT = os.path.join(ROOT, "placement.json")

BEGIN = "<!-- agent-rules:begin {id} -->"
END = "<!-- agent-rules:end {id} -->"
MARKER = re.compile(r"^<!-- agent-rules:(begin|end) ([a-z0-9-]+) -->$", re.M)


def parse_rule(path):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if not match:
        raise SystemExit("%s: missing frontmatter" % path)
    meta = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            value = [item.strip() for item in value[1:-1].split(",") if item.strip()]
        meta[key] = value
    for required in ("id", "title", "summary"):
        if required not in meta:
            raise SystemExit("%s: frontmatter is missing '%s'" % (path, required))

    parts = re.split(r"^<!-- binding: ([a-z0-9-]+) -->$", match.group(2), flags=re.M)
    bindings = {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}
    return meta, parts[0], bindings


def selected_tools(meta, placement):
    names = meta.get("tools")
    if not names:
        return list(placement["tools"])
    return names


def body_for_convention(meta, common, bindings, conv_id, placement):
    out = "# %s\n\n%s\n" % (meta["title"], common.strip())
    for tool in selected_tools(meta, placement):
        if conv_id in placement["tools"][tool]["reads"]["rules"] and tool in bindings:
            out += "\n%s\n" % bindings[tool].strip()
    return out


def load_rules(placement, rules_dir=None, *, allow_empty=False):
    directory = RULES_DIR if rules_dir is None else rules_dir
    rules = []
    known = set(placement["tools"])
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".rule.md"):
            continue
        path = os.path.join(directory, name)
        meta, common, bindings = parse_rule(path)
        if meta["id"] != name[: -len(".rule.md")]:
            raise SystemExit("%s: id does not match the file name" % path)
        if not re.fullmatch(r"[a-z0-9-]+", meta["id"]):
            raise SystemExit("%s: id must contain only lowercase letters, digits, and hyphens" % path)
        allowed = set(selected_tools(meta, placement))
        missing = allowed - known
        if missing:
            raise SystemExit("%s: unknown tools: %s" % (path, sorted(missing)))
        unknown = set(bindings) - allowed
        if unknown:
            raise SystemExit("%s: binding for a tool not in tools: %s" % (path, sorted(unknown)))
        rules.append((meta, common, bindings))
    if not rules and not allow_empty:
        raise SystemExit("no rules found in %s" % directory)
    return rules


SKILL_MARKER = ".agent-skills"
SKILL_MANIFEST = "UPSTREAM.tsv"
SKILL_MANIFEST_HEADER = ("id", "repo", "ref", "path", "tree_sha", "license")


def parse_skill_frontmatter(text, path):
    # Parse native Windows text without changing the verbatim skill payload.
    text = text.replace("\r\n", "\n")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise SystemExit("%s: missing frontmatter" % path)
    meta = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


class SkillContent(bytes):
    """Verbatim payload plus POSIX execute bits; other permissions are not copied."""

    def __new__(cls, data, executable):
        value = super().__new__(cls, data)
        value.executable = executable
        return value


def load_skills(skills_dir):
    """{id: {relative path: bytes}} for every skill directory under `skills_dir`.

    The tree is carried verbatim, so a vendored upstream skill stays diffable
    against its source. Placement metadata lives in the declaration, never in
    SKILL.md."""
    skills = {}
    if not os.path.isdir(skills_dir):
        return skills
    for name in sorted(os.listdir(skills_dir)):
        directory = os.path.join(skills_dir, name)
        if not os.path.isdir(directory):
            continue
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise SystemExit("%s: skill id must contain only lowercase letters, digits, and hyphens" % directory)
        skill_md = os.path.join(directory, "SKILL.md")
        if not os.path.isfile(skill_md):
            raise SystemExit("%s: skill directory has no SKILL.md" % directory)
        tree = {}
        for current, dirs, names in os.walk(directory):
            dirs.sort()
            for filename in sorted(names):
                full = os.path.join(current, filename)
                relative = os.path.relpath(full, directory).replace(os.sep, "/")
                if relative == SKILL_MARKER:
                    raise SystemExit("%s: %s is generated and must not be in the source" % (full, SKILL_MARKER))
                with open(full, "rb") as handle:
                    tree[relative] = SkillContent(
                        handle.read(), os.fstat(handle.fileno()).st_mode & 0o111 if os.name == "posix" else None
                    )
        meta = parse_skill_frontmatter(tree["SKILL.md"].decode("utf-8"), skill_md)
        for required in ("name", "description"):
            if not meta.get(required):
                raise SystemExit("%s: frontmatter is missing '%s'" % (skill_md, required))
        if meta["name"] != name:
            raise SystemExit("%s: frontmatter name '%s' does not match the directory" % (skill_md, meta["name"]))
        skills[name] = tree
    return skills


def load_skill_dirs(skills_dirs):
    skills = {}
    for skills_dir in skills_dirs or []:
        for skill_id, tree in load_skills(skills_dir).items():
            if skill_id in skills:
                raise SystemExit("duplicate skill id '%s'" % skill_id)
            skills[skill_id] = tree
    return skills


def load_rule_dirs(placement, rules_dirs, *, allow_empty=False):
    rules, seen = [], set()
    for rules_dir in rules_dirs:
        for item in load_rules(placement, rules_dir, allow_empty=allow_empty):
            rule_id = item[0]["id"]
            if rule_id in seen:
                raise SystemExit("duplicate rule id '%s'" % rule_id)
            seen.add(rule_id)
            rules.append(item)
    if not rules and not allow_empty:
        raise SystemExit("no rules found in %s" % rules_dirs)
    return rules


def splice(text, rule_id, body):
    begin, end = BEGIN.format(id=rule_id), END.format(id=rule_id)
    block = "%s\n%s%s\n" % (begin, body, end)
    pattern = re.compile(
        r"^%s\n.*?^%s\n" % (re.escape(begin), re.escape(end)), re.S | re.M
    )
    matches = list(pattern.finditer(text))
    if matches:
        first = matches[0]
        return text[: first.start()] + block + pattern.sub("", text[first.end() :])
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text else "") + block


def extract_all(text, rule_id):
    begin, end = BEGIN.format(id=rule_id), END.format(id=rule_id)
    return re.findall(
        r"^%s\n(.*?)^%s\n" % (re.escape(begin), re.escape(end)), text, re.S | re.M
    )


def remove_stale_sections(text, expected_ids):
    pattern = re.compile(
        r"^<!-- agent-rules:begin ([a-z0-9-]+) -->\n.*?"
        r"^<!-- agent-rules:end \1 -->\n",
        re.S | re.M,
    )
    return pattern.sub(lambda match: match.group(0) if match.group(1) in expected_ids else "", text)


def require_balanced_markers(text, path):
    stack = []
    for kind, rule_id in MARKER.findall(text):
        if kind == "begin":
            stack.append(rule_id)
        elif not stack or stack.pop() != rule_id:
            raise SystemExit("%s: malformed agent-rules markers; repair them before rendering" % path)
    if stack:
        raise SystemExit("%s: malformed agent-rules markers; repair them before rendering" % path)


def managed_names(template):
    directory = os.path.dirname(template)
    basename = os.path.basename(template)
    prefix, suffix = basename.split("{id}", 1)
    return directory, prefix, suffix


def export_sources(sources, destination, targets, exclude_ids=(), global_mode=False, skills_sources=()):
    """Convert selected legacy policy inputs once into native Rulesync sources.

    The destination must be new. Exported files are disposable build inputs,
    never a second editable source or a generated consumer location.
    """
    from pathlib import Path
    import shutil
    import tempfile
    target_tools = {"codexcli": "codex", "claudecode": "claude", "grokcli": "grok"}
    if not targets or set(targets) - set(target_tools):
        raise ValueError("select codexcli, claudecode and/or grokcli")
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("export destination must not exist")
    with open(PLACEMENT, encoding="utf-8") as handle:
        placement = json.load(handle)
    rules = load_rule_dirs(placement, sources, allow_empty=True)
    excluded = set(exclude_ids)
    unknown = excluded - {meta["id"] for meta, _, _ in rules}
    if unknown:
        raise ValueError("unknown excluded rule ids: " + ", ".join(sorted(unknown)))
    rules = [rule for rule in rules if rule[0]["id"] not in excluded]
    skills = load_skill_dirs(skills_sources)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        root = Path(temporary) / "source"
        (root / "rules").mkdir(parents=True)
        for skill_id, tree in skills.items():
            for relative, content in tree.items():
                path = root / "skills" / skill_id / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                if os.name != "nt":
                    path.chmod(0o644 | getattr(content, "executable", 0))
        for meta, common, bindings in rules:
            allowed = selected_tools(meta, placement)
            shared = [tool for tool in allowed if
                      "agents-md-section" in placement["tools"][tool]["reads"]["rules"]]
            active = [target for target in targets if
                      target_tools[target] in allowed or
                      (target in ("codexcli", "grokcli") and shared)]
            if not active:
                continue
            def emit(suffix, selected, body, root_rule=False):
                header = "---\nroot: %s\ntargets: %s\n---\n" % (
                    "true" if root_rule else "false", json.dumps(selected))
                (root / "rules" / (meta["id"] + suffix + ".md")).write_text(
                    header + body.strip() + "\n", encoding="utf-8", newline="\n")
            # Grok reads CLAUDE.md as well as AGENTS.md. Keep Claude in its
            # native rules directory; one target owns the shared AGENTS.md.
            shared_targets = [target for target in active if target in ("codexcli", "grokcli")]
            writer = "codexcli" if "codexcli" in shared_targets else "grokcli" if shared_targets else None
            common_targets = [target for target in active if target in ("codexcli", "claudecode")]
            body = "# " + meta["title"] + "\n\n" + common.strip()
            if common_targets:
                emit("-00", common_targets, body)
            if "grokcli" in shared_targets and (global_mode or writer == "grokcli"):
                emit("-00-grok", ["grokcli"], body, root_rule=True)
            shared_body = "\n\n".join(bindings[tool].strip() for tool in shared if tool in bindings)
            if writer and shared_body:
                emit("-01-shared", [writer], shared_body, root_rule=writer == "grokcli")
                if global_mode and writer == "codexcli" and "grokcli" in shared_targets:
                    emit("-01-grok", ["grokcli"], shared_body, root_rule=True)
            if "claudecode" in active and "claude" in bindings:
                emit("-01-claude", ["claudecode"], bindings["claude"])
        shutil.move(str(root), str(destination))
    return len(rules)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export explicit policy inputs to disposable native Rulesync source")
    parser.add_argument("source", nargs="+", help="explicit directories containing canonical .rule.md files")
    parser.add_argument("--dest", required=True, help="new disposable source directory")
    parser.add_argument("--targets", nargs="+", required=True,
                        choices=["codexcli", "claudecode", "grokcli"])
    parser.add_argument("--exclude-id", action="append", default=[],
                        help="explicit scope exclusion from the selected sources (repeatable)")
    parser.add_argument("--global", dest="global_mode", action="store_true",
                        help="export separate native user-scope roots rather than shared project AGENTS.md")
    parser.add_argument("--skills", action="append", default=[],
                        help="explicit native skill source directory for this disposable input tree")
    args = parser.parse_args()
    try:
        print("Exported %d rules" % export_sources(args.source, args.dest, args.targets, args.exclude_id, args.global_mode, args.skills))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
