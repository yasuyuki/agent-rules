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
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "16.39.1"
MANIFEST = ".rulesync-ownership.json"
JOURNAL = ".rulesync-transaction.json"
LOCK = ".rulesync-transaction.lock"
TARGETS = {"codexcli", "claudecode", "grokcli", "opencode"}
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
        raise BackendError("targets must be a non-empty subset of codexcli, claudecode, grokcli, opencode")
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
            version = subprocess.run(_tool_command(str(executable), ["--version"]), text=True, capture_output=True, check=False)
            if version.returncode == 0 and version.stdout.strip() == VERSION:
                return str(executable)
            raise BackendError(f"rulesync must be exactly {VERSION}: {executable}")
    raise BackendError("Rulesync executable not found; pass --rulesync or install the pinned local dependency")


def _tool_command(executable: str, args: list[str]) -> list[str]:
    if os.name == "nt" and executable.lower().endswith(".cmd"):
        # Run the pinned npm entry with Node directly, avoiding cmd.exe's
        # reinterpretation of source paths containing shell metacharacters.
        script = Path(executable).parent.parent / "rulesync" / "dist" / "cli" / "index.js"
        if not script.is_file():
            raise BackendError("select an npm-installed Rulesync shim or a native executable")
        return [shutil.which("node") or "node", str(script), *args]
    return [executable, *args]


def _allowed(target: str, rel: str, global_mode: bool = False) -> bool:
    if target == "codexcli":
        rule = ".codex/AGENTS.md" if global_mode else "AGENTS.md"
        return rel == rule or rel.startswith(".agents/skills/")
    if target == "claudecode":
        return rel == (".claude/CLAUDE.md" if global_mode else "CLAUDE.md") or rel.startswith(".claude/rules/") or rel.startswith(".claude/skills/")
    if target == "grokcli":
        return rel == (".grok/AGENTS.md" if global_mode else "AGENTS.md") or rel.startswith(".grok/rules/") or rel.startswith(".grok/skills/")
    return rel == (".config/opencode/AGENTS.md" if global_mode else "AGENTS.md") or rel.startswith(".config/opencode/skills/" if global_mode else ".opencode/skills/")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _combine(combined: dict[str, tuple[bytes, int]], rel: str, value: tuple[bytes, int]) -> None:
    old = combined.get(rel)
    if old is not None and old != value:
        raise BackendError(f"shared-output conflict for {rel}")
    combined[rel] = value


