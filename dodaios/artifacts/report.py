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
import re
import time
import uuid
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Final

from dodaios.artifacts.design_guide import GIGI_MARK_SVG, THEME_BOOTSTRAP_JS, THEME_CSS
from dodaios.artifacts.living import _atomic_write, outputs_root

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

_PAGE_CSS: Final[str] = """
.wrap{max-width:860px}
.report{margin-top:8px}
.report>*+*{margin-top:14px}
.report h1{font-size:26px;margin-top:44px}
.report h2{margin-top:44px;padding-bottom:10px;border-bottom:1px solid var(--line)}
.report h3{margin-top:28px}
.report h2+*,.report h3+*{margin-top:12px}
.report p,.report li{line-height:1.65}
.report ul,.report ol{padding-left:22px;max-width:72ch}
.report li+li{margin-top:6px}
.report li>p{margin:0}
.report strong{font-weight:600}
.report blockquote{margin:0;padding:12px 18px;background:var(--bg-2);
  border-left:3px solid var(--accent);border-radius:0 var(--radius) var(--radius) 0;
  color:var(--ink-2)}
.report pre{background:var(--sunken);padding:12px 14px;border-radius:var(--radius-sm);
  overflow-x:auto;line-height:1.5}
.report :not(pre)>code{background:var(--bg-3);padding:1px 5px;border-radius:var(--radius-sm)}
.report hr{border:0;border-top:1px solid var(--line);margin:32px 0}
.report .table-wrap{margin-top:16px}
"""

_TABLE_OPEN: Final = re.compile(r"<table>")
_TABLE_CLOSE: Final = re.compile(r"</table>")


def markdown_to_html(markdown: str) -> str:
    """The report body as HTML. Raw HTML in the Markdown is shown as text,
    never run: a report often quotes mails and web pages the person did not
    write. Falls back to escaped paragraphs when the Markdown library is absent."""
    try:
        import markdown as md_lib  # a base dependency; the fallback keeps a report readable

        converter = md_lib.Markdown(extensions=["extra", "sane_lists"])
        # Raw HTML blocks and inline tags become literal text.
        converter.preprocessors.deregister("html_block")
        converter.inlinePatterns.deregister("html")
        body = converter.convert(markdown)
    except Exception:  # noqa: BLE001 — a report must still be written
        log.info("report: markdown renderer unavailable, writing plain paragraphs")
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", markdown) if p.strip()]
        body = "".join(
            "<p>" + escape(p).replace("\n", "<br>") + "</p>" for p in paragraphs
        )
    body = _TABLE_OPEN.sub('<div class="table-wrap"><table class="table">', body)
    return _TABLE_CLOSE.sub("</table></div>", body)


def render_html(
    *, title: str, summary: str, markdown: str, language: str, created_at: float
) -> str:
    """The report as one self-contained HTML document (no network, no storage)."""
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
    standfirst = f'<p class="standfirst">{escape(summary)}</p>' if summary else ""
    return (
        "<!doctype html>\n"
        f'<html lang="{escape(language or "en", quote=True)}"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<script>{THEME_BOOTSTRAP_JS}</script>"
        f"<style>{THEME_CSS}{_PAGE_CSS}</style>"
        "</head><body>"
        '<main class="wrap">'
        '<header class="masthead">'
        f'<p class="eyebrow"><time>{escape(stamp)}</time></p>'
        f"<h1>{escape(title)}</h1>"
        f"{standfirst}"
        "</header>"
        f'<article class="report">{markdown_to_html(markdown)}</article>'
        '<footer class="colophon">'
        f'<span class="brand">{GIGI_MARK_SVG}Dodaios</span>'
        "</footer>"
        "</main>"
        "</body></html>\n"
    )


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
    # A model often repeats the title as the first heading; the masthead has it.
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
    "SLUG_INFIX",
    "Report",
    "ReportError",
    "count_sections",
    "markdown_to_html",
    "render_html",
    "write_report",
]
