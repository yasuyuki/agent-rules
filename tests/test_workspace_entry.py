"""Checkout shims and pinned-consumer boundary; package owns lifecycle behavior."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WorkspaceEntryTests(unittest.TestCase):
    def test_place_branch_delegates_to_independent_cli(self):
        result = subprocess.run([sys.executable, str(ROOT / 'bin/place.py'), 'branch', '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('workspace-lifecycle', result.stdout)
        self.assertIn('finish', result.stdout)

    def test_new_source_refuses_legacy_registry_without_touching_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', directory], check=True)
            state = root / '.git/agent-branches/state.json'
            state.parent.mkdir(); state.write_text('{"version":1}')
            result = subprocess.run([sys.executable, str(ROOT / 'bin/place.py'), 'branch',
                                     '--repo', directory, 'status'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('legacy', result.stderr)
            self.assertEqual(state.read_text(), '{"version":1}')
            self.assertFalse((root / '.git/workspace-lifecycle').exists())

if __name__ == '__main__':
    unittest.main()
