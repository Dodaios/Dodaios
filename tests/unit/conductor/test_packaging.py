"""Conductor ships in the distribution, data files included.

``conductor`` was missing from the package list: it imported only when the
app's working directory was the checkout (run.bat), so the console script,
autostart and every wheel install served no ``/api/conductor/*`` at all and
``jarvis conductor ...`` answered 404. The list lives in setup.py.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _setuptools_cfg() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["tool"]["setuptools"]


def _setup_script():  # noqa: ANN202
    """setup.py loaded as a module; its ``setup()`` call runs only as a script."""
    spec = importlib.util.spec_from_file_location("project_setup_script", ROOT / "setup.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conductor_packages_are_distributed() -> None:
    packages = set(_setup_script().packages(str(ROOT)))
    assert {"conductor", "conductor.api", "conductor.core", "conductor.jobs"} <= packages


def test_pyproject_declares_no_package_list_that_would_override_setup_py() -> None:
    assert "packages" not in _setuptools_cfg()


def test_conductor_runtime_data_files_are_declared() -> None:
    patterns = _setuptools_cfg()["package-data"]["conductor"]
    data_files = [
        path.relative_to(ROOT / "conductor").as_posix()
        for path in (ROOT / "conductor").rglob("*")
        if path.is_file() and path.suffix in {".sql", ".yaml"}
    ]
    assert data_files
    undeclared = [
        name for name in data_files if not any(fnmatch.fnmatch(name, p) for p in patterns)
    ]
    assert undeclared == []
