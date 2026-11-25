"""The mypy gate judges only the packages a change touches when it has a diff base."""

from __future__ import annotations

import importlib.util
import subprocess
from collections import Counter
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "mypy_gate.py"
_SPEC = importlib.util.spec_from_file_location("mypy_gate_under_test", _PATH)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


@pytest.fixture(autouse=True)
def _packages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate, "BLOCKING", ("dodaios.core",))


def test_package_of_groups_by_first_folder() -> None:
    assert gate.package_of("dodaios/core/config.py") == "dodaios.core"
    assert gate.package_of("dodaios\core\config.py") == "dodaios.core"
    assert gate.package_of("dodaios/__main__.py") == "dodaios"
    assert gate.package_of("ui/orb/overlay.py") == "ui"


def test_count_errors_ignores_notes() -> None:
    out = "dodaios/core/a.py:3: error: x  [misc]\ndodaios/core/a.py:3: note: y\n"
    assert gate.count_errors(out) == Counter({"dodaios.core": 1})


def test_full_check_judges_everything() -> None:
    counts = Counter({"dodaios.core": 1, "dodaios.brain": 11})
    failures, _ = gate.judge(counts, {"dodaios.brain": 10})
    assert len(failures) == 2


def test_stale_baseline_outside_touched_packages_is_ignored() -> None:
    # Main moved: brain grew and core broke, but this change touches neither.
    counts = Counter({"dodaios.core": 1, "dodaios.brain": 11})
    failures, _ = gate.judge(counts, {"dodaios.brain": 10}, touched={"dodaios.voice"})
    assert failures == []


def test_touched_blocking_package_fails_on_any_error() -> None:
    failures, _ = gate.judge(Counter({"dodaios.core": 1}), {}, touched={"dodaios.core"})
    assert len(failures) == 1


def test_touched_ratcheted_package_fails_only_when_it_grew() -> None:
    baseline = {"dodaios.brain": 10}
    assert gate.judge(Counter({"dodaios.brain": 10}), baseline, touched={"dodaios.brain"})[0] == []
    assert gate.judge(Counter({"dodaios.brain": 9}), baseline, touched={"dodaios.brain"})[0] == []
    grown = gate.judge(Counter({"dodaios.brain": 11}), baseline, touched={"dodaios.brain"})[0]
    assert len(grown) == 1


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_touched_packages_reads_the_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "dodaios" / "voice").mkdir(parents=True)
    (tmp_path / "dodaios" / "voice" / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "one")
    base = _git(tmp_path, "rev-parse", "HEAD").strip()
    (tmp_path / "dodaios" / "voice" / "a.py").write_text("x = 2\n")
    (tmp_path / "README.md").write_text("hi\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "two")
    monkeypatch.setattr(gate, "REPO", tmp_path)
    assert gate.touched_packages(base) == {"dodaios.voice"}
    (tmp_path / "pyproject.toml").write_text("[tool.mypy]\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "three")
    assert gate.touched_packages(base) is None
