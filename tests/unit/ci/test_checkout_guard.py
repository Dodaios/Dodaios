"""A test run leaves the checkout as it found it.

Covers the snapshot guard (``scripts/ci/checkout_guard.py``), the session-end
check in ``tests/conftest.py``, the parallel runner's defaults and check, and
the redirect that keeps provider switches out of ``scripts/config-soll.json``.  # i18n-allow: filename
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dodaios.core import config_writer
from scripts.ci import checkout_guard, run_tests_parallel


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "core.autocrlf", "false")
    (root / "tracked.json").write_text('{"primary": "openai"}\n', encoding="utf-8")
    (root / "edited.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _bump(path: Path, text: str) -> None:
    """Rewrite ``path`` with a strictly newer mtime, as a later write would."""
    before = path.stat().st_mtime_ns
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(before + 10_000_000, before + 10_000_000))


def test_a_clean_run_changes_nothing(repo: Path) -> None:
    before = checkout_guard.snapshot(repo)
    assert before == {}
    assert checkout_guard.changes(before, checkout_guard.snapshot(repo)) == []


def test_a_rewritten_tracked_file_and_a_new_file_are_reported(repo: Path) -> None:
    before = checkout_guard.snapshot(repo)
    (repo / "tracked.json").write_text('{"primary": "openrouter"}\n', encoding="utf-8")
    (repo / "report.xml").write_text("<testsuites/>", encoding="utf-8")
    after = checkout_guard.snapshot(repo)
    assert checkout_guard.changes(before, after) == ["report.xml", "tracked.json"]


def test_a_developers_own_edits_are_not_blamed_but_a_further_rewrite_is(repo: Path) -> None:
    (repo / "edited.txt").write_text("two\n", encoding="utf-8")
    before = checkout_guard.snapshot(repo)
    assert list(before) == ["edited.txt"]
    assert checkout_guard.changes(before, checkout_guard.snapshot(repo)) == []
    _bump(repo / "edited.txt", "three\n")
    assert checkout_guard.changes(before, checkout_guard.snapshot(repo)) == ["edited.txt"]


def test_ignored_outputs_are_skipped(repo: Path) -> None:
    before = checkout_guard.snapshot(repo)
    (repo / "out").mkdir()
    (repo / "out" / "junit.xml").write_text("<testsuites/>", encoding="utf-8")
    (repo / "r.json").write_text("{}", encoding="utf-8")
    after = checkout_guard.snapshot(repo)
    assert checkout_guard.changes(before, after, ["out/", "r.json"]) == []
    assert checkout_guard.changes(before, after, ["./out/"]) == ["r.json"]


def test_tracked_only_snapshots_ignore_untracked_files(repo: Path) -> None:
    (repo / "probe.py").write_text("", encoding="utf-8")
    assert checkout_guard.snapshot(repo, untracked=False) == {}


def test_outside_a_checkout_nothing_is_judged(tmp_path: Path) -> None:
    assert checkout_guard.snapshot(tmp_path / "nowhere") is None


def test_the_cli_snapshot_then_check_round_trip(repo: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setattr(checkout_guard, "REPO_ROOT", repo)
    snap = repo.parent / "before.json"
    assert checkout_guard.main(["snapshot", "--out", str(snap)]) == 0
    assert json.loads(snap.read_text(encoding="utf-8")) == {}
    assert checkout_guard.main(["check", "--snapshot", str(snap)]) == 0
    (repo / "report.xml").write_text("<testsuites/>", encoding="utf-8")
    assert checkout_guard.main(["check", "--snapshot", str(snap)]) == 1
    assert "report.xml" in capsys.readouterr().out
    (repo / "out").mkdir()
    (repo / "out" / "x.xml").write_text("", encoding="utf-8")
    assert checkout_guard.main(["check", "--snapshot", str(snap), "--ignore", "out/"]) == 1
    (repo / "report.xml").unlink()
    assert checkout_guard.main(["check", "--snapshot", str(snap), "--ignore", "out/"]) == 0


# ------------------------------------------------------------- session guard


def test_the_session_guard_reports_a_rewritten_tracked_file(repo: Path, monkeypatch) -> None:  # noqa: ANN001
    conftest = sys.modules["tests.conftest"]
    monkeypatch.setattr(conftest, "_REPO_ROOT", repo)
    monkeypatch.setattr(conftest, "_TRACKED_BEFORE", checkout_guard.snapshot(repo, untracked=False))
    (repo / "probe.py").write_text("", encoding="utf-8")  # untracked: a sibling's probe
    assert conftest._changed_tracked_files() == []
    (repo / "tracked.json").write_text('{"primary": "openrouter"}\n', encoding="utf-8")
    assert conftest._changed_tracked_files() == ["tracked.json"]


def test_the_session_guard_skips_a_session_outside_a_checkout(monkeypatch) -> None:  # noqa: ANN001
    conftest = sys.modules["tests.conftest"]
    monkeypatch.setattr(conftest, "_TRACKED_BEFORE", None)
    assert conftest._changed_tracked_files() == []


# ------------------------------------------------------------ drift baseline redirect


def test_the_session_writes_the_drift_baseline_to_a_temp_copy() -> None:
    baseline = config_writer._config_soll_path()  # i18n-allow: real config_writer identifier
    real = config_writer.PROJECT_ROOT / "scripts" / "config-soll.json"  # i18n-allow: filename
    assert baseline.resolve() != real.resolve()
    assert baseline.resolve().is_relative_to(Path(os.environ["JARVIS_DATA_DIR"]).resolve())


def test_without_the_override_the_baseline_is_the_checkouts_file(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv(config_writer.DRIFT_BASELINE_FILE_ENV, raising=False)
    assert (
        config_writer._config_soll_path()  # i18n-allow: real config_writer identifier
        == config_writer.PROJECT_ROOT / "scripts" / "config-soll.json"  # i18n-allow: filename
    )


def test_a_brain_switch_under_test_leaves_the_tracked_baseline_alone(tmp_path: Path) -> None:
    real = config_writer.PROJECT_ROOT / "scripts" / "config-soll.json"  # i18n-allow: filename
    before = real.read_bytes() if real.exists() else None
    config = tmp_path / "jarvis.toml"
    config.write_text('[brain]\nprimary = "openai"\n', encoding="utf-8")
    config_writer.set_brain_primary("openrouter", path=config)
    assert (real.read_bytes() if real.exists() else None) == before
    baseline = config_writer._config_soll_path()  # i18n-allow: real config_writer identifier
    if baseline.exists():
        assert json.loads(baseline.read_text(encoding="utf-8"))["brain"]["primary"] == "openrouter"


def test_the_session_never_writes_the_user_environment() -> None:
    assert config_writer._set_user_env_var_winreg("JARVIS__PROBE", "x") is None
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            with pytest.raises(FileNotFoundError):
                winreg.QueryValueEx(key, "JARVIS__PROBE")


# ------------------------------------------------------------ parallel runner


def test_the_runner_writes_its_reports_outside_the_checkout_by_default(
    monkeypatch, tmp_path: Path  # noqa: ANN001
) -> None:
    seen: dict[str, Path] = {}
    monkeypatch.setattr(run_tests_parallel, "discover", lambda roots: [])
    monkeypatch.setattr(
        run_tests_parallel, "merge_junit", lambda paths, out: seen.update(junit=out)
    )
    monkeypatch.setattr(
        run_tests_parallel,
        "checkout_changes",
        lambda before, outputs: seen.update(outs=outputs) or [],
    )
    code = run_tests_parallel.main(["tests", "--durations", str(tmp_path / "none.json")])
    assert code == 0
    report, junit = seen["outs"][0], seen["outs"][1]
    assert junit == seen["junit"] and junit.name == "report.xml"
    for path in (report, junit):
        assert not path.resolve().is_relative_to(run_tests_parallel.REPO_ROOT.resolve())
    assert json.loads(report.read_text(encoding="utf-8"))["files"] == 0


def test_the_runner_fails_a_run_that_changed_the_checkout(
    monkeypatch, tmp_path: Path  # noqa: ANN001
) -> None:
    monkeypatch.setattr(run_tests_parallel, "discover", lambda roots: [])
    monkeypatch.setattr(
        run_tests_parallel, "checkout_changes", lambda before, outputs: ["report.xml"]
    )
    code = run_tests_parallel.main(
        [
            "tests",
            "--durations",
            str(tmp_path / "none.json"),
            "--report",
            str(tmp_path / "r.json"),
            "--junit-out",
            str(tmp_path / "r.xml"),
        ]
    )
    assert code == 1


def test_the_runner_does_not_blame_its_own_outputs(repo: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(checkout_guard, "REPO_ROOT", repo)
    before = checkout_guard.snapshot()
    (repo / "out").mkdir()
    outputs = [repo / "out" / "junit.xml", repo / "out" / "r.json"]
    for path in outputs:
        path.write_text("", encoding="utf-8")
    assert run_tests_parallel.checkout_changes(before, outputs) == []
    (repo / "report.xml").write_text("", encoding="utf-8")
    assert run_tests_parallel.checkout_changes(before, outputs) == ["report.xml"]
