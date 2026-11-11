"""The system folder window: offered where it works, silent where it does not.

Two things must hold on every machine, and the second one is the reason this
feature is allowed to exist at all:

* Where a desktop is present, the window opens and the chosen folder comes back
  intact — including folders whose names carry accents, which is where the
  first version broke.
* Where one is not (a headless VPS, an SSH session, a container), the feature
  reports itself unavailable in plain language and the REST browser stays the
  whole story. It never raises, never blocks, and never offers a button that
  cannot deliver.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dodaios.agentic_ide import native_picker


class _Completed:
    """Stand-in for a finished helper process."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _marked(path: str) -> str:
    return f"noise before\n{native_picker._BEGIN}\n{path}\n{native_picker._END}\ntrailing\n"


# --------------------------------------------------------------------------- #
# Availability                                                                #
# --------------------------------------------------------------------------- #
def test_a_headless_linux_box_says_so_in_plain_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    probe = native_picker.support()

    assert probe.available is False
    assert probe.backend is None
    assert probe.reason and "desktop session" in probe.reason


def test_a_linux_desktop_without_a_dialog_program_names_the_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(native_picker.shutil, "which", lambda _name: None)

    probe = native_picker.support()

    assert probe.available is False
    # A dead end is not an answer: the message says what to install.
    assert probe.reason and "zenity" in probe.reason


def test_a_linux_desktop_with_zenity_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(
        native_picker.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None
    )

    assert native_picker.support() == native_picker.PickerSupport(available=True, backend="zenity")


def test_choosing_on_a_headless_box_fails_without_running_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no helper process may be started without a display")

    monkeypatch.setattr(native_picker.subprocess, "run", _explode)

    result = native_picker.choose_folder()

    assert result.path is None
    assert result.error


# --------------------------------------------------------------------------- #
# The answer                                                                  #
# --------------------------------------------------------------------------- #
def test_the_chosen_folder_comes_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "zenity")
    )
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        native_picker.subprocess, "run", lambda *_a, **_k: _Completed(stdout=str(tmp_path))
    )

    assert native_picker.choose_folder().path == str(tmp_path)


def test_a_folder_name_with_accents_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first version decoded the helper's output with the console codepage
    and took its own reader thread down on the first accented character. Most of
    the world names folders in something other than plain ASCII, so this is an
    ordinary folder, not an edge case.

    Written as escapes so the assertion is about ENCODING rather than about any
    one language, and so this file stays plain ASCII on disk.
    """
    folder = tmp_path / "\u00c5ngstr\u00f6m caf\u00e9 \u00f1o\u00f1o"
    folder.mkdir()
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "powershell")
    )
    monkeypatch.setattr(sys, "platform", "win32")

    seen: dict[str, object] = {}

    def _run(*_args: object, **kwargs: object) -> _Completed:
        seen.update(kwargs)
        return _Completed(stdout=_marked(str(folder)))

    monkeypatch.setattr(native_picker.subprocess, "run", _run)

    assert native_picker.choose_folder().path == str(folder)
    # The decoding is pinned, not inherited from whatever locale the app booted in.
    assert seen["encoding"] == "utf-8"


def test_the_helpers_own_chatter_is_not_mistaken_for_an_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "powershell")
    )
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        native_picker.subprocess,
        "run",
        lambda *_a, **_k: _Completed(stdout=f"Gtk-WARNING: something\n{_marked(str(tmp_path))}"),
    )

    assert native_picker.choose_folder().path == str(tmp_path)


def test_cancelling_is_an_outcome_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "zenity")
    )
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(native_picker.subprocess, "run", lambda *_a, **_k: _Completed(returncode=1))

    result = native_picker.choose_folder()

    assert result.cancelled is True
    assert result.error is None
    assert result.path is None


def test_a_window_left_open_is_closed_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dialog nobody answers must be recoverable, not merely bounded — which
    is the whole reason it runs as a separate process (AP-24)."""
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "zenity")
    )
    monkeypatch.setattr(sys, "platform", "linux")

    def _timeout(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="zenity", timeout=1)

    monkeypatch.setattr(native_picker.subprocess, "run", _timeout)

    result = native_picker.choose_folder(timeout=1)

    assert result.path is None
    assert result.error and "too long" in result.error


