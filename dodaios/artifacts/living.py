"""Living pages: an artifact whose data the assistant keeps current.

The person asks "keep a page that tracks my parcels" (or job applications, or
a stock list). The page is an ordinary artifact — one self-contained HTML file
in the run archive, so the Artifacts section, the Downloads mirror and the
cleanup sweep all see it without a second store — plus a small JSON state file
next to it that holds the rows. A lead routine (:mod:`.living_refresh`) reads
the person's sources on a schedule and hands fresh rows back through the
``living_page`` tool; this module rewrites the page from them.

Why the page is rendered HERE and not by a mission worker: a refresh changes
rows, not the design. Re-running the artifact worker on every refresh would
spend the strongest model on a table, and a routine run must never bill an
API key. The renderer is deterministic, uses the artifact design tokens
(:mod:`.design_guide`), and runs no network code: the page's only script
writes "updated 10 minutes ago" in the viewer's own locale through
``Intl.RelativeTimeFormat``, so the page carries no hard-coded language.

Layout of one living page on disk::

    <outputs_root>/<stamp>__living-page__<id>/
        .standalone-run.json                      (kind "living_page")
        living-page.json                          (this module's state)
        tasks/living/artifacts/files/<file>.html  (the page itself)

The state file sits outside ``tasks/*/artifacts/files`` on purpose: the
Outputs allowlist never lists it as a deliverable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from html import escape
from pathlib import Path
from typing import Any, Final

from dodaios.artifacts.design_guide import THEME_BOOTSTRAP_JS, THEME_CSS

log = logging.getLogger(__name__)

#: Marker kind of a living page's run directory (``missions/standalone_run``).
MARKER_KIND: Final[str] = "living_page"
#: The run-directory infix that names a living page; the frontend matches it.
SLUG_INFIX: Final[str] = "__living-page__"
STATE_FILE: Final[str] = "living-page.json"
PAGE_DIR: Final[tuple[str, ...]] = ("tasks", "living", "artifacts", "files")

#: Refresh cadence bounds, in minutes. Fifteen minutes is the floor because a
#: refresh is a whole assistant turn; a week is the ceiling of "living".
MIN_EVERY_MINUTES: Final[int] = 15
MAX_EVERY_MINUTES: Final[int] = 7 * 24 * 60
DEFAULT_EVERY_MINUTES: Final[int] = 180

MAX_COLUMNS: Final[int] = 8
MAX_ROWS: Final[int] = 200
MAX_CELL_CHARS: Final[int] = 500
MAX_TITLE_CHARS: Final[int] = 120
MAX_TRACK_CHARS: Final[int] = 2_000
MAX_NOTE_CHARS: Final[int] = 300
#: The column that carries a row's link, never shown as a column of its own.
LINK_KEY: Final[str] = "link"

_REPLACE_ATTEMPTS: Final[int] = 6
_ID_RE: Final = re.compile(r"^[0-9a-f]{12}$")
_FILE_RE: Final = re.compile(r"[^a-z0-9]+")


class LivingPageError(ValueError):
    """A request the store refuses, with a sentence the model can act on."""


@dataclass(frozen=True)
class LivingPage:
    """One living page and the state of its refresh."""

    id: str
    title: str
    track: str
    """The standing instruction for every refresh: what this page tracks."""
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    slug: str
    page_path: str
    """Posix path inside the run, as ``/api/outputs/{slug}/artifacts`` lists it."""
    created_at: float
    updated_at: float
    every_minutes: int = DEFAULT_EVERY_MINUTES
    task_id: str = ""
    refreshing: bool = False
    note: str = ""
    """A short line from the last refresh (why nothing could be read, …)."""
    language: str = "en"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def visual_id(self) -> str:
        """``slug::path`` — the Artifacts stage's address of this page."""
        return f"{self.slug}::{self.page_path}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["columns"] = list(self.columns)
        data["rows"] = [dict(row) for row in self.rows]
        data["visual_id"] = self.visual_id
        data["page_url"] = f"/api/outputs/{self.slug}/files/{self.page_path}/page"
        return data


# ---------------------------------------------------------------- normalizing


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def clamp_every(minutes: Any) -> int:
    """A refresh cadence inside the supported bounds (default when unreadable)."""
    try:
        value = int(float(minutes))
    except (TypeError, ValueError):  # an unreadable cadence means the default one
        return DEFAULT_EVERY_MINUTES
    return max(MIN_EVERY_MINUTES, min(MAX_EVERY_MINUTES, value))


