"""The installer's terminal presentation (Stage 2) degrades cleanly.

``dodaios.setup.install_ui`` decides what a terminal can show (colour, glyphs,
motion, width) and draws the phases, steps, failures and the finale card.
These tests drive it the way the installer meets real terminals: a pipe or CI
log (no TTY), ``NO_COLOR``, a terminal without Unicode, and a narrow window.
"""

from __future__ import annotations

import importlib.util
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS
from dodaios.setup import install_ui
from dodaios.setup.install_ui import Caps, InstallUI, detect, format_duration, strip_ansi

ESC = "\x1b"
REPO = Path(__file__).resolve().parents[3]


class FakeTty(io.StringIO):
    """A stream that says it is a terminal (and has no real descriptor)."""

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        raise OSError("no descriptor behind a test stream")


def _draw_everything(ui: InstallUI) -> None:
    """Every piece the installer draws, with the typography its messages use."""
    ui.context("Linux 6.8 (x86_64) · Python 3.12.3 · /srv/install")
    ui.phase(4, "Dependencies")
    ui.ok("Editable install (entry points)", 1.9)
    ui.ok("Runtime dependencies (hash-pinned lockfile)", 48.2)
    ui.skip("Node.js not found — the worker can be added in the app")
    ui.warn("A warning only: packages outside the environment are broken…")
    ui.note("Everything the voice pipeline needs is fetched now → first launch is fast")
    with ui.spinner("Downloading voice models (the long step)"):
        pass
    ui.fail(
        "Runtime dependencies (hash-pinned lockfile)",
        ["ERROR: Could not install packages due to an OSError."],
        ["Check your connection and free disk space.", "Run the installer again."],
        "https://example.invalid/help#troubleshooting",
    )
    ui.stopped("The install stopped here. Nothing was launched.")
    ui.card(
        "Dodaios is ready",
        [
            ("Open", 'Windows search → "Dodaios"'),
            ("", "or type dodaios in a new terminal"),
            ("Update", "dodaios update, or run the install command again"),
            ("Folder", "/srv/install"),
            ("Next", "The app opens with a one-time setup guide."),
        ],
        "installed in 3m 27s",
    )
    ui.launch("the desktop app", "/srv/install/run.sh")


def _render(caps: Caps) -> str:
    out = io.StringIO()
    _draw_everything(InstallUI(caps, out))
    return out.getvalue()


# ----------------------------------------------------------------- detection
def test_a_pipe_gets_no_colour_and_no_motion() -> None:
    caps = detect({"TERM": "xterm-256color", "LANG": "C.UTF-8"}, io.StringIO(), "linux")
    assert caps.color == "none"
    assert caps.motion is False


def test_no_color_wins_on_a_terminal_and_over_force_color() -> None:
    env = {"TERM": "xterm-256color", "LANG": "C.UTF-8", "NO_COLOR": "1", "FORCE_COLOR": "1"}
    assert detect(env, FakeTty(), "linux").color == "none"


def test_force_color_paints_a_log_but_never_animates_it() -> None:
    env = {"FORCE_COLOR": "1", "COLORTERM": "truecolor", "LANG": "C.UTF-8"}
    caps = detect(env, io.StringIO(), "linux")
    assert caps.color == "truecolor"
    assert caps.motion is False


def test_a_dumb_terminal_gets_plain_text() -> None:
    caps = detect({"TERM": "dumb", "LANG": "C.UTF-8"}, FakeTty(), "linux")
    assert caps.color == "none"
    assert caps.motion is False
    assert caps.glyphs == "ascii"


def test_ci_never_animates_even_on_a_terminal() -> None:
    caps = detect({"TERM": "xterm-256color", "LANG": "C.UTF-8", "CI": "true"}, FakeTty(), "linux")
    assert caps.motion is False
    assert caps.color == "256"


def test_a_terminal_animates_and_picks_its_colour_tier() -> None:
    tty = FakeTty()
    assert detect({"TERM": "xterm-256color", "LANG": "C.UTF-8"}, tty, "linux").motion is True
    assert detect({"TERM": "xterm-256color", "COLORTERM": "truecolor"}, tty, "linux").color == (
        "truecolor"
    )
    assert detect({"TERM": "xterm", "LANG": "C.UTF-8"}, tty, "linux").color == "16"
    # Windows Terminal forwards WT_SESSION into WSL, which never sets COLORTERM.
    assert detect({"TERM": "xterm-256color", "WT_SESSION": "x"}, tty, "linux").color == (
        "truecolor"
    )


@pytest.mark.parametrize(
    ("env", "platform", "glyphs"),
    [
        ({"LANG": "en_US.UTF-8"}, "linux", "full"),
        ({"LC_ALL": "C"}, "linux", "ascii"),
        ({"LANG": "de_DE.ISO-8859-1"}, "darwin", "ascii"),
        ({"LANG": "C.UTF-8", "TERM": "linux"}, "linux", "ascii"),
        ({"LANG": "C.UTF-8", "TERM": "vt100"}, "linux", "ascii"),
        ({}, "linux", "ascii"),
        ({"TERM_PROGRAM": "Apple_Terminal"}, "darwin", "full"),
        ({"LANG": "C.UTF-8", "JARVIS_INSTALL_ASCII": "1"}, "linux", "ascii"),
        ({"LANG": "C.UTF-8", "JARVIS_INSTALL_ASCII": "0"}, "linux", "full"),
        ({}, "win32", "basic"),
        ({"WT_SESSION": "x"}, "win32", "full"),
        ({"WT_SESSION": "x", "JARVIS_INSTALL_ASCII": "1"}, "win32", "ascii"),
    ],
)
def test_the_glyph_set_follows_the_terminal(
    env: dict[str, str], platform: str, glyphs: str
) -> None:
    assert detect(env, io.StringIO(), platform).glyphs == glyphs


