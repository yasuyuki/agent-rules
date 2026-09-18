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
from datetime import datetime, timezone

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
        # Persist the renamed evidence before reporting authorization success.
        # Windows has no portable Python directory-fsync equivalent.
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
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


def lock_dependency_worktree(root, lock):
    """Lock a dependency checkout, tolerating only a concurrent successful lock."""
    if lock.is_file():
        return
    try:
        git(root, 'worktree', 'lock', '--reason', 'branch management dependency', root)
    except BranchError:
        # A second installer can pass the pre-check just before its peer locks
        # this linked worktree.  Accept only that completed postcondition; all
        # other native Git failures remain installation failures.
        if not lock.is_file():
            raise


def installation_errors(repo, directory, state, *, source_check=True, packing_check=True):
    require(state)
    errors = []
    if packing_check:
        for key in ('gc.packRefs', 'maintenance.pack-refs.enabled'):
            value = git(repo, 'config', '--bool', '--get', key, optional=True)
            if value != 'false':
                raw = git(repo, 'config', '--get', key, optional=True)
                problem = 'missing' if raw is None else 'invalid or enabled'
                errors.append(key + ' is ' + problem + '; expected false; repair with branch install')
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
    for item in worktree_records(repo):
        return item['worktree']
    raise BranchError('repository has no working tree')


def worktree_records(repo):
    records = []
    for block in git_bytes(repo, 'worktree', 'list', '--porcelain', '-z').split(b'\0\0'):
        item = {}
        for field in block.split(b'\0'):
            if field:
                key, _, value = os.fsdecode(field).partition(' ')
                item[key] = value
        if 'worktree' in item:
            item['worktree'] = str(Path(item['worktree']).absolute())
            records.append(item)
    return records


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
    packing_scopes = {}
    for key in ('gc.packRefs', 'maintenance.pack-refs.enabled'):
        scoped = git(repo, 'config', '--show-scope', '--get', key, optional=True)
        scope = (scoped or '').partition('\t')[0]
        if scope == 'command':
            raise BranchError(key + ' has a command-scope override; remove it before branch install')
        packing_scopes[key] = '--worktree' if scope == 'worktree' else '--local'
    # Lock before reading/pinning source bytes. Preserve existing locks and never
    # auto-unlock on rebind: another repository may still consume this checkout.
    for root, lock in dependency_worktrees(ROOT, sys.executable):
        lock_dependency_worktree(root, lock)
    with locked(repo, create=True) as (directory, state):
        target = directory / 'hooks'
        dispatcher = ROOT / 'hooks/branch-hook'
        if state:
            require(state)
            if state['remote'] != args.remote or state['default'] != default:
                raise BranchError('remote/default changed; resolve registration before installing')
            if not state.get('installing'):
                # Only install owns repair of the two packing settings. Keep
                # remote, installed hook and source-binding checks intact.
                errors = installation_errors(repo, directory, state, source_check=False,
                                             packing_check=False)
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
        for key, scope in packing_scopes.items():
            git(repo, 'config', '--local', '--replace-all', key, 'false')
            if scope == '--worktree':
                git(repo, 'config', scope, '--replace-all', key, 'false')
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
    record = state.get('operations', {}).get(name)
    if (record and record['id'] == permit.get('operation_id') and record['before']['head'] == permit['old']
            and ((record['kind'] == 'sync' and permit['kind'] == 'import' and record['source'] == new)
                 or (record['kind'] == 'merge' and permit.get('merge') and record['source'] == permit['parents'][1])
                 or (record['kind'] == 'pick' and permit.get('pick') == record['source']))):
        record['completed'] = new
        if record.get('attempt'):
            record['attempt']['status'] = 'reference-committed'
    if permit.get('pick'):
        state['picks'].pop(name + ':' + permit['pick'], None)
    if permit.get('merge'):
        source = state['tasks'][permit['merge']]
        source['integrated'] = {'source': permit['parents'][1], 'destination': name, 'commit': new}
        state['merges'].pop(name, None)
    state['permits'].pop(name, None)


def creation_snapshot(path, index):
    """Fingerprint physical files and the real index without invoking Git filters."""
    path = Path(path)
    files = {}
    for current, directories, names in os.walk(path, followlinks=False):
        for name in directories + names:
            item = Path(current) / name
            mode = item.lstat().st_mode
            relative = item.relative_to(path).as_posix()
            if stat.S_ISLNK(mode):
                value = os.readlink(item)
            elif stat.S_ISREG(mode):
                value = digest(item)
            elif stat.S_ISDIR(mode):
                value = None
            else:
                raise BranchError('interrupted creation has an unsupported file; preserve and inspect')
            files[relative] = (mode, value)
    return digest(index), files


def verify_creation_checkout(repo, task, expected):
    path, name = task['worktree'], task['branch']
    if (Path(path).absolute() != Path(path).resolve() or not same_checkout(repo, path, name)
            or oid(repo, 'refs/heads/' + name) != expected):
        raise BranchError('interrupted creation has a conflicting checkout; preserve and inspect')
    index = Path(git(path, 'rev-parse', '--path-format=absolute', '--git-path', 'index'))
    before = creation_snapshot(path, index)
    # POSIX execution bits remain part of Q even if normal status ignores them.
    # Optional index refreshes must not write the user's real index.
    mode_check = ('-c', 'core.filemode=true') if os.name != 'nt' else ()
    if git(path, '--no-optional-locks', *mode_check, 'status', '--porcelain',
           '--untracked-files=all', '--ignored'):
        raise BranchError('interrupted creation has changed content; preserve and inspect')
    # A fresh, private index has neither assume-unchanged nor skip-worktree
    # flags. Compare the actual checkout to Q without rewriting the user index.
    with tempfile.TemporaryDirectory(prefix='creation-index-',
                                     dir=common(repo) / 'agent-branches') as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / 'index'))
        git(path, *mode_check, '-c', 'core.sparseCheckout=false', 'read-tree', expected, env=env)
        git(path, *mode_check, 'update-index', '--refresh', optional=True, env=env)
        if git(path, *mode_check, 'diff-files', '--quiet', '--ignore-submodules=none',
               optional=True, env=env) is None:
            raise BranchError('interrupted creation has changed tracked content; preserve and inspect')
    if creation_snapshot(path, index) != before:
        raise BranchError('interrupted creation changed during validation; preserve and inspect')
    return index, before


