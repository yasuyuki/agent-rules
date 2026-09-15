"""Public standard names preserve real cwd, output, arguments and held scopes."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('standard_place', ROOT / 'bin/place.py')
place = importlib.util.module_from_spec(spec)
spec.loader.exec_module(place)


class StandardStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root / 'work'
        self.nested = self.work / 'repo 日本語'
        self.subdir = self.nested / 'sub dir'
        self.held = self.work / 'held'
        for path in (self.subdir, self.held, self.root / 'home', self.root / 'vendor', self.root / 'entry'):
            path.mkdir(parents=True)
        self.declaration = self.root / 'PLACEMENT.md'
        def table(name, header, rows):
            return '<!-- BEGIN %s TSV -->\n```tsv\n%s\n%s\n```\n<!-- END %s TSV -->\n' % (name, header, '\n'.join(rows), name)
        self.declaration.write_text(
            table('SITES', 'id\thost\tuser\thome\treach\tlaunch',
                  ['local\tlocal\ttester\t%s\tlocal\t' % (self.root / 'home')]) +
            table('WORKSPACES', 'id\tsite\tkind\tpath\textra',
                  ['%s\tlocal\tdirect\t%s\t' % item for item in [('work', self.work), ('nested', self.nested), ('held', self.held)]]) +
            table('LOCATIONS', 'id\tscope\tanchor\ttool\trequirement\treason\tlegacy\tpath\tkind',
                  ['%s-%s\tworkspace\t%s\t%s\trequired\t\t\t\trules' % (name, tool, name, tool)
                   for name in ('work', 'nested', 'held') for tool in ('grok', 'codex', 'claude')
                   if (name, tool) != ('held', 'grok')]) +
            table('EXCEPTIONS', 'artifact\tlocation_id\trequirement\treason', []), encoding='utf-8')
        self.config = self.root / 'start.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(place.main(['save-start-config', '--config', str(self.config), '--declaration', str(self.declaration)]), 0)
            self.assertEqual(place.main(['apply', '--declaration', str(self.declaration)]), 0)

    def run_start(self, cwd, tool, args=(), runner=None):
        old = Path.cwd()
        os.chdir(cwd)
        try:
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                result = place.main(['standard-start', '--config', str(self.config), tool, '--', *args],
                                    runner=runner or self.capture, resolver=lambda name: 'vendor-' + name)
            return result, errors.getvalue()
        finally:
            os.chdir(old)

    def capture(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 7)

    def test_nested_cwd_and_native_continuation(self):
        for tool, args in [('grok', ['--continue']), ('codex', ['resume', '--last']), ('claude', ['--continue'])]:
            self.calls = []
            status, errors = self.run_start(self.subdir, tool, args)
            self.assertEqual(status, 7, errors)
            argv, kwargs = self.calls[0]
            self.assertEqual(kwargs['cwd'], str(self.subdir))
            self.assertEqual(argv[-len(args):], args)
            if tool != 'claude':
                self.assertEqual(argv[2], str(self.subdir))
            self.assertEqual(errors, '')

    def test_held_scope_and_native_override_do_not_fall_back(self):
        for cwd, args in [(self.held, []), (self.work, ['--cwd', 'held']), (self.work, ['--cwd=held'])]:
            self.calls = []
            status, errors = self.run_start(cwd, 'grok', args)
            self.assertEqual(status, 1)
            self.assertIn('not enabled', errors)
            self.assertEqual(self.calls, [])
        self.calls = []
        status, errors = self.run_start(self.root, 'claude')
        self.assertEqual(status, 1)
        self.assertIn('not declared', errors)

    def test_relative_override_preserves_native_argument_resolution(self):
        self.calls = []
        args = ['--cwd', 'repo 日本語/sub dir', '--prompt', 'a "quoted" 日本語 value']
        status, errors = self.run_start(self.work, 'grok', args)
        self.assertEqual(status, 7, errors)
        self.assertEqual(self.calls[0], (['vendor-grok', *args], {'cwd': str(self.work)}))

    def test_directory_words_in_values_remain_values(self):
        for tool, args in [('grok', ['-p', '--cwd']), ('codex', ['-c', '-Celsewhere'])]:
            self.calls = []
            status, errors = self.run_start(self.subdir, tool, args)
            self.assertEqual(status, 7, errors)
            self.assertEqual(self.calls[0][0][2], str(self.subdir))
            self.assertEqual(self.calls[0][0][-2:], args)

    def test_duplicate_ambiguous_and_missing_directory(self):
        self.calls = []
        for args in [['--cwd'], ['--cwd', '.', '--cwd', '.'], ['--cwd=missing']]:
            self.assertEqual(self.run_start(self.work, 'grok', args)[0], 1)
        raw = self.declaration.read_text(encoding='utf-8')
        self.declaration.write_text(raw.replace('nested\tlocal\tdirect\t', 'duplicate\tlocal\tdirect\t%s\t\nnested\tlocal\tdirect\t' % self.nested), encoding='utf-8')
        self.assertIn('ambiguous', self.run_start(self.subdir, 'grok')[1])
        self.assertEqual(self.calls, [])

    def test_repair_does_not_require_valid_config_but_agent_does(self):
        self.config.write_text('invalid', encoding='utf-8')
        self.calls = []
        self.assertEqual(self.run_start(self.subdir, 'grok', ['--help'])[0], 7)
        self.assertEqual(self.run_start(self.subdir, 'grok', ['inspect', '--json'])[0], 7)
        self.assertEqual(self.run_start(self.subdir, 'grok', ['--prompt', '--help'])[0], 1)
        self.assertEqual(len(self.calls), 2)

    @unittest.skipIf(os.name == 'nt', 'POSIX standard-name installation')
    def test_real_child_standard_name_stdio_and_exit(self):
        vendor = self.root / 'vendor' / 'grok'
        vendor.write_text('#!%s\nimport json,os,sys\nprint(json.dumps({"cwd":os.getcwd(),"args":sys.argv[1:],"stdin":sys.stdin.read()},ensure_ascii=False))\nprint("vendor stderr",file=sys.stderr)\nsys.exit(23)\n' % sys.executable, encoding='utf-8')
        vendor.chmod(0o755)
        directory = self.root / 'entry'
        path = str(vendor.parent) + os.pathsep + os.environ['PATH']
        place.managed_entry.install(self.config, directory, ['grok'], path=path)
        env = {**os.environ, 'PATH': str(directory) + os.pathsep + path}
        args = ['--prompt', 'a "quoted" 日本語', '']
        result = subprocess.run(['grok', *args], cwd=self.subdir, env=env, input='input 日本語', text=True, capture_output=True)
        self.assertEqual(result.returncode, 23, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['cwd'], str(self.subdir))
        self.assertEqual(payload['args'], ['--cwd', str(self.subdir), *args])
        self.assertEqual(payload['stdin'], 'input 日本語')
        self.assertEqual(result.stderr, 'vendor stderr\n')

    @unittest.skipIf(os.name == 'nt', 'POSIX terminal and signals')
    def test_terminal_and_interrupt_reach_vendor_process(self):
        import pty
        import select
        import signal
        vendor = self.root / 'vendor' / 'grok'
        vendor.write_text('#!%s\nimport os,sys,signal\nsignal.signal(signal.SIGINT,lambda *_:sys.exit(42))\nprint("TTY="+str(all(os.isatty(fd) for fd in (0,1,2))),flush=True)\nsignal.pause()\n' % sys.executable, encoding='utf-8')
        vendor.chmod(0o755)
        directory = self.root / 'entry'
        path = str(vendor.parent) + os.pathsep + os.environ['PATH']
        place.managed_entry.install(self.config, directory, ['grok'], path=path)
        master, slave = pty.openpty()
        child = None
        try:
            child = subprocess.Popen([str(directory / 'grok')], cwd=self.subdir,
                                     stdin=slave, stdout=slave, stderr=slave)
            ready, _, _ = select.select([master], [], [], 10)
            self.assertTrue(ready, 'vendor did not reach terminal')
            self.assertEqual(os.read(master, 1024).strip(), b'TTY=True')
            child.send_signal(signal.SIGINT)
            self.assertEqual(child.wait(timeout=10), 42)
        finally:
            if child is not None and child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    unittest.main()
