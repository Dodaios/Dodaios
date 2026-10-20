"""The release builds the same code as ``dodaios`` and as ``personal-jarvis``."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import yaml

from dodaios.core import branding
from scripts.ci import build_distributions as bd

ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_the_names_are_the_distribution_names_branding_declares() -> None:
    assert bd.CURRENT == branding.DISTRIBUTION_NAME
    assert (bd.LEGACY,) == branding.LEGACY_DISTRIBUTION_NAMES


def test_the_real_pyproject_renames_to_the_earlier_distribution() -> None:
    project = tomllib.loads(bd.renamed_pyproject(PYPROJECT))
    assert project["project"]["name"] == "personal-jarvis"
    extras = project["project"]["optional-dependencies"]
    # The earlier name's [full] must never pull in the current distribution:
    # two distributions owning the same files is what the transition avoids.
    assert extras["full"] == [
        "personal-jarvis[desktop,desktop-macos,telephony,channels,local-voice]"
    ]
    assert extras["dev"][0] == "personal-jarvis[desktop,local-voice]"
    assert all(
        not item.startswith("dodaios[") for group in extras.values() for item in group
    )
    data_files = project["tool"]["setuptools"]["data-files"]
    assert set(data_files) == {"share/personal-jarvis/docs", "share/personal-jarvis/docs/legal"}


def test_only_the_names_change() -> None:
    original = tomllib.loads(PYPROJECT)
    renamed = tomllib.loads(bd.renamed_pyproject(PYPROJECT))
    for key in ("version", "dependencies", "scripts", "entry-points", "requires-python"):
        assert renamed["project"][key] == original["project"][key], key
    for key in ("package-data", "exclude-package-data"):
        assert renamed["tool"]["setuptools"][key] == original["tool"]["setuptools"][key], key
    # The package list lives in setup.py, which both builds share unchanged.
    assert "packages" not in renamed["tool"]["setuptools"]
    assert renamed["build-system"] == original["build-system"]


def test_a_pyproject_under_another_name_is_refused() -> None:
    with pytest.raises(ValueError, match="expected"):
        bd.renamed_pyproject('[project]\nname = "something-else"\nversion = "1.0.0"\n')


def _project(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "dodaios"\n'
        'version = "1.2.3"\n'
        "[project.optional-dependencies]\n"
        'full = ["dodaios[desktop]"]\n'
        "[tool.setuptools.data-files]\n"
        '"share/dodaios/docs" = ["docs/*.md"]\n',
        encoding="utf-8",
    )
    return tmp_path


def _fake_build(seen: list[tuple[str, str]]):
    def runner(command, cwd: Path) -> None:
        outdir = Path(command[command.index("--outdir") + 1])
        name = tomllib.loads((cwd / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "name"
        ]
        seen.append((name, outdir.name))
        outdir.mkdir(parents=True)
        for artifact in bd.expected_artifacts(name, "1.2.3"):
            (outdir / artifact).write_bytes(b"artifact")
        # What setuptools leaves behind in the tree.
        (cwd / f"{bd._normalized(name)}.egg-info").mkdir()
        (cwd / "build" / "lib").mkdir(parents=True, exist_ok=True)

    return runner


def test_build_all_builds_both_names_and_restores_the_pyproject(tmp_path: Path) -> None:
    root = _project(tmp_path / "tree")
    original = (root / "pyproject.toml").read_bytes()
    (root / "build" / "Jarvis").mkdir(parents=True)  # a PyInstaller freeze
    seen: list[tuple[str, str]] = []

    outputs = bd.build_all(tmp_path / "dist", root=root, runner=_fake_build(seen))

    assert seen == [("dodaios", "dodaios"), ("personal-jarvis", "personal-jarvis")]
    assert sorted(p.name for p in outputs["personal-jarvis"].iterdir()) == [
        "personal_jarvis-1.2.3-py3-none-any.whl",
        "personal_jarvis-1.2.3.tar.gz",
    ]
    assert (root / "pyproject.toml").read_bytes() == original
    assert not list(root.glob("*.egg-info"))
    assert not (root / "build" / "lib").exists()
    assert (root / "build" / "Jarvis").is_dir()


def test_a_failed_second_build_still_restores_the_pyproject(tmp_path: Path) -> None:
    root = _project(tmp_path / "tree")
    original = (root / "pyproject.toml").read_bytes()
    seen: list[tuple[str, str]] = []
    build = _fake_build(seen)

    def runner(command, cwd: Path) -> None:
        if seen:
            raise OSError("second build failed")
        build(command, cwd)

    with pytest.raises(OSError, match="second build"):
        bd.build_all(tmp_path / "dist", root=root, runner=runner)
    assert (root / "pyproject.toml").read_bytes() == original


def test_a_missing_artifact_fails_the_build(tmp_path: Path) -> None:
    root = _project(tmp_path / "tree")

    def runner(command, cwd: Path) -> None:
        Path(command[command.index("--outdir") + 1]).mkdir(parents=True)

    with pytest.raises(ValueError, match="expected"):
        bd.build_all(tmp_path / "dist", root=root, runner=runner)


def _release() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))


def test_the_release_builds_both_names_and_publishes_each() -> None:
    jobs = _release()["jobs"]
    build_runs = "\n".join(step.get("run", "") for step in jobs["build"]["steps"])
    assert "scripts/ci/build_distributions.py --outdir dist" in build_runs
    assert "python -m build " not in build_runs
    # PyPI scopes an upload token to the one trusted publisher that matched,
    # so each project publishes from its own job and environment.
    uploads = {
        job_id: (
            jobs[job_id]["environment"],
            [
                step["with"]["packages-dir"]
                for step in jobs[job_id]["steps"]
                if "gh-action-pypi-publish@" in step.get("uses", "")
            ],
        )
        for job_id in ("publish", "publish-legacy")
    }
    assert uploads == {
        "publish": ("pypi", ["dist/dodaios/"]),
        "publish-legacy": ("pypi-legacy", ["dist/personal-jarvis/"]),
    }
    for job_id in uploads:
        assert jobs[job_id]["permissions"] == {"id-token": "write"}
