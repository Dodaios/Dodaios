"""The rows a pane has scrolled past are kept, so a viewer can be given them.

The defect (maintainer report, 2026-11-12): in a Grid pane running Claude Code
"I could scroll a little, but not all the way to the top". A pane's scrollback
lives in its viewer, the viewer is rebuilt whenever the pane is looked at again,
and all it was rebuilt from was the last 128 KB of raw output — a few screens of
an agent's drawing — or nothing at all after a resize.

``ScrollbackMirror`` replays the stream onto a grid and keeps what scrolls off.
These tests pin what counts as history (the same rows xterm would keep), that a
terminal written from the mirror ends up holding the same rows, and the bounds.

The cases in ``tests/fakes/terminal_scrollback_cases.json`` are shared with the
frontend (``terminalScrollbackReplay.test.ts``), which replays each one through
the real xterm: once continuously, once rebuilt from the replay recorded here.
Run this file with ``UPDATE_SCROLLBACK_CASES=1`` after changing the mirror's
output on purpose, and run the frontend test afterwards.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from dodaios.agentic_ide.scrollback import (
    HISTORY_LIMIT_CHARS,
    HISTORY_LIMIT_ROWS,
    ScrollbackMirror,
)
from dodaios.agentic_ide.transcript import strip_ansi

CASES_PATH = Path(__file__).parents[2] / "fakes" / "terminal_scrollback_cases.json"


def _history(mirror: ScrollbackMirror) -> list[str]:
    """The kept rows as plain text, one per line break."""
    if not mirror.history_rows:
        return []
    return strip_ansi(mirror.history_text()).split("\r\n")


def _rejoin(mirror: ScrollbackMirror) -> ScrollbackMirror:
    """A second terminal of the same size, written from the first one."""
    viewer = ScrollbackMirror(mirror.cols, mirror.rows)
    viewer.feed("\x1b[0m" + mirror.rows_text() + mirror.cursor_text())
    return viewer


# ------------------------------------------------------------ what is history
def test_rows_that_scroll_off_the_top_are_kept_in_order() -> None:
    mirror = ScrollbackMirror(40, 5)
    for number in range(12):
        mirror.feed(f"row {number}\r\n")

    assert _history(mirror) == [f"row {number}" for number in range(8)]
    assert mirror.display() == ["row 8", "row 9", "row 10", "row 11", ""]
    assert mirror.scrolled == 8


def test_a_row_repainted_in_place_is_not_history() -> None:
    """An agent's spinner rewrites one row hundreds of times; none of it scrolls."""
    mirror = ScrollbackMirror(40, 5)
    mirror.feed("answer\r\n\r\nworking 0s\r\n> prompt")
    for second in range(1, 300):
        mirror.feed(f"\x1b[1A\r\x1b[2Kworking {second}s\x1b[1B\r\x1b[8C")

    assert mirror.history_rows == 0
    assert mirror.display()[:4] == ["answer", "", "working 299s", "> prompt"]


def test_colours_survive_in_the_kept_rows() -> None:
    mirror = ScrollbackMirror(40, 3)
    mirror.feed("\x1b[1;38;5;174mClaude\x1b[22m \x1b[48;2;1;2;3mCode\x1b[0m plain\r\n")
    mirror.feed("\r\n\r\n")

    kept = mirror.history_text()
    assert kept.startswith("\x1b[0;1;38;5;174mClaude")
    assert "\x1b[0;38;5;174m " in kept, "bold ends, the colour stays"
    assert "\x1b[0;38;5;174;48;2;1;2;3mCode" in kept
    assert kept.splitlines()[0].endswith("\x1b[0m plain")


def test_a_row_ends_with_its_colour_closed() -> None:
    """Each kept row stands alone: the next one never inherits its colour."""
    mirror = ScrollbackMirror(20, 2)
    mirror.feed("\x1b[31mred to the end\r\nnext\r\n\r\n")

    first, second = mirror.history_text().split("\r\n")[:2]
    assert first == "\x1b[0;31mred to the end\x1b[0m"
    assert second == "\x1b[0;31mnext\x1b[0m"