def begin(args):
    repo = Path(args.repo).resolve()
    creation = None
    if args.from_remote and args.mode != 'adopt':
        raise BranchError('--from-remote is only valid for adoption')
    if args.sync and args.mode != 'continue':
        raise BranchError('--sync is only valid for continuation')
    if not args.task.strip():
        raise BranchError('work identifier cannot be empty')
    inputs = None
    if args.sync:
        with locked(repo) as (directory, state):
            assert_install(repo, directory, state)
            if args.task not in state['tasks']:
                raise BranchError('unknown work identifier')
            task = state['tasks'][args.task]
            if top(repo) != task['worktree'] or task.get('creating'):
                raise BranchError('sync must be prepared in its registered completed worktree')
            source = oid(repo, 'refs/remotes/' + state['remote'] + '/' + task['branch'])
        inputs = operation_inputs(repo, 'sync', source)
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
                if args.sync:
                    raise BranchError('finish interrupted creation before --sync')
                creation = task
            else:
                # Inspect named worktree without inheriting hook-local Git environment.
                if not same_checkout(repo, task['worktree'], task['branch']):
                    raise BranchError('registered worktree has changed')
                if oid(repo, 'refs/heads/' + task['branch']) != task['tip']:
                    raise BranchError('registered branch tip has changed outside enforcement')
            if args.sync:
                old = task['tip']
                new = oid(repo, 'refs/remotes/' + state['remote'] + '/' + task['branch'])
                if old == new:
                    raise BranchError('same-branch remote has no new commit to import')
                if not ancestor(repo, old, new):
                    raise BranchError('same-branch remote update is not a fast-forward')
                if not same_checkout(repo, repo, task['branch']) or top(repo) != task['worktree']:
                    raise BranchError('sync must be prepared in its registered worktree')
                record = prepare_operation(repo, directory, state, task, 'sync', new, inputs)
                state['permits'][task['branch']] = {'kind': 'import', 'old': old, 'new': new,
                                                      'operation_id': record['id'], 'worktree': task['worktree']}
        else:
            if args.task in tasks:
                raise BranchError('work already registered; use --mode continue')
            if not args.request or not args.branch or not args.worktree:
                raise BranchError('new/adopt requires --request, --branch and --worktree')
            git(repo, 'check-ref-format', '--branch', args.branch)
            if args.from_remote and os.path.lexists(args.worktree):
                raise BranchError('remote adoption requires an absent worktree path')
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
                if args.from_remote:
                    if git(repo, 'rev-parse', '--verify', 'refs/heads/' + args.branch, optional=True):
                        raise BranchError('remote adoption requires an absent local branch')
                    tip = oid(repo, 'refs/remotes/' + state['remote'] + '/' + args.branch)
                    advertised = git(repo, 'ls-remote', '--refs', state['remote'],
                                     'refs/heads/' + args.branch).split()
                    if advertised != [tip, 'refs/heads/' + args.branch]:
                        raise BranchError('fetch remote branch before adoption: tracking tip differs from advertised commit')
                else:
                    tip = oid(repo, 'refs/heads/' + args.branch)
                if not ancestor(repo, base, tip):
                    raise BranchError('adoption base is not an ancestor of branch')
                remote_tip = git(repo, 'rev-parse', '--verify', 'refs/remotes/' + state['remote'] + '/' + args.branch, optional=True)
                remote_base = remote_tip or oid(repo, 'refs/remotes/' + state['remote'] + '/' + state['default'])
                if not ancestor(repo, base, remote_base):
                    raise BranchError('adoption base does not agree with remote history')
                if not args.from_remote and not same_checkout(repo, path, args.branch):
                    raise BranchError('adoption checkout does not match branch/worktree')
            task = {'request': args.request, 'branch': args.branch, 'worktree': path,
                    'base': base, 'depends_on': args.depends_on, 'into': into, 'tip': tip}
            tasks[args.task] = task
            if args.mode == 'new' or args.from_remote:
                task['retirement_guarded'] = True
                task['creating'] = True
                if args.from_remote:
                    task['creation_tip'] = tip
                state['permits'][args.branch] = {'kind': 'create', 'old': '0' * len(tip), 'new': tip,
                                                 'worktree': path}
                creation = task
        save(directory, state)
        output = {'task': args.task, **task}
    if creation:
        # Registration survives failure. Continue retries rather than cleaning up.
        name = creation['branch']
        expected = creation.get('creation_tip', creation['tip'])
        if creation['tip'] != expected:
            raise BranchError('interrupted creation tip changed from its recorded intent; preserve and inspect')
        existing = git(repo, 'rev-parse', '--verify', 'refs/heads/' + name, optional=True)
        if existing is not None and existing != expected:
            raise BranchError('interrupted creation has a conflicting branch tip; preserve and inspect')
        if Path(creation['worktree']).absolute() != Path(creation['worktree']).resolve():
            raise BranchError('interrupted creation has a conflicting symlink; preserve and inspect')
        if not Path(creation['worktree']).exists():
            if existing:
                git(repo, 'worktree', 'add', creation['worktree'], name)
            else:
                git(repo, 'worktree', 'add', '-b', name, creation['worktree'], expected)
        # Git content comparison can invoke configured filters. Do it outside
        # the registration lock and before config writes; only read physical
        # state while finalizing, including changes during those writes.
        index, verified = verify_creation_checkout(repo, creation, expected)
        git(creation['worktree'], 'config', 'branch.' + name + '.remote', state['remote'])
        git(creation['worktree'], 'config', 'branch.' + name + '.merge', 'refs/heads/' + name)
        with locked(repo) as (directory, current):
            resumed = current['tasks'][args.task]
            if (resumed['tip'] != expected or
                    resumed.get('creation_tip') != creation.get('creation_tip')):
                raise BranchError('interrupted creation tip changed from its recorded intent; preserve and inspect')
            path = resumed['worktree']
            if (Path(path).absolute() != Path(path).resolve() or not same_checkout(repo, path, name) or
                    oid(path, 'HEAD') != expected or creation_snapshot(path, index) != verified):
                raise BranchError('interrupted creation changed after validation; preserve and inspect')
            resumed.pop('creating', None)
            resumed.pop('creation_tip', None)
            save(directory, current)
            output = {'task': args.task, **current['tasks'][args.task]}
    return output


def retirement_operation_identity(task, key, operation):
    return {'task': key, 'branch': task['branch'], 'tip': task['tip'],
            'operation_task': operation.get('task'),
            'id': operation.get('id'), 'kind': operation.get('kind'),
            'source': operation.get('source'),
            'before_branch': operation.get('before', {}).get('branch'),
            'before_head': operation.get('before', {}).get('head')}


def retirement_checks(repo, state, key, *, requesting=False):
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
    if not requesting and top(repo) == path:
        raise BranchError('retire from another checkout of this repository')
    if not requesting and any(within(value, path) for value in (Path.cwd(), ROOT, sys.executable)):
        raise BranchError('retire outside the active working directory and cleanup source/runtime')
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
    operation = state.get('operations', {}).get(name)
    if (operation and not operation.get('completed') and not operation.get('preflight_rejected')
            and (operation.get('separate_changes')
                 or operation.get('retirement_verified') != retirement_operation_identity(task, key, operation))):
        raise BranchError('unfinished Git operation evidence remains; resolve it before retirement')
    if os.path.lexists(path):
        retirement_identity(path)
        if not same_checkout(repo, path, name):
            raise BranchError('registered worktree has changed')
        if work_snapshot(path)['markers']:
            raise BranchError('active Git operation markers remain; preserve and finish the operation')
        if git(path, 'status', '--porcelain', '--untracked-files=all', '--ignored'):
            raise BranchError('checkout has uncommitted, untracked or ignored files; preserve and inspect')
    return task


