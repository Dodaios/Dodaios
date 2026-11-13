"""What every node page shares: the document around it, and safe text.

A node's page is one self-contained HTML file (no network, no storage), laid
out with the tokens and the block kit of :mod:`dodaios.artifacts.design_guide`
so a document, a deck and a dashboard read as one family, in the light and in
the dark theme. A type's renderer builds its own ``<body>`` content, styles
and script; :func:`document` puts the head, the theme and the shared page
script around them.

The helpers below are the only way text from a spec reaches a page: every
one of them escapes. A renderer never interpolates a spec value raw.
"""

from __future__ import annotations

import math
import re
from html import escape
from typing import Any, Final

from dodaios.artifacts.design_guide import PAGE_JS, THEME_BOOTSTRAP_JS, THEME_CSS

#: Schemes a link in a node may carry. Everything else is dropped to text.
_LINK_SCHEMES: Final[tuple[str, ...]] = ("https://", "http://", "mailto:")

#: Raster pictures a node may embed. No SVG: a data-URI SVG can carry script.
_IMAGE_DATA_RE: Final = re.compile(
    r"^data:image/(?:png|jpeg|jpg|gif|webp|avif);base64,[A-Za-z0-9+/=\s]+$"
)
MAX_IMAGE_CHARS: Final[int] = 400_000

_COLOR_RE: Final = re.compile(
    r"^(?:#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla)\([0-9a-zA-Z.,%/\s-]{1,60}\)|[a-zA-Z]{3,20})$"
)

#: The named colors a spec may use anywhere a color is asked for. They map to
#: the series tokens, so they hold their contrast in both themes.
NAMED_COLORS: Final[dict[str, str]] = {
    "blue": "var(--s1)",
    "orange": "var(--s2)",
    "green": "var(--s3)",
    "amber": "var(--s4)",
    "yellow": "var(--s4)",
    "violet": "var(--s5)",
    "purple": "var(--s5)",
    "pink": "var(--s6)",
    "accent": "var(--accent)",
    "ink": "var(--ink)",
    "muted": "var(--ink-2)",
    "good": "var(--good)",
    "warn": "var(--warn)",
    "bad": "var(--bad)",
}


def esc(value: Any) -> str:
    """Text for an element's content."""
    return escape(str(value if value is not None else ""), quote=False)


def attr(value: Any) -> str:
    """Text for an attribute value (inside double quotes)."""
    return escape(str(value if value is not None else ""), quote=True)


def clean(value: Any, limit: int) -> str:
    """One line of text: whitespace collapsed, clipped to ``limit``."""
    return " ".join(str(value if value is not None else "").split())[:limit].rstrip()


def clean_block(value: Any, limit: int) -> str:
    """Text that keeps its line breaks: trimmed, clipped to ``limit``."""
    text = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()[:limit]


def as_list(value: Any, limit: int) -> list[Any]:
    """``value`` as a list of at most ``limit`` items (a lone value becomes one item)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)[:limit]
    return [value]


def pick(value: Any, allowed: tuple[str, ...], default: str) -> str:
    """``value`` when it is one of ``allowed``, else ``default``."""
    name = str(value or "").strip().lower()
    return name if name in allowed else default


def number(value: Any) -> float | None:
    """A finite number from a JSON number or a numeric string, else ``None``."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).strip().replace(" ", "")
        try:
            result = float(text)
        except ValueError:  # not a number: the caller's default applies
            return None
    return result if math.isfinite(result) else None


def bounded(value: Any, low: float, high: float, default: float) -> float:
    """A number clamped into ``[low, high]``; ``default`` when it is none."""
    result = number(value)
    if result is None:
        return default
    return max(low, min(high, result))


def safe_link(value: Any) -> str:
    """The link when it is a web or mail address, else an empty string."""
    href = str(value or "").strip()
    return href if href.lower().startswith(_LINK_SCHEMES) and len(href) <= 2_000 else ""


def safe_image(value: Any) -> str:
    """An embedded raster picture (a ``data:`` URI), else an empty string.

    A node page runs without network, so a picture is either inside the page
    or not there at all.
    """
    src = str(value or "").strip()
    if len(src) > MAX_IMAGE_CHARS or not _IMAGE_DATA_RE.match(src):
        return ""
    return src


def color(value: Any, default: str = "") -> str:
    """A CSS color from a spec: a named token color, a hex or an rgb()/hsl().

    Returns ``default`` for anything else, so a spec can never inject a style.
    """
    text = str(value or "").strip()
    if not text:
        return default
    named = NAMED_COLORS.get(text.lower())
    if named:
        return named
    if text.startswith(("#", "rgb", "hsl")) and _COLOR_RE.match(text):
        return text
    return default


# --- inline text ---------------------------------------------------------------
#
# The little Markdown a single line may carry: **bold**, *italic*, `code` and
# [a link](https://…). Everything is escaped first; the marks are then read
# from the escaped text, so no tag from a spec ever survives.