def test_a_folder_deleted_while_the_window_was_open_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "zenity")
    )
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        native_picker.subprocess,
        "run",
        lambda *_a, **_k: _Completed(stdout=str(tmp_path / "gone")),
    )

    result = native_picker.choose_folder()

    assert result.path is None
    assert result.error and "not a folder" in result.error


def test_a_missing_helper_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "zenity")
    )
    monkeypatch.setattr(sys, "platform", "linux")

    def _missing(*_a: object, **_k: object) -> None:
        raise OSError("zenity vanished")

    monkeypatch.setattr(native_picker.subprocess, "run", _missing)

    assert native_picker.choose_folder().error


# --------------------------------------------------------------------------- #
# The command                                                                 #
# --------------------------------------------------------------------------- #
def test_the_start_folder_is_dropped_when_it_no_longer_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale start folder must not stop the window from opening."""
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "kdialog")
    )
    monkeypatch.setattr(sys, "platform", "linux")
    seen: list[list[str]] = []

    def _run(argv: list[str], **_k: object) -> _Completed:
        seen.append(argv)
        return _Completed(stdout=str(tmp_path))

    monkeypatch.setattr(native_picker.subprocess, "run", _run)
    native_picker.choose_folder(start=str(tmp_path / "deleted-yesterday"))

    assert seen and str(tmp_path / "deleted-yesterday") not in seen[0]


def test_the_windows_command_runs_in_a_single_threaded_apartment() -> None:
    """`-STA` is not optional: the shell dialogs refuse to run without it."""
    if sys.platform != "win32":
        pytest.skip("the Windows command is only built on Windows")
    argv, _env = native_picker._command(None, "powershell")
    assert "-STA" in argv
    assert "-NoProfile" in argv


def test_the_windows_owner_window_is_never_fully_transparent() -> None:
    """Regression guard for the "Browse does nothing" report.

    The dialog is made visible above a maximised app window by a topmost owner.
    Windows drops the topmost flag from a layered window whose opacity is 0, so
    an ``Opacity = 0`` owner is not topmost, the dialog it owns opens BEHIND the
    app, and the button looks dead. The owner must therefore be faint, never
    invisible — and topmost.
    """
    script = native_picker._fill(native_picker._WINDOWS_SCRIPT)
    assert "$owner.Opacity = 0\n" not in script
    assert "$owner.Opacity = 0.01" in script
    assert "$owner.TopMost = $true" in script
    # The dialog centres itself over its owner: park the owner where the person
    # is looking, i.e. on the screen the mouse is on.
    assert "Screen]::FromPoint($mouse).WorkingArea" in script


def test_handing_over_the_foreground_right_is_a_no_op_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    native_picker._let_the_dialog_take_the_foreground()  # must not raise


# --------------------------------------------------------------------------- #
# Windows: the fast route                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def fast_route(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The Python helper route with a pretend interpreter and owner window.

    Returns the list of owner windows that were handed back to the app.
    """
    released: list[int] = []
    monkeypatch.setattr(
        native_picker, "support", lambda: native_picker.PickerSupport(True, "powershell")
    )
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(native_picker, "_helper_python", lambda: "python.exe")
    monkeypatch.setattr(native_picker, "_foreground_window", lambda: 4242)
    monkeypatch.setattr(native_picker, "_release_owner", released.append)
    monkeypatch.setattr(native_picker, "_let_the_dialog_take_the_foreground", lambda: None)
    return released


