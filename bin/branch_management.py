#!/usr/bin/env python3
"""Checkout compatibility entry; lifecycle ownership is the independent package."""
from workspace_lifecycle.cli import main
from workspace_lifecycle.compat import *

if __name__ == '__main__':
    raise SystemExit(main())
