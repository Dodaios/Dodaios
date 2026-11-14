"""The ``docs`` node: a document the person reads, keeps and has revised.

Why the spec is Markdown and not a grammar of blocks: the assistant already
writes its long answers as Markdown, and the report pipeline
(:mod:`dodaios.artifacts.report`) already lays that Markdown out with charts,
metric rows, callouts, steps and source lists. A document node is the same
text with a longer life, so it takes the same text. A second grammar would
only give the model two ways to write one thing, and the page two renderers
that drift apart.

What this module adds on top of the report page is what a KEPT document needs:

* the page is a rendering of the spec, so it is drawn again on every revision
  (no date line; the upkeep line says when a kept-current document was read);
* a reading measure of 720 px, and on a wide window the contents box moves
  beside the text and follows the reader;
* two marks the Markdown library leaves as text and the document editor
  offers (``editors/docs`` in the frontend): ``~~struck~~`` text and checklist
  items (``- [ ]`` / ``- [x]``), drawn here as struck text and ticked boxes;
* a last pass over the rendered body. Markdown lets its writer set attributes
  and link anywhere, and a document often quotes mails and web pages the
  person did not write: no event handler, no style, no script address and no
  picture from the network reaches the page.

Pure functions, no I/O.
"""

from __future__ import annotations

import json
import re
import textwrap
from html import unescape
from typing import Any, Final

# The report's own page rules and contents box: one look for a report and a
# document, kept in one place.
from dodaios.artifacts.report import _PAGE_CSS, _contents_box, render_body
from dodaios.nodes import shell
from dodaios.nodes.types import NodeError

MAX_SUMMARY_CHARS: Final[int] = 600
MAX_BODY_CHARS: Final[int] = 200_000

#: What the card in the library shows of a document.
PREVIEW_LINES: Final[int] = 5
PREVIEW_LINE_CHARS: Final[int] = 64
PREVIEW_HEADING_CHARS: Final[int] = 60

_WHAT_TO_SEND: Final[str] = (
    "A docs node's spec is an object {\"summary\": \"…\", \"markdown\": \"…\"}; "
    "'markdown' must hold the document's full text as Markdown."
)

# Control characters have no place in a document, and both the Markdown
# library and the inline reader use some of them as their own placeholders.
_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


# ------------------------------------------------------------------ normalize


