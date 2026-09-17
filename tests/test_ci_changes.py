"""Selection uses full Git ranges and only admits classification-authorized skips."""
import importlib.util
import itertools
import json
import os
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('ci_changes', Path(__file__).with_name('ci_changes.py'))
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


class ChangesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'CI fixture')
        self.git('config', 'user.email', 'ci@example.invalid')
        self.write('docs/guide.md', '# Guide\n')
        self.write('README.md', '# Package\n')
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def push(self, base=None):
        return ci.selection(self.root, 'push', {'before': base or self.base, 'after': self.git('rev-parse', 'HEAD')})

    def test_explanation_and_readme(self):
        self.write('docs/new.md', '# New\n')
        self.commit()
        self.assertEqual((self.push()['full'], self.push()['readme']), (False, False))
        self.write('README.md', '# Updated package\n')
        self.commit()
        self.assertEqual((self.push()['full'], self.push()['readme']), (False, True))

    def test_agent_behavior_unknown_and_mixed_changes(self):
        for name in ('skills/optimize-agent-docs/SKILL.md', 'skills/optimize-human-docs/SKILL.md',
                     'rules/example.rule.md', 'docs/AGENTS.md', 'AGENTS.md',
                     '.claude/rules/a.md', 'docs/tool.py', 'new.md', 'bin/code.py', '.github/workflows/ci.yml'):
            with self.subTest(name=name):
                self.write(name, '# Instructions\n')
                self.assertTrue(ci.classify(self.root, [('M', 'README.md'), ('A', name)])['full'])
        self.write('docs/managed.md', '<!-- agent-rules:begin example -->\n')
        self.assertTrue(ci.classify(self.root, [('A', 'docs/managed.md')])['full'])

    def test_push_range_includes_earlier_code_commit(self):
        self.write('code.py', 'pass\n')
        self.commit()
        self.write('docs/guide.md', '# New guide\n')
        self.commit()
        self.assertTrue(self.push()['full'])

    def test_pr_uses_merge_base_not_latest_commit_or_base_tip(self):
        self.git('checkout', '-qb', 'topic')
        self.write('docs/new.md', '# New\n')
        self.commit()
        self.write('docs/guide.md', '# Updated\n')
        head = self.commit()
        self.git('checkout', 'main')
        self.write('main-only.py', 'pass\n')
        base = self.commit()
        self.git('checkout', 'topic')
        result = ci.selection(self.root, 'pull_request', {'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}})
        self.assertFalse(result['full'])
        self.assertEqual(result['base'], self.base)
        self.assertEqual(len(result['changes']), 2)

    def test_deleted_and_renamed_docs_require_full(self):
        self.git('mv', 'docs/guide.md', 'docs/renamed.md')
        self.commit()
        self.assertTrue(self.push()['full'])
        base = self.git('rev-parse', 'HEAD')
        self.git('rm', 'docs/renamed.md')
        self.commit()
        self.assertTrue(self.push(base)['full'])

    def test_doc_mode_change_requires_full(self):
        self.git('update-index', '--chmod=+x', 'README.md')
        self.git('commit', '-qm', 'mode fixture')
        self.assertTrue(self.push()['full'])

    def test_missing_empty_and_invalid_range_require_full(self):
        for name, event in [('push', {}), ('push', {'before': '0' * 40, 'after': self.base}),
                            ('push', {'before': 'a' * 40, 'after': self.base}),
                            ('push', {'before': '--help', 'after': self.base}),
                            ('pull_request', {}), ('workflow_dispatch', {})]:
            with self.subTest(event=event):
                self.assertTrue(ci.selection(self.root, name, event)['full'])
        self.assertTrue(self.push()['full'])
        self.assertTrue(ci.classify(self.root, [('M', 'docs/missing.md')])['full'])

    def test_entrypoint_writes_outputs_and_returns_gate_failure(self):
        event = self.root / 'event.json'
        output = self.root / 'output.txt'
        event.write_text('{}', encoding='utf-8')
        env = dict(os.environ, GITHUB_EVENT_PATH=str(event), GITHUB_OUTPUT=str(output),
                   GITHUB_EVENT_NAME='push')
        command = [sys.executable, str(Path(ci.__file__))]
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('full=true', output.read_text())
        self.assertTrue(json.loads(result.stdout)['full'])
        env['CI_NEEDS'] = json.dumps({'documentation': {'result': 'success', 'outputs': {'full': 'true'}},
                                     'checkout': {'result': 'success'}, 'package': {'result': 'cancelled'}})
        result = subprocess.run(command + ['--gate'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_gate_requires_success_or_only_intentional_skip(self):
        states = ('success', 'failure', 'cancelled', 'skipped', None)
        for full, light, checkout, package in itertools.product(('true', 'false', '', None), states, states, states):
            needs = {'documentation': {'result': light, 'outputs': {'full': full}},
                     'checkout': {'result': checkout}, 'package': {'result': package}}
            expected = light == 'success' and ((full == 'true' and checkout == package == 'success')
                                               or (full == 'false' and checkout == package == 'skipped'))
            self.assertEqual(ci.gate(needs), expected, needs)
        self.assertFalse(ci.gate({}))


if __name__ == '__main__':
    unittest.main()