def test_an_escape_sequence_split_by_a_read_is_still_one_sequence() -> None:
    """A PTY read ends anywhere; a half sequence must not be printed as text."""
    stream = "\x1b[38;5;214morange\x1b[0m\r\n\x1b]0;a title\x07second\x1b[2;5Hx\r\n\r\n\r\n"
    whole = ScrollbackMirror(30, 3)
    whole.feed(stream)
    for cut in range(1, len(stream)):
        split = ScrollbackMirror(30, 3)
        split.feed(stream[:cut])
        split.feed(stream[cut:])
        assert split.history_text() == whole.history_text(), f"differs when cut at {cut}"
        assert split.display() == whole.display(), f"differs when cut at {cut}"


def test_an_oversized_string_sequence_is_skipped_not_printed() -> None:
    """An inline image is megabytes of payload inside one OSC."""
    mirror = ScrollbackMirror(40, 4)
    mirror.feed("before\x1b]1337;File=inline=1:" + "A" * 3000)
    for _ in range(5):
        mirror.feed("B" * 3000)
    mirror.feed("CCC\x07after")

    assert mirror.display()[0] == "beforeafter"


def test_absurd_parameters_are_bounded_not_obeyed() -> None:
    """A stream may contain anything; none of it may raise or run for ever."""
    mirror = ScrollbackMirror(20, 3)
    # Numbers of thousands of digits: Python refuses to convert them at all.
    mirror.feed("ok\x1b[" + "9" * 5000 + "B\x1b[" + "9" * 5000 + "m")
    assert mirror.display() == ["ok", "", ""], "the cursor did not move, nothing raised"

    # "Repeat the last character a billion times" fills the screen once.
    mirror.feed("\x1b[999999999b")
    assert mirror.scrolled <= 3

    mirror.feed("\x1b[999999999;999999999H!\x1b[999999999S")
    mirror.feed("\x1b[999999999L\x1b[999999999M\x1b[999999999@\x1b[999999999P\x1b[999999999X")
    assert mirror.display() == ["", "", ""]
    assert mirror.scrolled <= 3


def test_scrolling_by_command_discards_rows_like_xterm() -> None:
    """``CSI S`` deletes rows; only a line feed at the bottom makes history."""
    mirror = ScrollbackMirror(20, 3)
    mirror.feed("one\r\ntwo\r\nthree\x1b[2S")

    assert mirror.history_rows == 0
    assert mirror.display() == ["three", "", ""]


def test_erasing_the_screen_keeps_the_history_and_ed3_clears_it() -> None:
    mirror = ScrollbackMirror(20, 3)
    mirror.feed("one\r\ntwo\r\nthree\r\nfour\r\n")
    assert _history(mirror) == ["one", "two"]

    mirror.feed("\x1b[2J\x1b[H")
    assert _history(mirror) == ["one", "two"], "an erase is not a scroll"
    assert mirror.display() == ["", "", ""]

    mirror.feed("\x1b[3J")
    assert mirror.history_rows == 0, "the terminal's own 'forget the scrollback'"


def test_the_alternate_screen_leaves_no_history() -> None:
    """A full-screen program's frames are not the pane's past."""
    mirror = ScrollbackMirror(20, 3)
    mirror.feed("one\r\ntwo\r\nthree\r\nfour")
    mirror.feed("\x1b[?1049h\x1b[H")
    assert mirror.on_alternate_screen is True
    for number in range(20):
        mirror.feed(f"frame {number}\r\n")
    mirror.feed("\x1b[?1049l")

    assert mirror.on_alternate_screen is False
    assert _history(mirror) == ["one"]
    assert mirror.display() == ["two", "three", "four"], "the primary screen is back"


def test_a_scroll_region_below_the_top_scrolls_nothing_into_history() -> None:
    mirror = ScrollbackMirror(20, 5)
    mirror.feed("header\r\n\x1b[2;5r\x1b[5;1H")
    for number in range(6):
        mirror.feed(f"\nline {number}")

    assert mirror.history_rows == 0
    assert mirror.display()[0] == "header"


def test_wide_glyphs_take_two_cells_and_marks_none() -> None:
    mirror = ScrollbackMirror(10, 3)
    mirror.feed("日本語\x1b[8Gx\r\né!\r\n\r\n\r\n")

    rows = _history(mirror)
    assert rows[0] == "日本語 x", "three wide glyphs fill six cells; column 8 is the eighth"
    assert rows[1] == "é!", "the accent joins its letter"


