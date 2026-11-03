#!/usr/bin/env python3
"""Bump packages in ``uv.lock`` and ``requirements.txt`` the way CI checks them.

Dependabot's uv security updates rewrite ``requirements.txt`` from
``requirements.in`` without ``--emit-find-links`` and the pyproject header, so
the deps-sync gate (``check_portable_install_matrix.py``) rejects them as "not a
byte-identical no-upgrade universal/hash recompile". Service such a pull
request by resetting its branch onto ``main`` and running, from the repo root::

    python scripts/ci/bump_locked_package.py pypdf==6.21.4 [pyasn1==0.6.5 ...]

It upgrades only the named packages, using the gate's own uv flags and compile
command, then runs the gate's lock and recompile checks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))

import check_portable_install_matrix as matrix  # noqa: E402


def upgrade_flags(packages: list[str]) -> list[str]:
    flags: list[str] = []
    for package in packages:
        flags += ["--upgrade-package", package]
    return flags


def main(argv: list[str] | None = None) -> int:
    packages = list(sys.argv[1:] if argv is None else argv)
    if not packages or any(p.startswith("-") for p in packages):
        print(__doc__)
        return 2
    error = matrix._verify_uv_version()
    if error:
        print(f"FAIL: {error}")
        return 1
    commands = (
        ["uv", "lock", *upgrade_flags(packages), *matrix._public_uv_flags()],
        matrix.requirements_compile_command(*upgrade_flags(packages)),
    )
    for command in commands:
        print("+", " ".join(command), flush=True)
        if subprocess.run(command, cwd=REPO_ROOT).returncode:
            return 1
    for check in (matrix._verify_uv_lock, matrix._verify_reproducible_requirements):
        error = check()
        if error:
            print(f"FAIL: {error}")
            return 1
    print("OK: uv.lock and requirements.txt match what the deps-sync gate expects.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
