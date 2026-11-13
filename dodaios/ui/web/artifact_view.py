"""Render a text/markdown artifact into a standalone, styled HTML page.

Used by GET /api/outputs/{slug}/files/{path}/view so the user can "open in
browser" a markdown deliverable and see it rendered (headings, tables, lists)
instead of raw '#'-prefixed text. The page is self-contained (inline CSS) and is
served with a strict no-script CSP (see VIEW_CSP in outputs_routes) so a
malicious/hallucinated artifact can never execute JS in the app origin.

Degrades gracefully: if the optional `markdown` library is unavailable, the raw
text is shown escaped inside <pre> so the base install never hard-fails.
"""

from __future__ import annotations

import html
import logging

from dodaios.artifacts.design_guide import THEME_CSS

log = logging.getLogger(__name__)

_MARKDOWN_EXT = (".md", ".markdown")

# No-script CSP for the /view page (referenced by outputs_routes). Neutralizes
# XSS from artifact content rendered in the app origin.
VIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:;"

# VIEW_CSP as a response HEADER. The ``sandbox`` directive is honoured only in
# a header (a <meta> CSP ignores it), and it puts the document in an opaque
# origin even when it is opened top-level in a browser tab rather than inside
# the app's sandboxed iframe — so a worker-written file can never act as the
# app origin, whatever the script-src says.
VIEW_HEADER_CSP = VIEW_CSP + " sandbox;"

# The artifact-page CSP (``/files/{path}/page`` in outputs_routes): an artifact
# is a self-contained page a worker wrote to be LOOKED AT and used — tabs,
# filters, a chart drawn on canvas — so inline scripts run. What stays shut is
# every way out: no network of any kind (no fetch, no remote script, font,
# image or frame), no forms posting anywhere, no navigation. The script runs in
# an opaque origin that cannot reach the app's cookies, storage or API — the
# same model Claude artifacts use. The frontend frames the page with
# ``sandbox="allow-scripts"``, but "Open in browser" loads the same URL as a
# top-level tab, where no iframe sandbox exists: there the ``sandbox
# allow-scripts`` directive below is the ONLY thing keeping the page out of
# the app origin (without it, one ``window.open('/')`` hands the page a
# same-origin window whose ``fetch`` reaches every API route). It also blocks
# popups, forms and top-level navigation. ``/view`` and inline downloads keep
# VIEW_HEADER_CSP: those are arbitrary worker files, not artifacts.
ARTIFACT_PAGE_CSP = (
    "sandbox allow-scripts; "
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "font-src data:; "
    "media-src data: blob:; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "base-uri 'none';"
)

# The artifact design standard (dodaios/artifacts/design_guide.py): the same
# tokens in both palettes, so a Markdown output opened in the browser looks
# like the page it sits next to in the Artifacts section — and follows the
# app's theme through the same `?theme=light|dark` query the artifact stage
# appends, stamped on <html> by the SERVER (the page stays script-free under
# VIEW_CSP; the guide's scripts are for pages that may run them). The tokens
# and the kit are the guide's verbatim; only the document rules below are
# this page's own: Markdown output is flat, so the rhythm is restated for it.
_PAGE_CSS = (
    THEME_CSS + "\n"
    "main>*+*{margin-top:12px}"
    "main>h1,main>h2{margin-top:64px}"
    "main>h1{font-size:22px;line-height:1.3;letter-spacing:-.01em}"
    "main>.artifact-name+*{margin-top:8px}"
    "main>h3,main>h4{margin-top:32px;font-size:16px;line-height:1.5;font-weight:600}"
    "main>h3+*,main>h4+*{margin-top:8px}"
    "main>table,main>pre,main>blockquote,main>*+ul,main>*+ol{margin-top:20px}"
    "main li>p{margin:0}main li>ul,main li>ol{margin-top:8px}"
    "table{display:block;overflow-x:auto;border-collapse:collapse;font-size:14px;"
    "line-height:20px}"
    "th,td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}"
    "th{font-weight:500}"
    "blockquote{padding:14px 18px;border-radius:var(--radius);background:var(--bg-2)}"
    "img{max-width:100%;border-radius:var(--radius-sm)}"
)


_THEMES = frozenset({"light", "dark"})


def _shell(title: str, body_html: str, theme: str | None) -> str:
    stamp = f" data-theme='{theme}'" if theme in _THEMES else ""
    return (
        f"<!doctype html><html lang='en'{stamp}><head><meta charset='utf-8'>"
        f'<meta http-equiv="Content-Security-Policy" content="{VIEW_CSP}">'
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{_PAGE_CSS}</style></head>"
        f"<body><main class='page'><p class='artifact-name caption'>{html.escape(title)}</p>"
        f"{body_html}</main></body></html>"
    )


def render_artifact_html(filename: str, text: str, *, theme: str | None = None) -> str:
    """Return a complete HTML document rendering *text*.

    Markdown filenames are rendered to HTML via the `markdown` library; everything
    else (and the no-markdown-lib fallback) is shown escaped in <pre>. *theme*
    (``light`` / ``dark``, anything else ignored) pins the palette the way the
    app's Artifacts stage pins it; without it the page follows the OS. Never raises.
    """
    if filename.lower().endswith(_MARKDOWN_EXT):
        try:
            import markdown  # lazy: optional dep; base install may lack it

            body = markdown.markdown(
                text,
                extensions=["extra", "sane_lists", "tables", "fenced_code"],
            )
            return _shell(filename, body, theme)
        except Exception as exc:  # noqa: BLE001 — a view must never 500
            log.info("markdown render unavailable (%s) — serving raw <pre>", exc)
    return _shell(filename, f"<pre>{html.escape(text)}</pre>", theme)


__all__ = ["ARTIFACT_PAGE_CSP", "VIEW_CSP", "VIEW_HEADER_CSP", "render_artifact_html"]
