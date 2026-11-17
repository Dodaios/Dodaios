"""Finding the quiet parts of a recording (``dodaios/nodes/clip/silence.py``)."""

from __future__ import annotations

from pathlib import Path

from dodaios.nodes.clip import silence

from .conftest import np, write_sound


def test_a_pause_between_two_sounds_is_found_with_its_padding(tmp_path: Path) -> None:
    source = write_sound(tmp_path / "talk.m4a", [(1.0, 0.5), (1.2, 0.0), (1.0, 0.5)])

    spans = silence.find_silences(source, min_silence=0.5, pad=0.1)

    assert len(spans) == 1
    start, end = spans[0]
    assert abs(start - 1.1) < 0.06 and abs(end - 2.1) < 0.06


def test_a_short_breath_and_a_steady_sound_hold_no_silence(tmp_path: Path) -> None:
    breath = write_sound(tmp_path / "breath.m4a", [(1.0, 0.5), (0.3, 0.0), (1.0, 0.5)])
    steady = write_sound(tmp_path / "steady.m4a", [(2.0, 0.4)])

    assert silence.find_silences(breath, min_silence=0.5) == []
    assert silence.find_silences(steady) == []


def test_times_are_in_the_source_when_a_range_is_read(tmp_path: Path) -> None:
    source = write_sound(tmp_path / "talk.m4a", [(1.0, 0.5), (1.0, 0.0), (1.0, 0.5)])

    spans = silence.find_silences(source, start=0.5, end=2.5, pad=0.0)

    assert len(spans) == 1
    assert abs(spans[0][0] - 1.0) < 0.05 and abs(spans[0][1] - 2.0) < 0.05


def test_the_edges_of_the_recording_need_no_padding() -> None:
    quiet = np.array([True] * 30 + [False] * 10 + [True] * 30)

    spans = silence.spans_of(quiet, 0.02, 0.3, 0.1)

    assert spans == [(0.0, 0.5), (0.9, 1.4)]
