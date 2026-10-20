#!/usr/bin/env python3
"""Build the sdist and wheel under the distribution name and under its earlier name.

    python scripts/ci/build_distributions.py --outdir dist

The project is ``dodaios`` on PyPI now; until existing installs have moved,
every release also publishes the SAME code as ``personal-jarvis``, so
``pip install -U personal-jarvis`` keeps updating. The second build runs on a
rewritten ``pyproject.toml`` that differs only in the names: the project name,
the self-references in the extras (``personal-jarvis[full]`` must never pull
in ``dodaios``) and the ``share/<name>`` data-file directory. The original
file is restored afterwards, whatever happens.

Output: ``<outdir>/<name>/`` per distribution, one wheel and one sdist each,
so the publish job can upload them as two separate steps.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT = "dodaios"
LEGACY = "personal-jarvis"

Runner = Callable[[Sequence[str], Path], None]


def _normalized(name: str) -> str:
    """The file-name spelling of a distribution name (PEP 427 / PEP 625)."""
    return re.sub(r"[-_.]+", "_", name).lower()


def renamed_pyproject(text: str, current: str = CURRENT, legacy: str = LEGACY) -> str:
    """``pyproject.toml`` text with every spelling of the project's name replaced."""
    project = tomllib.loads(text)["project"]
    if project["name"] != current:
        raise ValueError(f"pyproject names {project['name']!r}, expected {current!r}")
    text, count = re.subn(
        rf'(?m)^name = "{re.escape(current)}"(?=\r?$)', f'name = "{legacy}"', text, count=1
    )
    if count != 1:
        raise ValueError("pyproject.toml has no top-level project name line")
    # Self-references in the extras: "dodaios[desktop,...]".
    text = text.replace(f'"{current}[', f'"{legacy}[')
    # Data files: "share/dodaios/docs" = [...].
    text = text.replace(f'"share/{current}/', f'"share/{legacy}/')
    renamed = tomllib.loads(text)
    if renamed["project"]["name"] != legacy:
        raise ValueError("the rewritten pyproject.toml does not name the earlier distribution")
    extras = renamed["project"].get("optional-dependencies", {})
    for requirement in (item for group in extras.values() for item in group):
        if re.match(rf"{re.escape(current)}\s*\[", requirement):
            raise ValueError(f"an extra still refers to {current}: {requirement}")
    data_files = renamed.get("tool", {}).get("setuptools", {}).get("data-files", {})
    for target in data_files:
        if not target.startswith(f"share/{legacy}/"):
            raise ValueError(f"a data file still installs outside share/{legacy}: {target}")
    return text


def _run(command: Sequence[str], cwd: Path) -> None:
    subprocess.run(list(command), cwd=cwd, check=True)


def _clean_build_state(root: Path) -> None:
    """Leftovers of one build must not leak into the next one's sdist or wheel.

    Only what setuptools writes: a PyInstaller freeze keeps its own folder
    under ``build/``.
    """
    stale = [root / "build" / "lib", *(root / "build").glob("bdist.*")]
    stale += [root / f"{_normalized(name)}.egg-info" for name in (CURRENT, LEGACY)]
    for path in stale:
        shutil.rmtree(path, ignore_errors=True)


def expected_artifacts(name: str, version: str) -> set[str]:
    stem = f"{_normalized(name)}-{version}"
    return {f"{stem}.tar.gz", f"{stem}-py3-none-any.whl"}


def build_all(
    outdir: Path,
    *,
    root: Path = ROOT,
    build_command: Sequence[str] = (sys.executable, "-m", "build", "--no-isolation"),
    runner: Runner = _run,
) -> dict[str, Path]:
    """Build both distributions; return ``{name: its output directory}``."""
    pyproject = root / "pyproject.toml"
    original = pyproject.read_bytes()
    text = original.decode("utf-8")
    version = tomllib.loads(text)["project"]["version"]
    legacy_text = renamed_pyproject(text)
    outputs = {CURRENT: outdir / CURRENT, LEGACY: outdir / LEGACY}
    for directory in outputs.values():
        if directory.exists() and any(directory.iterdir()):
            raise ValueError(f"output directory is not empty: {directory}")
    try:
        _clean_build_state(root)
        runner([*build_command, "--outdir", str(outputs[CURRENT])], root)
        _clean_build_state(root)
        pyproject.write_bytes(legacy_text.encode("utf-8"))
        runner([*build_command, "--outdir", str(outputs[LEGACY])], root)
    finally:
        pyproject.write_bytes(original)
        _clean_build_state(root)
    for name, directory in outputs.items():
        found = {path.name for path in directory.iterdir()} if directory.is_dir() else set()
        expected = expected_artifacts(name, version)
        if found != expected:
            raise ValueError(
                f"{name}: built {sorted(found)}, expected {sorted(expected)}"
            )
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        outputs = build_all(args.outdir.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"::error::building the distributions failed: {exc}")
        return 1
    for name, directory in outputs.items():
        print(f"[build] {name}: {', '.join(sorted(p.name for p in directory.iterdir()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
