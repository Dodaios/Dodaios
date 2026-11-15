"""A microphone the audio system stopped answering for is freed by a restart.

Nothing inside the process can free such an input (see
``dodaios/audio/stuck_rescue.py``), and on 2026-11-15 the app stayed deaf for
sixteen minutes until somebody restarted it by hand. Pinned here: the app asks
for its own restart once the input has been stuck for a while and nothing is
running that the restart would end; it asks once per episode; and a restart
that does not help cannot repeat for ever.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.audio import stuck_rescue
from dodaios.audio.stuck_rescue import MAX_RESTARTS, STUCK_FOR_S, WINDOW_S, MicrophoneRescue

BUILT_IN = "MacBook Air Microphone"


class _App:
    """The three things the rescue asks the app, and a clock it can move."""

    def __init__(self, data_dir: Path) -> None:
        self.stuck: str | None = None
        self.idle = True
        self.can_restart = True
        self.restarts = 0
        self.now = 1_000.0
        self.rescue = self.new_process(data_dir)

    def new_process(self, data_dir: Path) -> MicrophoneRescue:
        self.rescue = MicrophoneRescue(
            stuck=lambda: self.stuck,
            idle=lambda: self.idle,
            restart=self._restart,
            data_dir=data_dir,
            clock=lambda: self.now,
            monotonic=lambda: self.now,
        )
        return self.rescue

    def _restart(self) -> bool:
        if self.can_restart:
            self.restarts += 1
        return self.can_restart

    def later(self, seconds: float) -> bool:
        self.now += seconds
        return self.rescue.tick()


@pytest.fixture
def app(tmp_path: Path) -> _App:
    return _App(tmp_path)


def test_a_microphone_that_works_is_never_a_reason_to_restart(app: _App) -> None:
    for _ in range(10):
        assert app.later(60.0) is False
    assert app.restarts == 0


def test_a_stuck_microphone_restarts_the_app_after_a_while(app: _App) -> None:
    app.stuck = BUILT_IN

    assert app.later(0.0) is False
    assert app.later(STUCK_FOR_S - 1.0) is False, "restarted before the audio system had its time"
    assert app.later(2.0) is True
    assert app.restarts == 1


def test_it_waits_until_nothing_is_running_that_the_restart_would_end(app: _App) -> None:
    app.stuck = BUILT_IN
    app.idle = False
    app.later(0.0)

    assert app.later(STUCK_FOR_S + 60.0) is False
    assert app.restarts == 0

    app.idle = True
    assert app.later(5.0) is True
    assert app.restarts == 1


def test_one_episode_asks_for_one_restart(app: _App) -> None:
    app.stuck = BUILT_IN
    app.later(0.0)
    assert app.later(STUCK_FOR_S) is True

    for _ in range(5):
        assert app.later(5.0) is False
    assert app.restarts == 1


def test_a_microphone_that_answers_again_in_time_needs_no_restart(app: _App) -> None:
    app.stuck = BUILT_IN
    app.later(0.0)
    app.later(STUCK_FOR_S - 5.0)
    app.stuck = None
    assert app.later(5.0) is False

    # Stuck again later: the wait starts over.
    app.stuck = BUILT_IN
    assert app.later(0.0) is False
    assert app.later(STUCK_FOR_S - 1.0) is False
    assert app.restarts == 0


def test_restarts_that_do_not_help_stop_after_a_few(app: _App, tmp_path: Path) -> None:
    """A broken audio driver would otherwise restart the app for ever."""
    app.stuck = BUILT_IN
    for _ in range(MAX_RESTARTS):
        app.new_process(tmp_path)  # the app came up again, and the microphone is stuck again
        app.later(0.0)
        assert app.later(STUCK_FOR_S) is True
    assert app.restarts == MAX_RESTARTS

    app.new_process(tmp_path)
    app.later(0.0)
    assert app.later(STUCK_FOR_S) is False
    assert app.later(600.0) is False
    assert app.restarts == MAX_RESTARTS

    # An hour later the count is forgotten.
    app.new_process(tmp_path)
    app.later(WINDOW_S)
    assert app.later(STUCK_FOR_S) is True
    assert app.restarts == MAX_RESTARTS + 1


def test_an_app_that_cannot_restart_itself_is_not_counted_as_restarted(
    app: _App, tmp_path: Path
) -> None:
    app.stuck = BUILT_IN
    app.can_restart = False
    app.later(0.0)

    assert app.later(STUCK_FOR_S) is False

    saved = json.loads((tmp_path / stuck_rescue._STATE_FILE).read_text(encoding="utf-8"))
    assert saved == {"restarts": []}


def test_a_restart_that_cannot_be_counted_is_not_made(app: _App, tmp_path: Path) -> None:
    """Without the count a restart loop could not be seen."""
    (tmp_path / stuck_rescue._STATE_FILE).mkdir()  # a folder where the file belongs
    app.stuck = BUILT_IN
    app.later(0.0)

    with pytest.raises(RuntimeError):
        app.later(STUCK_FOR_S)
    assert app.restarts == 0
