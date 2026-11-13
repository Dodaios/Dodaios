"""Read the browser model's structured reply even when it is wrapped in prose.

Browser-Use expects the model to answer with exactly one JSON object
(``AgentOutput``). Models reached through Dodaios' own providers have no
structured-output mode here, so a reply can come back as a fenced code block,
with a sentence in front of the JSON, or as prose only. Each unreadable reply
used to cost a whole agent step and counted as a failure; three in a row
ended the run. This module finds the JSON object inside such a reply.

It runs inside the isolated browser runtime (``live_runner.py`` imports it as
a sibling file), so it must not import anything from Dodaios.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

log = logging.getLogger(__name__)

# A second request after a reply without a usable JSON object.
REASK = (
    "Your last reply could not be used: it was not one JSON object that matches the "
    "required schema. Reply again with ONLY that JSON object: no text before or after "
    "it and no code fence. If you cannot continue, use the done action with "
    "success=false and say why in its text."
)

_FENCE = re.compile(r"```[a-zA-Z0-9_-]*[ \t]*\r?\n?(.*?)```", re.S)
# Objects tried per reply; a reply is one model turn, not a document.
_MAX_OBJECTS = 20


def json_candidates(text: str) -> Iterator[str]:
    """The reply itself, each fenced block, then each JSON object in the text."""
    stripped = (text or "").strip()
    if not stripped:
        return
    seen: set[str] = set()

    def fresh(candidate: str) -> bool:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            return False
        seen.add(candidate)
        return True

    if fresh(stripped):
        yield stripped
    for block in _FENCE.findall(stripped):
        if fresh(block):
            yield block.strip()
    decoder = json.JSONDecoder()
    position = stripped.find("{")
    found = 0
    while position != -1 and found < _MAX_OBJECTS:
        try:
            value, end = decoder.raw_decode(stripped, position)
        except ValueError:  # this brace starts no JSON object; try the next one
            position = stripped.find("{", position + 1)
            continue
        if isinstance(value, dict):
            found += 1
            candidate = stripped[position:end]
            if fresh(candidate):
                yield candidate
        position = stripped.find("{", end)


def parse_reply(text: str, output_format: Any) -> Any:
    """``output_format`` validated from the first usable JSON object in ``text``.

    Raises the first validation error when no candidate fits, so the caller
    reports the same error Browser-Use would have shown.
    """
    first_error: Exception | None = None
    for candidate in json_candidates(text):
        try:
            return output_format.model_validate_json(candidate)
        except ValueError as exc:  # a pydantic ValidationError; raised below if nothing fits
            log.debug("Browser model reply candidate did not fit the schema: %s", exc)
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error
    raise ValueError("The browser model returned an empty reply")
