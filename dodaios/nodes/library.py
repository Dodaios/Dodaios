"""The Nodes library: one list of cards for everything a person keeps.

The app shows one library, not two. A typed node (:mod:`dodaios.nodes.store`)
is a card, and so is everything older runs left behind: a page a worker built,
a report, a living page, a picture, a PDF. Each of those is adopted under the
node type it is closest to, so a person finds last month's dashboard next to
the sheet made today. A run that left nothing to look at is a card too (its
answer is the card), and so is a page a worker is still building.

Why the list is built HERE and not in the frontend: the old Artifacts section
read ``/api/outputs`` and then one ``/api/outputs/{slug}/artifacts`` listing
per run, sixty requests for one screen, and chose the files to show in the
browser. This module makes the same choice once, on the server, from the same
two listings (``dodaios/ui/web/outputs_routes.py``). It does not walk the
archive a second way: the run list decides which runs exist and what state
they are in, the file listing decides which files are deliverables. Nothing is
read from disk beyond what those two already read, plus one small state file
per typed node and per living page.

The card shape is the frontend's ``NodeCard``
(``frontend/src/components/nodes/nodeModel.ts``). See ``docs/nodes.md``.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from fastapi import HTTPException, Request

from dodaios.artifacts.living import SLUG_INFIX as LIVING_SLUG_INFIX
from dodaios.artifacts.living import LivingPageStore
from dodaios.artifacts.report import SLUG_INFIX as REPORT_SLUG_INFIX
from dodaios.nodes.kinds import kind_of
from dodaios.nodes.model import SLUG_INFIX as NODE_SLUG_INFIX
from dodaios.nodes.model import Node
from dodaios.nodes.store import NodeStore
from dodaios.ui.web.outputs_routes import list_output_artifacts, list_outputs

log = logging.getLogger(__name__)

#: Newest runs whose files are looked at. One listing is one walk of a run
#: directory; a machine with hundreds of archived runs must not pay for all of
#: them on every visit. Sixty is what the Artifacts gallery settled on.
DEFAULT_SCAN_LIMIT: Final[int] = 60
MAX_SCAN_LIMIT: Final[int] = 500

#: Extension -> how the stage puts the file on screen. Deliberately narrow:
#: everything here renders inside the desktop WebView without a plugin or a
#: converter. Any other file stays behind the run's Files tab.
VISUAL_EXTENSIONS: Final[tuple[tuple[str, str], ...]] = (
    (".png", "image"),
    (".jpg", "image"),
    (".jpeg", "image"),
    (".gif", "image"),
    (".webp", "image"),
    (".bmp", "image"),
    (".avif", "image"),
    (".svg", "vector"),
    (".html", "page"),
    (".htm", "page"),
    (".pdf", "document"),
)

#: A run card's text: the first lines of the answer, not the answer.
MAX_PREVIEW_CHARS: Final[int] = 240
#: One comfortable line at the size a card's title is set in.
HEADLINE_MAX_CHARS: Final[int] = 96

# A ``create_artifact`` mission's request leads with ``Artifact: <title>``
# (dodaios/artifacts/brief.py); the run list has already cut the quality lead
# in front of it.
_BRIEF_RE: Final = re.compile(r"^Artifact:[ \t]*([^\n]+)")
# The mission builder's tail for the worker; never part of what was asked.
_SUPPORTING_CONTEXT_RE: Final = re.compile(
    r"\s*Supporting context from the recent conversation\b.*$", re.IGNORECASE | re.DOTALL
)
_FIRST_SENTENCE_RE: Final = re.compile(r"^(.{12,}?[.!?])\s")
_HEADLINE_TAIL_RE: Final = re.compile(r"[\s,;:\-–—(]+$")
_TITLE_RE: Final = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HEADING_MARK_RE: Final = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_ANSWER_SUFFIXES: Final[tuple[str, ...]] = (".md", ".markdown", ".txt")


# ------------------------------------------------------------------ text rules


def visual_kind(path: str) -> str | None:
    """How the stage shows this file, or ``None`` when it is not a visual."""
    lower = path.lower()
    for extension, kind in VISUAL_EXTENSIONS:
        if lower.endswith(extension):
            return kind
    return None


def brief_title(utterance: str | None) -> str | None:
    """The title an ``Artifact: <title>`` brief leads with.

    ``None`` when the request is not a brief; an empty string for a brief
    that names nothing.
    """
    match = _BRIEF_RE.match((utterance or "").strip())
    return match.group(1).strip() if match else None


def clean_request(utterance: str | None) -> str:
    """What was asked, as one line, without the worker-facing tail."""
    return " ".join(_SUPPORTING_CONTEXT_RE.sub("", utterance or "").split())


def request_headline(text: str | None, limit: int = HEADLINE_MAX_CHARS) -> str:
    """A headline out of a request: its first sentence when that is short
    enough, else the first ``limit`` characters cut at a word."""
    clean = clean_request(text)
    if len(clean) <= limit:
        return clean
    sentence = _FIRST_SENTENCE_RE.match(clean)
    if sentence and len(sentence.group(1)) <= limit:
        return sentence.group(1)
    cut = clean[:limit]
    space = cut.rfind(" ")
    return _HEADLINE_TAIL_RE.sub("", cut[:space] if space > limit / 2 else cut) + "…"


def run_title(run: Mapping[str, Any]) -> str:
    """What a run is called when it has no page of its own to name it."""
    utterance = _text(run.get("utterance"))
    return brief_title(utterance) or request_headline(utterance) or _text(run.get("slug"))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _request_of(run: Mapping[str, Any]) -> str:
    """The card's ``request``: the run's request, a brief reduced to its title."""
    utterance = _text(run.get("utterance"))
    title = brief_title(utterance)
    return title if title is not None else clean_request(utterance)


def _title_in(preview: Any) -> str | None:
    """A page's ``<title>`` from the listing's text preview, or ``None``."""
    match = _TITLE_RE.search(_text(preview))
    if match is None:
        return None
    return " ".join(html.unescape(match.group(1)).split()) or None


def _clip(text: str, limit: int = MAX_PREVIEW_CHARS) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _answer_text(run: Mapping[str, Any], files: Sequence[Mapping[str, Any]]) -> str:
    """The run's summary, else the first lines of the answer it wrote down.

    The answer is read from the preview the file listing already carries, so
    a card never costs a file read of its own.
    """
    summary = _text(run.get("summary")).strip()
    if summary:
        return _clip(summary)
    for file in files:
        preview = _text(file.get("preview")).strip()
        if preview and _text(file.get("path")).lower().endswith(_ANSWER_SUFFIXES):
            return _clip(_HEADING_MARK_RE.sub("", preview))
    return ""


# ----------------------------------------------------------------------- cards


def _card(
    *,
    key: str,
    type: str,  # noqa: A002 - the card field's name, as the frontend reads it
    origin: str,
    title: str,
    slug: str,
    path: str | None = None,
    visual: str | None = None,
    created_at: float = 0.0,
    updated_at: float = 0.0,
    size: int = 0,
    status: str = "ready",
    request: str = "",
    preview: dict[str, Any] | None = None,
    node_id: str | None = None,
    version: int = 0,
    kept_current: bool = False,
    refreshing: bool = False,
    every_minutes: int = 0,
) -> dict[str, Any]:
    """One card, with every field of the frontend's ``NodeCard``."""
    return {
        "key": key,
        "id": node_id,
        "type": type,
        "origin": origin,
        "title": title,
        "slug": slug,
        "path": path,
        "visual_kind": visual,
        "created_at": created_at,
        "updated_at": updated_at,
        "size": size,
        "version": version,
        "status": status,
        "kept_current": kept_current,
        "refreshing": refreshing,
        "every_minutes": every_minutes,
        "request": request,
        "preview": preview,
    }


