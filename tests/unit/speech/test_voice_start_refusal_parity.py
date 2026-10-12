"""Parity for the layers that share the voice start-refusal vocabulary.

``POST /api/voice/call`` answers a refused start with a reason code, and the
voice controls turn that code into the sentence the person reads. A code the
frontend does not know falls back to a sentence without a cause, and a code
without a sentence in one language shows a raw key. Both ship silently, so the
layers are held together here:

1. ``jarvis/speech/start_refusal.py``                 - the Python tuple (source of truth)
2. ``jarvis/ui/web/frontend/src/lib/voiceStartRefusal.ts`` - ``VOICE_START_REFUSALS``
3. ``jarvis/ui/web/frontend/src/i18n/locales/*.json`` - one sentence per code and language
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from jarvis.speech.start_refusal import VOICE_START_REFUSALS

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "jarvis/ui/web/frontend/src"
REFUSAL_TS = FRONTEND_SRC / "lib/voiceStartRefusal.ts"
LOCALES = sorted((FRONTEND_SRC / "i18n/locales").glob("*.json"))


def test_the_frontend_lists_the_same_codes() -> None:
    source = REFUSAL_TS.read_text(encoding="utf-8")
    block = re.search(
        r"export const VOICE_START_REFUSALS = \[(.*?)\] as const", source, re.DOTALL
    )
    assert block, "VOICE_START_REFUSALS not found in voiceStartRefusal.ts"
    assert tuple(re.findall(r'"([a-z_]+)"', block.group(1))) == VOICE_START_REFUSALS


@pytest.mark.parametrize("locale", LOCALES, ids=lambda path: path.stem)
def test_every_language_has_one_sentence_per_code(locale: Path) -> None:
    bubble = json.loads(locale.read_text(encoding="utf-8"))["agentic_grid"]["voice_bubble"]
    sentences = bubble["start_refused"]
    assert set(sentences) == set(VOICE_START_REFUSALS)
    assert all(str(text).strip() for text in sentences.values())
    # The fallback names no cause: it is shown when the reason is unknown.
    assert bubble["start_failed"].strip()