def normalize_columns(columns: Any, rows: Any = None) -> tuple[str, ...]:
    """The table's columns: given ones first, else the keys the rows use."""
    names: list[str] = []
    for raw in columns if isinstance(columns, (list, tuple)) else ():
        name = _clean(raw, 60)
        if name and name.lower() != LINK_KEY and name not in names:
            names.append(name)
    if not names and isinstance(rows, (list, tuple)):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in row:
                name = _clean(key, 60)
                if name and name.lower() != LINK_KEY and name not in names:
                    names.append(name)
    return tuple(names[:MAX_COLUMNS])


def normalize_rows(rows: Any, columns: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    """Rows reduced to the columns (plus an optional ``link``), as plain text.

    Accepts a list of objects or a list of lists (cells in column order). A
    malformed row is dropped rather than failing the whole refresh.
    """
    out: list[dict[str, str]] = []
    if not isinstance(rows, (list, tuple)):
        raise LivingPageError("'rows' must be a list of objects, one per tracked item.")
    for raw in rows[:MAX_ROWS]:
        row: dict[str, str] = {}
        if isinstance(raw, dict):
            lowered = {_clean(k, 60).lower(): v for k, v in raw.items()}
            for column in columns:
                value = raw.get(column, lowered.get(column.lower()))
                if value is not None and value != "":
                    row[column] = _clean(value, MAX_CELL_CHARS)
            link = _clean(lowered.get(LINK_KEY), MAX_CELL_CHARS)
            if link.startswith(("https://", "http://")):
                row[LINK_KEY] = link
        elif isinstance(raw, (list, tuple)):
            for column, value in zip(columns, raw, strict=False):
                if value is not None and value != "":
                    row[column] = _clean(value, MAX_CELL_CHARS)
        if any(key != LINK_KEY for key in row):
            out.append(row)
    return tuple(out)


def new_page_id() -> str:
    return uuid.uuid4().hex[:12]


def _file_name(title: str) -> str:
    stem = _FILE_RE.sub("-", title.lower()).strip("-")[:48] or "living-page"
    return f"{stem}.html"


# ------------------------------------------------------------------ rendering

_PAGE_CSS: Final[str] = """
.living-meta{margin-top:14px;display:flex;flex-wrap:wrap;gap:6px 18px;font-family:var(--mono);
  font-size:11.5px;letter-spacing:.04em;color:var(--ink-3)}
.living-meta .live{display:inline-flex;align-items:center;gap:7px}
.living-meta .dot{width:7px;height:7px;border-radius:50%;background:var(--ink-3)}
.living-meta .live.on .dot{background:var(--accent)}
.living-note{margin-top:14px;color:var(--ink-2);font-size:14px}
.empty{padding:28px 0;color:var(--ink-2)}
.table a{color:var(--ink);text-decoration:underline dotted;text-underline-offset:3px}
"""

# Writes "updated 10 minutes ago" in the viewer's locale and keeps it current.
# No network, no storage: the sandbox the page runs in allows neither anyway.
_RELATIVE_TIME_JS: Final[str] = """
(function(){
  var el=document.querySelector("[data-updated]");if(!el)return;
  var at=Number(el.getAttribute("data-updated"))*1000;
  function draw(){
    var s=Math.round((at-Date.now())/1000),a=Math.abs(s),v,u;
    if(a<60){v=s;u="second";}else if(a<3600){v=Math.round(s/60);u="minute";}
    else if(a<86400){v=Math.round(s/3600);u="hour";}else{v=Math.round(s/86400);u="day";}
    try{el.textContent=new Intl.RelativeTimeFormat(navigator.language||undefined,
      {numeric:"auto"}).format(v,u);}catch(e){el.textContent=new Date(at).toLocaleString();}
    el.setAttribute("title",new Date(at).toLocaleString());
  }
  draw();setInterval(draw,30000);
})();
"""


def _cell(row: dict[str, str], column: str, first: bool) -> str:
    text = escape(row.get(column, ""))
    link = row.get(LINK_KEY, "")
    if first and link and text:
        return (
            f'<a href="{escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{text}</a>"
        )
    return text


def render_html(page: LivingPage) -> str:
    """The page as one self-contained HTML document (no network, no storage)."""
    head_cells = "".join(f"<th>{escape(c)}</th>" for c in page.columns)
    body_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{_cell(row, column, index == 0)}</td>"
            for index, column in enumerate(page.columns)
        )
        + "</tr>"
        for row in page.rows
    )
    table = (
        '<div class="table-wrap"><table class="table">'
        f"<thead><tr>{head_cells}</tr></thead><tbody>{body_rows}</tbody></table></div>"
        if page.rows and page.columns
        else '<p class="empty">—</p>'
    )
    note = f'<p class="living-note">{escape(page.note)}</p>' if page.note else ""
    state = "live on" if page.refreshing else "live"
    count = len(page.rows)
    return (
        "<!doctype html>\n"
        f'<html lang="{escape(page.language or "en", quote=True)}"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(page.title)}</title>"
        f'<meta name="dodaios-living-page" content="{escape(page.id, quote=True)}">'
        f"<script>{THEME_BOOTSTRAP_JS}</script>"
        f"<style>{THEME_CSS}{_PAGE_CSS}</style>"
        "</head><body>"
        '<main class="wrap">'
        '<header class="masthead">'
        f"<h1>{escape(page.title)}</h1>"
        '<p class="living-meta">'
        f'<span class="{state}"><span class="dot" aria-hidden="true"></span>'
        f'<time data-updated="{int(page.updated_at)}"></time></span>'
        f'<span class="num">{count}</span>'
        "</p>"
        f"{note}"
        "</header>"
        f'<section class="section">{table}</section>'
        "</main>"
        f"<script>{_RELATIVE_TIME_JS}</script>"
        "</body></html>\n"
    )


