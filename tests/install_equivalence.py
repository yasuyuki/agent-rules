"""Require a source installation to install the same runtime as a tested wheel installation.

Usage: python tests/install_equivalence.py WHEEL_PYTHON SOURCE_PYTHON

Each argument is the interpreter of a separate environment. Exit 0 means the two
environments resolve the same Python runtime and distributions, and their
site-packages and console launchers hold the same bytes apart from the
install-specific parts named in EXCLUDED and in launcher(). Exit 1 lists each
difference or inconsistent RECORD.
"""
import argparse
import base64
import configparser
import csv
import email.parser
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PROBE = r'''
import importlib, importlib.metadata as m, json, sys, sysconfig
module = importlib.import_module(sys.argv[1])
print(json.dumps(dict(
    runtime=[sys.version, sys.platform, sys.implementation.cache_tag, sys._base_executable],
    executable=sys.executable,
    purelib=sysconfig.get_path('purelib'),
    scripts=sysconfig.get_path('scripts'),
    module=module.__file__,
    distributions=sorted([d.metadata['Name'], d.version] for d in m.distributions()))))
'''

# direct_url.json records where pip found the distribution (PEP 610); the runtime
# never reads it. RECORD differs only by those hashes and is checked against the
# files themselves. Bytecode embeds the source mtime and is rebuilt from source.
EXCLUDED = re.compile(r'(^|/)__pycache__/[^/]+\.pyc$|\.dist-info/(direct_url\.json|RECORD)$')


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def digest(data):
    return 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()


def probe(python, module):
    with tempfile.TemporaryDirectory() as away:
        result = subprocess.run([python, '-I', '-c', PROBE, module], cwd=away,
                                capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f'FAIL: {python} cannot import {module} outside the checkout\n{result.stderr}')
    return json.loads(result.stdout)


def launcher(path, executable):
    """Return the launcher without the interpreter path and the zip timestamps pip writes."""
    data = path.read_bytes()
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        head, members = data, {}
    else:
        with archive:
            head = data[:min(info.header_offset for info in archive.infolist())]
            members = {info.filename: digest(archive.read(info)) for info in archive.infolist()}
    own = executable.encode()
    if own not in head:
        return None
    return digest(head.replace(own, b'@PYTHON@')), members


def inspect(python, distribution, module):
    found = probe(python, module)
    purelib = Path(found['purelib'])
    scripts = Path(found['scripts'])
    problems = []
    if not Path(found['module']).resolve().is_relative_to(purelib.resolve()):
        problems.append(f'{module} imported from {found["module"]}, not {purelib}')
    infos = [p for p in purelib.glob('*.dist-info')
             if canonical(email.parser.Parser().parsestr(
                 (p / 'METADATA').read_text(encoding='utf-8'), headersonly=True)['Name']) == canonical(distribution)]
    if len(infos) != 1:
        raise SystemExit(f'FAIL: {python} has {len(infos)} installations of {distribution}')
    info = infos[0]
    recorded, roots, launchers = set(), set(), {}
    with open(info / 'RECORD', newline='', encoding='utf-8') as stream:
        for row in csv.reader(stream):
            if len(row) != 3:
                problems.append(f'RECORD row is malformed: {row}')
                continue
            name, hashed, size = row
            path = (purelib / name).resolve()
            recorded.add(path)
            if not path.is_file():
                problems.append(f'RECORD names missing {name}')
                continue
            if hashed:
                data = path.read_bytes()
                if (digest(data), str(len(data))) != (hashed, size):
                    problems.append(f'RECORD hash or size differs from {name}')
            elif not (name.endswith('.pyc') or path == (info / 'RECORD').resolve()):
                problems.append(f'RECORD has no hash for {name}')
            if path.is_relative_to(purelib.resolve()):
                roots.add(path.relative_to(purelib.resolve()).parts[0])
            elif path.parent == scripts.resolve():
                launchers[path.name] = launcher(path, found['executable'])
            else:
                problems.append(f'RECORD installs {name} outside site-packages and scripts')
    for root in roots:
        top = purelib / root
        for path in (top.rglob('*') if top.is_dir() else [top]):
            if path.is_file() and path.resolve() not in recorded:
                problems.append(f'{path.relative_to(purelib).as_posix()} is not in RECORD')
    points = configparser.ConfigParser(delimiters=('=',), interpolation=None)
    points.optionxform = str
    points.read(info / 'entry_points.txt', encoding='utf-8')
    names = {name + ('.exe' if os.name == 'nt' else '')
             for section in ('console_scripts', 'gui_scripts') if points.has_section(section)
             for name in points[section]}
    if names != set(launchers):
        problems.append(f'launchers {sorted(launchers)} differ from entry points {sorted(names)}')
    problems += [f'launcher {name} does not start {found["executable"]}'
                 for name, parts in launchers.items() if parts is None]
    files = {path.relative_to(purelib).as_posix(): digest(path.read_bytes())
             for path in purelib.rglob('*') if path.is_file()}
    files = {name: value for name, value in files.items() if not EXCLUDED.search(name)}
    return dict(runtime=found['runtime'], distributions=found['distributions'],
                files=files, launchers=launchers), problems


def compare(wheel, source, distribution, module):
    (expected, problems), (actual, other) = (inspect(wheel, distribution, module),
                                             inspect(source, distribution, module))
    problems = [f'wheel: {p}' for p in problems] + [f'source: {p}' for p in other]
    for key in ('runtime', 'distributions'):
        if expected[key] != actual[key]:
            problems.append(f'{key} differs: {expected[key]} != {actual[key]}')
    for key in ('files', 'launchers'):
        for name in sorted(expected[key].keys() | actual[key].keys()):
            if name not in actual[key]:
                problems.append(f'source lacks {name}')
            elif name not in expected[key]:
                problems.append(f'source adds {name}')
            elif expected[key][name] != actual[key][name]:
                problems.append(f'source differs in {name}')
    return problems, expected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('wheel_python')
    parser.add_argument('source_python')
    parser.add_argument('--distribution', default='agent-rules')
    parser.add_argument('--module', default='agent_rules_manager')
    args = parser.parse_args(argv)
    problems, expected = compare(args.wheel_python, args.source_python, args.distribution, args.module)
    if problems:
        print('FAIL: source installation differs from the tested wheel', *problems, sep='\n  ', file=sys.stderr)
        return 1
    print(f'source installation matches the wheel: {len(expected["files"])} files, '
          f'{len(expected["launchers"])} launchers, {len(expected["distributions"])} distributions')
    return 0


if __name__ == '__main__':
    sys.exit(main())
