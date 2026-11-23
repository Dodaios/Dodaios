"""The seed suite: benchmark tasks that ship with the app.

A new installation has no past work to build tasks from, CI needs a benchmark
that does not depend on anyone's data, and a published number must be one that
everybody can reproduce. The seed suite is that: the memories of one invented
person and the messages she might send (``seed/recall.json``).

It never decides anything about a real installation. A value tuned on the
invented person's memories says nothing about the real person's, so a change
to the live assistant needs evidence from that person's own tasks; the seed
suite is where the mechanism is tried and where the public numbers come from.

The suite is data, and it may be corrected between versions. Each task keeps
its id (taken from its key); its content hash changes when its text does, so
only the results measured on the old text go stale.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from dodaios.memory.vault.store import MemoryVault

from .model import Domain, Source, Task, task_id

__all__ = ["SEED_WORLD", "SeedError", "SeedWorld", "build_world", "recall_data", "recall_tasks"]

#: Name of the world the seed tasks run in (``Task.payload["world"]``).
SEED_WORLD: Final = "seed"
_RECALL_FILE: Final = Path(__file__).with_name("seed") / "recall.json"
_KINDS: Final = frozenset(
    {"profile", "preference", "relationship", "project", "procedural", "episode", "reference"}
)
_NOTES: Final = frozenset({"lesson", "how_to"})


class SeedError(ValueError):
    """The seed file does not have the shape the benchmark needs."""


@lru_cache(maxsize=1)
def recall_data() -> dict[str, Any]:
    """The recall seed file, checked. Raises :class:`SeedError` when it is malformed."""
    data = json.loads(_RECALL_FILE.read_text(encoding="utf-8"))
    memories, queries = data.get("memories"), data.get("queries")
    if not isinstance(memories, list) or not isinstance(queries, list) or not data.get("now"):
        raise SeedError("the seed file needs 'now', 'memories' and 'queries'")
    keys: set[str] = set()
    for memory in memories:
        key = str(memory.get("key") or "")
        if not key or key in keys:
            raise SeedError(f"memory key missing or used twice: {key!r}")
        keys.add(key)
        if memory.get("kind") not in _KINDS:
            raise SeedError(f"{key}: unknown kind {memory.get('kind')!r}")
        if not str(memory.get("text") or "").strip() or not memory.get("cluster"):
            raise SeedError(f"{key}: a memory needs text and a cluster")
        note = str(memory.get("note") or "")
        if (memory["kind"] == "procedural") != (note in _NOTES):
            raise SeedError(f"{key}: exactly the rules for the assistant carry a note")
    seen: set[str] = set()
    for query in queries:
        key = str(query.get("key") or "")
        if not key or key in seen:
            raise SeedError(f"query key missing or used twice: {key!r}")
        seen.add(key)
        gold = query.get("gold")
        if not isinstance(gold, list) or any(g not in keys for g in gold):
            raise SeedError(f"{key}: gold names a memory that does not exist")
        stale = query.get("stale") or []
        if any(s not in keys or s in gold for s in stale):
            raise SeedError(f"{key}: stale names a memory that does not exist, or a gold one")
        if not str(query.get("text") or "").strip():
            raise SeedError(f"{key}: a query needs text")
    return data


def recall_tasks() -> list[Task]:
    """The seed tasks of the recall domain.

    The group of a task is the cluster of its first gold memory: memories of a
    cluster compete with each other, so every question about a cluster belongs
    into the same split. A message that needs no memory is its own group.
    """
    data = recall_data()
    cluster = {str(m["key"]): str(m["cluster"]) for m in data["memories"]}
    tasks: list[Task] = []
    for query in data["queries"]:
        key = str(query["key"])
        gold = [str(g) for g in query["gold"]]
        group = f"seed:{cluster[gold[0]]}" if gold else f"seed:none:{key}"
        tasks.append(
            Task(
                id=task_id(Domain.RECALL, Source.SEED, key),
                domain=Domain.RECALL,
                source=Source.SEED,
                group=group,
                payload={
                    "query": str(query["text"]),
                    "world": SEED_WORLD,
                    "style": str(query.get("style") or ""),
                    "hard": bool(query.get("hard")),
                },
                check={"gold": gold, "stale": [str(s) for s in query.get("stale") or ()]},
            )
        )
    return tasks


@dataclass(slots=True)
class SeedWorld:
    """The invented person's memory, built in RAM, with the ids its memories got."""

    vault: MemoryVault
    #: Seed key of a memory -> its id in :attr:`vault`.
    ids: dict[str, str]
    set_clock: Callable[[str], None]

    def close(self) -> None:
        self.vault.close()


def build_world(now: str | None = None) -> SeedWorld:
    """Build the seed memories into a fresh in-memory vault.

    Every memory is recorded at its own date; afterwards the vault's clock
    stands at ``now`` (the seed file's own date by default), so recency is the
    same on every machine and on every day the suite runs.
    """
    data = recall_data()
    clock = {"now": str(data["now"])}
    vault = MemoryVault(":memory:", clock=lambda: clock["now"])
    ids: dict[str, str] = {}
    for memory in sorted(data["memories"], key=lambda m: (str(m["recorded"]), str(m["key"]))):
        clock["now"] = f"{memory['recorded']}T12:00:00+00:00"
        source: dict[str, Any] = {}
        if memory.get("note"):
            source = {"note": memory["note"], "trigger": str(memory.get("trigger") or "")}
        written = vault.remember(
            str(memory["text"]),
            str(memory["kind"]),
            entities=[str(e) for e in memory.get("entities") or ()],
            origin="user",
            source=source,
            sensitivity="sensitive" if memory.get("sensitive") else "normal",
            pinned=bool(memory.get("pinned")),
        )
        if written.memory is None or written.action != "added":
            reason = written.reason or written.action
            raise SeedError(f"{memory['key']}: the vault did not store it ({reason})")
        ids[str(memory["key"])] = written.memory.id
    clock["now"] = now or str(data["now"])

    def set_clock(value: str) -> None:
        clock["now"] = value

    return SeedWorld(vault, ids, set_clock)
