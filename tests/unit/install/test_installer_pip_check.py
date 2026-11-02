"""The dependency check tolerates conflicts that live only in host packages (#1018).

A Linux desktop venv links the host's site-packages, so ``pip check`` also
judges packages other tools installed there. Those must not stop the install;
a broken requirement inside the venv, or anything Dodaios depends on, still
must.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("installer", REPO / "install" / "installer.py")
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)

ISSUE_1018_REPORT = (
    "opentelemetry-exporter-otlp-proto-http 1.40.0 has requirement "
    "opentelemetry-sdk~=1.40.0, but you have opentelemetry-sdk 1.45.1.\n"
    "opentelemetry-exporter-otlp-proto-grpc 1.40.0 has requirement "
    "opentelemetry-sdk~=1.40.0, but you have opentelemetry-sdk 1.45.1.\n"
)
CMD = [sys.executable, "-m", "pip", "check"]


def _pip_check_reports(monkeypatch, stdout: str, returncode: int = 1) -> None:
    def fake(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(installer, "run_captured", fake)


def test_report_lines_name_the_broken_distributions() -> None:
    report = ISSUE_1018_REPORT + (
        "WARNING: Skipping /usr/lib/python3/dist-packages/PyJWT-2.7.0.dist-info "
        "due to invalid metadata\n"
        "fastapi 0.138.2 requires starlette, which is not installed.\n"
        "pywin32 311 is not supported on this platform\n"
    )
    assert installer._pip_check_subjects(report) == [
        "opentelemetry-exporter-otlp-proto-http",
        "opentelemetry-exporter-otlp-proto-grpc",
        "fastapi",
        "pywin32",
    ]


def test_an_unknown_report_line_is_never_waved_through() -> None:
    assert installer._pip_check_subjects("Traceback (most recent call last):\n") is None


def test_a_clean_check_passes(monkeypatch) -> None:
    _pip_check_reports(monkeypatch, "No broken requirements found.\n", returncode=0)
    monkeypatch.setattr(
        installer, "_host_only_distributions", lambda _names: pytest.fail("no probe needed")
    )
    assert installer.dependency_check_passes(CMD, label="dependency consistency check")


def test_host_only_conflicts_warn_and_continue(monkeypatch, capsys) -> None:
    _pip_check_reports(monkeypatch, ISSUE_1018_REPORT)
    asked = []

    def probe(names):
        asked.append(list(names))
        return {installer._canonical_name(name): True for name in names}

    monkeypatch.setattr(installer, "_host_only_distributions", probe)
    assert installer.dependency_check_passes(CMD, label="dependency consistency check")
    assert asked == [[
        "opentelemetry-exporter-otlp-proto-http",
        "opentelemetry-exporter-otlp-proto-grpc",
    ]]
    out = capsys.readouterr().out
    assert "warning" in out
    assert "opentelemetry-exporter-otlp-proto-http" in out


def test_a_conflict_inside_the_venv_still_stops_the_install(monkeypatch, capsys) -> None:
    _pip_check_reports(monkeypatch, ISSUE_1018_REPORT)
    monkeypatch.setattr(
        installer,
        "_host_only_distributions",
        lambda names: {
            "opentelemetry-exporter-otlp-proto-http": True,
            "opentelemetry-exporter-otlp-proto-grpc": False,
        },
    )
    assert not installer.dependency_check_passes(CMD, label="dependency consistency check")
    assert "found broken requirements" in capsys.readouterr().out


def test_a_failed_probe_stops_the_install(monkeypatch) -> None:
    _pip_check_reports(monkeypatch, ISSUE_1018_REPORT)
    monkeypatch.setattr(installer, "_host_only_distributions", lambda _names: None)
    assert not installer.dependency_check_passes(CMD, label="dependency consistency check")


def test_a_failing_check_exits_the_pip_step(monkeypatch) -> None:
    monkeypatch.setattr(installer, "run_quiet", lambda *_a, **_k: 0)
    monkeypatch.setattr(installer, "installed_legacy_distributions", lambda: ())
    monkeypatch.setattr(installer, "repair_distribution_metadata", lambda **_kwargs: True)
    monkeypatch.setattr(installer, "dependency_check_passes", lambda *_a, **_k: False)
    with pytest.raises(SystemExit, match="2"):
        installer.step_pip_install(with_desktop=False, with_voice_local=False, dry_run=False)


def _dist_info(site: Path, name: str, version: str, requires: tuple[str, ...] = ()) -> None:
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
    lines += [f"Requires-Dist: {req}" for req in requires]
    (info / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_probe_tells_host_only_packages_from_dodaios_dependencies(
    monkeypatch, tmp_path
) -> None:
    """Runs the real probe in a real venv that links the host's site-packages."""
    pytest.importorskip("packaging")
    venv = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", "--system-site-packages", str(venv)],
        check=True, timeout=120,
    )
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    venv_site = Path(subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=True, capture_output=True, text=True, timeout=60,
    ).stdout.strip())
    host_site = tmp_path / "host-site-packages"
    _dist_info(venv_site, "dodaios", "0.0.0", ("host-needed>=1",))
    _dist_info(venv_site, "venv-local", "1.0")
    _dist_info(host_site, "host-needed", "1.0")
    _dist_info(host_site, "host-unrelated", "1.0")
    monkeypatch.setattr(installer, "venv_python", lambda: python)
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(host_site))

    verdict = installer._host_only_distributions(
        ["host-unrelated", "host_needed", "venv-local", "not-installed-anywhere"]
    )

    assert verdict == {
        "host-unrelated": True,  # outside the venv and unused: tolerable
        "host-needed": False,  # Dodaios depends on it: never tolerated
        "venv-local": False,  # lives inside the venv
        "not-installed-anywhere": False,
    }
