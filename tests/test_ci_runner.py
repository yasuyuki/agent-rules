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
        arguments = ['--output', str(output), '--timeout', str(options.get('timeout', 3)),
                     '--workers', str(options.get('workers', 1))]
        if options.get('timings'):
            arguments.extend(['--timings', str(options['timings'])])
        arguments.extend(['--shard-count', str(options.get('shard_count', 1)),
                          '--shard-index', str(options.get('shard_index', 0))])
        return subprocess.run([sys.executable, str(SOURCE), *arguments, *names],
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

    def test_lpt_assigns_skewed_timings_and_partitions_all_ids_once(self):
        ids = ['case.%s' % name for name in ('a', 'b', 'c', 'd', 'e')]
        with tempfile.TemporaryDirectory() as directory:
            timings = Path(directory) / 'timings.json'
            timings.write_text(json.dumps({'case.a': 100, 'case.b': 60, 'case.c': 5,
                                           'case.d': 4, 'case.e': 3}), encoding='utf-8')
            buckets = runner.assign_buckets(ids, 4, timings)
            self.assertEqual(buckets, [['case.a'], ['case.b'], ['case.c'], ['case.d', 'case.e']])
            assigned = [test_id for shard in buckets for test_id in shard]
            self.assertCountEqual(assigned, ids)
            self.assertEqual(len(assigned), len(set(assigned)))

    def test_actual_partitions_are_disjoint_and_cover_collected_synthetic_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            self.module(directory)
            names = ['synthetic_ci_tests.Cases.test_pass',
                     'synthetic_ci_tests.Cases.test_skip',
                     'synthetic_ci_tests.Cases.test_expected_failure']
            sys.path.insert(0, directory)
            try:
                collected = runner.collect(names)
            finally:
                sys.path.remove(directory)
            outputs = []
            for shard_index in range(2):
                output = Path(directory) / ('job-%d.json' % shard_index)
                result = self.invoke(directory, output, *names, workers=2,
                                     shard_count=2, shard_index=shard_index)
                self.assertEqual(result.returncode, 0)
                outputs.append(json.loads(output.read_text(encoding='utf-8')))
            selected = [set(output['tests']) for output in outputs]
            self.assertFalse(selected[0] & selected[1])
            self.assertEqual(selected[0] | selected[1], set(collected))

    def test_real_checkout_and_recovery_ids_are_assigned_once_at_all_bucket_counts(self):
        ids = runner.collect(['test_branch_management', 'test_branch_recovery'])
        for bucket_count in (1, 3, 6, len(ids) + 1):
            assigned = [test_id for bucket in runner.assign_buckets(ids, bucket_count)
                        for test_id in bucket]
            self.assertCountEqual(assigned, ids)
            self.assertEqual(len(assigned), len(set(assigned)))

    def test_timing_fallback_ignores_missing_and_invalid_values(self):
        ids = ['case.a', 'case.b', 'case.c']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timings.json'
            path.write_text(json.dumps({'case.a': True, 'case.b': -1, 'case.c': float('inf')}),
                            encoding='utf-8')
            self.assertEqual(runner.assign_buckets(ids, 2, path), [['case.a', 'case.c'], ['case.b']])
            self.assertEqual(runner.assign_buckets(ids, 2, Path(directory) / 'missing.json'),
                             [['case.a', 'case.c'], ['case.b']])
            path.write_text('{not json', encoding='utf-8')
            self.assertEqual(runner.assign_buckets(ids, 2, path),
                             [['case.a', 'case.c'], ['case.b']])
            path.write_bytes(b'\xff')
            self.assertEqual(runner.assign_buckets(ids, 2, path),
                             [['case.a', 'case.c'], ['case.b']])
            path.write_text('{"case.a": 4, "case.b": "bad", "case.c": ' + '9' * 400 + '}',
                            encoding='utf-8')
            self.assertEqual(runner.load_timings(path), ({'case.a': 4}, 4))
            self.assertEqual(runner.assign_buckets(ids, 2, path),
                             [['case.a', 'case.c'], ['case.b']])
            path.write_text('{"case.a": ' + '9' * 5000 + '}', encoding='utf-8')
            self.assertEqual(runner.assign_buckets(ids, 2, path),
                             [['case.a', 'case.c'], ['case.b']])

    def test_invalid_shard_arguments_fail_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'metrics.json'
            result = subprocess.run([sys.executable, str(SOURCE), '--output', str(output),
                                     '--timeout', '3', '--shard-count', '2', '--shard-index', '2',
                                     'test_branch_management'], text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--shard-index must select a shard', result.stderr)

    def test_empty_assigned_workers_do_not_launch_children(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'metrics.json'
            with mock.patch.object(runner.subprocess, 'Popen') as popen:
                self.assertEqual(runner.run_parent(['only'], output, 3, 3, None, 2, 1), 0)
            popen.assert_not_called()
            data = json.loads(output.read_text())
            self.assertEqual(data['shards'], [])

    def test_failure_in_selected_partition_still_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            self.module(directory)
            output = Path(directory) / 'metrics.json'
            result = self.invoke(directory, output,
                                 'synthetic_ci_tests.Cases.test_fail',
                                 'synthetic_ci_tests.Cases.test_pass',
                                 workers=1, shard_count=2, shard_index=0)
            self.assertEqual(result.returncode, 1)
            data = json.loads(output.read_text())
            self.assertEqual(data['tests']['synthetic_ci_tests.Cases.test_fail']['status'], 'failure')

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