def _page_size(node: Node, store: NodeStore) -> int:
    run_dir = store.dir_of(node.id)
    if run_dir is None:
        return 0
    try:
        return (run_dir / node.page_path).stat().st_size
    except OSError:  # a node whose page file is gone still gets its card
        return 0


def node_card(node: Node, store: NodeStore) -> dict[str, Any]:
    """The card of one typed node.

    ``node.refreshing`` is taken as given: a caller that can ask the
    scheduler (the route) passes the node with the checked value.
    """
    try:
        preview: dict[str, Any] | None = dict(kind_of(node.type).preview(node.spec))
    except Exception:  # noqa: BLE001 - a renderer's fault must not take the library down
        log.warning("node %s: no card preview (%s)", node.id, node.type, exc_info=True)
        preview = None
    kept_current = bool(node.track)
    return _card(
        key=node.visual_id,
        node_id=node.id,
        type=node.type,
        origin="node",
        title=node.title,
        slug=node.slug,
        path=node.page_path,
        visual="page",
        created_at=node.created_at,
        updated_at=node.updated_at,
        size=_page_size(node, store),
        version=node.version,
        kept_current=kept_current,
        refreshing=kept_current and node.refreshing,
        every_minutes=node.every_minutes if kept_current else 0,
        preview=preview,
    )


