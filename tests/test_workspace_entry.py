"""The placement CLI exposes no workspace mutation compatibility command."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WorkspaceEntryTests(unittest.TestCase):
    def test_place_branch_is_not_a_command(self):
        result = subprocess.run([sys.executable, str(ROOT / 'bin/place.py'), 'branch', '--help'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid choice', result.stderr)

    def test_inventory_compat_has_no_cli_main(self):
        result = subprocess.run([sys.executable, '-c',
                                 'import sys; sys.path.insert(0, sys.argv[1]); '
                                 'import branch_management; '
                                 'assert not hasattr(branch_management, "main"); '
                                 'assert callable(branch_management.registered_checkout)',
                                 str(ROOT / 'bin')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == '__main__':
    unittest.main()
