"""Question tasks: for a memory, messages the person might send that need exactly it.

One model call takes a batch of memories and a few of the person's real
messages as examples of how they write. It answers with two messages per
memory. Python then decides what is kept; the model's word is not enough:

* the message must share a topic word with its memory (a keyword search can
  never find a memory that shares no word, so such a task would only measure
  the search's kind, not its tuning);
* it must not be the memory said again (that would be too easy to be a task);
* it must be short, hold no credential-shaped text and no hidden characters;
* it must not fit a sibling memory of the batch better than its own.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, Final

from dodaios.memory.learning.guard import contains_secret, hidden_characters
from dodaios.memory.vault import lessons
from dodaios.memory.vault.models import Memory
from dodaios.rsi.bench.model import Domain, Source, Task, task_id

from .world import LIVE_WORLD

__all__ = ["ASKED", "BATCH", "PER_MEMORY", "SYSTEM", "build_prompt", "parse", "tasks_from"]

#: Memories per model call.
BATCH: Final[int] = 12
#: Messages asked for per memory.
ASKED: Final[int] = 2
#: Kept at most per memory. One is enough: a question shares words with its memory by
#: construction, so the recall nearly always finds it. Questions guard against a change
#: that breaks the recall; what tells a good change from a bad one are the real messages.
PER_MEMORY: Final[int] = 1
_MAX_WORDS: Final[int] = 30
#: Above this overlap a message is the memory said again.
_TOO_CLOSE: Final[float] = 0.9

SYSTEM: Final = (
    "You write test messages for a personal assistant's memory. You get facts the "
    "assistant has stored about one person, and a few messages that person really "
    "sent, as examples of how they write. For each fact write "
    f"{ASKED} different messages this person might send to the assistant in "
    "the middle of a day, for which the assistant needs exactly that fact: a "
    "question, or a task that cannot be done right without it. Write them in the "
    "language and the tone of the examples. Do not repeat the fact's sentence; ask "
    "about it or rely on it, but keep at least one of its meaningful words. A "
    "message must not be answered just as well by another fact in the list. "
    'Answer with JSON only: [{"id": "<fact id>", "messages": ["...", "..."]}].'
)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def build_prompt(memories: Sequence[Memory], examples: Sequence[str]) -> str:
    facts = [{"id": m.id, "fact": m.text} for m in memories]
    lines = ["Facts:", json.dumps(facts, ensure_ascii=False, indent=1)]
    if examples:
        lines += ["", "Messages this person sent (style only, do not reuse them):"]
        lines += [f"- {text}" for text in examples]
    return "\n".join(lines)


def parse(text: str) -> list[dict[str, Any]]:
    """The model's answer as a list of ``{"id", "messages"}``; ``[]`` when it is not that."""
    cleaned = _FENCE.sub("", (text or "").strip())
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(cleaned[start : end + 1])
    except ValueError:
        return []
    out: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and isinstance(item.get("messages"), list):
            messages = [str(m).strip() for m in item["messages"] if isinstance(m, str)]
            out.append({"id": str(item.get("id") or ""), "messages": messages})
    return out


def _document(memory: Memory) -> str:
    return f"{memory.text} {memory.source.get('trigger') or ''}"


def _acceptable(message: str, memory: Memory, siblings: Sequence[Memory]) -> bool:
    if not message or len(message.split()) > _MAX_WORDS:
        return False
    if hidden_characters(message) or contains_secret(message):
        return False
    own = lessons.words(message) & lessons.words(_document(memory))
    if not own:
        return False
    if lessons.similarity(message, memory.text) >= _TOO_CLOSE and len(own) > 2:
        return False
    return all(
        len(lessons.words(message) & lessons.words(_document(other))) <= len(own)
        for other in siblings
        if other.id != memory.id
    )


def tasks_from(answer: Sequence[dict[str, Any]], memories: Sequence[Memory]) -> list[Task]:
    """The tasks a model's answer gives for ``memories``, after Python's own checks."""
    known = {m.id: m for m in memories}
    tasks: list[Task] = []
    for item in answer:
        memory = known.get(item["id"])
        if memory is None:
            continue
        kept = 0
        for message in dict.fromkeys(item["messages"]):  # the same message twice counts once
            if kept >= PER_MEMORY or not _acceptable(message, memory, memories):
                continue
            kept += 1
            tasks.append(
                Task(
                    id=task_id(Domain.RECALL, Source.MADE, f"question:{memory.id}:{kept}"),
                    domain=Domain.RECALL,
                    source=Source.MADE,
                    group=f"memory:{memory.id}",
                    payload={"query": message, "world": LIVE_WORLD, "style": "question"},
                    check={"gold": [memory.id], "stale": []},
                )
            )
    return tasks
