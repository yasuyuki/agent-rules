#!/usr/bin/env python3
"""A small, deliberately conservative Rulesync 16.39.1 adapter.

The adapter treats Rulesync as a compiler: it is run in a throw-away directory
and only its rules/skills output is reconciled into the configured tree.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

VERSION = "16.39.1"
MANIFEST = ".rulesync-ownership.json"
JOURNAL = ".rulesync-transaction.json"
AGY_SKILLS = ".gemini/config/skills/"
AGY_LEGACY_SKILLS = ".gemini/antigravity-cli/skills/"
LOCK = ".rulesync-transaction.lock"
TARGETS = {"codexcli", "claudecode", "grokcli", "opencode", "cursor", "antigravity-cli"}
FEATURES = {"rules", "skills"}


class BackendError(RuntimeError):
    pass


@contextmanager
def _output_lock(output: Path):
    _assert_plain_output(output)
    output.mkdir(parents=True, exist_ok=True)
    lock_path = output / LOCK
    if _is_link_or_reparse(lock_path):
        raise BackendError(f"symlink or junction is not allowed: {lock_path}")
    if lock_path.exists() and not lock_path.is_file():
        raise BackendError(f"lock path is not a regular file: {lock_path}")
    handle = open(lock_path, "a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        acquired = True
        yield
    finally:
        try:
            if acquired and os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif acquired:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _abs(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def _contains_link(path: Path) -> bool:
    path = path.absolute()
    parts = path.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        try:
            if _is_link_or_reparse(current):
                return True
        except OSError as exc:
            raise BackendError(f"cannot inspect {current}: {exc}") from exc
    return False


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _walk_plain(root: Path) -> list[Path]:
    if _contains_link(root) or _is_link_or_reparse(root):
        raise BackendError(f"symlink or junction is not allowed: {root}")
    if not root.is_dir():
        raise BackendError(f"input root is not a directory: {root}")
    result = []
    for parent, dirs, files in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        for name in dirs + files:
            candidate = parent_path / name
            if _is_link_or_reparse(candidate):
                raise BackendError(f"symlink or junction is not allowed: {candidate}")
            mode = candidate.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise BackendError(f"special file is not allowed: {candidate}")
            result.append(candidate)
    return result


def _load_config(config_path: str | Path) -> dict:
    config_file = Path(config_path).absolute()
    try:
        raw = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackendError(f"cannot read config {config_file}: {exc}") from exc
    required = {"version", "input_roots", "targets", "output_root", "global", "features"}
    if not isinstance(raw, dict) or set(raw) != required or type(raw.get("version")) is not int or raw["version"] != 1:
        raise BackendError("config must contain exactly version 1 and the required fields")
    if not isinstance(raw["input_roots"], list) or not raw["input_roots"] or not all(isinstance(x, str) for x in raw["input_roots"]):
        raise BackendError("input_roots must be a non-empty array of paths")
    if not isinstance(raw["targets"], list) or not raw["targets"] or not all(isinstance(x, str) for x in raw["targets"]) or set(raw["targets"]) - TARGETS:
        raise BackendError("targets must be a non-empty subset of codexcli, claudecode, grokcli, opencode, cursor, antigravity-cli")
    if not isinstance(raw["features"], list) or not raw["features"] or not all(isinstance(x, str) for x in raw["features"]) or set(raw["features"]) - FEATURES:
        raise BackendError("features must be a non-empty subset of rules, skills")
    if not isinstance(raw["output_root"], str) or not isinstance(raw["global"], bool):
        raise BackendError("output_root must be a path and global must be boolean")
    base = config_file.parent
    roots = [Path(os.path.normcase(os.path.abspath(_abs(item, base)))) for item in raw["input_roots"]]
    if len(set(roots)) != len(roots):
        raise BackendError("input_roots must be distinct")
    output = Path(os.path.normcase(os.path.abspath(_abs(raw["output_root"], base))))
    for root in roots:
        try:
            output.relative_to(root)
        except ValueError:
            pass
        else:
            raise BackendError("input root cannot contain output_root")
    for root in roots:
        # Only Rulesync feature trees are source; unrelated repository files
        # (including .git internals) must not affect this adapter.
        if not root.is_dir():
            raise BackendError(f"input root is not a directory: {root}")
        if _contains_link(root):
            raise BackendError(f"symlink or junction is not allowed: {root}")
        for feature in FEATURES:
            candidate = root / feature
            if candidate.exists():
                _walk_plain(candidate)
    _reject_duplicate_sources(roots)
    raw["_file"] = config_file
    raw["_roots"] = roots
    raw["_output"] = output
    return raw


def _reject_duplicate_sources(roots: list[Path]) -> None:
    rules: set[str] = set()
    skills: set[str] = set()
    for root in roots:
        rule_dir, skill_dir = root / "rules", root / "skills"
        if rule_dir.is_dir():
            for item in rule_dir.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(rule_dir).as_posix()
                    if rel in rules:
                        raise BackendError(f"duplicate rule source relative name: {rel}")
                    rules.add(rel)
        if skill_dir.is_dir():
            for item in skill_dir.iterdir():
                if item.is_dir():
                    name = item.name
                    if name in skills:
                        raise BackendError(f"duplicate skill id: {name}")
                    skills.add(name)


def _resolve_executable(config: dict, explicit: str | None) -> str:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    elif os.environ.get("RULESYNC_EXECUTABLE"):
        candidates.append(os.environ["RULESYNC_EXECUTABLE"])
    if not candidates:
        name = "rulesync.cmd" if os.name == "nt" else "rulesync"
        for base in (config["_file"].parent, Path.cwd()):
            candidates.append(str(base / "node_modules" / ".bin" / name))
        found = shutil.which("rulesync")
        if found:
            candidates.append(found)
    for candidate in candidates:
        executable = Path(candidate)
        if executable.is_file() and (os.name == "nt" or os.access(executable, os.X_OK)):
            entry = _npm_entry(executable)
            if entry is not None:
                _check_npm_version(entry)
                return str(executable)
            command = _tool_command(str(executable), ["--version"])
            try:
                version = subprocess.run(command, text=True, capture_output=True, check=False)
            except OSError as exc:
                raise BackendError(f"cannot run {executable} --version: {exc}") from exc
            if version.returncode:
                raise BackendError(f"{executable} --version exited {version.returncode}: {version.stderr.strip()}")
            if version.stdout.strip() != VERSION:
                raise BackendError(f"rulesync must be exactly {VERSION}, not {version.stdout.strip()!r}: {executable}")
            return str(executable)
    raise BackendError("Rulesync executable not found; pass --rulesync or install the pinned local dependency")


NPM_ENTRY = ("rulesync", "dist", "cli", "index.js")
# The exact launch line npm's cmd-shim writes into node_modules/.bin/rulesync.cmd.
NPM_CMD_LAUNCH = '"%_prog%"  "%dp0%\\..\\rulesync\\dist\\cli\\index.js" %*'


def _npm_entry(executable: Path) -> Path | None:
    """Return the npm package entry `_tool_command` runs for this executable.

    Only a `.cmd` shim npm wrote (Windows) or a `.bin` symlink into the sibling
    package (POSIX) qualifies. A link out of the package, another launcher or a
    native executable returns None, so its own `--version` answers instead.
    """
    modules = executable.parent.parent
    entry = modules.joinpath(*NPM_ENTRY)
    if os.name == "nt" and executable.suffix.lower() == ".cmd":
        if not entry.is_file():
            raise BackendError("select an npm-installed Rulesync shim or a native executable")
        if not executable.read_text(encoding="utf-8", errors="replace").rstrip().endswith(" & " + NPM_CMD_LAUNCH):
            raise BackendError(f"Rulesync shim does not launch its sibling package entry: {executable}")
    elif not (executable.parent.name == ".bin" and executable.is_symlink()
              and Path(os.path.realpath(executable)) == Path(os.path.realpath(entry))):
        return None
    if Path(os.path.realpath(entry)) != Path(os.path.realpath(modules)).joinpath(*NPM_ENTRY):
        return None
    return entry


def _check_npm_version(entry: Path) -> None:
    """Read the version `rulesync --version` prints from the entry it runs.

    Rulesync 16.39.1 prints `getVersion()`, a single string constant in that
    entry. A launch would only load the same file to print it.
    """
    package = entry.parents[2] / "package.json"
    try:
        text = entry.read_bytes().decode("utf-8")
        manifest = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackendError(f"cannot read the Rulesync package version: {exc}") from exc
    lines = text.split("\n")
    constants = [re.fullmatch(r'const getVersion = \(\) => "([^"\\]*)";', line) for line in lines if line.startswith("const getVersion ")]
    if (lines[0] != "#!/usr/bin/env node" or len(constants) != 1 or constants[0] is None
            or '\tconst version = getVersion();\n\tprogram.name("rulesync")' not in text
            or '.version(version, "-v, --version", "Show version")' not in text
            or not isinstance(manifest, dict) or manifest.get("name") != "rulesync"):
        raise BackendError(f"cannot confirm the Rulesync version in {entry}")
    found = (constants[0][1], manifest.get("version"))
    if found != (VERSION, VERSION):
        raise BackendError(f"rulesync must be exactly {VERSION}, not {found!r}: {entry}")


def _tool_command(executable: str, args: list[str]) -> list[str]:
    if os.name == "nt" and executable.lower().endswith(".cmd"):
        # Run the pinned npm entry with Node directly, avoiding cmd.exe's
        # reinterpretation of source paths containing shell metacharacters.
        script = Path(executable).parent.parent.joinpath(*NPM_ENTRY)
        if not script.is_file():
            raise BackendError("select an npm-installed Rulesync shim or a native executable")
        return [shutil.which("node") or "node", str(script), *args]
    return [executable, *args]


# The (files, directory prefixes) each target may emit, by global mode.
NAMESPACES = {
    False: {
        "cursor": ((), (".cursor/skills/", ".cursor/rules/")),
        "antigravity-cli": (("AGENTS.md",), (".agents/skills/",)),
        "codexcli": (("AGENTS.md",), (".agents/skills/",)),
        "claudecode": (("CLAUDE.md",), (".claude/rules/", ".claude/skills/")),
        "grokcli": (("AGENTS.md",), (".grok/rules/", ".grok/skills/")),
        "opencode": (("AGENTS.md",), (".opencode/skills/",)),
    },
    True: {
        "cursor": ((), (".cursor/skills/",)),
        # GEMINI.md and the pre-1.3 skill root stay listed only so earlier
        # manifests can retire them.
        "antigravity-cli": ((".gemini/GEMINI.md",), (".gemini/config/rules/", AGY_SKILLS, AGY_LEGACY_SKILLS)),
        "codexcli": ((".codex/AGENTS.md",), (".agents/skills/",)),
        "claudecode": ((".claude/CLAUDE.md",), (".claude/rules/", ".claude/skills/")),
        "grokcli": ((".grok/AGENTS.md",), (".grok/rules/", ".grok/skills/")),
        "opencode": ((".config/opencode/AGENTS.md",), (".config/opencode/skills/",)),
    },
}


def _allowed(target: str, rel: str, global_mode: bool = False) -> bool:
    files, prefixes = NAMESPACES[global_mode][target]
    return rel in files or rel.startswith(prefixes)


def _namespaces_overlap(a: tuple, b: tuple) -> bool:
    (files_a, prefixes_a), (files_b, prefixes_b) = a, b
    return (bool(set(files_a) & set(files_b))
            or any(rel.startswith(prefixes_b) for rel in files_a)
            or any(rel.startswith(prefixes_a) for rel in files_b)
            or any(x.startswith(y) or y.startswith(x) for x in prefixes_a for y in prefixes_b))


def _generation_batches(config: dict) -> list[tuple[list[str], list[str]]]:
    """Group targets into (features, targets) runs of one `rulesync generate`.

    A run holds only targets with the same features whose namespaces are
    disjoint, so every generated path has exactly one possible target. Targets
    sharing a path (project AGENTS.md, .agents/skills/) stay in separate runs
    whose outputs `_combine` compares.
    """
    batches: list[tuple[list[str], list[str]]] = []
    namespaces = NAMESPACES[config["global"]]
    for target in config["targets"]:
        features = list(config["features"])
        if target == "antigravity-cli" and config["global"]:
            # `_antigravity_global_rules` places these rules instead.
            features = [feature for feature in features if feature != "rules"]
            if not features:
                continue
        for batch_features, members in batches:
            if batch_features == features and not any(_namespaces_overlap(namespaces[target], namespaces[m]) for m in members):
                members.append(target)
                break
        else:
            batches.append((features, [target]))
    return batches


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _output_mode(mode: int) -> int:
    """Carry read and execute bits; drop group and other write.

    Those write bits come from the umask of whoever made the source checkout or
    ran generation, not from the declaration, so carrying them made identical
    sources check differently. The kept bits are those Rulesync 16.39.1 carries
    for executable files. Windows modes only reflect the read-only attribute.
    """
    return stat.S_IMODE(mode) & (0o777 if os.name == "nt" else 0o755)


def _combine(combined: dict[str, tuple[bytes, int]], rel: str, value: tuple[bytes, int]) -> None:
    old = combined.get(rel)
    if old is not None and old != value:
        raise BackendError(f"shared-output conflict for {rel}")
    combined[rel] = value


def _rule_targets(text: str) -> list[str]:
    """Read `targets` from Rulesync rule frontmatter; absent means every target."""
    if not text.startswith("---\n") or "\n---\n" not in text:
        return ["*"]
    header = text[4:text.index("\n---\n")].split("\n")
    for index, line in enumerate(header):
        if not line.startswith("targets:"):
            continue
        value = line[len("targets:"):].strip()
        if value.startswith("[") and value.endswith("]"):
            return [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
        if value:
            return [value.strip("\"'")]
        items = []
        for item in header[index + 1:]:
            if not item.lstrip().startswith("- "):
                break
            items.append(item.lstrip()[2:].strip().strip("\"'"))
        return items
    return ["*"]


def _antigravity_global_rules(config: dict) -> dict[str, tuple[bytes, int]]:
    """Place agy user rules as separate always-on files.

    agy keeps only the first 24,000 bytes of ~/.gemini/GEMINI.md, the single
    global rule file Rulesync 16.39.1 writes, but loads each always-on file in
    ~/.gemini/config/rules/ separately.
    """
    placed: dict[str, tuple[bytes, int]] = {}
    for root in config["_roots"]:
        rules = root / "rules"
        if not rules.is_dir():
            continue
        for source in sorted(rules.glob("*.md")):
            text = source.read_text(encoding="utf-8").replace("\r\n", "\n")
            targets = _rule_targets(text)
            if "antigravity-cli" not in targets and "*" not in targets:
                continue
            body = text.split("\n---\n", 1)[1] if text.startswith("---\n") and "\n---\n" in text else text
            rel = ".gemini/config/rules/" + source.name
            if rel in placed:
                raise BackendError(f"duplicate agy global rule name: {source.name}")
            data = ("---\ntrigger: always_on\n---\n" + body.lstrip("\n")).encode("utf-8")
            placed[rel] = (data, _output_mode(source.stat().st_mode))
    return placed


def _skill_frontmatter(config: dict, target: str, executable: str, files: dict[str, tuple[bytes, int]]) -> None:
    roots = {
        "codexcli": ".agents/skills/", "claudecode": ".claude/skills/",
        "grokcli": ".grok/skills/", "cursor": ".cursor/skills/",
        "opencode": ".config/opencode/skills/" if config["global"] else ".opencode/skills/",
        "antigravity-cli": AGY_SKILLS if config["global"] else ".agents/skills/",
    }
    sources = []
    for root in config["_roots"]:
        directory = root / "skills"
        if directory.is_dir():
            for item in sorted(directory.iterdir()):
                source = item / "SKILL.md"
                if item.is_dir() and source.is_file():
                    sources.append({"id": item.name, "sourceBase64": base64.b64encode(source.read_bytes()).decode("ascii")})
    paths = {}
    for rel in files:
        if rel.startswith(roots[target]):
            parts = rel[len(roots[target]):].split("/")
            if len(parts) == 2 and parts[1] == "SKILL.md":
                paths[parts[0]] = rel
    if not sources and not paths:
        return
    request = {"target": target, "sources": sources, "generated": [
        {"id": name, "generatedBase64": base64.b64encode(files[rel][0]).decode("ascii")}
        for name, rel in paths.items()
    ]}
    try:
        run = subprocess.run([shutil.which("node") or "node", str(Path(__file__).with_name("skill_frontmatter.cjs")), executable],
                             input=json.dumps(request), text=True, capture_output=True, encoding="utf-8", check=False)
    except OSError as exc:
        raise BackendError(f"cannot inspect skill frontmatter for {target}: {exc}") from exc
    if run.returncode:
        raise BackendError(f"cannot preserve skill frontmatter for {target}: {run.stderr.strip()}")
    try:
        generated = json.loads(run.stdout)["generated"]
        if {entry["id"] for entry in generated} != set(paths) or len(generated) != len(paths):
            raise ValueError("unexpected skill identities")
        for entry in generated:
            rel = paths[entry["id"]]
            files[rel] = (base64.b64decode(entry["generatedBase64"], validate=True), files[rel][1])
    except (ValueError, KeyError, TypeError) as exc:
        raise BackendError(f"invalid skill frontmatter response for {target}: {exc}") from exc


def _git_checkout(root: Path) -> tuple[Path, str] | None:
    """Find the checkout whose `.git` is nearest to root, as Git discovery does."""
    real = Path(os.path.realpath(root))
    for top in (real, *real.parents):
        marker = top / ".git"
        if marker.exists() or _is_link_or_reparse(marker):
            return top, "" if real == top else real.relative_to(top).as_posix()
    return None


def _git(top: Path, *args: str) -> bytes:
    # Inherited GIT_* variables could point discovery at another repository.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    command = [shutil.which("git") or "git", "--no-optional-locks", "--literal-pathspecs", "-C", str(top), *args]
    try:
        run = subprocess.run(command, env=env, capture_output=True, check=False)
    except OSError as exc:
        raise BackendError(f"cannot run git for Git-managed input root {top}: {exc}") from exc
    if run.returncode:
        raise BackendError(f"git {args[0]} failed for Git-managed input root {top}: {run.stderr.decode('utf-8', 'replace').strip()}")
    return run.stdout


def _status_changes(output: bytes) -> tuple[str | None, list[str]]:
    """Parse `git status --porcelain=v2 -z --branch` into HEAD and uncommitted paths."""
    head, changes = None, []
    records = iter(output.decode("utf-8", "surrogateescape").split("\0"))
    for record in records:
        if record.startswith("# branch.oid "):
            oid = record[len("# branch.oid "):]
            head = None if oid == "(initial)" else oid
        elif record[:2] in ("1 ", "2 ", "u "):
            fields = record.split(" ", {"1": 8, "2": 9, "u": 10}[record[0]])
            index, worktree = fields[1]
            kinds = ["unmerged"] if record[0] == "u" else []
            kinds += ["staged"] if record[0] != "u" and index != "." else []
            kinds += ["unstaged"] if record[0] != "u" and worktree != "." else []
            kinds += ["deleted"] if "D" in fields[1] and record[0] != "u" else []
            if record[0] == "2":
                kinds.append(f"renamed from {next(records)}")
            changes.append(f"{'+'.join(kinds)} {fields[-1]}")
        elif record[:2] in ("? ", "! "):
            changes.append(f"{'untracked' if record[0] == '?' else 'ignored'} {record[2:]}")
        elif record and not record.startswith("# "):
            raise BackendError(f"unrecognized git status record: {record!r}")
    return head, changes


def _committed_roots(config: dict, temp: Path) -> list[Path]:
    """Return generation roots, replacing each Git-managed root by its HEAD content.

    A Git-managed root with uncommitted, untracked or ignored feature files is
    refused. Generating from the commit read with that same status, not from the
    working tree, keeps concurrent edits out of the distributed bytes.
    """
    roots = list(config["_roots"])
    checkouts: dict[Path, list[tuple[int, str]]] = {}
    for index, root in enumerate(roots):
        found = _git_checkout(root)
        if found:
            checkouts.setdefault(found[0], []).append((index, found[1]))
    for number, (top, members) in enumerate(checkouts.items()):
        pathspecs = [f"{prefix}/{feature}".lstrip("/") for _, prefix in members for feature in config["features"]]
        head, changes = _status_changes(_git(top, "status", "--porcelain=v2", "-z", "--branch", "--untracked-files=all", "--ignored=matching", "--ignore-submodules=none", "--", *pathspecs))
        if changes:
            raise BackendError(f"Git-managed input root has uncommitted source changes in {top}: {'; '.join(changes)}; commit and integrate them through the task topic, then rerun")
        if head is None:
            raise BackendError(f"Git-managed input root has no commit: {top}")
        snapshot = temp / "sources" / str(number)
        # Read from the commit: a skip-worktree deletion is invisible to status.
        tracked = _git(top, "ls-tree", "-r", "-z", "--name-only", head, "--", *pathspecs).decode("utf-8", "surrogateescape").split("\0")
        present = [spec for spec in pathspecs if any(name.startswith(spec + "/") for name in tracked)]
        snapshot.mkdir(parents=True)
        if present:
            with tarfile.open(fileobj=io.BytesIO(_git(top, "archive", "--format=tar", head, "--", *present))) as archive:
                entries = archive.getmembers()
                for entry in entries:
                    if not (entry.isfile() or entry.isdir()):
                        raise BackendError(f"Git-managed input root has a non-file source in {head}: {entry.name}")
                archive.extractall(snapshot, entries, filter="data")
        for index, prefix in members:
            committed = snapshot / prefix
            committed.mkdir(parents=True, exist_ok=True)
            # A submodule or other content git archive omits must not vanish silently.
            for feature in config["features"]:
                listed = [{item.relative_to(base / feature).as_posix() for item in (_walk_plain(base / feature) if (base / feature).is_dir() else []) if item.is_file()} for base in (roots[index], committed)]
                if listed[0] != listed[1]:
                    path = sorted(listed[0] ^ listed[1])[0]
                    raise BackendError(f"Git-managed input root differs from commit {head}: {feature}/{path}; commit and integrate the source change through the task topic, then rerun")
            roots[index] = committed
    return roots


def _generate(config: dict, executable: str) -> dict[str, tuple[bytes, int]]:
    combined: dict[str, tuple[bytes, int]] = {}
    with tempfile.TemporaryDirectory(prefix="rulesync-backend-") as temp:
        temp_root = Path(temp)
        config = {**config, "_roots": _committed_roots(config, temp_root)}
        if "antigravity-cli" in config["targets"] and config["global"] and "rules" in config["features"]:
            for rel, value in _antigravity_global_rules(config).items():
                _combine(combined, rel, value)
        for number, (features, members) in enumerate(_generation_batches(config)):
            label = ",".join(members)
            stage = temp_root / str(number) / "out"
            home = temp_root / str(number) / "home"
            stage.mkdir(parents=True)
            home.mkdir()
            cmd = ["generate", "--targets", label, "--features", ",".join(features), "--input-roots", *map(str, config["_roots"]), "--output-roots", str(stage), "--silent"]
            if config["global"]:
                cmd.append("--global")
            # Preserve only process essentials; redirect every known tool home so
            # native generation cannot discover or modify live configuration.
            env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "COMSPEC", "HOMEDRIVE", "HOMEPATH", "TEMP", "TMP") if key in os.environ}
            env.update({"HOME": str(home), "USERPROFILE": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"), "CODEX_HOME": str(home / ".codex"), "CLAUDE_CONFIG_DIR": str(home / ".claude"), "GROK_CONFIG_DIR": str(home / ".grok"), "OPENCODE_CONFIG_DIR": str(home / ".config" / "opencode")})
            try:
                run = subprocess.run(_tool_command(executable, cmd), cwd=temp_root, env=env, text=True, capture_output=True, check=False)
            except OSError as exc:
                raise BackendError(f"cannot run Rulesync for {label}: {exc}") from exc
            if run.returncode:
                raise BackendError(f"Rulesync generation failed for {label} (exit {run.returncode}): {(run.stderr or run.stdout).strip()}")
            # In global mode Rulesync deliberately writes below HOME and ignores
            # output-roots.  HOME is our staging root, so reconcile that tree.
            generated_root = home if config["global"] else stage
            per_target: dict[str, dict[str, tuple[bytes, int]]] = {target: {} for target in members}
            for item in _walk_plain(generated_root):
                if not item.is_file():
                    continue
                rel = item.relative_to(generated_root).as_posix()
                owners = [target for target in members if _allowed(target, rel, config["global"])]
                if not owners:
                    raise BackendError(f"Rulesync emitted unsupported path for {label}: {rel}")
                if len(owners) > 1:
                    raise BackendError(f"one Rulesync run cannot attribute {rel} among {label}")
                target = owners[0]
                if target == "antigravity-cli" and rel.startswith(AGY_LEGACY_SKILLS):
                    # Rulesync 16.39.1 still writes the pre-1.3 root, which agy
                    # 1.3 moves once to ~/.gemini/config/skills/ and no longer reads.
                    rel = AGY_SKILLS + rel[len(AGY_LEGACY_SKILLS):]
                value = (item.read_bytes(), _output_mode(item.stat().st_mode))
                _combine(per_target[target], rel, value)
            for target, target_files in per_target.items():
                if "skills" in features:
                    _skill_frontmatter(config, target, executable, target_files)
                for rel, value in target_files.items():
                    _combine(combined, rel, value)
    if "grokcli" in config["targets"] and not config["global"] and "CLAUDE.md" in combined:
        raise BackendError("Grok also discovers CLAUDE.md; use non-root Claude rules to avoid duplicate policy")
    return combined


class _Ownership(dict):
    """File ownership plus skill directory identities retained after file removal.

    Retirement adds an optional v1 manifest field. Older adapters deliberately
    reject that field, so consumers must upgrade the single existing writer;
    do not run old/new adapters as competing ownership writers.
    """
    def __init__(self, files=(), skill_directories=None):
        super().__init__(files)
        self.skill_directories = skill_directories or []


def _directory_identity(path: Path) -> dict:
    if _contains_link(path) or _is_link_or_reparse(path) or not path.is_dir():
        raise BackendError(f"owned skill directory is not plain: {path}")
    info = path.stat()
    if info.st_ino <= 0 or info.st_dev < 0:
        raise BackendError(f"owned skill directory identity is unavailable: {path}")
    return {"path": None, "device": info.st_dev, "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode) & 0o777}


def _validate_skill_directory_tree(output: Path, record: dict, allowed_files=()) -> None:
    expected = {entry["path"]: entry for entry in record["directories"]}
    root = output / record["path"]
    for rel, entry in expected.items():
        identity = _directory_identity(output / rel)
        identity["path"] = rel
        if identity != entry:
            raise BackendError(f"owned skill directory identity changed: {rel}")
    actual = {record["path"]}
    for path in _walk_plain(root):
        rel = path.relative_to(output).as_posix()
        if path.is_dir():
            actual.add(rel)
        elif rel not in allowed_files:
            raise BackendError(f"unowned contents in owned skill: {rel}")
    if actual != set(expected):
        raise BackendError(f"unowned directory in owned skill: {record['path']}")


def _retired_skill_absence(output: Path, record: dict) -> dict | None:
    root = output / record["path"]
    proof = {}
    try:
        try:
            root.lstat()
        except FileNotFoundError:
            proof[root] = None
        else:
            return None
        for entry in record["directories"]:
            path = output / entry["path"]
            try:
                path.lstat()
            except FileNotFoundError:
                proof[path] = None
            else:
                raise BackendError(f"retired skill directory is not absent: {path}")
        device = next(entry["device"] for entry in record["directories"]
                      if entry["path"] == record["path"])
        mountpoints = set()
        if sys.platform.startswith("linux"):
            lines = Path("/proc/self/mountinfo").read_text().splitlines()
            if not lines:
                raise BackendError("invalid Linux mount information")
            for line in lines:
                fields = line.split()
                if len(fields) < 10 or "-" not in fields:
                    raise BackendError("invalid Linux mount information")
                separator = fields.index("-")
                if separator < 6 or len(fields) != separator + 4 or not fields[0].isdigit() or not fields[1].isdigit() or not fields[4].startswith("/"):
                    raise BackendError("invalid Linux mount information")
                mountpoint = fields[4]
                for escaped, character in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
                    mountpoint = mountpoint.replace(escaped, character)
                mountpoints.add(Path(mountpoint))
        for path in root.parents:
            try:
                info = path.lstat()
            except FileNotFoundError:
                proof[path] = None
                continue
            if not stat.S_ISDIR(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
                raise BackendError(f"retired skill ancestor is not plain: {path}")
            if output in path.parents and (path in mountpoints or os.path.ismount(path)):
                raise BackendError(f"retired skill ancestor is mounted: {path}")
            if info.st_ino <= 0 or info.st_dev < 0 or ((path == output or output in path.parents) and info.st_dev != device):
                raise BackendError(f"retired skill ancestor identity changed: {path}")
            proof[path] = (info.st_dev, info.st_ino, info.st_mode)
    except OSError as exc:
        raise BackendError(f"cannot inspect retired skill directory: {exc}") from exc
    return proof


def _skill_directory_state(output: Path, desired: dict, owned: dict, retired: list | None = None) -> list[dict]:
    previous = {record["path"]: record for record in getattr(owned, "skill_directories", [])}
    stale = set(owned) - set(desired)
    affected = {root for root in _skill_roots(owned)
                if any(rel.startswith(root + "/") for rel in stale)}
    records = []
    for root in sorted(set(previous) | affected):
        files = {rel for rel in owned if rel.startswith(root + "/")}
        if retired is not None and root in previous and not files and not any(rel.startswith(root + "/") for rel in desired):
            proof = _retired_skill_absence(output, previous[root])
            if proof is not None:
                retired.append((previous[root], proof))
                continue
        known = {entry["path"]: entry for entry in previous.get(root, {}).get("directories", [])}
        directories = {root}
        for rel in files:
            parent = Path(rel).parent
            while parent.as_posix() != root:
                directories.add(parent.as_posix())
                parent = parent.parent
        for rel in directories - set(known):
            entry = _directory_identity(output / rel)
            entry["path"] = rel
            known[rel] = entry
        record = {"path": root, "directories": [known[rel] for rel in sorted(known)]}
        _validate_skill_directory_tree(output, record, files)
        records.append(record if root in affected else previous[root])
    return records


def _read_manifest(output: Path, config: dict) -> dict[str, dict] | None:
    manifest = output / MANIFEST
    if not manifest.exists():
        return None
    if _is_link_or_reparse(manifest):
        raise BackendError(f"symlink or junction is not allowed: {manifest}")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1 or set(value) not in ({"version", "files"}, {"version", "files", "skill_directories"}) or not isinstance(value.get("files"), list):
            raise ValueError("invalid format")
        files = {}
        for entry in value["files"]:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "mode"}:
                raise ValueError("invalid file entry")
            rel, digest, mode = entry["path"], entry["sha256"], entry["mode"]
            pure = Path(rel) if isinstance(rel, str) else Path("")
            if (not isinstance(rel, str) or not rel or rel != pure.as_posix() or ":" in rel or "\\" in rel or pure.is_absolute() or pure.drive or any(part in ("", ".", "..") for part in pure.parts) or rel == MANIFEST or rel in files or not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest) or not isinstance(mode, int) or isinstance(mode, bool) or mode < 0 or mode > 0o777 or not _owned_output(rel, config)):
                raise ValueError("invalid file entry")
            files[rel] = {"sha256": digest, "mode": mode}
        directory_records = value.get("skill_directories", [])
        if not isinstance(directory_records, list):
            raise ValueError("invalid skill directories")
        roots = set()
        for record in directory_records:
            if not isinstance(record, dict) or set(record) != {"path", "directories"} or not isinstance(record["directories"], list):
                raise ValueError("invalid skill directory")
            root = _plain_relative(record["path"], config, owned=True)
            parts = Path(root).parts
            if "skills" not in parts[:-1] or root in roots:
                raise ValueError("invalid skill directory root")
            roots.add(root)
            seen = set()
            for entry in record["directories"]:
                if not isinstance(entry, dict) or set(entry) != {"path", "device", "inode", "mode"}:
                    raise ValueError("invalid owned skill directory")
                rel = _plain_relative(entry["path"], config, owned=True)
                if rel in seen or not (rel == root or rel.startswith(root + "/")) or any(type(entry[key]) is not int for key in ("device", "inode", "mode")) or entry["device"] < 0 or entry["inode"] <= 0 or not 0 <= entry["mode"] <= 0o777:
                    raise ValueError("invalid owned skill directory")
                seen.add(rel)
            if root not in seen or any(Path(rel).parent.as_posix() not in seen for rel in seen if rel != root):
                raise ValueError("invalid owned skill directory ancestry")
        if any(root.startswith(other + "/") for root in roots for other in roots if root != other):
            raise ValueError("overlapping skill directory roots")
        return _Ownership(files, directory_records)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise BackendError(f"invalid ownership manifest {manifest}: {exc}") from exc


def _assert_plain_output(output: Path) -> None:
    if _contains_link(output):
        raise BackendError(f"symlink or junction is not allowed: {output}")


def _actual(path: Path) -> tuple[str, int]:
    if _is_link_or_reparse(path) or not path.is_file():
        raise BackendError(f"owned path is not a regular file: {path}")
    return _digest(path.read_bytes()), stat.S_IMODE(path.stat().st_mode) & 0o777


def _skill_roots(files: dict[str, tuple[bytes, int]]) -> set[str]:
    return {Path(rel).parent.as_posix() for rel in files
            if Path(rel).name == "SKILL.md" and "skills" in Path(rel).parts[:-1]}


def _validate_reconcile(output: Path, desired: dict[str, tuple[bytes, int]], owned: dict[str, dict] | None, config: dict, allow_grok_stale_claude: bool = False, allow_absent_retired: bool = False) -> dict[str, dict]:
    _assert_plain_output(output)
    owned = owned if owned is not None else _Ownership()
    if "grokcli" in config["targets"] and not config["global"] and "AGENTS.md" in desired and (output / "CLAUDE.md").exists():
        if not (allow_grok_stale_claude and "CLAUDE.md" in owned and "CLAUDE.md" not in desired):
            raise BackendError("Grok discovers existing CLAUDE.md; refusing to change AGENTS.md")
    # Before any mutation, prove every previously-owned file was not edited.
    for rel, meta in owned.items():
        path = output / rel
        if _contains_link(path):
            raise BackendError(f"symlink or junction is not allowed: {path}")
        if not path.exists() or _actual(path) != (meta["sha256"], meta["mode"]):
            raise BackendError(f"externally modified owned file: {rel}")
    for rel in desired:
        path = output / rel
        if _contains_link(path):
            raise BackendError(f"symlink or junction is not allowed: {path}")
        if path.exists() and rel not in owned:
            raise BackendError(f"unowned file would be replaced: {rel}")
    recorded_roots = {record["path"] for record in getattr(owned, "skill_directories", [])}
    _skill_directory_state(output, desired, owned, [] if allow_absent_retired else None)
    for skill in _skill_roots(desired) | _skill_roots({rel: (b"", 0) for rel in owned}):
        directory = output / skill
        if directory.exists():
            matching_owned = any(rel.startswith(skill + "/") for rel in owned)
            if not matching_owned and skill not in recorded_roots:
                raise BackendError(f"unowned same-name skill: {skill}")
            for item in _walk_plain(directory):
                if item.is_file() and item.relative_to(output).as_posix() not in owned:
                    raise BackendError(f"unowned same-name skill: {skill}")
    return owned


def _protect_sources(config: dict, desired: dict[str, tuple[bytes, int]]) -> None:
    for rel in desired:
        target = config["_output"] / rel
        for root in config["_roots"]:
            for feature in config["features"]:
                source = root / feature
                try:
                    target.relative_to(source)
                except ValueError:
                    try:
                        source.relative_to(target)
                    except ValueError:
                        pass
                    else:
                        raise BackendError(f"generated output overlaps source tree: {rel}")
                else:
                    raise BackendError(f"generated output overlaps source tree: {rel}")


def _manifest_bytes(desired: dict[str, tuple[bytes, int]], skill_directories: list[dict] | None = None) -> bytes:
    files = [{"path": rel, "sha256": _digest(data), "mode": mode} for rel, (data, mode) in sorted(desired.items())]
    value = {"version": 1, "files": files}
    if skill_directories:
        value["skill_directories"] = skill_directories
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _journal_bytes(backups: dict[Path, tuple[bytes, int] | None], after: dict[Path, tuple[bytes, int] | None], output: Path, directories: list[Path]) -> bytes:
    def encode(value):
        return None if value is None else {"data": base64.b64encode(value[0]).decode("ascii"), "mode": value[1]}
    files = [{"path": path.relative_to(output).as_posix(), "before": encode(backups[path]), "after": encode(after[path])} for path in backups]
    return (json.dumps({"version": 1, "files": files, "directories": [path.relative_to(output).as_posix() for path in directories]}, sort_keys=True) + "\n").encode()


def _recover(output: Path, config: dict, readonly: bool = False) -> None:
    journal = output / JOURNAL
    if not journal.exists():
        return
    if readonly:
        raise BackendError("pending Rulesync transaction")
    if _is_link_or_reparse(journal):
        raise BackendError("invalid Rulesync transaction")
    try:
        value = json.loads(journal.read_text())
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1 or set(value) != {"version", "files", "directories"} or not isinstance(value["files"], list) or not isinstance(value["directories"], list):
            raise ValueError()
        restore = {}
        for entry in value["files"]:
            if not isinstance(entry, dict) or set(entry) != {"path", "before", "after"}:
                raise ValueError()
            rel = entry["path"]
            canonical = Path(rel).as_posix() if isinstance(rel, str) else ""
            allowed = rel == MANIFEST or _owned_output(rel, config)
            if not isinstance(rel, str) or not rel or rel != canonical or "\\" in rel or ":" in rel or Path(rel).is_absolute() or ".." in Path(rel).parts or rel == JOURNAL or not allowed:
                raise ValueError()
            def decode(item):
                if item is None: return None
                if not isinstance(item, dict) or set(item) != {"data", "mode"} or not isinstance(item["data"], str) or not isinstance(item["mode"], int) or isinstance(item["mode"], bool) or item["mode"] < 0 or item["mode"] > 0o777: raise ValueError()
                return (base64.b64decode(item["data"], validate=True), item["mode"])
            before, after = decode(entry["before"]), decode(entry["after"])
            path = output / rel
            if _contains_link(path) or _is_link_or_reparse(path):
                raise BackendError(f"symlink or junction is not allowed: {path}")
            if path.exists() and not path.is_file():
                raise BackendError(f"pending transaction has non-file path: {rel}")
            current = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode) & 0o777) if path.exists() else None
            if current not in (before, after):
                raise BackendError(f"pending transaction conflicts with external edit: {rel}")
            restore[path] = before
        directories = []
        for rel in value["directories"]:
            if not isinstance(rel, str) or not rel or rel != Path(rel).as_posix() or "\\" in rel or ":" in rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise ValueError()
            directory = output / rel
            if _contains_link(directory) or _is_link_or_reparse(directory):
                raise BackendError(f"symlink or junction is not allowed: {directory}")
            if directory == output or not any(directory in path.parents for path in restore):
                raise ValueError()
            directories.append(directory)
        _restore(restore)
        for directory in reversed(directories):
            if directory.exists():
                directory.rmdir()
        journal.unlink()
    except BackendError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise BackendError("invalid Rulesync transaction") from exc


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.rulesync-tmp-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _restore(backups: dict[Path, tuple[bytes, int] | None]) -> None:
    failure = None
    for path, previous in backups.items():
        try:
            if previous is None:
                if path.exists() or _is_link_or_reparse(path):
                    path.unlink()
            elif not path.is_file() or _is_link_or_reparse(path) or _actual(path) != (_digest(previous[0]), previous[1]):
                _write_atomic(path, *previous)
        except BaseException as exc:
            failure = failure or (path, exc)
    if failure:
        path, error = failure
        raise BackendError(f"rollback failed for {path}: {error}") from error


def _plan(output: Path, desired: dict[str, tuple[bytes, int]], owned: dict[str, dict]):
    """Read-only reconcile plan shared by apply and preview."""
    stale = set(owned) - set(desired)
    writes = {rel: value for rel, value in desired.items() if rel not in owned or _actual(output / rel) != (_digest(value[0]), value[1])}
    manifest = output / MANIFEST
    retired = []
    directory_records = _skill_directory_state(output, desired, owned, retired)
    manifest_data = _manifest_bytes(desired, directory_records)
    manifest_needs = not manifest.exists() or manifest.read_bytes() != manifest_data
    return stale, writes, retired, manifest_data, manifest_needs


def _apply_reconcile(output: Path, desired: dict[str, tuple[bytes, int]], owned: dict[str, dict]) -> bool:
    # Preserve old directories and their ACLs; only files and manifest are journaled.
    stale, writes, retired, manifest_data, manifest_needs = _plan(output, desired, owned)
    manifest = output / MANIFEST
    if not stale and not writes and not manifest_needs:
        return False
    touched = [output / rel for rel in stale | set(writes)] + ([manifest] if manifest_needs else [])
    backups = {}
    for path in touched:
        backups[path] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode) & 0o777) if path.exists() else None
    after = {path: (writes[path.relative_to(output).as_posix()] if path.relative_to(output).as_posix() in writes else None) for path in touched}
    if manifest_needs:
        after[manifest] = (manifest_data, 0o666 if os.name == "nt" else 0o600)
    missing_dirs = set()
    for path in [output, *(item.parent for item in touched)]:
        missing = []
        cursor = path
        while not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        missing_dirs.update(missing)
    created_dirs = sorted(missing_dirs, key=lambda p: (len(p.parts), str(p)))
    journal = output / JOURNAL
    _write_atomic(journal, _journal_bytes(backups, after, output, created_dirs), 0o600)
    try:
        for directory in created_dirs:
            directory.mkdir()
        for rel in stale:
            (output / rel).unlink()
        for rel, value in writes.items():
            _write_atomic(output / rel, *value)
        if manifest_needs:
            for record, proof in retired:
                if _retired_skill_absence(output, record) != proof:
                    raise BackendError(f"retired skill directory ancestry changed: {record['path']}")
            _write_atomic(manifest, manifest_data, 0o600)
        journal.unlink()
    except BaseException as exc:
        try:
            _restore(backups)
            for directory in reversed(created_dirs):
                if directory.exists():
                    directory.rmdir()
            if journal.exists():
                journal.unlink()
        except BaseException as rollback:
            raise BackendError(f"apply failed: {exc}; rollback failed: {rollback}") from rollback
        raise exc
    return True


def _owned_output(rel: str, config: dict) -> bool:
    # Recorded ownership may come from a target since removed from the config;
    # it must stay readable so apply can retire it. New output stays per-target.
    return any(_allowed(target, rel, config["global"]) for target in TARGETS)


def _plain_relative(rel: object, config: dict, owned: bool = False) -> str:
    if not isinstance(rel, str) or not rel:
        raise ValueError("invalid file entry")
    pure = Path(rel)
    if (rel != pure.as_posix() or ":" in rel or "\\" in rel or pure.is_absolute() or pure.drive
            or any(part in ("", ".", "..") for part in pure.parts) or rel in (MANIFEST, JOURNAL, LOCK)
            or not (_owned_output(rel, config) if owned else any(_allowed(target, rel, config["global"]) for target in config["targets"]))):
        raise ValueError("invalid file entry")
    return rel


def _load_handover_plan(plan_path: str | Path, config: dict, desired: dict[str, tuple[bytes, int]]) -> tuple[dict[str, dict], Path, bytes]:
    plan_file = Path(plan_path).absolute()
    try:
        raw_bytes = plan_file.read_bytes()
        value = json.loads(raw_bytes)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise BackendError(f"cannot read handover plan {plan_file}: {exc}") from exc
    required = {"version", "output_root", "files", "evidence", "backup_root", "desired_sha256"}
    if not isinstance(value, dict) or set(value) != required or type(value.get("version")) is not int or value["version"] != 1:
        raise BackendError("handover plan must contain exactly version 1 and the required fields")
    output_value = value["output_root"]
    if not isinstance(output_value, str):
        raise BackendError("handover plan output_root must be a path")
    plan_output = Path(os.path.normcase(os.path.abspath(_abs(output_value, plan_file.parent))))
    if plan_output != config["_output"]:
        raise BackendError("handover plan output_root does not match config")
    if not isinstance(value["evidence"], str) or not value["evidence"].strip():
        raise BackendError("handover plan evidence must be non-empty")
    if not isinstance(value["desired_sha256"], str) or value["desired_sha256"] != _digest(_manifest_bytes(desired)):
        raise BackendError("handover plan desired_sha256 does not match generated output")
    backup_value = value["backup_root"]
    if not isinstance(backup_value, str) or not Path(backup_value).is_absolute():
        raise BackendError("handover plan backup_root must be absolute")
    backup = Path(os.path.normcase(os.path.abspath(backup_value)))
    for protected in [config["_output"], *config["_roots"]]:
        try:
            backup.relative_to(protected)
        except ValueError:
            try:
                protected.relative_to(backup)
            except ValueError:
                pass
            else:
                raise BackendError("handover backup_root cannot contain output or source roots")
        else:
            raise BackendError("handover backup_root cannot be inside output or source roots")
    if not isinstance(value["files"], list):
        raise BackendError("handover plan files must be an array")
    files: dict[str, dict] = {}
    try:
        for entry in value["files"]:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "mode"}:
                raise ValueError("invalid file entry")
            rel = _plain_relative(entry["path"], config)
            digest, mode = entry["sha256"], entry["mode"]
            if (rel in files or not isinstance(digest, str) or len(digest) != 64
                    or any(ch not in "0123456789abcdef" for ch in digest)
                    or not isinstance(mode, int) or isinstance(mode, bool) or mode < 0 or mode > 0o777):
                raise ValueError("invalid file entry")
            files[rel] = {"sha256": digest, "mode": mode}
    except ValueError as exc:
        raise BackendError(f"invalid handover plan: {exc}") from exc
    return files, backup, raw_bytes


def _assert_new_plain_backup(backup: Path) -> None:
    if _contains_link(backup):
        raise BackendError(f"symlink or junction is not allowed: {backup}")
    if backup.exists() or _is_link_or_reparse(backup):
        raise BackendError(f"handover backup already exists: {backup}")
    parent = backup.parent
    if not parent.is_dir() or _is_link_or_reparse(parent):
        raise BackendError(f"handover backup parent is not a plain directory: {parent}")


def _write_handover_backup(backup: Path, output: Path, plan_files: dict[str, dict], plan_bytes: bytes, config: dict, desired: dict[str, tuple[bytes, int]]) -> None:
    _assert_new_plain_backup(backup)
    backup.mkdir(mode=0o700)
    before = backup / "before"
    before.mkdir()
    for rel, meta in plan_files.items():
        source = output / rel
        data = source.read_bytes()
        mode = stat.S_IMODE(source.stat().st_mode) & 0o777
        if (_digest(data), mode) != (meta["sha256"], meta["mode"]):
            raise BackendError(f"reviewed handover file changed while backing up: {rel}")
        destination = before / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(destination, data, mode)
    _write_atomic(backup / "plan.json", plan_bytes, 0o600)
    _write_atomic(backup / "config.json", config["_file"].read_bytes(), 0o600)
    _write_atomic(backup / "desired-ownership.json", _manifest_bytes(desired), 0o600)


def handover(config_path: str | Path, plan_path: str | Path, rulesync: str | None = None) -> bool:
    """Transfer explicitly reviewed handwritten outputs to Rulesync exactly once."""
    config = _load_config(config_path)
    executable = _resolve_executable(config, rulesync)
    desired = _generate(config, executable)
    _protect_sources(config, desired)
    plan_files, backup, plan_bytes = _load_handover_plan(plan_path, config, desired)
    output = config["_output"]
    with _output_lock(output):
        plan_files, backup, plan_bytes = _load_handover_plan(plan_path, config, desired)
        manifest, journal = output / MANIFEST, output / JOURNAL
        if _is_link_or_reparse(manifest) or _is_link_or_reparse(journal):
            raise BackendError("symlink or junction is not allowed for Rulesync metadata")
        if manifest.exists():
            raise BackendError("handover requires no existing ownership manifest")
        if journal.exists():
            raise BackendError("handover requires no pending transaction journal")
        _assert_new_plain_backup(backup)
        owned = _validate_reconcile(output, desired, plan_files, config, allow_grok_stale_claude=True)
        _write_handover_backup(backup, output, owned, plan_bytes, config, desired)
        # Preserve edits that race backup creation rather than applying over them.
        owned = _validate_reconcile(output, desired, owned, config, allow_grok_stale_claude=True)
        return _apply_reconcile(output, desired, owned)

def apply(config_path: str | Path, rulesync: str | None = None) -> bool:
    config = _load_config(config_path)
    executable = _resolve_executable(config, rulesync)
    desired = _generate(config, executable)
    _protect_sources(config, desired)
    output = config["_output"]
    with _output_lock(output):
        _recover(output, config)
        owned = _validate_reconcile(output, desired, _read_manifest(output, config), config, allow_absent_retired=True)
        return _apply_reconcile(output, desired, owned)


def check(config_path: str | Path, rulesync: str | None = None) -> bool:
    config = _load_config(config_path)
    executable = _resolve_executable(config, rulesync)
    desired = _generate(config, executable)
    _protect_sources(config, desired)
    output = config["_output"]
    _assert_plain_output(output)
    _recover(output, config, readonly=True)
    owned = _validate_reconcile(output, desired, _read_manifest(output, config), config)
    if set(owned) != set(desired):
        return False
    return all(_actual(output / rel) == (_digest(data), mode) for rel, (data, mode) in desired.items())


def preview(config_path: str | Path, rulesync: str | None = None) -> dict:
    """List what apply would change, without writing or locking the output."""
    config = _load_config(config_path)
    executable = _resolve_executable(config, rulesync)
    desired = _generate(config, executable)
    _protect_sources(config, desired)
    output = config["_output"]
    _assert_plain_output(output)
    _recover(output, config, readonly=True)
    owned = _validate_reconcile(output, desired, _read_manifest(output, config), config, allow_absent_retired=True)
    stale, writes, _, _, manifest_needs = _plan(output, desired, owned)
    changes = [{"path": rel, "operation": "update" if rel in owned else "add"} for rel in writes]
    changes += [{"path": rel, "operation": "delete"} for rel in stale]
    return {"changes": sorted(changes, key=lambda change: change["path"]), "manifest": manifest_needs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("apply", "check"))
    parser.add_argument("config")
    parser.add_argument("--rulesync")
    args = parser.parse_args(argv)
    try:
        changed = apply(args.config, args.rulesync) if args.command == "apply" else check(args.config, args.rulesync)
        print(json.dumps({"ok": bool(changed), "changed": bool(changed) if args.command == "apply" else None}))
        return 0 if args.command == "apply" or changed else 1
    except BackendError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