def _line(value: Any, limit: int) -> str:
    """One clipped line. Trimmed again after the cut, so a second pass keeps it."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    return shell.clean(_CONTROL_RE.sub(" ", str(value)), limit).rstrip()


def normalize(spec: Any) -> dict[str, Any]:
    """The document's clean spec: ``{"summary", "markdown"}``.

    Raises:
        NodeError: the spec is not an object, or it carries no text.
    """
    if not isinstance(spec, dict):
        raise NodeError(_WHAT_TO_SEND)
    body = spec.get("markdown")
    if not isinstance(body, str):
        raise NodeError(_WHAT_TO_SEND)
    text = _CONTROL_RE.sub("", body.replace("\r\n", "\n").replace("\r", "\n"))
    text = shell.clean_block(text, MAX_BODY_CHARS).rstrip()
    if not text:
        raise NodeError(_WHAT_TO_SEND)
    return {"summary": _line(spec.get("summary"), MAX_SUMMARY_CHARS), "markdown": text}


# --------------------------------------------------------------------- render

# Every tag of the rendered body goes through `_tag`. The Markdown library and
# the report blocks write tags in one fixed form (double-quoted, escaped
# attribute values), so anything that looks like a tag but is not in that form
# was not written by them and is shown as text.
_ANY_TAG_RE: Final = re.compile(r"<[^>]*>")
_OPEN_TAG_RE: Final = re.compile(
    r'<([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^\s<>="\'/]+(?:="[^"]*")?)*)\s*(/?)>'
)
_CLOSE_TAG_RE: Final = re.compile(r"</([a-zA-Z][a-zA-Z0-9]*)>")
_ATTRIBUTE_RE: Final = re.compile(r'([^\s<>="\'/]+)(?:="([^"]*)")?')
#: Attributes that load or send something, wherever they stand.
_FETCHING: Final = frozenset(
    {
        "action", "background", "data", "formaction", "lowsrc", "manifest", "ping", "poster",
        "srcdoc", "srcset", "target", "xlink:href",
    }
)
#: The inline styles the pipeline writes itself: a chart mark's value or
#: series slot, and a table column's alignment.
_OWN_STYLE_RE: Final = re.compile(
    r"^(?:--[a-z]{1,8}:[A-Za-z0-9().\- ]{1,40}|text-align: ?(?:left|right|center));?$"
)
_HEADING_RE: Final = re.compile(r'<h2(?:\s[^>]*?)?\sid="([^"]+)"[^>]*>(.*?)</h2>', re.DOTALL)
_STRIP_TAGS_RE: Final = re.compile(r"<[^>]*>")


def _tag(match: re.Match[str]) -> str:
    """One tag of the body, without what a document must not carry."""
    whole = match.group(0)
    closing = _CLOSE_TAG_RE.fullmatch(whole)
    if closing:
        # The page's only h1 is the node's title.
        return "</h2>" if closing.group(1).lower() == "h1" else whole
    opening = _OPEN_TAG_RE.fullmatch(whole)
    if not opening:
        return shell.esc(whole)
    name = opening.group(1)
    lowered = name.lower()
    kept: list[str] = []
    picture = ""
    alt = ""
    for found in _ATTRIBUTE_RE.finditer(opening.group(2)):
        key, raw = found.group(1), found.group(2)
        low = key.lower()
        value = unescape(raw or "")
        if low.startswith("on") or low in _FETCHING:
            continue
        if low == "style" and not _OWN_STYLE_RE.match(value):
            continue
        if low == "href":
            if not (value.startswith("#") or shell.safe_link(value)):
                continue
        if low == "src":
            picture = shell.safe_image(value) if lowered == "img" else ""
            if not picture:
                continue
        if low == "alt":
            alt = value
        kept.append(key if raw is None else f'{key}="{raw}"')
    if lowered == "img" and not picture:
        # The page has no network: a picture from an address is its description.
        return shell.esc(alt)
    if lowered == "h1":
        name = "h2"
    attributes = "".join(f" {item}" for item in kept)
    return f"<{name}{attributes}{' /' if opening.group(3) else ''}>"


# The library writes ``~~`` and ``[ ]`` as text. Both are read from the
# rendered body: code keeps its characters, and a strike never runs across a
# block (a paragraph, an item, a cell). Control characters cannot be in a
# document (`normalize` drops them), so one can stand in for "~~" meanwhile.
_CODE_OR_TAG_RE: Final = re.compile(r"(<pre\b.*?</pre>|<code\b.*?</code>|<[^>]*>)", re.DOTALL)
_STRIKE_MARK: Final[str] = "\x01"
_STRIKE_RE: Final = re.compile(
    "\x01(?=[^\\s\x01])((?:(?!\x01|</?(?:p|li|h[1-6]|td|th|dd|dt|blockquote|ul|ol|div|table|tr)\\b).)+?)"
    "(?<=[^\\s\x01])\x01",
    re.DOTALL,
)
_TASK_RE: Final = re.compile(r"<li>(\s*(?:<p>)?)\[([ xX])\](?:\s+|(?=</))")


def _strike_and_tasks(html: str) -> str:
    """``~~text~~`` as struck text and ``[ ]``/``[x]`` items as checklist items."""
    parts = _CODE_OR_TAG_RE.split(html)
    for index in range(0, len(parts), 2):  # text between tags and code
        parts[index] = parts[index].replace("~~", _STRIKE_MARK)
    html = _STRIKE_RE.sub(r"<del>\1</del>", "".join(parts)).replace(_STRIKE_MARK, "~~")

    def task(match: re.Match[str]) -> str:
        ticked = " checked" if match.group(2) in "xX" else ""
        return f'<li class="task">{match.group(1)}<input type="checkbox" disabled{ticked}> '

    return _TASK_RE.sub(task, html)


def _harden(html: str) -> str:
    """The rendered body with every tag checked (see the module docstring)."""
    return _ANY_TAG_RE.sub(_tag, html)


def _sections(html: str) -> tuple[tuple[str, str], ...]:
    """``(id, heading text)`` of every section of the hardened body."""
    found = []
    for anchor, inner in _HEADING_RE.findall(html):
        name = unescape(_STRIP_TAGS_RE.sub("", inner)).strip()
        if name:
            found.append((unescape(anchor), name))
    return tuple(found)


def _without_title(markdown: str, title: str) -> str:
    """The body without a first heading that only repeats the node's title."""
    first, _, rest = markdown.lstrip().partition("\n")
    if first.startswith("#") and first.strip("# \t").lower() == title.strip().lower():
        return rest.strip()
    return markdown


