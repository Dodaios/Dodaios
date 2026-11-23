"""Message tasks: real messages of the person, and which stored memory each one needs.

Most messages a person sends need no memory at all, and a recall that brings
something up for every one of them wastes prompt on each. Only the person's
real messages show that mix. So a model is given a batch of them, each with
the stored memories a generous search finds for it (not the ones the assistant
always has in mind), and says for each message which of those memories it
needs to answer or act, or none.

One model's word is not the truth. Every batch is asked twice, with the
candidates in the opposite order and under other short names, and a message
becomes a task only when both answers name the same memories. A message the
two answers disagree on is left out for good.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from dodaios.memory.learning.guard import contains_secret, hidden_characters
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.models import Memory
from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi import overlay as overlays
from dodaios.rsi.bench.model import Domain, Source, Task, task_id

from .world import LIVE_WORLD

__all__ = [
    "BATCH",
    "SYSTEM",
    "Candidate",
    "agreed",
    "build_prompt",
    "candidates_for",
    "key_of",
    "parse",
    "task_from",
    "usable",
]

#: Messages per model call. Real messages are the scarce, telling kind of task, so a
#: call takes as many as a model labels reliably in one go.
BATCH: Final[int] = 16
#: Stored memories offered per message.
_CANDIDATES: Final[int] = 8
_MIN_WORDS: Final[int] = 3
_MAX_WORDS: Final[int] = 60

SYSTEM: Final = (
    "You label messages a person sent to their personal assistant. For each "
    "message you get stored facts about that person which a search found. Decide "
    "which of these facts the assistant NEEDS in order to answer the message or to "
    "do what it asks. Most messages need none: a fact that merely shares a word "
    "or a topic with the message is not needed. Name a fact only when the "
    "assistant could not answer correctly without it. "
    'Answer with JSON only: [{"n": <message number>, "needs": ["<fact name>", ...]}], '
    "one entry per message, with an empty list when no fact is needed."
)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Candidate:
    """A real message and the memories that could matter for it."""

    key: str
    text: str
    memories: tuple[Memory, ...]


def key_of(text: str) -> str:
    """A stable key for a message: the same words asked again are the same message."""
    normal = _SPACE.sub(" ", text.casefold()).strip()
    return hashlib.sha256(normal.encode()).hexdigest()[:16]


def usable(text: str) -> bool:
    """Whether a message can become a task at all."""
    words = text.split()
    if not _MIN_WORDS <= len(words) <= _MAX_WORDS or text.lstrip().startswith("/"):
        return False
    return not (hidden_characters(text) or contains_secret(text))


def candidates_for(vault: MemoryVault, text: str, in_mind: frozenset[str]) -> tuple[Memory, ...]:
    """The stored memories a generous search finds for ``text``, with the shipped values.

    The shipped values on purpose: what is offered to the labeller must not
    depend on what the assistant has learned, or the tasks would be shaped by
    the very thing they are meant to judge.
    """
    words = [
        w
        for w in re.findall(r"\w+", text.casefold())
        if len(w) > 2 and w not in vault_runtime._STOPWORDS
    ]
    if not words:
        return ()
    with overlays.active(overlays.FACTORY):
        hits = vault.search(" ".join(words), limit=_CANDIDATES * 2)
    found = [h.memory for h in hits if h.memory.id not in in_mind]
    return tuple(m for m in found if m.sensitivity != "sensitive")[:_CANDIDATES]


def _names(candidate: Candidate, flip: bool) -> dict[str, str]:
    """Short names for a message's memories: ``f1`` ... in one order, ``g1`` ... in the other."""
    ordered = list(reversed(candidate.memories)) if flip else list(candidate.memories)
    letter = "g" if flip else "f"
    return {f"{letter}{index}": memory.id for index, memory in enumerate(ordered, 1)}


def build_prompt(batch: Sequence[Candidate], *, flip: bool = False) -> str:
    """The batch as the labeller sees it. ``flip`` is the second asking."""
    blocks: list[str] = []
    for number, candidate in enumerate(batch, 1):
        by_id = {m.id: m for m in candidate.memories}
        facts = {name: by_id[mid].text for name, mid in _names(candidate, flip).items()}
        blocks.append(
            f"Message {number}: {candidate.text}\n"
            f"Facts: {json.dumps(facts, ensure_ascii=False)}"
        )
    return "\n\n".join(blocks)


def parse(
    text: str, batch: Sequence[Candidate], *, flip: bool = False
) -> dict[str, frozenset[str]]:
    """Message key -> ids of the memories the answer says the message needs.

    An entry that cannot be read, or that names a fact which was not offered,
    is left out.
    """
    cleaned = _FENCE.sub("", (text or "").strip())
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(cleaned[start : end + 1])
    except ValueError:
        return {}
    out: dict[str, frozenset[str]] = {}
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("needs"), list):
            continue
        try:
            candidate = batch[int(item["n"]) - 1]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if int(item["n"]) < 1:
            continue
        names = _names(candidate, flip)
        needs = [str(name) for name in item["needs"]]
        if any(name not in names for name in needs):
            continue  # it named a fact that was not offered: the entry cannot be trusted
        out[candidate.key] = frozenset(names[name] for name in needs)
    return out


def agreed(
    first: dict[str, frozenset[str]], second: dict[str, frozenset[str]]
) -> dict[str, frozenset[str]]:
    """The messages both askings labelled the same."""
    return {key: needs for key, needs in first.items() if second.get(key) == needs}


def task_from(candidate: Candidate, needs: frozenset[str]) -> Task:
    return Task(
        id=task_id(Domain.RECALL, Source.MADE, f"message:{candidate.key}"),
        domain=Domain.RECALL,
        source=Source.MADE,
        group=f"message:{candidate.key}",
        payload={"query": candidate.text, "world": LIVE_WORLD, "style": "message"},
        check={"gold": sorted(needs), "stale": []},
    )
