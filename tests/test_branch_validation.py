"""Focused regressions for batched installation reads, using real Git config."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'management', Path(__file__).resolve().parents[1] / 'bin/branch_management.py')
management = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(management)


class InstallationConfigTests(unittest.TestCase):
    def test_batch_preserves_last_value_and_all_scope_semantics(self):
        with tempfile.TemporaryDirectory(prefix='config values ') as temp:
            repo = Path(temp)
            subprocess.run(['git', 'init', '-q', temp], check=True)
            management.git(repo, 'remote', 'add', 'origin', 'https://example.invalid/repo')
            for key in ('gc.packRefs', 'maintenance.pack-refs.enabled'):
                management.git(repo, 'config', key, 'false')
            directory = repo / '.git/agent-branches'
            state = dict(version=1, remote='origin', remote_url='https://example.invalid/repo',
                         python='python path', source='source path', hook_hashes={}, hook_executable={})
            values = [('core.hooksPath', str(directory / 'hooks')),
                      ('agentBranch.python', state['python']), ('agentBranch.source', state['source'])]
            for key, value in values:
                management.git(repo, 'config', '--add', key, 'obsolete value')
                management.git(repo, 'config', '--add', key, '\n ' + value + ' \n')
                self.assertEqual(management.git(repo, 'config', '--get', key), value)
            self.assertEqual(management.installation_errors(repo, directory, state, source_check=False), [])
            global_config = repo / 'global config'
            management.git(repo, 'config', '--file', str(global_config), 'agentBranch.python', state['python'])
            management.git(repo, 'config', '--unset-all', 'agentBranch.python')
            with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(global_config),
                                               'GIT_CONFIG_NOSYSTEM': '1'}):
                self.assertEqual(management.git(repo, 'config', '--get', 'agentBranch.python'), state['python'])
                self.assertEqual(management.installation_errors(repo, directory, state, source_check=False), [])
                management.git(repo, 'config', 'agentBranch.python', 'wrong local value')
                with mock.patch.dict(os.environ, {'GIT_CONFIG_COUNT': '1',
                                                   'GIT_CONFIG_KEY_0': 'agentBranch.python',
                                                   'GIT_CONFIG_VALUE_0': state['python']}):
                    self.assertEqual(management.git(repo, 'config', '--get', 'agentBranch.python'), state['python'])
                    self.assertEqual(management.installation_errors(repo, directory, state, source_check=False), [])
            management.git(repo, 'config', '--add', 'agentBranch.source', 'changed\nsource')
            self.assertIn('agentBranch.source differs from installation',
                          management.installation_errors(repo, directory, state, source_check=False))
            management.git(repo, 'config', '--unset-all', 'agentBranch.source')
            self.assertIn('agentBranch.source differs from installation',
                          management.installation_errors(repo, directory, state, source_check=False))


class DependencyWorktreeLockTests(unittest.TestCase):
    def git(self, *args, cwd=None):
        return subprocess.run(('git', *args), cwd=cwd, text=True, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def linked_worktree(self, root):
        primary = root / 'primary'
        linked = root / 'linked'
        self.git('init', '-q', '--initial-branch=main', primary)
        self.git('config', 'user.name', 'Test User', cwd=primary)
        self.git('config', 'user.email', 'test@example.invalid', cwd=primary)
        (primary / 'README').write_text('base\n', encoding='utf-8')
        self.git('add', 'README', cwd=primary)
        self.git('commit', '-q', '-m', 'base', cwd=primary)
        self.git('worktree', 'add', '-q', linked, cwd=primary)
        lock = Path(self.git('rev-parse', '--path-format=absolute', '--git-path', 'locked',
                             cwd=linked).stdout.strip())
        return linked, lock

    def install_repositories(self, root, count):
        remote = root / 'remote.git'
        seed = root / 'seed'
        self.git('init', '-q', '--bare', '--initial-branch=main', remote)
        self.git('clone', '-q', remote, seed)
        self.git('config', 'user.name', 'Test User', cwd=seed)
        self.git('config', 'user.email', 'test@example.invalid', cwd=seed)
        (seed / 'README').write_text('base\n', encoding='utf-8')
        self.git('add', 'README', cwd=seed)
        self.git('commit', '-q', '-m', 'base', cwd=seed)
        self.git('push', '-q', '-u', 'origin', 'main', cwd=seed)
        repositories = [root / ('consumer-' + str(index)) for index in range(count)]
        for repo in repositories:
            self.git('clone', '-q', remote, repo)
        return repositories

    def test_concurrent_installs_accept_the_peer_completed_lock(self):
        with tempfile.TemporaryDirectory(prefix='dependency lock ') as temporary:
            root = Path(temporary)
            linked, lock = self.linked_worktree(root)
            repositories = self.install_repositories(root, 3)
            barrier = threading.Barrier(len(repositories))
            native_git = management.git

            def race_to_lock(repo, *args, **kwargs):
                if args[:2] == ('worktree', 'lock'):
                    barrier.wait()
                return native_git(repo, *args, **kwargs)

            def install(repo):
                try:
                    return management.install(SimpleNamespace(repo=repo, remote='origin'))
                except BaseException:
                    barrier.abort()
                    raise

            with mock.patch.object(management, 'dependency_worktrees', return_value=[(linked, lock)]):
                with mock.patch.object(management, 'git', side_effect=race_to_lock):
                    with ThreadPoolExecutor(max_workers=len(repositories)) as workers:
                        futures = [workers.submit(install, repo) for repo in repositories]
                    for future in futures:
                        self.assertEqual(future.result(), {'installed': True, 'default': 'main'})
            self.assertEqual(lock.read_bytes(), b'branch management dependency\n')

    def test_existing_lock_is_preserved_without_another_git_lock(self):
        with tempfile.TemporaryDirectory(prefix='dependency lock ') as temporary:
            linked, lock = self.linked_worktree(Path(temporary))
            management.git(linked, 'worktree', 'lock', '--reason', 'existing consumer', linked)
            before = lock.read_bytes()
            with mock.patch.object(management, 'git', side_effect=AssertionError('must not relock')):
                management.lock_dependency_worktree(linked, lock)
            self.assertEqual(lock.read_bytes(), before)

    def test_lock_failure_without_a_completed_lock_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='dependency lock ') as temporary:
            linked, lock = self.linked_worktree(Path(temporary))
            with mock.patch.object(management, 'git', side_effect=management.BranchError('lock failed')):
                with self.assertRaisesRegex(management.BranchError, 'lock failed'):
                    management.lock_dependency_worktree(linked, lock)
            lock.mkdir()
            with mock.patch.object(management, 'git', side_effect=management.BranchError('lock failed')):
                with self.assertRaisesRegex(management.BranchError, 'lock failed'):
                    management.lock_dependency_worktree(linked, lock)


if __name__ == '__main__':
    unittest.main()
