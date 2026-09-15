"""Small, bounded unittest runner for CI matrix shards.

It deliberately records only test identities, outcomes, and timings.  Test
output stays on the normal stderr stream and is never copied into metrics.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


VERSION = '1'
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))


def _write(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    temporary = str(path) + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, sort_keys=True)
    os.replace(temporary, path)


def _flatten(suite):
    if isinstance(suite, unittest.TestCase):
        return [suite.id()]
    found = []
    for item in suite:
        found.extend(_flatten(item))
    return found


def collect(names):
    """Collect explicit unittest names, preserving each module's load_tests hook."""
    loader = unittest.TestLoader()
    ids = [test_id for name in names for test_id in _flatten(loader.loadTestsFromName(name))]
    if loader.errors:
        raise ValueError('; '.join(loader.errors))
    if not ids:
        raise ValueError('collection selected no tests')
    return sorted(set(ids))


def _metadata():
    return {
        'github': {key: os.environ.get(key) for key in
                   ('GITHUB_SHA', 'GITHUB_WORKFLOW_REF', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')},
        'runtime': {'python': sys.version, 'platform': sys.platform,
                    'version': VERSION, 'executable': sys.executable},
    }


def _safe_metrics(metrics):
    """Metrics are numeric observations, never test output or arbitrary text."""
    fields = ('gitCommandCount', 'gitCommandSeconds', 'cliCommandCount', 'cliCommandSeconds',
              'fixtureSeconds', 'cleanupSeconds')
    if isinstance(metrics, dict) and set(metrics) - set(fields):
        return {'invalid': True}
    values = metrics if isinstance(metrics, dict) else {
        field: getattr(metrics, field, None) for field in fields}
    recorded = {}
    for field in fields:
        value = values.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return {'invalid': True}
        recorded[field] = value
    return recorded


class _RecordingResult(unittest.TestResult):
    def __init__(self, output):
        super().__init__()
        self.output = output
        self.current = None

    def _save(self):
        _write(self.output, self.output_data)

    @property
    def output_data(self):
        return {'metadata': _metadata(), 'tests': self.tests}

    def _record(self, test, status):
        test_id = test.id()
        record = self.tests.setdefault(test_id, {'status': status, 'elapsed': 0.0})
        record['status'] = status
        return record

    def _diagnostic(self, test, err):
        print('ci_runner %s %s' % (test.id(), ''.join(self._exc_info_to_string(err, test))),
              file=sys.stderr, flush=True)

    def startTest(self, test):
        super().startTest(test)
        self.current = test.id()
        self.started = time.monotonic()
        self._record(test, 'running')
        self._save()
        print('ci_runner start ' + self.current, file=sys.stderr, flush=True)

    def stopTest(self, test):
        record = self._record(test, self.tests.get(test.id(), {}).get('status', 'running'))
        record['elapsed'] = time.monotonic() - self.started
        if record['status'] == 'running':
            record['status'] = 'pass'
        metrics = getattr(test, '_ci_metrics', None)
        if metrics is not None:
            record['metrics'] = _safe_metrics(metrics)
        self._save()
        print('ci_runner end %s %s %.3fs' %
              (test.id(), record['status'], record['elapsed']), file=sys.stderr, flush=True)
        super().stopTest(test)

    def addFailure(self, test, err):
        self._record(test, 'failure')
        super().addFailure(test, err)
        self._diagnostic(test, err)
        self._save()

    def addError(self, test, err):
        self._record(test, 'error')
        super().addError(test, err)
        self._diagnostic(test, err)
        self._save()

    def addSubTest(self, test, subtest, err):
        if err is not None:
            status = 'failure' if issubclass(err[0], test.failureException) else 'error'
            self._record(test, status)
            self._diagnostic(test, err)
        super().addSubTest(test, subtest, err)
        self._save()

    def addSkip(self, test, reason):
        self._record(test, 'skip')
        super().addSkip(test, reason)
        self._save()

    def addExpectedFailure(self, test, err):
        self._record(test, 'expected_failure')
        super().addExpectedFailure(test, err)
        self._save()

    def addUnexpectedSuccess(self, test):
        self._record(test, 'unexpected_success')
        super().addUnexpectedSuccess(test)
        self._save()


def run_child(ids, output):
    result = _RecordingResult(output)
    result.tests = {}
    _write(output, result.output_data)
    suite = unittest.TestLoader().loadTestsFromNames(ids)
    suite.run(result)
    # unittest treats expected platform skips as a successful run.  Keep that
    # established exit contract while recording them distinctly in the metrics.
    return 0 if result.wasSuccessful() else 1


def _terminate(process):
    if os.name == 'nt':
        if process.poll() is not None:
            return True
        try:
            result = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, check=False, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            return True
        # A direct-child fallback prevents an unbounded parent wait.  It cannot
        # prove the descendant tree was removed, so report cleanup failure.
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return process.poll() is not None
    return True


def _pid_alive(pid):
    """Check a child PID without using Windows' signal-like os.kill API."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists.
                return False
            raise OSError(error, 'OpenProcess failed for child PID')
        try:
            result = kernel32.WaitForSingleObject(handle, 0)
            if result == 0x102:  # WAIT_TIMEOUT
                return True
            if result == 0:  # WAIT_OBJECT_0
                return False
            raise OSError(ctypes.get_last_error(), 'WaitForSingleObject failed for child PID')
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _child_command(output, timeout, ids):
    return [sys.executable, str(Path(__file__).resolve()), '--_child', '--output', str(output),
            '--timeout', str(timeout), *ids]


def _child_data(child):
    try:
        return json.loads(child['output'].read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {'tests': {}}


def _last_test(data):
    running = [test_id for test_id, record in data.get('tests', {}).items()
               if record.get('status') == 'running']
    return running[-1] if running else None


def load_timings(path):
    """Read optional per-test estimates, treating every bad value as unknown."""
    if not path:
        return {}, 1.0
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        # Includes malformed UTF-8/JSON and Python's integer-decoding limit.
        return {}, 1.0
    if not isinstance(data, dict):
        return {}, 1.0
    weights = {}
    for test_id, value in data.items():
        if not isinstance(test_id, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            valid = math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if valid:
            weights[test_id] = value
    # An unseen test should not be favoured over known slow tests.  This also
    # keeps scheduling useful if a timings file is only partially populated.
    return weights, max(weights.values(), default=1.0)


def assign_buckets(ids, bucket_count, timings=None):
    """Deterministically assign every ID once with longest-processing-time first."""
    weights, fallback = load_timings(timings)
    buckets = [[] for unused in range(bucket_count)]
    loads = [0.0] * bucket_count
    for test_id in sorted(ids, key=lambda item: (-weights.get(item, fallback), item)):
        index = min(range(bucket_count), key=lambda item: (loads[item], item))
        buckets[index].append(test_id)
        loads[index] += weights.get(test_id, fallback)
    return buckets


def run_parent(ids, output, workers, timeout, timings=None, shard_count=1, shard_index=0):
    buckets = assign_buckets(ids, workers * shard_count, timings)
    first_bucket = shard_index * workers
    assigned_buckets = buckets[first_bucket:first_bucket + workers]
    # Do not launch no-op children when a job owns more workers than tests.
    shards = [bucket for bucket in assigned_buckets if bucket]
    started = time.monotonic()
    children = []
    with tempfile.TemporaryDirectory(prefix='agent-rules-ci-runner-') as directory:
        interrupted = False
        cleanup_failed = False
        spawn_error = None
        try:
            for index, shard in enumerate(shards):
                child_output = Path(directory) / ('shard-%d.json' % index)
                kwargs = {'stdin': subprocess.DEVNULL}
                if os.name == 'nt':
                    kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
                else:
                    kwargs['preexec_fn'] = os.setsid
                process = subprocess.Popen(_child_command(child_output, timeout, shard), **kwargs)
                children.append({'process': process, 'output': child_output,
                                 'deadline': time.monotonic() + timeout, 'ids': shard,
                                 'timed_out': False})
            while any(child['process'].poll() is None for child in children):
                now = time.monotonic()
                for child in children:
                    if child['process'].poll() is None and now >= child['deadline']:
                        child['timed_out'] = True
                        child['last_test'] = _last_test(_child_data(child))
                        print('ci_runner timeout last=%s' % (child['last_test'] or 'none'),
                              file=sys.stderr, flush=True)
                        cleanup_failed |= not _terminate(child['process'])
                time.sleep(.02)
        except OSError as error:
            spawn_error = str(error)
            print('ci_runner spawn error: ' + spawn_error, file=sys.stderr, flush=True)
        except KeyboardInterrupt:
            interrupted = True
            for child in children:
                cleanup_failed |= not _terminate(child['process'])
        finally:
            for child in children:
                if child['process'].poll() is None:
                    cleanup_failed |= not _terminate(child['process'])
                try:
                    child['returncode'] = child['process'].wait(timeout=5)
                except subprocess.TimeoutExpired:
                    cleanup_failed = True
                    child['returncode'] = child['process'].poll()
        tests, shards_data = {}, []
        for child in children:
            data = _child_data(child)
            tests.update(data.get('tests', {}))
            shards_data.append({'ids': child['ids'], 'exitCode': child['returncode'],
                                'timedOut': child['timed_out'],
                                'lastTest': child.get('last_test')})
        assigned_ids = [test_id for shard in assigned_buckets for test_id in shard]
        missing = sorted(set(assigned_ids) - set(tests))
        for test_id in missing:
            tests[test_id] = {'status': 'missing', 'elapsed': 0.0}
        payload = {'metadata': _metadata(), 'stageElapsed': time.monotonic() - started,
                   'tests': tests, 'shards': shards_data, 'missing': missing,
                   'globalShards': buckets,
                   'cleanupFailed': cleanup_failed, 'spawnError': spawn_error}
        _write(output, payload)
    failed = (interrupted or spawn_error or cleanup_failed or missing or
              any(item['timedOut'] or item['exitCode'] for item in shards_data))
    return 130 if interrupted else (1 if failed else 0)


def run_command(command, output, timeout):
    """Run one script-style stage with the same owned-tree timeout boundary."""
    started = time.monotonic()
    kwargs = {'stdin': subprocess.DEVNULL}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['preexec_fn'] = os.setsid
    print('ci_runner command start ' + command[0], file=sys.stderr, flush=True)
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        # Keep executable arguments and OS diagnostics out of the metric file.
        _write(output, {'metadata': _metadata(), 'command': os.path.basename(command[0]),
                        'stageElapsed': time.monotonic() - started, 'tests': {},
                        'spawnError': type(exc).__name__, 'cleanupFailed': False,
                        'shards': [{'ids': [], 'exitCode': None, 'timedOut': False, 'lastTest': None}]})
        print('ci_runner command launch failed: ' + type(exc).__name__, file=sys.stderr, flush=True)
        return 1
    timed_out = False
    interrupted = False
    cleanup_failed = False
    try:
        while process.poll() is None:
            if time.monotonic() - started >= timeout:
                timed_out = True
                print('ci_runner command timeout', file=sys.stderr, flush=True)
                cleanup_failed = not _terminate(process)
                break
            time.sleep(.02)
    except KeyboardInterrupt:
        interrupted = True
        cleanup_failed = not _terminate(process)
    finally:
        if process.poll() is None:
            cleanup_failed |= not _terminate(process)
        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cleanup_failed = True
            exit_code = process.poll()
    payload = {'metadata': _metadata(), 'command': os.path.basename(command[0]),
               'stageElapsed': time.monotonic() - started,
               'tests': {}, 'shards': [{'ids': [], 'exitCode': exit_code,
                                         'timedOut': timed_out, 'lastTest': None}]}
    payload['cleanupFailed'] = cleanup_failed
    _write(output, payload)
    print('ci_runner command end %s %s' % (command[0], exit_code), file=sys.stderr, flush=True)
    return 130 if interrupted else (1 if timed_out or cleanup_failed else exit_code)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--shard-count', type=int, default=1)
    parser.add_argument('--shard-index', type=int, default=0)
    parser.add_argument('--timings')
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--_child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--command', nargs=argparse.REMAINDER)
    parser.add_argument('names', nargs='*')
    args = parser.parse_args(argv)
    if (args.workers < 1 or args.shard_count < 1 or
            args.shard_index < 0 or args.shard_index >= args.shard_count or
            args.timeout <= 0 or not math.isfinite(args.timeout)):
        parser.error('--workers, --shard-count, and --timeout must be positive; '
                     '--shard-index must select a shard')
    if args.command is not None:
        if args._child or args.names or not args.command or args.timings or args.shard_count != 1 or args.shard_index:
            parser.error('--command cannot be combined with test names or child mode')
        return run_command(args.command, args.output, args.timeout)
    if not args.names:
        parser.error('test name or --command is required')
    try:
        ids = args.names if args._child else collect(args.names)
    except ValueError as error:
        print('ci_runner collection error: ' + str(error), file=sys.stderr, flush=True)
        _write(args.output, {'metadata': _metadata(), 'collectionError': str(error),
                             'tests': {}, 'shards': []})
        return 1
    if args._child and (args.timings or args.shard_count != 1 or args.shard_index):
        parser.error('child mode cannot select timings or shards')
    return run_child(ids, args.output) if args._child else run_parent(
        ids, args.output, args.workers, args.timeout, args.timings,
        args.shard_count, args.shard_index)


if __name__ == '__main__':
    raise SystemExit(main())