_CODE_RE: Final = re.compile(r"`([^`\n]+)`")
_BOLD_RE: Final = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC_RE: Final = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_LINK_RE: Final = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def inline(value: Any, limit: int = 2_000) -> str:
    """One line of text as HTML, with bold, italic, code and links."""
    # NUL marks the held spans below; a spec must not be able to forge one.
    text = esc(clean(value, limit).replace("\x00", ""))
    held: list[str] = []

    def hold(html: str) -> str:
        held.append(html)
        return f"\x00{len(held) - 1}\x00"

    def code(match: re.Match[str]) -> str:
        return hold(f"<code>{match.group(1)}</code>")

    def link(match: re.Match[str]) -> str:
        href = safe_link(match.group(2).replace("&amp;", "&"))
        if not href:
            return match.group(1)
        # The address is held back so the marks below never read inside it;
        # the link's own text still takes bold and italic.
        opening = hold(f'<a href="{attr(href)}" rel="noopener noreferrer">')
        return f"{opening}{match.group(1)}{hold('</a>')}"

    text = _CODE_RE.sub(code, text)
    text = _LINK_RE.sub(link, text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], text)


def lines(value: Any, limit: int = 4_000) -> str:
    """Several lines of text as HTML: inline marks, line breaks kept."""
    return "<br>".join(inline(part) for part in clean_block(value, limit).split("\n"))


# --- the document --------------------------------------------------------------

#: What every node page adds to the kit: a full-height body for the types that
#: fill the window (a deck, a board, a film), and the small head a page opens
#: with.
NODE_CSS: Final[str] = """
html,body{height:100%}
body.fill{overflow:hidden}
.node-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 16px}
.node-head h1{flex:1 1 320px;min-width:0}
.node-meta{display:flex;flex-wrap:wrap;gap:6px 16px;margin-top:10px;font-size:14px;line-height:20px;
  color:var(--ink-2)}
.node-meta .live{display:inline-flex;align-items:center;gap:7px}
.node-meta .dot{width:7px;height:7px;border-radius:50%;background:var(--ink-3)}
.node-meta .live.on .dot{background:var(--accent)}
.node-note{margin-top:12px;color:var(--ink-2);font-size:14px;line-height:20px}
.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);
  white-space:nowrap}
"""

# Writes "updated 10 minutes ago" in the viewer's locale and keeps it current.
RELATIVE_TIME_JS: Final[str] = """
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


def upkeep_meta(node: Any) -> str:
    """The line under a kept-current node's title: when it was last refreshed.

    Empty for a node nobody keeps current, so an ordinary page carries no
    status line.
    """
    if not getattr(node, "track", ""):
        return ""
    state = "live on" if getattr(node, "refreshing", False) else "live"
    note = getattr(node, "note", "")
    line = (
        '<p class="node-meta">'
        f'<span class="{state}"><span class="dot" aria-hidden="true"></span>'
        f'<time data-updated="{int(getattr(node, "updated_at", 0))}"></time></span>'
        "</p>"
    )
    if note:
        line += f'<p class="node-note">{esc(note)}</p>'
    return line


def document(
    node: Any,
    *,
    body: str,
    css: str = "",
    js: str = "",
    body_class: str = "",
    kit_js: bool = True,
) -> str:
    """The node's page as one self-contained HTML document.

    Inputs:
        node: the :class:`~dodaios.nodes.model.Node` being rendered.
        body: the ``<body>`` content, already escaped HTML.
        css: the type's own styles, appended after the theme and the kit.
        js: the type's own script, run after the page script.
        body_class: ``"fill"`` for a type that fills the window and scrolls
            inside itself (a deck, a board, a film).
        kit_js: leave out the kit's page script (sortable tables, tooltips,
            the contents marker, links opened by the app) when the type
            handles its own pointer events.
    """
    language = attr(getattr(node, "language", "") or "en")
    scripts = f"<script>{RELATIVE_TIME_JS}</script>" if getattr(node, "track", "") else ""
    if kit_js:
        scripts += f"<script>{PAGE_JS}</script>"
    if js:
        scripts += f"<script>{js}</script>"
    klass = f' class="{attr(body_class)}"' if body_class else ""
    return (
        "<!doctype html>\n"
        f'<html lang="{language}"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(node.title)}</title>"
        f'<meta name="dodaios-node" content="{attr(node.id)}">'
        f'<meta name="dodaios-node-type" content="{attr(node.type)}">'
        f"<script>{THEME_BOOTSTRAP_JS}</script>"
        f"<style>{THEME_CSS}{NODE_CSS}{css}</style>"
        f"</head><body{klass}>"
        f"{body}"
        f"{scripts}"
        "</body></html>\n"
    )


__all__ = [
    "MAX_IMAGE_CHARS",
    "NAMED_COLORS",
    "NODE_CSS",
    "RELATIVE_TIME_JS",
    "as_list",
    "attr",
    "bounded",
    "clean",
    "clean_block",
    "color",
    "document",
    "esc",
    "inline",
    "lines",
    "number",
    "pick",
    "safe_image",
    "safe_link",
    "upkeep_meta",
]
