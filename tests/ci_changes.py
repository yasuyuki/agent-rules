"""Shared CI change selection and required-job gate; unknown inputs run full CI."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def classify(root, changes):
    """Only known explanatory Markdown additions/modifications can omit regression."""
    if not changes:
        return {'full': True, 'readme': False}
    readme = False
    for status, name in changes:
        path = PurePosixPath(name)
        readme |= name == 'README.md'
        if (status not in ('A', 'M') or path.is_absolute() or '..' in path.parts
                or path.name == 'AGENTS.md'
                or not (name == 'README.md' or
                        (path.parts[0] == 'docs' and path.suffix == '.md'))):
            return {'full': True, 'readme': readme}
        try:
            source = root / name
            if source.is_symlink() or root.resolve() not in source.resolve().parents:
                return {'full': True, 'readme': readme}
            content = source.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            return {'full': True, 'readme': readme}
        if 'agent-rules:begin' in content:
            return {'full': True, 'readme': readme}
    return {'full': False, 'readme': readme}


def selection(root, event_name, event):
    try:
        if event_name == 'pull_request':
            base = event['pull_request']['base']['sha']
            head = event['pull_request']['head']['sha']
        elif event_name == 'push':
            base, head = event['before'], event['after']
        else:
            raise ValueError('unsupported event')
        if not all(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40}', sha)
                   and sha != '0' * 40 for sha in (base, head)):
            raise ValueError('missing commit range')
        for sha in (base, head):
            git(root, 'cat-file', '-e', sha + '^{commit}')
        if event_name == 'pull_request':
            base = git(root, 'merge-base', base, head).decode().strip()
        fields = git(root, 'diff', '--raw', '-z', '--no-renames', base, head, '--').decode('utf-8').split('\0')
        if fields[-1] != '' or (len(fields) - 1) % 2:
            raise ValueError('invalid diff')
        changes = []
        modes_known = True
        for record, name in zip(fields[:-1:2], fields[1:-1:2]):
            old_mode, new_mode, _old_blob, _new_blob, status = record.split()
            modes_known &= (old_mode, new_mode, status) in (
                (':100644', '100644', 'M'), (':000000', '100644', 'A'))
            changes.append((status, name))
        result = classify(root, changes) if modes_known else {'full': True, 'readme': False}
        return {**result, 'base': base, 'head': head, 'changes': changes}
    except (KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        return {'full': True, 'readme': False, 'reason': 'range unavailable: ' + type(exc).__name__}


def gate(needs):
    """An intentional skip is valid only after successful, explicit classification."""
    light = needs.get('documentation', {})
    full = light.get('outputs', {}).get('full')
    return (light.get('result') == 'success' and full in ('true', 'false')
            and all(needs.get(job, {}).get('result') ==
                    ('success' if full == 'true' else 'skipped')
                    for job in ('checkout', 'package')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gate', action='store_true')
    args = parser.parse_args()
    if args.gate:
        needs = json.loads(os.environ['CI_NEEDS'])
        print(json.dumps(needs, sort_keys=True))
        return 0 if gate(needs) else 1
    try:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    except (KeyError, OSError, ValueError):
        event = {}
    result = selection(ROOT, os.environ.get('GITHUB_EVENT_NAME'), event)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
        for key in ('full', 'readme'):
            stream.write(f'{key}={str(result[key]).lower()}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
