"""How a project is tested, read from its files and nothing else.

The test command is the judge of a loop-made change, so it comes from the
project as it was BEFORE the coding agent touched it, never from the agent.
Detection is deterministic and conservative: a project whose tests cannot be
found is not worked on (triage refuses it), rather than shipped untested.

:func:`detect` reads the folder on disk, or any object that answers the same
questions about a project's files (``files``: ``is_file``, ``is_dir``,
``read``, ``names``, ``root``), such as one commit of a repository read from
git (``dodaios.rsi.bench.at_commit``).
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

#: Where a project keeps its virtual environment, newest convention first.
_VENVS = (".venv", "venv", "env")
_WORKFLOW_RUN = re.compile(r"^\s*(?:-\s*)?run:\s*(.+)$")
_TESTY = re.compile(
    r"\b(pytest|tox|nox|jest|vitest|mocha|npm (?:run )?test|pnpm (?:run )?test|yarn test|"
    r"cargo test|go test|make test|gradle test|mvn test)\b"
)


def _read(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:  # an unreadable file counts as absent: no command from it
        return ""


class _Disk:
    """A project's folder on disk, asked about by paths relative to it."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def is_file(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def is_dir(self, rel: str) -> bool:
        return (self.root / rel).is_dir()

    def read(self, rel: str, limit: int = 200_000) -> str:
        return _read(self.root / rel, limit)

    def names(self, rel: str) -> list[str]:
        return [p.name for p in (self.root / rel).iterdir()]


def _python(files: Any) -> str:
    """The project's own interpreter when it has a virtual environment."""
    for name in _VENVS:
        for rel in ("Scripts/python.exe", "bin/python"):
            if files.is_file(f"{name}/{rel}"):
                return str(Path(files.root) / name / rel)
    return "python"


def _python_tests(files: Any) -> bool:
    has_tests = any(files.is_dir(name) for name in ("tests", "test"))
    if files.is_file("pytest.ini") or files.is_file("conftest.py"):
        return True
    if "[tool.pytest" in files.read("pyproject.toml", 200_000):
        return True
    if "[tool:pytest]" in files.read("setup.cfg", 200_000):
        return True
    markers = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "tox.ini")
    return has_tests and any(files.is_file(m) for m in markers)


def _node(files: Any) -> tuple[list[list[str]], list[list[str]]]:
    raw = files.read("package.json", 200_000)
    if not raw:
        return [], []
    try:
        package = json.loads(raw)
    except ValueError:  # a broken package.json gives no test command, so no build
        return [], []
    scripts = package.get("scripts") if isinstance(package, dict) else None
    test = str((scripts or {}).get("test") or "") if isinstance(scripts, dict) else ""
    if not test or "no test specified" in test:
        return [], []
    if files.is_file("pnpm-lock.yaml"):
        return [["pnpm", "install", "--frozen-lockfile"]], [["pnpm", "test"]]
    if files.is_file("yarn.lock"):
        return [["yarn", "install", "--frozen-lockfile"]], [["yarn", "test"]]
    setup = [["npm", "ci"]] if files.is_file("package-lock.json") else [["npm", "install"]]
    return setup, [["npm", "test", "--silent"]]


def _makefile_test(files: Any) -> bool:
    text = files.read("Makefile", 200_000)
    return bool(re.search(r"^test\s*:", text, re.MULTILINE))


def ci_lines(folder: Path, limit: int = 8, *, files: Any = None) -> list[str]:
    """The workflow files and the test lines they run (for the brief only)."""
    files = files if files is not None else _Disk(Path(folder))
    where = ".github/workflows"
    if not files.is_dir(where):
        return []
    lines: list[str] = []
    try:
        names = sorted(n for n in files.names(where) if Path(n).suffix in (".yml", ".yaml"))
    except OSError:  # unreadable workflows only leave the brief without CI lines
        return []
    for name in names[:12]:
        text = files.read(f"{where}/{name}", 60_000)
        runs = [
            match.group(1).strip()
            for match in map(_WORKFLOW_RUN.match, text.splitlines())
            if match and _TESTY.search(match.group(1))
        ]
        lines.append(f"{name}: " + ("; ".join(runs[:3]) if runs else "(no test step)"))
        if len(lines) >= limit:
            break
    return lines


def detect(folder: str | Path, *, files: Any = None) -> dict[str, Any]:
    """``{"label", "setup", "test", "ci"}``: argv lists, empty when unknown.

    ``files`` answers for the project instead of its folder on disk (see the module text).
    """
    root = Path(folder)
    files = files if files is not None else _Disk(root)
    setup: list[list[str]] = []
    test: list[list[str]] = []
    label = ""
    if _python_tests(files):
        test.append([_python(files), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"])
        label = "pytest"
    node_setup, node_test = _node(files)
    if node_test:
        setup += node_setup
        test += node_test
        label = label or node_test[0][0]
    if files.is_file("Cargo.toml"):
        test.append(["cargo", "test", "--quiet"])
        label = label or "cargo"
    if files.is_file("go.mod"):
        test.append(["go", "test", "./..."])
        label = label or "go"
    if not test and _makefile_test(files):
        test.append(["make", "test"])
        label = "make"
    return {"label": label, "setup": setup, "test": test, "ci": ci_lines(root, files=files)}


def runnable(argv: list[str]) -> str:
    """A command exactly as the judge runs it, quoted for this platform's shell."""
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def shown(argv: list[str]) -> str:
    """A command as the person would type it (the venv path shortened)."""
    if argv and Path(argv[0]).name.lower().startswith("python") and len(argv[0]) > 12:
        return " ".join(["python", *argv[1:]])
    return " ".join(argv)
