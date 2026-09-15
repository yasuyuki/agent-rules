"""Real receive/Git/file writes through the ordinary start and resume entry."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


place = load('handoff_start_place', ROOT / 'bin/place.py')
fixture = load('handoff_fixture', ROOT / 'tests/test_handoff_receive.py')


class StartTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.ReceiveTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.dest
        declaration = self.root / 'placement.md'
        declaration.write_text('''<!-- BEGIN SITES TSV -->
```tsv
id\thost\tuser\thome\treach\tlaunch
site\tlocal\ttester\t{root}\tlocal\t
```
<!-- END SITES TSV -->
<!-- BEGIN WORKSPACES TSV -->
```tsv
id\tsite\tkind\tpath\textra
work\tsite\tdirect\t{root}\t
```
<!-- END WORKSPACES TSV -->
<!-- BEGIN LOCATIONS TSV -->
```tsv
id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind
work-codex\tworkspace\twork\tcodex\trequired\t\t\t\trules
```
<!-- END LOCATIONS TSV -->
<!-- BEGIN EXCEPTIONS TSV -->
```tsv
artifact\tlocation_id\trequirement\treason
```
<!-- END EXCEPTIONS TSV -->
'''.format(root=self.root.as_posix()), encoding='utf-8')
        self.assertEqual(place.main(['apply', '--declaration', str(declaration)]), 0)
        self.config = self.root / 'placement-start.json'
        self.assertEqual(place.main(['save-start-config', '--config', str(self.config),
                                     '--declaration', str(declaration)]), 0)
        fetch = patch.object(place.handoff_receive, '_fetch', fixture.receive._fetch)
        fetch.start()
        self.addCleanup(fetch.stop)

    def start(self, expected, *, independent=False, runner=None):
        def model(argv, **kwargs):
            self.assertEqual(argv, ['fixture-codex', 'resume', '--last'])
            self.assertEqual(Path(kwargs['cwd']), self.root)
            self.assertIn(expected, (self.root / 'HANDOFF.md').read_text(encoding='utf-8'))
            return SimpleNamespace(returncode=7)
        args = ['start', '--config', str(self.config)]
        if independent:
            args.append('--handoff-independent')
        return place.main(args + ['work', 'codex', '--', 'resume', '--last'],
                          runner=runner or model, resolver=lambda _: 'fixture-codex')

    def test_first_resume_repeat_and_correction_before_model(self):
        before_head = fixture.git(self.root, 'rev-parse', 'HEAD')
        before_index = fixture.git(self.root, 'ls-files', '--stage')
        self.assertEqual(self.start('first'), 7)
        before = (self.root / 'HANDOFF.md').read_bytes()
        self.assertEqual(self.start('first'), 7)
        self.assertEqual(before, (self.root / 'HANDOFF.md').read_bytes())
        self.fixture.update_source('corrected\n')
        self.assertEqual(self.start('corrected'), 7)
        self.assertEqual(fixture.git(self.root, 'rev-parse', 'HEAD'), before_head)
        self.assertEqual(fixture.git(self.root, 'ls-files', '--stage'), before_index)

    def test_unconfirmed_blocks_shared_work_but_allows_explicit_independent_work(self):
        self.assertEqual(self.start('first'), 7)
        def failed(*args):
            raise place.handoff_receive.ReceiveError('fetch failed')
        with patch.object(place.handoff_receive, '_fetch', failed):
            self.assertEqual(self.start('first', runner=lambda *a, **k: self.fail('model started')), 1)
            self.assertEqual(self.start('first', independent=True), 7)
        self.fixture.update_source('recovered\n')
        self.assertEqual(self.start('recovered'), 7)


if __name__ == '__main__':
    unittest.main()