def test_the_one_cell_fast_path_only_takes_one_cell_characters() -> None:
    """Runs of these are laid out without a per-character width lookup."""
    from dodaios.agentic_ide import scrollback

    for code in range(0x20, 0x3000):
        ch = chr(code)
        if scrollback._NARROW_RE.fullmatch(ch) and not ch.isascii():  # noqa: SLF001
            assert scrollback._width(ch) == 1, f"U+{code:04X} is not one cell wide"  # noqa: SLF001


def test_a_long_line_wraps_and_is_kept_as_one_line() -> None:
    """Written back at any width it wraps there, instead of staying cut at ours."""
    mirror = ScrollbackMirror(10, 3)
    mirror.feed("abcdefghijklmnopqrstuvwxy\r\nnext\r\n\r\n\r\n\r\n")

    assert _history(mirror)[:2] == ["abcdefghijklmnopqrstuvwxy", "next"]


# ------------------------------------------------------------------ the bounds
def test_the_history_is_bounded_by_rows() -> None:
    mirror = ScrollbackMirror(20, 3, limit_rows=50)
    for number in range(500):
        mirror.feed(f"row {number}\r\n")

    rows = _history(mirror)
    assert len(rows) == 50
    assert rows[0] == "row 448" and rows[-1] == "row 497"
    assert mirror.scrolled == 498, "the counter keeps counting past the bound"


def test_the_history_is_bounded_by_characters() -> None:
    mirror = ScrollbackMirror(120, 3, limit_chars=2_000)
    for number in range(200):
        mirror.feed(f"{number:03d} " + "x" * 96 + "\r\n")

    assert len(mirror.history_text()) <= 2_000
    assert _history(mirror)[-1].startswith("197 ")
    assert mirror.history_rows < 20


def test_the_default_bound_matches_the_viewers_scrollback() -> None:
    """Rows past the viewer's own limit would be sent and dropped on arrival."""
    frontend = Path(__file__).parents[3] / "dodaios/ui/web/frontend/src/components/agentic"
    source = (frontend / "AgenticTerminal.tsx").read_text(encoding="utf-8")

    assert f"scrollback: {HISTORY_LIMIT_ROWS}," in source
    assert HISTORY_LIMIT_CHARS >= 80 * HISTORY_LIMIT_ROWS, "a full history of ordinary rows fits"


def test_rows_up_to_a_mark_can_be_asked_for() -> None:
    mirror = ScrollbackMirror(20, 3, limit_rows=4)
    for number in range(5):
        mirror.feed(f"row {number}\r\n")
    mark = mirror.scrolled
    for number in range(5, 8):
        mirror.feed(f"row {number}\r\n")

    assert mark == 3
    assert strip_ansi(mirror.history_text(upto=mark)) == "row 2", (
        "rows 0 and 1 have left the bound; rows past the mark are not included"
    )
    assert mirror.history_text(upto=0) == ""


def test_a_new_process_starts_with_no_history_at_the_same_size() -> None:
    mirror = ScrollbackMirror(30, 4)
    for number in range(10):
        mirror.feed(f"\x1b[32mrow {number}\r\n")
    mirror.clear()

    assert (mirror.cols, mirror.rows) == (30, 4)
    assert mirror.history_rows == 0 and mirror.scrolled == 0
    mirror.feed("fresh")
    assert mirror.rows_text().startswith("fresh"), "and no colour left over"


# -------------------------------------------------------------------- resizing
def test_a_shorter_pane_drops_rows_below_the_cursor_before_it_scrolls() -> None:
    mirror = ScrollbackMirror(20, 6)
    mirror.feed("one\r\ntwo\r\nthree\r\nfour\x1b[2;1H")

    mirror.resize(20, 4)
    assert mirror.history_rows == 0
    assert mirror.display() == ["one", "two", "three", "four"]

    mirror.resize(20, 2)
    assert mirror.display() == ["one", "two"], "the rows below the cursor go first"

    mirror.feed("\x1b[2;1H")
    mirror.resize(20, 1 + 1)
    assert mirror.history_rows == 0


def test_a_shorter_pane_scrolls_when_the_cursor_is_at_the_bottom() -> None:
    mirror = ScrollbackMirror(20, 4)
    mirror.feed("one\r\ntwo\r\nthree\r\nfour")

    mirror.resize(20, 2)

    assert _history(mirror) == ["one", "two"]
    assert mirror.display() == ["three", "four"]


