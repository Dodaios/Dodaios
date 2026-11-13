"""Reports: a long answer kept as a page, so the chat itself stays short.

The person asks something whose full answer is a document: the important
mails of the week, a comparison, a research summary, a plan. Read in the
chat, a document breaks the conversation into a wall of text. So the
assistant writes the full answer into a report, and the chat gets two or
three sentences plus a card that opens the report.

The assistant writes the Markdown itself, in the turn that read the sources.
This module only lays it out: one self-contained HTML page in the artifact
design standard (:mod:`.design_guide`), written into the run archive like a
living page, so the Artifacts section, the Downloads mirror and the cleanup
sweep all see it. No worker, no model call, no network.

Layout of one report on disk::

    <outputs_root>/<stamp>__report__<id>/
        .standalone-run.json                      (kind "report")
        tasks/report/artifacts/files/<file>.html  (the page)
        tasks/report/artifacts/files/<file>.md    (the Markdown it was made from)
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from html import escape, unescape
from pathlib import Path
from typing import Any, Final

from dodaios.artifacts.design_guide import PAGE_JS, THEME_BOOTSTRAP_JS, THEME_CSS
from dodaios.artifacts.living import _atomic_write, outputs_root
from dodaios.artifacts.report_blocks import upgrade_blocks

log = logging.getLogger(__name__)

#: Marker kind of a report's run directory (``missions/standalone_run``).
MARKER_KIND: Final[str] = "report"
#: The run-directory infix that names a report.
SLUG_INFIX: Final[str] = "__report__"
PAGE_DIR: Final[tuple[str, ...]] = ("tasks", "report", "artifacts", "files")

MAX_TITLE_CHARS: Final[int] = 120
MAX_SUMMARY_CHARS: Final[int] = 600
MAX_BODY_CHARS: Final[int] = 200_000

_FILE_RE: Final = re.compile(r"[^a-z0-9]+")
_SECTION_RE: Final = re.compile(r"^ {0,3}##\s+\S", re.MULTILINE)


class ReportError(ValueError):
    """A request the writer refuses, with a sentence the model can act on."""


@dataclass(frozen=True)
class Report:
    """One written report."""

    id: str
    title: str
    summary: str
    slug: str
    page_path: str
    """Posix path inside the run, as ``/api/outputs/{slug}/artifacts`` lists it."""
    sections: int
    created_at: float

    @property
    def visual_id(self) -> str:
        """``slug::path`` — the Artifacts stage's address of this page."""
        return f"{self.slug}::{self.page_path}"


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def _stem(title: str) -> str:
    return _FILE_RE.sub("-", title.lower()).strip("-")[:48] or "report"


def count_sections(markdown: str) -> int:
    """How many ``##`` sections the report has (code fences are not skipped; a
    heading inside one is rare enough to only miscount a label)."""
    return len(_SECTION_RE.findall(markdown or ""))


# ------------------------------------------------------------------ rendering

# The report body is flat Markdown output (h2, p, table, …), not the kit's
# nested sections, so the kit's rhythm is restated here for direct children:
# 64px before a section heading, 20px around a block, 12px between paragraphs.
# Every rule has the same weight (`:where` adds none), so the later one wins:
# keep them in this order.
_PAGE_CSS: Final[str] = """
.report{margin-top:8px}
.report>*+*{margin-top:12px}
.report>:where(.table-wrap,blockquote,pre,ul,ol,dl,.card,.callout,.metrics){margin-top:20px}
.report>:where(.table-wrap,blockquote,pre,dl,.card,.callout,.metrics)+*{margin-top:20px}
.report>:where(h3,h4){margin-top:32px;font-size:16px;line-height:1.5;font-weight:600}
.report>:where(h1,h2){margin-top:64px;scroll-margin-top:24px;font-size:22px;line-height:1.3;
  letter-spacing:-.01em}
.report>:where(h1,h2)+*{margin-top:12px}
.report>:where(h3,h4)+*{margin-top:8px}
.report li>p{margin:0}
.report li>ul,.report li>ol{margin-top:8px}
.report blockquote{padding:14px 18px;border-radius:var(--radius);background:var(--bg-2)}
.report blockquote>*+*{margin-top:8px}
.report>dl{display:grid;grid-template-columns:minmax(96px,132px) 1fr;font-size:14px;
  line-height:20px}
.report>dl dt,.report>dl dd{padding:12px 0;border-bottom:1px solid var(--line)}
.report>dl dt{padding-right:16px;color:var(--ink-2)}
.report>dl dt:last-of-type,.report>dl dd:last-of-type{border-bottom:0}
.report-date{margin-top:12px}
"""

_TABLE_OPEN: Final = re.compile(r"<table>")
_TABLE_CLOSE: Final = re.compile(r"</table>")

