#!/usr/bin/env python3
"""Checkout compatibility entry; lifecycle ownership is the independent package."""
from pathlib import Path
import sys

# Checkout use is explicit. The independent wheel never imports this repository.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'packages/workspace-lifecycle/src'))
from workspace_lifecycle.cli import main
from workspace_lifecycle.compat import *

if __name__ == '__main__':
    raise SystemExit(main())
