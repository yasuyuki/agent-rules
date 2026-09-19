"""The checkout preflight delegates to the independently tested policy owner."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PreflightCompatibilityTests(unittest.TestCase):
    def test_help_delegates_to_package(self):
        result = subprocess.run([sys.executable, str(ROOT / 'bin/push_preflight.py'), '--help'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--policy', result.stdout)
        self.assertIn('--user-intent', result.stdout)