def retirement_identity(path):
    """Reject redirected paths and pin the containing filesystem before removal."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if not os.path.lexists(item):
            raise BranchError('retirement path or parent is unavailable: ' + str(item))
        info = item.lstat()
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise BranchError('retirement path crosses a symlink/reparse point: ' + str(item))
    info, parent = path.stat(), path.parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_dev != parent.st_dev or os.path.ismount(path):
        raise BranchError('retirement target is not an ordinary directory on its parent filesystem')
    return {'device': info.st_dev, 'inode': info.st_ino,
            'parent_device': parent.st_dev, 'parent_inode': parent.st_ino}


def retirement_contents(path):
    """Git's ignored status is insufficient for empty directories and nested repos."""
    for current, directories, names in os.walk(path, followlinks=False):
        for name in directories + names:
            item = Path(current) / name
            info = item.lstat()
            if (stat.S_ISLNK(info.st_mode) or
                    getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise BranchError('retirement content contains a link/reparse point: ' + str(item))
            if item != Path(path) / '.git' and name == '.git':
                raise BranchError('retirement content contains a nested repository: ' + str(item))
            if stat.S_ISDIR(info.st_mode) and (os.path.ismount(item) or info.st_dev != Path(path).stat().st_dev):
                raise BranchError('retirement content crosses a filesystem boundary: ' + str(item))
    if git(path, 'ls-files', '--stage').startswith('160000 ') or b'\x00160000 ' in git_bytes(path, 'ls-files', '--stage', '-z'):
        raise BranchError('retirement content contains a submodule')
    # Reuse the existing fresh-index check, including assume-unchanged and
    # skip-worktree protection, without modifying the user's index.
    verify_creation_checkout(path, {'worktree': str(path), 'branch': branch(path)}, oid(path, 'HEAD'))


def process_identity(pid):
    """Return a creation identity, None for a dead process; uncertainty raises."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return None
            raise BranchError('cannot inspect session process: ' + str(pid))
        try:
            values = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
                raise BranchError('cannot inspect session creation time')
            return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        data = Path('/proc', str(pid), 'stat').read_text()
        fields = data.rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + fields[19]
    except FileNotFoundError:
        if Path('/proc').is_dir():
            return None
        raise BranchError('process identity inspection is unavailable')


def active_leases(task):
    remaining = {}
    for token, lease in task.get('leases', {}).items():
        if process_identity(lease['owner_pid']) == lease['owner_identity']:
            remaining[token] = lease
            continue
        if 'child_pid' not in lease:
            # The supervisor may have died between spawn and attachment.
            remaining[token] = lease
            continue
        if lease['child_identity'] is not None and process_identity(lease['child_pid']) == lease['child_identity']:
            remaining[token] = lease
            continue
        if lease.get('process_group'):
            try:
                os.killpg(lease['process_group'], 0)
                remaining[token] = lease
            except ProcessLookupError:
                pass
        elif lease.get('windows_job'):
            job_active = windows_job_active(lease, token)
            if job_active is None:
                raise BranchError('Windows job name is unavailable; descendant release is unknown; '
                                  'confirm external users and explicitly release lease ' + token)
            if job_active:
                remaining[token] = lease
        elif not lease.get('released'):
            # Without a process group/job completion proof descendants are unknown.
            remaining[token] = lease
    task['leases'] = remaining
    return remaining


def windows_session_id():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    session = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        raise BranchError('cannot establish the current Windows session')
    return session.value


def windows_job_active(lease, token):
    """Return True (alive), False (queried empty), or None (name unavailable).

    Closing the last handle can make a job name unavailable while associated
    processes still run. An absent name is never proof of descendant exit.
    """
    if os.name != 'nt' or lease.get('windows_session') != windows_session_id():
        raise BranchError('Windows session differs from the retirement lease')
    if lease['windows_job'] != 'Local\\agent-rules-retirement-' + token:
        raise BranchError('Windows retirement job name differs from the lease token')
    import ctypes
    from ctypes import wintypes
    class Accounting(ctypes.Structure):
        _fields_ = [('times', ctypes.c_int64 * 4), ('page_faults', wintypes.DWORD),
                    ('total', wintypes.DWORD), ('active', wintypes.DWORD), ('terminated', wintypes.DWORD)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenJobObjectW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenJobObjectW.restype = wintypes.HANDLE
    kernel.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenJobObjectW(4, False, lease['windows_job'])
    if not handle:
        if ctypes.get_last_error() == 2:
            return None
        raise BranchError('cannot inspect the retirement Windows job')
    try:
        info = Accounting()
        if not kernel.QueryInformationJobObject(handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            raise BranchError('cannot inspect retirement Windows job processes')
        return info.active != 0
    finally:
        kernel.CloseHandle(handle)


def acquire_worktree_lease(repo, path=None):
    repo = Path(repo).resolve()
    if not (common(repo) / 'agent-branches/state.json').is_file():
        return None
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        selected = top(path or repo)
        matches = [(key, task) for key, task in state['tasks'].items()
                   if selected == task['worktree']]
        if not matches:
            return None
        if len(matches) != 1:
            raise BranchError('ambiguous registered session worktree')
        key, task = matches[0]
        if task.get('retirement'):
            raise BranchError('worktree has a retirement request; resolve it before resuming work')
        token = uuid.uuid4().hex
        task.setdefault('leases', {})[token] = {'owner_pid': os.getpid(),
            'owner_identity': process_identity(os.getpid())}
        save(directory, state)
        return {'repo': main_worktree(repo), 'task': key, 'token': token}


def attach_worktree_child(lease, pid, *, process_group=None, windows_job=None):
    if lease is None:
        return
    with locked(lease['repo']) as (directory, state):
        value = state['tasks'][lease['task']]['leases'][lease['token']]
        value.update(child_pid=pid, child_identity=process_identity(pid), process_group=process_group)
        if windows_job is not None:
            if os.name != 'nt' or windows_job != 'Local\\agent-rules-retirement-' + lease['token']:
                raise BranchError('Windows job must belong to this lease token')
            value.update(windows_job=windows_job, windows_session=windows_session_id())
        save(directory, state)


def finish_worktree_lease(lease, *, child_exited=True, workspace=None):
    if lease is None:
        return {'ok': True, 'retired': [], 'pending': []}
    repo = lease['repo']
    with locked(repo) as (directory, state):
        task = state['tasks'][lease['task']]
        value = task['leases'][lease['token']]
        if value['owner_pid'] != os.getpid() or value['owner_identity'] != process_identity(os.getpid()):
            raise BranchError('session lease belongs to another supervisor')
        if child_exited:
            if value.get('process_group'):
                try:
                    os.killpg(value['process_group'], 0)
                except ProcessLookupError:
                    task['leases'].pop(lease['token'])
            else:
                task['leases'].pop(lease['token'])
        save(directory, state)
    return retry_pending(repo, workspace=workspace)


def check_retirement_result(reference, path):
    if not reference.startswith(('https://', 'http://')):
        result_path = Path(reference).resolve()
        if within(result_path, path) or not result_path.is_file():
            raise BranchError('result reference must be an existing file outside the retirement worktree')


def request_retirement(directory, state, key, args):
    task = state['tasks'].get(key)
    if task is None:
        raise BranchError('unregistered work item: ' + str(key))
    if task.get('retirement'):
        return
    if not getattr(args, 'users_released', False) or not getattr(args, 'result_ref', None):
        raise BranchError('new retirement requires --users-released and --result-ref outside the worktree')
    path = task['worktree']
    if task['branch'] == state['default'] or Path(path).resolve() == Path(main_worktree(args.repo)).resolve():
        raise BranchError('the default branch and repository working tree are not retired')
    if not task.get('integrated') or task['integrated']['source'] != task['tip']:
        raise BranchError('work is not integrated into its registered destination')
    check_retirement_result(args.result_ref, path)
    identity = retirement_identity(path)
    task['retirement'] = {'worktree': path, 'branch': task['branch'], 'tip': task['tip'],
        'integration': task.get('integrated'), 'result_ref': args.result_ref,
        'users_released': True, 'identity': identity, 'phase': 'requested',
        'reason': 'waiting for safety checks and managed session release'}
    save(directory, state)


def perform_retirement(repo, directory, state, key):
    task = state['tasks'][key]
    request = task['retirement']
    try:
        if any(request[field] != task[field] for field in ('worktree', 'branch', 'tip')) or request['integration'] != task.get('integrated'):
            raise BranchError('retirement identity/tip/integration changed; preserve old request for inspection')
        if active_leases(task):
            raise BranchError('managed sessions or unconfirmed child processes still hold the worktree')
        retirement_checks(repo, state, key)
        path = Path(task['worktree'])
        check_retirement_result(request['result_ref'], path)
        parent = path.parent.stat()
        identity = request['identity']
        if [parent.st_dev, parent.st_ino] != [identity['parent_device'], identity['parent_inode']]:
            raise BranchError('retirement parent filesystem changed or is unavailable')
        exists = os.path.lexists(path)
        if exists:
            if retirement_identity(path) != identity:
                raise BranchError('retirement physical directory identity changed')
            retirement_contents(path)
        elif request['phase'] != 'removing':
            raise BranchError('worktree disappeared before authorized removal; cannot confirm filesystem identity')
        request.update(phase='removing', reason='physical removal and postconditions pending')
        save(directory, state)
        listed = next((r for r in worktree_records(repo) if r['worktree'] == str(path)), None)
        if listed:
            if 'locked' in listed:
                raise BranchError('worktree metadata remains locked: ' + listed['locked'])
            git(repo, 'worktree', 'remove', str(path))
        if os.path.lexists(path) or any(r['worktree'] == str(path) for r in worktree_records(repo)):
            raise BranchError('worktree directory or metadata remains after removal')
        if oid(repo, 'refs/heads/' + task['branch']) != task['tip']:
            raise BranchError('retained branch ref changed during removal')
        if [path.parent.stat().st_dev, path.parent.stat().st_ino] != [identity['parent_device'], identity['parent_inode']]:
            raise BranchError('retirement parent filesystem changed during removal')
        check_retirement_result(request['result_ref'], path)
        output = {'task': key, 'branch': task['branch'], 'worktree': str(path), 'tip': task['tip'],
                  'retired': True, 'branch_retained': True, 'result_ref': request['result_ref']}
        state['tasks'].pop(key)
        try:
            save(directory, state)
        except OSError:
            state['tasks'][key] = task
            raise
        return output
    except (BranchError, OSError) as exc:
        request['reason'] = str(exc)
        save(directory, state)
        return {'task': key, 'retired': False, 'pending': True, 'reason': str(exc),
                'leases': list(task.get('leases', {}))}


def retry_pending(repo, workspace=None):
    repo = Path(repo).resolve()
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        reconcile(repo, state)
        results = [perform_retirement(repo, directory, state, key)
                   for key, task in list(state['tasks'].items())
                   if task.get('retirement') and (workspace is None or within(task['worktree'], workspace))]
        return {'ok': all(item['retired'] for item in results),
                'retired': [item for item in results if item['retired']],
                'pending': [item for item in results if not item['retired']]}


def retire(args):
    if getattr(args, 'pending', False):
        if args.task:
            raise BranchError('--pending cannot select a new task')
        return retry_pending(args.repo, getattr(args, 'workspace', None))
    if not args.task:
        raise BranchError('retire requires --task or --pending')
    repo = Path(args.repo).resolve()
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        reconcile(repo, state)
        release = getattr(args, 'release_lease', None)
        if release:
            if not args.users_released or not args.result_ref:
                raise BranchError('lease recovery requires --users-released and --result-ref')
            task = state['tasks'].get(args.task)
            lease = task.get('leases', {}).get(release) if task else None
            if not lease:
                raise BranchError('unknown session lease token')
            if process_identity(lease['owner_pid']) == lease['owner_identity']:
                raise BranchError('session supervisor is still running')
            if lease.get('child_identity') and process_identity(lease['child_pid']) == lease['child_identity']:
                raise BranchError('session child is still running')
            if lease.get('process_group'):
                try:
                    os.killpg(lease['process_group'], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise BranchError('session process group is still running')
            if lease.get('windows_job') and windows_job_active(lease, release) is True:
                raise BranchError('session Windows job still has live processes')
            task['leases'].pop(release)
            task.setdefault('released_leases', {})[release] = {'result_ref': args.result_ref,
                'users_released': True}
            save(directory, state)
        request_retirement(directory, state, args.task, args)
        if getattr(args, 'request', False):
            return {'task': args.task, 'requested': True, 'pending': True,
                    'reason': state['tasks'][args.task]['retirement']['reason']}
        result = perform_retirement(repo, directory, state, args.task)
        result['ok'] = result['retired']
        return result


def migrate_retirement(args):
    """Admit one reviewed historical checkout without inventing integration."""
    if not args.maintenance or not args.users_released or not args.result_ref or not args.consumer:
        raise BranchError('migration requires a fixed consumer set, maintenance interval, user release and result reference')
    repo = Path(args.repo).resolve()
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        reconcile(repo, state)
        task = state['tasks'].get(args.task)
        if task is None:
            raise BranchError('adopt the historical task before retirement migration')
        path = task['worktree']
        check_retirement_result(args.result_ref, path)
        if (str(Path(args.expect_worktree).absolute()) != path or args.expect_tip != task['tip']
                or args.base != task['base']):
            raise BranchError('migration path/tip/base differs from registration')
        retirement_identity(path)
        if not same_checkout(repo, path, task['branch']) or oid(path, 'HEAD') != args.expect_tip:
            raise BranchError('migration checkout differs from its pinned identity')
        commit = oid(repo, args.integration_commit)
        if commit != args.integration_commit or not ancestor(repo, task['base'], task['tip']):
            raise BranchError('migration requires exact historical base and integration commit')
        parents = git(repo, 'show', '-s', '--format=%P', commit).split()
        if (len(parents) != 2 or parents[1] != task['tip']
                or not ancestor(repo, commit, 'refs/heads/' + task['into'])):
            raise BranchError('migration requires a two-parent integration of this exact tip into its destination')
        candidate = {'source': task['tip'], 'destination': task['into'], 'commit': commit}
        if task.get('integrated') and task['integrated'] != candidate:
            raise BranchError('migration cannot replace existing integration evidence')
        consumers = sorted({str(Path(value).resolve()) for value in args.consumer})
        if str(Path(main_worktree(repo)).resolve()) not in consumers:
            raise BranchError('consumer set must include this repository primary checkout')
        # The explicit maintenance interval excludes installs by older clients,
        # which cannot participate in a new lock protocol. Never infer a global
        # consumer inventory by scanning HOME or all drives.
        for consumer in consumers:
            consumer_dir = common(consumer) / 'agent-branches'
            consumer_state = json.loads((consumer_dir / 'state.json').read_text(encoding='utf-8'))
            assert_install(consumer, consumer_dir, consumer_state)
            for value in (consumer_state['source'], consumer_state['python'],
                          str(Path(consumer_state['python']).resolve())):
                if within(value, path):
                    raise BranchError('consumer still references retirement checkout: ' + consumer)
        if active_leases(task):
            raise BranchError('managed session still holds migration checkout')
        retirement_contents(path)
        if work_snapshot(path)['markers']:
            raise BranchError('active Git operation markers prevent retirement migration')
        name = task['branch']
        if (state['permits'].get(name) or state['merges'].get(name)
                or any(ticket['task'] == args.task for ticket in state['merges'].values())
                or any(pick.startswith(name + ':') for pick in state['picks'])):
            raise BranchError('in-flight permission prevents retirement migration')
        operation = state.get('operations', {}).get(name)
        if operation and not operation.get('completed') and not operation.get('preflight_rejected'):
            # Older hook clients could consume a sync permit and update the
            # registered tip without recording the newer operation receipt.
            # Attest only retirement of this exact, clean, integrated checkout;
            # retain the original operation evidence and unknown Git exit.
            if (not isinstance(operation.get('id'), str) or not operation['id']
                    or operation.get('kind') != 'sync' or operation.get('source') != task['tip']
                    or operation.get('task') != args.task or operation.get('separate_changes')
                    or operation.get('before', {}).get('branch') != name
                    or not ancestor(repo, operation.get('before', {}).get('head', ''), task['tip'])):
                raise BranchError('unfinished operation cannot be verified for retirement')
            receipt = retirement_operation_identity(task, args.task, operation)
            if operation.get('retirement_verified') not in (None, receipt):
                raise BranchError('retirement operation receipt changed; preserve evidence')
            operation['retirement_verified'] = receipt
        record = next((item for item in worktree_records(repo) if item['worktree'] == path), None)
        if record is None:
            raise BranchError('migration worktree is not registered with Git')
        if 'locked' in record and record['locked'] != 'branch management dependency':
            raise BranchError('migration does not own this worktree lock: ' + record['locked'])
        # Persist the audited inputs before changing the native lock. A crash
        # keeps the task and repeats the same checks on the next invocation.
        task['retirement_migration'] = {'worktree': path, 'tip': task['tip'],
            'base': task['base'], 'integration': candidate, 'consumers': consumers,
            'result_ref': args.result_ref}
        save(directory, state)
        if 'locked' in record:
            git(repo, 'worktree', 'unlock', path)
        task['retirement_guarded'] = True
        task['integrated'] = candidate
        save(directory, state)
        return {'task': args.task, 'migrated': True, 'consumers': consumers}


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


def tree_entries(repo, tree):
    result = {}
    for row in git_bytes(repo, 'ls-tree', '-r', '-z', tree).split(b'\0'):
        if row:
            info, name = row.split(b'\t', 1)
            mode, kind, value = info.decode().split()
            result[os.fsdecode(name)] = [mode, value]
    return result


def index_entries(entries):
    result = {}
    for row in entries:
        info, name = row.split('\t', 1)
        mode, value, stage = info.split()
        if stage == '0':
            result[name] = [mode, value]
    return result


def attributes(repo, paths):
    if not paths:
        return {}
    p = subprocess.run(['git', '-C', str(repo), 'check-attr', '-z', '--stdin',
                        'text', 'eol', 'filter', 'working-tree-encoding', 'ident', 'merge'],
                       input=b''.join(os.fsencode(n) + b'\0' for n in paths),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise BranchError(p.stderr.decode('utf-8', 'replace'))
    values = p.stdout.split(b'\0')[:-1]
    result = {}
    for i in range(0, len(values), 3):
        name, attr, value = map(os.fsdecode, values[i:i + 3])
        result.setdefault(name, {})[attr] = value
    return result


def work_matches(item, entry):
    if item is None or entry is None:
        return item is None and entry is None
    if item.get('unverified') or item.get('git_mode') != entry[0]:
        return False
    return entry[1] in item.get('blob_ids', [])


def work_snapshot(repo):
    """Raw evidence and semantic index, without refresh, diff, or external filters.

    Built-in text conversion is limited to Git's CRLF handling. Unsupported
    conversions remain unverified, even if their raw bytes happen to match.
    """
    def names(*args):
        return [os.fsdecode(x) for x in git_bytes(repo, *args).split(b'\0') if x]
    entries = names('ls-files', '--stage', '-z')
    indexed = index_entries(entries)
    tracked = [entry.split('\t', 1)[1] for entry in entries]
    untracked = names('ls-files', '--others', '--exclude-standard', '-z')
    attrs = attributes(repo, sorted(set(tracked)))
    autocrlf = git(repo, 'config', '--get', 'core.autocrlf', optional=True)
    symlinks = git(repo, 'config', '--bool', '--get', 'core.symlinks', optional=True) != 'false'
    algorithm = git(repo, 'rev-parse', '--show-object-format')
    files = {}
    for name in sorted(set(tracked + untracked)):
        path = Path(repo) / name
        if any((Path(repo) / Path(name).parents[i]).is_symlink()
               for i in range(len(Path(name).parents) - 1)):
            files[name] = {'kind': 'unsafe-parent', 'unverified': True}
            continue
        try:
            info = path.lstat()
        except FileNotFoundError:
            files[name] = {'kind': 'missing'}
            continue
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            data, kind, git_mode = os.fsencode(os.readlink(path)), 'symlink', '120000'
        elif stat.S_ISREG(info.st_mode):
            data, kind = path.read_bytes(), 'file'
            git_mode = '100755' if os.name != 'nt' and mode & 0o111 else '100644'
            if os.name == 'nt' and name in indexed:
                git_mode = indexed[name][0]
            if not symlinks and indexed.get(name, [None])[0] == '120000':
                git_mode = '120000'
        else:
            files[name] = {'kind': 'directory' if stat.S_ISDIR(info.st_mode) else 'special',
                           'mode': mode, 'unverified': True}
            continue
        attr = attrs.get(name, {})
        unverified = any(attr.get(k, 'unspecified') not in ('unspecified', 'unset')
                         for k in ('filter', 'working-tree-encoding', 'ident'))
        def blob(value):
            return hashlib.new(algorithm, b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()
        blobs = [blob(data)]
        text = attr.get('text', 'unspecified')
        convert = (text != 'unset' and
                   (text in ('set', 'auto') or attr.get('eol') in ('lf', 'crlf') or autocrlf in ('true', 'input')))
        normalized = data.replace(b'\r\n', b'\n')
        # Conservative subset of Git convert.c's automatic text detection:
        # never equate CRLF variants of binary/control/lone-CR data. Explicit
        # text/eol attributes have Git's force-text semantics instead.
        plain_text = all(c >= 32 and c != 127 or c in b'\n\t\b\x1b\f' for c in normalized)
        forced_text = text == 'set' or (text != 'auto' and attr.get('eol') in ('lf', 'crlf'))
        if git_mode != '120000' and convert and (forced_text or plain_text):
            blobs.append(blob(normalized))
        files[name] = {'kind': kind, 'mode': mode, 'sha256': hashlib.sha256(data).hexdigest(),
                       'git_mode': git_mode, 'blob_ids': blobs, 'unverified': unverified}
    markers = {}
    for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'sequencer', 'rebase-merge', 'rebase-apply'):
        path = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-path', name))
        if path.is_file():
            markers[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif path.is_dir():
            markers[name] = 'present'
    head = oid(repo, 'HEAD')
    head_entries = tree_entries(repo, head)
    staged = sorted(n for n in set(indexed) | set(head_entries) if indexed.get(n) != head_entries.get(n))
    unstaged = sorted(n for n in set(tracked) if not work_matches(files.get(n), indexed.get(n)))
    index = Path(git(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'index'))
    return {'head': head, 'branch': branch(repo), 'index': entries,
            'raw_index_sha256': digest(index) if index.exists() else None,
            'worktree': files, 'staged': staged, 'unstaged': unstaged,
            'untracked': untracked, 'markers': markers,
            'unmerged': names('ls-files', '--unmerged', '-z')}


def operation_inputs(repo, kind, source):
    """Compute a pinned tree outside the registry lock; never run from check."""
    before = work_snapshot(repo)
    old = before['head']
    source = oid(repo, source)
    # merge-tree can run custom drivers or renormalizing filters. These are
    # outside this bounded contract, and must be rejected before evaluation.
    if (git(repo, 'config', '--get-regexp', r'^merge\..*\.driver$', optional=True)
            or git(repo, 'config', '--bool', '--get', 'merge.renormalize', optional=True) == 'true'
            or git(repo, 'config', '--get', 'merge.default', optional=True) not in (None, 'text', 'binary')):
        raise BranchError('custom merge drivers/renormalization are not verified for operation preparation')
    if kind == 'sync':
        tree, conflicts = source, []
    else:
        argv = ['merge-tree', '--write-tree', '-z', '--name-only', '--no-messages']
        if kind == 'pick':
            parents = git(repo, 'rev-list', '--parents', '-n', '1', source).split()[1:]
            if len(parents) != 1:
                raise BranchError('pick preparation requires a single-parent commit')
            argv += ['--merge-base=' + parents[0]]
        result = subprocess.run(['git', '-C', str(repo), *argv, old, source],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode not in (0, 1):
            raise BranchError('operation needs Git merge-tree --write-tree/--merge-base: ' +
                              result.stderr.decode('utf-8', 'replace'))
        fields = result.stdout.split(b'\0')
        tree = fields[0].decode().strip()
        conflicts = [os.fsdecode(x) for x in fields[1:] if x]
        if (result.returncode == 1) != bool(conflicts):
            raise BranchError('could not identify exact merge conflict paths')
    expected = tree_entries(repo, tree)
    if work_snapshot(repo) != before or oid(repo, 'HEAD') != old:
        raise BranchError('worktree changed during operation preparation; preserve and retry')
    return {'before': before, 'source': source, 'expected': expected, 'conflicts': conflicts}


def incoming_collisions(repo, before, expected):
    tracked = index_entries(before['index'])
    root = Path(repo)
    for name in expected:
        if name in tracked:
            continue
        path = root / name
        replaced_parent = False
        for parent in path.parents:
            if parent == root:
                break
            relative = parent.relative_to(root).as_posix()
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                if relative not in tracked or relative in expected:
                    raise BranchError('incoming path parent collision with existing data: ' + name)
                replaced_parent = True
        if replaced_parent:
            continue  # Git replaces a tracked parent; never traverse its old link.
        if path.is_dir() and not path.is_symlink():
            # A tracked directory-to-file replacement is legitimate, but every
            # physical descendant must belong to the removed tracked tree.
            for current, directories, files in os.walk(path, followlinks=False):
                for child in directories + files:
                    item = Path(current) / child
                    relative = item.relative_to(root).as_posix()
                    if item.is_dir() and not item.is_symlink():
                        if not any(n.startswith(relative + '/') for n in tracked):
                            raise BranchError('incoming path collision with untracked/ignored directory: ' + relative)
                    elif relative not in tracked or relative in expected:
                        raise BranchError('incoming path collision with untracked/ignored data: ' + relative)
            if not any(n.startswith(name + '/') for n in tracked):
                raise BranchError('incoming path collision with untracked/ignored directory: ' + name)
        elif path.exists() or path.is_symlink():
            raise BranchError('incoming path collision with existing untracked/ignored data: ' + name)



def operation_changes(record, current, *, final=False):
    """Compare authorized content, never just an incoming path whitelist."""
    expected = record['expected']
    actual = index_entries(current['index'])
    before = index_entries(record['before']['index'])
    conflicts = set(record['conflicts'])
    changed = set(current['untracked'])
    for name in set(expected) | set(actual) | set(before):
        if name in conflicts:
            if final and not work_matches(current['worktree'].get(name), actual.get(name)):
                if actual.get(name) is not None or current['worktree'].get(name, {}).get('kind') != 'missing':
                    changed.add(name)
            continue
        options = [expected.get(name)]
        if not final:
            options.append(before.get(name))
        if actual.get(name) not in options:
            changed.add(name)
        item = current['worktree'].get(name)
        if item and item.get('kind') == 'missing':
            item = None
        if not any(work_matches(item, entry) for entry in options):
            changed.add(name)
    return sorted(changed)


def authorized_record(repo, state, kind, source, operation_id):
    name = branch(repo)
    record = state.get('operations', {}).get(name)
    if (not record or record.get('completed') or record.get('preflight_rejected')
            or record['id'] != operation_id or record['kind'] != kind
            or record['source'] != source or record['before']['head'] != oid(repo, 'HEAD')
            or record['task'] != checkout(repo, state)[0]):
        raise BranchError('operation permission does not match retained evidence')
    return record


def operation_markers_match(repo, record, current, *, final=False):
    if record['kind'] == 'sync':
        return not current['markers']
    marker = 'MERGE_HEAD' if record['kind'] == 'merge' else 'CHERRY_PICK_HEAD'
    if not current['markers']:
        return not final
    return (git(repo, 'rev-parse', '--verify', marker, optional=True) == record['source']
            and not set(current['markers']) - {marker, 'sequencer'})


def validate_operation(repo, directory, state, record):
    current = work_snapshot(repo)
    changes = operation_changes(record, current, final=True)
    if (changes or current['unmerged'] or record.get('separate_changes')
            or not operation_markers_match(repo, record, current, final=True)):
        record['separate_changes'] = sorted(set(changes) | set(record.get('separate_changes', [])))
        save(directory, state)
        raise BranchError('operation content/mode differs from expected result; preserve index/worktree and use branch check --json')
    return current


def changed_paths(before, current):
    names = {name for name in set(before['worktree']) | set(current['worktree'])
             if before['worktree'].get(name) != current['worktree'].get(name)}
    # An index-only edit (including chmod --cached) is a separate change too.
    names.update(entry.split('\t', 1)[1]
                 for entry in set(before['index']) ^ set(current['index']))
    return sorted(names)


def operation_diagnosis(repo, state, record):
    current = work_snapshot(repo)
    if work_snapshot(repo) != current:
        raise BranchError('worktree changed during diagnosis; retry read-only check')
    before = record['before']
    head_changed = current['head'] != before['head']
    index_changed = current['index'] != before['index']
    worktree_changed = current['worktree'] != before['worktree']
    name = before['branch']
    permit = state['permits'].get(name, {})
    receipt = record.get('completed')
    if (not receipt and permit.get('operation_id') == record['id']
            and permit.get('old') == before['head'] and permit.get('prepared') == current['head']
            and head_changed):
        receipt = current['head']  # ref observation, never an inferred Git exit
    separate = operation_changes(record, current) if not receipt else []
    separate = sorted(set(separate) | set(record.get('separate_changes', [])))
    authorization, authorization_error = 'available', None
    if record.get('preflight_rejected'):
        authorization = 'not-issued'
    elif receipt:
        authorization = 'consumed'
    else:
        try:
            if record['kind'] == 'sync':
                permission = permit
                if (permit.get('kind') != 'import' or permit.get('new') != record['source']
                        or oid(repo, 'refs/remotes/' + state['remote'] + '/' + name) != record['source']):
                    raise BranchError('same-branch import permission or fetched source changed')
            elif record['kind'] == 'merge':
                permission = state['merges'].get(name, {})
                if permission.get('source') != record['source']:
                    raise BranchError('merge permission changed')
                merge_valid(repo, state, name, permission)
            else:
                permission = state['picks'].get(name + ':' + record['source'], {})
            if permission.get('operation_id') != record['id'] or permission.get('old') != before['head']:
                raise BranchError('operation ID/before differs from permission')
        except BranchError as exc:
            authorization, authorization_error = 'stale', str(exc)
    unverified = sorted(n for n, item in current['worktree'].items() if item.get('unverified'))
    marker = 'MERGE_HEAD' if record['kind'] == 'merge' else 'CHERRY_PICK_HEAD'
    active_source = git(repo, 'rev-parse', '--verify', marker, optional=True)
    markers_match = (record['kind'] != 'sync' and active_source == record['source']
                     and not set(current['markers']) - {marker, 'sequencer'})
    if receipt:
        _, task = task_for(state, name)
        valid_head = (current['branch'] == name and current['head'] in (task['tip'], receipt)
                      and ancestor(repo, receipt, current['head']))
        outcome = 'completed' if valid_head and not current['markers'] and not unverified else 'unknown'
    elif record.get('preflight_rejected') and current == before:
        outcome = 'no-update'
    elif (separate or unverified or current['branch'] != name or head_changed or authorization == 'stale'
          or (current['markers'] and not markers_match)):
        outcome = 'unknown'
    elif current['unmerged']:
        actual_conflicts = {row.split('\t', 1)[1] for row in current['unmerged']}
        outcome = 'conflict' if markers_match and actual_conflicts <= set(record['conflicts']) else 'unknown'
    elif index_changed or worktree_changed or current['markers'] != before['markers']:
        outcome = 'partial-update'
    else:
        outcome = 'no-update'
    action = {
        'no-update': 'No update observed. Use the prepared Git operation only while its source and approval agree.',
        'completed': 'Authorized reference completion is recorded separately from current work. Use branch begin --mode continue for this task to reconcile any interrupted final notification. Git command exit remains unknown.',
        'partial-update': 'Preserve index/worktree. Resume the exact operation through branch begin --mode continue --sync, branch prepare-merge, or branch allow-cherry-pick, as applicable. Resolve an active merge/pick before git commit or git cherry-pick --continue.',
        'conflict': 'Preserve and resolve the reported conflicting paths, then git add and git commit (merge) or git cherry-pick --continue (pick).',
        'unknown': 'Preserve index/worktree and review before/current content identities. Do not reuse permission for separate changes; no automatic recovery is performed.'}[outcome]
    if authorization == 'not-issued':
        action = 'Preflight rejected; no authorization issued. Preserve existing work before fresh preparation.'
    return dict(record, current=current, outcome=outcome, head_changed=head_changed,
                index_changed=index_changed, worktree_changed=worktree_changed,
                separate_changes=separate, unverified_worktree_paths=unverified,
                reference_completion=receipt, current_markers=current['markers'],
                authorization=authorization, authorization_error=authorization_error, next_action=action,
                attribution='Content correspondence is not authorship. Snapshots are evidence, not backups.')


def prepare_operation(repo, directory, state, task, kind, source, inputs, *, resume=False):
    """Bind existing authorization to its original durable observation."""
    before = work_snapshot(repo)
    if (before != inputs['before'] or source != inputs['source']
            or before['head'] != task['tip'] or before['branch'] != task['branch']):
        raise BranchError('operation source/checkout changed during preparation')
    previous = state.get('operations', {}).get(task['branch'])
    dirty = {name: before[name] for name in ('staged', 'unstaged', 'untracked') if before[name]}
    if (previous and not previous.get('completed') and not previous.get('preflight_rejected')
            and not (not before['markers'] and before['head'] == previous['before']['head']
                     and before['index'] == previous['before']['index']
                     and before['worktree'] == previous['before']['worktree']
                     and (previous['kind'] != kind or previous['source'] != source))):
        if (previous['kind'] != kind or previous['source'] != source
                or previous['before']['head'] != before['head'] or previous.get('separate_changes')):
            raise BranchError('active operation differs from retained snapshot; use branch check --json')
        if operation_changes(previous, before) or not operation_markers_match(repo, previous, before):
            raise BranchError('active operation has unrelated dirty changes; preserve them before authorization: ' +
                              json.dumps(dirty, ensure_ascii=True))
        # Exact pending retries, including a rejected fast-forward, retain ID
        # and before. Never bless already-mutated bytes as a new baseline.
        return previous
    record = {'id': uuid.uuid4().hex, 'kind': kind, 'source': source,
              'task': task_for(state, task['branch'])[0], 'before': before,
              'expected': inputs['expected'], 'conflicts': inputs['conflicts'],
              'prepared_at': datetime.now(timezone.utc).isoformat(), 'git_exit': None,
              'snapshot_scope': 'active-operation-authorization' if resume else 'before-git-operation'}
    if resume:
        allowed = {'MERGE_HEAD'} if kind == 'merge' else {'CHERRY_PICK_HEAD', 'sequencer'}
        if operation_changes(record, before, final=True) or set(before['markers']) - allowed:
            raise BranchError('active operation has unrelated dirty staged/unstaged/untracked changes; preserve before authorization')
    else:
        state.setdefault('operations', {})[task['branch']] = record
        try:
            if dirty or before['markers']:
                raise BranchError('operation requires a clean worktree; preserve existing changes: ' +
                                  json.dumps(dict(dirty, markers=before['markers']), ensure_ascii=True))
            incoming_collisions(repo, before, record['expected'])
        except BranchError:
            record['preflight_rejected'] = True
            save(directory, state)
            raise
    state.setdefault('operations', {})[task['branch']] = record
    return record


def observe_reference_attempt(repo, directory, state, data):
    """Save the attempt before a legacy hook can reject or be interrupted."""
    for row in data.decode().splitlines():
        values = row.split()
        if len(values) != 3 or not values[2].startswith('refs/heads/'):
            continue
        old, new, ref = values
        if old == new:
            continue  # No ref transition (including an explicit Git abort).
        record = state.get('operations', {}).get(ref[len('refs/heads/'):])
        if record and not record.get('completed') and not record.get('preflight_rejected') and record['before']['head'] == old:
            if record.get('separate_changes'):
                raise BranchError('operation snapshot is stale; use branch check --json and fresh preparation')
            current = work_snapshot(repo)
            record['attempt'] = {'old': old, 'new': new, 'status': 'in-flight-or-interrupted',
                                 'observed_at': datetime.now(timezone.utc).isoformat()}
            # Changes outside the declared operation footprint are independent
            # evidence. Refuse the ref, but do not imply Git undid earlier writes.
            changed = operation_changes(record, current, final=True)
            if changed:
                record['separate_changes'] = sorted(changed)
                record['attempt']['status'] = 'rejected-separate-changes'
                save(directory, state)
                raise BranchError('worktree changed outside prepared operation; preserve partial state and use branch check --json')
            save(directory, state)


def prepare_merge(args):
    with locked(args.repo) as (directory, state):
        assert_install(args.repo, directory, state)
        _, target = checkout(args.repo, state)
        if args.task not in state['tasks']:
            raise BranchError('unknown source work')
        source = state['tasks'][args.task]
        ticket = {'task': args.task, 'source': oid(args.repo, 'refs/heads/' + source['branch']),
                  'old': oid(args.repo, 'HEAD')}
        merge_valid(args.repo, state, target['branch'], ticket)
    inputs = operation_inputs(args.repo, 'merge', ticket['source'])
    with locked(args.repo) as (directory, state):
        assert_install(args.repo, directory, state)
        reconcile(args.repo, state)
        _, target = checkout(args.repo, state)
        if args.task not in state['tasks']:
            raise BranchError('unknown source work')
        source = state['tasks'][args.task]
        if source['branch'] == target['branch']:
            raise BranchError('cannot merge work into itself')
        ticket = {'task': args.task, 'source': oid(args.repo, 'refs/heads/' + source['branch']),
                  'old': oid(args.repo, 'HEAD')}
        merge_valid(args.repo, state, target['branch'], ticket)
        resume = git(args.repo, 'rev-parse', '--verify', 'MERGE_HEAD', optional=True) == ticket['source']
        record = prepare_operation(args.repo, directory, state, target, 'merge', ticket['source'], inputs, resume=resume)
        ticket['operation_id'] = record['id']
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
    inputs = operation_inputs(args.repo, 'pick', args.commit)
    with locked(args.repo) as (directory, state):
        assert_install(args.repo, directory, state)
        _, task = checkout(args.repo, state)
        if task['branch'] == state['default']:
            raise BranchError('cherry-pick destination must be a topic')
        commit = oid(args.repo, args.commit)
        key = task['branch'] + ':' + commit
        resume = git(args.repo, 'rev-parse', '--verify', 'CHERRY_PICK_HEAD', optional=True) == commit
        record = prepare_operation(args.repo, directory, state, task, 'pick', commit, inputs, resume=resume)
        state['picks'][key] = {'approval': args.approval, 'reason': args.reason, 'operation_id': record['id'],
                               'old': oid(args.repo, 'HEAD'), 'worktree': task['worktree']}
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
    record = None
    if merge_head.exists():
        heads = merge_head.read_text().splitlines()
        ticket = state['merges'].get(name)
        if not ticket or heads != [ticket['source']]:
            raise BranchError('merge is not authorized by prepare-merge')
        merge_valid(repo, state, name, ticket)
        parents += heads
        permit['merge'] = ticket['task']
        record = authorized_record(repo, state, 'merge', ticket['source'], ticket.get('operation_id'))
    elif name == state['default']:
        raise BranchError('default branch is integration-only')
    if pick:
        permission = state['picks'].get(name + ':' + pick)
        if not permission or permission['old'] != old or permission['worktree'] != task['worktree']:
            raise BranchError('cherry-pick needs an exact user-approved exception')
        permit['pick'] = pick
        record = authorized_record(repo, state, 'pick', pick, permission.get('operation_id'))
    if record:
        validate_operation(repo, directory, state, record)
        permit['operation_id'] = record['id']
    permit['parents'] = parents
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
                    record = authorized_record(repo, state, 'sync', new, permit.get('operation_id'))
                    validate_operation(repo, directory, state, record)
                    if new != permit['new'] or new != oid(repo, 'refs/remotes/' + state['remote'] + '/' + name):
                        raise BranchError('remote update differs from registered same-branch import')
                else:
                    lines = git(repo, 'cat-file', '-p', new).split('\n\n', 1)[0].splitlines()
                    trees = [line[5:] for line in lines if line.startswith('tree ')]
                    parents = [line[7:] for line in lines if line.startswith('parent ')]
                    if trees != [permit['tree']] or parents != permit['parents']:
                        raise BranchError('commit tree or parents differ from authorization')
                    if git(repo, 'rev-parse', '--verify', 'CHERRY_PICK_HEAD', optional=True) != permit.get('pick'):
                        raise BranchError('cherry-pick state changed after commit preparation')
                    if permit.get('operation_id'):
                        record = authorized_record(repo, state, 'pick' if permit.get('pick') else 'merge',
                            permit.get('pick') or permit['parents'][1], permit['operation_id'])
                        current = validate_operation(repo, directory, state, record)
                        if index_entries(current['index']) != tree_entries(repo, permit['tree']):
                            raise BranchError('index changed after operation commit preparation')
                    if permit.get('merge'):
                        merge_valid(repo, state, name, state['merges'][name])
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
        if name == 'reference-transaction' and args == ['prepared']:
            observe_reference_attempt(repo, directory, state, data)
        needs_legacy = not committed and previous.exists() and os.access(previous, os.X_OK)
        if not needs_legacy:
            enforce(directory, state)
    if needs_legacy:
        code = legacy()
        if code:
            if name == 'reference-transaction' and args == ['prepared']:
                with locked(repo) as (directory, state):
                    assert_install(repo, directory, state)
                    for row in data.decode().splitlines():
                        values = row.split()
                        if len(values) == 3 and values[2].startswith('refs/heads/'):
                            record = state.get('operations', {}).get(values[2][len('refs/heads/'):])
                            attempt = record.get('attempt', {}) if record else {}
                            if attempt.get('old') == values[0] and attempt.get('new') == values[1]:
                                attempt.update(status='legacy-hook-rejected', hook_exit=code)
                    save(directory, state)
            return code
        with locked(repo) as (directory, state):
            assert_install(repo, directory, state)
            if name == 'reference-transaction' and args == ['prepared']:
                observe_reference_attempt(repo, directory, state, data)
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
        operations = []
        if work_snapshot(args.repo)['markers'] and not state.get('operations', {}).get(branch(args.repo)):
            errors.append('unrecorded active Git operation; before/command exit unknown; preserve index/worktree')
        for record in state.get('operations', {}).values():
            if record['before']['branch'] in [t['branch'] for t in state['tasks'].values() if t['worktree'] == top(args.repo)]:
                try:
                    diagnosis = operation_diagnosis(args.repo, state, record)
                    operations.append(diagnosis)
                    if diagnosis['outcome'] in ('partial-update', 'conflict', 'unknown'):
                        errors.append('operation ' + record['id'] + ': ' + diagnosis['outcome'] + '; ' + diagnosis['next_action'])
                except (BranchError, OSError) as exc:
                    operations.append(dict(record, outcome='unknown', error=str(exc)))
                    errors.append('operation state could not be read: ' + str(exc))
        return {'ok': not errors, 'errors': errors, 'tasks': list(state['tasks']), 'operations': operations}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ['hook']:
            return hook(argv[1], argv[2:])
        parser = argparse.ArgumentParser(description=__doc__)
        sub = parser.add_subparsers(dest='command', required=True)
        for name in ('install', 'begin', 'check', 'retire', 'migrate-retirement', 'prepare-merge', 'allow-cherry-pick', 'allow-tag-push'):
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
                p.add_argument('--from-remote', action='store_true')
            elif name == 'retire':
                p.add_argument('--task')
                p.add_argument('--request', action='store_true', help='record a retirement request without removing the checkout')
                p.add_argument('--pending', action='store_true', help='retry only existing retirement requests')
                p.add_argument('--release-lease', help='recover one dead supervisor lease after external release confirmation')
                p.add_argument('--workspace', help='limit pending requests to this workspace')
                p.add_argument('--result-ref', help='durable result saved outside the checkout')
                p.add_argument('--users-released', action='store_true', help='external users and evidence have been released; managed leases remain enforced')
            elif name == 'migrate-retirement':
                for flag in ('task', 'expect-worktree', 'expect-tip', 'base', 'integration-commit', 'result-ref'):
                    p.add_argument('--' + flag, required=True)
                p.add_argument('--consumer', action='append', required=True, help='complete reviewed consumer set; repeat for every repository')
                p.add_argument('--maintenance', action='store_true', help='consumer installs and external users are excluded during migration')
                p.add_argument('--users-released', action='store_true')
            elif name == 'prepare-merge':
                p.add_argument('--task', required=True)
            elif name == 'allow-cherry-pick':
                for flag in ('commit', 'approval', 'reason'):
                    p.add_argument('--' + flag, required=True)
            elif name == 'allow-tag-push':
                for flag in ('remote', 'tag', 'commit', 'approval'):
                    p.add_argument('--' + flag, required=True)
        args = parser.parse_args(argv)
        value = {'install': install, 'begin': begin, 'check': check, 'retire': retire,
                 'migrate-retirement': migrate_retirement,
                 'prepare-merge': prepare_merge, 'allow-cherry-pick': allow_pick,
                 'allow-tag-push': allow_tag_push}[args.command](args)
        if args.command == 'check' and not args.json:
            print('OK: registered worktrees and hooks agree' if value['ok'] else 'FAIL: ' + '; '.join(value['errors']))
        else:
            print(json.dumps(value, ensure_ascii=True, sort_keys=True))
        if args.command == 'retire' and value.get('ok') is False:
            print(json.dumps(value, ensure_ascii=True, sort_keys=True), file=sys.stderr)
        return 1 if value.get('ok') is False else 0
    except (BranchError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'ok': False, 'errors': [str(exc)]}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
