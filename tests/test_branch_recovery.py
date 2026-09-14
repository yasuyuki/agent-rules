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

from test_branch_management import BranchManagementTests, ROOT, PLACE

spec = importlib.util.spec_from_file_location('branch_management', PLACE.with_name('branch_management.py'))
management = importlib.util.module_from_spec(spec)
spec.loader.exec_module(management)


class RecoveryTests(BranchManagementTests):
    def test_remote_adoption_post_checkout_interruption_keeps_target_immutable(self):
        sender, base, tip = self.remote_adoption_fixture()
        path = self.root / 'received'
        args = ['begin', '--repo', str(self.repo), '--mode', 'adopt', '--from-remote',
                '--task', 'received', '--branch', 'received', '--request', 'issue-89',
                '--base', base, '--worktree', str(path)]
        real_git = management.git
        def fail_tracking(repo, *argv, **kwargs):
            if argv[:2] == ('config', 'branch.received.remote'):
                raise management.BranchError('fixture interruption after checkout')
            return real_git(repo, *argv, **kwargs)
        with patch.object(management, 'git', side_effect=fail_tracking):
            self.assertEqual(management.main(args), 1)
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.git_at(path, 'commit', '--allow-empty', '-m', 'must not change Q', ok=False)
        self.assertEqual(self.read_state()['tasks']['received']['tip'], tip)
        original = (path / 'binary').read_bytes()
        index = Path(self.git_at(path, 'rev-parse', '--path-format=absolute', '--git-path', 'index').stdout.strip())
        for variation in ('ordinary', 'skip-worktree', 'assume-unchanged', 'hidden-untracked'):
            with self.subTest(variation=variation):
                changed = path / ('additional-work' if variation == 'hidden-untracked' else 'binary')
                if variation in ('skip-worktree', 'assume-unchanged'):
                    self.git_at(path, 'update-index', '--' + variation, 'binary')
                if variation == 'hidden-untracked':
                    self.git_at(path, 'config', 'status.showUntrackedFiles', 'no')
                changed.write_bytes(b'work after interruption\x00\xff')
                if variation != 'ordinary':
                    self.assertEqual(self.git_at(path, 'status', '--porcelain', '--ignored').stdout, '')
                before = (self.state_path().read_bytes(), index.read_bytes(), changed.read_bytes(),
                          self.git_at(path, 'config', '--local', '--list').stdout)
                self.branch('begin', '--mode', 'continue', '--task', 'received', ok=False)
                self.assertEqual(before, (self.state_path().read_bytes(), index.read_bytes(), changed.read_bytes(),
                                         self.git_at(path, 'config', '--local', '--list').stdout))
                self.assertTrue(self.read_state()['tasks']['received']['creating'])
                self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
                if variation == 'hidden-untracked':
                    changed.unlink()
                else:
                    changed.write_bytes(original)
                if variation in ('skip-worktree', 'assume-unchanged'):
                    self.git_at(path, 'update-index', '--no-' + variation, 'binary')
        if os.name != 'nt':
            self.git_at(path, 'config', 'core.filemode', 'false')
            for filename, changed_mode, tree_mode in (('executable', 0o644, '100755'),
                                                       ('binary', 0o755, '100644')):
                with self.subTest(mode_change=filename):
                    changed = path / filename
                    original_mode = changed.stat().st_mode & 0o777
                    self.assertTrue(self.git_at(path, 'ls-tree', tip, '--', filename).stdout.startswith(tree_mode))
                    changed.chmod(changed_mode)
                    self.assertEqual(self.git_at(path, 'status', '--porcelain', '--ignored').stdout, '')
                    before = (self.state_path().read_bytes(), index.read_bytes(), changed.read_bytes(),
                              changed.stat().st_mode, self.git_at(path, 'config', '--local', '--list').stdout)
                    self.branch('begin', '--mode', 'continue', '--task', 'received', ok=False)
                    self.assertEqual(before, (self.state_path().read_bytes(), index.read_bytes(), changed.read_bytes(),
                                             changed.stat().st_mode, self.git_at(path, 'config', '--local', '--list').stdout))
                    self.assertTrue(self.read_state()['tasks']['received']['creating'])
                    self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
                    changed.chmod(original_mode)
        self.branch('begin', '--mode', 'continue', '--task', 'received')
        self.branch('begin', '--mode', 'continue', '--task', 'received')
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.assertEqual(self.git('config', 'branch.received.remote').stdout.strip(), 'origin')
        self.assertNotIn('received', self.read_state()['permits'])

    def test_remote_adoption_resumes_after_branch_created_without_checkout(self):
        sender, base, tip = self.remote_adoption_fixture()
        args = ['begin', '--repo', str(self.repo), '--mode', 'adopt', '--from-remote',
                '--task', 'received', '--branch', 'received', '--request', 'issue-89',
                '--base', base, '--worktree', str(self.root / 'received')]
        real_git = management.git
        def partial_creation(repo, *argv, **kwargs):
            if argv[:2] == ('worktree', 'add'):
                real_git(repo, 'branch', 'received', tip)
                raise management.BranchError('fixture interruption after ref creation')
            return real_git(repo, *argv, **kwargs)
        with patch.object(management, 'git', side_effect=partial_creation):
            self.assertEqual(management.main(args), 1)
        self.assertNotIn('received', self.read_state()['permits'])
        self.assertFalse((self.root / 'received').exists())
        self.branch('begin', '--mode', 'continue', '--task', 'received')
        self.branch('begin', '--mode', 'continue', '--task', 'received')
        self.assertEqual(self.git_at(self.root / 'received', 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.assertNotIn('creating', self.read_state()['tasks']['received'])

    def test_remote_adoption_recovery_refuses_changed_branch_without_path(self):
        sender, base, tip = self.remote_adoption_fixture()
        path = self.root / 'received'
        args = ['begin', '--repo', str(self.repo), '--mode', 'adopt', '--from-remote',
                '--task', 'received', '--branch', 'received', '--request', 'issue-89',
                '--base', base, '--worktree', str(path)]
        real_git = management.git
        def fail_creation(repo, *argv, **kwargs):
            if argv[:2] == ('worktree', 'add'):
                raise management.BranchError('fixture interruption')
            return real_git(repo, *argv, **kwargs)
        with patch.object(management, 'git', side_effect=fail_creation):
            self.assertEqual(management.main(args), 1)
        # Model external tampering only in this disposable fixture. The public
        # continuation must detect it even though the normal hooks prevent it.
        self.git('-c', 'core.hooksPath=' + str(self.root / 'no-hooks'),
                 'update-ref', 'refs/heads/received', base)
        before = self.read_state()
        self.branch('begin', '--mode', 'continue', '--task', 'received', ok=False)
        self.assertEqual(self.git('rev-parse', 'received').stdout.strip(), base)
        self.assertFalse(path.exists())
        self.assertEqual(self.read_state(), before)

    def test_remote_adoption_recovers_pinned_tip_after_creation_failure(self):
        sender, base, tip = self.remote_adoption_fixture()
        args = ['begin', '--repo', str(self.repo), '--mode', 'adopt', '--from-remote',
                '--task', 'received', '--branch', 'received', '--request', 'issue-89',
                '--base', base, '--worktree', str(self.root / 'received')]
        real_git = management.git
        def fail_creation(repo, *argv, **kwargs):
            if argv[:2] == ('worktree', 'add'):
                raise management.BranchError('fixture creation failure')
            return real_git(repo, *argv, **kwargs)
        with patch.object(management, 'git', side_effect=fail_creation):
            self.assertEqual(management.main(args), 1)
        state = self.read_state()
        self.assertTrue(state['tasks']['received']['creating'])
        self.assertEqual(state['permits']['received']['new'], tip)
        (sender / 'later').write_text('Q2', encoding='utf-8')
        self.git_at(sender, 'add', 'later')
        self.git_at(sender, 'commit', '-m', 'later')
        self.git_at(sender, 'push', 'origin', 'received')
        self.git('fetch', 'origin')
        self.branch('begin', '--mode', 'continue', '--task', 'received', '--sync', ok=False)
        self.branch('begin', '--mode', 'continue', '--task', 'received')
        self.assertEqual(self.git('rev-parse', 'received').stdout.strip(), tip)
        self.assertEqual(self.read_state()['tasks']['received']['base'], base)
        self.assertNotIn('received', self.read_state()['permits'])
        state = self.read_state()
        state['tasks']['received']['creating'] = True
        self.write_state(state)
        path = self.root / 'received'
        (path / 'binary').write_bytes(b'changed')
        self.branch('begin', '--mode', 'continue', '--task', 'received', ok=False)
        self.assertEqual((path / 'binary').read_bytes(), b'changed')
        self.assertTrue(self.read_state()['tasks']['received']['creating'])

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

    def test_retire_completes_when_the_worktree_directory_is_already_gone(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        worktree = self.integrate('source')
        tip = self.git('rev-parse', 'refs/heads/source').stdout.strip()
        shutil.rmtree(worktree)  # Crash or manual deletion before the ledger was closed.
        self.branch('retire', '--task', 'source')
        checked = json.loads(self.branch('check', '--json').stdout)
        self.assertTrue(checked['ok'], checked)
        self.assertNotIn('source', checked['tasks'])
        self.assertNotIn(str(worktree), self.git('worktree', 'list').stdout)
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
        args = type('Args', (), {'repo': str(self.repo), 'task': 'source'})()
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
        shutil.rmtree(worktree)
        self.assertIn('metadata remains', self.branch('retire', '--task', 'locked', ok=False).stderr)
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