#: The label of the contents box, by page language.
_CONTENTS_LABEL: Final[dict[str, str]] = {
    "de": "Auf dieser Seite",
    "en": "On this page",
    "es": "En esta página",
    "pt": "Nesta página",
}
#: From this many sections on, the page opens with a contents box.
MIN_SECTIONS_FOR_CONTENTS: Final[int] = 4


@dataclass(frozen=True)
class RenderedBody:
    """The report body as HTML, plus its ``##`` sections for the contents box."""

    html: str
    sections: tuple[tuple[str, str], ...] = ()
    """``(id, heading text)`` per section, in page order."""


def render_body(markdown: str, language: str = "en") -> RenderedBody:
    """The report body as HTML. Raw HTML in the Markdown is shown as text,
    never run: a report often quotes mails and web pages the person did not
    write. Charts, metric rows, callouts, steps and source lists become kit
    blocks (:mod:`.report_blocks`). Falls back to escaped paragraphs when the
    Markdown library is absent."""
    sections: list[tuple[str, str]] = []
    try:
        import markdown as md_lib  # a base dependency; the fallback keeps a report readable

        converter = md_lib.Markdown(extensions=["extra", "sane_lists", "toc"])
        # Raw HTML blocks and inline tags become literal text.
        converter.preprocessors.deregister("html_block")
        converter.inlinePatterns.deregister("html")
        body = converter.convert(markdown)
        for token in getattr(converter, "toc_tokens", None) or ():
            if token.get("level") == 2 and token.get("id") and token.get("name"):
                sections.append((str(token["id"]), unescape(str(token["name"]))))
    except Exception:  # noqa: BLE001 — a report must still be written
        log.info("report: markdown renderer unavailable, writing plain paragraphs")
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", markdown) if p.strip()]
        body = "".join(
            "<p>" + escape(p).replace("\n", "<br>") + "</p>" for p in paragraphs
        )
    body = upgrade_blocks(body, language)
    body = _TABLE_OPEN.sub('<div class="table-wrap"><table class="table" data-sort>', body)
    return RenderedBody(html=_TABLE_CLOSE.sub("</table></div>", body), sections=tuple(sections))


def markdown_to_html(markdown: str) -> str:
    """The report body as HTML (see :func:`render_body`)."""
    return render_body(markdown).html


def _contents_box(sections: tuple[tuple[str, str], ...], language: str) -> str:
    if len(sections) < MIN_SECTIONS_FOR_CONTENTS:
        return ""
    label = _CONTENTS_LABEL.get((language or "").strip().lower()[:2], _CONTENTS_LABEL["en"])
    links = "".join(
        f'<a href="#{escape(anchor, quote=True)}">{escape(name)}</a>' for anchor, name in sections
    )
    return (
        f'<nav class="toc" aria-label="{escape(label, quote=True)}">'
        f'<p class="toc-label">{escape(label)}</p>{links}</nav>'
    )


def render_html(
    *, title: str, summary: str, markdown: str, language: str, created_at: float
) -> str:
    """The report as one self-contained HTML document (no network, no storage).

    The plain document of the design standard: the report's name, the summary,
    when it was written, a contents box from four sections on, then the body.
    """
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
    lead = f'<p class="summary">{escape(summary)}</p>' if summary else ""
    body = render_body(markdown, language)
    return (
        "<!doctype html>\n"
        f'<html lang="{escape(language or "en", quote=True)}"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<script>{THEME_BOOTSTRAP_JS}</script>"
        f"<style>{THEME_CSS}{_PAGE_CSS}</style>"
        "</head><body>"
        '<main class="page">'
        f"<h1>{escape(title)}</h1>"
        f"{lead}"
        f'<p class="caption report-date"><time>{escape(stamp)}</time></p>'
        f"{_contents_box(body.sections, language)}"
        f'<article class="report">{body.html}</article>'
        "</main>"
        f"<script>{PAGE_JS}</script>"
        "</body></html>\n"
    )


# -------------------------------------------------------------------- restyle

# What marks a page laid out before 2026-11-13 (the editorial kit), and where
# that page kept the facts the Markdown beside it does not carry on their own.
_DATED_MARK: Final = 'class="masthead"'
_OLD_SUMMARY_RE: Final = re.compile(r'<p class="standfirst">(.*?)</p>', re.DOTALL)
_OLD_STAMP_RE: Final = re.compile(r'<p class="eyebrow"><time>(.*?)</time></p>')
_PAGE_LANG_RE: Final = re.compile(r'<html lang="([^"]*)"')
_PAGE_TITLE_RE: Final = re.compile(r"<title>(.*?)</title>", re.DOTALL)