def test_a_narrower_pane_breaks_long_rows_instead_of_cutting_them() -> None:
    mirror = ScrollbackMirror(20, 4)
    mirror.feed("0123456789abcdefghij\r\nshort\r\n")

    mirror.resize(10, 4)
    assert mirror.display() == ["0123456789", "abcdefghij", "short", ""]

    mirror.feed("\r\n\r\n\r\n\r\n")
    assert _history(mirror)[:2] == ["0123456789abcdefghij", "short"], "still one line of text"


def test_a_row_that_stopped_being_a_continuation_starts_its_own_line() -> None:
    """A wrapped line's second half is erased and reused; it must not stay glued on."""
    mirror = ScrollbackMirror(10, 3)
    mirror.feed("0123456789abc")
    mirror.feed("\r\x1b[2Kfresh\r\n\r\n\r\n")

    assert _history(mirror)[:2] == ["0123456789", "fresh"]


# ------------------------------------------------------- the shared protocol cases
def _inline_agent_steps() -> list[dict[str, Any]]:
    """An agent that prints into the normal buffer and repaints its footer in place."""
    steps: list[dict[str, Any]] = [
        {"write": "\x1b7\x1b[r\x1b8\x1b[?25l\x1b[?2004h"},
        {"write": "\x1b[38;5;174m ▐▛███▜▌\x1b[12G\x1b[39m\x1b[1mAgent\x1b[22m v1\r\n\r\n"},
    ]
    footer = (
        "\x1b[38;5;245m" + "─" * 60 + "\x1b[39m\r\n"
        "❯\xa0\r\n"
        "\x1b[38;5;245m" + "─" * 60 + "\x1b[39m\r\n"
        "  \x1b[38;5;137m⏵⏵\x1b[6Gauto\x1b[11Gmode\x1b[39m"
    )
    steps.append({"write": footer + "\x1b[2A\r\x1b[2C"})
    for turn in range(14):
        # Back to the top of the footer, erase it, print the turn, redraw it.
        steps.append({"write": "\x1b[1A\r\x1b[J"})
        steps.append({"write": f"\x1b[48;5;237m> question {turn}" + " " * 40 + "\x1b[49m\r\n\r\n"})
        steps.append(
            {"write": "\x1b[38;5;174m✻\x1b[39m Working… 0s\r\n" + footer + "\x1b[2A\r\x1b[2C"}
        )
        for second in range(1, 6):
            spinner = f"\x1b[38;5;174m✻\x1b[39m Working… {second}s"
            steps.append({"write": f"\x1b[2A\r\x1b[2K{spinner}\x1b[2B\r\x1b[2C"})
        steps.append({"write": "\x1b[2A\r\x1b[J"})
        answer = "".join(
            f"\x1b[3G\x1b[32mline\x1b[39m {turn}.{line} of the answer\r\n" for line in range(4)
        )
        steps.append({"write": "⏺ answer " + str(turn) + "\r\n" + answer + "\r\n" + footer})
        steps.append({"write": "\x1b[2A\r\x1b[2C"})
    return steps