def test_the_helper_is_given_the_window_the_click_came_from(
    tmp_path: Path, fast_route: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The folder window is owned by the app window, so it opens in front of
    the app and nothing else; the always-on-top form is not needed."""
    seen: list[list[str]] = []

    def _run(argv: list[str], **_k: object) -> _Completed:
        seen.append(argv)
        return _Completed(stdout=_marked(str(tmp_path)))

    monkeypatch.setattr(native_picker.subprocess, "run", _run)

    assert native_picker.choose_folder(start=str(tmp_path)).path == str(tmp_path)
    assert len(seen) == 1
    argv = seen[0]
    assert argv[0] == "python.exe"
    assert argv[-3].endswith("folder_dialog_win.py")
    assert argv[-2:] == ["4242", str(tmp_path)]
    # No PowerShell, and so no C# compile on the way to the window.
    assert "powershell" not in argv
    assert fast_route == [4242]


def test_closing_the_fast_window_is_a_cancel(
    fast_route: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def _run(argv: list[str], **_k: object) -> _Completed:
        calls.append(argv)
        return _Completed(returncode=1)

    monkeypatch.setattr(native_picker.subprocess, "run", _run)

    result = native_picker.choose_folder()

    assert result.cancelled is True
    # A cancel is an answer: PowerShell must not open a second window after it.
    assert len(calls) == 1


def test_a_failed_helper_falls_back_to_powershell(
    tmp_path: Path, fast_route: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def _run(argv: list[str], **_k: object) -> _Completed:
        calls.append(argv)
        if len(calls) == 1:
            return _Completed(stderr="OSError: COM call failed", returncode=3)
        return _Completed(stdout=_marked(str(tmp_path)))

    monkeypatch.setattr(native_picker.subprocess, "run", _run)

    assert native_picker.choose_folder().path == str(tmp_path)
    assert calls[1][0] == "powershell"
    assert "-STA" in calls[1]


def test_the_app_window_is_handed_back_even_when_the_helper_is_killed(
    fast_route: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A modal window disables its owner and enables it again when it closes.
    A helper that timed out never reaches the second half, and the app would
    stay dead to every click."""

    def _timeout(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="python.exe", timeout=1)

    monkeypatch.setattr(native_picker.subprocess, "run", _timeout)

    result = native_picker.choose_folder(timeout=1)

    assert result.error and "too long" in result.error
    assert fast_route == [4242]


def test_without_a_window_to_own_it_the_fast_route_is_not_taken(
    tmp_path: Path, fast_route: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(native_picker, "_foreground_window", lambda: 0)
    calls: list[list[str]] = []

    def _run(argv: list[str], **_k: object) -> _Completed:
        calls.append(argv)
        return _Completed(stdout=_marked(str(tmp_path)))

    monkeypatch.setattr(native_picker.subprocess, "run", _run)

    assert native_picker.choose_folder().path == str(tmp_path)
    assert [argv[0] for argv in calls] == ["powershell"]
    assert fast_route == []


def test_the_branded_launcher_is_not_used_as_the_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the desktop app ``sys.executable`` is a renamed copy of pythonw that
    finds its standard library through the registry and cannot start with -I.
    The interpreter beside the standard library on ``sys.path`` is used."""
    install = tmp_path / "Python311"
    (install / "Lib").mkdir(parents=True)
    (install / "python.exe").write_bytes(b"")
    branded = tmp_path / "bin" / "DodaiosApp.exe"
    branded.parent.mkdir()
    branded.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(branded))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "nowhere"))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "nowhere"))
    monkeypatch.setattr(sys, "path", [str(install / "Lib"), str(install / "DLLs")])

    assert native_picker._helper_python() == str(install / "python.exe")


def test_the_dialog_helper_needs_only_the_standard_library() -> None:
    """It runs with -I and -S in a bare interpreter: an import from the app, or
    from any installed package, would fail there and send every click down the
    slow route."""
    import ast

    helper = Path(native_picker.__file__).with_name("folder_dialog_win.py")
    tree = ast.parse(helper.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])

    assert imported <= {"__future__", "ctypes", "sys", "threading", "time"}