_CSS: Final[str] = _PAGE_CSS + """
::selection{background:var(--accent-soft)}
.page.doc{max-width:768px}
.doc-head .lead{margin-top:14px;font-size:18px;line-height:28px;color:var(--ink-2);
  text-wrap:pretty}
.doc-head .node-meta{margin-top:16px}
.doc>.toc{margin-top:28px}
.doc .report{margin-top:36px;padding-top:36px;border-top:1px solid var(--line);line-height:1.65}
.doc .report>:first-child{margin-top:0}
.doc .report>p,.doc .report li,.doc .report dd{text-wrap:pretty}
.doc .report>:where(h5,h6){font-size:14px;line-height:20px;color:var(--ink-2)}
.doc .report ul:not([class])>li::marker{color:var(--ink-3)}
.doc .report blockquote{padding:0 0 0 20px;border-left:2px solid var(--line-2);border-radius:0;
  background:none;color:var(--ink-2)}
.doc .report img{display:block;max-width:100%;height:auto;border-radius:8px}
.doc .report pre{font-size:13px;line-height:20px;tab-size:2}
.doc .report .table{font-variant-numeric:tabular-nums}
.doc .plot{overflow-x:auto}
.doc .plot svg{min-width:480px}
.doc .report .card,.doc .report .callout,.doc .report .steps,.doc .report .links,
.doc .report .metrics{line-height:1.5}
.doc .report a:not([href]){color:inherit;text-decoration:none}
.doc .report sup{font-size:.75em;line-height:0}
.doc .report del{color:var(--ink-2)}
.doc .report li.task{position:relative;list-style:none}
.doc .report li.task>input,.doc .report li.task>p>input:first-child{position:absolute;left:-1.6em;
  top:.3em;width:15px;height:15px;margin:0;accent-color:var(--accent)}
.doc .report sup a{text-decoration:none}
.doc .footnote{margin-top:48px;font-size:14px;line-height:20px;color:var(--ink-2)}
.doc .footnote hr{margin:0 0 16px}
.doc .footnote-backref{text-decoration:none}
@media screen and (min-width:1280px){
.page.doc.has-toc{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,720px) minmax(0,1fr);
  max-width:none}
.doc.has-toc>*{grid-column:2}
.doc.has-toc>.report{grid-row:2}
.doc.has-toc>.toc{grid-column:3;grid-row:2;position:sticky;top:32px;align-self:start;gap:0;
  width:216px;max-height:calc(100vh - 64px);overflow-y:auto;margin:72px 0 0 48px;padding:0;
  border:0;border-radius:0}
.doc.has-toc .toc-label,.doc.has-toc .toc a{margin:0;border-left:1px solid var(--line);
  border-radius:0}
.doc.has-toc .toc-label{padding:0 0 6px 16px}
.doc.has-toc .toc a{padding:4px 4px 4px 16px;white-space:normal}
.doc.has-toc .toc a:hover{background:none}
.doc.has-toc .toc a.is-current{border-left-color:var(--ink)}
}
@media (max-width:560px){.doc .chart .tick,.doc .chart .mark-label{font-size:13px}
.doc-head .lead{font-size:17px;line-height:26px}}
@media print{.page.doc{max-width:none}.doc .report{border-top:0;padding-top:0}
.doc>.toc{break-inside:avoid}.doc .plot{overflow:visible}.doc .plot svg{min-width:0}}
"""

# The kit's script sorts a table on a click only; a column head must answer
# to the keyboard too. A plot that scrolls inside its card opens at its end,
# where the latest value is.
_JS: Final[str] = """
(function(){var d=document;
Array.prototype.forEach.call(d.querySelectorAll(".plot"),
  function(p){p.scrollLeft=p.scrollWidth;});
Array.prototype.forEach.call(d.querySelectorAll("table[data-sort] thead th"),
  function(th){th.tabIndex=0;});
d.addEventListener("keydown",function(e){
  if(e.key!=="Enter"&&e.key!==" ")return;
  var th=e.target.closest?e.target.closest("table[data-sort] thead th"):null;
  if(th){e.preventDefault();th.click();}});
})();
"""


