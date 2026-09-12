"""Bind runtime adoption to the existing saved launch inputs, not a second catalog."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def _git(directory, *arguments):
    result = subprocess.run(['git', '-C', str(directory), *arguments],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError('cannot resolve committed catalog source')
    return result.stdout


def identity(place, args, context, site, source_ref='HEAD'):
    """Identify actual runtime inputs and their committed declaration source.

    A retained runtime HEAD may differ from the supplied source revision, but the
    catalog must be byte-identical to that revision. Other dirty files are neither
    guessed as belonging to this operation nor discarded.
    """
    binding = place.inventory_binding(args, context, site)
    if binding is None:
        raise ValueError('runtime adoption requires an INVENTORY binding')
    declaration, catalog, environment = binding
    inventory = place.environment_inventory
    inventory.snapshot_inputs([declaration, catalog])
    repo = Path(_git(catalog.parent, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    relative = catalog.resolve().relative_to(repo).as_posix()
    revision = _git(repo, 'rev-parse', '--verify', '--end-of-options', source_ref + '^{commit}').decode().strip()
    # Compare the checkout representation, including its declared Git EOL rules.
    committed = _git(repo, 'cat-file', '--filters', revision + ':' + relative)
    if catalog.read_bytes() != committed:
        raise ValueError('runtime catalog differs from source revision; preserve it and resolve the source')
    try:
        declared_relative = declaration.relative_to(repo).as_posix()
    except ValueError:
        declaration_source = 'external-runtime-policy'
    else:
        if declaration.read_bytes() != _git(repo, 'cat-file', '--filters', revision + ':' + declared_relative):
            raise ValueError('runtime declaration differs from catalog source revision')
        declaration_source = 'catalog-repository'
    sources = inventory.snapshot_inputs(place._inventory_source_paths(args))
    loaders = place._inventory_loader_inputs(args)
    code = inventory.snapshot_inputs([place.HERE / name for name in (
        'place.py', 'rules.py', 'environment_inventory.py', 'inventory_lifecycle.py',
        'inventory_adoption.py', 'inventory_inspection.py', 'work_classification.py')])
    digest = hashlib.sha256()
    for path, value in sorted({**sources, **code}.items(), key=lambda item: str(item[0])):
        digest.update(str(path).encode('utf-8'))
        digest.update(repr(value).encode('utf-8'))
    digest.update(repr(loaders).encode('utf-8'))
    digest.update(json.dumps(place.current_runtime(context), sort_keys=True).encode('utf-8'))
    return {'environment': environment, 'site': site, 'sourceRevision': revision,
            'sourceScope': 'catalog', 'declarationSource': declaration_source,
            'declarationDigest': hashlib.sha256(declaration.read_bytes()).hexdigest(),
            'runtimeHead': _git(repo, 'rev-parse', 'HEAD').decode().strip(),
            'repository': str(repo), 'catalog': relative, 'declaration': str(declaration),
            'catalogDigest': hashlib.sha256(committed).hexdigest(),
            'inputDigest': digest.hexdigest()}


def write_state(place, config, original, document, facts, state):
    """CAS the singleton adoption member under the caller's catalog lock."""
    inventory = place.environment_inventory
    inventory.snapshot_inputs([config])
    if config.read_bytes() != original:
        raise ValueError('saved launch inputs changed; preserve them and retry')
    # A tracked launch configuration is a shared declaration, not runtime state.
    result = subprocess.run(['git', '-C', str(config.parent), 'ls-files', '--error-unmatch',
                             '--', str(config)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        raise ValueError('runtime start config is tracked; select existing untracked runtime inputs')
    updated = dict(document, version=2, adoption=dict(facts, state=state))
    content = (json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if updated != document:
        mode = stat.S_IMODE(config.stat().st_mode)
        descriptor, temporary = tempfile.mkstemp(prefix='.place-adoption-', dir=config.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            inventory.snapshot_inputs([config])
            if config.read_bytes() != original:
                raise ValueError('saved launch inputs changed; preserve them and retry')
            os.replace(temporary, config)
            if os.name == 'posix':
                directory = os.open(config.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            if config.read_bytes() != content:
                raise ValueError('saved adoption readback differs; inspect retained runtime state')
        finally:
            Path(temporary).unlink(missing_ok=True)
    return config.read_bytes(), updated


def effective_active(place, args, context, site):
    """None means legacy inputs; False means a present but stale/pending adoption."""
    document = getattr(args, '_start_document', {})
    if document.get('version') != 2:
        return None
    adoption = document.get('adoption')
    if not isinstance(adoption, dict) or adoption.get('state') != 'active':
        return False
    try:
        expected = identity(place, args, context, site, adoption['sourceRevision'])
    except (KeyError, OSError, ValueError, place.environment_inventory.CatalogError):
        return False
    return adoption == dict(expected, state='active')
