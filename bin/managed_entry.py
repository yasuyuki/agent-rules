#!/usr/bin/env python3
"""Install and resolve the small standard-name entrypoints for ``place.py``.

The installed state is deliberately limited to links and one JSON file in the
chosen directory.  It never changes a vendor executable or PATH globally.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


class EntryError(RuntimeError):
    pass


HERE = Path(__file__).resolve().parent
DISPATCHER = HERE / "managed-cli"
PLACE = HERE / "place.py"
BINDING_NAME = ".managed-entry.json"
VERSION = 1


def _absolute(path):
    return Path(path).expanduser().absolute()


def _name(value):
    if not value or Path(value).name != value or value in {".", ".."}:
        raise EntryError("tool name must be a single executable name: %r" % value)
    return value


def _is_executable(path):
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and os.access(path, os.X_OK)


def _same_file(left, right):
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False


def _vendor_path(directory, path=None):
    values = (os.environ.get("PATH", "") if path is None else path).split(os.pathsep)
    result = []
    directory = _absolute(directory)
    for value in values:
        # Empty PATH components mean the current directory.  Preserve that
        # semantic, except when it is the managed directory itself.
        candidate = _absolute(value or os.curdir)
        if candidate == directory:
            continue
        # Store an absolute lexical path.  In particular, an empty or relative
        # component must not later acquire the dispatcher's invocation cwd.
        normalized = str(candidate)
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise EntryError("vendor PATH would be empty after excluding managed directory")
    return result


def _document(directory, config, tools, vendor_path, *, place=None, dispatcher=None):
    place = PLACE if place is None else place
    dispatcher = DISPATCHER if dispatcher is None else dispatcher
    return {
        "version": VERSION,
        "kind": "agent-rules-managed-entry",
        "directory": str(_absolute(directory)),
        "dispatcher": str(_absolute(dispatcher)),
        "place": str(_absolute(place)),
        "config": str(_absolute(config)),
        "vendor_path": vendor_path,
        "tools": list(tools),
    }


def _validate_document(document, directory=None):
    if not isinstance(document, dict):
        raise EntryError("managed entry binding must be a JSON object")
    required = {"version", "kind", "directory", "dispatcher", "place", "config", "vendor_path", "tools"}
    if set(document) != required or document.get("version") != VERSION or document.get("kind") != "agent-rules-managed-entry":
        raise EntryError("unsupported managed entry binding")
    for key in ("directory", "dispatcher", "place", "config"):
        if not isinstance(document[key], str) or not document[key]:
            raise EntryError("managed entry binding has invalid %s" % key)
    if not isinstance(document["vendor_path"], list) or not document["vendor_path"] or any(not isinstance(value, str) for value in document["vendor_path"]):
        raise EntryError("managed entry binding has invalid vendor_path")
    if (not isinstance(document["tools"], list) or not document["tools"] or
            any(not isinstance(tool, str) for tool in document["tools"]) or
            len(set(document["tools"])) != len(document["tools"])):
        raise EntryError("managed entry binding has invalid tools")
    for tool in document["tools"]:
        _name(tool)
    if directory is not None and _absolute(document["directory"]) != _absolute(directory):
        raise EntryError("managed entry binding belongs to another directory")
    for key in ("dispatcher", "place"):
        if not Path(document[key]).is_file():
            raise EntryError("managed entry binding is stale: %s does not exist" % key)
    return document


def load_binding(directory):
    """Read and validate the binding owned by *directory*."""
    directory = _absolute(directory)
    path = directory / BINDING_NAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EntryError("invalid managed entry binding %s: %s" % (path, exc)) from None
    return _validate_document(document, directory)


def _find_vendor(name, vendor_path, *, seen=None):
    name = _name(name)
    seen = set() if seen is None else seen
    for segment in vendor_path:
        directory = _absolute(segment or os.curdir)
        binding_path = directory / BINDING_NAME
        # A binding reserves this PATH directory.  Treat damage as an error
        # even if this particular name is absent, rather than falling through
        # to an unmanaged executable later in PATH.
        if binding_path.exists() or binding_path.is_symlink():
            binding = load_binding(directory)
            marker = str(directory)
            if marker in seen:
                raise EntryError("managed entry resolver loop for %s" % name)
            candidate = directory / name
            if candidate.exists() or candidate.is_symlink():
                managed = _managed_candidate(candidate)
                if managed is None:
                    raise EntryError("managed entry binding does not own %s" % candidate)
                seen.add(marker)
                return _find_vendor(name, binding["vendor_path"], seen=seen)
        candidate = directory / name
        if not _is_executable(candidate):
            continue
        managed = _managed_candidate(candidate)
        if managed is None:
            return str(candidate)
        directory, binding = managed
        marker = str(directory)
        if marker in seen:
            raise EntryError("managed entry resolver loop for %s" % name)
        seen.add(marker)
        return _find_vendor(name, binding["vendor_path"], seen=seen)
    return None


def _managed_candidate(candidate):
    """Return an owned dispatcher binding, or reject a corrupt dispatcher."""
    try:
        resolves_dispatcher = _same_file(candidate, DISPATCHER)
    except OSError:
        resolves_dispatcher = False
    binding_path = candidate.parent / BINDING_NAME
    if not binding_path.exists() and not resolves_dispatcher:
        return None
    try:
        binding = load_binding(candidate.parent)
    except EntryError:
        # A dispatcher-like link must never be skipped in favour of a later
        # PATH entry: doing so silently bypasses the managed route.
        if resolves_dispatcher or binding_path.exists():
            raise
        return None
    if candidate.name not in binding["tools"] or not candidate.is_symlink() or not _same_file(candidate, binding["dispatcher"]):
        raise EntryError("managed entry link is stale or changed: %s" % candidate)
    return candidate.parent, binding


def resolve_executable(name, *, binding=None, path=None):
    """Resolve a vendor executable without recursively selecting this dispatcher.

    ``binding`` is normally the caller's binding.  Without it, PATH is walked;
    an owned managed link switches the search to its saved vendor PATH.
    """
    if binding is not None:
        binding = _validate_document(binding)
        result = _find_vendor(name, binding["vendor_path"])
    else:
        result = _find_vendor(name, (os.environ.get("PATH", "") if path is None else path).split(os.pathsep))
    return result


def install(config, directory, tools, *, path=None):
    """Validate then install managed links.  Returns the binding path.

    This is the API used by ``place.py entry install``.
    """
    if os.name != 'posix':
        raise EntryError('standard-name installation requires a POSIX runtime')
    directory, config = _absolute(directory), _absolute(config)
    tools = tuple(dict.fromkeys(_name(tool) for tool in tools))
    if not tools:
        raise EntryError("at least one --tool is required")
    if not directory.is_dir():
        raise EntryError("managed entry directory does not exist: %s" % directory)
    if not config.is_file():
        raise EntryError("saved start config does not exist: %s" % config)
    if not DISPATCHER.is_file() or not PLACE.is_file():
        raise EntryError("managed entry source is incomplete")
    vendor_path = _vendor_path(directory, path)
    for tool in tools:
        resolved = _find_vendor(tool, vendor_path)
        if resolved is None or _same_file(resolved, DISPATCHER):
            raise EntryError("vendor executable does not resolve: %s" % tool)
    document = _document(directory, config, tools, vendor_path)
    binding_path = directory / BINDING_NAME
    existing = None
    if binding_path.exists() or binding_path.is_symlink():
        existing = load_binding(directory)
        stable = ("directory", "config")
        if any(existing[key] != document[key] for key in stable):
            raise EntryError("managed entry binding differs; refusing to replace it")
        old_tools = set(existing["tools"])
        if not old_tools.issubset(tools):
            raise EntryError("managed entry install cannot remove tools; use entry remove")
        # Every existing entry must still be owned before any source, PATH, or
        # tool-set update can proceed.  This makes a changed user link a hard
        # stop instead of an opportunity to replace it.
        for tool in existing["tools"]:
            target = directory / tool
            if not target.is_symlink() or not _same_file(target, existing["dispatcher"]):
                raise EntryError("managed entry link is stale or changed: %s" % target)
    for tool in tools:
        target = directory / tool
        if target.exists() or target.is_symlink():
            if existing is None or tool not in existing["tools"] or not target.is_symlink() or not _same_file(target, existing["dispatcher"]):
                raise EntryError("managed entry collision: %s" % target)
    # All checks above precede mutation.  A failure while publishing links only
    # removes links created by this call; pre-existing owned state remains.
    created = []
    try:
        if existing is None:
            data = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".managed-entry-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, binding_path)
            finally:
                temporary.unlink(missing_ok=True)
        elif existing != document:
            # This can only rebind an already owned complete set.  A source
            # checkout normally keeps these paths stable; this path also makes
            # an intentional reviewed relocation explicit and bounded.
            data = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".managed-entry-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(temporary, binding_path)
            finally:
                temporary.unlink(missing_ok=True)
        # Replace owned links with same-directory temporary symlinks.  os.replace
        # avoids an unlink-first interval in which a later PATH entry could run.
        for tool in (existing or {}).get("tools", []):
            target = directory / tool
            if _same_file(target, DISPATCHER):
                continue
            temporary = directory / (".managed-entry-link-" + tool)
            if temporary.exists() or temporary.is_symlink():
                raise EntryError("managed entry temporary collision: %s" % temporary)
            temporary.symlink_to(DISPATCHER)
            try:
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        for tool in tools:
            target = directory / tool
            if not target.exists() and not target.is_symlink():
                temporary = directory / (".managed-entry-link-" + tool)
                if temporary.exists() or temporary.is_symlink():
                    raise EntryError("managed entry temporary collision: %s" % temporary)
                temporary.symlink_to(DISPATCHER)
                try:
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
                created.append(target)
    except OSError as exc:
        for target in created:
            target.unlink(missing_ok=True)
        raise EntryError("could not install managed entry: %s" % (exc.strerror or exc)) from None
    return binding_path


def remove(directory):
    """Remove only unchanged links and a valid binding owned by *directory*."""
    directory = _absolute(directory)
    binding = load_binding(directory)
    targets = [directory / tool for tool in binding["tools"]]
    for target in targets:
        if not target.is_symlink() or not _same_file(target, binding["dispatcher"]):
            raise EntryError("managed entry link changed; refusing to remove: %s" % target)
    for target in targets:
        target.unlink()
    (directory / BINDING_NAME).unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    install_p = sub.add_parser("install")
    install_p.add_argument("--config", required=True)
    install_p.add_argument("--directory", required=True)
    install_p.add_argument("--tool", action="append", required=True)
    remove_p = sub.add_parser("remove")
    remove_p.add_argument("--directory", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            install(args.config, args.directory, args.tool)
        else:
            remove(args.directory)
        return 0
    except EntryError as exc:
        print("FAIL: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
