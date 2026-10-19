"""Path-addressed read and write API behind the desktop Memory section.

The slug routes in :mod:`dodaios.ui.web.wiki_routes` stay for the CLI and
older callers. They address a page by file name, which cannot work for a
vault where 100+ agent notebooks are all called ``MEMORY.md``. These routes
address every page by its vault-relative path and serve the linked model
from :mod:`dodaios.memory.wiki.vault_model`:

* ``GET  /api/wiki/index``          every page, grouped, with agent owners.
* ``GET  /api/wiki/read?path=``     one page with links, backlinks, mentions,
                                    related pages and notebook entries.
* ``GET  /api/wiki/map``            nodes and edges for the memory map.
* ``GET  /api/wiki/activity``       what changed recently, from ``log.md``.
* ``POST /api/wiki/pages``          create a knowledge page.
* ``PUT  /api/wiki/pages``          save an edited body.
* ``POST /api/wiki/pages/rename``   rename and repoint every link to it.
* ``POST /api/wiki/pages/archive``  move a page to ``_archive/``.
* ``POST /api/wiki/tidy``           archive empty notebooks of agents that
                                    are no longer active.

Every write goes through the running ``WikiCurator`` and so through the
guarded ``AtomicWriter`` (backup, secret refusal, schema validation,
rollback, search index update, ``log.md`` entry, live event). Nothing here
calls a model, so none of it can bill a key.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dodaios.memory.wiki.integration import get_running_curator
from dodaios.memory.wiki.protocols import PageUpdate
from dodaios.memory.wiki.session_links import slugify
from dodaios.memory.wiki.vault_model import (
    AgentInfo,
    SourcePage,
    VaultModel,
    build_model,
)
from dodaios.ui.web.wiki_routes import _resolve_vault_root, _scan_visible_pages

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])

#: Kinds a person can create from the Memory section, and where they live.
CREATABLE_KINDS: dict[str, str] = {
    "entity": "entities",
    "project": "projects",
    "concept": "concepts",
}
#: Groups whose pages a person edits by hand. Agent notebooks are written by
#: their agent through entry markers; the reader shows them, the agent's own
#: memory panel edits them.
_EDITABLE_GROUPS = frozenset({"knowledge", "journal"})
_ARCHIVABLE_GROUPS = frozenset({"knowledge", "journal", "agents"})
_ROSTER_TIMEOUT_S = 3.0
_LOG_ENTRY_RE = re.compile(
    r"^## \[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] (?P<verb>[\w-]+) \| (?P<subject>.+?)\s*$"
)
_LOG_LINK_RE = re.compile(r"\[\[([^\]|#]+)")
_FM_BLOCK_RE = re.compile(r"\A(﻿?---\r?\n.*?\r?\n---[ \t]*)(?:\r?\n|\Z)", re.DOTALL)
_UPDATED_RE = re.compile(r"^updated:.*$", re.MULTILINE)


# ------------------------------------------------------------------ bodies


class CreatePageBody(BaseModel):
    kind: str = Field(pattern=r"^(entity|project|concept)$")
    title: str = Field(min_length=1, max_length=160)
    body_md: str = Field(default="", max_length=200_000)


class SavePageBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    body_md: str = Field(max_length=200_000)
    #: The page's mtime when the editor opened it; a newer file on disk
    #: means someone (an agent, Obsidian) changed it meanwhile.
    base_mtime: float


class RenamePageBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=160)


class ArchivePageBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)


class TidyBody(BaseModel):
    dry_run: bool = True


# ------------------------------------------------------------------- model

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, tuple[tuple[Any, ...], VaultModel]] = {}


async def _agents(request: Request) -> dict[str, AgentInfo] | None:
    """Roster names and states, or ``None`` when the society is unavailable.

    A notebook folder whose agent the roster no longer knows is an orphan;
    the reader groups those apart instead of listing them as live agents.
    """
    try:
        from dodaios.society.display_name import display_name
        from dodaios.ui.web.society_routes import _runtime

        runtime = await asyncio.wait_for(_runtime(request), timeout=_ROSTER_TIMEOUT_S)
        records = await asyncio.wait_for(
            runtime.roster.list(include_archived=True), timeout=_ROSTER_TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001 - the vault reads fine without agent names
        log.info("memory vault: roster unavailable, agent names fall back to ids: %s", exc)
        return None
    out: dict[str, AgentInfo] = {}
    for record in records:
        state = "archived" if str(record.state).endswith("archived") else "active"
        out[record.agent_id] = AgentInfo(record.agent_id, display_name(record), state)
    return out


async def _model(request: Request, *, require_roster: bool = False) -> tuple[Path, VaultModel]:
    """The linked model of the vault, rebuilt only when a file or the roster changed.

    ``require_roster`` is for actions that depend on agent states: without the
    roster every notebook folder would read as orphaned, live agents included.
    """
    vault_root = _resolve_vault_root(request)
    if vault_root is None or not vault_root.is_dir():
        raise HTTPException(404, "The memory vault is not set up yet.")
    visible, roster = await asyncio.gather(_scan_visible_pages(vault_root), _agents(request))
    if roster is None and require_roster:
        raise HTTPException(
            503, "The agent list is not available right now, so nothing was changed. Try again."
        )
    agents = roster or {}
    signature = (
        tuple((v.relative_path.as_posix(), v.mtime, v.size) for v in visible),
        tuple(sorted((a.agent_id, a.name, a.state) for a in agents.values())),
    )
    key = str(vault_root)
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return vault_root, cached[1]
    sources = [
        SourcePage(
            path=v.relative_path.as_posix(),
            body=v.page.body,
            properties=v.properties,
            page_type=v.page.page_type,
            mtime=v.mtime,
            size=v.size,
        )
        for v in visible
    ]
    model = await asyncio.to_thread(build_model, sources, agents)
    with _MODEL_LOCK:
        _MODEL_CACHE[key] = (signature, model)
    return vault_root, model


def _require_page(model: VaultModel, path: str) -> Any:
    record = model.pages.get(path)
    if record is None:
        raise HTTPException(404, "No page at that path.")
    return record


def _require_curator() -> Any:
    curator = get_running_curator()
    if curator is None:
        raise HTTPException(
            503,
            "The memory writer is not running. Turn on the wiki in Settings, then try again.",
        )
    return curator


def _today() -> str:
    return _dt.date.today().isoformat()


# ------------------------------------------------------------------- reads


@router.get("/index")
async def get_index(request: Request) -> dict[str, Any]:
    """Every page once, grouped, plus the agents that own notebook folders."""
    vault_root, model = await _model(request)
    agents = []
    for agent_id, info in sorted(model.agents.items(), key=lambda item: item[1].name.casefold()):
        pages = [p for p in model.pages.values() if p.agent_id == agent_id]
        agents.append(
            {
                "agent_id": agent_id,
                "name": info.name,
                "state": info.state,
                "empty": all(p.empty for p in pages),
                "updated": max((p.mtime for p in pages), default=0.0),
                "pages": [p.path for p in sorted(pages, key=lambda p: (p.kind, -p.mtime))],
            }
        )
    pages = []
    for record in model.pages.values():
        summary = record.summary_dict()
        summary["links_in"] = len({link.source for link in model.incoming.get(record.path, [])})
        summary["links_out"] = len(
            {link.target for link in model.outgoing.get(record.path, []) if link.target}
        )
        pages.append(summary)
    pages.sort(key=lambda p: -p["mtime"])
    return {
        "ok": True,
        "vault_root": str(vault_root),
        "stats": model.stats(),
        "pages": pages,
        "agents": agents,
        "writable": get_running_curator() is not None,
    }


@router.get("/read")
async def read_page(request: Request, path: str = Query(min_length=1)) -> dict[str, Any]:
    """One page, its links in both directions, and what it relates to."""
    _, model = await _model(request)
    record = _require_page(model, path)
    entries: list[dict[str, Any]] = []
    if record.kind in ("memory", "profile"):
        from dodaios.society.notebook import parse

        try:
            entries = [
                {
                    "id": entry.id,
                    "text": entry.text,
                    "importance": entry.importance,
                    "origin": entry.origin,
                }
                for entry in parse(record.body)
                if entry.text.strip()
            ]
        except (ValueError, KeyError) as exc:
            log.warning("memory vault: notebook %s has unreadable entries: %s", path, exc)
    agent = model.agents.get(record.agent_id or "")
    return {
        "ok": True,
        **record.summary_dict(),
        "properties": dict(record.properties),
        "aliases": list(record.aliases),
        "body_md": record.body,
        "size": record.size,
        "editable": record.group in _EDITABLE_GROUPS,
        "archivable": record.group in _ARCHIVABLE_GROUPS,
        "agent": (
            {"agent_id": agent.agent_id, "name": agent.name, "state": agent.state}
            if agent
            else None
        ),
        "entries": entries,
        **model.page_links(path),
        "related": model.related(path),
    }


@router.get("/map")
async def get_map(request: Request, agents: bool = Query(default=True)) -> dict[str, Any]:
    """The memory map: pages with content as nodes, links and mentions as edges."""
    _, model = await _model(request)
    return {"ok": True, **model.graph(include_agents=agents)}


@router.get("/activity")
async def get_activity(
    request: Request, limit: int = Query(default=40, ge=1, le=200)
) -> dict[str, Any]:
    """Recent writes from ``log.md``, newest first, without self-doc refreshes."""
    vault_root, model = await _model(request)
    log_path = vault_root / "log.md"
    try:
        text = await asyncio.to_thread(log_path.read_text, encoding="utf-8", errors="replace")
    except OSError as exc:
        log.info("memory vault: activity feed empty, log.md unreadable: %s", exc)
        text = ""
    return {"ok": True, "items": _parse_activity(text, model, limit)}


def _parse_activity(text: str, model: VaultModel, limit: int) -> list[dict[str, Any]]:
    by_stem: dict[str, str] = {}
    for path in model.pages:
        by_stem.setdefault(path.removesuffix(".md").casefold(), path)
        by_stem.setdefault(Path(path).stem.casefold(), path)
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        match = _LOG_ENTRY_RE.match(line)
        if match:
            if current is not None:
                items.append(current)
            current = {
                "ts": match["ts"],
                "verb": match["verb"],
                "source": match["subject"],
                "summary": "",
                "pages": [],
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("- pages touched:"):
            for raw in _LOG_LINK_RE.findall(stripped):
                path = by_stem.get(raw.strip().casefold())
                if path and path not in current["pages"]:
                    current["pages"].append(path)
        elif stripped.startswith("- summary:"):
            current["summary"] = stripped.removeprefix("- summary:").strip()
    if current is not None:
        items.append(current)
    meaningful = [
        item
        for item in items
        if not item["source"].startswith("self-doc") and item["pages"]
    ]
    meaningful.reverse()
    out = []
    for item in meaningful[:limit]:
        item["pages"] = [
            {"path": p, "title": model.pages[p].title, "kind": model.pages[p].kind}
            for p in item["pages"]
        ]
        out.append(item)
    return out


# ------------------------------------------------------------------ writes


def _write_failure(result: Any) -> HTTPException | None:
    if result.applied:
        return None
    if result.blocked_pii:
        return HTTPException(
            422, "Not saved: the text looks like it contains a password or key."
        )
    if result.skipped_due_to_recent_edit:
        return HTTPException(
            409, "Not saved: the page changed somewhere else a moment ago. Reload it first."
        )
    if result.failed_validation:
        return HTTPException(422, "Not saved: the page did not pass the vault's schema check.")
    return HTTPException(500, "Not saved.")


async def _apply(updates: list[PageUpdate], *, label: str, verb: str) -> Any:
    curator = _require_curator()
    result = await curator.apply_external_updates(
        updates,
        source_label=label,
        verb=verb,
        all_or_nothing=len(updates) > 1,
        keep_unresolved_links=True,
    )
    failure = _write_failure(result)
    if failure is not None:
        raise failure
    return result


def _frontmatter_for(kind: str, slug: str, title: str) -> str:
    today = _today()
    lines = ["---", f"type: {kind}", f"slug: {slug}", f"title: {_yaml_text(title)}"]
    if kind == "project":
        lines.append("status: active")
    lines += [f"created: {today}", f"updated: {today}", "---"]
    return "\n".join(lines)


def _yaml_text(text: str) -> str:
    clean = " ".join(text.split())
    escaped = clean.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


@router.post("/pages", openapi_extra={"x-jarvis-risk-tier": "monitor"})
async def create_page(payload: CreatePageBody, request: Request) -> dict[str, Any]:
    """Create a new entity, project or concept page."""
    vault_root, model = await _model(request)
    title = " ".join(payload.title.split())
    slug = slugify(title)
    if not slug:
        raise HTTPException(422, "Give the page a title with at least one letter or digit.")
    folder = CREATABLE_KINDS[payload.kind]
    path = f"{folder}/{slug}.md"
    if path in model.pages or (vault_root / path).exists():
        raise HTTPException(409, f"A page called {title} already exists.")
    body = payload.body_md.strip()
    content = f"{_frontmatter_for(payload.kind, slug, title)}\n\n# {title}\n"
    if body:
        content += f"\n{body}\n"
    await _apply(
        [PageUpdate(Path(path), "create", content, reason="created in the Memory section")],
        label="user:memory-section",
        verb="create",
    )
    return {"ok": True, "path": path}


@router.put("/pages", openapi_extra={"x-jarvis-risk-tier": "monitor"})
async def save_page(payload: SavePageBody, request: Request) -> dict[str, Any]:
    """Replace a page's body; its frontmatter stays as it was."""
    vault_root, model = await _model(request)
    record = _require_page(model, payload.path)
    if record.group not in _EDITABLE_GROUPS:
        raise HTTPException(
            403, "Agent notebooks are kept by their agent. Edit them in the agent's memory panel."
        )
    target = vault_root / record.path
    # The file on disk, not the cached model, decides whether it is stale.
    current = await asyncio.to_thread(target.stat)
    if max(record.mtime, current.st_mtime) > payload.base_mtime + 0.001:
        raise HTTPException(409, "This page changed since you opened it. Reload it first.")
    raw = await asyncio.to_thread(target.read_text, encoding="utf-8")
    match = _FM_BLOCK_RE.match(raw)
    head = match.group(1) if match else ""
    if head and _UPDATED_RE.search(head):
        head = _UPDATED_RE.sub(f"updated: {_today()}", head, count=1)
    body = payload.body_md.replace("\r\n", "\n").strip("\n")
    content = f"{head}\n\n{body}\n" if head else f"{body}\n"
    await _apply(
        [PageUpdate(Path(payload.path), "update", content, reason="edited in the Memory section")],
        label="user:memory-section",
        verb="update",
    )
    stat = await asyncio.to_thread(target.stat)
    return {"ok": True, "path": payload.path, "mtime": stat.st_mtime}


