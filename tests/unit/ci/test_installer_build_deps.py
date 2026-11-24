"""The native installers freeze the dependency set that ``uv.lock`` names.

``desktop-installers.yml`` builds what people download and what the in-app
updater installs. Its build jobs once ran ``pip install -e ".[desktop,dev]"``:
every version range was resolved anew on the day of the release and no hash
was checked, so the frozen app carried packages no test had seen. The jobs
now install through ``scripts/ci/install_locked.py`` (the lock, hashes
enforced), like every test job.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "desktop-installers.yml"
ACTION = ROOT / ".github" / "actions" / "install-locked" / "action.yml"

#: job -> the project extras its frozen app is built from.
BUILD_JOBS = {
    "windows": ["desktop", "dev"],
    "macos": ["desktop", "desktop-macos", "dev"],
    "linux": ["desktop", "dev"],
}


def _steps(job: str) -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"][job]["steps"]


def _commands(steps: list[dict]) -> list[str]:
    """Every shell line of ``steps`` that is not a comment."""
    lines = [line.strip() for step in steps for line in str(step.get("run", "")).splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def _uv_pin() -> str:
    """The uv version the test jobs install the lock with."""
    found = re.search(r"\buv==([0-9][0-9.]*)", ACTION.read_text(encoding="utf-8"))
    assert found, "the install-locked action no longer pins uv"
    return found.group(1)


@pytest.mark.parametrize(("job", "extras"), sorted(BUILD_JOBS.items()))
def test_a_frozen_app_is_built_from_the_locked_set_with_hashes(job: str, extras: list[str]) -> None:
    steps = _steps(job)
    names = [str(step.get("name", "")) for step in steps]
    build = next(i for i, name in enumerate(names) if name.startswith("Build the "))
    before_the_freeze = _commands(steps[:build])

    # The lock is installed once, for exactly the extras this app ships.
    wanted = " ".join(f"--extra {extra}" for extra in extras)
    locked = [line for line in before_the_freeze if "install_locked.py" in line]
    assert locked == [f"python scripts/ci/install_locked.py {wanted}"]

    # Nothing else puts a Python package into the environment that is frozen:
    # pip only fetches uv, at the version the test jobs use.
    installs = [line for line in before_the_freeze if re.search(r"\bpip(3)?\b.*\binstall\b", line)]
    assert installs == [f"python -m pip install --disable-pip-version-check uv=={_uv_pin()}"]
    assert not [line for line in before_the_freeze if "pip_install.py" in line]
    assert not [line for line in before_the_freeze if re.search(r"-e\s+[\"']?\.", line)]


@pytest.mark.parametrize("job", sorted(BUILD_JOBS))
def test_a_release_build_restores_no_cache(job: str) -> None:
    """The install-locked action restores a build cache; a release build must not."""
    uses = [str(step.get("uses", "")) for step in _steps(job)]
    assert not [action for action in uses if "install-locked" in action]
    assert not [action for action in uses if action.startswith("actions/cache")]


def test_every_extra_an_installer_needs_is_in_the_lock() -> None:
    """`uv export --frozen` fails on an extra the lock does not know."""
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    provided = re.search(r"^provides-extras = \[(.*?)\]", lock, re.M | re.S)
    assert provided, "uv.lock names no extras for the project"
    known = set(re.findall(r'"([^"]+)"', provided.group(1)))
    for extras in BUILD_JOBS.values():
        assert set(extras) <= known
