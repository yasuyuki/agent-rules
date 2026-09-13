"""Focused regressions for batched installation reads, using real Git config."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'management', Path(__file__).resolve().parents[1] / 'bin/branch_management.py')
management = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(management)


class InstallationConfigTests(unittest.TestCase):
    def test_batch_preserves_last_value_and_all_scope_semantics(self):
        with tempfile.TemporaryDirectory(prefix='config values ') as temp:
            repo = Path(temp)
            subprocess.run(['git', 'init', '-q', temp], check=True)
            management.git(repo, 'remote', 'add', 'origin', 'https://example.invalid/repo')
            directory = repo / '.git/agent-branches'
            state = dict(version=1, remote='origin', remote_url='https://example.invalid/repo',
                         python='python path', source='source path', hook_hashes={}, hook_executable={})
            values = [('core.hooksPath', str(directory / 'hooks')),
                      ('agentBranch.python', state['python']), ('agentBranch.source', state['source'])]
            for key, value in values:
                management.git(repo, 'config', '--add', key, 'obsolete value')
                management.git(repo, 'config', '--add', key, '\n ' + value + ' \n')
                self.assertEqual(management.git(repo, 'config', '--get', key), value)
            self.assertEqual(management.installation_errors(repo, directory, state, source_check=False), [])
            global_config = repo / 'global config'
            management.git(repo, 'config', '--file', str(global_config), 'agentBranch.python', state['python'])
            management.git(repo, 'config', '--unset-all', 'agentBranch.python')
            with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(global_config),
                                               'GIT_CONFIG_NOSYSTEM': '1'}):
                self.assertEqual(management.git(repo, 'config', '--get', 'agentBranch.python'), state['python'])
                self.assertEqual(management.installation_errors(repo, directory, state, source_check=False), [])
                management.git(repo, 'config', 'agentBranch.python', 'wrong local value')
                with mock.patch.dict(os.environ, {'GIT_CONFIG_COUNT': '1',
                                                   'GIT_CONFIG_KEY_0': 'agentBranch.python',
                                                   'GIT_CONFIG_VALUE_0': state['python']}):
                    self.assertEqual(management.git(repo, 'config', '--get', 'agentBranch.python'), state['python'])
                    self.assertEqual(management.installation_errors(repo, directory, state, source_check=False), [])
            management.git(repo, 'config', '--add', 'agentBranch.source', 'changed\nsource')
            self.assertIn('agentBranch.source differs from installation',
                          management.installation_errors(repo, directory, state, source_check=False))
            management.git(repo, 'config', '--unset-all', 'agentBranch.source')
            self.assertIn('agentBranch.source differs from installation',
                          management.installation_errors(repo, directory, state, source_check=False))


if __name__ == '__main__':
    unittest.main()
