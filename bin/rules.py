#!/usr/bin/env python3
"""Render the canonical agent rules into each tool's effective path, and check
that what is on disk is what the canonical source produces.

    rules.py render <workspace>    write every rule to every tool path
    rules.py verify <workspace>    compare disk against the canonical source

One rule body is written once. Per-tool differences live in `<!-- binding: X -->`
sections of the same file, so a diff between tools is visible in one place
instead of being spread over several near-identical files.
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


def convention_ids_for(meta, placement):
    seen = []
    for tool in selected_tools(meta, placement):
        spec = placement["tools"].get(tool)
        if spec is None:
            raise SystemExit("placement.json has no entry for tool '%s'" % tool)
        for conv_id in spec["reads"]:
            if conv_id not in placement["conventions"]:
                raise SystemExit("placement.json has no convention '%s'" % conv_id)
            if conv_id not in seen:
                seen.append(conv_id)
    return seen


def body_for_convention(meta, common, bindings, conv_id, placement):
    out = "# %s\n\n%s\n" % (meta["title"], common.strip())
    for tool in selected_tools(meta, placement):
        if conv_id in placement["tools"][tool]["reads"] and tool in bindings:
            out += "\n%s\n" % bindings[tool].strip()
    return out


def load_rules(placement):
    rules = []
    known = set(placement["tools"])
    for name in sorted(os.listdir(RULES_DIR)):
        if not name.endswith(".rule.md"):
            continue
        path = os.path.join(RULES_DIR, name)
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
    if not rules:
        raise SystemExit("no rules found in %s" % RULES_DIR)
    return rules


def expected_files(rules, placement):
    """(path, content) for every convention that writes one file per rule."""
    out = {}
    for meta, common, bindings in rules:
        for conv_id in convention_ids_for(meta, placement):
            spec = placement["conventions"][conv_id]
            if spec.get("mode") == "section":
                continue
            body = body_for_convention(meta, common, bindings, conv_id, placement)
            if spec.get("frontmatter"):
                header = "".join(
                    "%s: %s\n" % (key, meta["summary"] if value == "@summary" else value)
                    for key, value in spec["frontmatter"].items()
                )
                body = "---\n%s---\n\n%s" % (header, body)
            out[spec["path"].format(id=meta["id"])] = body
    return out


def expected_sections(rules, placement):
    """(file, {id: content}) for conventions that splice sections into one shared file."""
    out = {}
    for meta, common, bindings in rules:
        for conv_id in convention_ids_for(meta, placement):
            spec = placement["conventions"][conv_id]
            if spec.get("mode") != "section":
                continue
            out.setdefault(spec["path"], {})[meta["id"]] = body_for_convention(
                meta, common, bindings, conv_id, placement
            )
    return out


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


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def convention_specs(placement):
    return placement["conventions"].values()


def main(argv):
    if len(argv) != 3 or argv[1] not in ("render", "verify"):
        raise SystemExit(__doc__)
    command, workspace = argv[1], os.path.abspath(argv[2])
    with open(PLACEMENT, encoding="utf-8") as handle:
        placement = json.load(handle)
    rules = load_rules(placement)
    files = expected_files(rules, placement)
    sections = expected_sections(rules, placement)

    if command == "render":
        expected_paths = set(files)
        for spec in convention_specs(placement):
            template = spec.get("path", "")
            if spec.get("mode") == "section" or "{id}" not in template:
                continue
            relative_dir, prefix, suffix = managed_names(template)
            directory = os.path.join(workspace, relative_dir)
            if not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                relative = os.path.join(relative_dir, name).replace(os.sep, "/")
                if name.startswith(prefix) and name.endswith(suffix) and relative not in expected_paths:
                    os.remove(os.path.join(directory, name))
        for relative, content in sorted(files.items()):
            write(os.path.join(workspace, relative), content)
        for relative, blocks in sorted(sections.items()):
            path = os.path.join(workspace, relative)
            text = read(path) or ""
            require_balanced_markers(text, path)
            text = remove_stale_sections(text, set(blocks))
            for rule_id in sorted(blocks):
                text = splice(text, rule_id, blocks[rule_id])
            write(path, text)
        print("rendered %d rules" % len(rules))
        return 0

    drift = []
    for relative, content in sorted(files.items()):
        actual = read(os.path.join(workspace, relative))
        if actual is None:
            drift.append("missing: %s" % relative)
        elif actual != content:
            drift.append("differs from canonical: %s" % relative)
    expected_paths = set(files)
    for spec in convention_specs(placement):
        template = spec.get("path", "")
        if spec.get("mode") == "section" or "{id}" not in template:
            continue
        relative_dir, prefix, suffix = managed_names(template)
        directory = os.path.join(workspace, relative_dir)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            relative = os.path.join(relative_dir, name).replace(os.sep, "/")
            if (
                os.path.isfile(os.path.join(directory, name))
                and name.startswith(prefix)
                and name.endswith(suffix)
                and relative not in expected_paths
            ):
                drift.append("unexpected managed rule: %s" % relative)
    for relative, blocks in sorted(sections.items()):
        text = read(os.path.join(workspace, relative))
        if text is None:
            drift.append("missing: %s" % relative)
            continue
        markers = list(MARKER.findall(text))
        begins = [rule_id for kind, rule_id in markers if kind == "begin"]
        ends = [rule_id for kind, rule_id in markers if kind == "end"]
        for rule_id in sorted((set(begins) | set(ends)) - set(blocks)):
            drift.append("unexpected section '%s' in %s" % (rule_id, relative))
        for rule_id in sorted(set(begins) | set(ends)):
            if begins.count(rule_id) != ends.count(rule_id):
                drift.append("unpaired section marker '%s' in %s" % (rule_id, relative))
        for rule_id in sorted(blocks):
            actual = extract_all(text, rule_id)
            if not actual:
                drift.append("missing section '%s' in %s" % (rule_id, relative))
            elif len(actual) > 1:
                drift.append("duplicate section '%s' in %s" % (rule_id, relative))
            elif actual[0] != blocks[rule_id]:
                drift.append("section '%s' differs from canonical in %s" % (rule_id, relative))

    for line in drift:
        print(line)
    print("separated" if not drift else "contaminated (%d)" % len(drift))
    return 0 if not drift else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