def _run_when(run: Mapping[str, Any]) -> float:
    """The run's moment: when it ended, else when it began."""
    return _number(run.get("completed_at")) or _number(run.get("started_at"))


def _file_cards(
    run: Mapping[str, Any],
    files: Sequence[Mapping[str, Any]],
    living_store: LivingPageStore | None,
) -> list[dict[str, Any]]:
    """The cards of a run's files a person can look at."""
    slug = _text(run.get("slug"))
    is_living = LIVING_SLUG_INFIX in slug
    is_report = REPORT_SLUG_INFIX in slug
    visuals = [(file, visual_kind(_text(file.get("path")))) for file in files]
    # A run that built exactly one page was asked for that page by name: the
    # brief's title names the page when the file itself does not.
    pages = sum(1 for _, kind in visuals if kind == "page")
    asked = (brief_title(_text(run.get("utterance"))) or None) if pages == 1 else None
    living = (
        living_store.by_slug(slug) if is_living and pages and living_store is not None else None
    )
    started = _number(run.get("started_at"))
    status = "error" if run.get("status") == "error" else "ready"
    request = _request_of(run)

    cards: list[dict[str, Any]] = []
    for file, kind in visuals:
        # A report run holds its page and the Markdown it was made from; the
        # page is the report.
        if kind is None or (is_report and kind != "page"):
            continue
        path = _text(file.get("path"))
        name = path.rsplit("/", 1)[-1]
        mtime = _number(file.get("mtime"))
        title = name
        kept_current = refreshing = False
        every_minutes = 0
        created_at = started or mtime
        if kind == "page":
            title = (
                _text(file.get("title")).strip() or _title_in(file.get("preview")) or asked or name
            )
            if is_living:
                card_type, origin, kept_current = "sheets", "living", True
                if living is not None:
                    refreshing = living.refreshing
                    every_minutes = living.every_minutes
                    created_at = living.created_at or created_at
            elif is_report:
                card_type, origin = "docs", "report"
            else:
                card_type, origin = "design", "page"
        else:
            card_type, origin = ("docs" if kind == "document" else "design"), "file"
        cards.append(
            _card(
                key=f"{slug}::{path}",
                type=card_type,
                origin=origin,
                title=title,
                slug=slug,
                path=path,
                visual=kind,
                created_at=created_at,
                updated_at=mtime,
                size=int(_number(file.get("size"))),
                status=status,
                request=request,
                kept_current=kept_current,
                refreshing=refreshing,
                every_minutes=every_minutes,
            )
        )
    return cards


def _build_card(run: Mapping[str, Any]) -> dict[str, Any]:
    slug = _text(run.get("slug"))
    return _card(
        key=f"build:{slug}",
        type="design",
        origin="build",
        title=run_title(run),
        slug=slug,
        created_at=_number(run.get("started_at")),
        updated_at=_run_when(run),
        status="building",
        request=_request_of(run),
    )


