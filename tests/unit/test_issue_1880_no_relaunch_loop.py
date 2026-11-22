"""A detached desktop start never detaches again (#1880).

On the Windows installer build a bare ``DodaiosApp.exe`` started about every
two seconds after the app was quit with "Keep agents running" on. Each copy's
parent was the previous one, each exited at once and wrote no log.

The chain: the background service's tray "Open" (and every restart) starts the
frozen executable bare, detached, with its standard streams on the NUL device.
Windows answers ``isatty()`` with True for NUL, so the bare start took itself
for ``dodaios`` typed into a terminal, started one more detached copy "in the
background" and returned, and that copy did the same.

Everything here injects the platform, so the Windows shape is checked on
whichever OS runs the suite.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

import dodaios.__main__ as main_mod
import dodaios.ui.relauncher as relauncher
from dodaios.ui.relauncher import DESKTOP_SPAWN_ENV_VAR, mark_desktop_spawn


class _NulStream:
    """How a stream on Windows' NUL device looks to Python: a character device."""

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 0


def test_the_marker_names_the_same_variable_in_both_modules() -> None:
    assert main_mod._DESKTOP_SPAWN_ENV_VAR == DESKTOP_SPAWN_ENV_VAR


def test_nul_is_no_terminal_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_windows_console", lambda stream: False)
    assert main_mod._is_terminal(_NulStream(), "win32") is False


def test_a_real_console_is_a_terminal_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_windows_console", lambda stream: True)
    assert main_mod._is_terminal(_NulStream(), "win32") is True


def test_elsewhere_isatty_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_console_api(stream: object) -> bool:
        raise AssertionError("the console API is Windows only")

    monkeypatch.setattr(main_mod, "_windows_console", no_console_api)
    assert main_mod._is_terminal(_NulStream(), "darwin") is True
    assert main_mod._is_terminal(None, "darwin") is False


def test_the_console_probe_fails_closed_off_windows() -> None:
    # No msvcrt / windll here: never a console, never an exception.
    if sys.platform == "win32":
        pytest.skip("checks the probe's fallback where the console API is missing")
    assert main_mod._windows_console(_NulStream()) is False


def test_a_start_with_nul_streams_does_not_detach_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_mod, "_windows_console", lambda stream: False)
    monkeypatch.setattr(sys, "stdin", _NulStream())
    monkeypatch.setattr(sys, "stdout", _NulStream())
    assert main_mod._should_detach_from_terminal(platform_name="win32", environ={}) is False


