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

    def test_wl_slot_registration(self):
        sys.path.insert(0, str(ROOT / 'bin'))
        try:
            import branch_management
        finally:
            sys.path.pop(0)
        slot = Path('slots/1').resolve()
        def status(**task):
            return {'tasks': [{'task': 'other', 'worktree': 'slots/2', 'stage': 'ready', 'branch': 'other', 'finish': None},
                              {'task': 'alpha', 'worktree': 'slots/1', 'stage': 'ready', 'branch': 'alpha', 'finish': None, **task}]}
        self.assertEqual(branch_management.wl_registration(status(), slot, 'alpha', 'abc'),
                         {'task': 'alpha', 'tip': 'abc', 'branch': 'alpha'})
        self.assertIsNone(branch_management.wl_registration(status(), Path('slots/3').resolve(), 'alpha', 'abc'))
        for task, branch in (({}, 'main'), ({'stage': 'claimed'}, 'alpha'), ({'finish': {'stage': 'prepared'}}, 'alpha')):
            with self.assertRaises(branch_management.BranchError):
                branch_management.wl_registration(status(**task), slot, branch, 'abc')

if __name__ == '__main__':
    unittest.main()
