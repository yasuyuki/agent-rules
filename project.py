"""Place explicitly selected native Rulesync sources; no environment enrollment."""
from __future__ import annotations
import argparse
from importlib.metadata import version
import json
from pathlib import Path
import sys
from .bin import rulesync_backend as backend


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=version("agent-rules"))
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("apply", "check", "handover"):
        entry = sub.add_parser(command)
        entry.add_argument("--config", required=True, type=Path,
                           help="explicit Rulesync placement configuration")
        entry.add_argument("--rulesync", help="installed Rulesync 16.39.1 executable")
        if command == "handover":
            entry.add_argument("--plan", required=True, type=Path,
                               help="explicit reviewed legacy before-state plan")
    args = parser.parse_args(argv)
    try:
        if args.command == "handover":
            result = backend.handover(args.config, args.plan, rulesync=args.rulesync)
        else:
            result = getattr(backend, args.command)(args.config, rulesync=args.rulesync)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if args.command == "check" and not result else 0
    except (backend.BackendError, OSError, ValueError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