@router.post("/pages/rename", openapi_extra={"x-jarvis-risk-tier": "monitor"})
async def rename_page(payload: RenamePageBody, request: Request) -> dict[str, Any]:
    """Rename a knowledge page and repoint every link that opened it."""
    vault_root, model = await _model(request)
    record = _require_page(model, payload.path)
    if record.group != "knowledge":
        raise HTTPException(403, "Only knowledge pages can be renamed here.")
    title = " ".join(payload.title.split())
    slug = slugify(title)
    if not slug:
        raise HTTPException(422, "Give the page a title with at least one letter or digit.")
    folder = record.folder
    new_path = f"{folder}/{slug}.md" if folder else f"{slug}.md"
    if new_path != record.path and (new_path in model.pages or (vault_root / new_path).exists()):
        raise HTTPException(409, f"A page called {title} already exists.")

    raw = await asyncio.to_thread((vault_root / record.path).read_text, encoding="utf-8")
    head, fresh_body = _split_head(raw)
    if head:
        head = re.sub(r"^slug:.*$", f"slug: {slug}", head, count=1, flags=re.MULTILINE)
        if re.search(r"^title:", head, flags=re.MULTILINE):
            head = re.sub(
                r"^title:.*$", f"title: {_yaml_text(title)}", head, count=1, flags=re.MULTILINE
            )
    body = re.sub(
        rf"^# {re.escape(record.title)}\s*$", f"# {title}", fresh_body, count=1, flags=re.MULTILINE
    )
    content = f"{head}\n{body}\n" if head else f"{body}\n"
    new_target = new_path.removesuffix(".md")
    updates: list[PageUpdate] = []
    if new_path == record.path:
        updates.append(PageUpdate(Path(record.path), "update", content, reason="renamed"))
    else:
        updates.append(
            PageUpdate(
                Path(new_path),
                "rename",
                content,
                rename_from=Path(record.path),
                reason="renamed in the Memory section",
            )
        )
    rewritten = 0
    # Agent notebooks are written by their agents through entry markers, so
    # their links are reported rather than rewritten behind the agent's back.
    unrewritten = 0
    linking = {
        link.source
        for link in model.incoming.get(record.path, [])
        if link.kind == "link" and link.source != record.path
    }
    for source in sorted(linking):
        if model.pages[source].group not in _EDITABLE_GROUPS:
            unrewritten += 1
            continue
        # Rewrite the file as it is now, not as the cached model saw it.
        source_raw = await asyncio.to_thread((vault_root / source).read_text, encoding="utf-8")
        source_head, source_body = _split_head(source_raw)
        new_body, count = model.rewrite_links(source, record.path, new_target, body=source_body)
        if not count:
            continue
        prefix = f"{source_head}\n" if source_head else ""
        updates.append(
            PageUpdate(Path(source), "update", f"{prefix}{new_body}\n", reason="link renamed")
        )
        rewritten += count
    await _apply(updates, label="user:memory-section", verb="rename")
    return {
        "ok": True,
        "path": new_path,
        "links_rewritten": rewritten,
        "links_unrewritten": unrewritten,
    }


