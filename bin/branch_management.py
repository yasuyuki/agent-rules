#!/usr/bin/env python3
"""Local work/branch registration and Git reference enforcement.

State and one-use authorizations belong to the Git common directory. They are
not portable project records. No command resets, stashes or deletes user work.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ('prepare-commit-msg', 'reference-transaction', 'pre-push')


class BranchError(RuntimeError):
    pass


def git(repo, *args, optional=False):
    p = subprocess.run(['git', '-C', str(repo), *args], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, encoding='utf-8')
    if p.returncode and not optional:
        raise BranchError(p.stderr.strip() or 'git failed: ' + ' '.join(args))
    return p.stdout.strip() if p.returncode == 0 else None


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
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
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
    # OS locks disappear on process death; never call a Git mutation here.
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


def installation_errors(repo, directory, state, *, source_check=True):
    require(state)
    errors = []
    if git(repo, 'remote', 'get-url', state['remote'], optional=True) != state['remote_url']:
        errors.append('registered remote URL changed')
    if git(repo, 'config', '--get', 'core.hooksPath', optional=True) != str(directory / 'hooks'):
        errors.append('core.hooksPath differs from registered hooks')
    for key, value in [('agentBranch.python', state['python']), ('agentBranch.source', state['source'])]:
        if git(repo, 'config', '--get', key, optional=True) != value:
            errors.append(key + ' differs from installation')
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


def same_checkout(repo, path, name):
    return (top(path) == str(Path(path).resolve()) and branch(path) == name
            and common(path).resolve() == common(repo).resolve())


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
                state['source_hashes'] = {name: digest(ROOT / name) for name in ('bin/branch_management.py', 'hooks/branch-hook')}
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
                     'source_hashes': {name: digest(ROOT / name) for name in ('bin/branch_management.py', 'hooks/branch-hook')},
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
    if permit.get('pick'):
        state['picks'].pop(name + ':' + permit['pick'], None)
    if permit.get('merge'):
        source = state['tasks'][permit['merge']]
        source['integrated'] = {'source': permit['parents'][1], 'destination': name, 'commit': new}
        state['merges'].pop(name, None)
    state['permits'].pop(name, None)


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
                old = task['tip']
                new = oid(repo, 'refs/remotes/' + state['remote'] + '/' + task['branch'])
                if old == new:
                    raise BranchError('same-branch remote has no new commit to import')
                if not ancestor(repo, old, new):
                    raise BranchError('same-branch remote update is not a fast-forward')
                state['permits'][task['branch']] = {'kind': 'import', 'old': old, 'new': new,
                                                      'worktree': task['worktree']}
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
        if not done or done['source'] != oid(repo, 'refs/heads/' + parent['branch']) or not ancestor(repo, done['commit'], ticket['old']):
            raise BranchError('dependency must be integrated first into destination history')


def prepare_merge(args):
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
        state['picks'][key] = {'approval': args.approval, 'reason': args.reason,
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
    permit = {'kind': 'commit', 'old': old, 'worktree': top(repo)}
    if merge_head.exists():
        heads = merge_head.read_text().splitlines()
        ticket = state['merges'].get(name)
        if not ticket or heads != [ticket['source']]:
            raise BranchError('merge is not authorized by prepare-merge')
        merge_valid(repo, state, name, ticket)
        parents += heads
        permit['merge'] = ticket['task']
    elif name == state['default']:
        raise BranchError('default branch is integration-only')
    if pick:
        permission = state['picks'].get(name + ':' + pick)
        if not permission or permission['old'] != old or permission['worktree'] != top(repo):
            raise BranchError('cherry-pick needs an exact user-approved exception')
        permit['pick'] = pick
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
    if phase == 'prepared' and any(r[2] == 'HEAD' for r in rows) and not updates:
        try:
            branch(repo)
        except BranchError:
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


def validate_push(repo, directory, state, rows, remote):
    assert_install(repo, directory, state)
    if remote != state['remote']:
        raise BranchError('push remote differs from registration')
    reconcile(repo, state)
    for local, value, target, previous in rows:
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


def push_check(repo, remote, destination):
    """Shared preflight check; legacy, non-installed repositories remain usable."""
    directory = common(repo) / 'agent-branches'
    if not directory.exists() and not git(repo, 'config', '--get', 'agentBranch.source', optional=True):
        return
    with locked(repo) as (directory, state):
        validate_push(repo, directory, state,
                      [('HEAD', oid(repo, 'HEAD'), 'refs/heads/' + destination, '0' * len(oid(repo, 'HEAD')))], remote)


def hook(name, args):
    repo = Path.cwd()
    data = sys.stdin.buffer.read() if name in ('reference-transaction', 'pre-push') else b''
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
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
    if not committed:
        code = legacy()
        if code:
            return code
    with locked(repo) as (directory, state):
        assert_install(repo, directory, state)
        reconcile(repo, state)
        if name == 'prepare-commit-msg':
            prepare_commit(repo, directory, state)
        elif name == 'reference-transaction':
            transaction(repo, directory, state, args[0], data)
        elif name == 'pre-push':
            rows = [line.split() for line in data.decode().splitlines()]
            if any(len(row) != 4 for row in rows):
                raise BranchError('invalid push input')
            validate_push(repo, directory, state, rows, args[0])
            save(directory, state)
        else:
            raise BranchError('unknown hook')
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
        return {'ok': not errors, 'errors': errors, 'tasks': list(state['tasks'])}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ['hook']:
            return hook(argv[1], argv[2:])
        parser = argparse.ArgumentParser(description=__doc__)
        sub = parser.add_subparsers(dest='command', required=True)
        for name in ('install', 'begin', 'check', 'prepare-merge', 'allow-cherry-pick'):
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
            elif name == 'prepare-merge':
                p.add_argument('--task', required=True)
            elif name == 'allow-cherry-pick':
                for flag in ('commit', 'approval', 'reason'):
                    p.add_argument('--' + flag, required=True)
        args = parser.parse_args(argv)
        value = {'install': install, 'begin': begin, 'check': check,
                 'prepare-merge': prepare_merge, 'allow-cherry-pick': allow_pick}[args.command](args)
        if args.command == 'check' and not args.json:
            print('OK: registered worktrees and hooks agree' if value['ok'] else 'FAIL: ' + '; '.join(value['errors']))
        else:
            print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return 1 if value.get('ok') is False else 0
    except (BranchError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'ok': False, 'errors': [str(exc)]}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
