"""Source/wheel installation equivalence must reject every runtime difference."""
from pathlib import Path
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import install_equivalence


def wheel(directory, name, version, module='eqfixture', target='main'):
    info = f'{name}-{version}.dist-info'
    files = {
        f'{module}/__init__.py': f'def main():\n    print("{version}")\n'.encode(),
        f'{module}/data.txt': b'packaged data\n',
        f'{info}/METADATA': f'Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n'.encode(),
        f'{info}/WHEEL': b'Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
        f'{info}/entry_points.txt': f'[console_scripts]\n{name} = {module}:{target}\n'.encode(),
    }
    record = ''.join(f'{path},{install_equivalence.digest(data)},{len(data)}\n' for path, data in files.items())
    files[f'{info}/RECORD'] = (record + f'{info}/RECORD,,\n').encode()
    path = Path(directory) / f'{name}-{version}-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w') as archive:
        for member, data in files.items():
            archive.writestr(member, data)
    return path


def environment(root, *wheels):
    venv.create(root, with_pip=False)
    python = root / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    subprocess.run([sys.executable, '-m', 'pip', '--python', str(python), 'install', '-q',
                    '--no-index', '--no-deps', '--disable-pip-version-check', *map(str, wheels)],
                   check=True, capture_output=True)
    return python


class InstallEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.fixture = wheel(root, 'eqfixture', '1.0')
        cls.wheel_python = environment(root / 'wheel', cls.fixture)
        cls.source_python = environment(root / 'source', cls.fixture)
        cls.other_version = wheel(root, 'eqfixture', '1.1')
        cls.extra = wheel(root, 'eqextra', '1.0', module='eqextra')
        probe = install_equivalence.probe(str(cls.source_python), 'eqfixture')
        cls.purelib = Path(probe['purelib'])
        cls.scripts = Path(probe['scripts'])
        cls.info = cls.purelib / 'eqfixture-1.0.dist-info'
        cls.launcher = cls.scripts / ('eqfixture.exe' if os.name == 'nt' else 'eqfixture')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.saved = {}
        self.addCleanup(self.restore)

    def restore(self):
        for path, data in self.saved.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)

    def write(self, path, data, rehash=False):
        self.saved.setdefault(path, path.read_bytes() if path.exists() else None)
        if data is None:
            path.unlink()
        else:
            path.write_bytes(data)
        if rehash:
            record = self.info / 'RECORD'
            name = path.relative_to(self.purelib).as_posix()
            lines = [line for line in record.read_text(encoding='utf-8').splitlines()
                     if not line.startswith(name + ',')]
            if data is not None:
                lines.append(f'{name},{install_equivalence.digest(data)},{len(data)}')
            self.write(record, ('\n'.join(lines) + '\n').encode())

    def problems(self, source=None):
        return install_equivalence.compare(str(self.wheel_python), str(source or self.source_python),
                                           'eqfixture', 'eqfixture')[0]

    def assertRejected(self, *expected, source=None):
        problems = self.problems(source)
        for text in expected:
            self.assertTrue(any(text in problem for problem in problems), (text, problems))

    def test_independent_installs_of_one_wheel_match(self):
        self.assertEqual(self.problems(), [])
        self.assertEqual(install_equivalence.main([str(self.wheel_python), str(self.source_python),
                                                   '--distribution', 'eqfixture', '--module', 'eqfixture']), 0)

    def test_missing_package_file(self):
        self.write(self.purelib / 'eqfixture/data.txt', None)
        self.assertRejected('RECORD names missing eqfixture/data.txt', 'source lacks eqfixture/data.txt')

    def test_missing_package_file_with_consistent_record(self):
        self.write(self.purelib / 'eqfixture/data.txt', None, rehash=True)
        self.assertRejected('source lacks eqfixture/data.txt')

    def test_changed_content_behind_an_equal_record(self):
        self.write(self.purelib / 'eqfixture/data.txt', b'altered data\n')
        self.assertRejected('RECORD hash or size differs from eqfixture/data.txt',
                            'source differs in eqfixture/data.txt')

    def test_changed_content_with_consistent_record(self):
        self.write(self.purelib / 'eqfixture/data.txt', b'altered data\n', rehash=True)
        self.assertRejected('source differs in eqfixture/data.txt')

    def test_unrecorded_package_file(self):
        self.write(self.purelib / 'eqfixture/extra.py', b'')
        self.assertRejected('eqfixture/extra.py is not in RECORD', 'source adds eqfixture/extra.py')

    def test_unrelated_site_file(self):
        self.write(self.purelib / 'injected.pth', b'')
        self.assertRejected('source adds injected.pth')

    def test_record_entry_without_hash(self):
        record = self.info / 'RECORD'
        text = record.read_text(encoding='utf-8')
        self.write(record, re.sub(r'(?m)^(eqfixture/data\.txt),[^,]*,', r'\1,,', text).encode())
        self.assertRejected('RECORD has no hash for eqfixture/data.txt')

    def test_entry_point_metadata(self):
        points = self.info / 'entry_points.txt'
        self.write(points, points.read_bytes().replace(b':main', b':other'), rehash=True)
        self.assertRejected('source differs in eqfixture-1.0.dist-info/entry_points.txt')

    def test_missing_launcher(self):
        self.write(self.launcher, None)
        self.assertRejected('RECORD names missing', 'differ from entry points', f'source lacks {self.launcher.name}')

    def test_changed_launcher_script(self):
        data = self.launcher.read_bytes()
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            altered = data + b'raise SystemExit(3)\n'
        else:
            start = min(info.header_offset for info in archive.infolist())
            replacement = io.BytesIO()
            with zipfile.ZipFile(replacement, 'w') as rebuilt:
                rebuilt.writestr('__main__.py', archive.read('__main__.py') + b'raise SystemExit(3)\n')
            altered = data[:start] + replacement.getvalue()
        self.write(self.launcher, altered)
        self.assertRejected(f'RECORD hash or size differs from', f'source differs in {self.launcher.name}')

    def test_launcher_for_another_interpreter(self):
        data = self.launcher.read_bytes()
        own = os.fsencode(self.source_python)
        self.assertIn(own, data)
        self.write(self.launcher, data.replace(own, os.fsencode(self.wheel_python)))
        self.assertRejected(f'launcher {self.launcher.name} does not start')

    def test_module_imported_from_outside_site_packages(self):
        outside = Path(self.temporary.name) / 'checkout'
        (outside / 'eqfixture').mkdir(parents=True, exist_ok=True)
        (outside / 'eqfixture/__init__.py').write_bytes(b'')
        package = self.purelib / 'eqfixture/__init__.py'
        self.write(package, None)
        self.write(self.purelib / 'checkout.pth', f'{outside}\n'.encode())
        self.assertRejected('eqfixture imported from', 'source lacks eqfixture/__init__.py')

    def test_different_distribution_version(self):
        other = environment(Path(self.temporary.name) / 'other-version', self.other_version)
        self.assertRejected('distributions differ', 'source lacks eqfixture-1.0.dist-info/METADATA',
                            'source adds eqfixture-1.1.dist-info/METADATA', source=other)

    def test_additional_distribution(self):
        other = environment(Path(self.temporary.name) / 'with-extra',
                            self.fixture, self.extra)
        self.assertRejected('distributions differ', 'source adds eqextra/__init__.py', source=other)

    def test_different_runtime(self):
        probe = install_equivalence.probe
        def other_runtime(python, module):
            found = probe(python, module)
            if python == str(self.source_python):
                found['runtime'][0] += ' other build'
            return found
        with mock.patch.object(install_equivalence, 'probe', other_runtime):
            self.assertRejected('runtime differs')


if __name__ == '__main__':
    unittest.main()