@router.post("/pages/archive", openapi_extra={"x-jarvis-risk-tier": "monitor"})
async def archive_page(payload: ArchivePageBody, request: Request) -> dict[str, Any]:
    """Move a page into ``_archive/``; nothing is deleted."""
    _, model = await _model(request)
    record = _require_page(model, payload.path)
    if record.group not in _ARCHIVABLE_GROUPS:
        raise HTTPException(403, "System pages cannot be archived.")
    await _apply(
        [PageUpdate(Path(record.path), "archive", "", reason="archived in the Memory section")],
        label="user:memory-section",
        verb="archive",
    )
    return {"ok": True, "path": record.path}


@router.post("/tidy", openapi_extra={"x-jarvis-risk-tier": "monitor"})
async def tidy_vault(payload: TidyBody, request: Request) -> dict[str, Any]:
    """Archive empty notebooks that belong to archived or unknown agents.

    Only pages without a single sentence of content qualify, and they move to
    ``_archive/`` rather than being deleted. ``dry_run`` (the default) lists
    what would move.
    """
    # Without a roster answer every folder would read as orphaned, live
    # agents included, so this refuses instead of guessing.
    vault_root, model = await _model(request, require_roster=True)
    candidates = [
        record.path
        for record in model.pages.values()
        if record.group == "agents"
        and record.kind in ("memory", "profile")
        and record.empty
        and model.agents.get(record.agent_id or "", AgentInfo("", "", "orphan")).state != "active"
    ]
    candidates.sort()
    if payload.dry_run or not candidates:
        return {"ok": True, "dry_run": True, "count": len(candidates), "paths": candidates}
    curator = _require_curator()
    moved: list[str] = []
    # Batches keep one backup snapshot per call small and each call fast.
    for start in range(0, len(candidates), 25):
        batch = candidates[start : start + 25]
        result = await curator.apply_external_updates(
            [PageUpdate(Path(p), "archive", "", reason="empty notebook tidied") for p in batch],
            source_label="user:memory-tidy",
            verb="archive",
        )
        moved += [_relative(Path(p), vault_root) for p in result.applied]
    skipped = len(candidates) - len(moved)
    if skipped:
        log.warning(
            "memory tidy: %d of %d empty notebooks were not archived", skipped, len(candidates)
        )
    return {"ok": True, "dry_run": False, "count": len(moved), "skipped": skipped, "paths": moved}


def _relative(path: Path, vault_root: Path) -> str:
    try:
        return path.resolve().relative_to(vault_root.resolve()).as_posix()
    except ValueError:  # silent-ok: the writer only applies in-vault paths; this is display only
        return path.as_posix()


def _split_head(raw: str) -> tuple[str, str]:
    """``(frontmatter block, body)`` of a page file; the block is ``""`` when absent."""
    match = _FM_BLOCK_RE.match(raw)
    if not match:
        return "", raw
    return match.group(1), raw[match.end() :]


__all__ = ["router"]
