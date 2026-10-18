"""Installed-wheel entry and dependency boundary, outside the source checkout."""
from pathlib import Path
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest


FIXTURE = Path(__file__).parent / 'fixtures/native-e2e'


def native_probe_sources(root, run_id):
    """Keep expected values outside the consumer workspace and vary each run."""
    source = root / 'inputs'
    rule_dir = source / 'rules'
    skill_dir = source / 'skills' / f'e2e-probe-{run_id}'
    rule_dir.mkdir(parents=True)
    skill_dir.mkdir(parents=True)
    rule = 'RULE_' + secrets.token_hex(16)
    skill = 'SKILL_' + secrets.token_hex(16)
    (rule_dir / 'native-probe.md').write_text(
        (FIXTURE / 'rule.md').read_text(encoding='utf-8').replace('@RULE_NONCE@', rule[5:]),
        encoding='utf-8')
    (skill_dir / 'SKILL.md').write_text(
        (FIXTURE / 'SKILL.md').read_text(encoding='utf-8').replace('@SKILL_NAME@', skill_dir.name),
        encoding='utf-8')
    (skill_dir / 'support.txt').write_text(
        (FIXTURE / 'support.txt').read_text(encoding='utf-8').replace('@SKILL_NONCE@', skill[6:]),
        encoding='utf-8')
    shutil.copyfile(FIXTURE / 'proof.py', skill_dir / 'proof.py')
    return source, rule, skill, skill_dir.name


