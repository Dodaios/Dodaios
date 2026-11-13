"""Where nodes live: one run directory per node, in the run archive.

A node is an ordinary run in the archive, so everything that already knows
runs (the stage that shows a page, the Downloads mirror, the cleanup sweep,
sharing) sees it without a second store::

    <outputs_root>/<stamp>__node__<id>/
        .standalone-run.json                    (kind "node")
        node.json                               (type, title, spec, upkeep)
        history/v<N>.json                       (earlier specs, newest kept)
        tasks/node/artifacts/files/<file>.html  (the page, rendered from spec)

The state file and the history sit outside ``tasks/*/artifacts/files`` on
purpose: the Outputs allowlist never lists them as deliverables.

The page is always REWRITTEN from the spec, never edited: a revision changes
the spec (:mod:`.patch`), the type's renderer (:mod:`.kinds`) draws it again.
That is also how nodes stay maintained: when a renderer improves
(``RENDER_REVISION``), a node's page is rewritten the next time it is read.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from dodaios.nodes.kinds import RENDER_REVISION, kind_of
from dodaios.nodes.model import (
    HISTORY_DIR,
    MARKER_KIND,
    PAGE_DIR,
    SLUG_INFIX,
    STATE_FILE,
    Node,
    node_from_state,
)
from dodaios.nodes.patch import apply_changes
from dodaios.nodes.types import MAX_SPEC_BYTES, MAX_TITLE_CHARS, NodeError, node_type

log = logging.getLogger(__name__)

#: Earlier specs kept per node, so "undo that" works a few steps back.
MAX_HISTORY: Final[int] = 12
MAX_NOTE_CHARS: Final[int] = 300
MAX_TRACK_CHARS: Final[int] = 2_000
#: Refresh cadence bounds, in minutes (the same as a living page's): a refresh
#: is a whole assistant turn, and a week is the ceiling of "kept current".
MIN_EVERY_MINUTES: Final[int] = 15
MAX_EVERY_MINUTES: Final[int] = 7 * 24 * 60
DEFAULT_EVERY_MINUTES: Final[int] = 180

_REPLACE_ATTEMPTS: Final[int] = 6
_ID_RE: Final = re.compile(r"^[0-9a-f]{12}$")
_FILE_RE: Final = re.compile(r"[^a-z0-9]+")
_VERSION_RE: Final = re.compile(r"^v(\d+)\.json$")


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def clamp_every(minutes: Any) -> int:
    """A refresh cadence inside the allowed range."""
    try:
        value = int(minutes)
    except (TypeError, ValueError):  # no usable number: the default cadence
        return DEFAULT_EVERY_MINUTES
    return max(MIN_EVERY_MINUTES, min(MAX_EVERY_MINUTES, value))


def new_node_id() -> str:
    return uuid.uuid4().hex[:12]


def _file_name(title: str) -> str:
    stem = _FILE_RE.sub("-", title.lower()).strip("-")[:48] or "node"
    return f"{stem}.html"


def outputs_root() -> Path:
    """The archive root new nodes are written to."""
    from dodaios.core.paths import repo_root
    from dodaios.missions.isolation.worktree import resolve_outputs_root

    return resolve_outputs_root(repo_root())


def _readable_roots() -> tuple[Path, ...]:
    from dodaios.core.paths import repo_root
    from dodaios.missions.isolation.worktree import resolve_readable_outputs_roots

    return resolve_readable_outputs_roots(repo_root())


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=".node-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        # Windows refuses a replace while another reader (the page's frame, a
        # virus scanner) holds the target for a moment; try a few times.
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(staged, target)
                break
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def _checked_spec(type_name: str, spec: Any) -> dict[str, Any]:
    """The spec as the type's renderer accepts it, within the size bound."""
    if not isinstance(spec, dict):
        raise NodeError("'spec' must be an object in the type's grammar (ask for the guide).")
    clean = kind_of(type_name).normalize(spec)
    if len(json.dumps(clean, ensure_ascii=False)) > MAX_SPEC_BYTES:
        raise NodeError("The node is too large; split it into several nodes.")
    return clean


