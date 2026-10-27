"""Top-level ``ui`` (orb overlay) ships in the distribution.

``--orb-doctor`` and the desktop overlay import ``ui.orb…``. When ``ui`` was
missing from setup.py's package list, the installed console script raised
``ModuleNotFoundError: No module named 'ui'`` while the same command worked
from a checkout (issue #457). The list lives in setup.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _setup_script():  # noqa: ANN202
    """setup.py loaded as a module; its ``setup()`` call runs only as a script."""
    spec = importlib.util.spec_from_file_location("project_setup_script", ROOT / "setup.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ui_orb_packages_are_distributed() -> None:
    packages = set(_setup_script().packages(str(ROOT)))
    assert {"ui", "ui.orb"} <= packages


def test_orb_doctor_module_is_present_on_disk() -> None:
    assert (ROOT / "ui" / "orb" / "drag_persistence.py").is_file()