def render(node: Any) -> str:
    """The document as one self-contained page: title, summary, contents, body."""
    spec = node.spec if isinstance(node.spec, dict) else {}
    language = str(getattr(node, "language", "") or "en")
    summary = _line(spec.get("summary"), MAX_SUMMARY_CHARS)
    markdown = _without_title(str(spec.get("markdown") or ""), str(node.title))
    body = _harden(_strike_and_tasks(render_body(markdown, language).html))
    # A plot is drawn on a fixed frame; on a narrow window it scrolls inside
    # its card instead of shrinking until its labels cannot be read.
    body = body.replace("<svg ", '<div class="plot"><svg ').replace("</svg>", "</svg></div>")
    contents = _contents_box(_sections(body), language)
    # What the reader can write into themselves in edit mode (`nodes/bridge.py`):
    # the title, the summary, and the body. The body is drawn from Markdown, so
    # its field shows the Markdown while it is edited and the page is drawn
    # again afterwards.
    lead = f'<p class="lead" data-at="/summary">{shell.esc(summary)}</p>' if summary else ""
    source = shell.attr(str(spec.get("markdown") or ""))
    page = (
        f'<main class="page doc{" has-toc" if contents else ""}">'
        f'<header class="doc-head"><h1 data-at="@title">{shell.esc(node.title)}</h1>{lead}'
        f"{shell.upkeep_meta(node)}</header>"
        f"{contents}"
        f'<article class="report" data-at="/markdown" data-src="{source}" data-multiline '
        f"data-refresh>{body}</article>"
        "</main>"
    )
    return shell.document(node, body=page, css=_CSS, js=_JS)


# -------------------------------------------------------------------- preview