# ---------------------------------------------------------------------- store


def outputs_root() -> Path:
    """The archive root new pages are written to."""
    from dodaios.core.paths import repo_root
    from dodaios.missions.isolation.worktree import resolve_outputs_root

    return resolve_outputs_root(repo_root())


def _readable_roots() -> tuple[Path, ...]:
    from dodaios.core.paths import repo_root
    from dodaios.missions.isolation.worktree import resolve_readable_outputs_roots

    return resolve_readable_outputs_roots(repo_root())


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=".living-", dir=target.parent)
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


def _from_state(data: dict[str, Any]) -> LivingPage:
    columns = tuple(str(c) for c in data.get("columns") or ())
    rows = tuple(
        {str(k): str(v) for k, v in row.items()}
        for row in data.get("rows") or ()
        if isinstance(row, dict)
    )
    return LivingPage(
        id=str(data["id"]),
        title=str(data.get("title") or ""),
        track=str(data.get("track") or ""),
        columns=columns,
        rows=rows,
        slug=str(data.get("slug") or ""),
        page_path=str(data.get("page_path") or ""),
        created_at=float(data.get("created_at") or 0.0),
        updated_at=float(data.get("updated_at") or 0.0),
        every_minutes=clamp_every(data.get("every_minutes")),
        task_id=str(data.get("task_id") or ""),
        refreshing=bool(data.get("refreshing")),
        note=str(data.get("note") or ""),
        language=str(data.get("language") or "en"),
    )


