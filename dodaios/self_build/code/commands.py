"""How a project is tested, read from its files and nothing else.

The test command is the judge of a loop-made change, so it comes from the
project as it was BEFORE the coding agent touched it, never from the agent.
Detection is deterministic and conservative: a project whose tests cannot be
found is not worked on (triage refuses it), rather than shipped untested.
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


def _python(folder: Path) -> str:
    """The project's own interpreter when it has a virtual environment."""
    for name in _VENVS:
        for rel in ("Scripts/python.exe", "bin/python"):
            candidate = folder / name / rel
            if candidate.is_file():
                return str(candidate)
    return "python"


def _python_tests(folder: Path) -> bool:
    has_tests = any((folder / name).is_dir() for name in ("tests", "test"))
    if (folder / "pytest.ini").is_file() or (folder / "conftest.py").is_file():
        return True
    if "[tool.pytest" in _read(folder / "pyproject.toml"):
        return True
    if "[tool:pytest]" in _read(folder / "setup.cfg"):
        return True
    markers = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "tox.ini")
    return has_tests and any((folder / m).is_file() for m in markers)


def _node(folder: Path) -> tuple[list[list[str]], list[list[str]]]:
    raw = _read(folder / "package.json")
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
    if (folder / "pnpm-lock.yaml").is_file():
        return [["pnpm", "install", "--frozen-lockfile"]], [["pnpm", "test"]]
    if (folder / "yarn.lock").is_file():
        return [["yarn", "install", "--frozen-lockfile"]], [["yarn", "test"]]
    setup = [["npm", "ci"]] if (folder / "package-lock.json").is_file() else [["npm", "install"]]
    return setup, [["npm", "test", "--silent"]]


def _makefile_test(folder: Path) -> bool:
    text = _read(folder / "Makefile")
    return bool(re.search(r"^test\s*:", text, re.MULTILINE))


def ci_lines(folder: Path, limit: int = 8) -> list[str]:
    """The workflow files and the test lines they run (for the brief only)."""
    workflows = folder / ".github" / "workflows"
    if not workflows.is_dir():
        return []
    lines: list[str] = []
    try:
        files = sorted(p for p in workflows.iterdir() if p.suffix in (".yml", ".yaml"))
    except OSError:  # unreadable workflows only leave the brief without CI lines
        return []
    for path in files[:12]:
        runs = [
            match.group(1).strip()
            for match in map(_WORKFLOW_RUN.match, _read(path, 60_000).splitlines())
            if match and _TESTY.search(match.group(1))
        ]
        lines.append(f"{path.name}: " + ("; ".join(runs[:3]) if runs else "(no test step)"))
        if len(lines) >= limit:
            break
    return lines


def detect(folder: str | Path) -> dict[str, Any]:
    """``{"label", "setup", "test", "ci"}``: argv lists, empty when unknown."""
    root = Path(folder)
    setup: list[list[str]] = []
    test: list[list[str]] = []
    label = ""
    if _python_tests(root):
        test.append([_python(root), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"])
        label = "pytest"
    node_setup, node_test = _node(root)
    if node_test:
        setup += node_setup
        test += node_test
        label = label or node_test[0][0]
    if (root / "Cargo.toml").is_file():
        test.append(["cargo", "test", "--quiet"])
        label = label or "cargo"
    if (root / "go.mod").is_file():
        test.append(["go", "test", "./..."])
        label = label or "go"
    if not test and _makefile_test(root):
        test.append(["make", "test"])
        label = "make"
    return {"label": label, "setup": setup, "test": test, "ci": ci_lines(root)}


def runnable(argv: list[str]) -> str:
    """A command exactly as the judge runs it, quoted for this platform's shell."""
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def shown(argv: list[str]) -> str:
    """A command as the person would type it (the venv path shortened)."""
    if argv and Path(argv[0]).name.lower().startswith("python") and len(argv[0]) > 12:
        return " ".join(["python", *argv[1:]])
    return " ".join(argv)
