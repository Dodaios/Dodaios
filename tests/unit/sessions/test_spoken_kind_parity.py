"""Parity test for the SpeechSpoken ``spoken_kind`` vocabulary.

Same anti-drift contract as ``test_hangup_reason_parity.py``: the set of spoken
phrase-kinds (timeout / announcement / clarify / …) must agree across every
layer, so the frontend's types cover every value the pipeline can emit. A
drift fails this test instead of shipping an unknown kind.

Layers under test:

1. ``dodaios/sessions/constants.py``       — ``SPOKEN_KINDS`` tuple (source of truth)
2. ``dodaios/sessions/models.py``          — ``KNOWN_SPOKEN_KINDS`` frozenset (mirror)
3. ``dodaios/ui/web/frontend/.../sessions/types.ts``
                                          — ``KNOWN_SPOKEN_KINDS`` const tuple
"""
from __future__ import annotations

import re
from pathlib import Path

from dodaios.sessions.constants import SPOKEN_KINDS
from dodaios.sessions.models import KNOWN_SPOKEN_KINDS

REPO_ROOT = Path(__file__).resolve().parents[3]
TYPES_TS = REPO_ROOT / "dodaios/ui/web/frontend/src/components/sessions/types.ts"
def _expected() -> set[str]:
    return set(SPOKEN_KINDS)


def test_models_known_set_matches_constants_tuple() -> None:
    assert set(KNOWN_SPOKEN_KINDS) == _expected()


def test_types_ts_known_set_matches_constants_tuple() -> None:
    text = TYPES_TS.read_text(encoding="utf-8")
    block = re.search(
        r"export\s+const\s+KNOWN_SPOKEN_KINDS\s*=\s*\[([\s\S]+?)\]\s*as\s+const",
        text,
        re.MULTILINE,
    )
    assert block is not None, "could not find KNOWN_SPOKEN_KINDS const in types.ts"
    found = set(re.findall(r'"([^"]*)"', block.group(1)))
    assert found == _expected(), (
        f"types.ts drift: extra={found - _expected()}, "
        f"missing={_expected() - found}"
    )
