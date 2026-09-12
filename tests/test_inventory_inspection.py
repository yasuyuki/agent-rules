"""Portable tests for the read-only Grok inspection helper."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'bin' / 'inventory_inspection.py'
SPEC = importlib.util.spec_from_file_location('inventory_inspection', SOURCE)
inspection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspection)


class InventoryInspectionTests(unittest.TestCase):
    def setUp(self):
        self.cwd = os.path.abspath('inventory-inspection-work')
        self.instruction = os.path.join(self.cwd, 'AGENTS.md')
        self.skill = os.path.join(
            self.cwd, '.grok', 'skills', 'maintain-environment-inventory', 'SKILL.md')
        self.executable = os.path.join(self.cwd, 'bin', 'grok')
        self.normalized_cwd = os.path.normcase(os.path.normpath(self.cwd))
        self.normalized_instruction = os.path.normcase(os.path.normpath(self.instruction))
        self.normalized_skill = os.path.normcase(os.path.normpath(self.skill))

    def payload(self, **changes):
        result = {
            'cwd': self.cwd,
            'projectRoot': self.cwd + os.sep,
            'projectTrusted': True,
            'projectInstructions': [{
                'path': self.instruction, 'scope': 'project', 'fileType': 'agents_md',
                'sizeBytes': 42, 'approxTokens': 11,
            }],
            'skills': [{
                'name': 'maintain-environment-inventory', 'description': 'inventory',
                'source': {'type': 'project', 'path': self.skill}, 'userInvocable': True,
            }],
            'ignored': {'could': 'contain configuration'},
        }
        result.update(changes)
        return result

    def runner(self, payload, returncode=0, stderr='secret-token'):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            stdout = payload if isinstance(payload, str) else json.dumps(payload)
            return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
        return run, calls

    def inspect(self, payload, returncode=0):
        runner, calls = self.runner(payload, returncode)
        result = inspection.inspect_grok(
            executable=self.executable, cwd=self.cwd,
            instruction_paths=[self.instruction], skill_paths=[self.skill], runner=runner)
        return result, calls

    def test_returns_only_required_sanitized_discovery(self):
        result, calls = self.inspect(self.payload())
        self.assertEqual(result, {
            'cwd': self.normalized_cwd, 'projectTrusted': True,
            'instructionPaths': [self.normalized_instruction],
            'skillPaths': [self.normalized_skill],
        })
        self.assertEqual(calls, [([
            self.executable, 'inspect', '--json'], {
            'cwd': self.normalized_cwd, 'stdin': subprocess.DEVNULL, 'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE, 'text': True,
        })])

    def test_rejects_foreign_cwd(self):
        foreign = os.path.abspath('inventory-inspection-foreign')
        with self.assertRaisesRegex(ValueError, 'different cwd for cwd ') as error:
            self.inspect(self.payload(cwd=foreign))
        self.assertIn(self.normalized_cwd, str(error.exception))
        self.assertNotIn(foreign, str(error.exception))

    def test_rejects_foreign_project_root(self):
        foreign_root = os.path.abspath('inventory-inspection-foreign-root')
        with self.assertRaisesRegex(ValueError, 'foreign project root for cwd '):
            self.inspect(self.payload(projectRoot=foreign_root))

    def test_rejects_untrusted_project(self):
        with self.assertRaisesRegex(ValueError, 'untrusted project for cwd '):
            self.inspect(self.payload(projectTrusted=False))

    def test_home_only_expectations_do_not_require_project_trust(self):
        home_skill = os.path.abspath('inventory-inspection-home/SKILL.md')
        payload = self.payload(projectTrusted=False, projectInstructions=[], skills=[{
            'name': 'personal', 'description': 'home skill',
            'source': {'type': 'user', 'path': home_skill}, 'userInvocable': True,
        }])
        runner, _ = self.runner(payload)
        result = inspection.inspect_grok(
            executable=self.executable, cwd=self.cwd,
            instruction_paths=[], skill_paths=[home_skill], runner=runner)
        self.assertFalse(result['projectTrusted'])

    def test_rejects_required_paths_not_discovered(self):
        with self.assertRaisesRegex(ValueError, 'required instructions for cwd '):
            self.inspect(self.payload(projectInstructions=[]))
        with self.assertRaisesRegex(ValueError, 'required skills for cwd '):
            self.inspect(self.payload(skills=[]))

    def test_rejects_failed_or_invalid_output_without_echoing_stderr(self):
        for payload, returncode, reason in [
                (self.payload(), 1, 'failed'), ('not json', 0, 'invalid JSON')]:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, reason) as error:
                    self.inspect(payload, returncode)
                self.assertNotIn('secret-token', str(error.exception))

    def test_failure_does_not_change_a_sentinel_configuration(self):
        sentinel = {'trust': 'unchanged'}
        runner, _ = self.runner(self.payload(cwd=os.path.abspath('inventory-inspection-foreign')))
        with self.assertRaises(ValueError):
            inspection.inspect_grok(
                executable=self.executable, cwd=self.cwd,
                instruction_paths=[self.instruction], skill_paths=[self.skill], runner=runner)
        self.assertEqual(sentinel, {'trust': 'unchanged'})

    def test_ignores_extra_legacy_metadata_and_unrequested_kinds(self):
        payload = self.payload(projectInstructions=[
            {'path': self.instruction, 'scope': 'user', 'fileType': 'custom'},
            {'path': os.path.abspath('other-instruction'), 'scope': 'plugin'},
        ], skills=[
            {'source': {'path': self.skill}},
            {'source': {'path': os.path.abspath('other-skill')}, 'plugin': True},
            {'source': {'type': 'plugin'}},
        ])
        result, _ = self.inspect(payload)
        self.assertEqual(result['instructionPaths'], [self.normalized_instruction])
        self.assertEqual(result['skillPaths'], [self.normalized_skill])

    def test_relative_reported_paths_cannot_satisfy_expectations(self):
        with self.assertRaisesRegex(ValueError, 'different cwd'):
            self.inspect(self.payload(cwd='inventory-inspection-work'))
        with self.assertRaisesRegex(ValueError, 'required instructions'):
            self.inspect(self.payload(projectInstructions=[{'path': 'AGENTS.md'}]))
        with self.assertRaisesRegex(ValueError, 'required skills'):
            self.inspect(self.payload(skills=[{'source': {'path': 'SKILL.md'}}]))


if __name__ == '__main__':
    unittest.main()
