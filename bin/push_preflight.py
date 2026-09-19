#!/usr/bin/env python3
"""Compatibility entry for the independent workspace push policy."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'packages/workspace-lifecycle/src'))
from workspace_lifecycle.push import *

if __name__ == '__main__':
    raise SystemExit(main())
