"""A pane that is looked at again can be scrolled back to where its agent began.

The report (maintainer, 2026-11-12, Agentic IDE, Grid layout, a pane running
Claude Code): "I could scroll a little, but not all the way to the top."

Nothing was wrong with scrolling. A pane's scrollback lives in its viewer, and
the viewer is rebuilt from the registry's replay every time the pane is joined
again — the switch between Chat and Grid, another workspace and back, a reload,
an app restart. That replay was the last 128 KB of the agent's raw output, which
is a few screens of a TUI's drawing; and any resize of the pane emptied it,
because cursor moves made for one grid cannot be replayed into another. What the
viewer was handed is what it could scroll through.

These drive the registry the way a viewer does — attach, let the agent print,
come back — and read the replay the way a terminal would, so they hold whatever
shape the replay takes. ``test_scrollback.py`` covers the mirror that keeps the
rows, ``test_transcript.py`` the buffer that composes the replay.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.agentic_ide import session as ide
from dodaios.agentic_ide.scrollback import ScrollbackMirror
from dodaios.agentic_ide.transcript import REPLAY_LIMIT_CHARS, strip_ansi
from dodaios.terminal.pty_host import PtyHost
from tests.fakes.fake_pty_manager import FakePtyManager
from tests.unit.agentic_ide.test_pty_host_adoption import FakeHostedPool


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> FakePtyManager:
    monkeypatch.setattr(ide, "agent_argv", lambda name: (f"/usr/bin/{name}",))
    monkeypatch.setattr(ide, "COLD_START_SETTLE_S", 0.0)
    # The repaint nudge sleeps between its two resizes; nothing here waits on it.
    monkeypatch.setattr(ide, "REPAINT_NUDGE_S", 0.0)
    return FakePtyManager()


async def _gone(_code: int) -> None:
    return None


class Viewer:
    """One pane socket: live output on one channel, a re-joined screen on the other."""

    def __init__(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.output: list[str] = []
        self.replay: list[str] = []

    async def on_output(self, text: str) -> None:
        self.output.append(text)

    async def on_replay(self, text: str, repaint: bool = False) -> None:
        self.replay.append(text)

    def rows_held(self) -> list[str]:
        """What a terminal of this size holds once the replay is written to it.

        The pane clears its terminal for a replay, so only the last one counts,
        followed by whatever arrived as output after it.
        """
        terminal = ScrollbackMirror(self.cols, self.rows)
        terminal.feed("".join(self.replay[-1:]) + "".join(self.output))
        history = strip_ansi(terminal.history_text()).split("\r\n") if terminal.history_rows else []
        return history + terminal.display()


async def _pane(pool: FakePtyManager, folder: Path, cols: int = 80, rows: int = 24):  # noqa: ANN202
    registry = ide.Registry(pty_manager=pool)
    session = await registry.start(str(folder), [{"agent": "claude"}])
    term = session.terminals[0]
    first = Viewer(cols, rows)
    await registry.attach(
        term.key,
        cols,
        rows,
        first.on_output,
        _gone,
        workspace_id=session.id,
        on_replay=first.on_replay,
    )
    return registry, session, term, first


async def _work(pool: FakePtyManager, pty_id: str | None, turns: range, spins: int = 60) -> int:
    """An agent on the normal buffer: one answer row per turn, a spinner between.

    Returns how many characters it wrote, to show the raw output is long gone.
    """
    written = 0
    for turn in turns:
        chunk = f"\x1b[32m⏺\x1b[39m answer {turn}\r\n✻ working 0s"
        chunk += "".join(f"\r\x1b[2K✻ working {second}s" for second in range(1, spins))
        chunk += "\r\x1b[2K"
        await pool.emit(pty_id, chunk)
        written += len(chunk)
    return written


def _answers(rows: list[str]) -> list[str]:
    return [row for row in rows if row.startswith("⏺ answer ")]


async def _rejoin(registry, session, term, cols: int, rows: int) -> Viewer:  # noqa: ANN001
    back = Viewer(cols, rows)
    await registry.attach(
        term.key,
        cols,
        rows,
        back.on_output,
        _gone,
        workspace_id=session.id,
        on_replay=back.on_replay,
    )
    return back


async def test_a_rejoined_pane_reaches_back_to_the_first_row(
    pool: FakePtyManager, tmp_path: Path
) -> None:
    """The report: a long session, looked at again, starts where it started."""
    registry, session, term, _first = await _pane(pool, tmp_path)
    written = await _work(pool, term.pty_id, range(400))
    assert written > 3 * REPLAY_LIMIT_CHARS, "far more than the raw tail keeps"

    back = await _rejoin(registry, session, term, 80, 24)

    assert _answers(back.rows_held()) == [f"⏺ answer {turn}" for turn in range(400)]
    assert len(back.replay[-1]) < REPLAY_LIMIT_CHARS, "and it is a small thing to send"


async def test_a_pane_that_was_resized_keeps_its_history(
    pool: FakePtyManager, tmp_path: Path
) -> None:
    """Maximizing a pane or dragging a seam used to cost the next viewer everything."""
    registry, session, term, first = await _pane(pool, tmp_path)
    await _work(pool, term.pty_id, range(120), spins=4)

    assert registry.resize(term.key, 100, 30, workspace_id=session.id, viewer=first.on_output)
    back = await _rejoin(registry, session, term, 100, 30)

    answers = _answers(back.rows_held())
    assert answers[0] == "⏺ answer 0"
    assert answers == [f"⏺ answer {turn}" for turn in range(len(answers))], "in order, none twice"
    assert len(answers) >= 120 - 30, "everything that had scrolled off; the screen is the agent's"


async def test_a_viewer_coming_back_at_another_size_gets_the_history(
    pool: FakePtyManager, tmp_path: Path
) -> None:
    """Chat and Grid give a pane different sizes; switching is a re-join AND a resize."""
    registry, session, term, _first = await _pane(pool, tmp_path)
    await _work(pool, term.pty_id, range(120), spins=4)

    back = await _rejoin(registry, session, term, 120, 40)

    answers = _answers(back.rows_held())
    assert answers[0] == "⏺ answer 0"
    assert len(answers) >= 120 - 24
    assert (term.pty_cols, term.pty_rows) == (120, 40)
    # Rows the agent prints from now on scroll off at the NEW height.
    kept = term.replay.history_rows
    await pool.emit(term.pty_id, "\x1b[H" + "row\r\n" * 39)
    assert term.replay.history_rows == kept, "39 line feeds from the top of 40 rows scroll nothing"
    await pool.emit(term.pty_id, "row\r\n")
    assert term.replay.history_rows == kept + 1


async def test_a_restarted_agent_starts_with_an_empty_history(
    pool: FakePtyManager, tmp_path: Path
) -> None:
    """The rows belong to the process that printed them, not to the pane."""
    registry, session, term, first = await _pane(pool, tmp_path)
    await _work(pool, term.pty_id, range(60), spins=4)
    assert term.replay.history_rows > 0

    await pool.die(term.pty_id, 0)
    await registry.attach(
        term.key,
        80,
        24,
        first.on_output,
        _gone,
        workspace_id=session.id,
        on_replay=first.on_replay,
    )

    assert term.status == "live"
    assert term.replay.history_rows == 0
    assert "answer" not in term.replay.text()


async def test_an_agent_that_outlived_the_app_brings_its_history_along(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host keeps the rows while the app is closed, and hands them over.

    Both ends for real: a ``PtyHost`` that owned the agent, and a registry that
    adopts what the host replies with.
    """
    monkeypatch.setattr(ide, "agent_argv", lambda name: (f"/usr/bin/{name}",))
    monkeypatch.setattr(ide, "REPAINT_NUDGE_S", 0.0)
    hosted = FakePtyManager()
    monkeypatch.setattr("dodaios.terminal.pty_manager.PtyManager", lambda: hosted)
    host = PtyHost("token")
    spawned = await host._spawn({"argv": ["claude"], "cols": 100, "rows": 40})  # noqa: SLF001
    await _work(hosted, spawned["id"], range(400))
    reply = host._adopt(spawned["id"])  # noqa: SLF001
    assert reply["truncated"] is True

    pool = FakeHostedPool()
    registry = ide.Registry(pty_manager=pool)
    session = await registry.start(str(tmp_path), [{"agent": "claude", "name": "T1"}])
    term = session.find("T1")
    pool.add_hosted("h1", history_id=term.history_id, replay=reply["replay"])
    await registry._adopt_hosted(session)  # noqa: SLF001 - what a restart runs

    back = await _rejoin(registry, session, term, 100, 40)

    assert _answers(back.rows_held()) == [f"⏺ answer {turn}" for turn in range(400)]


async def test_the_host_keeps_history_at_the_size_it_was_told(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows scroll off at the pane's height, not at a default one."""
    hosted = FakePtyManager()
    monkeypatch.setattr("dodaios.terminal.pty_manager.PtyManager", lambda: hosted)
    host = PtyHost("token")
    spawned = await host._spawn({"argv": ["sh"], "cols": 60, "rows": 10})  # noqa: SLF001
    replay = host._terminals[spawned["id"]].replay  # noqa: SLF001

    await hosted.emit(spawned["id"], "".join(f"line {n}\r\n" for n in range(15)))
    assert replay.history_rows == 6, "sixteen rows through a screen of ten"

    host._resize({"id": spawned["id"], "cols": 60, "rows": 5})  # noqa: SLF001
    assert replay.history_rows == 11, "the cursor is on the last row, so the top scrolls off"
