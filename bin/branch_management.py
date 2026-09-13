#!/usr/bin/env python3
"""Local work/branch registration and Git reference enforcement.

State and one-use authorizations belong to the Git common directory. They are
not portable project records. No command resets, stashes or deletes user work.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ('prepare-commit-msg', 'reference-transaction', 'pre-push')


class BranchError(RuntimeError):
    pass


def git(repo, *args, optional=False, env=None):
    p = subprocess.run(['git', '-C', str(repo), *args], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, encoding='utf-8', env=env)
    if p.returncode and not optional:
        raise BranchError(p.stderr.strip() or 'git failed: ' + ' '.join(args))
    return p.stdout.strip() if p.returncode == 0 else None


def git_bytes(repo, *args, optional=False):
    """Read an exact Git object without text decoding or newline stripping."""
    p = subprocess.run(['git', '-C', str(repo), *args], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if p.returncode and not optional:
        raise BranchError(p.stderr.decode('utf-8', 'replace').strip() or 'git failed: ' + ' '.join(args))
    return p.stdout if p.returncode == 0 else None


def oid(repo, ref):
    value = git(repo, 'rev-parse', '--verify', ref + '^{commit}', optional=True)
    if not value:
        raise BranchError('missing commit: ' + ref)
    return value


def branch(repo):
    value = git(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD', optional=True)
    if not value:
        raise BranchError('detached HEAD is not a registered checkout')
    return value


def top(repo):
    return str(Path(git(repo, 'rev-parse', '--show-toplevel')).resolve())


def common(repo):
    return Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'))


def ancestor(repo, a, b):
    return git(repo, 'merge-base', '--is-ancestor', a, b, optional=True) is not None


def atomic(path, data):
    fd, name = tempfile.mkstemp(prefix='state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(data, stream, ensure_ascii=True, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name != 'nt':
            parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(repo, create=False):
    directory = common(repo) / 'agent-branches'
    if create:
        directory.mkdir(exist_ok=True)
    if not directory.is_dir():
        raise BranchError('branch management is not installed')
    # OS locks disappear on process death. Reference-changing Git operations
    # invoke our hooks and must run outside this non-reentrant lock. Worktree
    # removal changes no refs and is serialized here with registration changes.
    with (directory / 'lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            except OSError as exc:
                raise BranchError('registration busy; retry without discarding work') from exc
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            path = directory / 'state.json'
            state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
            yield directory, state
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def save(directory, state):
    atomic(directory / 'state.json', state)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(state):
    if not isinstance(state, dict) or state.get('version') != 1:
        raise BranchError('missing or unsupported branch registration')


def dependency_worktrees(source, python):
    # Protect both the named executable (which may be a venv symlink) and its
    # resolved target. Git's native lock is shared across consumer repositories.
    found = {}
    # Dependency discovery is outside the hook's current repository/index.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    seen_paths, seen_roots = set(), set()
    for path in (Path(source), Path(python).absolute().parent, Path(python).resolve().parent):
        named = path.absolute()
        if named in seen_paths:
            continue
        seen_paths.add(named)
        root = git(path, 'rev-parse', '--show-toplevel', optional=True, env=env)
        if not root:
            continue
        root = str(Path(root).resolve())
        if root in seen_roots:
            continue
        seen_roots.add(root)
        gitdir = git(root, 'rev-parse', '--path-format=absolute', '--git-dir', env=env)
        shared = git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir', env=env)
        if Path(gitdir).resolve() == Path(shared).resolve():
            continue  # The primary checkout cannot be retired.
        lock = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'locked', env=env))
        found[root] = lock
    return found.items()


def installation_errors(repo, directory, state, *, source_check=True):
    require(state)
    errors = []
    if git(repo, 'remote', 'get-url', state['remote'], optional=True) != state['remote_url']:
        errors.append('registered remote URL changed')
    # One fresh read per validation; last value matches `config --get`. NUL
    # records avoid ambiguity with embedded newlines; strip matches git() above.
    raw = git_bytes(repo, 'config', '--null', '--get-regexp',
                    r'^(core\.hookspath|agentbranch\.(python|source))$', optional=True)
    config = {}
    for record in (raw or b'').split(b'\0'):
        if record:
            key, _, value = record.partition(b'\n')
            config[key.decode('utf-8').lower()] = value.decode('utf-8').strip()
    if config.get('core.hookspath') != str(directory / 'hooks'):
        errors.append('core.hooksPath differs from registered hooks')
    for key, value in [('agentBranch.python', state['python']), ('agentBranch.source', state['source'])]:
        if config.get(key.lower()) != value:
            errors.append(key + ' differs from installation')
    if source_check:
        for root, lock in dependency_worktrees(state['source'], state['python']):
            if not lock.is_file():
                errors.append('unprotected dependency worktree; reinstall reviewed source: ' + root)
    source = Path(state['source']) / 'hooks/branch-hook'
    for relative, expected in (state.get('source_hashes', {}) if source_check else {}).items():
        path = Path(state['source']) / relative
        if not path.is_file() or digest(path) != expected:
            errors.append('missing or modified public source: ' + relative)
    for name, expected in state['hook_hashes'].items():
        path = directory / 'hooks' / name
        if not path.is_file() or digest(path) != expected or os.access(path, os.X_OK) != state['hook_executable'][name]:
            errors.append('missing, modified or non-executable hook: ' + name)
    if source_check and (not source.is_file() or digest(source) != state['dispatcher_hash']):
        errors.append('public hook source changed; reinstall reviewed source')
    return errors


def assert_install(repo, directory, state):
    errors = installation_errors(repo, directory, state)
    if errors:
        raise BranchError('; '.join(errors))


def task_for(state, name):
    matches = [(key, value) for key, value in state['tasks'].items() if value['branch'] == name]
    if len(matches) != 1:
        raise BranchError('unregistered branch: ' + name)
    return matches[0]


def checkout(repo, state):
    name = branch(repo)
    key, task = task_for(state, name)
    if task['worktree'] != top(repo):
        raise BranchError('checkout does not match registered worktree: ' + name)
    return key, task


@contextmanager
def registered_checkout(repo):
    """Hold a registered checkout stable for a bounded source edit.

    Callers which edit a tracked input use this instead of reconstructing the
    branch registration.  The registration lock covers the caller's atomic
    replacement, and both the recorded branch ref and HEAD must remain the
    registered tip.
    """
    repo = Path(repo).resolve()
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        task_id, task = checkout(repo, state)
        if task['branch'] == state['default'] or task['branch'] == task['into']:
            raise BranchError('bounded source edits require a registered topic checkout')
        head = oid(repo, 'HEAD')
        if task['tip'] != head or oid(repo, 'refs/heads/' + task['branch']) != head:
            raise BranchError('registered branch tip differs from checkout HEAD')
        yield {'task': task_id, 'branch': task['branch'], 'tip': head,
               'worktree': task['worktree']}
        if (task['tip'] != head or oid(repo, 'HEAD') != head or
                oid(repo, 'refs/heads/' + task['branch']) != head):
            raise BranchError('registered branch tip changed during bounded operation')


def same_checkout(repo, path, name):
    return (top(path) == str(Path(path).resolve()) and branch(path) == name
            and common(path).resolve() == common(repo).resolve())


def registered_head_return(repo, state, new):
    """Allow only a detached worktree to reattach to its recorded branch tip.

    A symbolic HEAD update identifies its named target as
    ``ref:refs/heads/<branch>``.  Requiring that target, the worktree, its
    single registered task, the named branch ref, and the recorded tip to agree
    limits this exception to restoring the registered checkout state.
    """
    path = top(repo)
    matches = [task for task in state['tasks'].values() if task['worktree'] == path]
    if len(matches) != 1:
        return False
    task = matches[0]
    return (new == 'ref:refs/heads/' + task['branch']
            and git(repo, 'rev-parse', '--verify', 'refs/heads/' + task['branch'], optional=True) == task['tip'])


def within(child, parent):
    child, parent = Path(child).resolve(), Path(parent).resolve()
    return child == parent or parent in child.parents


def main_worktree(repo):
    for line in git(repo, 'worktree', 'list', '--porcelain').splitlines():
        if line.startswith('worktree '):
            return str(Path(line[len('worktree '):]).resolve())
    raise BranchError('repository has no working tree')


def default_remote(repo, remote):
    if remote.startswith('-') or remote not in (git(repo, 'remote') or '').splitlines():
        raise BranchError('choose an existing remote explicitly')
    text = git(repo, 'ls-remote', '--symref', remote, 'HEAD')
    refs = [line.split()[1] for line in text.splitlines() if line.startswith('ref: refs/heads/')]
    if len(refs) != 1:
        raise BranchError('remote default branch could not be verified')
    return refs[0][len('refs/heads/'):]


def install(args):
    repo = Path(args.repo).resolve()
    default = default_remote(repo, args.remote)
    # Lock before reading/pinning source bytes. Preserve existing locks and never
    # auto-unlock on rebind: another repository may still consume this checkout.
    for root, lock in dependency_worktrees(ROOT, sys.executable):
        if not lock.exists():
            git(root, 'worktree', 'lock', '--reason', 'branch management dependency', root)
    with locked(repo, create=True) as (directory, state):
        target = directory / 'hooks'
        dispatcher = ROOT / 'hooks/branch-hook'
        if state:
            require(state)
            if state['remote'] != args.remote or state['default'] != default:
                raise BranchError('remote/default changed; resolve registration before installing')
            if not state.get('installing'):
                errors = installation_errors(repo, directory, state, source_check=False)
                if errors:
                    raise BranchError('; '.join(errors))
                if digest(dispatcher) != state['dispatcher_hash']:
                    raise BranchError('dispatcher version differs; explicit hook migration is required')
                state['source'] = str(ROOT)
                state['python'] = sys.executable
                state['source_hashes'] = {name: digest(ROOT / name) for name in ('bin/branch_management.py', 'bin/push_preflight.py', 'hooks/branch-hook')}
                # Rebinding to a reviewed public source is itself an installation.
                state['installing'] = {name: {'source': str(target / name), 'sha256': expected,
                    'executable': state['hook_executable'][name]} for name, expected in state['hook_hashes'].items()}
                save(directory, state)
        else:
            old = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks'))
            if target.exists():
                raise BranchError('hook destination already exists; refusing to overwrite')
            sources = list(old.iterdir()) if old.is_dir() else []
            if any(p.is_symlink() or not p.is_file() for p in sources):
                raise BranchError('existing hooks contain links/directories; cannot preserve safely')
            if any(p.name in {name + '.previous' for name in HOOKS} for p in sources):
                raise BranchError('existing hook backup name collision')
            files = {p.name + '.previous' if p.name in HOOKS else p.name:
                     {'source': str(p), 'sha256': digest(p), 'executable': os.access(p, os.X_OK)}
                     for p in sources}
            files.update({name: {'source': str(dispatcher), 'sha256': digest(dispatcher),
                                 'executable': True} for name in HOOKS})
            state = {'version': 1, 'remote': args.remote, 'default': default,
                     'remote_url': git(repo, 'remote', 'get-url', args.remote),
                     'source': str(ROOT), 'python': sys.executable,
                     'dispatcher_hash': digest(dispatcher),
                     'source_hashes': {name: digest(ROOT / name) for name in ('bin/branch_management.py', 'bin/push_preflight.py', 'hooks/branch-hook')},
                     'hook_hashes': {name: item['sha256'] for name, item in files.items()},
                     'hook_executable': {name: item['executable'] for name, item in files.items()},
                     'tasks': {}, 'permits': {}, 'merges': {}, 'picks': {}, 'installing': files}
            # Ownership and expected bytes are durable before creating any file.
            save(directory, state)
        files = state['installing']
        if target.exists() and (target.is_symlink() or not target.is_dir()):
            raise BranchError('installation destination collision')
        target.mkdir(exist_ok=True)
        if any(p.name not in files for p in target.iterdir()):
            raise BranchError('unknown file in interrupted installation')
        for name, item in files.items():
            path = target / name
            if path.exists() or path.is_symlink():
                if path.is_symlink() or not path.is_file() or digest(path) != item['sha256']:
                    raise BranchError('interrupted installation collision: ' + name)
            else:
                source = Path(item['source'])
                if not source.is_file() or digest(source) != item['sha256']:
                    raise BranchError('installation source changed: ' + name)
                # Copy via an atomic rename; a crash never exposes partial bytes.
                fd, tmp = tempfile.mkstemp(prefix='hook-', dir=directory)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(source.read_bytes())
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(tmp, path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            path.chmod(0o755 if item['executable'] else 0o644)
        git(repo, 'config', '--local', 'agentBranch.python', state['python'])
        git(repo, 'config', '--local', 'agentBranch.source', state['source'])
        git(repo, 'config', '--local', 'core.hooksPath', str(target))
        # The hook cannot distinguish loose-ref pruning from branch deletion.
        git(repo, 'config', '--local', 'maintenance.pack-refs.enabled', 'false')
        git(repo, 'config', '--local', 'gc.packRefs', 'false')
        assert_install(repo, directory, state)
        state.pop('installing')
        save(directory, state)
    return {'installed': True, 'default': default}


def reconcile(repo, state):
    """Recover a committed ref whose final notification was interrupted."""
    for name, permit in list(state['permits'].items()):
        new = permit.get('prepared')
        current = git(repo, 'rev-parse', '--verify', 'refs/heads/' + name, optional=True)
        if new and current == new:
            finish(state, name, permit, new)


def finish(state, name, permit, new):
    _, task = task_for(state, name)
    task['tip'] = new
    operation = state.get('operations', {}).get(name)
    if operation and permit.get('operation') == operation['id']:
        operation['ref_result'] = new
        if permit.get('operation_files') is not None:
            operation['completion_files'] = permit['operation_files']
    if permit.get('pick'):
        state['picks'].pop(name + ':' + permit['pick'], None)
    if permit.get('merge'):
        source = state['tasks'][permit['merge']]
        source['integrated'] = {'source': permit['parents'][1], 'destination': name, 'commit': new}
        state['merges'].pop(name, None)
    state['permits'].pop(name, None)


def index_entries(repo, tree=None):
    result = {}
    command = ('ls-tree', '-r', '-z', tree) if tree else ('ls-files', '--stage', '-z')
    for row in git_bytes(repo, *command).split(b'\0'):
        if not row:
            continue
        metadata, path = row.split(b'\t', 1)
        mode, second, third = metadata.decode('ascii').split()
        entry = [mode, third, '0'] if tree else [mode, second, third]
        result.setdefault(os.fsdecode(path), []).append(entry)
    return result


def work_state(repo):
    """Read semantic index and exact byte/mode fingerprints; never refresh it.

    The two reads at preparation/check detect observable races, not arbitrary
    writers which change and restore bytes between reads. No backup or rollback
    is implied by a fingerprint.
    """
    entries = index_entries(repo)
    paths = set(entries)
    paths.update(os.fsdecode(p) for p in git_bytes(
        repo, 'ls-files', '--others', '-z').split(b'\0') if p)
    files = {}
    for name in sorted(paths):
        path = Path(repo) / name
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                data, kind = os.fsencode(os.readlink(path)), 'symlink'
            elif stat.S_ISREG(info.st_mode):
                data, kind = path.read_bytes(), 'file'
            else:
                files[name] = {'kind': 'special', 'mode': stat.S_IMODE(info.st_mode)}
                continue
            files[name] = {'kind': kind, 'mode': stat.S_IMODE(info.st_mode),
                           'sha256': hashlib.sha256(data).hexdigest()}
        except FileNotFoundError:
            files[name] = None
    return {'head': oid(repo, 'HEAD'), 'branch': branch(repo), 'index': entries,
            'files': files, 'git_state': {name: git(repo, 'rev-parse', '--verify', name, optional=True)
                for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD')},
            'sequencer': any(Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-path', name)).exists()
                             for name in ('sequencer', 'rebase-merge', 'rebase-apply'))}


def stable_work_state(repo):
    before = work_state(repo)
    if before != work_state(repo):
        raise BranchError('checkout changed while reading operation state; retry check')
    return before


def changed_paths(before, after):
    return sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))


def prepare_operation(repo, state, task, kind, target):
    if oid(repo, 'HEAD') != task['tip'] or branch(repo) != task['branch'] or top(repo) != task['worktree']:
        raise BranchError('operation checkout differs from registered tip/worktree')
    before = stable_work_state(repo)
    if state['permits'].get(task['branch'], {}).get('prepared'):
        raise BranchError('in-flight reference update; finish or inspect it before preparing another')
    continuing_pick = (kind == 'cherry-pick' and before['git_state']['CHERRY_PICK_HEAD'] == target
                       and not before['git_state']['MERGE_HEAD'] and not before['git_state']['REVERT_HEAD'])
    continuing_merge = (kind == 'merge' and before['git_state']['MERGE_HEAD'] == target
                        and not before['git_state']['CHERRY_PICK_HEAD'] and not before['git_state']['REVERT_HEAD']
                        and not before['sequencer'])
    if not (continuing_pick or continuing_merge) and (any(before['git_state'].values()) or before['sequencer'] or any(
            entry[2] != '0' for rows in before['index'].values() for entry in rows)):
        raise BranchError('unfinished Git operation; use branch check before preparing another')
    previous = state.setdefault('operations', {}).get(task['branch'])
    if previous and not previous.get('ref_result') and previous['before'] != before:
        if (kind == 'sync' and previous['kind'] == kind and previous['target'] == target
                and before['head'] == previous['before']['head']
                and before['index'] == previous['expected_index']
                and sync_files_match(repo, previous, before)):
            validate_operation_state(repo, previous, before)
            return previous['id']  # Retry retains the original provenance.
        raise BranchError('unresolved operation state changed; use branch check and preserve work')
    head_entries = index_entries(repo, before['head'])
    staged = changed_paths(head_entries, before['index'])
    unstaged = [os.fsdecode(p) for p in git_bytes(repo, 'diff-files', '--name-only', '-z').split(b'\0') if p]
    untracked = sorted(set(before['files']) - set(before['index']))
    operation = {'id': uuid.uuid4().hex, 'kind': kind, 'target': target,
                 'before': before, 'captured_after_git_started': continuing_pick or continuing_merge,
                 'dirty': {'staged': staged, 'unstaged': unstaged, 'untracked': untracked}}
    if kind == 'sync':
        target_entries = index_entries(repo, target)
        touched = changed_paths(head_entries, target_entries)
        if any(a == b or a.startswith(b + '/') or b.startswith(a + '/')
               for a in touched for b in staged + unstaged + untracked):
            raise BranchError('remote update overlaps existing local changes; preserve work before sync')
        expected = dict(before['index'])
        for name in touched:
            if name in target_entries:
                expected[name] = target_entries[name]
            else:
                expected.pop(name, None)
        operation.update(expected_index=expected, touched=touched)
    else:
        base = (git(repo, 'merge-base', before['head'], target) if kind == 'merge'
                else git(repo, 'rev-parse', target + '^', optional=True))
        operation['touched'] = changed_paths(index_entries(repo, base) if base else {}, index_entries(repo, target))
        if not (continuing_pick or continuing_merge) and any(
                a == b or a.startswith(b + '/') or b.startswith(a + '/')
                for a in operation['touched'] for b in staged + unstaged + untracked):
            raise BranchError('operation overlaps existing local changes; preserve work before preparation')
    if previous:
        state.setdefault('operation_history', []).append(previous)
    state['operations'][task['branch']] = operation
    return operation['id']


def validate_operation_state(repo, operation, current):
    before = operation['before']
    unexpected = set(changed_paths(before['files'], current['files']) +
                     changed_paths(before['index'], current['index'])) - set(operation['touched'])
    if unexpected:
        raise BranchError('checkout changed after preparation outside the operation: ' +
                          ', '.join(sorted(unexpected)) + '; preserve work and run branch check')


def sync_files_match(repo, operation, current):
    """Check ordinary blob bytes without executing clean filters under a lock.

    Custom filters and submodule interiors cannot be independently normalized
    here. Preserve their ordinary Git behavior, expose that limit, and retain
    exact post-update fingerprints. No user command runs from diagnostics.
    """
    algorithm = git(repo, 'rev-parse', '--show-object-format')
    def blob_oid(data):
        return hashlib.new(algorithm, b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    unverified = []
    for name in operation['touched']:
        expected = operation['expected_index'].get(name)
        actual = current['files'].get(name)
        if expected is None:
            if actual is not None:
                return False
            continue
        mode, value, _ = expected[0]
        if mode == '160000':
            unverified.append(name)
            continue  # Git does not recursively update a submodule checkout.
        if actual is None or actual['kind'] == 'special':
            return False
        path = Path(repo) / name
        if mode == '120000':
            if actual['kind'] == 'symlink':
                data = os.fsencode(os.readlink(path))
            elif actual['kind'] == 'file' and git(repo, 'config', '--bool', 'core.symlinks', optional=True) == 'false':
                data = path.read_bytes()
            else:
                return False
        else:
            if actual['kind'] != 'file':
                return False
            if os.name != 'nt' and bool(actual['mode'] & 0o111) != (mode == '100755'):
                return False
            data = path.read_bytes()
        if blob_oid(data) != value and (mode == '120000' or blob_oid(data.replace(b'\r\n', b'\n')) != value):
            attrs = git_bytes(repo, 'check-attr', '-z', 'filter', 'ident', 'working-tree-encoding', '--', name).split(b'\0')
            conversions = [os.fsdecode(attrs[i]) for i in range(2, len(attrs), 3)]
            if mode == '120000' or not any(v not in ('unspecified', 'unset') for v in conversions):
                return False
            unverified.append(name)
    operation['unverified_worktree_paths'] = unverified
    return True


def operation_diagnosis(repo, operation):
    current = stable_work_state(repo)
    before = operation['before']
    index_changed = changed_paths(before['index'], current['index'])
    files_changed = changed_paths(before['files'], current['files'])
    conflict = any(entry[2] != '0' for rows in current['index'].values() for entry in rows)
    unexpected = sorted(set(files_changed + index_changed) - set(operation['touched']))
    ref_result = operation.get('ref_result')
    matching_conflict = (operation['kind'] == 'merge' and current['git_state']['MERGE_HEAD'] == operation['target']
                         or operation['kind'] == 'cherry-pick' and current['git_state']['CHERRY_PICK_HEAD'] == operation['target'])
    if ref_result and (any(current['git_state'].values()) or current['sequencer']):
        status = 'indeterminate'  # A later unfinished Git command is not this completed operation.
    elif conflict and matching_conflict:
        status = 'conflict'
    elif conflict:
        status = 'indeterminate'
    elif ref_result and current['head'] != ref_result and ancestor(repo, ref_result, current['head']):
        status = 'completed'
    elif unexpected or current['branch'] != before['branch']:
        status = 'indeterminate'
    elif ref_result and ancestor(repo, ref_result, current['head']):
        status = 'completed'
        if current['head'] == ref_result:
            expected_index = (operation['expected_index'] if operation['kind'] == 'sync'
                              else index_entries(repo, ref_result))
            expected_files = operation.get('completion_files')
            if current['index'] != expected_index or expected_files is None or current['files'] != expected_files:
                status = 'indeterminate'
    elif current == before:
        status = 'no-update'
    elif current['head'] == before['head']:
        status = 'partial-update'
    else:
        status = 'indeterminate'
    next_step = {'completed': 'Normal registered continuation is available.',
                 'no-update': 'No observed update; retry the existing preparation before Git.',
                 'partial-update': 'Preserve work. Git may have changed index/worktree before ref refusal or interruption. For sync, retry branch begin --mode continue --sync with the same task: it accepts only the unchanged original snapshot or exact pending import. For a prepared merge, resolve and commit through its existing permission.',
                 'conflict': 'Preserve original changes; resolve Git conflicts and use git cherry-pick --continue or the prepared merge commit as appropriate. Abort can discard work and is not automatic.',
                 'indeterminate': 'Preserve work and coordinate with other writers; changes cannot safely be attributed to this operation.'}[status]
    return {'id': operation['id'], 'kind': operation['kind'], 'target': operation['target'],
            'captured_after_git_started': operation['captured_after_git_started'],
            'conflict_present': conflict,
            'attribution': 'Observed differences since preparation; concurrent writers within operation paths cannot be identified from bytes alone.',
            'unverified_worktree_paths': operation.get('unverified_worktree_paths', []),
            'last_reference_attempt': operation.get('last_reference_attempt'),
            'status': status, 'before': before, 'current': current, 'original_dirty': operation['dirty'],
            'head_changed': before['head'] != current['head'], 'index_changed': index_changed,
            'worktree_changed': files_changed, 'unexpected_paths': unexpected,
            'ref_result': ref_result, 'command_exit': None, 'next_step': next_step}


def begin(args):
    repo = Path(args.repo).resolve()
    creation = None
    if args.sync and args.mode != 'continue':
        raise BranchError('--sync is only valid for continuation')
    if not args.task.strip():
        raise BranchError('work identifier cannot be empty')
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        reconcile(repo, state)
        tasks = state['tasks']
        if args.mode == 'continue':
            if args.task not in tasks:
                raise BranchError('unknown work identifier')
            if any(getattr(args, key) is not None for key in ('base', 'into', 'depends_on')):
                raise BranchError('continuation cannot redefine base, integration or dependency')
            task = tasks[args.task]
            if any(getattr(args, field) is not None and getattr(args, field) != task[key]
                   for field, key in [('branch', 'branch'), ('worktree', 'worktree'), ('request', 'request')]):
                raise BranchError('continuation differs from registered work')
            if task.get('creating'):
                creation = task
            else:
                # Inspect named worktree without inheriting hook-local Git environment.
                if not same_checkout(repo, task['worktree'], task['branch']):
                    raise BranchError('registered worktree has changed')
                if oid(repo, 'refs/heads/' + task['branch']) != task['tip']:
                    raise BranchError('registered branch tip has changed outside enforcement')
            if args.sync:
                assert_install(task['worktree'], directory, state)
                old = task['tip']
                new = oid(repo, 'refs/remotes/' + state['remote'] + '/' + task['branch'])
                if old == new:
                    raise BranchError('same-branch remote has no new commit to import')
                if not ancestor(repo, old, new):
                    raise BranchError('same-branch remote update is not a fast-forward')
                operation = prepare_operation(task['worktree'], state, task, 'sync', new)
                state['permits'][task['branch']] = {'kind': 'import', 'old': old, 'new': new,
                                                      'worktree': task['worktree'], 'operation': operation}
        else:
            if args.task in tasks:
                raise BranchError('work already registered; use --mode continue')
            if not args.request or not args.branch or not args.worktree:
                raise BranchError('new/adopt requires --request, --branch and --worktree')
            git(repo, 'check-ref-format', '--branch', args.branch)
            path = str(Path(args.worktree).resolve())
            if any(t['branch'] == args.branch or t['worktree'] == path for t in tasks.values()):
                raise BranchError('branch or worktree already belongs to another work item')
            into = args.into or state['default']
            if into != state['default']:
                task_for(state, into)
            if args.depends_on:
                if args.depends_on not in tasks:
                    raise BranchError('dependency must already be registered')
                parent = tasks[args.depends_on]
                base = oid(repo, 'refs/heads/' + parent['branch'])
            else:
                base = oid(repo, 'refs/remotes/' + state['remote'] + '/' + state['default'])
            if args.mode == 'new':
                if not args.depends_on:
                    verified = default_remote(repo, state['remote'])
                    if verified != state['default']:
                        raise BranchError('remote default changed; resolve registration')
                    advertised = git(repo, 'ls-remote', state['remote'], 'refs/heads/' + verified).split()
                    if not advertised or advertised[0] != base:
                        raise BranchError('fetch remote default before beginning independent work')
                elif base != parent['tip']:
                    raise BranchError('dependency tip differs from registration')
                if args.branch == state['default']:
                    raise BranchError('default branch is integration-only')
                if args.base and oid(repo, args.base) != base:
                    raise BranchError('new work must start from remote default or registered parent')
                if Path(path).exists() or git(repo, 'rev-parse', '--verify', 'refs/heads/' + args.branch, optional=True):
                    raise BranchError('new branch/worktree already exists; explicitly adopt existing work')
                tip = base
            else:
                if not args.base:
                    raise BranchError('adoption requires explicit historical --base')
                base = oid(repo, args.base)
                tip = oid(repo, 'refs/heads/' + args.branch)
                if not ancestor(repo, base, tip):
                    raise BranchError('adoption base is not an ancestor of branch')
                remote_tip = git(repo, 'rev-parse', '--verify', 'refs/remotes/' + state['remote'] + '/' + args.branch, optional=True)
                remote_base = remote_tip or oid(repo, 'refs/remotes/' + state['remote'] + '/' + state['default'])
                if not ancestor(repo, base, remote_base):
                    raise BranchError('adoption base does not agree with remote history')
                if not same_checkout(repo, path, args.branch):
                    raise BranchError('adoption checkout does not match branch/worktree')
            task = {'request': args.request, 'branch': args.branch, 'worktree': path,
                    'base': base, 'depends_on': args.depends_on, 'into': into, 'tip': tip}
            tasks[args.task] = task
            if args.mode == 'new':
                task['retirement_guarded'] = True
                task['creating'] = True
                state['permits'][args.branch] = {'kind': 'create', 'old': '0' * len(base), 'new': base,
                                                 'worktree': path}
                creation = task
        save(directory, state)
        output = {'task': args.task, **task}
    if creation:
        # Registration survives failure. Continue retries rather than cleaning up.
        name = creation['branch']
        if Path(creation['worktree']).exists():
            if not same_checkout(repo, creation['worktree'], name) or oid(repo, 'refs/heads/' + name) != creation['tip']:
                raise BranchError('interrupted creation has a conflicting checkout; preserve and inspect')
        elif git(repo, 'rev-parse', '--verify', 'refs/heads/' + name, optional=True):
            git(repo, 'worktree', 'add', creation['worktree'], name)
        else:
            git(repo, 'worktree', 'add', '-b', name, creation['worktree'], creation['base'])
        git(creation['worktree'], 'config', 'branch.' + name + '.remote', state['remote'])
        git(creation['worktree'], 'config', 'branch.' + name + '.merge', 'refs/heads/' + name)
        with locked(repo) as (directory, current):
            current['tasks'][args.task].pop('creating', None)
            save(directory, current)
            output = {'task': args.task, **current['tasks'][args.task]}
    return output


def retirement_checks(repo, state, key):
    """Everything that must hold before a finished registration is closed.

    Refusal leaves both the registration and the files as they are. The
    directory checks are skipped once the checkout is gone, so the same
    conditions can be re-evaluated after removal."""
    task = state['tasks'].get(key)
    if task is None:
        raise BranchError('unregistered work item: ' + key)
    name, path = task['branch'], task['worktree']
    if name == state['default']:
        raise BranchError('the default branch registration is not retired')
    if Path(path).resolve() == Path(main_worktree(repo)).resolve():
        raise BranchError('the repository working tree is not retired')
    if top(repo) == path:
        raise BranchError('retire from another checkout of this repository')
    if not task.get('retirement_guarded'):
        raise BranchError('legacy/adopted registration needs dependency migration before retirement; keep checkout')
    # Removing the registered dispatcher source or runtime would break every
    # hook, commit and push in each repository installed from it.
    for label, value in [('source', state['source']), ('python', state['python'])]:
        if within(value, path):
            raise BranchError('registered ' + label + ' lives in this checkout; '
                              'rebind from another reviewed source first')
    done = task.get('integrated')
    if not done or done['source'] != task['tip']:
        raise BranchError('work is not integrated into its registered destination')
    if oid(repo, 'refs/heads/' + name) != task['tip']:
        raise BranchError('registered branch tip changed outside enforcement')
    if not ancestor(repo, done['commit'], 'refs/heads/' + done['destination']):
        raise BranchError('integration is not present in the destination history')
    for other, value in state['tasks'].items():
        if other != key and (value['depends_on'] == key or value['into'] == name):
            raise BranchError('another registration depends on or integrates into this work: ' + other)
    if (state['permits'].get(name) or state['merges'].get(name)
            or any(ticket['task'] == key for ticket in state['merges'].values())
            or any(pick.startswith(name + ':') for pick in state['picks'])):
        raise BranchError('in-flight permit or prepared integration; finish or retry it first')
    if Path(path).exists():
        if not same_checkout(repo, path, name):
            raise BranchError('registered worktree has changed')
        if git(path, 'status', '--porcelain', '--ignored'):
            raise BranchError('checkout has uncommitted, untracked or ignored files; preserve and inspect')
    return task


def retire(args):
    """Close a finished registration: remove its worktree, keep its branch.

    The branch and its commits stay, unregistered, so nothing becomes
    unreachable and no reference transaction is needed. Only the final removal
    from `tasks` writes the registration, so an interrupted run is completed by
    running the same command again."""
    repo = Path(args.repo).resolve()
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        reconcile(repo, state)
        task = retirement_checks(repo, state, args.task)
        save(directory, state)
        name, path = task['branch'], task['worktree']
        output = {'task': args.task, 'branch': name, 'worktree': path, 'tip': task['tip'],
                  'destination': task['integrated']['destination'],
                  'retired': True, 'branch_retained': True}
        # Worktree removal does not update refs or invoke reference hooks.
        # Keep registration changes excluded until removal and bookkeeping end.
        if Path(path).exists():
            git(repo, 'worktree', 'remove', path)  # never --force; honors Git locks
            if Path(path).exists():
                raise BranchError('worktree removal left the checkout in place')
        listed = [str(Path(line[len('worktree '):]).resolve())
                  for line in git(repo, 'worktree', 'list', '--porcelain').splitlines()
                  if line.startswith('worktree ')]
        if path in listed:
            git(repo, 'worktree', 'prune')  # metadata only, never files
            remaining = [str(Path(line[len('worktree '):]).resolve())
                         for line in git(repo, 'worktree', 'list', '--porcelain').splitlines()
                         if line.startswith('worktree ')]
            if path in remaining:
                raise BranchError('worktree metadata remains; preserve registration and inspect its lock')
        state['tasks'].pop(args.task)
        operation = state.get('operations', {}).pop(name, None)
        if operation:
            state.setdefault('operation_history', []).append(operation)
        save(directory, state)
    return output


def merge_valid(repo, state, name, ticket):
    source = state['tasks'][ticket['task']]
    _, target = task_for(state, name)
    guarded = [source]
    if source['depends_on']:
        guarded.append(state['tasks'][source['depends_on']])
    if any(state['permits'].get(item['branch'], {}).get('prepared') for item in guarded):
        raise BranchError('merge source or dependency has an in-flight reference update; retry')
    if source['tip'] != ticket['source'] or target['tip'] != ticket['old']:
        raise BranchError('merge tips differ from registration')
    if source['into'] != name:
        raise BranchError('merge direction differs from registration')
    if oid(repo, 'refs/heads/' + source['branch']) != ticket['source'] or oid(repo, 'refs/heads/' + name) != ticket['old']:
        raise BranchError('merge source or destination moved; prepare again')
    dependency = source['depends_on']
    if dependency:
        parent = state['tasks'][dependency]
        done = parent.get('integrated')
        if parent is not target and (not done or done['source'] != oid(repo, 'refs/heads/' + parent['branch'])
                                     or not ancestor(repo, done['commit'], ticket['old'])):
            raise BranchError('dependency must be integrated first into destination history')


def prepare_merge(args):
    with locked(args.repo) as (directory, state):
        assert_install(args.repo, directory, state)
        reconcile(args.repo, state)
        _, target = checkout(args.repo, state)
        if args.task not in state['tasks']:
            raise BranchError('unknown source work')
        source = state['tasks'][args.task]
        if not same_checkout(args.repo, source['worktree'], source['branch']):
            raise BranchError('merge source worktree differs from registration')
        if source['branch'] == target['branch']:
            raise BranchError('cannot merge work into itself')
        ticket = {'task': args.task, 'source': oid(args.repo, 'refs/heads/' + source['branch']),
                  'old': oid(args.repo, 'HEAD')}
        merge_valid(args.repo, state, target['branch'], ticket)
        ticket['operation'] = prepare_operation(args.repo, state, target, 'merge', ticket['source'])
        state['merges'][target['branch']] = ticket
        save(directory, state)
        return ticket


def allow_pick(args):
    if not args.approval.strip() or not args.reason.strip():
        raise BranchError('explicit user approval reference and reason are required')
    with locked(args.repo) as (directory, state):
        assert_install(args.repo, directory, state)
        _, task = checkout(args.repo, state)
        if task['branch'] == state['default']:
            raise BranchError('cherry-pick destination must be a topic')
        commit = oid(args.repo, args.commit)
        key = task['branch'] + ':' + commit
        operation = prepare_operation(args.repo, state, task, 'cherry-pick', commit)
        state['picks'][key] = {'approval': args.approval, 'reason': args.reason,
                               'old': oid(args.repo, 'HEAD'), 'worktree': task['worktree'],
                               'operation': operation}
        save(directory, state)
        return {'commit': commit, 'destination': task['branch'], 'approval': args.approval}


def prepare_commit(repo, directory, state):
    _, task = checkout(repo, state)
    name = task['branch']
    old = oid(repo, 'HEAD')
    if task['tip'] != old:
        raise BranchError('branch tip differs from registration')
    merge_head = Path(git(repo, 'rev-parse', '--git-path', 'MERGE_HEAD'))
    pick = git(repo, 'rev-parse', '--verify', 'CHERRY_PICK_HEAD', optional=True)
    parents = [old]
    permit = {'kind': 'commit', 'old': old, 'worktree': task['worktree']}
    if merge_head.exists():
        heads = merge_head.read_text().splitlines()
        ticket = state['merges'].get(name)
        if not ticket or heads != [ticket['source']]:
            raise BranchError('merge is not authorized by prepare-merge')
        merge_valid(repo, state, name, ticket)
        parents += heads
        permit['merge'] = ticket['task']
        permit['operation'] = ticket.get('operation')
    elif name == state['default']:
        raise BranchError('default branch is integration-only')
    if pick:
        permission = state['picks'].get(name + ':' + pick)
        if not permission or permission['old'] != old or permission['worktree'] != task['worktree']:
            raise BranchError('cherry-pick needs an exact user-approved exception')
        permit['pick'] = pick
        permit['operation'] = permission.get('operation')
    permit['parents'] = parents
    operation = state.get('operations', {}).get(name)
    if permit.get('operation'):
        if not operation or operation['id'] != permit['operation']:
            raise BranchError('stale operation snapshot; preserve work and run branch check')
        prepared_state = stable_work_state(repo)
        validate_operation_state(repo, operation, prepared_state)
        permit['operation_files'] = prepared_state['files']
    permit['tree'] = git(repo, 'write-tree')  # Inherits the actual GIT_INDEX_FILE.
    state['permits'][name] = permit
    save(directory, state)


def transaction(repo, directory, state, phase, data):
    rows = [line.split() for line in data.decode().splitlines()]
    if any(len(row) != 3 for row in rows):
        raise BranchError('invalid reference transaction')
    updates = [row for row in rows if row[2].startswith('refs/heads/')]
    # HEAD updates paired with a branch are validated through that branch.
    # A detached checkout may return only to its own recorded branch tip.
    if phase == 'prepared' and any(r[2] == 'HEAD' for r in rows) and not updates:
        try:
            branch(repo)
        except BranchError:
            head_rows = [row for row in rows if row[2] == 'HEAD']
            if len(head_rows) != 1 or not registered_head_return(repo, state, head_rows[0][1]):
                raise BranchError('detached HEAD updates are not authorized')
    if phase == 'prepared':
        checked = []
        for old, new, ref in updates:
            zero = '0' * len(new)
            if (new != zero and old in (zero, new)
                    and git(repo, 'rev-parse', '--verify', ref + '^{commit}', optional=True) == new):
                continue  # Packing refs changes storage, not the already-visible branch tip.
            name = ref[len('refs/heads/'):]
            _, task = task_for(state, name)
            permit = state['permits'].get(name)
            if not permit or permit['old'] != old:
                raise BranchError('unapproved branch update: ' + name + ' (' + old + ' -> ' + new + ')')
            # A merge prepared for another transaction reserves its source until
            # commit or a retry completes; this closes cross-worktree races.
            for dest, other in state['permits'].items():
                if (other.get('prepared') and other.get('merge') and dest != name
                        and (state['tasks'][other['merge']]['branch'] == name
                             or state['tasks'][other['merge']]['depends_on'] == task_for(state, name)[0])):
                    raise BranchError('branch is reserved by an integration; finish/retry that merge')
            if permit['kind'] == 'create':
                if (not task.get('creating') or new != permit['new']
                        or git(repo, 'rev-parse', '--verify', ref, optional=True) is not None):
                    raise BranchError('branch creation differs from registration')
            else:
                _, current = checkout(repo, state)
                if current is not task or old != task['tip']:
                    raise BranchError('reference update belongs to another checkout')
                if permit['kind'] == 'import':
                    if new != permit['new'] or new != oid(repo, 'refs/remotes/' + state['remote'] + '/' + name):
                        raise BranchError('remote update differs from registered same-branch import')
                    operation = state.get('operations', {}).get(name)
                    if not operation or operation['id'] != permit.get('operation'):
                        raise BranchError('missing or stale sync snapshot; prepare again')
                    current_state = stable_work_state(repo)
                    unexpected = set(changed_paths(operation['before']['files'], current_state['files'])) - set(operation['touched'])
                    # Git may still be holding its new index in index.lock here.
                    if unexpected or current_state['index'] not in (operation['before']['index'], operation['expected_index']) or not sync_files_match(repo, operation, current_state):
                        raise BranchError('checkout changed after sync preparation; preserve work and run branch check')
                    permit['operation_files'] = current_state['files']
                else:
                    lines = git(repo, 'cat-file', '-p', new).split('\n\n', 1)[0].splitlines()
                    trees = [line[5:] for line in lines if line.startswith('tree ')]
                    parents = [line[7:] for line in lines if line.startswith('parent ')]
                    if trees != [permit['tree']] or parents != permit['parents']:
                        raise BranchError('commit tree or parents differ from authorization')
                    if git(repo, 'rev-parse', '--verify', 'CHERRY_PICK_HEAD', optional=True) != permit.get('pick'):
                        raise BranchError('cherry-pick state changed after commit preparation')
                    if permit.get('merge'):
                        merge_valid(repo, state, name, state['merges'][name])
                    if permit.get('operation'):
                        operation = state.get('operations', {}).get(name)
                        if not operation or operation['id'] != permit['operation']:
                            raise BranchError('stale operation snapshot; preserve work and run branch check')
                        current_state = stable_work_state(repo)
                        validate_operation_state(repo, operation, current_state)
                        if current_state['files'] != permit['operation_files']:
                            raise BranchError('worktree changed after commit preparation; preserve work and retry commit')
            checked.append((name, new))
        for name, new in checked:
            state['permits'][name]['prepared'] = new
        save(directory, state)
    elif phase == 'committed':
        for old, new, ref in updates:
            name = ref[len('refs/heads/'):]
            permit = state['permits'].get(name)
            if permit and permit.get('prepared') == new:
                finish(state, name, permit, new)
        save(directory, state)
    elif phase == 'aborted':
        for old, new, ref in updates:
            permit = state['permits'].get(ref[len('refs/heads/'):])
            if permit and permit.get('prepared') == new:
                permit.pop('prepared', None)
        save(directory, state)


def push_destination(repo, state, remote):
    if remote != state['remote']:
        raise BranchError('push remote differs from registration')
    fetch = git(repo, 'remote', 'get-url', '--all', remote).splitlines()
    push = git(repo, 'remote', 'get-url', '--push', '--all', remote).splitlines()
    if fetch != [state['remote_url']] or len(push) != 1:
        raise BranchError('push requires one registered fetch and one push URL')
    # Share the preflight's conservative repository identity, including supported
    # read/write transports. Pin this executable dependency with the hook source.
    spec = importlib.util.spec_from_file_location('push_identity', ROOT / 'bin/push_preflight.py')
    identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity)
    registered = identity.repo_identity(state['remote_url'])
    if registered is None or identity.repo_identity(push[0]) != registered:
        raise BranchError('push repository differs from registration')
    return push[0]


def allow_tag_push(args):
    if not args.approval.strip():
        raise BranchError('explicit user approval reference is required')
    if args.tag.startswith('refs/'):
        raise BranchError('--tag requires a tag name, not a full ref')
    ref = 'refs/tags/' + args.tag
    git(args.repo, 'check-ref-format', ref)
    with locked(args.repo) as (directory, state):
        assert_install(args.repo, directory, state)
        checkout(args.repo, state)
        destination = push_destination(args.repo, state, args.remote)
        commit = oid(args.repo, args.commit)
        if args.commit != commit:
            raise BranchError('tag approval requires a full commit object ID')
        if oid(args.repo, ref) != commit:
            raise BranchError('tag target differs from approved commit')
        value = git(args.repo, 'rev-parse', '--verify', ref)
        if git(args.repo, 'ls-remote', '--refs', args.remote, ref):
            raise BranchError('release tag already exists on remote; replacement is not authorized')
        ticket = {'object': value, 'commit': commit, 'remote': args.remote,
                  'destination': destination, 'approval': args.approval}
        state.setdefault('tag_pushes', {})[ref] = ticket
        save(directory, state)
        return {'ref': ref, **ticket}


def validate_push(repo, directory, state, rows, remote, destination=None):
    assert_install(repo, directory, state)
    expected = push_destination(repo, state, remote)
    if destination != expected:
        raise BranchError('push destination differs from registration')
    reconcile(repo, state)
    tags = []
    for local, value, target, previous in rows:
        if target.startswith('refs/tags/'):
            ticket = state.get('tag_pushes', {}).get(target)
            if not ticket:
                raise BranchError('tag push needs an exact user-approved exception')
            if target in tags:
                raise BranchError('duplicate tag push destination')
            if set(value) == {'0'} or set(previous) != {'0'}:
                raise BranchError('tag replacement or deletion is not authorized')
            if (local != target or value != ticket['object']
                    or git(repo, 'rev-parse', '--verify', target, optional=True) != value
                    or oid(repo, target) != ticket['commit']):
                raise BranchError('tag object or target differs from authorization')
            if (remote != ticket['remote'] or destination != ticket['destination']
                    or expected != destination):
                raise BranchError('tag push destination differs from authorization')
            tags.append(target)
            continue
        if not target.startswith('refs/heads/') or set(value) == {'0'}:
            raise BranchError('only registered branch pushes are authorized')
        name = target[len('refs/heads/'):]
        _, task = task_for(state, name)
        if value != task['tip'] or oid(repo, 'refs/heads/' + name) != value:
            raise BranchError('push commit differs from registered branch tip')
        if local not in ('HEAD', 'refs/heads/' + name):
            raise BranchError('push source differs from registered branch')
        if set(previous) != {'0'} and not ancestor(repo, previous, value):
            raise BranchError('push would rewrite remote history')
    return tags


def push_check(repo, remote, destination):
    """Shared preflight check; legacy, non-installed repositories remain usable."""
    directory = common(repo) / 'agent-branches'
    if not directory.exists() and not git(repo, 'config', '--get', 'agentBranch.source', optional=True):
        return
    with locked(repo) as (directory, state):
        head = oid(repo, 'HEAD')
        validate_push(repo, directory, state,
                      [('HEAD', head, 'refs/heads/' + destination, '0' * len(head))],
                      remote, push_destination(repo, state, remote))


def note_legacy_reference(state, data, outcome, code=None):
    changed = False
    for row in data.decode().splitlines():
        fields = row.split()
        if len(fields) != 3 or not fields[2].startswith('refs/heads/'):
            continue
        old, new, ref = fields
        name = ref[len('refs/heads/'):]
        permit = state['permits'].get(name)
        operation = state.get('operations', {}).get(name)
        if (permit and operation and permit.get('operation') == operation['id']
                and permit['old'] == old):
            operation['last_reference_attempt'] = {'old': old, 'new': new, 'outcome': outcome,
                                                    'legacy_hook_exit': code}
            changed = True
    return changed


def hook(name, args):
    repo = Path.cwd()
    data = sys.stdin.buffer.read() if name in ('reference-transaction', 'pre-push') else b''
    directory = common(repo) / 'agent-branches'
    previous = directory / 'hooks' / (name + '.previous')
    def legacy():
        if previous.exists() and os.access(previous, os.X_OK):
            # Git for Windows uses its shell for shebang hooks; Python CreateProcess does not.
            command, env = [str(previous)], None
            if os.name == 'nt':
                exec_path = Path(git(repo, '--exec-path'))
                shell = next((parent / 'usr/bin/sh.exe' for parent in exec_path.parents
                              if (parent / 'usr/bin/sh.exe').is_file()), None)
                if shell is None:
                    raise BranchError('Git for Windows shell is unavailable')
                command = [str(shell), '-c', 'exec "$@"', 'branch-legacy', str(previous)]
                env = dict(os.environ, PATH=str(shell.parent) + os.pathsep + os.environ.get('PATH', ''))
            return subprocess.run(command + args, input=data, env=env).returncode
        return 0
    committed = name == 'reference-transaction' and args == ['committed']
    def enforce(directory, state):
        reconcile(repo, state)
        if name == 'prepare-commit-msg':
            prepare_commit(repo, directory, state)
        elif name == 'reference-transaction':
            transaction(repo, directory, state, args[0], data)
        elif name == 'pre-push':
            rows = [line.split() for line in data.decode().splitlines()]
            if any(len(row) != 4 for row in rows):
                raise BranchError('invalid push input')
            tags = validate_push(repo, directory, state, rows, args[0], args[1])
            # pre-push cannot observe transport success. Consume only after the
            # entire batch passes; a transport failure needs fresh authorization.
            for ref in tags:
                state['tag_pushes'].pop(ref, None)
            save(directory, state)
        else:
            raise BranchError('unknown hook')
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        # Without an external legacy hook, validate and enforce in this same
        # lock scope. Never carry validation across a legacy hook invocation.
        needs_legacy = not committed and previous.exists() and os.access(previous, os.X_OK)
        if needs_legacy and name == 'reference-transaction' and args == ['prepared']:
            if note_legacy_reference(state, data, 'entered-legacy-hook'):
                save(directory, state)
        if not needs_legacy:
            enforce(directory, state)
    if needs_legacy:
        code = legacy()
        if code:
            if name == 'reference-transaction' and args == ['prepared']:
                try:
                    with locked(repo) as (directory, state):
                        assert_install(repo, directory, state)
                        if note_legacy_reference(state, data, 'legacy-refused', code):
                            save(directory, state)
                except (BranchError, OSError) as exc:
                    # Evidence failure must not replace the legacy hook's exit.
                    print('branch diagnostic could not record refusal: ' + str(exc), file=sys.stderr)
            return code
        with locked(repo) as (directory, state):
            assert_install(repo, directory, state)
            enforce(directory, state)
    return legacy() if committed else 0


def check(args):
    with locked(args.repo) as (directory, state):
        errors = installation_errors(args.repo, directory, state)
        try:
            checkout(args.repo, state)
        except BranchError as exc:
            errors.append(str(exc))
        for key, task in state['tasks'].items():
            try:
                if not same_checkout(args.repo, task['worktree'], task['branch']):
                    errors.append(key + ': worktree mismatch')
                if oid(args.repo, 'refs/heads/' + task['branch']) != task['tip']:
                    errors.append(key + ': tip mismatch')
                if task['depends_on'] and task['depends_on'] not in state['tasks']:
                    errors.append(key + ': missing dependency')
            except BranchError as exc:
                errors.append(key + ': ' + str(exc))
        operations = {}
        for name, operation in state.get('operations', {}).items():
            try:
                if not any(task['branch'] == name for task in state['tasks'].values()):
                    continue  # Retired operation evidence is historical.
                _, task = task_for(state, name)
                if not Path(task['worktree']).exists():
                    continue
                diagnosis = operation_diagnosis(task['worktree'], operation)
                operations[name] = diagnosis
                if diagnosis['status'] in ('partial-update', 'conflict', 'indeterminate'):
                    errors.append(name + ': ' + diagnosis['status'] + '; ' + diagnosis['next_step'])
            except (BranchError, OSError) as exc:
                operations[name] = {'status': 'indeterminate', 'error': str(exc)}
                errors.append(name + ': operation state unavailable')
        return {'ok': not errors, 'errors': errors, 'tasks': list(state['tasks']), 'operations': operations}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ['hook']:
            return hook(argv[1], argv[2:])
        parser = argparse.ArgumentParser(description=__doc__)
        sub = parser.add_subparsers(dest='command', required=True)
        for name in ('install', 'begin', 'check', 'retire', 'prepare-merge', 'allow-cherry-pick', 'allow-tag-push'):
            p = sub.add_parser(name)
            p.add_argument('--repo', default='.')
            p.add_argument('--json', action='store_true')
            if name == 'install':
                p.add_argument('--remote', required=True)
            elif name == 'begin':
                p.add_argument('--mode', choices=('new', 'adopt', 'continue'), required=True)
                p.add_argument('--task', required=True)
                for flag in ('request', 'branch', 'worktree', 'base', 'into', 'depends-on'):
                    p.add_argument('--' + flag)
                p.add_argument('--sync', action='store_true')
            elif name in ('retire', 'prepare-merge'):
                p.add_argument('--task', required=True)
            elif name == 'allow-cherry-pick':
                for flag in ('commit', 'approval', 'reason'):
                    p.add_argument('--' + flag, required=True)
            elif name == 'allow-tag-push':
                for flag in ('remote', 'tag', 'commit', 'approval'):
                    p.add_argument('--' + flag, required=True)
        args = parser.parse_args(argv)
        value = {'install': install, 'begin': begin, 'check': check, 'retire': retire,
                 'prepare-merge': prepare_merge, 'allow-cherry-pick': allow_pick,
                 'allow-tag-push': allow_tag_push}[args.command](args)
        if args.command == 'check' and not args.json:
            print('OK: registered worktrees and hooks agree' if value['ok'] else 'FAIL: ' + '; '.join(value['errors']))
        else:
            print(json.dumps(value, ensure_ascii=True, sort_keys=True))
        return 1 if value.get('ok') is False else 0
    except (BranchError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'ok': False, 'errors': [str(exc)]}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