def _run_card(run: Mapping[str, Any], files: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    slug = _text(run.get("slug"))
    state = run.get("status")
    return _card(
        key=f"run:{slug}",
        type="output",
        origin="run",
        title=run_title(run),
        slug=slug,
        created_at=_number(run.get("started_at")),
        updated_at=_run_when(run),
        status="building" if state == "running" else "error" if state == "error" else "ready",
        request=_request_of(run),
        preview={"text": _answer_text(run, files)},
    )


# -------------------------------------------------------------------- listings


async def list_runs(request: Request) -> list[dict[str, Any]]:
    """The runs of the archive, newest first, exactly as ``/api/outputs`` lists them."""
    return [session.model_dump() for session in (await list_outputs(request)).sessions]


async def _file_listings(request: Request, slugs: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    """Each run's deliverable files, as ``/api/outputs/{slug}/artifacts`` lists them."""
    listings: dict[str, list[dict[str, Any]]] = {}
    for slug in slugs:
        try:
            listings[slug] = list((await list_output_artifacts(slug, request))["files"])
        except HTTPException as exc:
            # The run was removed since the run list was read, or its folder
            # cannot be walked. Half a library is still a library.
            log.debug("nodes library: no file listing for %s (%s)", slug, exc.detail)
    return listings


def build_library(
    request: Request,
    *,
    runs: Sequence[Mapping[str, Any]],
    nodes: Sequence[Node],
    store: NodeStore,
    living_store: LivingPageStore | None = None,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
) -> dict[str, Any]:
    """Every card of the library, work in progress first, then newest first.

    Blocking file I/O from start to end: call it on a worker thread
    (``asyncio.to_thread``), never on the event loop.

    Inputs:
        request: the HTTP request; the outputs listing reads the archive
            roots from its app state.
        runs: the run list (:func:`list_runs`), newest first.
        nodes: the typed nodes (``NodeStore.list_nodes()``), with
            ``refreshing`` already checked by a caller that can.
        store: where those nodes live (for the size of their pages).
        living_store: where living pages keep their state; without it a
            living page still gets its card, as not refreshing.
        scan_limit: how many of the newest runs are searched for files.
    """
    limit = max(1, min(MAX_SCAN_LIMIT, int(scan_limit)))
    cards = [node_card(node, store) for node in nodes]
    # A typed node's run is already a card; its files are never adopted.
    others = [run for run in runs if NODE_SLUG_INFIX not in _text(run.get("slug"))]
    scanned = others[:limit]
    # The outputs listing is an ``async def`` handler that walks a run folder
    # without ever awaiting. On the app's event loop sixty of those walks in
    # a row would stall every other request, so the handler runs to the end
    # here, on this worker thread, in a loop of its own.
    listings = asyncio.run(_file_listings(request, [_text(run.get("slug")) for run in scanned]))

    for run in others:
        slug = _text(run.get("slug"))
        files = listings.get(slug, [])
        found = _file_cards(run, files, living_store)
        cards.extend(found)
        has_page = any(card["visual_kind"] == "page" for card in found)
        building = (
            run.get("status") == "running"
            and brief_title(_text(run.get("utterance"))) is not None
            and not has_page
        )
        if building:
            cards.append(_build_card(run))
        elif not found:
            # Also a run outside the scan window: it keeps a card, and its
            # files are read when the card is opened.
            cards.append(_run_card(run, files))

    cards.sort(key=lambda card: (card["status"] == "building", card["updated_at"]), reverse=True)
    return {
        "nodes": cards,
        "scanned_runs": len(scanned),
        "skipped_runs": len(others) - len(scanned),
    }


__all__ = [
    "DEFAULT_SCAN_LIMIT",
    "MAX_SCAN_LIMIT",
    "VISUAL_EXTENSIONS",
    "brief_title",
    "build_library",
    "clean_request",
    "list_runs",
    "node_card",
    "request_headline",
    "run_title",
    "visual_kind",
]