def _generate(config: dict, executable: str) -> dict[str, tuple[bytes, int]]:
    combined: dict[str, tuple[bytes, int]] = {}
    with tempfile.TemporaryDirectory(prefix="rulesync-backend-") as temp:
        temp_root = Path(temp)
        for target in config["targets"]:
            stage = temp_root / target / "out"
            home = temp_root / target / "home"
            stage.mkdir(parents=True)
            home.mkdir()
            cmd = ["generate", "--targets", target, "--features", ",".join(config["features"]), "--input-roots", *map(str, config["_roots"]), "--output-roots", str(stage), "--silent"]
            if config["global"]:
                cmd.append("--global")
            # Preserve only process essentials; redirect every known tool home so
            # native generation cannot discover or modify live configuration.
            env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "COMSPEC", "HOMEDRIVE", "HOMEPATH", "TEMP", "TMP") if key in os.environ}
            env.update({"HOME": str(home), "USERPROFILE": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"), "CODEX_HOME": str(home / ".codex"), "CLAUDE_CONFIG_DIR": str(home / ".claude"), "GROK_CONFIG_DIR": str(home / ".grok"), "OPENCODE_CONFIG_DIR": str(home / ".config" / "opencode")})
            run = subprocess.run(_tool_command(executable, cmd), cwd=temp_root, env=env, text=True, capture_output=True, check=False)
            if run.returncode:
                raise BackendError(f"Rulesync generation failed for {target}: {(run.stderr or run.stdout).strip()}")
            # In global mode Rulesync deliberately writes below HOME and ignores
            # output-roots.  HOME is our staging root, so reconcile that tree.
            generated_root = home if config["global"] else stage
            for item in _walk_plain(generated_root):
                if not item.is_file():
                    continue
                rel = item.relative_to(generated_root).as_posix()
                if not _allowed(target, rel, config["global"]):
                    raise BackendError(f"Rulesync emitted unsupported path for {target}: {rel}")
                value = (item.read_bytes(), stat.S_IMODE(item.stat().st_mode) & 0o777)
                _combine(combined, rel, value)
    if "grokcli" in config["targets"] and not config["global"] and "CLAUDE.md" in combined:
        raise BackendError("Grok also discovers CLAUDE.md; use non-root Claude rules to avoid duplicate policy")
    return combined


def _read_manifest(output: Path, config: dict) -> dict[str, dict] | None:
    manifest = output / MANIFEST
    if not manifest.exists():
        return None
    if _is_link_or_reparse(manifest):
        raise BackendError(f"symlink or junction is not allowed: {manifest}")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1 or set(value) != {"version", "files"} or not isinstance(value.get("files"), list):
            raise ValueError("invalid format")
        files = {}
        for entry in value["files"]:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "mode"}:
                raise ValueError("invalid file entry")
            rel, digest, mode = entry["path"], entry["sha256"], entry["mode"]
            pure = Path(rel) if isinstance(rel, str) else Path("")
            if (not isinstance(rel, str) or not rel or rel != pure.as_posix() or ":" in rel or "\\" in rel or pure.is_absolute() or pure.drive or any(part in ("", ".", "..") for part in pure.parts) or rel == MANIFEST or rel in files or not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest) or not isinstance(mode, int) or isinstance(mode, bool) or mode < 0 or mode > 0o777 or not any(_allowed(target, rel, config["global"]) for target in config["targets"])):
                raise ValueError("invalid file entry")
            files[rel] = {"sha256": digest, "mode": mode}
        return files
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
    roots = set()
    for rel in files:
        parts = rel.split("/")
        for index, part in enumerate(parts):
            if part == "skills" and len(parts) > index + 1:
                roots.add("/".join(parts[: index + 2]))
    return roots


def _validate_reconcile(output: Path, desired: dict[str, tuple[bytes, int]], owned: dict[str, dict] | None, config: dict, allow_grok_stale_claude: bool = False) -> dict[str, dict]:
    _assert_plain_output(output)
    owned = owned or {}
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
    for skill in _skill_roots(desired) | _skill_roots({rel: (b"", 0) for rel in owned}):
        directory = output / skill
        if directory.exists():
            matching_owned = any(rel.startswith(skill + "/") for rel in owned)
            if not matching_owned:
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


def _manifest_bytes(desired: dict[str, tuple[bytes, int]]) -> bytes:
    files = [{"path": rel, "sha256": _digest(data), "mode": mode} for rel, (data, mode) in sorted(desired.items())]
    return (json.dumps({"version": 1, "files": files}, sort_keys=True, indent=2) + "\n").encode()


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
            allowed = rel == MANIFEST or any(_allowed(target, rel, config["global"]) for target in config["targets"])
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
            else:
                _write_atomic(path, *previous)
        except BaseException as exc:
            failure = failure or exc
    if failure:
        raise BackendError("rollback failed") from failure


def _apply_reconcile(output: Path, desired: dict[str, tuple[bytes, int]], owned: dict[str, dict]) -> bool:
    stale = set(owned) - set(desired)
    writes = {rel: value for rel, value in desired.items() if rel not in owned or _actual(output / rel) != (_digest(value[0]), value[1])}
    manifest = output / MANIFEST
    manifest_data = _manifest_bytes(desired)
    manifest_needs = not manifest.exists() or manifest.read_bytes() != manifest_data
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
            raise BackendError("rollback failed") from rollback
        raise exc
    return True


def _plain_relative(rel: object, config: dict) -> str:
    if not isinstance(rel, str) or not rel:
        raise ValueError("invalid file entry")
    pure = Path(rel)
    if (rel != pure.as_posix() or ":" in rel or "\\" in rel or pure.is_absolute() or pure.drive
            or any(part in ("", ".", "..") for part in pure.parts) or rel in (MANIFEST, JOURNAL, LOCK)
            or not any(_allowed(target, rel, config["global"]) for target in config["targets"])):
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
        owned = _validate_reconcile(output, desired, _read_manifest(output, config), config)
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
