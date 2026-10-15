"""The Today page and the task store speak one vocabulary (AP-4).

``src/types/today.ts`` repeats the store's priorities, statuses, views and
limits for the page; a value added on one side only would let the page send
what the store refuses, or hide what it returns.
"""

from __future__ import annotations

import re
from pathlib import Path

from jarvis.today.store import NOTES_MAX_CHARS, PRIORITIES, STATUSES, TITLE_MAX_CHARS, VIEWS

TYPES_TS = Path(__file__).resolve().parents[3] / "jarvis/ui/web/frontend/src/types/today.ts"


def _array(name: str, text: str) -> tuple[str, ...]:
    block = re.search(rf"export const {name} = \[(.*?)\] as const", text, re.DOTALL)
    assert block, f"{name} not found in {TYPES_TS.name}"
    return tuple(re.findall(r'"([^"]+)"', block.group(1)))


def _number(name: str, text: str) -> int:
    match = re.search(rf"export const {name} = (\d+);", text)
    assert match, f"{name} not found in {TYPES_TS.name}"
    return int(match.group(1))


def test_the_page_uses_the_stores_vocabulary_in_the_same_order() -> None:
    text = TYPES_TS.read_text(encoding="utf-8")
    assert _array("TASK_PRIORITIES", text) == PRIORITIES
    assert _array("TASK_STATUSES", text) == STATUSES
    assert _array("TASK_VIEWS", text) == VIEWS


def test_the_pages_input_limits_are_the_stores() -> None:
    text = TYPES_TS.read_text(encoding="utf-8")
    assert _number("TASK_TITLE_MAX_CHARS", text) == TITLE_MAX_CHARS
    assert _number("TASK_NOTES_MAX_CHARS", text) == NOTES_MAX_CHARS
