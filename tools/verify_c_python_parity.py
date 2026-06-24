#!/usr/bin/env python3
"""Run C extension vs pure-Python parser parity tests."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_c_python_parity_unit.py",
        "tests/test_regressions_unit.py",
        "-v",
        "--tb=short",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
