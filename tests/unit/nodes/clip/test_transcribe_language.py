"""The spoken language is judged once per file, not per short piece."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dodaios.nodes.clip import transcribe


class _Model:
    def __init__(self) -> None:
        self.asked = 0

    def detect_language(self, samples: Any) -> tuple[str, float, list[Any]]:
        self.asked += 1
        return "en", 0.93, []


def test_language_is_judged_on_the_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "take.mp4"
    source.write_bytes(b"x")
    model = _Model()
    monkeypatch.setattr(transcribe, "_recognizer", lambda: model)
    monkeypatch.setattr(transcribe, "read_audio", lambda *a, **k: np.zeros(16_000 * 5, np.float32))
    monkeypatch.setattr(transcribe, "_heard", {})

    assert transcribe.spoken_language(source) == "en"
    assert transcribe.spoken_language(source) == "en"
    assert model.asked == 1


def test_an_unsure_guess_is_left_to_the_recognizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "take.mp4"
    source.write_bytes(b"x")

    class Unsure(_Model):
        def detect_language(self, samples: Any) -> tuple[str, float, list[Any]]:
            return "de", 0.3, []

    monkeypatch.setattr(transcribe, "_recognizer", Unsure)
    monkeypatch.setattr(transcribe, "read_audio", lambda *a, **k: np.zeros(16_000 * 5, np.float32))
    monkeypatch.setattr(transcribe, "_heard", {})

    assert transcribe.spoken_language(source) is None
