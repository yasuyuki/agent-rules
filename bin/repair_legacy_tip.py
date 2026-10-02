#!/usr/bin/env python3
"""Repair one approved legacy task tip without changing its Git worktree."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
from datetime import datetime, timezone


class RepairError(RuntimeError): pass


def digest(value): return hashlib.sha256(value).hexdigest()


def regular(path, *, outside=None):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise RepairError('expected a regular file: ' + str(path))
    if outside and path.resolve().is_relative_to(Path(outside).resolve()):
        raise RepairError('path must be outside target top')
    return path.resolve()


def load_owner(path, expected):
    root = Path(path).resolve()
    path = regular(root / 'bin' / 'branch_management.py')
    if digest(path.read_bytes()) != expected:
        raise RepairError('owner module digest changed')
    spec = importlib.util.spec_from_file_location('pinned_legacy_owner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ('locked', 'assert_install', 'checkout', 'save', 'oid', 'ancestor', 'git_bytes'):
        if not callable(getattr(module, name, None)):
            raise RepairError('owner module lacks ' + name)
    return root, module


def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def artifact(manifest, value, top):
    path = Path(value['path'])
    if path.is_absolute() or '..' in path.parts:
        raise RepairError('artifact path must be relative')
    path = regular(manifest.parent / path, outside=top)
    data = path.read_bytes()
    if digest(data) != value.get('sha256'):
        raise RepairError('artifact digest changed')
    return data


def repair(args):
    if not args.approval.strip():
        raise RepairError('explicit approval is required')
    source, owner = load_owner(args.owner_source, args.owner_module_sha256)
    repo, top = Path(args.repo).resolve(), Path(args.top).resolve()
    manifest = regular(args.evidence, outside=top)
    raw = manifest.read_bytes()
    if digest(raw) != args.evidence_sha256:
        raise RepairError('evidence digest changed')
    try: evidence = json.loads(raw)
    except json.JSONDecodeError as exc: raise RepairError('invalid evidence') from exc
    if set(evidence) != {'version', 'task', 'branch', 'top', 'old', 'new', 'artifacts', 'untracked'} or evidence['version'] != 1 or evidence.get('untracked') != []:
        raise RepairError('invalid evidence schema')
    if {key: evidence.get(key) for key in ('task','branch','top','old','new')} != {key: getattr(args, key) for key in ('task','branch','top','old','new')}:
        raise RepairError('evidence identity differs')
    artifacts = evidence['artifacts']
    if set(artifacts) != {'index_patch', 'worktree_patch'}:
        raise RepairError('invalid evidence artifacts')
    index, worktree = artifact(manifest, artifacts['index_patch'], top), artifact(manifest, artifacts['worktree_patch'], top)
    if not all(isinstance(getattr(args, name), str) and len(getattr(args, name)) == 40 and all(c in '0123456789abcdef' for c in getattr(args, name)) for name in ('old','new')):
        raise RepairError('old and new must be full lowercase object IDs')
    with owner.locked(repo) as (directory, state):
        owner.assert_install(repo, directory, state)
        if Path(state.get('source', '')).resolve() != source or state.get('source_hashes', {}).get('bin/branch_management.py') != args.owner_module_sha256:
            raise RepairError('registered owner source differs')
        key, task = owner.checkout(repo, state)
        if key != args.task or task.get('branch') != args.branch or task.get('worktree') != str(top):
            raise RepairError('selected task identity differs')
        if not (task.get('branch') == state.get('default') == task.get('into') == args.branch):
            raise RepairError('selected task is not the legacy default task')
        if (task.get('creating') or args.branch in state.get('permits', {})
                or any(destination == args.branch or ticket.get('task') == key
                       for destination, ticket in state.get('merges', {}).items())
                or any(pick.startswith(args.branch + ':') for pick in state.get('picks', {}))):
            raise RepairError('selected task has an incompatible operation')
        if any((lambda path: (path if path.is_absolute() else repo / path).exists())(Path(owner.git(repo, 'rev-parse', '--git-path', marker))) for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'sequencer')):
            raise RepairError('Git operation is in progress')
        old, new = owner.oid(repo, args.old), owner.oid(repo, args.new)
        if old != args.old or new != args.new or owner.oid(repo, 'HEAD') != new or owner.oid(repo, 'refs/heads/' + args.branch) != new:
            raise RepairError('HEAD or branch does not match new tip')
        if task.get('tip') not in (old, new) or old == new or not owner.ancestor(repo, old, new):
            raise RepairError('legacy tip is not an old ancestor of new')
        if owner.git_bytes(repo, 'diff', '--cached', '--binary', '--no-ext-diff') != index or owner.git_bytes(repo, 'diff', '--binary', '--no-ext-diff') != worktree:
            raise RepairError('dirty artifacts changed')
        if owner.git_bytes(repo, 'ls-files', '--others', '--exclude-standard', '-z') != b'':
            raise RepairError('untracked files are not permitted')
        dirty = digest(b'\0'.join((owner.oid(repo, 'HEAD').encode(), owner.git_bytes(repo, 'ls-files', '--stage', '-z'), index, worktree)))
        receipts = state.setdefault('tip_repairs', [])
        identity = {'schema': 1, 'kind': 'legacy-tip-repair', 'task': key, 'branch': args.branch, 'top': str(top), 'request': task.get('request'), 'base': task.get('base'), 'into': task.get('into'), 'old': old, 'new': new, 'approval': args.approval, 'evidence': str(manifest), 'evidence_sha256': args.evidence_sha256, 'dirty_fingerprint': dirty}
        receipt_id = digest(canonical(identity))
        matches = [r for r in receipts if {key: value for key, value in r.items() if key not in ('id', 'created_at')} == identity and r.get('id') == receipt_id]
        if task['tip'] == new:
            if len(matches) != 1:
                raise RepairError('new tip needs its exact prior receipt')
            return {'changed': False, 'receipt': matches[0]}
        if any(receipt.get('task') == key for receipt in receipts):
            raise RepairError('selected task already has a different repair receipt')
        before = dirty
        receipt = {**identity, 'id': receipt_id, 'created_at': datetime.now(timezone.utc).isoformat()}
        task['tip'] = new; receipts.append(receipt)
        after = digest(b'\0'.join((owner.oid(repo, 'HEAD').encode(), owner.git_bytes(repo, 'ls-files', '--stage', '-z'), owner.git_bytes(repo, 'diff', '--cached', '--binary', '--no-ext-diff'), owner.git_bytes(repo, 'diff', '--binary', '--no-ext-diff'))))
        if after != before:
            raise RepairError('workspace changed during repair')
        owner.save(directory, state)
        return {'changed': True, 'receipt': receipt}


def main(argv=None):
    parser = argparse.ArgumentParser()
    for name in ('repo','owner-source','owner-module-sha256','task','branch','top','old','new','approval','evidence','evidence-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps({'ok': True, **repair(args)}, sort_keys=True)); return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, sort_keys=True), file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