def _boot_recorder(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    import dodaios.ui.web.launcher as launcher_mod

    booted: list[list[str]] = []

    def never_detach() -> object:
        raise AssertionError("a detached start must boot, not start another copy")

    monkeypatch.setattr(main_mod, "_missing_desktop_dependency", lambda: None)
    monkeypatch.setattr(launcher_mod, "main", lambda argv: booted.append(argv) or 0)
    monkeypatch.setattr(relauncher, "launch_desktop_detached", never_detach)
    return booted


def test_a_spawned_desktop_boots_even_where_its_streams_look_like_a_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    booted = _boot_recorder(monkeypatch)
    monkeypatch.setattr(main_mod, "_should_detach_from_terminal", lambda: True)
    monkeypatch.setenv(DESKTOP_SPAWN_ENV_VAR, "1")

    assert main_mod._run_desktop(debug=False) == 0
    assert booted == [[]]
    import os

    # The app's own terminals must not inherit it.
    assert DESKTOP_SPAWN_ENV_VAR not in os.environ


def _frozen_windows(monkeypatch: pytest.MonkeyPatch, exe: str) -> None:
    import dodaios.core.frozen as frozen_mod

    monkeypatch.setattr(frozen_mod, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", exe)


def test_the_tray_open_starts_a_desktop_that_boots_instead_of_looping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole chain of the report: tray "Open" -> bare exe on NUL -> boots."""
    from dodaios.ui import background_tray

    exe = r"C:\Users\someone\AppData\Local\Programs\Dodaios\DodaiosApp.exe"
    spawned: list[dict] = []

    def fake_popen(argv: list[str], **kwargs: object) -> object:
        spawned.append({"argv": argv, **kwargs})
        return SimpleNamespace(pid=4321)

    monkeypatch.setattr(relauncher, "fresh_user_env", lambda *a, **k: {"PATH": r"C:\Windows"})
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    _frozen_windows(monkeypatch, exe)
    assert background_tray.open_desktop_app() is True

    (child,) = spawned
    # What the reporter saw: the bare executable, no arguments, NUL streams.
    assert child["argv"] == [exe]
    assert child["stdin"] is subprocess.DEVNULL
    assert child["env"][DESKTOP_SPAWN_ENV_VAR] == "1"

    # That child, on Windows, with NUL streams: it boots the desktop.
    booted = _boot_recorder(monkeypatch)
    monkeypatch.setattr(main_mod, "_windows_console", lambda stream: False)
    monkeypatch.setattr(sys, "stdin", _NulStream())
    monkeypatch.setattr(sys, "stdout", _NulStream())
    for name, value in child["env"].items():
        monkeypatch.setenv(name, value)
    assert main_mod._run_desktop(debug=False) == 0
    assert booted == [[]]


def test_even_without_the_marker_nul_streams_boot_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A start by an older release carries no marker; the console check holds."""
    booted = _boot_recorder(monkeypatch)
    monkeypatch.delenv(DESKTOP_SPAWN_ENV_VAR, raising=False)
    monkeypatch.setattr(main_mod, "_windows_console", lambda stream: False)
    monkeypatch.setattr(sys, "stdin", _NulStream())
    monkeypatch.setattr(sys, "stdout", _NulStream())
    monkeypatch.setattr(sys, "platform", "win32")
    assert main_mod._run_desktop(debug=False) == 0
    assert booted == [[]]


def test_a_restart_marks_the_desktop_it_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(relauncher, "fresh_user_env", lambda *a, **k: {"PATH": "/bin"})
    spawned: list[dict] = []

    def fake_spawn(cmd: list[str], **kwargs: object) -> object:
        spawned.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(pid=999)

    rc = relauncher.main(
        ["4242", "repo"],
        _wait=lambda pid, **_kw: True,
        _spawn=fake_spawn,
        _sleep=lambda _s: None,
        _alive=lambda _p: True,
        _finalize_update=lambda _cwd: True,
        _serving=lambda: False,
    )
    assert rc == 0
    assert spawned[0]["env"][DESKTOP_SPAWN_ENV_VAR] == "1"


def test_a_terminal_launch_marks_the_desktop_it_starts() -> None:
    captured: dict[str, object] = {}

    def fake_popen(argv: list[str], **kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    relauncher.launch_desktop_detached(_popen=fake_popen)
    env = captured["env"]
    assert isinstance(env, dict)
    assert env[DESKTOP_SPAWN_ENV_VAR] == "1"


def test_mark_desktop_spawn_keeps_the_rest_and_copies() -> None:
    base = {"PATH": "/bin"}
    marked = mark_desktop_spawn(base)
    assert marked == {"PATH": "/bin", DESKTOP_SPAWN_ENV_VAR: "1"}
    assert base == {"PATH": "/bin"}


@pytest.mark.skipif(sys.platform != "win32", reason="NUL and the console API are Windows only")
def test_a_real_detached_child_on_nul_is_no_terminal(tmp_path) -> None:
    """The quirk itself, on a real Windows: a child started the way the tray
    and the relauncher start the desktop (detached, streams on NUL) sees
    ``isatty()`` True, and the console check says it is no terminal."""
    import json

    from dodaios.ui.relauncher import detached_popen_kwargs

    out = tmp_path / "seen.json"
    probe = (
        "import json, sys\n"
        "from dodaios.__main__ import _is_terminal\n"
        f"open({str(out)!r}, 'w').write(json.dumps({{\n"
        "    'isatty': bool(sys.stdin.isatty()),\n"
        "    'terminal': _is_terminal(sys.stdin, sys.platform),\n"
        "}))\n"
    )
    kwargs = detached_popen_kwargs()
    child = subprocess.Popen([sys.executable, "-c", probe], **kwargs)  # type: ignore[call-overload]  # noqa: S603
    assert child.wait(timeout=120) == 0
    seen = json.loads(out.read_text())
    assert seen["isatty"] is True, seen  # what made every copy start the next one
    assert seen["terminal"] is False, seen
