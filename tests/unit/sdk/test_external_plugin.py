"""An external plugin works with only dodaios-sdk installed (no other repo code)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SDK = Path(__file__).resolve().parents[3] / "sdk"

pytestmark = [pytest.mark.integration, pytest.mark.timeout(300)]


def test_hello_tts_runs_in_a_clean_venv(tmp_path: Path) -> None:
    # Copy the sources so pip leaves no build/ or egg-info folders in the repo.
    sdk_src, example_src = tmp_path / "sdk", tmp_path / "hello_tts"
    shutil.copytree(
        SDK,
        sdk_src,
        ignore=shutil.ignore_patterns("examples", "build", "*.egg-info", "__pycache__"),
    )
    shutil.copytree(
        SDK / "examples" / "hello_tts",
        example_src,
        ignore=shutil.ignore_patterns("build", "*.egg-info", "__pycache__"),
    )
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)  # noqa: S603
    py = venv / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    subprocess.run(  # noqa: S603
        [
            str(py),
            "-m",
            "pip",
            "install",
            "-q",
            "--disable-pip-version-check",
            str(sdk_src),
            str(example_src),
        ],
        check=True,
    )
    out = subprocess.run(  # noqa: S603
        [str(py), "-I", str(example_src / "check_plugin.py")],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert out.stdout.strip() == "OK 2"
