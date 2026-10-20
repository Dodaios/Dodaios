"""The earlier package name ships as an alias, built from a folder of another name.

``python -m jarvis`` and ``import jarvis.x`` stay valid for autostart entries
and MCP registrations written before the rename. The alias source lives in
``dodaios/_legacy_alias`` and setup.py publishes it as the top-level
``jarvis`` package, so the repository itself has no folder or file of that
name. These tests run the real setup.py helper and the real alias module; a
wheel round trip is too slow for the unit suite.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from dodaios.core import branding

ROOT = Path(__file__).resolve().parents[3]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _setup_script():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("project_setup_script", ROOT / "setup.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_publishes_the_alias_once_under_its_earlier_name() -> None:
    script = _setup_script()
    packages = script.packages(str(ROOT))

    assert script.LEGACY_PACKAGE == branding.LEGACY_PACKAGE_NAMES[0]
    assert packages.count(script.LEGACY_PACKAGE) == 1
    # Built only as ``jarvis``, never a second time as a dodaios subpackage.
    assert not [name for name in packages if name.startswith("dodaios._legacy_alias")]
    assert "dodaios" in packages
    assert (ROOT / script.LEGACY_PACKAGE_DIR / "__init__.py").is_file()


def test_the_alias_resolves_old_names_to_the_same_module_objects() -> None:
    """What an installed wheel does: the folder is imported as ``jarvis``."""
    probe = (
        "import importlib.util, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"init = {str(ROOT / 'dodaios' / '_legacy_alias' / '__init__.py')!r}\n"
        "spec = importlib.util.spec_from_file_location('jarvis', init,"
        " submodule_search_locations=[])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['jarvis'] = module\n"
        "spec.loader.exec_module(module)\n"
        "import dodaios, dodaios.core.branding\n"
        "import jarvis.core.branding\n"
        "assert sys.modules['jarvis'] is dodaios\n"
        "assert jarvis.core.branding is dodaios.core.branding\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        creationflags=_NO_WINDOW,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_the_repository_tracks_no_path_with_the_earlier_name() -> None:
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            check=True,
            timeout=60,
            creationflags=_NO_WINDOW,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    paths = [name for name in listing.decode("utf-8", "replace").split("\0") if name]
    assert paths
    assert [name for name in paths if "jarvis" in name.lower()] == []
