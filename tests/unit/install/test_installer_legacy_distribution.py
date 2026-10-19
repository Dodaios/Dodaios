"""The installer retires the distribution's earlier name before it installs the current one.

Both names own the same package files. pip installing ``dodaios`` and only
then uninstalling ``personal-jarvis`` would delete files ``dodaios`` needs, so
the uninstall has to come first (and only when the earlier name is there).
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("installer", REPO / "install" / "installer.py")
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)


def _site_packages(root: Path, platform: str) -> Path:
    if platform == "win32":
        return root / ".venv" / "Lib" / "site-packages"
    return root / ".venv" / "lib" / "python3.12" / "site-packages"


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
@pytest.mark.parametrize(
    "record",
    [
        "personal_jarvis-3.2.0.dist-info",
        "personal-jarvis.egg-link",
        "personal_jarvis.egg-link",
    ],
)
def test_an_install_from_before_the_rename_is_found(monkeypatch, tmp_path, platform, record):
    monkeypatch.setattr(installer.sys, "platform", platform)
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    site = _site_packages(tmp_path, platform)
    site.mkdir(parents=True)
    (site / "dodaios-3.3.0.dist-info").mkdir()
    assert installer.installed_legacy_distributions() == ()
    target = site / record
    if record.endswith(".dist-info"):
        target.mkdir()
    else:
        target.write_text(str(tmp_path), encoding="utf-8")
    assert installer.installed_legacy_distributions() == ("personal-jarvis",)


def test_no_environment_yet_means_nothing_to_retire(monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "repo_root", lambda: tmp_path)
    assert installer.installed_legacy_distributions() == ()


def _commands(monkeypatch, legacy: tuple[str, ...], *, desktop: bool) -> list[list[str]]:
    commands: list[list[str]] = []

    def capture(command, **_kwargs):
        commands.append(command)
        return 0

    monkeypatch.setattr(installer, "installed_legacy_distributions", lambda: legacy)
    monkeypatch.setattr(installer, "run_quiet", capture)
    monkeypatch.setattr(installer, "repair_distribution_metadata", lambda **_kwargs: True)
    installer.step_pip_install(with_desktop=desktop, with_voice_local=False, dry_run=False)
    return commands


@pytest.mark.parametrize("desktop", [True, False])
def test_the_earlier_name_is_uninstalled_before_anything_is_installed(monkeypatch, desktop):
    commands = _commands(monkeypatch, ("personal-jarvis",), desktop=desktop)
    pip = [str(installer.venv_python()), "-m", "pip"]
    assert commands[0] == [*pip, "uninstall", "-y", "personal-jarvis"]
    assert all("uninstall" not in command for command in commands[1:])
    assert commands[1][len(pip) :] == ["install", "-e", ".", "--no-deps"]


def test_a_current_install_runs_no_uninstall(monkeypatch):
    commands = _commands(monkeypatch, (), desktop=True)
    assert not any("uninstall" in command for command in commands)


def test_a_failed_uninstall_stops_the_install(monkeypatch):
    monkeypatch.setattr(installer, "installed_legacy_distributions", lambda: ("personal-jarvis",))
    monkeypatch.setattr(installer, "repair_distribution_metadata", lambda **_kwargs: True)
    commands: list[list[str]] = []

    def fail_uninstall(command, **_kwargs):
        commands.append(command)
        return 1 if "uninstall" in command else 0

    monkeypatch.setattr(installer, "run_quiet", fail_uninstall)
    with pytest.raises(SystemExit, match="2"):
        installer.step_pip_install(with_desktop=True, with_voice_local=False, dry_run=False)
    assert len(commands) == 1


def test_the_dry_run_names_the_retirement(monkeypatch, capsys):
    monkeypatch.setattr(installer, "installed_legacy_distributions", lambda: ("personal-jarvis",))
    installer.step_pip_install(with_desktop=True, with_voice_local=False, dry_run=True)
    # The console wraps long lines at the terminal's width (narrow on CI), so
    # compare the output with its whitespace folded.
    out = " ".join(capsys.readouterr().out.replace("│", " ").split())
    assert "retire the earlier package name (personal-jarvis)" in out
    assert out.index("uninstall -y personal-jarvis") < out.index("install -e . --no-deps")