class NodeStore:
    """Reads and writes nodes under one or more archive roots.

    ``root`` is where new nodes go; ``read_roots`` are searched for existing
    ones (the canonical root first). Plain files, no database: a node, its
    page and its history live and die with their run directory.
    """

    def __init__(self, root: Path | None = None, read_roots: tuple[Path, ...] | None = None):
        self._root = root
        self._read_roots = read_roots

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else outputs_root()

    def _roots(self) -> tuple[Path, ...]:
        if self._read_roots is not None:
            return self._read_roots
        if self._root is not None:
            return (self._root,)
        return _readable_roots()

    def dir_of(self, node_id: str) -> Path | None:
        """The run directory of ``node_id``, or ``None``."""
        if not _ID_RE.match(node_id or ""):
            return None
        suffix = f"{SLUG_INFIX}{node_id}"
        for root in self._roots():
            try:
                for entry in root.iterdir():
                    if entry.name.endswith(suffix) and entry.is_dir():
                        return entry
            except OSError:  # a missing or unreadable root holds no nodes; try the next
                continue
        return None

    # ------------------------------------------------------------- writing

    def _write(self, run_dir: Path, node: Node) -> Node:
        """Render ``node`` and write its page and state. Returns the node as written."""
        page = kind_of(node.type).render(node)
        stamped = replace(node, rendered=RENDER_REVISION)
        _atomic_write(run_dir / stamped.page_path, page)
        _atomic_write(
            run_dir / STATE_FILE, json.dumps(stamped.state(), ensure_ascii=False, indent=1)
        )
        return stamped

    def _keep_version(self, run_dir: Path, node: Node) -> None:
        """Put the node's current spec into its history before it changes."""
        history = run_dir / HISTORY_DIR
        snapshot = {"version": node.version, "title": node.title, "spec": node.spec,
                    "updated_at": node.updated_at}
        try:
            _atomic_write(
                history / f"v{node.version}.json", json.dumps(snapshot, ensure_ascii=False)
            )
            kept = sorted(
                (int(match.group(1)), entry)
                for entry in history.iterdir()
                if (match := _VERSION_RE.match(entry.name))
            )
            for _, entry in kept[:-MAX_HISTORY]:
                entry.unlink(missing_ok=True)
        except OSError:
            # History is a convenience; a revision must not fail because an
            # old snapshot could not be written or trimmed.
            log.warning("node %s: history not written", node.id, exc_info=True)

    def create(
        self,
        *,
        type: str,  # noqa: A002 — the field's name everywhere a node is described
        title: str,
        spec: Any = None,
        language: str = "en",
        now: float | None = None,
    ) -> Node:
        """Write a new node. ``spec=None`` starts from the type's starter."""
        from dodaios.missions.standalone_run import write_marker

        type_name = node_type(type)
        clean_title = _clean(title, MAX_TITLE_CHARS)
        if not clean_title:
            raise NodeError("'title' must name the node.")
        lang = _clean(language, 8) or "en"
        kind = kind_of(type_name)
        clean_spec = _checked_spec(
            type_name, kind.starter(clean_title, lang) if spec is None else spec
        )
        stamp = now if now is not None else time.time()
        node_id = new_node_id()
        slug = time.strftime("%Y%m%dT%H%M%S", time.gmtime(stamp)) + SLUG_INFIX + node_id
        node = Node(
            id=node_id,
            type=type_name,
            title=clean_title,
            spec=clean_spec,
            slug=slug,
            page_path="/".join((*PAGE_DIR, _file_name(clean_title))),
            created_at=stamp,
            updated_at=stamp,
            language=lang,
        )
        run_dir = self.root / slug
        write_marker(run_dir, kind=MARKER_KIND, title=clean_title)
        written = self._write(run_dir, node)
        log.info("node %s created (%s)", node_id, type_name)
        return written

    def update(
        self,
        node_id: str,
        *,
        title: str | None = None,
        spec: Any = None,
        changes: Any = None,
        note: str | None = None,
        now: float | None = None,
    ) -> Node:
        """Revise a node: a new ``spec``, or ``changes`` to the one it has,
        and/or a new ``title``. The earlier spec goes into the history.

        ``note`` records one line from a refresh (shown on a kept-current
        node's page); with nothing else given it only sets that line and the
        time of the refresh.
        """
        node = self._require(node_id)
        run_dir = self.dir_of(node_id)
        assert run_dir is not None  # _require found it
        if spec is not None and changes is not None:
            raise NodeError("Send either 'spec' (a rewrite) or 'changes' (edits), not both.")
        new_spec = node.spec
        if spec is not None:
            new_spec = _checked_spec(node.type, spec)
        elif changes is not None:
            new_spec = _checked_spec(node.type, apply_changes(node.spec, changes))
        new_title = node.title if title is None else _clean(title, MAX_TITLE_CHARS)
        if not new_title:
            raise NodeError("'title' must name the node.")
        revised = new_spec != node.spec or new_title != node.title
        if not revised and note is None:
            if spec is not None or changes is not None:
                raise NodeError(
                    "That left the node exactly as it was. A field the type does not know "
                    "is dropped, and a value over a limit is cut back: check the path and "
                    "the value against the type's guide (operation 'guide')."
                )
            raise NodeError("Nothing to change: give 'spec', 'changes' or 'title'.")
        if revised:
            self._keep_version(run_dir, node)
        updated = replace(
            node,
            title=new_title,
            spec=new_spec,
            version=node.version + 1 if revised else node.version,
            note=node.note if note is None else _clean(note, MAX_NOTE_CHARS),
            updated_at=now if now is not None else time.time(),
        )
        if new_title != node.title:
            self._relabel(run_dir, new_title)
        return self._write(run_dir, updated)

    def revert(self, node_id: str, *, now: float | None = None) -> Node:
        """Put the previous version back (and keep the current one in history)."""
        node = self._require(node_id)
        run_dir = self.dir_of(node_id)
        assert run_dir is not None
        history = run_dir / HISTORY_DIR
        try:
            kept = sorted(
                (int(match.group(1)), entry)
                for entry in history.iterdir()
                if (match := _VERSION_RE.match(entry.name))
            )
        except OSError:  # no history directory: the node was never revised
            kept = []
        while kept:
            _, entry = kept.pop()
            try:
                snapshot = json.loads(entry.read_text(encoding="utf-8"))
                spec = _checked_spec(node.type, snapshot["spec"])
            except (OSError, ValueError, KeyError, TypeError):
                log.warning("node %s: history entry %s unreadable", node_id, entry.name)
                continue
            self._keep_version(run_dir, node)
            entry.unlink(missing_ok=True)
            title = _clean(snapshot.get("title"), MAX_TITLE_CHARS) or node.title
            restored = replace(
                node,
                title=title,
                spec=spec,
                version=node.version + 1,
                updated_at=now if now is not None else time.time(),
            )
            if title != node.title:
                self._relabel(run_dir, title)
            return self._write(run_dir, restored)
        raise NodeError("This node has no earlier version to go back to.")

    def duplicate(self, node_id: str, *, title: str = "", now: float | None = None) -> Node:
        """A new node with the same content (no upkeep, no history)."""
        node = self._require(node_id)
        return self.create(
            type=node.type,
            title=_clean(title, MAX_TITLE_CHARS) or node.title,
            spec=node.spec,
            language=node.language,
            now=now,
        )

    def delete(self, node_id: str) -> bool:
        """Remove the node, its page and its history. True when it existed."""
        run_dir = self.dir_of(node_id)
        if run_dir is None:
            return False
        shutil.rmtree(run_dir)
        log.info("node %s deleted", node_id)
        return True

    def set_upkeep(
        self,
        node_id: str,
        *,
        track: str | None = None,
        every_minutes: Any = None,
        refreshing: bool | None = None,
        task_id: str | None = None,
    ) -> Node:
        """Record how the node is kept current (the refresh routine's state)."""
        node = self._require(node_id)
        run_dir = self.dir_of(node_id)
        assert run_dir is not None
        updated = replace(
            node,
            track=node.track if track is None else " ".join(str(track).split())[:MAX_TRACK_CHARS],
            every_minutes=(
                node.every_minutes if every_minutes is None else clamp_every(every_minutes)
            ),
            refreshing=node.refreshing if refreshing is None else bool(refreshing),
            task_id=node.task_id if task_id is None else str(task_id),
        )
        return self._write(run_dir, updated)

    def _relabel(self, run_dir: Path, title: str) -> None:
        from dodaios.missions.standalone_run import write_marker

        try:
            write_marker(run_dir, kind=MARKER_KIND, title=title)
        except OSError:
            # The marker's label is what the run list shows; the node itself
            # carries the new title either way.
            log.warning("node marker not relabelled: %s", run_dir, exc_info=True)

    # ------------------------------------------------------------- reading

    def _read(self, run_dir: Path) -> Node | None:
        try:
            data = json.loads((run_dir / STATE_FILE).read_text(encoding="utf-8"))
            node = node_from_state(data)
            node_type(node.type)
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("node state unreadable: %s", run_dir, exc_info=True)
            return None
        if node.rendered < RENDER_REVISION:
            try:
                # The renderer changed since this page was written: draw the
                # node again so it gets the current look.
                node = self._write(run_dir, replace(node, spec=_checked_spec(node.type, node.spec)))
            except Exception:  # noqa: BLE001 — one node's renderer fault must not hide the others
                log.warning("node %s: page not redrawn", node.id, exc_info=True)
        return node

    def get(self, node_id: str) -> Node | None:
        run_dir = self.dir_of(node_id)
        return self._read(run_dir) if run_dir is not None else None

    def _require(self, node_id: str) -> Node:
        node = self.get(node_id)
        if node is None:
            raise NodeError(f"No node with id {node_id!r}.")
        return node

    def by_slug(self, slug: str) -> Node | None:
        _, sep, node_id = (slug or "").rpartition(SLUG_INFIX)
        return self.get(node_id) if sep else None

    def find(self, reference: str) -> Node | None:
        """A node by id, by slug, or by its exact title (newest first)."""
        ref = (reference or "").strip()
        if not ref:
            return None
        found = self.get(ref) or self.by_slug(ref)
        if found is not None:
            return found
        wanted = ref.casefold()
        for node in self.list_nodes():
            if node.title.casefold() == wanted:
                return node
        return None

    def list_nodes(self) -> list[Node]:
        """Every node, most recently changed first."""
        nodes: dict[str, Node] = {}
        for root in self._roots():
            try:
                entries = [e for e in root.iterdir() if SLUG_INFIX in e.name and e.is_dir()]
            except OSError:  # a missing or unreadable root holds no nodes
                continue
            for entry in entries:
                node_id = entry.name.rpartition(SLUG_INFIX)[2]
                if node_id in nodes or not _ID_RE.match(node_id):
                    continue
                node = self._read(entry)
                if node is not None:
                    nodes[node_id] = node
        return sorted(nodes.values(), key=lambda n: n.updated_at, reverse=True)


__all__ = [
    "DEFAULT_EVERY_MINUTES",
    "MAX_EVERY_MINUTES",
    "MAX_HISTORY",
    "MIN_EVERY_MINUTES",
    "NodeStore",
    "clamp_every",
    "new_node_id",
    "outputs_root",
]
