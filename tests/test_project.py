"""Installed-wheel entry and dependency boundary, outside the source checkout."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


class ProjectCliTests(unittest.TestCase):
    def test_explicit_sources_independent_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'inputs/rules'
            source.mkdir(parents=True)
            rule = source / 'policy.md'
            rule.write_text('---\nroot: false\ntargets: [codexcli, claudecode]\n---\nOnly the selected project policy.\n', encoding='utf-8')
            config = root / 'placement.json'
            config.write_text(json.dumps(dict(version=1, input_roots=['inputs'],
                targets=['codexcli','claudecode','grokcli'], features=['rules','skills'],
                output_root='project', **{'global': False})), encoding='utf-8')
            env = os.environ.copy()
            env.pop('PYTHONPATH', None)
            def run(*args):
                return subprocess.run([sys.executable, '-m', 'agent_rules_manager.project', *args],
                    cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(run('--version').returncode, 0)
            self.assertNotEqual(run('apply').returncode, 0)
            result = run('apply', '--config', str(config))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual((root/'project/AGENTS.md').read_text().strip(), 'Only the selected project policy.')
            self.assertEqual(run('check', '--config', str(config)).returncode, 0)
            before = {p: (p.read_bytes(),p.stat().st_mtime_ns) for p in (root/'project').rglob('*') if p.is_file()}
            self.assertEqual(run('apply', '--config', str(config)).returncode, 0)
            self.assertEqual(before, {p: (p.read_bytes(),p.stat().st_mtime_ns) for p in (root/'project').rglob('*') if p.is_file()})
            rule.unlink()
            self.assertNotEqual(run('check', '--config', str(config)).returncode, 0)
            result = run('apply', '--config', str(config))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertFalse((root/'project/AGENTS.md').exists())
            script = ('import importlib.util,agent_rules_manager; '
                      'from pathlib import Path; '
                      'p=Path(agent_rules_manager.__file__).parent; '
                      'assert not (p/"bin/place.py").exists(); '
                      'assert not (p/"bin/branch_management.py").exists(); '
                      'assert not (p/"bin/necessity_install.py").exists(); '
                      'assert not (p/"placement.json").exists(); '
                      'assert not (p/"rules").exists(); '
                      'assert not (p/"skills").exists()')
            result = subprocess.run([sys.executable,'-c',script], cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
