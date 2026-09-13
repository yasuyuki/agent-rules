"""Operation correspondence through the public CLI and real Git."""
import json
import os
import sys
from pathlib import Path
import unittest

from test_branch_management import BranchManagementTests


class OperationTests(BranchManagementTests):
    def sync_topic(self):
        topic = Path(self.begin('topic', branch='topic')['worktree'])
        publisher = self.root / 'publisher'
        self.command('git', 'clone', self.remote, publisher)
        self.git_at(publisher, 'config', 'user.name', 'Publisher')
        self.git_at(publisher, 'config', 'user.email', 'publisher@example.invalid')
        self.git_at(publisher, 'switch', '-c', 'topic', 'origin/main')
        (publisher / 'remote').write_bytes(b'remote\x00bytes\n')
        self.git_at(publisher, 'add', 'remote')
        self.git_at(publisher, 'commit', '-m', 'remote')
        self.git_at(publisher, 'push', 'origin', 'topic')
        self.git_at(topic, 'fetch', 'origin')
        return topic

    def prepare(self, topic, ok=True):
        return self.branch('begin', '--mode', 'continue', '--task', 'topic', '--sync', repo=topic, ok=ok)

    def diagnosis(self, topic, ok=True):
        return json.loads(self.branch('check', '--json', repo=topic, ok=ok).stdout)

    def test_dirty_preflight_preserves_bytes_modes_and_separate_classes(self):
        topic = self.sync_topic()
        (topic / 'staged').write_bytes(b'\x00staged\xff')
        (topic / 'staged').chmod(0o755)
        self.git_at(topic, 'add', 'staged')
        (topic / 'README').write_bytes(b'unstaged\x00')
        (topic / 'untracked').write_bytes(b'\xffuntracked')
        (topic / 'untracked').chmod(0o640)
        before = self.diagnosis(topic)['working_state']
        self.prepare(topic, ok=False)
        after = self.diagnosis(topic)['working_state']
        self.assertEqual(before, after)
        self.assertEqual(after['staged'], ['staged'])
        self.assertEqual(after['unstaged'], ['README'])
        self.assertEqual(after['untracked'], ['untracked'])
        self.assertEqual((topic / 'staged').read_bytes(), b'\x00staged\xff')
        self.assertEqual((topic / 'README').read_bytes(), b'unstaged\x00')
        self.assertEqual((topic / 'untracked').read_bytes(), b'\xffuntracked')
        if os.name != 'nt':
            self.assertEqual((topic / 'staged').stat().st_mode & 0o777, 0o755)
            self.assertEqual((topic / 'untracked').stat().st_mode & 0o777, 0o640)

    def test_sync_tracks_completion_and_diagnostics_do_not_write_index(self):
        topic = self.sync_topic()
        self.prepare(topic)
        prepared = self.diagnosis(topic)['operations'][0]
        self.assertEqual(prepared['status'], 'unchanged')
        self.git_at(topic, 'merge', '--ff-only', 'origin/topic')
        index = Path(self.git_at(topic, 'rev-parse', '--path-format=absolute', '--git-path', 'index').stdout.strip())
        before = index.read_bytes()
        completed = self.diagnosis(topic)['operations'][0]
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(completed['id'], prepared['id'])
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['hook_outcome'], 'committed')
        self.assertTrue(completed['changed']['head'])
        self.assertTrue(completed['changed']['index'])

    def test_changed_after_prepare_is_separate_and_snapshot_cannot_be_replaced(self):
        topic = self.sync_topic()
        self.prepare(topic)
        prepared = self.diagnosis(topic)['operations'][0]
        (topic / 'README').write_bytes(b'another editor\x00')
        self.git_at(topic, 'merge', '--ff-only', 'origin/topic', ok=False)
        current = self.diagnosis(topic, ok=False)['operations'][0]
        self.assertEqual(current['status'], 'indeterminate')
        self.assertEqual(current['unattributed_paths'], ['README'])
        self.assertFalse(current['changed']['head'])
        self.assertTrue(current['changed']['index'])
        self.prepare(topic, ok=False)
        final = self.diagnosis(topic, ok=False)['operations'][0]
        self.assertEqual(final['before'], prepared['before'])
        self.assertEqual(final['id'], prepared['id'])
        self.assertEqual((topic / 'README').read_bytes(), b'another editor\x00')

    def test_pre_ref_partial_state_is_retained_and_retry_uses_original_snapshot(self):
        topic = self.sync_topic()
        self.prepare(topic)
        prepared = self.diagnosis(topic)['operations'][0]
        # Git's tree update is independent of the later reference transaction.
        self.git_at(topic, 'read-tree', '-m', '-u', 'HEAD', 'origin/topic')
        partial = self.diagnosis(topic, ok=False)['operations'][0]
        self.assertEqual(partial['status'], 'partial-update')
        self.assertFalse(partial['changed']['head'])
        self.assertTrue(partial['changed']['index'])
        self.assertEqual(partial['before'], prepared['before'])
        self.prepare(topic, ok=False)
        self.git_at(topic, 'merge', '--ff-only', 'origin/topic')
        completed = self.diagnosis(topic)['operations'][0]
        self.assertEqual(completed['id'], prepared['id'])
        self.assertEqual(completed['status'], 'completed')

    def test_crlf_sync_uses_git_content_identity(self):
        topic = self.sync_topic()
        # Publish text as well as binary to exercise checkout conversion.
        publisher = self.root / 'publisher'
        (publisher / 'text').write_bytes(b'line one\nline two\n')
        self.git_at(publisher, 'add', 'text')
        self.git_at(publisher, 'commit', '-m', 'text')
        self.git_at(publisher, 'push', 'origin', 'topic')
        self.git_at(topic, 'fetch', 'origin')
        self.git_at(topic, 'config', 'core.autocrlf', 'true')
        self.prepare(topic)
        self.git_at(topic, 'merge', '--ff-only', 'origin/topic')
        self.assertEqual((topic / 'text').read_bytes(), b'line one\r\nline two\r\n')
        self.assertEqual(self.diagnosis(topic)['operations'][0]['status'], 'completed')

    def test_attribute_filter_sync_uses_clean_blob_identity(self):
        topic = self.sync_topic()
        publisher = self.root / 'publisher'
        (publisher / '.gitattributes').write_text('filtered filter=marker\n')
        (publisher / 'filtered').write_bytes(b'repository bytes\n')
        self.git_at(publisher, 'add', '.gitattributes', 'filtered')
        self.git_at(publisher, 'commit', '-m', 'filtered file')
        self.git_at(publisher, 'push', 'origin', 'topic')
        self.git_at(topic, 'fetch', 'origin')
        script = self.root / 'filter.py'
        script.write_text("import sys\ndata=sys.stdin.buffer.read()\n"
                          "sys.stdout.buffer.write(data.removeprefix(b'SMUDGED:') if sys.argv[1]=='clean' else b'SMUDGED:'+data)\n")
        command = '"' + Path(sys.executable).as_posix() + '" "' + script.as_posix() + '" '
        self.git_at(topic, 'config', 'filter.marker.clean', command + 'clean')
        self.git_at(topic, 'config', 'filter.marker.smudge', command + 'smudge')
        self.git_at(topic, 'config', 'filter.marker.required', 'true')
        self.prepare(topic)
        self.git_at(topic, 'merge', '--ff-only', 'origin/topic')
        self.assertEqual((topic / 'filtered').read_bytes(), b'SMUDGED:repository bytes\n')
        self.assertEqual(self.diagnosis(topic)['operations'][0]['status'], 'completed')

    def test_completed_sync_allows_later_ordinary_registered_commit(self):
        topic = self.sync_topic()
        self.prepare(topic)
        self.git_at(topic, 'merge', '--ff-only', 'origin/topic')
        receipt = self.diagnosis(topic)['operations'][0]
        (topic / 'README').write_bytes(b'normal continued work\n')
        self.git_at(topic, 'add', 'README')
        self.git_at(topic, 'commit', '-m', 'continue topic')
        diagnosis = self.diagnosis(topic)['operations'][0]
        self.assertEqual(diagnosis['status'], 'completed')
        self.assertEqual(diagnosis['committed'], receipt['committed'])
        self.assertEqual(diagnosis['later_registered_tip'], self.git_at(topic, 'rev-parse', 'HEAD').stdout.strip())

    def test_merge_rejects_unrelated_post_prepare_staged_change(self):
        self.begin('integration', 'adopt', branch='main', into='main')
        source = Path(self.begin('source', branch='source')['worktree'])
        (source / 'incoming').write_bytes(b'incoming\n')
        self.git_at(source, 'add', 'incoming')
        self.git_at(source, 'commit', '-m', 'incoming')
        self.branch('prepare-merge', '--task', 'source')
        self.git('merge', '--no-ff', '--no-commit', 'source')
        (self.repo / 'unrelated').write_bytes(b'another editor\x00')
        self.git('add', 'unrelated')
        head = self.git('rev-parse', 'HEAD').stdout
        result = self.git('commit', '-m', 'integration', ok=False)
        self.assertIn('unrelated changes after preparation', result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout, head)
        diagnosis = self.diagnosis(self.repo, ok=False)['operations'][0]
        self.assertEqual(diagnosis['unattributed_paths'], ['unrelated'])
        self.assertEqual((self.repo / 'unrelated').read_bytes(), b'another editor\x00')

    def test_pick_rejects_unrelated_post_prepare_worktree_change(self):
        source = Path(self.begin('source', branch='source')['worktree'])
        (source / 'incoming').write_bytes(b'incoming\n')
        self.git_at(source, 'add', 'incoming')
        self.git_at(source, 'commit', '-m', 'incoming')
        sha = self.git_at(source, 'rev-parse', 'HEAD').stdout.strip()
        target = Path(self.begin('target', branch='target')['worktree'])
        self.branch('allow-cherry-pick', '--commit', sha, '--approval', 'exact approval',
                    '--reason', 'backport', repo=target)
        (target / 'README').write_bytes(b'another editor\x00')
        head = self.git_at(target, 'rev-parse', 'HEAD').stdout
        self.git_at(target, 'cherry-pick', sha, ok=False)
        self.assertEqual(self.git_at(target, 'rev-parse', 'HEAD').stdout, head)
        diagnosis = self.diagnosis(target, ok=False)['operations'][0]
        self.assertEqual(diagnosis['unattributed_paths'], ['README'])
        self.assertEqual((target / 'README').read_bytes(), b'another editor\x00')

    def test_sync_rejects_unrelated_index_only_change(self):
        topic = self.sync_topic()
        self.prepare(topic)
        blob = self.git_at(topic, 'hash-object', '-w', '--stdin', input='other staged bytes').stdout.strip()
        self.git_at(topic, 'update-index', '--cacheinfo', '100644,' + blob + ',README')
        diagnosis = self.diagnosis(topic, ok=False)['operations'][0]
        self.assertEqual(diagnosis['unattributed_paths'], ['README'])
        self.assertEqual((topic / 'README').read_bytes(), b'base\n')
        self.prepare(topic, ok=False)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(OperationTests(name) for name in OperationTests.__dict__
                              if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
