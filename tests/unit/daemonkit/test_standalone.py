"""daemonkit must stay liftable: standard library only, and it works under another name."""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[3] / "daemonkit"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_only_the_standard_library_is_imported() -> None:
    allowed = set(sys.stdlib_module_names)
    for path in PACKAGE.rglob("*.py"):
        outside = _imports(path) - allowed - {"__future__"}
        assert not outside, f"{path.relative_to(PACKAGE)} imports {sorted(outside)}"


def test_internal_imports_are_relative() -> None:
    """Absolute ``daemonkit.`` imports would break a copy under another package."""
    for path in PACKAGE.rglob("*.py"):
        assert "daemonkit" not in _imports(path), path


def test_a_copy_inside_another_package_supervises_under_its_own_name(tmp_path: Path) -> None:
    vendor = tmp_path / "myapp" / "vendor"
    vendor.mkdir(parents=True)
    (tmp_path / "myapp" / "__init__.py").touch()
    (vendor / "__init__.py").touch()
    shutil.copytree(PACKAGE, vendor / "daemonkit", ignore=shutil.ignore_patterns("__pycache__"))
    code = (
        "from myapp.vendor.daemonkit import Daemon;"
        "d = Daemon('x', ['srv'], state_dir='.');"
        "print(d.supervisor_argv(windowless=False)[2])"
    )
    result = subprocess.run(  # noqa: S603 - test helper
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, '.'); {code}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "myapp.vendor.daemonkit.supervise"


def test_the_package_has_its_own_project_file() -> None:
    text = (PACKAGE / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "daemonkit"' in text
    assert "dependencies = []" in text


def test_dodaios_ships_daemonkit_with_its_own_packages() -> None:
    """The agent server's supervisor runs ``daemonkit.supervise``; a wheel without it breaks it."""
    import importlib.util

    root = PACKAGE.parent
    spec = importlib.util.spec_from_file_location("project_setup_script", root / "setup.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {"daemonkit", "daemonkit.service"} <= set(module.packages(str(root)))
    assert 'collect_submodules("daemonkit")' in (root / "dodaios.spec").read_text(encoding="utf-8")