def _cases() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {
        "inline_agent": {"cols": 64, "rows": 18, "steps": _inline_agent_steps()},
        "wide_and_wrapped": {
            "cols": 24,
            "rows": 6,
            "steps": [
                {"write": "日本語のテキスト、長い行は折り返されます。\r\n"},
                {"write": "tab\there\tand\tthere\r\n"},
                {"write": "".join(chr(ord("a") + index % 26) for index in range(70)) + "\r\n"},
                {"write": "café \x1b[4:3mcurly\x1b[24m \x1b[7minverse\x1b[27m\r\n"},
                {"write": "ok ⚠️ warning\r\n\x1b[2;3Hx\x1b[6;1H"},
                {"write": "one\r\ntwo\r\nthree\r\nfour\r\nfive"},
            ],
        },
        # The cursor rests above the last row, as an agent's does in its prompt
        # box: with it ON the last row xterm pulls rows back out of its
        # scrollback when a pane grows, which the mirror does not do (see the
        # module docstring of ``scrollback``).
        "resized": {
            "cols": 40,
            "rows": 8,
            "steps": [
                {"write": "".join(f"row {n} " + "=" * (n * 3) + "\r\n" for n in range(12))},
                {
                    "write": "\x1b[44mprompt"
                    + " " * 34
                    + "\x1b[49m\r\n> \r\n  status\x1b[1A\r\x1b[2C"
                },
                {"resize": [28, 11]},
                {"write": "\x1b[H" + "\x1b[2K\x1b[1B" * 11 + "\x1b[Hrepainted\r\n> \r\n  status"},
                {"write": "\x1b[1A\r\x1b[2C"},
                {"resize": [50, 6]},
                {"write": "\x1b[H" + "\x1b[2K\x1b[1B" * 6 + "\x1b[Hagain\r\n> \r\n  status"},
                {"write": "".join(f"\r\nafter {n}" for n in range(15))},
            ],
        },
        "shell_clear": {
            "cols": 30,
            "rows": 5,
            "steps": [
                {"write": "$ ls\r\na\r\nb\r\nc\r\nd\r\ne\r\n$ clear\r\n"},
                {"write": "\x1b[H\x1b[2J$ echo hi\r\nhi\r\n$ "},
                {"write": "seq\r\n" + "".join(f"{n}\r\n" for n in range(9)) + "$ "},
            ],
        },
        "alternate_screen_visit": {
            "cols": 30,
            "rows": 5,
            "steps": [
                {"write": "".join(f"before {n}\r\n" for n in range(7)) + "$ vim"},
                {"write": "\x1b[?1049h\x1b[H\x1b[2J" + "".join(f"~ {n}\r\n" for n in range(9))},
                {
                    "write": "\x1b[?1049l\r\n$ after\r\n"
                    + "".join(f"then {n}\r\n" for n in range(4))
                },
            ],
        },
        "scroll_region": {
            "cols": 30,
            "rows": 8,
            "steps": [
                {"write": "".join(f"log {n}\r\n" for n in range(5))},
                {"write": "\x1b[1;5r\x1b[5;1H" + "".join(f"\ninserted {n}" for n in range(6))},
                {"write": "\x1b[r\x1b[7;1Hstatus\x1b[3;1H\x1b[1L\x1b[2M\x1b[1;1H\x1bMtop"},
                {"write": "\x1b[8;1H" + "".join(f"\nmore {n}" for n in range(4))},
            ],
        },
    }
    for case in cases.values():
        mirror = ScrollbackMirror(case["cols"], case["rows"])
        for step in case["steps"]:
            if "resize" in step:
                mirror.resize(*step["resize"])
            else:
                mirror.feed(step["write"])
        case["replay"] = "\x1b[0m" + mirror.rows_text() + mirror.cursor_text()
        case["history_rows"] = mirror.history_rows
    return cases


def test_the_shared_cases_are_current() -> None:
    """The frontend replays these through xterm; they must be what the mirror writes."""
    cases = _cases()
    if os.environ.get("UPDATE_SCROLLBACK_CASES"):
        CASES_PATH.write_text(
            json.dumps(cases, ensure_ascii=True, indent=1) + "\n", encoding="utf-8"
        )
    assert json.loads(CASES_PATH.read_text(encoding="utf-8")) == cases, (
        "the mirror's output changed: rerun with UPDATE_SCROLLBACK_CASES=1, then run "
        "terminalScrollbackReplay.test.ts in the frontend"
    )


@pytest.mark.parametrize("name", sorted(_cases()))
def test_a_terminal_written_from_the_mirror_holds_the_same_rows(name: str) -> None:
    """Written back and read again, nothing is lost, doubled or moved."""
    case = _cases()[name]
    mirror = ScrollbackMirror(case["cols"], case["rows"])
    for step in case["steps"]:
        if "resize" in step:
            mirror.resize(*step["resize"])
        else:
            mirror.feed(step["write"])

    viewer = _rejoin(mirror)

    assert viewer.history_text() == mirror.history_text()
    assert viewer.display() == mirror.display()
    assert viewer.cursor_text() == mirror.cursor_text()


def test_the_inline_agent_case_keeps_the_whole_conversation() -> None:
    """The report in one assertion: the first question is still reachable."""
    case = _cases()["inline_agent"]
    mirror = ScrollbackMirror(case["cols"], case["rows"])
    for step in case["steps"]:
        mirror.feed(step["write"])

    rows = [row.rstrip() for row in _history(mirror)] + mirror.display()
    for turn in range(14):
        assert rows.count(f"> question {turn}") == 1
        assert rows.count(f"⏺ answer {turn}") == 1
    assert sum("Working…" in row for row in rows) == 0, "the spinner never scrolled"
    assert rows.index("> question 0") < rows.index("> question 13")
