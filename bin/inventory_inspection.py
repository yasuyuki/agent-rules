"""Read-only validation of Grok's official workspace inspection output."""
import json
import os
import subprocess


def _absolute(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def _project_path(path, cwd):
    return path == cwd or path.startswith(cwd + os.sep)


def _within(path, parent):
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def _error(reason, cwd):
    raise ValueError('Grok inspect ' + reason + ' for cwd ' + cwd)


def inspect_grok(*, executable, cwd, instruction_paths, skill_paths, runner=subprocess.run):
    """Validate selected paths from ``grok inspect --json`` without changing trust.

    Only the requested discovery facts are returned.  Diagnostics deliberately do
    not include Grok's stdout, stderr, or other configuration fields.
    """
    requested_cwd = _absolute(cwd)
    expected_instructions = {_absolute(path) for path in instruction_paths}
    expected_skills = {_absolute(path) for path in skill_paths}
    completed = runner(
        [os.fspath(executable), 'inspect', '--json'], cwd=requested_cwd,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True)
    if completed.returncode != 0:
        _error('failed', requested_cwd)
    if not isinstance(completed.stdout, str):
        _error('returned invalid JSON', requested_cwd)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        _error('returned invalid JSON', requested_cwd)
    if not isinstance(payload, dict):
        _error('returned invalid output', requested_cwd)

    reported_cwd = payload.get('cwd')
    project_root = payload.get('projectRoot')
    trusted = payload.get('projectTrusted')
    instructions = payload.get('projectInstructions')
    skills = payload.get('skills')
    if (not isinstance(reported_cwd, str) or not os.path.isabs(reported_cwd)
            or _absolute(reported_cwd) != requested_cwd):
        _error('reported a different cwd', requested_cwd)
    if not isinstance(project_root, str) or not os.path.isabs(project_root):
        _error('returned invalid project root', requested_cwd)
    normalized_root = _absolute(project_root)
    if not _within(requested_cwd, normalized_root):
        _error('reported a foreign project root', requested_cwd)
    if not isinstance(trusted, bool):
        _error('returned invalid trust state', requested_cwd)
    if not isinstance(instructions, list) or not isinstance(skills, list):
        _error('returned invalid discovery lists', requested_cwd)

    requires_project_trust = any(
        _project_path(path, requested_cwd)
        for path in expected_instructions | expected_skills
    )
    if requires_project_trust and not trusted:
        _error('found an untrusted project', requested_cwd)

    discovered_instructions = set()
    for item in instructions:
        path = item.get('path') if isinstance(item, dict) else None
        if isinstance(path, str) and os.path.isabs(path):
            discovered_instructions.add(_absolute(path))

    discovered_skills = set()
    for item in skills:
        source = item.get('source') if isinstance(item, dict) else None
        path = source.get('path') if isinstance(source, dict) else None
        if isinstance(path, str) and os.path.isabs(path):
            discovered_skills.add(_absolute(path))

    if not expected_instructions.issubset(discovered_instructions):
        _error('did not discover required instructions', requested_cwd)
    if not expected_skills.issubset(discovered_skills):
        _error('did not discover required skills', requested_cwd)
    return {
        'cwd': requested_cwd,
        'projectTrusted': trusted,
        'instructionPaths': sorted(expected_instructions),
        'skillPaths': sorted(expected_skills),
    }
