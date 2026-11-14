"""Where nodes live: one run directory per node, in the run archive.

A node is an ordinary run in the archive, so everything that already knows
runs (the stage that shows a page, the Downloads mirror, the cleanup sweep,
sharing) sees it without a second store::

    <outputs_root>/<stamp>__node__<id>/
        .standalone-run.json                    (kind "node")
        node.json                               (type, title, spec, upkeep)
        history/v<N>.json                       (earlier specs, newest kept)
        board-files/<hash>                      (a whiteboard's pictures)
        tasks/node/artifacts/files/<file>.html  (the page, rendered from spec)

The state file and the history sit outside ``tasks/*/artifacts/files`` on
purpose: the Outputs allowlist never lists them as deliverables.

The page is always REWRITTEN from the spec, never edited: a revision changes
the spec (:mod:`.patch`), the type's renderer (:mod:`.kinds`) draws it again.
That is also how nodes stay maintained: when a renderer improves
(``RENDER_REVISION``), a node's page is rewritten the next time it is read.

A whiteboard is the one type the person edits whole, in the embedded editor:
its saves come through :meth:`NodeStore.merge_save_scene`, which joins them
with what the assistant drew meanwhile (:func:`~dodaios.nodes.board.scene.merge_scene`)
and keeps one history version per stretch of drawing instead of one per
save (an editor saves every second while the person draws). Changes to one
node are serialised by a per-node lock, so a save from the editor and an
edit from the assistant cannot overwrite each other.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from dodaios.nodes.board import files as board_files
from dodaios.nodes.board.scene import MAX_SCENE_BYTES, is_scene, merge_scene
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

#: The spec size of the types that may be larger than :data:`MAX_SPEC_BYTES`.
SPEC_BYTES_BY_TYPE: Final[dict[str, int]] = {"whiteboard": MAX_SCENE_BYTES}
#: The person's whiteboard saves within this many seconds of the previous
#: one share one history version, up to :data:`SAVE_STRETCH_SECONDS` in all:
#: "undo that" then goes back a stretch of drawing, not one stroke.
SAVE_COALESCE_SECONDS: Final[float] = 10 * 60
SAVE_STRETCH_SECONDS: Final[float] = 60 * 60

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
    limit = SPEC_BYTES_BY_TYPE.get(type_name, MAX_SPEC_BYTES)
    if len(json.dumps(clean, ensure_ascii=False)) > limit:
        raise NodeError("The node is too large; split it into several nodes.")
    return clean


def _legacy_board(type_name: str, spec: Any) -> bool:
    """Whether ``spec`` is a whiteboard in the older grammar (items and links)."""
    return (
        type_name == "whiteboard"
        and isinstance(spec, dict)
        and "items" in spec
        and not is_scene(spec)
    )


def _image_keeper(run_dir: Path) -> Callable[[str], tuple[str, str] | None]:
    """Keeps a picture of the older board grammar as a board file of ``run_dir``."""

    def keep(data_url: str) -> tuple[str, str] | None:
        try:
            return board_files.store_data_url(run_dir, data_url)
        except NodeError:  # a picture that cannot be kept becomes a labelled box
            log.info("board picture not kept in %s", run_dir.name)
            return None

    return keep


def _prepared(type_name: str, spec: Any, run_dir: Path) -> Any:
    """``spec`` with an older-grammar whiteboard turned into a scene whose
    pictures are kept in ``run_dir``; any other spec as it is."""
    if not _legacy_board(type_name, spec):
        return spec
    from dodaios.nodes.board.convert import legacy_to_scene

    return legacy_to_scene(spec, store_image=_image_keeper(run_dir))


def _scene_file_ids(spec: Any) -> set[str]:
    """The file ids a scene names: its file entries and its pictures."""
    if not isinstance(spec, dict):
        return set()
    ids = {key for key in spec.get("files") or {} if isinstance(key, str)}
    for element in spec.get("elements") or []:
        if isinstance(element, dict) and isinstance(element.get("fileId"), str):
            ids.add(element["fileId"])
    return ids


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_of(node_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(node_id)
        if lock is None:
            lock = _LOCKS[node_id] = threading.RLock()
        return lock


def _without_person_save(extra: dict[str, Any]) -> dict[str, Any]:
    """``extra`` without the mark of the person's last whiteboard save: any
    other revision starts a new history version for the next save."""
    if "last_save" not in extra:
        return extra
    return {key: value for key, value in extra.items() if key != "last_save"}


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

    @contextmanager
    def locked(self, node_id: str) -> Iterator[None]:
        """Hold the node while a read-change-write runs (re-entrant, per process).

        Inputs: ``node_id``. Use it around a change computed from the node's
        current spec (the whiteboard actions), so a concurrent save cannot
        land between the read and the write.
        """
        with _lock_of(node_id):
            yield

    # ------------------------------------------------------------- writing

    def _write(self, run_dir: Path, node: Node) -> Node:
        """Render ``node`` and write its page and state. Returns the node as written."""
        kind = kind_of(node.type)
        page = (
            kind.render_in_run(node, run_dir)
            if kind.render_in_run is not None
            else kind.render(node)
        )
        stamped = replace(node, rendered=RENDER_REVISION)
        _atomic_write(run_dir / stamped.page_path, page)
        _atomic_write(
            run_dir / STATE_FILE, json.dumps(stamped.state(), ensure_ascii=False, indent=1)
        )
        return stamped

    def _keep_version(self, run_dir: Path, node: Node) -> None:
        """Put the node's current spec into its history before it changes."""
        history = run_dir / HISTORY_DIR
        snapshot = {
            "version": node.version,
            "title": node.title,
            "spec": node.spec,
            "updated_at": node.updated_at,
        }
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
        stamp = now if now is not None else time.time()
        node_id = new_node_id()
        slug = time.strftime("%Y%m%dT%H%M%S", time.gmtime(stamp)) + SLUG_INFIX + node_id
        run_dir = self.root / slug
        raw = kind.starter(clean_title, lang) if spec is None else spec
        try:
            clean_spec = _checked_spec(type_name, _prepared(type_name, raw, run_dir))
        except BaseException:
            # An older board's pictures may already be kept; the node is not.
            if run_dir.is_dir() and not (run_dir / STATE_FILE).exists():
                shutil.rmtree(run_dir, ignore_errors=True)
            raise
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
        with self.locked(node_id):
            return self._update(
                node_id, title=title, spec=spec, changes=changes, note=note, now=now
            )

    def _update(
        self,
        node_id: str,
        *,
        title: str | None,
        spec: Any,
        changes: Any,
        note: str | None,
        now: float | None,
    ) -> Node:
        node = self._require(node_id)
        run_dir = self.dir_of(node_id)
        assert run_dir is not None  # _require found it
        if spec is not None and changes is not None:
            raise NodeError("Send either 'spec' (a rewrite) or 'changes' (edits), not both.")
        new_spec = node.spec
        if spec is not None:
            new_spec = _checked_spec(node.type, _prepared(node.type, spec, run_dir))
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
            extra=_without_person_save(node.extra) if revised else node.extra,
        )
        if new_title != node.title:
            self._relabel(run_dir, new_title)
        return self._write(run_dir, updated)

    def revert(self, node_id: str, *, now: float | None = None) -> Node:
        """Put the previous version back (and keep the current one in history)."""
        with self.locked(node_id):
            return self._revert(node_id, now=now)

    def _revert(self, node_id: str, *, now: float | None) -> Node:
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
                spec = _checked_spec(node.type, _prepared(node.type, snapshot["spec"], run_dir))
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
                extra=_without_person_save(node.extra),
            )
            if title != node.title:
                self._relabel(run_dir, title)
            return self._write(run_dir, restored)
        raise NodeError("This node has no earlier version to go back to.")

    def duplicate(self, node_id: str, *, title: str = "", now: float | None = None) -> Node:
        """A new node with the same content (no upkeep, no history)."""
        node = self._require(node_id)
        copy = self.create(
            type=node.type,
            title=_clean(title, MAX_TITLE_CHARS) or node.title,
            spec=node.spec,
            language=node.language,
            now=now,
        )
        source, target = self.dir_of(node_id), self.dir_of(copy.id)
        if node.type == "whiteboard" and source is not None and target is not None:
            # The copy's scene names the same pictures; draw its page with them.
            board_files.copy_all(source, target)
            copy = self._write(target, copy)
        return copy

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

    # ------------------------------------------------------------ whiteboards

    def _board(self, node_id: str) -> tuple[Node, Path]:
        node = self._require(node_id)
        if node.type != "whiteboard":
            raise NodeError(f"Node {node_id!r} is a {node.type} node, not a whiteboard.")
        run_dir = self.dir_of(node_id)
        assert run_dir is not None  # _require found it
        return node, run_dir

    def scene_of(self, node_id: str) -> tuple[Node, dict[str, Any]]:
        """A whiteboard node and its scene. Raises ``NodeError`` for another type."""
        node, run_dir = self._board(node_id)
        if is_scene(node.spec):
            return node, node.spec
        # Not converted yet (the conversion failed when the node was read).
        return node, _checked_spec(node.type, _prepared(node.type, node.spec, run_dir))

    def _save_scene(
        self, node: Node, run_dir: Path, clean: dict[str, Any], now: float | None
    ) -> Node:
        if clean == node.spec:
            return node
        stamp = now if now is not None else time.time()
        last = node.extra.get("last_save")
        since = stamp
        coalesce = False
        if isinstance(last, dict) and last.get("by") == "person":
            try:
                at = float(last["at"])
                since = float(last.get("since", at))
            except (KeyError, TypeError, ValueError):  # an unreadable mark starts a new stretch
                at = since = -math.inf
            coalesce = (
                0 <= stamp - at < SAVE_COALESCE_SECONDS and stamp - since < SAVE_STRETCH_SECONDS
            )
            if not coalesce:
                since = stamp
        if not coalesce:
            self._keep_version(run_dir, node)
        updated = replace(
            node,
            spec=clean,
            version=node.version + 1,
            updated_at=stamp,
            extra={**node.extra, "last_save": {"by": "person", "at": stamp, "since": since}},
        )
        return self._write(run_dir, updated)

    def save_scene(self, node_id: str, scene: Any, *, now: float | None = None) -> Node:
        """Save the person's scene from the editor as the whiteboard's spec.

        A save that changes nothing returns the node as it is. Saves within
        :data:`SAVE_COALESCE_SECONDS` of the person's previous save share one
        history version (the version number still goes up); any other
        revision ends that stretch. Raises ``NodeError`` for another type or
        a scene ``normalize`` refuses.
        """
        with self.locked(node_id):
            node, run_dir = self._board(node_id)
            return self._save_scene(node, run_dir, _checked_spec(node.type, scene), now)

    def merge_save_scene(
        self, node_id: str, scene: Any, *, now: float | None = None
    ) -> tuple[Node, bool]:
        """Join the editor's scene with the stored one and save the result.

        Returns the node as saved and whether the stored scene had something
        newer (then the editor has to take ``node.spec``). Read, merge and
        write happen under the node's lock.
        """
        with self.locked(node_id):
            node, stored = self.scene_of(node_id)
            run_dir = self.dir_of(node_id)
            assert run_dir is not None
            incoming = _checked_spec(node.type, scene)
            stamp = now if now is not None else time.time()
            merged, stored_newer = merge_scene(stored, incoming, now_ms=int(stamp * 1000))
            if node.spec != stored:
                node = replace(node, spec=stored)
            saved = self._save_scene(node, run_dir, _checked_spec(node.type, merged), stamp)
            return saved, stored_newer

    def _kept_file_ids(self, node: Node, run_dir: Path) -> set[str]:
        """Every file id the board's scene and its kept versions name."""
        ids = _scene_file_ids(node.spec)
        try:
            entries = list((run_dir / HISTORY_DIR).iterdir())
        except OSError:  # no history yet
            entries = []
        for entry in entries:
            if not _VERSION_RE.match(entry.name):
                continue
            try:
                ids |= _scene_file_ids(json.loads(entry.read_text(encoding="utf-8")).get("spec"))
            except (OSError, ValueError, AttributeError):
                # An unreadable snapshot names no picture; it cannot be reverted to either.
                continue
        return ids

    def put_file(
        self, node_id: str, data_url: str, *, file_id: str | None = None
    ) -> tuple[str, str]:
        """Keep a picture for a whiteboard. Returns ``(file id, picture type)``.

        Raises ``NodeError`` for another type, a file that is no PNG, JPEG,
        GIF or WebP, or one over the limits (:mod:`dodaios.nodes.board.files`);
        :class:`~dodaios.nodes.board.files.FileConflict` when the id holds a
        different picture.
        """
        with self.locked(node_id):
            node, run_dir = self._board(node_id)
            return board_files.store_data_url(
                run_dir, data_url, file_id=file_id, keep=self._kept_file_ids(node, run_dir)
            )

    def read_file(self, node_id: str, file_id: str) -> tuple[bytes, str] | None:
        """A whiteboard picture's bytes and type, or ``None``. Raises ``NodeError``
        for another type."""
        _, run_dir = self._board(node_id)
        return board_files.read(run_dir, file_id)

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
                spec = _checked_spec(node.type, _prepared(node.type, node.spec, run_dir))
                node = self._write(run_dir, replace(node, spec=spec))
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
    "SAVE_COALESCE_SECONDS",
    "SAVE_STRETCH_SECONDS",
    "SPEC_BYTES_BY_TYPE",
    "DEFAULT_EVERY_MINUTES",
    "MAX_EVERY_MINUTES",
    "MAX_HISTORY",
    "MIN_EVERY_MINUTES",
    "NodeStore",
    "clamp_every",
    "new_node_id",
    "outputs_root",
]
