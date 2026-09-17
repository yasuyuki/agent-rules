"""Acceptance coverage for remote-only adoption recovery.

These cases use the public ``place.py branch begin`` entry point.  The owned
``config.lock`` interruption occurs after the remote checkout has been made,
so the continuation cases exercise the state a user can actually encounter.
"""
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch
import importlib.util
from contextlib import contextmanager
import shlex

from test_branch_management import BranchManagementTests, PLACE


spec = importlib.util.spec_from_file_location('remote_adoption_management',
                                              PLACE.with_name('branch_management.py'))
management = importlib.util.module_from_spec(spec)
spec.loader.exec_module(management)


class RemoteAdoptionAcceptanceTests(BranchManagementTests):
    """Keep the original remote Q and every user-owned checkout byte intact."""

    def state_path(self):
        return self.repo / '.git' / 'agent-branches' / 'state.json'

    def remote_topic(self):
        """Create Q with checkout conversion, distinct from the caller rules."""
        seed, base, _tip = super().remote_topic()
        (seed / '.gitattributes').write_bytes(b'lines text eol=crlf\n')
        (seed / 'lines').write_bytes(b'one\ntwo\n')
        self.git_at(seed, 'add', '.gitattributes', 'lines')
        self.git_at(seed, 'commit', '-m', 'declare incoming checkout attributes')
        tip = self.git_at(seed, 'rev-parse', 'HEAD').stdout.strip()
        self.git_at(seed, 'push', 'origin', 'incoming')
        self.git('fetch', 'origin')
        return seed, base, tip

    def read_state_bytes(self):
        return self.state_path().read_bytes()

    def worktree_snapshot(self, path):
        """Read the user-visible tree and Git index without refreshing either."""
        path = Path(path)
        files = {}
        for current, directories, names in os.walk(path, followlinks=False):
            directories[:] = [directory for directory in directories if directory != '.git']
            directories.sort()
            for name in sorted(names):
                item = Path(current) / name
                relative = item.relative_to(path).as_posix()
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode):
                    files[relative] = ('link', os.readlink(item), stat.S_IMODE(info.st_mode))
                elif stat.S_ISREG(info.st_mode):
                    files[relative] = ('file', item.read_bytes(), stat.S_IMODE(info.st_mode))
        index = Path(self.git_at(path, 'rev-parse', '--path-format=absolute',
                                 '--git-path', 'index').stdout.strip())
        return {
            'head': self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(),
            'index_bytes': index.read_bytes(),
            'index_stage': self.git_at(path, 'ls-files', '--stage', '-z').stdout,
            'files': files,
            'state': self.read_state_bytes(),
        }

    def interrupt_remote_adoption(self, path=None):
        seed, base, tip = self.remote_topic()
        path = Path(path or self.root / 'received')
        lock = self.repo / '.git' / 'config.lock'
        self.assertFalse(lock.exists())
        lock.write_bytes(b'owned acceptance fixture lock\n')
        try:
            failed = self.remote_begin(base, path=path, ok=False)
        finally:
            lock.unlink()
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('could not lock config file', failed.stderr)
        self.assertTrue(path.is_dir())
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.assertIn(b'"creating": true', self.read_state_bytes())
        return seed, base, tip, path

    def assert_rejected_without_writes(self, path):
        before = self.worktree_snapshot(path)
        rejected = self.branch('begin', '--mode', 'continue', '--task', 'incoming', ok=False)
        self.assertIn('preserve and inspect', rejected.stderr)
        self.assertEqual(self.worktree_snapshot(path), before)

    def assert_checkout_unchanged(self, before, path):
        after = self.worktree_snapshot(path)
        before.pop('state')
        after.pop('state')
        self.assertEqual(after, before)

    def test_remote_resume_clean_checkout_keeps_original_q_after_tracking_advances(self):
        seed, _base, tip, path = self.interrupt_remote_adoption()
        (seed / 'Q2').write_text('later remote commit\n', encoding='utf-8')
        self.git_at(seed, 'add', 'Q2')
        self.git_at(seed, 'commit', '-m', 'advance remote after Q')
        self.git_at(seed, 'push', 'origin', 'incoming')
        self.git('fetch', 'origin')
        self.assertNotEqual(self.git('rev-parse', 'origin/incoming').stdout.strip(), tip)
        before = self.worktree_snapshot(path)
        caller_before = self.worktree_snapshot(self.repo)
        self.branch('begin', '--mode', 'continue', '--task', 'incoming')
        self.assert_checkout_unchanged(before, path)
        self.assert_checkout_unchanged(caller_before, self.repo)
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.assertNotIn(b'"creating"', self.read_state_bytes())

    def test_remote_resume_clean_checkout_uses_target_attributes_and_preserves_crlf(self):
        # Caller attributes must not become the comparison rules for Q.
        (self.repo / '.gitattributes').write_bytes(b'lines -text\n')
        caller_before = self.worktree_snapshot(self.repo)
        _seed, _base, tip, path = self.interrupt_remote_adoption()
        self.assertEqual((path / 'lines').read_bytes(), b'one\r\ntwo\r\n')
        before = self.worktree_snapshot(path)
        self.branch('begin', '--mode', 'continue', '--task', 'incoming')
        self.assert_checkout_unchanged(before, path)
        self.assert_checkout_unchanged(caller_before, self.repo)
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)
        self.assertEqual((path / 'lines').read_bytes(), b'one\r\ntwo\r\n')

    def test_remote_resume_rejects_ordinary_content_and_preserves_it(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        (path / 'binary').write_bytes(b'foreign binary\x00\xff\r\n')
        self.assert_rejected_without_writes(path)

    def test_remote_resume_rejects_crlf_byte_change_and_preserves_it(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        self.assertEqual((path / 'lines').read_bytes(), b'one\r\ntwo\r\n')
        # This has Q's normalized blob, but not Q's checkout bytes.
        (path / 'lines').write_bytes(b'one\ntwo\n')
        self.assert_rejected_without_writes(path)

    def test_remote_resume_rejects_assume_unchanged_content_and_preserves_index(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        self.git_at(path, 'update-index', '--assume-unchanged', 'binary')
        (path / 'binary').write_bytes(b'hidden by assume unchanged\x00')
        self.assertEqual(self.git_at(path, 'status', '--porcelain').stdout, '')
        self.assert_rejected_without_writes(path)

    def test_remote_resume_rejects_skip_worktree_content_and_preserves_index(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        self.git_at(path, 'update-index', '--skip-worktree', 'binary')
        (path / 'binary').write_bytes(b'hidden by skip worktree\x00')
        self.assertEqual(self.git_at(path, 'status', '--porcelain').stdout, '')
        self.assert_rejected_without_writes(path)

    def test_remote_resume_rejects_committed_content_and_preserves_registration(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        (path / 'README').write_text('ordinary approved commit\n', encoding='utf-8')
        self.git_at(path, 'add', 'README')
        self.git_at(path, 'commit', '-m', 'ordinary work during interrupted adoption')
        self.assert_rejected_without_writes(path)

    def test_remote_resume_rejects_staged_only_content_and_preserves_index(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        original = (path / 'README').read_bytes()
        (path / 'README').write_bytes(b'foreign staged content\n')
        self.git_at(path, 'add', 'README')
        (path / 'README').write_bytes(original)
        self.assert_rejected_without_writes(path)

    def test_remote_resume_rejects_hidden_untracked_content_and_preserves_it(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        self.git_at(path, 'config', 'status.showUntrackedFiles', 'no')
        (path / 'private.bin').write_bytes(b'foreign untracked\x00')
        self.assert_rejected_without_writes(path)

    def test_remote_resume_rejects_ignored_content_and_preserves_it(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        (self.repo / '.git' / 'info' / 'exclude').write_text('private.bin\n', encoding='utf-8')
        (path / 'private.bin').write_bytes(b'foreign ignored\x00')
        self.assert_rejected_without_writes(path)

    def test_remote_resume_rejects_redefined_historical_contract(self):
        _seed, base, tip, path = self.interrupt_remote_adoption()
        for option, value in (('--base', tip), ('--into', 'incoming'), ('--depends-on', 'unknown-parent')):
            with self.subTest(option=option):
                before = self.worktree_snapshot(path)
                rejected = self.branch('begin', '--mode', 'continue', '--task', 'incoming',
                                       option, value, ok=False)
                self.assertIn('continuation cannot redefine', rejected.stderr)
                self.assertEqual(self.worktree_snapshot(path), before)
        # Continuation inherits these fields; the established API rejects
        # respecifying them, including equal values.
        self.branch('begin', '--mode', 'continue', '--task', 'incoming')

    @unittest.skipIf(os.name == 'nt', 'POSIX file modes are not available')
    def test_remote_resume_clean_checkout_with_filemode_disabled(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        self.git_at(path, 'config', 'core.filemode', 'false')
        before = self.worktree_snapshot(path)
        self.branch('begin', '--mode', 'continue', '--task', 'incoming')
        self.assert_checkout_unchanged(before, path)
        self.assertEqual(self.git_at(path, 'config', '--get', 'core.filemode').stdout.strip(), 'false')

    @unittest.skipIf(os.name == 'nt', 'POSIX file modes are not available')
    def test_remote_resume_rejects_executable_bit_removal_hidden_by_filemode(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        self.git_at(path, 'config', 'core.filemode', 'false')
        (path / 'run').chmod(0o644)
        self.assertEqual(stat.S_IMODE((path / 'run').stat().st_mode), 0o644)
        self.assert_rejected_without_writes(path)

    @unittest.skipIf(os.name == 'nt', 'POSIX file modes are not available')
    def test_remote_resume_rejects_executable_bit_addition_hidden_by_filemode(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        self.git_at(path, 'config', 'core.filemode', 'false')
        (path / 'README').chmod(0o755)
        self.assertEqual(stat.S_IMODE((path / 'README').stat().st_mode), 0o755)
        self.assert_rejected_without_writes(path)

    def test_remote_resume_stale_real_index_stays_byte_identical(self):
        _seed, _base, tip, path = self.interrupt_remote_adoption()
        index = Path(self.git_at(path, 'rev-parse', '--path-format=absolute',
                                 '--git-path', 'index').stdout.strip())
        self.git_at(path, 'update-index', '--refresh')
        before = index.read_bytes()
        tracked = path / 'README'
        stamp = tracked.stat().st_mtime_ns + 2_000_000_000
        os.utime(tracked, ns=(stamp, stamp))
        self.branch('begin', '--mode', 'continue', '--task', 'incoming')
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), tip)

    def test_remote_resume_filter_runs_without_registration_lock(self):
        self.git('config', 'core.autocrlf', 'true')
        seed, base, _tip = self.remote_topic()
        # Make the incoming blob deterministic before applying -text: the base
        # README comes from the shared fixture and may have CRLF on Windows.
        # The separate CRLF cases exercise newline conversion itself.
        (seed / 'README').write_bytes(b'base\n')
        (seed / '.gitattributes').write_text('README filter=acceptance-filter -text\n', encoding='utf-8')
        self.git_at(seed, 'add', 'README', '.gitattributes')
        self.git_at(seed, 'commit', '-m', 'configure acceptance filter')
        self.assertEqual(self.git_at(seed, 'rev-parse', 'HEAD:README').stdout.strip(),
                         self.git_at(seed, 'hash-object', 'README').stdout.strip())
        self.git_at(seed, 'push', 'origin', 'incoming')
        self.git('fetch', 'origin')
        marker = self.root / 'filter-lock-observation'
        program = self.root / 'filter_lock_probe.py'
        lock = self.repo / '.git' / 'agent-branches' / 'lock'
        prefix = b'acceptance-smudge:'
        program.write_text('''import os
import pathlib
import sys

prefix = b'acceptance-smudge:'
data = sys.stdin.buffer.read()
if sys.argv[1] == 'smudge':
    sys.stdout.buffer.write(prefix + data)
    raise SystemExit(0)
stream = open(sys.argv[2], 'a+b')
try:
    if os.name == 'nt':
        import msvcrt
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    observation = 'unlocked'
except OSError:
    observation = 'locked'
finally:
    stream.close()
with pathlib.Path(sys.argv[3]).open('a', encoding='utf-8') as output:
    output.write(observation + '\\n')
if not data.startswith(prefix):
    raise SystemExit('missing smudge prefix')
sys.stdout.buffer.write(data[len(prefix):])
''', encoding='utf-8')
        clean = ' '.join(shlex.quote(str(value))
                         for value in (os.sys.executable, program, 'clean', lock, marker))
        smudge = ' '.join(shlex.quote(str(value))
                          for value in (os.sys.executable, program, 'smudge', lock, marker))
        self.git('config', 'filter.acceptance-filter.clean', clean)
        self.git('config', 'filter.acceptance-filter.smudge', smudge)
        config_lock = self.repo / '.git' / 'config.lock'
        config_lock.write_bytes(b'owned acceptance fixture lock\n')
        try:
            self.remote_begin(base, ok=False)
        finally:
            config_lock.unlink()
        path = self.root / 'received'
        self.assertEqual((path / 'README').read_bytes(), prefix + b'base\n')
        marker.unlink(missing_ok=True)  # Ignore filter calls made during setup.
        self.branch('begin', '--mode', 'continue', '--task', 'incoming')
        self.assertEqual((path / 'README').read_bytes(), prefix + b'base\n')
        observations = marker.read_text(encoding='utf-8').splitlines()
        self.assertTrue(observations)
        self.assertEqual(set(observations), {'unlocked'})

    def test_remote_resume_final_snapshot_rejects_a_validation_race(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        args = type('Args', (), {'repo': str(self.repo), 'task': 'incoming', 'mode': 'continue',
                                 'from_remote': False, 'sync': False, 'request': None,
                                 'branch': None, 'worktree': None, 'base': None,
                                 'into': None, 'depends_on': None})()
        original_locked = management.locked
        lock_entries = 0

        @contextmanager
        def mutate_after_final_lock(repo, create=False):
            nonlocal lock_entries
            with original_locked(repo, create) as current:
                lock_entries += 1
                if lock_entries == 2:
                    (path / 'README').write_bytes(b'changed after outside validation\n')
                yield current

        before = self.worktree_snapshot(path)
        with patch.object(management, 'locked', side_effect=mutate_after_final_lock):
            with self.assertRaisesRegex(management.BranchError, 'changed after validation'):
                management.begin(args)
        self.assertEqual((path / 'README').read_bytes(), b'changed after outside validation\n')
        after = self.worktree_snapshot(path)
        self.assertEqual(after['head'], before['head'])
        self.assertEqual(after['index_bytes'], before['index_bytes'])
        self.assertEqual(after['state'], before['state'])

    @unittest.skipIf(os.name == 'nt', 'POSIX symlinks are not available')
    def test_remote_resume_rejects_leaf_symlink_swap_without_writes(self):
        _seed, _base, _tip, path = self.interrupt_remote_adoption()
        retained = self.root / 'retained-received'
        path.rename(retained)
        path.symlink_to(retained, target_is_directory=True)
        before = self.worktree_snapshot(retained)
        rejected = self.branch('begin', '--mode', 'continue', '--task', 'incoming', ok=False)
        self.assertIn('conflicting symlink', rejected.stderr)
        self.assertTrue(path.is_symlink())
        self.assertEqual(self.worktree_snapshot(retained), before)

    @unittest.skipIf(os.name == 'nt', 'POSIX symlinks are not available')
    def test_remote_resume_rejects_parent_symlink_swap_without_writes(self):
        parent = self.root / 'nested-received'
        parent.mkdir()
        path = parent / 'received'
        _seed, _base, _tip, path = self.interrupt_remote_adoption(path)
        retained_parent = self.root / 'retained-parent'
        parent.rename(retained_parent)
        parent.symlink_to(retained_parent, target_is_directory=True)
        before = self.worktree_snapshot(retained_parent / 'received')
        rejected = self.branch('begin', '--mode', 'continue', '--task', 'incoming', ok=False)
        self.assertIn('conflicting', rejected.stderr)
        self.assertTrue(parent.is_symlink())
        self.assertEqual(self.worktree_snapshot(retained_parent / 'received'), before)

    def test_existing_new_creation_can_continue_after_an_ordinary_commit(self):
        path = self.root / 'ordinary new worktree'
        lock = self.repo / '.git' / 'config.lock'
        lock.write_bytes(b'owned acceptance fixture lock\n')
        try:
            self.branch('begin', '--mode', 'new', '--task', 'ordinary-new',
                        '--request', 'existing contract', '--branch', 'ordinary-new',
                        '--worktree', str(path), ok=False)
        finally:
            lock.unlink()
        (path / 'README').write_text('ordinary existing new work\n', encoding='utf-8')
        self.git_at(path, 'add', 'README')
        self.git_at(path, 'commit', '-m', 'ordinary existing new work')
        head = self.git_at(path, 'rev-parse', 'HEAD').stdout.strip()
        self.branch('begin', '--mode', 'continue', '--task', 'ordinary-new')
        self.assertEqual(self.git_at(path, 'rev-parse', 'HEAD').stdout.strip(), head)
        self.assertIn(head.encode(), self.read_state_bytes())
        self.assertNotIn(b'"creating"', self.read_state_bytes())


def load_tests(loader, tests, pattern):
    # Reuse the fixture without scheduling branch-management's base suite twice.
    return unittest.TestSuite(RemoteAdoptionAcceptanceTests(name)
                              for name in RemoteAdoptionAcceptanceTests.__dict__
                              if name.startswith('test_'))