_FENCE_RE: Final = re.compile(r"^(?:```|~~~)")
_ATX_RE: Final = re.compile(r"^#{1,6}\s+(.*?)\s*#*$")
_ITEM_RE: Final = re.compile(r"^(?:[-*+]|\d{1,3}[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
# `&#8203;` alone is the document editor's separator between two quotes or
# two lists (it draws nothing).
_SKIPPED_RE: Final = re.compile(
    r"^(?:[|>]|!\[|\{:|={3,}$|-{3,}$|\*{3,}$|_{3,}$|\[\^[^\]]+\]:|&#8203;$)"
)
_MD_IMAGE_RE: Final = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK_RE: Final = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_NOTE_RE: Final = re.compile(r"\[\^[^\]]+\]|\{:[^}]*\}")
_MD_MARK_RE: Final = re.compile(r"\*\*|__|~~|`|(?<!\w)[*_]|[*_](?!\w)")


def _plain(text: str) -> str:
    """A line of Markdown as the words a reader sees."""
    text = _MD_IMAGE_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_NOTE_RE.sub("", text)
    # Character references (the editor writes "&#126;" for a literal "~") are read as the page reads them.
    return " ".join(unescape(_MD_MARK_RE.sub("", text)).split())


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _blocks(markdown: str) -> list[tuple[str, list[str]]]:
    """The body as ``("heading" | "text" | "list", lines)`` in reading order.

    A reader for the card only: it knows headings, paragraphs and top-level
    list items, and steps over everything else (code, charts, tables, quotes).
    """
    blocks: list[tuple[str, list[str]]] = []
    fenced = False
    open_kind = ""
    for raw in markdown.split("\n"):
        line = raw.strip()
        if _FENCE_RE.match(line):
            fenced = not fenced
            open_kind = ""
            continue
        if fenced:
            continue
        if not line or _SKIPPED_RE.match(line):
            open_kind = ""
            continue
        heading = _ATX_RE.match(line)
        if heading:
            blocks.append(("heading", [_plain(heading.group(1))]))
            open_kind = ""
            continue
        item = _ITEM_RE.match(line)
        indented = raw.startswith(("  ", "\t"))
        if item and not (indented and open_kind == "list"):
            if open_kind != "list":
                blocks.append(("list", []))
                open_kind = "list"
            blocks[-1][1].append(_plain(item.group(1)))
            continue
        if open_kind == "list":
            if not item:  # the item's text runs on; a nested item is left out
                blocks[-1][1][-1] = f"{blocks[-1][1][-1]} {_plain(line)}".strip()
            continue
        if open_kind != "text":
            blocks.append(("text", [""]))
            open_kind = "text"
        blocks[-1][1][0] = f"{blocks[-1][1][0]} {_plain(line)}".strip()
    return [(kind, [entry for entry in entries if entry]) for kind, entries in blocks]


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """The card's view of a document: its first heading and the lines under it."""
    markdown = str(spec.get("markdown") or "") if isinstance(spec, dict) else ""
    blocks = [block for block in _blocks(markdown) if block[1]]
    first = next((index for index, (kind, _) in enumerate(blocks) if kind == "heading"), None)
    heading = _clip(blocks[first][1][0], PREVIEW_HEADING_CHARS) if first is not None else ""
    after = [block for block in blocks[(first or 0) :] if block[0] != "heading"]
    before = [block for block in blocks[: first or 0] if block[0] != "heading"]
    content = after or before
    lines: list[str] = []
    bullets = bool(content) and content[0][0] == "list"
    if bullets:
        lines = [_clip(entry, PREVIEW_LINE_CHARS) for entry in content[0][1]]
    else:
        for kind, entries in content:
            if kind != "text" or len(lines) >= PREVIEW_LINES:
                break
            lines.extend(textwrap.wrap(entries[0], PREVIEW_LINE_CHARS))
    return {"heading": heading, "lines": lines[:PREVIEW_LINES], "bullets": bullets}


# -------------------------------------------------------------------- starter


def starter(title: str, language: str) -> dict[str, Any]:
    """A fresh document: three short parts that show what a document holds.

    The page shows the title itself, and the few placeholder words are the
    same in every language, so neither argument changes the text.
    """
    return normalize(
        {
            "summary": "A short summary: what this document is about and what it concludes.",
            "markdown": (
                "## Overview\n\n"
                "Write the opening here. Ask the assistant to fill this document, "
                "to revise a part of it, or to keep it current.\n\n"
                "> [!NOTE]\n"
                "> **Good to know** A document can hold tables, charts, key figures, "
                "notes like this one, steps and sources.\n\n"
                "## Details\n\n"
                "| Item | Status | Owner |\n"
                "| --- | --- | --- |\n"
                "| First item | Open | – |\n"
                "| Second item | Open | – |\n\n"
                "## Next steps\n\n"
                "1. **First step** What happens first.\n"
                "2. **Second step** What follows.\n"
            ),
        }
    )


# ---------------------------------------------------------------------- guide

EXAMPLE: Final[dict[str, Any]] = {
    "summary": (
        "Three hosting plans compared on 12 Nov 2026. Alpha is the cheapest and the only one "
        "with an EU region; Beta has more integrations. Support quality was not tested."
    ),
    "markdown": (
        "## Result\n\n"
        "Alpha costs **19 €** per seat and month, 8 € less than Beta.\n\n"
        "```chart\n"
        '{"type": "bar", "title": "Price per seat (€/month)", '
        '"x": ["Alpha", "Beta", "Gamma"], "data": [19, 27, 24]}\n'
        "```\n\n"
        "> [!TIP]\n"
        "> **Recommendation** Start with Alpha; move only if an integration is missing.\n\n"
        "## Sources\n\n"
        "- [Alpha pricing](https://alpha.example/pricing)\n"
        "- [Beta pricing](https://beta.example/pricing)\n"
    ),
}

GUIDE: Final[str] = (
    """\
docs: a document the person reads (a report, a plan, notes, a comparison).
spec = {"summary": str, "markdown": str}
- summary (optional, up to 600 chars): two to four sentences that already answer. Shown \
under the title.
- markdown (required): the whole body. The node's title is the page's h1, so do not repeat \
it. Sections are "## " headings (four or more get a contents box), "### " inside them.
Markdown: paragraphs, **bold**, *italic*, ~~struck~~, `code`, [links](https://…), lists, \
checklists ("- [ ] open", "- [x] done"), tables (a "--:" column is right-aligned), quotes, \
fenced code, footnotes. Nest a list by four spaces. Raw HTML is shown as text. \
Pictures from an address are not loaded (the page has no network): say what they show.
Blocks beyond plain Markdown:
- a fenced "chart" block holding one JSON object {"type": "line"|"area"|"column"|"bar", \
"title", "x": [labels], "series": [{"name", "data": [numbers]}] or "data": [numbers], \
"unit", "note"}; "x" and every "data" have the same length, 2 or more points;
- a fenced "metrics" block, one "value | label | detail" per line (up to 6);
- a quote that opens with [!NOTE], [!TIP], [!IMPORTANT], [!WARNING] or [!CAUTION] is a \
callout; a **bold** opening is its title;
- a numbered list whose items each open with a **bold title** becomes steps;
- a list whose items are each one link becomes the source list (last, under "## Sources").
Write statements: numbers with their unit, dates, names. Short paragraphs, plain headings.
To revise: {"op": "replace", "path": "/markdown", "find": exact passage, "value": new text} \
for an edit, {"op": "append", "path": "/markdown", "value": "\\n\\n## New section\\n…"} to add \
at the end; set /markdown again only for a rewrite.
Example:
"""
    + json.dumps(EXAMPLE, ensure_ascii=False)
)


__all__ = [
    "EXAMPLE",
    "GUIDE",
    "MAX_BODY_CHARS",
    "MAX_SUMMARY_CHARS",
    "normalize",
    "preview",
    "render",
    "starter",
]
