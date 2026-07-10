#!/usr/bin/env python3
"""Repository entry point for the NM V6 deterministic core."""

import sys


if sys.version_info < (3, 11):
    print("ERROR: NM V6 requires Python 3.11 or newer", file=sys.stderr)
    raise SystemExit(2)

from nmv6.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
