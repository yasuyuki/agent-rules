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
    def test_pack_refs_preserves_registered_and_retained_branches(self):
        clone = self.root / 'packed refs'
        self.command('git', 'clone', self.remote, clone)
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
