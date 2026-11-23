#!/usr/bin/env python3
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess

from workspace_lifecycle.compat import BranchError, git, git_bytes, oid, top
from workspace_lifecycle.compat import registered_checkout as _legacy_registered_checkout


def wl_registration(status, checkout, branch, tip):
    """The task of `wl status` output whose slot is `checkout`, or None when no wl task owns it."""
    for task in status.get("tasks", []):
        if Path(task["worktree"]).resolve() != checkout:
            continue
        if task["stage"] != "ready":
            raise BranchError("wl task %s is not ready" % task["task"])
        if task.get("finish"):
            raise BranchError("wl task %s is finishing" % task["task"])
        if task["branch"] != branch:
            raise BranchError("not on the branch of wl task %s" % task["task"])
        return {"task": task["task"], "tip": tip, "branch": branch}
    return None


def _wl_status(checkout):
    if not (Path(git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "wl").is_dir():
        return None
    wl = shutil.which("wl")
    if wl is None:
        raise BranchError("the repository has wl tasks but wl is not on PATH")
    result = subprocess.run([wl, "--repo", str(checkout), "status"], capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise BranchError("wl status failed: " + result.stderr.strip())
    return json.loads(result.stdout)


@contextmanager
def registered_checkout(repo):
    """The task that owns this checkout: a wl slot, else a legacy workspace-lifecycle worktree."""
    checkout = top(repo)
    status = _wl_status(checkout)
    branch = git(checkout, "symbolic-ref", "--quiet", "--short", "HEAD", optional=True)
    registration = status and branch and wl_registration(status, checkout, branch, oid(checkout))
    if registration:
        yield registration
        return
    with _legacy_registered_checkout(repo) as legacy:
        yield legacy