def restyle_if_dated(page: Path) -> bool:
    """Lay out a report from before the plain look again, in the plain look.

    A report page is a rendering of the Markdown saved beside it, so an old
    page can be drawn anew without losing a word: the title, the summary, the
    language and the time come from the old page, the body from the ``.md``.
    The file keeps its modification time (the Artifacts section sorts by it).
    Returns True when the page was rewritten; a page that is already current,
    has no Markdown beside it or cannot be read is left exactly as it is.
    """
    try:
        html = page.read_text(encoding="utf-8")
        source = page.with_suffix(".md")
        if _DATED_MARK not in html or not source.is_file():
            return False
        found_title = _PAGE_TITLE_RE.search(html)
        title = unescape(found_title.group(1)).strip() if found_title else ""
        if not title:
            return False
        found_summary = _OLD_SUMMARY_RE.search(html)
        summary = unescape(found_summary.group(1)).strip() if found_summary else ""
        found_lang = _PAGE_LANG_RE.search(html)
        stat = page.stat()
        created_at = stat.st_mtime
        found_stamp = _OLD_STAMP_RE.search(html)
        if found_stamp:
            try:
                created_at = time.mktime(time.strptime(found_stamp.group(1), "%Y-%m-%d %H:%M"))
            except (ValueError, OverflowError):  # an unreadable stamp: the file's time stands
                created_at = stat.st_mtime
        body = source.read_text(encoding="utf-8").replace("\r\n", "\n")
        for head in (f"# {title}", summary):
            if head and body.lstrip().startswith(head):
                body = body.lstrip()[len(head):]
        _atomic_write(
            page,
            render_html(
                title=title,
                summary=summary,
                markdown=body.strip(),
                language=found_lang.group(1) if found_lang else "en",
                created_at=created_at,
            ),
        )
        os.utime(page, (stat.st_atime, stat.st_mtime))
    except (OSError, UnicodeDecodeError):
        log.info("report: could not restyle %s", page.name, exc_info=True)
        return False
    log.info("report: %s laid out again in the plain look", page.name)
    return True


# ---------------------------------------------------------------------- write


def write_report(
    *,
    title: str,
    markdown: str,
    summary: str = "",
    language: str = "en",
    root: Path | None = None,
    now: float | None = None,
) -> Report:
    """Write one report page into the archive and return where it is.

    Raises:
        ReportError: the title or the body is missing.
        OSError: the archive could not be written.
    """
    from dodaios.missions.standalone_run import write_marker

    clean_title = _clean(title, MAX_TITLE_CHARS)
    clean_summary = _clean(summary, MAX_SUMMARY_CHARS)
    body = str(markdown or "").replace("\r\n", "\n").strip()[:MAX_BODY_CHARS]
    if not clean_title:
        raise ReportError("'title' must name the report in a few words.")
    if not body:
        raise ReportError("'markdown' must hold the report's full text.")
    # A model often repeats the title as the first heading; the page has it.
    first, _, rest = body.partition("\n")
    if first.lstrip("# ").strip().lower() == clean_title.lower() and first.startswith("#"):
        body = rest.strip() or body
    stamp = now if now is not None else time.time()
    report_id = uuid.uuid4().hex[:12]
    slug = time.strftime("%Y%m%dT%H%M%S", time.gmtime(stamp)) + SLUG_INFIX + report_id
    lang = _clean(language, 8) or "en"
    stem = _stem(clean_title)
    page_path = "/".join((*PAGE_DIR, f"{stem}.html"))
    run_dir = (root if root is not None else outputs_root()) / slug
    write_marker(run_dir, kind=MARKER_KIND, title=clean_title)
    _atomic_write(
        run_dir / page_path,
        render_html(
            title=clean_title,
            summary=clean_summary,
            markdown=body,
            language=lang,
            created_at=stamp,
        ),
    )
    md_head = f"# {clean_title}\n\n" + (f"{clean_summary}\n\n" if clean_summary else "")
    _atomic_write(run_dir.joinpath(*PAGE_DIR, f"{stem}.md"), md_head + body + "\n")
    report = Report(
        id=report_id,
        title=clean_title,
        summary=clean_summary,
        slug=slug,
        page_path=page_path,
        sections=count_sections(body),
        created_at=stamp,
    )
    log.info("report %s written (%d chars, %d sections)", report_id, len(body), report.sections)
    return report


__all__ = [
    "MARKER_KIND",
    "MIN_SECTIONS_FOR_CONTENTS",
    "SLUG_INFIX",
    "RenderedBody",
    "Report",
    "ReportError",
    "count_sections",
    "markdown_to_html",
    "render_body",
    "render_html",
    "restyle_if_dated",
    "write_report",
]
