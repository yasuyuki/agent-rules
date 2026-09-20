"""Public launch requires only its one-way shim and independently packaged owner."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeEntryTests(unittest.TestCase):
    def test_launch_without_any_legacy_engine_and_reject_old_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            checkout = root / 'checkout'
            (checkout / 'bin').mkdir(parents=True)
            for name in ('place.py', 'runtime_entry.py'):
                shutil.copy2(ROOT / 'bin' / name, checkout / 'bin' / name)
            shutil.copytree(ROOT / 'packages/agent-runtime/src', checkout / 'packages/agent-runtime/src',
                            ignore=shutil.ignore_patterns('__pycache__'))
            bridge = root / 'bridge.py'
            bridge.write_text('import subprocess,sys\nargs=sys.argv[1:]\n'
                              'raise SystemExit(subprocess.call(args[args.index("--")+1:]))\n', encoding='utf-8')
            vendor = root / 'vendor.py'
            vendor.write_text('import json,os,sys\nprint(json.dumps({"cwd":os.getcwd(),"argv":sys.argv[1:]}))\n', encoding='utf-8')
            config = root / 'runtime.json'
            config.write_text(json.dumps({'version': 1,
                'tools': {'claude': {'argv': [sys.executable, str(vendor)]}},
                'workspaces': [{'id': 'sample', 'root': str(root), 'state': 'active', 'tools': ['claude'],
                    'lifecycle': {'argv': [sys.executable, str(bridge)], 'interface': 'resolve-run-v1', 'source': str(bridge),
                        'pins': [{'path': str(bridge), 'sha256': hashlib.sha256(bridge.read_bytes()).hexdigest()}]}}]}), encoding='utf-8')
            env = {k: v for k, v in os.environ.items() if k not in {'AGENT_RUNTIME_DEPTH', 'PYTHONPATH'}}
            for selection in (['standard-start'], ['start']):
                args = [sys.executable, str(checkout / 'bin/place.py'), *selection, '--config', str(config)]
                if selection == ['start']:
                    args.append('sample')
                result = subprocess.run([*args, 'claude', '--', 'two words', '日本語'], cwd=root,
                                        env=env, capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'cwd': str(root), 'argv': ['two words', '日本語']})
            config.write_text(json.dumps({'version': 2, 'declaration': 'missing.md'}))
            result = subprocess.run([sys.executable, str(checkout / 'bin/place.py'), 'standard-start',
                                     '--config', str(config), 'claude'], cwd=root, env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('configuration', result.stderr)
            self.assertNotIn('ModuleNotFoundError', result.stderr)


if __name__ == '__main__':
    unittest.main()
