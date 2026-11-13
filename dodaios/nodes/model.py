"""One node: what it is, what it holds, and where its page lives."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Final

#: The run-directory infix that names a node; the frontend matches it.
SLUG_INFIX: Final[str] = "__node__"
#: Marker kind of a node's run directory (``missions/standalone_run``).
MARKER_KIND: Final[str] = "node"
STATE_FILE: Final[str] = "node.json"
HISTORY_DIR: Final[str] = "history"
PAGE_DIR: Final[tuple[str, ...]] = ("tasks", "node", "artifacts", "files")


@dataclass(frozen=True)
class Node:
    """One node and the state of its upkeep.

    ``spec`` is the content in the type's own grammar, already normalized by
    the type's ``normalize``; the page on disk is always rendered from it.
    """

    id: str
    type: str
    title: str
    spec: dict[str, Any]
    slug: str
    page_path: str
    """Posix path inside the run, as ``/api/outputs/{slug}/artifacts`` lists it."""
    created_at: float
    updated_at: float
    version: int = 1
    """Counts content revisions; the previous ones are kept for ``revert``."""
    language: str = "en"
    rendered: int = 0
    """The renderer revision the page on disk was written with."""
    track: str = ""
    """The standing instruction of a kept-current node: what each refresh reads."""
    every_minutes: int = 0
    task_id: str = ""
    refreshing: bool = False
    note: str = ""
    """A short line from the last refresh (why nothing could be read, …)."""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def visual_id(self) -> str:
        """``slug::path`` — the stage's address of this node's page."""
        return f"{self.slug}::{self.page_path}"

    @property
    def page_url(self) -> str:
        return f"/api/outputs/{self.slug}/files/{self.page_path}/page"

    def state(self) -> dict[str, Any]:
        """What the state file holds (no derived fields)."""
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "spec": copy.deepcopy(self.spec),
            "slug": self.slug,
            "page_path": self.page_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "language": self.language,
            "rendered": self.rendered,
            "track": self.track,
            "every_minutes": self.every_minutes,
            "task_id": self.task_id,
            "refreshing": self.refreshing,
            "note": self.note,
            "extra": copy.deepcopy(self.extra),
        }

    def to_dict(self, *, with_spec: bool = True) -> dict[str, Any]:
        """The node as the tool and the routes hand it out."""
        data = self.state()
        if not with_spec:
            data.pop("spec")
        data.pop("extra")
        data.pop("rendered")
        data["visual_id"] = self.visual_id
        data["page_url"] = self.page_url
        return data


def node_from_state(data: dict[str, Any]) -> Node:
    """A node from its state file. Raises ``KeyError``/``TypeError``/``ValueError``
    on a file that is not one."""
    spec = data.get("spec")
    extra = data.get("extra")
    return Node(
        id=str(data["id"]),
        type=str(data["type"]),
        title=str(data.get("title") or ""),
        spec=spec if isinstance(spec, dict) else {},
        slug=str(data.get("slug") or ""),
        page_path=str(data.get("page_path") or ""),
        created_at=float(data.get("created_at") or 0.0),
        updated_at=float(data.get("updated_at") or 0.0),
        version=max(1, int(data.get("version") or 1)),
        language=str(data.get("language") or "en"),
        rendered=int(data.get("rendered") or 0),
        track=str(data.get("track") or ""),
        every_minutes=int(data.get("every_minutes") or 0),
        task_id=str(data.get("task_id") or ""),
        refreshing=bool(data.get("refreshing")),
        note=str(data.get("note") or ""),
        extra=extra if isinstance(extra, dict) else {},
    )


__all__ = [
    "HISTORY_DIR",
    "MARKER_KIND",
    "PAGE_DIR",
    "SLUG_INFIX",
    "STATE_FILE",
    "Node",
    "node_from_state",
]
