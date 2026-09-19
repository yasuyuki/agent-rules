"""Native process fixtures; Windows exercises jobs, Linux exercises process groups."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from workspace_lifecycle import leases


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lifecycle lease ')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / 'repo'
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)

    def supervisor(self, script):
        code = ('from workspace_lifecycle import leases; import sys; '
                'sys.exit(leases.run(sys.argv[1], "task", [sys.executable, "-c", sys.argv[2]], sys.argv[1]))')
        child = subprocess.Popen([sys.executable, '-c', code, str(self.repo), script],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, child)
        return child

    @staticmethod
    def stop(child):
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if child.stdout:
            child.stdout.close()
        if child.stderr:
            child.stderr.close()

    def until(self, predicate):
        deadline = time.monotonic() + 15
        while not predicate():
            if time.monotonic() > deadline:
                self.fail('native lease fixture did not reach expected state')
            time.sleep(.02)

    def test_mutation_guard_excludes_process_and_releases_on_exit(self):
        gate = self.repo / 'gate'
        script = 'import pathlib,time; p=pathlib.Path("gate"); p.write_text("ready");\nwhile p.exists(): time.sleep(.02)'
        child = self.supervisor(script)
        self.until(gate.exists)
        self.assertTrue(leases.is_in_use(self.repo, 'task'))
        with self.assertRaises(ValueError):
            with leases.guard(self.repo, 'task'):
                self.fail('active task was acquired')
        gate.unlink()
        stdout, stderr = child.communicate(timeout=15)
        self.assertEqual(child.returncode, 0, stderr.decode())
        self.assertFalse(leases.is_in_use(self.repo, 'task'))
        with leases.guard(self.repo, 'task'):
            pass

    def test_grandchild_outlives_leader_and_keeps_retirement_blocked(self):
        gate = self.repo / 'descendant'
        grandchild = 'import pathlib,time; p=pathlib.Path("descendant"); p.write_text("ready");\nwhile p.exists(): time.sleep(.02)'
        leader = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c",%r])' % grandchild
        child = self.supervisor(leader)
        self.until(gate.exists)
        self.assertTrue(leases.is_in_use(self.repo, 'task'))
        self.assertIsNone(child.poll())
        gate.unlink()
        stdout, stderr = child.communicate(timeout=15)
        self.assertEqual(child.returncode, 0, stderr.decode())
        self.assertFalse(leases.is_in_use(self.repo, 'task'))

    @unittest.skipIf(os.name == 'nt', 'Linux subreaper fixture; Windows uses native job inheritance')
    def test_detached_grandchild_keeps_lease_until_exit(self):
        gate = self.repo / 'detached'
        grandchild = 'import pathlib,time; p=pathlib.Path("detached"); p.write_text("ready");\nwhile p.exists(): time.sleep(.02)'
        leader = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c",%r],start_new_session=True)' % grandchild
        child = self.supervisor(leader)
        self.until(gate.exists)
        self.assertTrue(leases.is_in_use(self.repo, 'task'))
        time.sleep(.2)
        self.assertIsNone(child.poll())
        gate.unlink()
        stdout, stderr = child.communicate(timeout=15)
        self.assertEqual(child.returncode, 0, stderr.decode())
        self.assertFalse(leases.is_in_use(self.repo, 'task'))

    def test_killed_supervisor_never_implies_release(self):
        gate = self.repo / 'gate'
        script = 'import pathlib,time; p=pathlib.Path("gate"); p.write_text("ready");\nwhile p.exists(): time.sleep(.02)'
        child = self.supervisor(script)
        self.until(gate.exists)
        token = leases.status(self.repo, 'task')['receipt']['token']
        child.kill()
        child.wait(timeout=10)
        self.assertTrue(leases.is_in_use(self.repo, 'task'))
        with self.assertRaises(ValueError):
            leases.release(self.repo, 'task', token, '')
        receipt = leases.status(self.repo, 'task')['receipt']
        # Windows can terminate the launcher and its child together. Assert
        # live-user refusal only when the native child identity is still live.
        if receipt.get('child_identity') is not None and leases._identity(receipt['child_pid']) == receipt['child_identity']:
            with self.assertRaises(ValueError):
                leases.release(self.repo, 'task', token, 'external inspection')
        gate.unlink()
        child.communicate(timeout=15)
        receipt = leases.status(self.repo, 'task')['receipt']
        self.until(lambda: leases._identity(receipt['child_pid']) != receipt['child_identity'])
        leases.release(self.repo, 'task', token, 'fixture child exited; no detached users')
        self.assertFalse(leases.is_in_use(self.repo, 'task'))

    def test_release_requires_exact_receipt_and_cannot_release_live_owner(self):
        gate = self.repo / 'release-gate'
        child = self.supervisor('import pathlib,time; p=pathlib.Path("release-gate"); p.write_text("ready");\nwhile p.exists(): time.sleep(.02)')
        self.until(gate.exists)
        try:
            receipt = leases.status(self.repo, 'task')['receipt']
            with self.assertRaises(ValueError):
                leases.release(self.repo, 'task', receipt['token'], 'claimed release')
            self.assertIsNone(child.poll())
        finally:
            gate.unlink(missing_ok=True)
        child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0)


if __name__ == '__main__':
    unittest.main()
