import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'bin' / 'repair_legacy_tip.py'


def sha(data): return hashlib.sha256(data).hexdigest()


def git(repo, *args, text=False):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=text).stdout


OWNER = '''
import contextlib, json, subprocess
from pathlib import Path
@contextlib.contextmanager
def locked(repo):
 d=Path(repo)/'.git'/'agent-branches'; yield d,json.loads((d/'state.json').read_text())
def assert_install(repo, directory, state): pass
def checkout(repo, state): return '540',state['tasks']['540']
def save(directory, state): (Path(directory)/'state.json').write_text(json.dumps(state, sort_keys=True, separators=(',', ':')))
def git(repo, *args): return git_bytes(repo, *args).decode().strip()
def oid(repo, ref): return git_bytes(repo, 'rev-parse', ref).decode().strip()
def ancestor(repo, old, new): return subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',old,new]).returncode == 0
def git_bytes(repo, *args): return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True).stdout
'''


class LegacyTipRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(); self.repo = self.base / 'repo'; self.repo.mkdir()
        git(self.repo, 'init'); git(self.repo, 'config', 'user.name', 'Test'); git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'base').write_text('old\n'); (self.repo / 'staged').write_text('base\n'); (self.repo / 'worktree').write_text('base\n')
        git(self.repo, 'add', 'base', 'staged', 'worktree'); git(self.repo, 'commit', '-m', 'old')
        self.old = git(self.repo, 'rev-parse', 'HEAD', text=True).strip()
        (self.repo / 'base').write_text('new\n'); git(self.repo, 'add', 'base'); git(self.repo, 'commit', '-m', 'new')
        self.new = git(self.repo, 'rev-parse', 'HEAD', text=True).strip(); self.branch = git(self.repo, 'branch', '--show-current', text=True).strip()
        (self.repo / 'staged').write_text('index\n'); git(self.repo, 'add', 'staged')
        (self.repo / 'worktree').write_text('worktree\n')
        self.owner = self.base / 'owner'; (self.owner / 'bin').mkdir(parents=True); (self.owner / 'bin' / 'branch_management.py').write_text(OWNER)
        self.state = self.repo / '.git' / 'agent-branches' / 'state.json'; self.state.parent.mkdir()
        self.state.write_text(json.dumps({'version':1,'default': self.branch, 'source':str(self.owner), 'source_hashes':{'bin/branch_management.py':sha((self.owner/'bin'/'branch_management.py').read_bytes())}, 'permits':{'other':{'keep':True}}, 'merges':{'other':{'task':'broken'}}, 'picks':{'other:keep':{'keep':True}}, 'tip_repairs':[{'task':'broken','keep':True}], 'tasks': {'540': {'branch': self.branch, 'worktree': str(self.repo), 'into': self.branch, 'tip': self.old, 'request': 'issue/540', 'base': self.old}, 'broken': {'branch':'broken','worktree':'x','into':'x','tip':'dead','integrated':{'keep':True}}}}, sort_keys=True))
        self.index = self.base / 'index.patch'; self.worktree = self.base / 'worktree.patch'
        self.index.write_bytes(git(self.repo, 'diff', '--cached', '--binary', '--no-ext-diff'))
        self.worktree.write_bytes(git(self.repo, 'diff', '--binary', '--no-ext-diff'))
        self.evidence = self.base / 'evidence.json'
        self.evidence.write_text(json.dumps({'version': 1, 'task': '540', 'branch': self.branch, 'top': str(self.repo), 'old': self.old, 'new': self.new, 'untracked': [], 'artifacts': {'index_patch': {'path': self.index.name, 'sha256': sha(self.index.read_bytes())}, 'worktree_patch': {'path': self.worktree.name, 'sha256': sha(self.worktree.read_bytes())}}}, sort_keys=True))

    def invoke(self, **changes):
        values = {'repo': self.repo, 'owner-source': self.owner, 'owner-module-sha256': sha((self.owner/'bin'/'branch_management.py').read_bytes()), 'task': '540', 'branch': self.branch, 'top': self.repo, 'old': self.old, 'new': self.new, 'approval': 'issue/9', 'evidence': self.evidence, 'evidence-sha256': sha(self.evidence.read_bytes())}
        values.update(changes)
        command = [sys.executable, str(SCRIPT)] + [item for key, value in values.items() for item in ('--' + key, str(value))]
        return subprocess.run(command, capture_output=True, text=True)

    def git_snapshot(self):
        return (git(self.repo, 'rev-parse', 'HEAD'), git(self.repo, 'rev-parse', 'refs/heads/' + self.branch),
                git(self.repo, 'ls-files', '--stage', '-z'), git(self.repo, 'diff', '--cached', '--binary', '--no-ext-diff'),
                git(self.repo, 'diff', '--binary', '--no-ext-diff'), git(self.repo, 'ls-files', '--others', '--exclude-standard', '-z'))

    def refuse(self, mutate=None, **changes):
        if mutate: mutate()
        state, git_state = self.state.read_bytes(), self.git_snapshot()
        result = self.invoke(**changes)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state.read_bytes(), state)
        self.assertEqual(self.git_snapshot(), git_state)

    def test_repairs_only_tip_and_receipt_preserving_dirty_bytes_and_replays(self):
        original, before = json.loads(self.state.read_text()), self.git_snapshot()
        result = self.invoke(); self.assertEqual(result.returncode, 0, result.stderr)
        saved = self.state.read_bytes(); state = json.loads(saved)
        self.assertEqual(state['tasks']['540']['tip'], self.new); self.assertEqual(state['tasks']['broken'], original['tasks']['broken'])
        self.assertEqual(state['permits'], original['permits']); self.assertEqual(state['merges'], original['merges']); self.assertEqual(state['picks'], original['picks'])
        self.assertEqual(state['tip_repairs'][:-1], original['tip_repairs']); self.assertEqual(before, self.git_snapshot())
        replay = self.invoke(); self.assertEqual(replay.returncode, 0, replay.stderr); self.assertEqual(self.state.read_bytes(), saved)

    def test_refuses_bad_identity_or_unsafe_state_without_mutation(self):
        for change in ({'owner-source': self.base / 'wrong'}, {'owner-module-sha256': '0' * 64}, {'old': self.new}, {'evidence-sha256': '0' * 64}, {'approval': ''}):
            with self.subTest(change=change):
                self.refuse(**change)
        for name, mutate in (
            ('creating', lambda: self.state.write_text(json.dumps({**json.loads(self.state.read_text()), 'tasks': {**json.loads(self.state.read_text())['tasks'], '540': {**json.loads(self.state.read_text())['tasks']['540'], 'creating': True}}}))),
            ('permit', lambda: self.state.write_text(json.dumps({**json.loads(self.state.read_text()), 'permits': {self.branch: {'task':'540'}}}))),
            ('destination-merge', lambda: self.state.write_text(json.dumps({**json.loads(self.state.read_text()), 'merges': {self.branch: {'task':'other'}}}))),
            ('source-merge', lambda: self.state.write_text(json.dumps({**json.loads(self.state.read_text()), 'merges': {'other': {'task':'540'}}}))),
            ('pick', lambda: self.state.write_text(json.dumps({**json.loads(self.state.read_text()), 'picks': {self.branch + ':x': {}}}))),
        ):
            with self.subTest(name=name): self.refuse(mutate)
            self.setUp()
        for marker in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','sequencer'):
            with self.subTest(marker=marker):
                target = self.repo / '.git' / marker
                if marker == 'sequencer': target.mkdir()
                else: target.write_text('x')
                self.refuse()
            self.setUp()
        self.index.write_bytes(b'changed artifact')
        self.refuse()
        self.setUp()
        document = json.loads(self.state.read_text()); document['tasks']['540']['tip'] = self.new; self.state.write_text(json.dumps(document))
        self.refuse()
        self.setUp()
        evidence = json.loads(self.evidence.read_text()); evidence['task'] = 'other'; self.evidence.write_text(json.dumps(evidence))
        self.refuse(task='other')
        self.setUp()
        evidence = json.loads(self.evidence.read_text()); evidence['branch'] = 'other'; self.evidence.write_text(json.dumps(evidence))
        self.refuse(branch='other')


if __name__ == '__main__': unittest.main()
