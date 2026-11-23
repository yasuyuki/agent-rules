#!/usr/bin/env python3
"""The task checkout a registered inventory change runs in: a wl slot."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess


class BranchError(Exception):
    pass


def _run(repo, args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                          env={**os.environ, 'GIT_LITERAL_PATHSPECS': '1'})


def git(repo, *args, optional=False):
    result = _run(repo, args)
    if result.returncode:
        if optional:
            return None
        raise BranchError(result.stderr.decode('utf-8', 'replace').strip() or 'git failed: ' + ' '.join(args))
    return result.stdout.decode('utf-8').strip()


def git_bytes(repo, *args, optional=False):
    result = _run(repo, args)
    if result.returncode:
        if optional:
            return None
        raise BranchError(result.stderr.decode('utf-8', 'replace'))
    return result.stdout


def oid(repo, ref='HEAD'):
    value = git(repo, 'rev-parse', '--verify', ref + '^{commit}', optional=True)
    if not value:
        raise BranchError('missing commit: ' + ref)
    return value


def top(repo):
    return Path(git(repo, 'rev-parse', '--show-toplevel')).resolve()


def wl_registration(status, checkout, branch, tip):
    """The task of `wl status` output whose slot is `checkout`, or None when no wl task owns it."""
    for task in status.get('tasks', []):
        if Path(task['worktree']).resolve() != checkout:
            continue
        if task['stage'] != 'ready':
            raise BranchError('wl task %s is not ready' % task['task'])
        if task.get('finish'):
            raise BranchError('wl task %s is finishing' % task['task'])
        if task['branch'] != branch:
            raise BranchError('not on the branch of wl task %s' % task['task'])
        return {'task': task['task'], 'tip': tip, 'branch': branch}
    return None


@contextmanager
def registered_checkout(repo):
    """The wl task whose slot is this checkout; anything else is refused."""
    checkout = top(repo)
    wl = shutil.which('wl')
    if wl is None:
        raise BranchError('wl is not on PATH; begin the change as a wl task')
    result = subprocess.run([wl, '--repo', str(checkout), 'status'], capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise BranchError('wl status failed: ' + result.stderr.strip())
    branch = git(checkout, 'symbolic-ref', '--quiet', '--short', 'HEAD', optional=True)
    registration = branch and wl_registration(json.loads(result.stdout), checkout, branch, oid(checkout))
    if not registration:
        raise BranchError('this checkout is not the slot of a ready wl task; begin the change with wl begin')
    yield registration
