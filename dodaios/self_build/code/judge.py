"""The judge of a loop-made change, which the coding agent cannot edit.

Two checks, both in Python:

* :func:`guard` refuses a change that touches what the loop must never touch:
  CI config, deployment, secrets and credentials, and the repository's own
  instruction files (the rules the agent was told to follow).
* :func:`run_tests` runs the test commands the brief read from the project
  BEFORE the run, in the worktree, with a time limit.

CI on the pull request is the second judge (``watch``).
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Final

from . import commands, gitcmd

PROTECTED: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?:^|/)(?:"
    r"\.github/|\.gitlab-ci\.ya?ml$|\.circleci/|azure-pipelines\.ya?ml$|jenkinsfile$|"
    r"\.env(?:\..*)?$|.*secrets?.*|.*credentials?.*|.*\.pem$|.*\.key$|id_rsa.*|"
    r"\.npmrc$|\.pypirc$|"
    r"deploy(?:ment)?s?/|.*deploy.*\.(?:ya?ml|sh|ps1)$|dockerfile$|docker-compose.*\.ya?ml$|"
    r"terraform/|.*\.tf$|helm/|k8s/|kubernetes/|"
    r"agents\.md$|claude\.md$|gemini\.md$|copilot-instructions\.md$"
    r")"
)
SETUP_TIMEOUT_S: Final[float] = 15 * 60.0
TEST_TIMEOUT_S: Final[float] = 20 * 60.0


def guard(changed: list[str]) -> list[str]:
    """The changed paths the loop may not ship (empty: the change may go on)."""
    return [path for path in changed if PROTECTED.search(path.replace("\\", "/"))]


def _env(worktree: Path) -> dict[str, str]:
    env = dict(os.environ)
    paths = [str(worktree)]
    if (worktree / "src").is_dir():
        paths.insert(0, str(worktree / "src"))
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.setdefault("CI", "1")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _needs_setup(worktree: Path, argv: list[str]) -> bool:
    if argv and argv[0] in ("npm", "pnpm", "yarn"):
        return not (worktree / "node_modules").is_dir()
    return True


def run_tests(
    worktree: str | Path,
    *,
    setup: list[list[str]],
    tests: list[list[str]],
    test_timeout_s: float = TEST_TIMEOUT_S,
) -> tuple[bool, str]:
    """``(passed, detail)``. No test command is a failure, never a pass."""
    root = Path(worktree)
    if not tests:
        return False, "no test command"
    env = _env(root)
    for argv in setup:
        if not _needs_setup(root, argv):
            continue
        result = gitcmd.run(argv, root, timeout=SETUP_TIMEOUT_S, env=env)
        if not result.ok:
            return False, f"`{commands.shown(argv)}` failed:\n{result.tail()}"
    lines: list[str] = []
    for argv in tests:
        started = time.monotonic()
        result = gitcmd.run(argv, root, timeout=test_timeout_s, env=env)
        took = int(time.monotonic() - started)
        if not result.ok:
            return False, f"`{commands.shown(argv)}` failed after {took} s:\n{result.tail()}"
        lines.append(f"`{commands.shown(argv)}` passed in {took} s")
    return True, "\n".join(lines)
