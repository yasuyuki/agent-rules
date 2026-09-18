"""Interrupted operations and actual push authorization, using real Git fixtures."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import unittest
from unittest.mock import patch
import importlib.util

from test_branch_management import BranchManagementTests, ROOT

spec = importlib.util.spec_from_file_location('branch_management', ROOT / 'bin/branch_management.py')
management = importlib.util.module_from_spec(spec)
spec.loader.exec_module(management)


class RecoveryTests(BranchManagementTests):
    def test_next_sync_preserves_old_hook_observation_without_inventing_completion(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        topic = Path(self.begin('topic', branch='topic')['worktree'])
        self.publish_topic_update(topic)
        self.branch('begin', '--mode', 'continue', '--task', 'topic', '--sync', repo=topic)
        self.git_at(topic, 'merge', '--ff-only', 'origin/topic')
        state = self.read_state()
        old = state['operations']['topic']
        old.pop('completed')
        old.pop('attempt')
        state['operations']['topic'] = old
        self.write_state(state)
        saved = json.loads(json.dumps(old))
        publisher = self.root / 'publisher remote'
        (publisher / 'next').write_text('next remote revision')
        self.git_at(publisher, 'add', 'next')
        self.git_at(publisher, 'commit', '-m', 'next remote revision')
        self.git_at(publisher, 'push', 'origin', 'topic')
        self.git_at(topic, 'fetch', 'origin')
        for field, value in [('task', 'different-task'), ('attempt', {'status': 'rejected'}),
                             ('retirement_verified', {'task': 'topic'}),
                             ('separate_changes', ['personal-data'])]:
            with self.subTest(field=field):
                state['operations']['topic'] = dict(saved, **{field: value})
                self.write_state(state)
                self.branch('begin', '--mode', 'continue', '--task', 'topic', '--sync', repo=topic, ok=False)
                self.assertEqual(self.read_state()['operations']['topic'], state['operations']['topic'])
        state['operations']['topic'] = saved
        self.write_state(state)
        state['tasks']['topic']['retirement'] = {'tip': saved['source']}
        self.write_state(state)
        self.branch('begin', '--mode', 'continue', '--task', 'topic', '--sync', repo=topic, ok=False)
        self.assertEqual(self.read_state()['operations']['topic'], saved)
        state['tasks']['topic'].pop('retirement')
        self.write_state(state)
        (topic / 'personal-data').write_text('preserve')
        self.branch('begin', '--mode', 'continue', '--task', 'topic', '--sync', repo=topic, ok=False)
        self.assertEqual((topic / 'personal-data').read_text(), 'preserve')
        self.assertEqual(self.read_state()['operations']['topic'], saved)
        (topic / 'personal-data').unlink()
        state['permits']['topic'] = {'kind': 'import', 'old': old['before']['head'], 'new': old['source']}
        self.write_state(state)
        self.branch('begin', '--mode', 'continue', '--task', 'topic', '--sync', repo=topic, ok=False)
        state['permits'].pop('topic')
        self.write_state(state)
        for mapping, key, value in [('picks', 'topic:' + old['source'], {'commit': old['source']}),
                                    ('merges', 'main', {'task': 'topic'})]:
            with self.subTest(mapping=mapping):
                state[mapping][key] = value
                self.write_state(state)
                self.branch('begin', '--mode', 'continue', '--task', 'topic', '--sync', repo=topic, ok=False)
                self.assertEqual(self.read_state()['operations']['topic'], saved)
                state[mapping].pop(key)
        self.write_state(state)
        self.branch('begin', '--mode', 'continue', '--task', 'topic', '--sync', repo=topic)
        self.assertEqual(self.read_state()['operations']['topic']['prior_sync_observation'], saved)
        self.git_at(topic, 'merge', '--ff-only', 'origin/topic')
        current = self.read_state()['operations']['topic']
        self.assertEqual(current['prior_sync_observation'], saved)
        self.assertEqual(current['completed'], self.git_at(topic, 'rev-parse', 'HEAD').stdout.strip())
        self.assertNotIn('completed', current['prior_sync_observation'])
        self.assertIsNone(current['prior_sync_observation']['git_exit'])

    def retirement_args(self, task, **extra):
        return type('Args', (), dict(repo=str(self.repo), task=task,
            users_released=True, result_ref='https://example.invalid/saved-result', **extra))()

    def test_retirement_leases_release_last_user_and_keep_branch(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        path = self.integrate('leased')
        tip = self.git('rev-parse', 'leased').stdout.strip()
        first = management.acquire_worktree_lease(self.repo, path)
        second = management.acquire_worktree_lease(self.repo, path)
        management.retire(self.retirement_args('leased', request=True))
        self.assertFalse(management.finish_worktree_lease(first)['ok'])
        self.assertTrue(path.exists())
        final = management.finish_worktree_lease(second)
        self.assertTrue(final['ok'], final)
        self.assertFalse(path.exists())
        self.assertEqual(self.git('rev-parse', 'leased').stdout.strip(), tip)
        self.assertEqual(management.retry_pending(self.repo)['retired'], [])

    def test_retirement_retries_failed_remove_and_failed_final_save(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        path = self.integrate('retry')
        management.retire(self.retirement_args('retry', request=True))
        real_git = management.git
        def fail_remove(repo, *argv, **kwargs):
            if argv[:2] == ('worktree', 'remove'):
                raise management.BranchError('open Windows handle')
            return real_git(repo, *argv, **kwargs)
        with patch.object(management, 'git', side_effect=fail_remove):
            result = management.retry_pending(self.repo)
        self.assertFalse(result['ok'])
        self.assertTrue(path.is_dir())
        self.assertIn('open Windows handle', self.read_state()['tasks']['retry']['retirement']['reason'])
        real_save = management.save
        def fail_final(directory, state):
            if 'retry' not in state['tasks']:
                raise OSError('final registry write failed')
            real_save(directory, state)
        with patch.object(management, 'save', side_effect=fail_final):
            result = management.retry_pending(self.repo)
        self.assertFalse(result['ok'])
        self.assertFalse(path.exists())
        self.assertIn('retry', self.read_state()['tasks'])
        self.assertTrue(management.retry_pending(self.repo)['ok'])
        self.assertNotIn('retry', self.read_state()['tasks'])

    def test_retirement_rejects_changed_tip_and_empty_nested_repository(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        path = self.integrate('changed')
        management.retire(self.retirement_args('changed', request=True))
        nested = path / 'empty' / '.git'
        nested.mkdir(parents=True)
        result = management.retry_pending(self.repo)
        self.assertFalse(result['ok'])
        self.assertTrue(nested.is_dir())
        nested.rmdir()
        nested.parent.rmdir()
        (path / 'later').write_text('must retain')
        self.git_at(path, 'add', 'later')
        self.git_at(path, 'commit', '-m', 'later change')
        result = management.retry_pending(self.repo)
        self.assertFalse(result['ok'])
        self.assertIn('changed', result['pending'][0]['reason'])
        self.assertTrue(path.exists())

    def test_legacy_retirement_migration_validates_exact_merge_and_removes(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        path = self.integrate('legacy')
        state = self.read_state()
        task = state['tasks']['legacy']
        task.pop('retirement_guarded')
        done = task.pop('integrated')
        self.write_state(state)
        self.git('worktree', 'lock', '--reason', 'branch management dependency', str(path))
        args = self.retirement_args('legacy', maintenance=True, consumer=[str(self.repo)],
            expect_worktree=str(path), expect_tip=task['tip'], base=task['base'],
            integration_commit=done['commit'])
        wrong = self.retirement_args('legacy', maintenance=True, consumer=[str(self.repo)],
            expect_worktree=str(path), expect_tip=task['base'], base=task['base'],
            integration_commit=done['commit'])
        with self.assertRaisesRegex(management.BranchError, 'path/tip/base'):
            management.migrate_retirement(wrong)
        self.assertTrue(management.migrate_retirement(args)['migrated'])
        self.assertTrue(management.retire(self.retirement_args('legacy'))['retired'])
        self.assertFalse(path.exists())

    def test_migration_preserves_old_sync_evidence_and_verifies_only_retirement(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        path = self.integrate('old-sync')
        state = self.read_state()
        task = state['tasks']['old-sync']
        operation = {'id': 'old-hook-sync', 'kind': 'sync', 'task': 'old-sync',
                     'source': task['tip'], 'before': {'head': task['base'], 'branch': task['branch']},
                     'git_exit': None}
        state.setdefault('operations', {})[task['branch']] = operation
        self.write_state(state)
        args = self.retirement_args('old-sync', maintenance=True, consumer=[str(self.repo)],
            expect_worktree=str(path), expect_tip=task['tip'], base=task['base'],
            integration_commit=task['integrated']['commit'])
        with self.assertRaisesRegex(management.BranchError, 'unfinished Git operation'):
            management.retirement_checks(self.repo, state, 'old-sync')
        blocker = path / 'personal-data'
        blocker.write_text('preserve')
        with self.assertRaises(management.BranchError):
            management.migrate_retirement(args)
        self.assertEqual(blocker.read_text(), 'preserve')
        blocker.unlink()
        marker = Path(self.git_at(path, 'rev-parse', '--path-format=absolute', '--git-path', 'MERGE_HEAD').stdout.strip())
        marker.write_text(task['base'] + '\n')
        with self.assertRaisesRegex(management.BranchError, 'markers'):
            management.migrate_retirement(args)
        marker.unlink()
        lease = management.acquire_worktree_lease(self.repo, path)
        with self.assertRaisesRegex(management.BranchError, 'session'):
            management.migrate_retirement(args)
        management.finish_worktree_lease(lease)
        state = self.read_state()
        state['permits'][task['branch']] = {'kind': 'import', 'old': task['base'], 'new': task['tip']}
        self.write_state(state)
        with self.assertRaisesRegex(management.BranchError, 'in-flight'):
            management.migrate_retirement(args)
        state['permits'].pop(task['branch'])
        state['operations'][task['branch']]['source'] = task['base']
        self.write_state(state)
        with self.assertRaisesRegex(management.BranchError, 'unfinished operation'):
            management.migrate_retirement(args)
        state['operations'][task['branch']]['source'] = task['tip']
        self.write_state(state)
        self.assertTrue(management.migrate_retirement(args)['migrated'])
        state = self.read_state()
        receipt = state['operations'][task['branch']]
        self.assertNotIn('completed', receipt)
        self.assertNotIn('attempt', receipt)
        self.assertIsNone(receipt['git_exit'])
        receipt['task'] = 'different-work'
        self.write_state(state)
        self.assertFalse(management.retire(self.retirement_args('old-sync'))['ok'])
        self.assertTrue(path.exists())
        state = self.read_state()
        receipt = state['operations'][task['branch']]
        receipt['task'] = 'old-sync'
        receipt['source'] = task['base']
        self.write_state(state)
        self.assertFalse(management.retire(self.retirement_args('old-sync'))['ok'])
        self.assertTrue(path.exists())
        state = self.read_state()
        state['operations'][task['branch']]['source'] = task['tip']
        self.write_state(state)
        self.assertTrue(management.retire(self.retirement_args('old-sync'))['retired'])
        self.assertFalse(path.exists())

    def test_retirement_unknown_crashed_launch_remains_pending(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        path = self.integrate('crashed')
        management.acquire_worktree_lease(self.repo, path)
        management.retire(self.retirement_args('crashed', request=True))
        with patch.object(management, 'process_identity', return_value=None):
            result = management.retry_pending(self.repo)
        self.assertFalse(result['ok'])
        self.assertTrue(path.is_dir())
        self.assertTrue(self.read_state()['tasks']['crashed']['leases'])

    def test_retirement_preserves_a_replaced_directory(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        path = self.integrate('replaced')
        management.retire(self.retirement_args('replaced', request=True))
        original = path.with_name('original preserved')
        path.rename(original)
        path.mkdir()
        (path / 'personal-data').write_text('retain me')
        result = management.retry_pending(self.repo)
        self.assertFalse(result['ok'])
        self.assertEqual((path / 'personal-data').read_text(), 'retain me')
        self.assertTrue((original / 'replaced-change').is_file())
        self.assertIn('replaced', self.read_state()['tasks'])

    @unittest.skipUnless(os.name == 'nt', 'Windows native job lifetime')
    def test_windows_missing_job_requires_confirmed_external_release(self):
        import ctypes
        from ctypes import wintypes
        self.begin('integration', 'adopt', branch='main', into='main')
        path = self.integrate('windows-job')
        lease = management.acquire_worktree_lease(self.repo, path)
        name = 'Local\\agent-rules-retirement-' + lease['token']
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.CreateJobObjectW(None, name)
        self.assertTrue(handle)
        child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], stdin=subprocess.PIPE)
        try:
            self.assertTrue(kernel.AssignProcessToJobObject(handle, int(child._handle)), ctypes.get_last_error())
            management.attach_worktree_child(lease, child.pid, windows_job=name)
            management.retire(self.retirement_args('windows-job', request=True))
            # A crashed supervisor loses its last handle. The name can vanish
            # while a descendant is alive: absence is not proof of death.
            kernel.CloseHandle(handle)
            handle = None
            stored = self.read_state()['tasks']['windows-job']['leases'][lease['token']]
            self.assertIsNone(child.poll())
            self.assertIsNone(management.windows_job_active(stored, lease['token']))
            with patch.object(management, 'process_identity', return_value=None):
                result = management.retry_pending(self.repo)
            self.assertFalse(result['ok'])
            self.assertEqual(result['pending'][0]['leases'], [lease['token']])
            self.assertTrue(path.exists())
            child.communicate(b'finished', timeout=10)
            stored = self.read_state()['tasks']['windows-job']['leases'][lease['token']]
            self.assertIsNone(management.windows_job_active(stored, lease['token']))
            with patch.object(management, 'process_identity', return_value=None):
                self.assertFalse(management.retry_pending(self.repo)['ok'])
                self.assertTrue(management.retire(self.retirement_args(
                    'windows-job', release_lease=lease['token']))['ok'])
            self.assertFalse(path.exists())
        finally:
            if child.poll() is None:
                child.communicate(b'finished', timeout=10)
            if handle:
                kernel.CloseHandle(handle)

    def test_migration_rechecks_multiple_consumers_before_dependency_unlock(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        path = Path(self.begin('supplier', branch='supplier')['worktree'])
        for relative in ('bin/branch_management.py', 'bin/push_preflight.py', 'hooks/branch-hook'):
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.git_at(path, 'add', 'bin', 'hooks')
        self.git_at(path, 'commit', '-m', 'source supplier')
        self.branch('prepare-merge', '--task', 'supplier')
        self.git('merge', '--no-ff', '--no-commit', 'supplier')
        self.git('commit', '-m', 'integrate supplier')
        consumers = [self.root / 'consumer one', self.root / 'consumer two']
        for consumer in consumers:
            self.command('git', 'clone', self.remote, consumer)
            self.command(sys.executable, str(path / 'bin/branch_management.py'), 'install',
                         '--repo', str(consumer), '--remote', 'origin')
        task = self.read_state()['tasks']['supplier']
        args = self.retirement_args('supplier', maintenance=True,
            consumer=[str(self.repo), *(str(value) for value in consumers)],
            expect_worktree=str(path), expect_tip=task['tip'], base=task['base'],
            integration_commit=task['integrated']['commit'])
        self.branch('install', repo=consumers[0])
        with self.assertRaisesRegex(management.BranchError, 'still references'):
            management.migrate_retirement(args)
        self.assertIn('locked', next(row for row in management.worktree_records(self.repo)
                                    if row['worktree'] == str(path)))
        self.branch('install', repo=consumers[1])
        self.assertTrue(management.migrate_retirement(args)['migrated'])
        self.assertTrue(management.retire(self.retirement_args('supplier'))['retired'])
        self.assertFalse(path.exists())

    def test_remote_adopt_interruption_keeps_q_and_rejects_content_conflicts(self):
        seed, base, tip = self.remote_topic()
        path = self.root / 'received'
        args = type('Args', (), dict(repo=str(self.repo), task='incoming', mode='adopt',
                    from_remote=True, sync=False, request='issue-89', branch='incoming',
                    worktree=str(path), base=base, into=None, depends_on=None))()
        real_git = management.git
        def fail_add(repo, *argv, **kwargs):
            if argv[:2] == ('worktree', 'add'):
                raise management.BranchError('fixture interrupted before worktree add')
            return real_git(repo, *argv, **kwargs)
        with patch.object(management, 'git', side_effect=fail_add):
            with self.assertRaisesRegex(management.BranchError, 'fixture interrupted'):
                management.begin(args)
        state = self.read_state()
        self.assertTrue(state['tasks']['incoming']['creating'])
        self.assertEqual(state['permits']['incoming']['new'], tip)
        self.assertFalse(path.exists())
        self.branch('begin', '--mode', 'continue', '--task', 'incoming', '--sync', ok=False)
        (seed / 'advance').write_text('Q2')
        self.git_at(seed, 'add', '.')
        self.git_at(seed, 'commit', '-m', 'Q2')
        self.git_at(seed, 'push', 'origin', 'incoming')
        self.git('fetch', 'origin')
        self.assertNotEqual(self.git('rev-parse', 'origin/incoming').stdout.strip(), tip)
        args.mode, args.from_remote = 'continue', False
        args.base, args.request, args.branch, args.worktree = None, None, None, None
        def fail_config(repo, *argv, **kwargs):
            if argv[:2] == ('config', 'branch.incoming.remote'):
                raise management.BranchError('fixture interrupted after worktree add')
            return real_git(repo, *argv, **kwargs)
        with patch.object(management, 'git', side_effect=fail_config):
            with self.assertRaisesRegex(management.BranchError, 'fixture interrupted'):
                management.begin(args)
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.assertNotIn('incoming', self.read_state()['permits'])
        (path / 'foreign').write_bytes(b'preserve')
        self.branch('begin', '--mode', 'continue', '--task', 'incoming', ok=False)
        self.assertEqual((path / 'foreign').read_bytes(), b'preserve')
        self.assertTrue(self.read_state()['tasks']['incoming']['creating'])
        (path / 'foreign').unlink()
        for _ in range(2):
            self.branch('begin', '--mode', 'continue', '--task', 'incoming')
        task = self.read_state()['tasks']['incoming']
        self.assertEqual((task['base'], task['tip']), (base, tip))
        self.assertNotIn('creating', task)
        self.assertNotIn('incoming', self.read_state()['permits'])

    def test_remote_adopt_cli_git_failure_is_resumable(self):
        seed, base, tip = self.remote_topic()
        receiver = self.root / 'cli receiver'
        self.command('git', 'clone', self.remote, receiver)
        hook = receiver / '.git/hooks/reference-transaction'
        hook.write_text('#!/bin/sh\n'
                        'common=$(git rev-parse --git-common-dir)\n'
                        'if [ "$1" = prepared ] && [ -f "$common/deny-create" ]; then\n'
                        '  echo "fixture denied creation" >&2\n  exit 41\nfi\nexit 0\n',
                        encoding='utf-8', newline='\n')
        hook.chmod(0o755)
        self.branch('install', repo=receiver)
        marker = receiver / '.git/deny-create'
        marker.touch()
        before = ((receiver / '.git/index').read_bytes(),
                  self.git_at(receiver, 'show-ref').stdout, (receiver / 'README').read_bytes())
        result = self.remote_begin(base, repo=receiver, ok=False)
        self.assertIn('fixture denied creation', result.stderr)
        state_path = receiver / '.git/agent-branches/state.json'
        state = json.loads(state_path.read_text())
        self.assertTrue(state['tasks']['incoming']['creating'])
        self.assertEqual(state['permits']['incoming']['new'], tip)
        self.assertEqual(before, ((receiver / '.git/index').read_bytes(),
                         self.git_at(receiver, 'show-ref').stdout, (receiver / 'README').read_bytes()))
        self.assertFalse((self.root / 'received').exists())
        marker.unlink()
        (seed / 'advance').write_text('Q2')
        self.git_at(seed, 'add', '.')
        self.git_at(seed, 'commit', '-m', 'Q2')
        self.git_at(seed, 'push', 'origin', 'incoming')
        self.git_at(receiver, 'fetch', 'origin')
        for _ in range(2):
            self.branch('begin', '--mode', 'continue', '--task', 'incoming', repo=receiver)
        state = json.loads(state_path.read_text())
        self.assertEqual((state['tasks']['incoming']['base'], state['tasks']['incoming']['tip']), (base, tip))
        self.assertEqual(self.git_at(self.root / 'received', 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.assertNotIn('incoming', state['permits'])
        self.assertNotIn('creating', state['tasks']['incoming'])

    def test_remote_adopt_config_failure_preserves_original_intent(self):
        seed, base, tip = self.remote_topic()
        lock = self.repo / '.git/config.lock'
        lock.write_text('fixture lock')
        try:
            self.remote_begin(base, ok=False)
        finally:
            lock.unlink()
        path = self.root / 'received'
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.assertEqual(self.read_state()['tasks']['incoming']['creation_tip'], tip)
        # A normal approved commit updates the registration tip, but must not
        # change the original creation intent or make continuation accept Q2.
        (path / 'README').write_text('intervening commit')
        self.git_at(path, 'add', 'README')
        self.git_at(path, 'commit', '-m', 'intervening')
        changed = self.git_at(path, 'rev-parse', 'HEAD').stdout.strip()
        self.assertNotEqual(changed, tip)
        before = self.read_state()
        self.branch('begin', '--mode', 'continue', '--task', 'incoming', ok=False)
        self.assertEqual(self.read_state(), before)
        self.assertTrue(before['tasks']['incoming']['creating'])
        self.assertEqual(before['tasks']['incoming']['creation_tip'], tip)
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), changed)
        self.assertEqual((path / 'README').read_text(), 'intervening commit')

    def test_remote_adopt_resume_checks_bytes_hidden_by_index_flags(self):
        seed, base, tip = self.remote_topic()
        lock = self.repo / '.git/config.lock'
        lock.write_text('fixture lock')
        try:
            self.remote_begin(base, ok=False)
        finally:
            lock.unlink()
        path = self.root / 'received'
        tracked = path / 'README'
        original = tracked.read_bytes()
        index = Path(self.git_at(path, 'rev-parse', '--path-format=absolute', '--git-path', 'index').stdout.strip())
        for flag in ('assume-unchanged', 'skip-worktree'):
            with self.subTest(flag=flag):
                self.git_at(path, 'update-index', '--' + flag, 'README')
                tracked.write_bytes(b'hidden change')
                self.assertEqual(self.git_at(path, 'status', '--porcelain').stdout, '')
                before_index, before_state = index.read_bytes(), self.read_state()
                self.branch('begin', '--mode', 'continue', '--task', 'incoming', ok=False)
                self.assertEqual(tracked.read_bytes(), b'hidden change')
                self.assertEqual(index.read_bytes(), before_index)
                self.assertEqual(self.read_state(), before_state)
                tracked.write_bytes(original)
                self.git_at(path, 'update-index', '--no-' + flag, 'README')
        self.branch('begin', '--mode', 'continue', '--task', 'incoming')
        self.assertNotIn('creating', self.read_state()['tasks']['incoming'])
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)

    def test_new_creation_can_resume_after_an_approved_commit(self):
        path = self.root / 'new worktree'
        lock = self.repo / '.git/config.lock'
        lock.write_text('fixture lock')
        try:
            self.branch('begin', '--mode', 'new', '--task', 'new', '--request', 'new-work',
                        '--branch', 'new', '--worktree', str(path), ok=False)
        finally:
            lock.unlink()
        self.assertTrue(self.read_state()['tasks']['new']['creating'])
        self.assertNotIn('creation_tip', self.read_state()['tasks']['new'])
        (path / 'README').write_text('approved new work')
        self.git_at(path, 'add', 'README')
        self.git_at(path, 'commit', '-m', 'approved new work')
        tip = self.git_at(path, 'rev-parse', 'HEAD').stdout.strip()
        self.branch('begin', '--mode', 'continue', '--task', 'new')
        self.assertEqual(self.read_state()['tasks']['new']['tip'], tip)
        self.assertNotIn('creating', self.read_state()['tasks']['new'])
        self.assertEqual((path / 'README').read_text(), 'approved new work')

    def test_legacy_hook_mutation_is_revalidated_before_enforcement(self):
        clone = self.root / 'legacy mutation'
        self.command('git', 'clone', self.remote, clone)
        previous = clone / '.git/hooks/prepare-commit-msg'
        previous.write_text('#!/bin/sh\ngit config agentBranch.source unexpected-source\n',
                            encoding='utf-8', newline='\n')
        previous.chmod(0o755)
        self.branch('install', repo=clone)
        before = self.git_at(clone, 'show-ref').stdout
        message = clone / 'message'
        message.write_text('message', encoding='utf-8')
        rejected = self.git_at(clone, 'hook', 'run', 'prepare-commit-msg', '--', str(message), ok=False)
        self.assertIn('agentBranch.source differs from installation', rejected.stderr)
        self.assertEqual(self.git_at(clone, 'show-ref').stdout, before)
        self.assertEqual(message.read_text(encoding='utf-8'), 'message')

    def test_pack_refs_preserves_registered_and_retained_branches(self):
        clone = self.root / 'packed refs'
        self.command('git', 'clone', self.remote, clone)
        self.git_at(clone, 'config', 'user.name', 'Test User')
        self.git_at(clone, 'config', 'user.email', 'test@example.invalid')
        self.git_at(clone, 'branch', 'retained')
        self.branch('install', repo=clone)
        for key in ('maintenance.pack-refs.enabled', 'gc.packRefs'):
            self.assertEqual(self.git_at(clone, 'config', '--local', '--get', key).stdout.strip(), 'false')
        self.begin('main', 'adopt', repo=clone, branch='main', into='main')
        topic = Path(self.begin('topic', repo=clone, branch='topic')['worktree'])
        before = self.git_at(clone, 'show-ref', '--heads').stdout
        self.git_at(clone, 'pack-refs', '--all', '--no-prune')
        self.assertEqual(self.git_at(clone, 'show-ref', '--heads').stdout, before)
        self.branch('check', repo=topic)
        self.git_at(clone, 'maintenance', 'run', '--task=gc')
        self.git_at(clone, 'pack-refs', '--all', '--prune', ok=False)
        self.assertEqual(self.git_at(clone, 'show-ref', '--heads').stdout, before)
        self.branch('check', repo=topic)
        old = self.git_at(clone, 'rev-parse', 'retained').stdout.strip()
        tree = self.git_at(clone, 'rev-parse', 'HEAD^{tree}').stdout.strip()
        new = self.git_at(clone, 'commit-tree', tree, '-p', old, '-m', 'unapproved').stdout.strip()
        self.git_at(clone, 'update-ref', 'refs/heads/retained', new, old, ok=False)
        self.git_at(clone, 'update-ref', '-d', 'refs/heads/retained', old, ok=False)
        self.assertEqual(self.git_at(clone, 'rev-parse', 'retained').stdout.strip(), old)

    def state_path(self):
        return self.repo / '.git/agent-branches/state.json'

    def read_state(self):
        return json.loads(self.state_path().read_text(encoding='utf-8'))

    def write_state(self, state):
        self.state_path().write_text(json.dumps(state), encoding='utf-8')

    def test_completed_worktree_creation_can_resume_after_final_write_loss(self):
        work = self.begin('feature', branch='feature')
        state = self.read_state()
        state['tasks']['feature']['creating'] = True  # Crash before final bookkeeping.
        self.write_state(state)
        self.branch('begin', '--mode', 'continue', '--task', 'feature')
        self.assertNotIn('creating', self.read_state()['tasks']['feature'])
        self.assertTrue(Path(work['worktree']).is_dir())

    def test_install_retries_after_config_write_interruption(self):
        clone = self.root / 'install interrupted'
        self.command('git', 'clone', self.remote, clone)
        args = type('Args', (), {'repo': str(clone), 'remote': 'origin'})()
        real_git = management.git
        def fail_config(repo, *argv, **kwargs):
            if argv[:3] == ('config', '--local', 'core.hooksPath'):
                raise management.BranchError('injected interruption')
            return real_git(repo, *argv, **kwargs)
        with patch.object(management, 'git', side_effect=fail_config):
            with self.assertRaisesRegex(management.BranchError, 'injected'):
                management.install(args)
        # Retry owns only its recorded bytes; no deletion/reset of Git state.
        self.branch('install', repo=clone)
        self.begin('main', 'adopt', repo=clone, branch='main', into='main')
        self.branch('check', repo=clone)

    def test_wrong_clone_is_not_a_linked_worktree(self):
        clone = self.root / 'separate clone'
        self.command('git', 'clone', self.remote, clone)
        self.branch('begin', '--mode', 'adopt', '--task', 'wrong', '--request', 'fixture',
                    '--branch', 'main', '--worktree', str(clone), '--base', 'HEAD', ok=False)
        self.assertNotIn('wrong', self.read_state()['tasks'])

    def test_retire_preserves_a_worktree_missing_without_a_removal_record(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        worktree = self.integrate('source')
        tip = self.git('rev-parse', 'refs/heads/source').stdout.strip()
        shutil.rmtree(worktree)  # Crash or manual deletion before the ledger was closed.
        self.branch('retire', '--task', 'source', ok=False)
        self.assertIn('source', self.read_state()['tasks'])
        self.assertEqual(self.git('rev-parse', 'refs/heads/source').stdout.strip(), tip)

    def test_retire_refuses_a_checkout_holding_the_registered_hook_source(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        worktree = self.integrate('source')
        copied = worktree / 'reviewed source'
        (copied / 'bin').mkdir(parents=True)
        (copied / 'hooks').mkdir()
        shutil.copyfile(ROOT / 'bin/branch_management.py', copied / 'bin/branch_management.py')
        shutil.copyfile(ROOT / 'hooks/branch-hook', copied / 'hooks/branch-hook')
        state = self.read_state()
        original = state['source']
        state['source'] = str(copied)
        self.write_state(state)
        self.git('config', '--local', 'agentBranch.source', str(copied))
        # Retiring this checkout would delete the dispatcher every hook runs.
        self.assertIn('reinstall reviewed source', self.branch('retire', '--task', 'source', ok=False).stderr)
        self.assertTrue((copied / 'bin/branch_management.py').exists())
        state = self.read_state()
        state['source'] = original
        self.write_state(state)
        self.git('config', '--local', 'agentBranch.source', original)
        shutil.rmtree(copied)
        self.branch('retire', '--task', 'source')
        self.assertFalse(worktree.exists())

    def test_retire_preserves_a_different_repositories_hook_source(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        worktree = Path(self.begin('supplier', branch='supplier')['worktree'])
        for relative in ('bin/branch_management.py', 'bin/push_preflight.py', 'hooks/branch-hook'):
            target = worktree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.git_at(worktree, 'add', 'bin', 'hooks')
        self.git_at(worktree, 'commit', '-m', 'source')
        self.branch('prepare-merge', '--task', 'supplier')
        self.git('merge', '--no-ff', '--no-commit', 'supplier')
        self.git('commit', '-m', 'integrate supplier')
        consumer = self.root / 'consumer'
        self.command('git', 'clone', self.remote, consumer)
        entry = worktree / 'bin/branch_management.py'
        self.command(sys.executable, str(entry), 'install', '--repo', str(consumer), '--remote', 'origin')
        self.begin('consumer-main', 'adopt', repo=consumer, branch='main', into='main')
        self.assertIn('locked', self.branch('retire', '--task', 'supplier', ok=False).stderr)
        self.assertTrue(entry.exists())
        self.command(sys.executable, str(entry), 'check', '--repo', str(consumer))
        # Rebinding cannot establish that every other consumer is gone.
        self.branch('install', repo=consumer)
        self.assertIn('locked', self.branch('retire', '--task', 'supplier', ok=False).stderr)
        # Simulate an old, unlocked installation and require explicit reinstallation.
        self.git('worktree', 'unlock', str(worktree))
        self.command(sys.executable, str(entry), 'install', '--repo', str(consumer), '--remote', 'origin')
        self.git('worktree', 'unlock', str(worktree))
        result = self.command(sys.executable, str(entry), 'check', '--repo', str(consumer), ok=False)
        self.assertIn('unprotected dependency worktree', result.stdout)
        self.command(sys.executable, str(entry), 'install', '--repo', str(consumer), '--remote', 'origin')
        self.assertIn('locked', self.branch('retire', '--task', 'supplier', ok=False).stderr)

    def test_retire_serializes_a_new_dependency_until_removal_finishes(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        worktree = self.integrate('source')
        args = type('Args', (), {'repo': str(self.repo), 'task': 'source',
            'users_released': True, 'result_ref': 'https://example.invalid/saved-result'})()
        real_git = management.git
        children = []
        def interleave(repo, *argv, **kwargs):
            if argv[:2] == ('worktree', 'remove'):
                child = subprocess.Popen([sys.executable, str(ROOT / 'bin/place.py'),
                    'branch', 'begin', '--repo', str(self.repo), '--mode', 'new',
                    '--task', 'late', '--request', 'late', '--branch', 'late',
                    '--worktree', str(self.root / 'late'), '--depends-on', 'source'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                children.append(child)
                with self.assertRaises(subprocess.TimeoutExpired):
                    child.communicate(timeout=1)
            return real_git(repo, *argv, **kwargs)
        try:
            with patch.object(management, 'git', side_effect=interleave):
                management.retire(args)
        finally:
            for child in children:
                out, err = child.communicate(timeout=30)
        self.assertNotEqual(child.returncode, 0, out + err)
        self.assertFalse(worktree.exists())
        state = self.read_state()
        self.assertNotIn('late', state['tasks'])
        self.assertNotIn('source', state['tasks'])
        self.branch('check')

    def test_legacy_registration_is_not_removed_without_dependency_migration(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        worktree = self.integrate('legacy')
        state = self.read_state()
        state['tasks']['legacy'].pop('retirement_guarded')
        self.write_state(state)
        self.assertIn('dependency migration', self.branch('retire', '--task', 'legacy', ok=False).stderr)
        self.assertTrue(worktree.exists())
        self.branch('begin', '--mode', 'continue', '--task', 'legacy')
        self.assertNotIn('retirement_guarded', self.read_state()['tasks']['legacy'])
        self.branch('check')

    def test_missing_locked_worktree_keeps_its_registration(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        worktree = self.integrate('locked')
        self.git('worktree', 'lock', '--reason', 'dependency', str(worktree))
        self.branch('retire', '--request', '--task', 'locked')
        shutil.rmtree(worktree)
        self.assertIn('disappeared', self.branch('retire', '--task', 'locked', ok=False).stderr)
        self.assertIn('locked', self.read_state()['tasks'])
        self.assertIn(str(worktree).replace(chr(92), '/'),
                      self.git('worktree', 'list', '--porcelain').stdout.replace(chr(92), '/'))

    def test_new_commit_tree_must_equal_actual_prepared_index(self):
        topic = Path(self.begin('feature', branch='feature')['worktree'])
        old = self.git_at(topic, 'rev-parse', 'HEAD').stdout.strip()
        self.git_at(topic, 'hook', 'run', 'prepare-commit-msg', '--', 'MESSAGE')
        (topic / 'unprepared').write_text('changed tree\n', encoding='utf-8')
        self.git_at(topic, 'add', 'unprepared')
        tree = self.git_at(topic, 'write-tree').stdout.strip()
        candidate = self.git_at(topic, 'commit-tree', tree, '-p', old, input='candidate\n').stdout.strip()
        denied = self.git_at(topic, 'update-ref', 'refs/heads/feature', candidate, old, ok=False)
        self.assertIn('tree or parents', denied.stderr)
        self.assertEqual(self.git_at(topic, 'rev-parse', 'HEAD').stdout.strip(), old)
        self.assertTrue((topic / 'unprepared').exists())
        self.git_at(topic, 'commit', '-m', 'prepared by ordinary commit')

    def test_source_prepared_before_merge_is_reserved_in_both_orders(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        topic = Path(self.begin('feature', branch='feature')['worktree'])
        old = self.git_at(topic, 'rev-parse', 'HEAD').stdout.strip()
        (topic / 'feature').write_text('feature\n', encoding='utf-8')
        self.git_at(topic, 'add', 'feature')
        self.git_at(topic, 'hook', 'run', 'prepare-commit-msg', '--', 'MESSAGE')
        tree = self.git_at(topic, 'write-tree').stdout.strip()
        new = self.git_at(topic, 'commit-tree', tree, '-p', old, input='feature\n').stdout.strip()
        self.command(sys.executable, str(ROOT / 'bin/branch_management.py'), 'hook',
                     'reference-transaction', 'prepared', cwd=topic,
                     input=f'{old} {new} refs/heads/feature\n')
        denied = self.branch('prepare-merge', '--task', 'feature', ok=False)
        self.assertIn('in-flight', denied.stderr)
        self.git_at(topic, 'update-ref', 'refs/heads/feature', new, old)
        self.branch('prepare-merge', '--task', 'feature')
        self.git('merge', '--no-ff', '--no-commit', 'feature')
        self.git('hook', 'run', 'prepare-commit-msg', '--', 'MESSAGE')
        tree = self.git('write-tree').stdout.strip()
        merged = self.git('commit-tree', tree, '-p', old, '-p', new, input='merge\n').stdout.strip()
        self.command(sys.executable, str(ROOT / 'bin/branch_management.py'), 'hook',
                     'reference-transaction', 'prepared', cwd=self.repo,
                     input=f'{old} {merged} refs/heads/main\n')
        denied = self.git_at(topic, 'commit', '--allow-empty', '-m', 'source moved', ok=False)
        self.assertIn('reserved', denied.stderr)
        self.git('update-ref', 'refs/heads/main', merged, old)
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), merged)

    def test_push_checks_actual_refs_and_shared_preflight(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        denied = self.git('commit', '--allow-empty', '--no-verify', '-m', 'direct main', ok=False)
        self.assertIn('integration-only', denied.stderr)
        topic = Path(self.begin('feature', branch='feature')['worktree'])
        self.git_at(topic, 'commit', '--allow-empty', '-m', 'feature')
        management.push_check(topic, 'origin', 'feature')
        self.git_at(topic, 'push', 'origin', 'HEAD:refs/heads/feature')
        with self.assertRaises(management.BranchError):
            management.push_check(topic, 'origin', 'main')
        denied = self.git_at(topic, 'push', 'origin', 'HEAD:refs/heads/unregistered', ok=False)
        self.assertIn('unregistered branch', denied.stderr)
        # The preflight CLI must apply the same gate even with explicit push intent.
        result = self.command(sys.executable, str(ROOT / 'bin/push_preflight.py'), str(topic),
                              '--user-intent', 'push')
        self.assertEqual(json.loads(result.stdout)['decision'], 'push')
        hooks = Path(self.git_at(topic, 'config', '--get', 'core.hooksPath').stdout.strip())
        (hooks / 'reference-transaction').unlink()
        result = self.command(sys.executable, str(ROOT / 'bin/push_preflight.py'), str(topic),
                              '--user-intent', 'push')
        self.assertEqual(json.loads(result.stdout)['decision'], 'hold')
        self.git_at(topic, 'commit', '--allow-empty', '--no-verify', '-m', 'missing hook', ok=False)


    def test_previous_push_hook_keeps_stdin_arguments_and_exit_code(self):
        clone = self.root / 'legacy push'
        self.command('git', 'clone', self.remote, clone)
        previous = clone / '.git/hooks/pre-push'
        previous.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$@" > previous-args\n'
            'cat > previous-input\n[ -f deny-push ] && exit 41\nexit 0\n',
            encoding='utf-8', newline='\n')
        previous.chmod(0o755)
        self.branch('install', repo=clone)
        self.begin('main', 'adopt', repo=clone, branch='main', into='main')
        topic = Path(self.begin('topic', repo=clone, branch='topic')['worktree'])
        tip = self.git_at(topic, 'rev-parse', 'HEAD').stdout.strip()
        payload = f"refs/heads/topic {tip} refs/heads/topic {'0' * len(tip)}\n"
        args = (sys.executable, str(ROOT / 'bin/branch_management.py'), 'hook',
                'pre-push', 'origin', str(self.remote))
        hook_env = os.environ.copy()
        if os.name == 'nt':
            hook_env['PATH'] = str(Path(shutil.which('git')).parent)
        with patch.dict(os.environ, hook_env, clear=True):
            self.command(*args, cwd=topic, input=payload)
        self.assertEqual((topic / 'previous-args').read_text().splitlines(), ['origin', str(self.remote)])
        self.assertEqual((topic / 'previous-input').read_text(), payload)
        (topic / 'deny-push').touch()
        with patch.dict(os.environ, hook_env, clear=True):
            self.assertEqual(self.command(*args, cwd=topic, input=payload, ok=False).returncode, 41)
        if os.name != 'nt':
            hooks = Path(self.git_at(topic, 'config', '--get', 'core.hooksPath').stdout.strip())
            (hooks / 'pre-push.previous').chmod(0o644)
            self.branch('check', repo=topic, ok=False)


def load_tests(loader, tests, pattern):
    # Reuse real-Git fixture helpers without running the base suite twice.
    return unittest.TestSuite(RecoveryTests(name) for name in RecoveryTests.__dict__
                              if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