def test_columns_sets_the_width() -> None:
    assert detect({"COLUMNS": "40"}, io.StringIO(), "linux").width == 40
    assert detect({"COLUMNS": "7"}, io.StringIO(), "linux").width == 20
    assert detect({"COLUMNS": "wide"}, io.StringIO(), "linux").width >= 20


# ----------------------------------------------------------------- fallbacks
def test_no_colour_output_carries_no_escape_sequence() -> None:
    text = _render(Caps("none", "full", False, 100))
    assert ESC not in text
    assert "[4/6] Dependencies" in text
    assert "[STOPPED]" in text and "[✓ READY]" in text


def test_no_unicode_output_is_plain_ascii() -> None:
    for color in ("none", "256", "truecolor"):
        text = strip_ansi(_render(Caps(color, "ascii", False, 100)))
        assert text.isascii(), sorted({c for c in text if not c.isascii()})
        assert "->" in text and "..." in text


def test_a_classic_windows_console_gets_only_glyphs_its_font_draws() -> None:
    text = strip_ansi(_render(Caps("truecolor", "basic", False, 100)))
    for missing_from_consolas in ("✓", "⠋", "◆", "✗"):
        assert missing_from_consolas not in text
    assert "√" in text


@pytest.mark.parametrize("glyphs", ["full", "ascii"])
@pytest.mark.parametrize("color", ["none", "truecolor"])
def test_a_narrow_window_gets_no_broken_frame(color: str, glyphs: str) -> None:
    text = strip_ansi(_render(Caps(color, glyphs, False, 40)))
    # Too narrow for the framed card: the same rows, unframed.
    assert "┌" not in text and "+--" not in text
    assert "Dodaios is ready" in text
    assert "Windows search" in text


def test_the_card_frames_itself_where_it_fits() -> None:
    text = strip_ansi(_render(Caps("truecolor", "full", False, 100)))
    framed = [line for line in text.splitlines() if line.startswith("  │")]
    assert framed, text
    assert len({len(line) for line in framed}) == 1, "the right edge is ragged"


def test_times_sit_on_the_right_edge_without_overflowing() -> None:
    out = io.StringIO()
    ui = InstallUI(Caps("none", "full", False, 70), out)
    ui.ok("Runtime dependencies (hash-pinned lockfile)", 48.2)
    line = out.getvalue().rstrip("\n")
    assert line.endswith("48s")
    assert len(line) <= 70 - 2


def test_the_live_line_never_wraps_in_a_narrow_window() -> None:
    out = FakeTty()
    ui = InstallUI(Caps("truecolor", "full", True, 30), out)
    with ui.spinner("Downloading voice models (the long step, a few hundred MB)"):
        ui.note("downloading wake model")
    frames = [strip_ansi(chunk) for chunk in out.getvalue().split("\r") if chunk.strip()]
    live = [frame.replace("\x1b[K", "") for frame in frames if "⠋" in frame or "⠙" in frame]
    assert live, out.getvalue()
    assert all(len(frame.rstrip("\n")) < 30 for frame in live)
    # The cursor comes back after the spinner hid it.
    assert out.getvalue().endswith("\x1b[?25h")


def test_without_motion_a_wait_is_one_honest_line() -> None:
    out = io.StringIO()
    ui = InstallUI(Caps("none", "ascii", False, 80), out)
    with ui.spinner("Checking the voice models"):
        pass
    assert out.getvalue() == "     -  Checking the voice models...\n"


def test_durations_read_like_a_person_would_say_them() -> None:
    assert format_duration(None) == ""
    assert format_duration(0.4) == ""
    assert format_duration(12.9) == "12s"
    assert format_duration(91) == "1m 31s"
    assert format_duration(3725) == "1h 02m"


# ----------------------------------------------------------------- Stage 2
def _installer():
    spec = importlib.util.spec_from_file_location(
        "installer_ui_under_test", REPO / "install" / "installer.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "env",
    [
        {"NO_COLOR": "1", "FORCE_COLOR": "1", "COLUMNS": "100"},
        {"FORCE_COLOR": "1", "JARVIS_INSTALL_ASCII": "1", "COLUMNS": "100"},
        {"COLUMNS": "40"},
    ],
)
def test_the_whole_stage_2_dry_run_degrades_cleanly(monkeypatch, capsys, env) -> None:
    installer = _installer()
    for name in ("NO_COLOR", "FORCE_COLOR", "JARVIS_INSTALL_ASCII", "COLUMNS", "COLORTERM"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(installer, "is_update_run", lambda: False)
    monkeypatch.setattr(installer, "_UI", None)
    assert installer.main(["--dry-run", "--headless"]) == 0
    out = capsys.readouterr().out
    if "NO_COLOR" in env or "FORCE_COLOR" not in env:
        assert ESC not in out
    if "JARVIS_INSTALL_ASCII" in env:
        assert strip_ansi(out).isascii()
    assert re.search(r"4/6.*Dependencies", strip_ansi(out))
    assert "Dodaios is ready" in out


def test_the_module_needs_nothing_beyond_the_standard_library() -> None:
    # installer.py draws with it before phase 4 has installed anything: an
    # interpreter without site-packages (-S) must import and use it.
    probe = (
        "import io, sys; sys.path.insert(0, sys.argv[1]); "
        "from dodaios.setup.install_ui import Caps, InstallUI; "
        "out = io.StringIO(); InstallUI(Caps('none', 'ascii', False, 80), out).ok('fine'); "
        "print(out.getvalue().strip())"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", probe, str(REPO)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "+  fine"
    assert install_ui.__name__.endswith("install_ui")
