"""Piper phonemes keep word spaces and stress marks.

BC-250 2026-10-29: the French Siwis voice spoke parts of an answer too fast,
with words skipped or unintelligible. The eSpeak IPA handed to sherpa-onnx 2 had
every space and stress mark removed, so a whole clause was read as one long
word. Measured on the real voice: 12-18 % shorter and a round-trip transcript
word error rate of 32 % against 11 % once spaces and stress are kept.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.plugins.tts import piper_local
from dodaios.plugins.tts.piper_local import PiperLocalTTS

SPACE, PRIMARY, SECONDARY = ord(" "), ord("ˈ"), ord("ˌ")
SENTENCE = "En 2387, Léa, la mécanicienne du vaisseau Aurore, capte un signal."  # i18n-allow: French fixture


def test_one_group_with_single_spaces_and_stress_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(stdout="  ʒə- nə  pˈø\npa  fˈɛʁ\n")

    monkeypatch.setattr(piper_local.shutil, "which", lambda _name: "/usr/bin/espeak-ng")
    monkeypatch.setattr(piper_local.subprocess, "run", fake_run)

    groups = PiperLocalTTS._phonemize("je ne peux pas faire", "fr-FR")  # i18n-allow: French fixture

    assert len(groups) == 1, "sherpa-onnx 2 needs one group per segment"
    assert "".join(map(chr, groups[0])) == "ʒə- nə pˈø pa fˈɛʁ"


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="eSpeak NG is not installed")
def test_real_french_phonemes_keep_word_boundaries_and_stress() -> None:
    (group,) = PiperLocalTTS._phonemize(SENTENCE, "fr-FR")
    words = len(SENTENCE.split())
    assert group.count(SPACE) >= words - 2, "each word boundary must reach the voice"
    assert PRIMARY in group
    assert "  " not in "".join(map(chr, group))


def _french_tokens() -> Path | None:
    for base in (Path("data/models"), Path(__file__).resolve().parents[4] / "data" / "models"):
        tokens = base / "vits-piper-fr_FR-siwis-medium" / "tokens.txt"
        if tokens.is_file():
            return tokens
    return None


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="eSpeak NG is not installed")
@pytest.mark.skipif(_french_tokens() is None, reason="the French Piper voice is not installed")
def test_every_phoneme_handed_to_the_french_voice_is_in_its_vocabulary() -> None:
    tokens_file = _french_tokens()
    assert tokens_file is not None
    known = set()
    for line in tokens_file.read_text(encoding="utf-8").splitlines():
        symbol = line.rsplit(" ", 1)[0] if line.strip() else ""
        known.add(" " if line.startswith("  ") else symbol)
    for text in (SENTENCE, "Je ne peux pas faire de recherche en direct ici, donc."):  # i18n-allow
        (group,) = PiperLocalTTS._phonemize(text, "fr-FR")
        unknown = {chr(code) for code in group} - known
        assert not unknown, f"phonemes the voice cannot read: {sorted(unknown)}"
    assert {" ", "ˈ", "ˌ"} <= known


def test_subprocess_is_called_without_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        seen["argv"], seen["shell"] = argv, kwargs.get("shell", False)
        return SimpleNamespace(stdout="bɔ̃ʒˈuʁ\n")

    monkeypatch.setattr(piper_local.shutil, "which", lambda _name: "/usr/bin/espeak-ng")
    monkeypatch.setattr(piper_local.subprocess, "run", fake_run)
    PiperLocalTTS._phonemize("bonjour", "fr")
    assert seen["argv"][:5] == ["espeak-ng", "-q", "-v", "fr", "--ipa"]
    assert seen["shell"] is False
    assert subprocess is piper_local.subprocess