class LivingPageStore:
    """Reads and writes living pages under one or more archive roots.

    ``root`` is where new pages go; ``read_roots`` are searched for existing
    ones (the canonical root first). Plain files, no database: a page and its
    state live and die with their run directory.
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

    def _dir_of(self, page_id: str) -> Path | None:
        if not _ID_RE.match(page_id or ""):
            return None
        suffix = f"{SLUG_INFIX}{page_id}"
        for root in self._roots():
            try:
                for entry in root.iterdir():
                    if entry.name.endswith(suffix) and entry.is_dir():
                        return entry
            except OSError:  # a missing or unreadable root holds no pages; try the next
                continue
        return None

    def _write(self, run_dir: Path, page: LivingPage) -> None:
        state = page.to_dict()
        state.pop("visual_id", None)
        state.pop("page_url", None)
        _atomic_write(run_dir / page.page_path, render_html(page))
        _atomic_write(run_dir / STATE_FILE, json.dumps(state, ensure_ascii=False, indent=1))

    def create(
        self,
        *,
        title: str,
        track: str,
        columns: Any = None,
        rows: Any = None,
        every_minutes: Any = DEFAULT_EVERY_MINUTES,
        language: str = "en",
        note: str = "",
        now: float | None = None,
    ) -> LivingPage:
        from dodaios.missions.standalone_run import write_marker

        clean_title = _clean(title, MAX_TITLE_CHARS)
        clean_track = " ".join(str(track or "").split())[:MAX_TRACK_CHARS]
        if not clean_title:
            raise LivingPageError("'title' must name the page.")
        if not clean_track:
            raise LivingPageError("'track' must say what the page keeps current.")
        cols = normalize_columns(columns, rows)
        if not cols:
            raise LivingPageError("Give 'columns' (or rows with named fields) for the table.")
        clean_rows = normalize_rows(rows or [], cols)
        stamp = now if now is not None else time.time()
        page_id = new_page_id()
        slug = time.strftime("%Y%m%dT%H%M%S", time.gmtime(stamp)) + SLUG_INFIX + page_id
        page = LivingPage(
            id=page_id,
            title=clean_title,
            track=clean_track,
            columns=cols,
            rows=clean_rows,
            slug=slug,
            page_path="/".join((*PAGE_DIR, _file_name(clean_title))),
            created_at=stamp,
            updated_at=stamp,
            every_minutes=clamp_every(every_minutes),
            note=_clean(note, MAX_NOTE_CHARS),
            language=_clean(language, 8) or "en",
        )
        run_dir = self.root / slug
        write_marker(run_dir, kind=MARKER_KIND, title=clean_title)
        self._write(run_dir, page)
        log.info("living page %s created (%d rows)", page_id, len(clean_rows))
        return page

    def get(self, page_id: str) -> LivingPage | None:
        run_dir = self._dir_of(page_id)
        if run_dir is None:
            return None
        try:
            data = json.loads((run_dir / STATE_FILE).read_text(encoding="utf-8"))
            return _from_state(data)
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("living page %s: state unreadable", page_id, exc_info=True)
            return None

    def by_slug(self, slug: str) -> LivingPage | None:
        _, sep, page_id = (slug or "").rpartition(SLUG_INFIX)
        return self.get(page_id) if sep else None

    def list_pages(self) -> list[LivingPage]:
        pages: dict[str, LivingPage] = {}
        for root in self._roots():
            try:
                entries = [e for e in root.iterdir() if SLUG_INFIX in e.name and e.is_dir()]
            except OSError:  # a missing or unreadable root holds no pages
                continue
            for entry in entries:
                page_id = entry.name.rpartition(SLUG_INFIX)[2]
                if page_id in pages:
                    continue
                page = self.get(page_id)
                if page is not None:
                    pages[page_id] = page
        return sorted(pages.values(), key=lambda p: p.created_at, reverse=True)

    def save(self, page: LivingPage) -> LivingPage:
        run_dir = self._dir_of(page.id)
        if run_dir is None:
            raise LivingPageError(f"No living page with id {page.id!r}.")
        self._write(run_dir, page)
        return page

    def update_rows(
        self,
        page_id: str,
        *,
        rows: Any = None,
        columns: Any = None,
        note: str = "",
        now: float | None = None,
    ) -> LivingPage:
        """Replace the rows with a fresh, complete list (a refresh's result).

        ``rows=None`` keeps the old rows and only records ``note`` — the
        refresh could not read its sources and says so on the page.
        """
        page = self.get(page_id)
        if page is None:
            raise LivingPageError(f"No living page with id {page_id!r}.")
        cols = normalize_columns(columns, rows) if columns else page.columns
        cols = cols or page.columns
        new_rows = page.rows if rows is None else normalize_rows(rows, cols)
        updated = replace(
            page,
            columns=cols,
            rows=new_rows,
            note=_clean(note, MAX_NOTE_CHARS),
            updated_at=now if now is not None else time.time(),
        )
        return self.save(updated)

    def set_refresh(self, page_id: str, *, refreshing: bool, task_id: str = "") -> LivingPage:
        page = self.get(page_id)
        if page is None:
            raise LivingPageError(f"No living page with id {page_id!r}.")
        return self.save(replace(page, refreshing=refreshing, task_id=task_id))

    def set_every(self, page_id: str, every_minutes: Any) -> LivingPage:
        page = self.get(page_id)
        if page is None:
            raise LivingPageError(f"No living page with id {page_id!r}.")
        return self.save(replace(page, every_minutes=clamp_every(every_minutes)))


__all__ = [
    "DEFAULT_EVERY_MINUTES",
    "LINK_KEY",
    "MARKER_KIND",
    "SLUG_INFIX",
    "LivingPage",
    "LivingPageError",
    "LivingPageStore",
    "clamp_every",
    "normalize_columns",
    "normalize_rows",
    "outputs_root",
    "render_html",
]
