"""Check bounded, maintained Markdown links without fetching the network.

Supported links are ordinary inline ``[label](relative/path.md#heading)`` links
and fragment-only ``[label](#heading)`` links.  The checker intentionally does
not interpret reference-style links, HTML, URLs, absolute paths, or Markdown
extensions.  Fenced and inline code are excluded so examples do not become
documentation dependencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote


LINK = re.compile(r"(?<!!)\[[^]\n]*\]\(([^()\s]+)(?:\s+[^)]*)?\)")
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True)
class Problem:
    source: Path
    target: str
    message: str

    def __str__(self):
        return "%s: %s (%s)" % (self.source.as_posix(), self.message, self.target)


def _tracked_markdown(root):
    """Return tracked Markdown files in the documented source roots."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        names = [Path(name) for name in result.stdout.decode("utf-8").split("\0") if name]
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        raise RuntimeError("cannot list tracked Markdown documents") from exc
    return sorted((root / name for name in names if _is_maintained(name)), key=lambda path: path.as_posix())


def _is_maintained(path):
    parts = path.parts
    return path == Path("README.md") or (parts and parts[0] in {"docs", "rules", "skills"})


def _without_fences(text):
    """Strip ordinary fenced blocks while retaining prose, including inline code."""
    lines = []
    marker = None
    for line in text.splitlines():
        match = FENCE.match(line)
        if marker:
            if (match and match.group(1)[0] == marker[0]
                    and len(match.group(1)) >= len(marker)):
                marker = None
            continue
        if match:
            marker = match.group(1)
            continue
        lines.append(line)
    return "\n".join(lines)


def _without_code(text):
    """Strip fenced and inline-code examples before finding supported links."""
    return INLINE_CODE.sub("", _without_fences(text))


def _slug(value):
    value = re.sub(r"[\t\n ]+", "-", value.strip().lower())
    return "".join(char for char in value if char.isalnum() or char in "-_")


def _headings(path):
    seen = {}
    anchors = set()
    try:
        text = _without_fences(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return anchors
    for line in text.splitlines():
        match = HEADING.match(line)
        if not match:
            continue
        anchor = _slug(match.group(1))
        if not anchor:
            continue
        count = seen.get(anchor, 0)
        seen[anchor] = count + 1
        anchors.add(anchor if count == 0 else "%s-%d" % (anchor, count))
    return anchors


def _local_target(source, raw, root):
    """Return a supported local target, or None for deliberate exclusions."""
    target = unquote(raw)
    if (not target or target.startswith(("http:", "https:", "mailto:", "//", "/"))
            or ":" in target.split("#", 1)[0] or "{" in target or "}" in target
            or "<" in target or ">" in target):
        return None
    filename, separator, fragment = target.partition("#")
    path = source if not filename else (source.parent / filename)
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved, fragment if separator else None


def check_documents(root):
    """Return broken supported local Markdown references in maintained docs."""
    root = Path(root).resolve()
    problems = []
    for source in _tracked_markdown(root):
        try:
            source.resolve().relative_to(root)
            text = _without_code(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        for match in LINK.finditer(text):
            raw = match.group(1)
            target = _local_target(source, raw, root)
            if target is None:
                continue
            path, fragment = target
            relative_source = source.relative_to(root)
            if not path.is_file():
                problems.append(Problem(relative_source, raw, "missing local target"))
            elif fragment and fragment not in _headings(path):
                problems.append(Problem(relative_source, raw, "missing heading"))
    return problems


def main(argv=None):
    root = Path(argv[0]).resolve() if argv else Path(__file__).resolve().parents[1]
    problems = check_documents(root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print("OK: checked tracked Markdown in README.md, docs/, rules/, and skills/; "
              "excluded code examples, placeholders, external/absolute/out-of-root links, "
              "and unsupported Markdown link forms.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
