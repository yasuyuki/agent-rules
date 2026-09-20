"""One-way checkout compatibility entry to the independent runtime package.

Legacy adoption documents are deliberately not converted during launch.
"""
from pathlib import Path
import argparse
import json
import os
import sys


def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    if not values or values[0] not in {"start", "standard-start"}:
        raise ValueError("runtime entry requires start or standard-start")
    command = values.pop(0)
    # argparse's REMAINDER would swallow options after the command positional.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--handoff-independent', action='store_true')
    parser.add_argument('selection', nargs=argparse.REMAINDER)
    args = parser.parse_args(values)
    selected = args.selection
    try:
        if command == 'start':
            if len(selected) < 2:
                parser.error('start requires WORKSPACE TOOL [-- VENDOR-ARGS]')
            workspace, tool, *native = selected
            path = args.config or os.environ.get('AGENT_RUNTIME_CONFIG')
            if not path:
                raise ValueError('explicit adopted runtime config required; legacy placement inputs are not launch inputs')
            document = json.loads(Path(path).read_text(encoding='utf-8'))
            matches = [w for w in document.get('workspaces', []) if w.get('id') == workspace]
            if len(matches) != 1:
                raise ValueError('runtime workspace id is missing or ambiguous: ' + workspace)
            if args.config:
                args.config = str(Path(args.config).absolute())
            elif path:
                os.environ['AGENT_RUNTIME_CONFIG'] = str(Path(path).absolute())
            os.chdir(matches[0]['root'])
        else:
            if not selected:
                parser.error('standard-start requires TOOL [-- VENDOR-ARGS]')
            tool, *native = selected
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packages/agent-runtime/src'))
        from agent_runtime.cli import main as runtime_main
        arguments = (['--config', args.config] if args.config else [])
        if args.handoff_independent:
            arguments.append('--handoff-independent')
        return runtime_main([*arguments, tool, *native])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('runtime: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
