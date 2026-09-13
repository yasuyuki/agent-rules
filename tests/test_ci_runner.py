"""Behavioral tests for the CI unittest orchestrator."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SOURCE = Path(__file__).with_name('ci_runner.py')
SPEC = importlib.util.spec_from_file_location('ci_runner', SOURCE)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class CiRunnerTests(unittest.TestCase):
    def module(self, directory):
        path = Path(directory) / 'synthetic_ci_tests.py'
        path.write_text('''import os, subprocess, sys, time, unittest\n
class Cases(unittest.TestCase):
    def test_pass(self): self._ci_metrics = {"gitCommandCount": 2}
    def test_fail(self): self.fail("expected")
    @unittest.expectedFailure
    def test_expected_failure(self): self.fail("expected failure")
    @unittest.skip("expected")
    def test_skip(self): pass
    def test_subtest(self):
        with self.subTest("bad"): self.assertEqual(1, 2)
    def test_sleep(self): time.sleep(30)
    def test_descendant(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        open(os.environ["CI_RUNNER_PID_FILE"], "w").write(str(child.pid))
        time.sleep(30)
class SetupError(unittest.TestCase):
    @classmethod
    def setUpClass(cls): raise RuntimeError("setup expected")
    def test_never_runs(self): pass
''', encoding='utf-8')
        return path

    def invoke(self, directory, output, *names, **options):
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(directory) + os.pathsep + str(SOURCE.parent)
        environment.update(options.get('environment', {}))
        return subprocess.run([sys.executable, str(SOURCE), '--output', str(output),
                               '--timeout', str(options.get('timeout', 3)),
                               '--workers', str(options.get('workers', 1)), *names],
                              env=environment, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=15)

    def test_collect_uses_recovery_load_tests_without_running_it(self):
        ids = runner.collect(['test_branch_recovery'])
        self.assertTrue(any('.RecoveryTests.' in test_id for test_id in ids))
        self.assertFalse(any('.BranchManagementTests.' in test_id for test_id in ids))

    def test_shards_are_deterministic_and_persist_pass_fail_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            self.module(directory)
            output = Path(directory) / 'metrics.json'
            result = self.invoke(directory, output, 'synthetic_ci_tests.Cases.test_pass',
                                 'synthetic_ci_tests.Cases.test_fail',
                                 'synthetic_ci_tests.Cases.test_expected_failure',
                                 'synthetic_ci_tests.Cases.test_skip', workers=2)
            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(data['tests']['synthetic_ci_tests.Cases.test_pass']['status'], 'pass')
            self.assertEqual(data['tests']['synthetic_ci_tests.Cases.test_fail']['status'], 'failure')
            self.assertEqual(data['tests']['synthetic_ci_tests.Cases.test_expected_failure']['status'],
                             'expected_failure')
            self.assertEqual(data['tests']['synthetic_ci_tests.Cases.test_skip']['status'], 'skip')
            self.assertEqual(data['tests']['synthetic_ci_tests.Cases.test_pass']['metrics'],
                             {'gitCommandCount': 2})
            self.assertIn('metadata', data)
            self.assertEqual([shard['ids'] for shard in data['shards']], [
                ['synthetic_ci_tests.Cases.test_expected_failure',
                 'synthetic_ci_tests.Cases.test_pass'],
                ['synthetic_ci_tests.Cases.test_fail', 'synthetic_ci_tests.Cases.test_skip']])
            self.assertIn('ci_runner start', result.stderr)

    def test_command_stage_records_exit_code_without_capturing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'metrics.json'
            result = subprocess.run([sys.executable, str(SOURCE), '--output', str(output),
                                     '--timeout', '3', '--command', sys.executable, '-c',
                                     'import sys; print("secret", file=sys.stderr); sys.exit(7)'],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result.returncode, 7)
            self.assertEqual(data['shards'][0]['exitCode'], 7)
            self.assertNotIn('secret', json.dumps(data))

    def test_timeout_reaps_child_process_group_and_keeps_partial_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            self.module(directory)
            output = Path(directory) / 'metrics.json'
            pid_file = Path(directory) / 'child.pid'
            started = time.monotonic()
            result = self.invoke(directory, output, 'synthetic_ci_tests.Cases.test_descendant', timeout=3,
                                 environment={'CI_RUNNER_PID_FILE': str(pid_file)})
            self.assertLess(time.monotonic() - started, 10)
            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result.returncode, 1)
            self.assertTrue(data['shards'][0]['timedOut'])
            self.assertEqual(data['shards'][0]['lastTest'],
                             'synthetic_ci_tests.Cases.test_descendant')
            self.assertEqual(data['tests']['synthetic_ci_tests.Cases.test_descendant']['status'], 'running')
            self.assertIn('ci_runner timeout', result.stderr)
            pid = int(pid_file.read_text())
            for unused in range(50):
                if not runner._pid_alive(pid):
                    break
                time.sleep(.02)
            else:
                self.fail('runner did not reap descendant %s' % pid)

    def test_fixture_and_subtest_errors_are_recorded_and_printed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.module(directory)
            output = Path(directory) / 'metrics.json'
            result = self.invoke(directory, output, 'synthetic_ci_tests.Cases.test_subtest',
                                 'synthetic_ci_tests.SetupError.test_never_runs')
            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(data['tests']['synthetic_ci_tests.Cases.test_subtest']['status'], 'failure')
            self.assertTrue(any(record['status'] == 'error' for record in data['tests'].values()))
            self.assertIn('AssertionError', result.stderr)
            self.assertIn('RuntimeError', result.stderr)

    def test_invalid_or_empty_collection_returns_a_failure_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'metrics.json'
            result = self.invoke(directory, output, 'not_a_real_test')
            self.assertEqual(result.returncode, 1)
            self.assertIn('collectionError', json.loads(output.read_text(encoding='utf-8')))

    def test_command_launch_failure_retains_nonzero_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'command.json'
            with unittest.mock.patch.object(runner.subprocess, 'Popen', side_effect=FileNotFoundError('secret')):
                self.assertEqual(runner.run_command(['missing-executable'], output, 3), 1)
            data = json.loads(output.read_text())
            self.assertEqual(data['spawnError'], 'FileNotFoundError')
            self.assertIsNone(data['shards'][0]['exitCode'])
            self.assertNotIn('secret', json.dumps(data))

    def test_metrics_allow_only_numeric_observations(self):
        self.assertEqual(runner._safe_metrics({'gitCommandCount': 2, 'fixtureSeconds': .1}),
                         {'gitCommandCount': 2, 'fixtureSeconds': .1})
        self.assertEqual(runner._safe_metrics({'output': 'secret'}), {'invalid': True})

    def test_partial_spawn_failure_reaps_already_started_shard(self):
        class Child:
            pid = 123
            def poll(self): return None
            def wait(self, timeout=None): return -9
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'metrics.json'
            with mock.patch.object(runner.subprocess, 'Popen', side_effect=[Child(), OSError('spawn failed')]), \
                    mock.patch.object(runner, '_terminate', return_value=True) as terminate:
                self.assertEqual(runner.run_parent(['first', 'second'], output, 2, 3), 1)
            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(terminate.call_count, 1)
            self.assertEqual(data['spawnError'], 'spawn failed')


if __name__ == '__main__':
    unittest.main()