class ProjectCliTests(unittest.TestCase):
    def test_native_probe_offline_round_trip(self):
        rulesync = os.environ.get('RULESYNC_EXECUTABLE')
        self.assertTrue(rulesync and Path(rulesync).is_file(), 'fixed Rulesync executable required')
        entry = Path(sys.executable).parent / ('agent-rules.exe' if os.name == 'nt' else 'agent-rules')
        self.assertTrue(entry.is_file(), 'test requires the installed wheel entry')
        cases = (
            ('claude', ['claudecode'], 1),
            ('codex', ['codexcli'], 1),
            ('agy', ['codexcli'], 1),
            ('cursor', ['cursor'], 1),
            ('all', ['codexcli', 'claudecode', 'cursor'], 2),
        )
        for case, targets, rounds in cases:
            for iteration in range(rounds):
                with self.subTest(case=case, iteration=iteration), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source, rule, skill, name = native_probe_sources(root, secrets.token_hex(6))
                    workspace = root / 'consumer'
                    workspace.mkdir()
                    sentinel = workspace / 'unowned.txt'
                    sentinel.write_bytes(b'leave this file intact\n')
                    config = root / 'placement.json'
                    config.write_text(json.dumps(dict(version=1, input_roots=['inputs'],
                        targets=targets, features=['rules', 'skills'], output_root='consumer',
                        **{'global': False})), encoding='utf-8')
                    env = os.environ.copy()
                    env.pop('PYTHONPATH', None)

                    def run(*args):
                        return subprocess.run([str(entry), *args, '--config', str(config),
                                               '--rulesync', rulesync], cwd=workspace, env=env,
                                              text=True, capture_output=True)

                    def tree():
                        return {path: (path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns)
                                for path in workspace.rglob('*')}

                    def preview():
                        before = tree()
                        result = run('preview')
                        self.assertEqual(before, tree())
                        if result.returncode:
                            self.assertEqual((result.returncode, result.stdout), (1, ''))
                            self.assertTrue(result.stderr.startswith('FAIL: '), result.stderr)
                            return None
                        plan = json.loads(result.stdout)
                        self.assertEqual(set(plan), {'changes', 'manifest'})
                        self.assertEqual(plan['changes'], sorted(plan['changes'], key=lambda c: c['path']))
                        return plan

                    added = preview()
                    self.assertEqual({c['operation'] for c in added['changes']}, {'add'})
                    self.assertTrue(added['manifest'])
                    self.assertEqual(run('apply').returncode, 0)
                    self.assertEqual(run('check').returncode, 0)
                    self.assertEqual(preview(), {'changes': [], 'manifest': False})
                    manifest = workspace / '.rulesync-ownership.json'
                    self.assertTrue(manifest.is_file())
                    owned = {item['path'] for item in json.loads(manifest.read_text())['files']}
                    expected = set()
                    if 'codexcli' in targets:
                        expected.update(('AGENTS.md', f'.agents/skills/{name}/SKILL.md',
                                         f'.agents/skills/{name}/support.txt', f'.agents/skills/{name}/proof.py'))
                    if 'claudecode' in targets:
                        expected.update((f'.claude/rules/native-probe.md',
                                         f'.claude/skills/{name}/SKILL.md',
                                         f'.claude/skills/{name}/support.txt',
                                         f'.claude/skills/{name}/proof.py'))
                    if 'cursor' in targets:
                        expected.update(('.cursor/rules/native-probe.mdc',
                                         f'.cursor/skills/{name}/SKILL.md',
                                         f'.cursor/skills/{name}/support.txt',
                                         f'.cursor/skills/{name}/proof.py'))
                    self.assertTrue(expected <= owned, (case, expected - owned, owned))
                    self.assertEqual({c['path'] for c in added['changes']}, owned)
                    self.assertTrue(any(rule in (workspace / rel).read_text(encoding='utf-8')
                                        for rel in owned if rel.endswith(('.md', '.mdc'))))
                    self.assertTrue(all(skill in (workspace / rel).read_text(encoding='utf-8')
                                        for rel in owned if rel.endswith('support.txt')))
                    before = {rel: ((workspace / rel).read_bytes(), (workspace / rel).stat().st_mtime_ns)
                              for rel in owned}
                    self.assertEqual(run('apply').returncode, 0)
                    self.assertEqual(before, {rel: ((workspace / rel).read_bytes(),
                                                   (workspace / rel).stat().st_mtime_ns) for rel in owned})
                    support = next(rel for rel in owned if rel.endswith('support.txt'))
                    (workspace / support).unlink()
                    self.assertNotEqual(run('check').returncode, 0)
                    self.assertIsNone(preview())
                    self.assertNotEqual(run('apply').returncode, 0)
                    (workspace / support).write_bytes(before[support][0])
                    self.assertEqual(run('check').returncode, 0)
                    shutil.rmtree(source / 'skills' / name)
                    (source / 'rules/native-probe.md').unlink()
                    self.assertNotEqual(run('check').returncode, 0)
                    self.assertEqual(preview(), {'changes': [{'path': rel, 'operation': 'delete'}
                                                             for rel in sorted(owned)], 'manifest': True})
                    rollback = run('apply')
                    self.assertEqual(rollback.returncode, 0, rollback.stdout + rollback.stderr)
                    self.assertEqual(run('check').returncode, 0)
                    self.assertTrue(all(not (workspace / rel).exists() for rel in owned))
                    self.assertEqual(sentinel.read_bytes(), b'leave this file intact\n')

    def test_explicit_sources_independent_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'inputs/rules'
            source.mkdir(parents=True)
            rule = source / 'policy.md'
            rule.write_text('---\nroot: false\ntargets: [codexcli, claudecode]\n---\nOnly the selected project policy.\n', encoding='utf-8')
            skill = source.parent / 'skills/license-proof'
            skill.mkdir(parents=True)
            skill_source = b'---\nname: license-proof\ndescription: Check packaged metadata preservation.\nlicense: MIT\n---\n# License proof\n'
            (skill / 'SKILL.md').write_bytes(skill_source)
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
            parser = """const {createRequire} = require('node:module');
const {readFileSync, realpathSync} = require('node:fs');
const matter = createRequire(realpathSync(process.argv[1]))('gray-matter');
process.stdout.write(JSON.stringify(process.argv.slice(2).map(p => matter(readFileSync(p, 'utf8')).data)));"""
            parsed = subprocess.run([shutil.which('node') or 'node', '-e', parser,
                                     os.environ['RULESYNC_EXECUTABLE'],
                                     *[str(root / 'project' / target / 'skills/license-proof/SKILL.md')
                                       for target in ('.agents', '.claude', '.grok')]],
                                    capture_output=True, text=True)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            self.assertEqual(json.loads(parsed.stdout),
                             [{'name': 'license-proof', 'description': 'Check packaged metadata preservation.',
                               'license': 'MIT'}] * 3)
            self.assertEqual((skill / 'SKILL.md').read_bytes(), skill_source)
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
                      'assert not (p/"placement.json").exists(); '
                      'assert not (p/"rules").exists(); '
                      'assert not (p/"skills").exists()')
            result = subprocess.run([sys.executable,'-c',script], cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__':
    unittest.main()
