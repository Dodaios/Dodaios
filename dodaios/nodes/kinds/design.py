"""The ``design`` node: one freely designed visual.

A poster, an invitation, a one-pager, a social card, a landing-page mock-up.
Every other node type has a grammar and a renderer that lays it out; a design
has neither, because its layout IS the content. So this is the one type where
the model writes the markup and the styles itself, on the same tokens and the
same block kit as every other page.

Why the markup is cleaned although the page already runs in a sandbox without
network: a design is a picture, not a program. The spec is stored, patched,
reverted and shown on a library card; none of that should ever carry a script,
a form or a reference to another server, whatever frame the page is opened in
later. So ``normalize`` parses the markup and writes it out again from an
allowlist of elements and attributes. Text is escaped on the way out and
attributes are quoted, which makes the result safe by construction: nothing a
parser disagreement could do turns allowlisted output into running code. The
one raw channel is CSS, and it gets its own pass (no ``@import``, no
``url()`` beyond embedded pictures and ``#id``, no ``<`` inside a style
element). Both passes run until their output no longer changes, so
``normalize`` is idempotent.

Two ways to show a design: ``page`` puts the markup in a scrolling page as
wide as the window (a one-pager, a landing page); ``canvas`` puts it on an
artboard of an exact pixel size and scales the artboard to the window with
one transform (a poster, a card), so the design is laid out once and looks
the same at every size.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any, Final

from dodaios.nodes import shell
from dodaios.nodes.shell import attr, esc
from dodaios.nodes.types import NodeError

MAX_HTML_CHARS: Final[int] = 300_000
MAX_CSS_CHARS: Final[int] = 100_000
FITS: Final[tuple[str, ...]] = ("page", "canvas")
DEFAULT_SIZE: Final[tuple[int, int]] = (1080, 1350)
#: The size a ``page`` design reports to the library card.
PAGE_SIZE: Final[tuple[int, int]] = (1280, 800)
MIN_SIDE: Final[int] = 320
MAX_WIDTH: Final[int] = 4000
MAX_HEIGHT: Final[int] = 6000

_SPEC_HINT: Final[str] = (
    "A design spec is an object with 'html': the body markup of the visual as a string "
    "(no scripts, no external resources), plus optional 'css', 'fit', 'width', 'height' "
    "and 'background'."
)

# --- what a design may be made of ----------------------------------------------

_HTML_TAGS: Final[frozenset[str]] = frozenset(
    "a abbr address article aside b bdi bdo blockquote br button caption cite code col "
    "colgroup dd del details dfn div dl dt em fieldset figcaption figure footer h1 h2 h3 "
    "h4 h5 h6 header hgroup hr i img input ins kbd label legend li main mark meter nav ol "
    "optgroup option p pre progress q rp rt ruby s samp section select small span strong "
    "style sub summary sup table tbody td textarea tfoot th thead time tr u ul var wbr".split()
)
_VOID_TAGS: Final[frozenset[str]] = frozenset({"br", "col", "hr", "img", "input", "wbr"})

# The parser hands every name over in lower case; SVG names are case-sensitive,
# so each is written back the way SVG spells it.
_SVG_TAGS: Final[dict[str, str]] = {
    name.lower(): name
    for name in (
        "svg g defs symbol use path rect circle ellipse line polyline polygon text tspan "
        "textPath linearGradient radialGradient stop clipPath mask pattern marker title desc "
        "style a filter feBlend feColorMatrix feComponentTransfer feComposite "
        "feDisplacementMap feDropShadow feFlood feFuncA feFuncB feFuncG feFuncR "
        "feGaussianBlur feMerge feMergeNode feMorphology feOffset feTurbulence"
    ).split()
}

#: Elements that go together with everything inside them. Every other unknown
#: element is only unwrapped: its tag is dropped, its content stays.
_DROPPED_WHOLE: Final[frozenset[str]] = frozenset(
    "script iframe object noscript template title canvas audio video applet frameset "
    "noframes noembed math foreignobject animate set animatetransform animatemotion "
    "xmp plaintext listing".split()
)
#: Dropped elements that have no content, so they open nothing to skip.
_DROPPED_VOID: Final[frozenset[str]] = frozenset(
    "link meta base embed source track param area frame br col hr img input wbr".split()
)

_HTML_ATTRS: Final[frozenset[str]] = frozenset(
    "class id title lang dir role hidden tabindex alt width height colspan rowspan scope "
    "headers span start reversed value datetime cite open for placeholder checked disabled "
    "selected readonly multiple min max step low high optimum rows cols loading "
    "decoding".split()
)
_SVG_ATTRS: Final[dict[str, str]] = {
    name.lower(): name
    for name in (
        "class id lang role tabindex viewBox preserveAspectRatio xmlns xmlns:xlink version "
        "x y x1 y1 x2 y2 cx cy r rx ry d points width height transform fill fill-opacity "
        "fill-rule stroke stroke-width stroke-linecap stroke-linejoin stroke-dasharray "
        "stroke-dashoffset stroke-opacity stroke-miterlimit opacity color display visibility "
        "overflow vector-effect paint-order shape-rendering text-rendering mix-blend-mode "
        "offset stop-color stop-opacity gradientUnits gradientTransform spreadMethod fx fy fr "
        "patternUnits patternContentUnits patternTransform clip-path clip-rule clipPathUnits "
        "mask maskUnits maskContentUnits marker-start marker-mid marker-end markerWidth "
        "markerHeight markerUnits refX refY orient text-anchor dominant-baseline "
        "alignment-baseline baseline-shift font-family font-size font-weight font-style "
        "font-variant letter-spacing word-spacing text-decoration dx dy rotate textLength "
        "lengthAdjust startOffset method spacing pathLength filter filterUnits primitiveUnits "
        "in in2 result stdDeviation type values mode operator k1 k2 k3 k4 flood-color "
        "flood-opacity baseFrequency numOctaves seed stitchTiles scale xChannelSelector "
        "yChannelSelector radius color-interpolation-filters tableValues slope intercept "
        "amplitude exponent edgeMode"
    ).split()
}
_INPUT_TYPES: Final[frozenset[str]] = frozenset(
    "text email search tel url number checkbox radio range date time color".split()
)
_LIST_TYPES: Final[frozenset[str]] = frozenset({"1", "a", "A", "i", "I"})

_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DATA_ATTR_RE: Final = re.compile(r"(?:data|aria)-[a-z0-9_.\-]+")
_FRAGMENT_RE: Final = re.compile(r"#[\w\-.:]*")


def _plain(text: str) -> str:
    """``text`` without control characters (they also mark kept URLs below)."""
    return _CONTROL_RE.sub("", text)


def _settle(clean: Callable[[str], str], text: str) -> str:
    """``clean`` applied until its output no longer changes.

    Taking something out can leave something new behind ("ur" + "l(" around a
    removed token), and only a result that the cleaner maps to itself is one
    ``normalize`` may return twice. A text that never settles is dropped.
    """
    for _ in range(8):
        cleaned = clean(text)
        if cleaned == text:
            return cleaned
        text = cleaned
    return ""


# --- CSS -----------------------------------------------------------------------

_CSS_URL_RE: Final = re.compile(
    r"""url\s*\(\s*(?:"([^"]*)"|'([^']*)'|([^)"']*))\s*\)""", re.IGNORECASE
)
#: What a ``url()`` may point at: a picture inside the page. An SVG is fine
#: here, because a style sheet loads it as a still image without script.
_CSS_IMAGE_RE: Final = re.compile(
    r"data:image/(?:png|jpeg|jpg|gif|webp|avif|svg\+xml)[;,]", re.IGNORECASE
)
#: ``image-set()`` takes bare strings as addresses, so it goes as a whole.
_CSS_IMAGE_SET_RE: Final = re.compile(r"(?:-webkit-)?image-set\s*\([^()]*\)?", re.IGNORECASE)
_CSS_STRIP_RE: Final = re.compile(
    r"@import\b[^;{}]*;?|url\s*\(|expression\s*\(|(?:-webkit-)?image-set\s*\(|"
    r"(?:java|vb)\s*script\s*:|-moz-binding",
    re.IGNORECASE,
)
_HELD_RE: Final = re.compile(r"\x00(\d+)\x00")


def _css_unmasked(css: str) -> str:
    """``css`` without comments, and without escapes outside strings.

    A comment or an escape can spell a keyword the checks below would not
    recognize ("@im/**/port", "u\\72l("); inside a quoted string both are
    plain text and stay.
    """
    out: list[str] = []
    quote = ""
    index, size = 0, len(css)
    while index < size:
        char = css[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < size:
                out.append(css[index + 1])
                index += 1
            elif char in (quote, "\n"):
                quote = ""
        elif char in "\"'":
            quote = char
            out.append(char)
        elif css.startswith("/*", index):
            end = css.find("*/", index + 2)
            index = size if end < 0 else end + 1
            out.append(" ")
        elif char != "\\":
            out.append(char)
        index += 1
    return "".join(out)


def _css_pass(css: str, element: bool) -> str:
    held: list[str] = []

    def reference(match: re.Match[str]) -> str:
        target = next((group for group in match.groups() if group is not None), "").strip()
        if not (_FRAGMENT_RE.fullmatch(target) and len(target) > 1) and not (
            _CSS_IMAGE_RE.match(target)
        ):
            return "none"
        held.append(match.group(0).replace("<", "%3C"))
        return f"\x00{len(held) - 1}\x00"

    css = _CSS_URL_RE.sub(reference, _css_unmasked(_plain(css)))
    css = _CSS_IMAGE_SET_RE.sub("none", css)
    css = _CSS_STRIP_RE.sub("", css)
    css = _HELD_RE.sub(lambda match: held[int(match.group(1))], css)
    if element:
        # Inside a style element a "<" can only start a tag that ends it.
        css = css.replace("<", "")
    return css.strip()


def _clean_css(css: str, *, element: bool) -> str:
    """CSS that loads nothing and runs nothing.

    ``element`` is for the content of a style element; a ``style`` attribute
    is escaped on the way out and may keep its "<".
    """
    return _settle(lambda text: _css_pass(text, element), css)


# --- markup --------------------------------------------------------------------


def _attribute(tag: str, key: str, value: str, svg: bool) -> tuple[str, str] | None:
    """One attribute as it may stay (its SVG spelling and its value), or ``None``."""
    if key.startswith("on") or key == "srcdoc":
        return None
    if key == "style":
        css = _clean_css(value, element=False)
        return ("style", css) if css else None
    if key in ("href", "xlink:href"):
        link = value.strip()
        if not _FRAGMENT_RE.fullmatch(link):
            link = shell.safe_link(link) if tag == "a" and key == "href" else ""
        return (key, link) if link else None
    if _DATA_ATTR_RE.fullmatch(key):
        return key, value
    if svg:
        name = _SVG_ATTRS.get(key)
        if name is None:
            return None
        # fill="url(#grad)" stays, a reference to another server does not.
        return name, _clean_css(value, element=False) if "(" in value or "\\" in value else value
    if key == "src":
        picture = shell.safe_image(value) if tag == "img" else ""
        return ("src", picture) if picture else None
    if key == "type":
        if tag == "input" and value.lower() in _INPUT_TYPES:
            return "type", value.lower()
        return ("type", value) if tag == "ol" and value in _LIST_TYPES else None
    return (key, value) if key in _HTML_ATTRS else None


def _attributes(tag: str, attrs: list[tuple[str, str | None]], *, svg: bool) -> str | None:
    """The kept attributes as markup, or ``None`` when the element cannot stay."""
    seen: set[str] = set()
    kept: dict[str, str] = {}
    for raw_key, raw_value in attrs:
        key = raw_key.lower()
        if key in seen:
            continue
        seen.add(key)
        pair = _attribute(tag, key, _plain(raw_value or ""), svg)
        if pair is not None:
            kept[pair[0]] = pair[1]
    if tag == "img" and "src" not in kept:
        return None  # a picture from another server: the page could never load it
    if tag == "button":
        kept["type"] = "button"
    return "".join(f' {name}="{attr(value)}"' for name, value in kept.items())


class _Cleaner(HTMLParser):
    """Reads markup and writes the allowed part of it out again, balanced."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.dropped: list[str] = []
        self.css: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.dropped:
            if tag not in _DROPPED_VOID:
                self.dropped.append(tag)
            return
        svg = tag == "svg" or "svg" in self.open
        name = _SVG_TAGS.get(tag, "") if svg else tag if tag in _HTML_TAGS else ""
        if not name:
            if tag in _DROPPED_WHOLE:
                self.dropped.append(tag)
            return
        if name == "style":
            # Written when it closes, as one piece, and only if something is left.
            self.css = []
            self.open.append(name)
            return
        attributes = _attributes(name, attrs, svg=svg)
        if attributes is None:
            return
        self.out.append(f"<{name}{attributes}>")
        if name not in _VOID_TAGS:
            self.open.append(name)

    def handle_endtag(self, tag: str) -> None:
        if self.dropped:
            if tag in self.dropped:
                last = len(self.dropped) - 1 - self.dropped[::-1].index(tag)
                del self.dropped[last:]
            return
        for index in range(len(self.open) - 1, -1, -1):
            if self.open[index].lower() == tag:
                while len(self.open) > index:
                    self._close()
                return

    def handle_data(self, data: str) -> None:
        if self.dropped:
            return
        if self.css is not None:
            self.css.append(data)
        else:
            self.out.append(esc(_plain(data)))

    def _close(self) -> None:
        name = self.open.pop()
        if name != "style":
            self.out.append(f"</{name}>")
            return
        css = _clean_css("".join(self.css or []), element=True)
        self.css = None
        if css:
            self.out.append(f"<style>{css}</style>")

    def result(self) -> str:
        while self.open:
            self._close()
        return "".join(self.out).strip()


def _html_pass(markup: str) -> str:
    cleaner = _Cleaner()
    try:
        cleaner.feed(_plain(markup).replace("\r\n", "\n").replace("\r", "\n"))
        cleaner.close()
    except AssertionError as error:  # the parser gives up on a malformed <![ ]> section
        raise NodeError(
            "The 'html' could not be read: send plain body markup without <!DOCTYPE> or "
            "<![CDATA[ sections."
        ) from error
    return cleaner.result()


def clean_html(markup: str) -> str:
    """``markup`` as a picture: allowed elements and attributes only, no code."""
    return _settle(_html_pass, markup)


# --- normalize -----------------------------------------------------------------


def _background(value: Any) -> str:
    """The ground as the spec keeps it: a color name, a hex/rgb/hsl, or nothing."""
    text = " ".join(str(value or "").split())
    if text.lower() in shell.NAMED_COLORS:
        return text.lower()
    if text.startswith("#") and len(text) not in (4, 5, 7, 9):
        return ""
    return text if shell.color(text) else ""


def normalize(spec: Any) -> dict[str, Any]:
    """A clean design spec. Raises ``NodeError`` with one sentence for the model."""
    if isinstance(spec, str):
        spec = {"html": spec}
    if not isinstance(spec, dict):
        raise NodeError(_SPEC_HINT)
    markup = spec.get("html")
    if not isinstance(markup, str) or not markup.strip():
        raise NodeError(_SPEC_HINT)
    too_long = (
        f"'html' is too long: keep the design's markup under {MAX_HTML_CHARS} characters "
        "(simplify paths, shrink embedded pictures)."
    )
    if len(markup) > MAX_HTML_CHARS:
        raise NodeError(too_long)
    html = clean_html(markup)
    if not html:
        raise NodeError(
            "Nothing of 'html' is left after cleaning: send visible body markup (text, "
            "boxes, inline SVG), not scripts or embedded frames."
        )
    if len(html) > MAX_HTML_CHARS:
        raise NodeError(too_long)
    raw_css = spec.get("css")
    css = _settle(
        lambda text: _css_pass(text[:MAX_CSS_CHARS], True),
        raw_css if isinstance(raw_css, str) else "",
    )
    sized = any(shell.number(spec.get(side)) is not None for side in ("width", "height"))
    fit = shell.pick(spec.get("fit"), FITS, "canvas" if sized else "page")
    clean: dict[str, Any] = {"html": html, "css": css, "fit": fit}
    if fit == "canvas":
        clean["width"] = round(
            shell.bounded(spec.get("width"), MIN_SIDE, MAX_WIDTH, DEFAULT_SIZE[0])
        )
        clean["height"] = round(
            shell.bounded(spec.get("height"), MIN_SIDE, MAX_HEIGHT, DEFAULT_SIZE[1])
        )
    clean["background"] = _background(spec.get("background"))
    return clean


# --- the page ------------------------------------------------------------------

_PAGE_CSS: Final[str] = """
body{background:var(--design-bg,var(--bg))}
.design{min-height:100%;background:var(--design-bg,var(--bg))}
"""

_CANVAS_CSS: Final[str] = """
.design-stage{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;
  padding:32px;overflow:hidden;background:var(--bg-2)}
.design-fit{position:relative;flex:none;overflow:hidden;outline:1px solid var(--line-2)}
.design-art{position:absolute;left:0;top:0;overflow:hidden;transform-origin:0 0;
  background:var(--design-bg,var(--bg))}
@media (max-width:560px){.design-stage{padding:16px}}
@media print{body.fill{overflow:visible}
.design-stage{position:static;display:block;padding:0;background:none}
.design-fit{width:auto!important;height:auto!important;overflow:visible;outline:0}
.design-art{position:relative;transform:none!important}}
"""

# Fits the artboard into the window: one scale for both axes, never more than
# twice its size, measured again whenever the window changes.
_CANVAS_JS: Final[str] = """
(function(){
var stage=document.querySelector(".design-stage");if(!stage)return;
var fit=stage.querySelector(".design-fit"),art=fit&&fit.querySelector(".design-art");
if(!art)return;
var W=+fit.getAttribute("data-w"),H=+fit.getAttribute("data-h");
function size(){
  var cs=getComputedStyle(stage);
  var w=stage.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
  var h=stage.clientHeight-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom);
  var fw=Math.max(1,Math.floor(W*Math.min(w/W,h/H,2))),s=fw/W;
  fit.style.width=fw+"px";fit.style.height=Math.round(H*s)+"px";
  art.style.transform="scale("+s.toFixed(5)+")";}
size();addEventListener("resize",size);
})();
"""


def render(node: Any) -> str:
    """The design as one self-contained page, scrolling or on its artboard."""
    spec = normalize(node.spec)
    ground = shell.color(spec["background"])
    # ``shell.color`` returns a token, a hex or an rgb()/hsl() of digits only,
    # so the value can stand in a style sheet as it is.
    css = f":root{{--design-bg:{ground}}}" if ground else ""
    if spec["fit"] == "page":
        return shell.document(
            node,
            body=f'<main class="design">{spec["html"]}</main>',
            css=css + _PAGE_CSS + spec["css"],
        )
    width, height = int(spec["width"]), int(spec["height"])
    size = f"width:{width}px;height:{height}px"
    body = (
        '<div class="design-stage">'
        f'<div class="design-fit" data-w="{width}" data-h="{height}" style="{size}">'
        f'<main class="design design-art" style="{size}">{spec["html"]}</main>'
        "</div></div>"
    )
    page = f"@page{{size:{width}px {height}px;margin:0}}"
    return shell.document(
        node,
        body=body,
        css=css + _CANVAS_CSS + page + spec["css"],
        js=_CANVAS_JS,
        body_class="fill",
    )


# --- the library card, the starter, the guide ----------------------------------


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """What the library draws on a design's card: its ground and its proportions."""
    fit = shell.pick(spec.get("fit"), FITS, "page")
    width, height = PAGE_SIZE
    if fit == "canvas":
        width = round(shell.bounded(spec.get("width"), MIN_SIDE, MAX_WIDTH, DEFAULT_SIZE[0]))
        height = round(shell.bounded(spec.get("height"), MIN_SIDE, MAX_HEIGHT, DEFAULT_SIZE[1]))
    return {
        "background": shell.color(spec.get("background")),
        "fit": fit,
        "width": int(width),
        "height": int(height),
    }


_STARTER_HTML: Final[str] = (
    '<section class="cover">'
    '<svg class="cover-art" viewBox="0 0 400 400" aria-hidden="true">'
    '<circle cx="400" cy="0" r="130"/><circle cx="400" cy="0" r="230"/>'
    '<circle cx="400" cy="0" r="330"/><circle class="dot" cx="237.4" cy="162.6" r="9"/>'
    "</svg>"
    '<div class="cover-body"><h1>{title}</h1>'
    '<p class="cover-lead">One line that says what this is.</p></div>'
    '<dl class="cover-facts">'
    "<div><dt>When</dt><dd>Date</dd></div>"
    "<div><dt>Where</dt><dd>Place</dd></div>"
    "<div><dt>Who</dt><dd>Name</dd></div>"
    "</dl></section>"
)

_STARTER_CSS: Final[str] = (
    ".cover{position:relative;display:grid;grid-template-rows:1fr auto;"
    "gap:clamp(32px,7vh,72px);min-height:100vh;padding:clamp(24px,6vw,88px);overflow:hidden}"
    ".cover-art{position:absolute;top:0;right:0;width:min(58vw,84vh);height:min(58vw,84vh)}"
    ".cover-art circle{fill:none;stroke:var(--line-2);stroke-width:1.5;"
    "vector-effect:non-scaling-stroke}"
    ".cover-art .dot{fill:var(--accent);stroke:none}"
    ".cover-body{position:relative;align-self:end}"
    ".cover h1{max-width:14em;font-size:clamp(40px,VWvw,MAXpx);line-height:1;font-weight:650;"
    "letter-spacing:-.04em}"
    ".cover-lead{max-width:32em;margin-top:clamp(16px,2.4vw,28px);"
    "font-size:clamp(17px,1.6vw,22px);line-height:1.45;color:var(--ink-2)}"
    ".cover-facts{position:relative;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));"
    "gap:24px;padding-top:20px;border-top:1px solid var(--line-2);font-size:14px;"
    "line-height:20px}"
    ".cover-facts dt{color:var(--ink-2)}"
    ".cover-facts dd{margin-top:2px;font-weight:500}"
)


def starter(title: str, language: str) -> dict[str, Any]:
    """A one-screen cover that shows the node's title.

    ``language`` is accepted for the contract; the few placeholder words are
    English and are replaced with the first real edit.
    """
    name = shell.clean(title, 120) or "Untitled"
    # A short title is set large; a long one steps down so it stays a few lines.
    scale, largest = ("8.6", "128") if len(name) <= 18 else ("6.4", "96")
    if len(name) > 44:
        scale, largest = "4.6", "68"
    return normalize(
        {
            "html": _STARTER_HTML.replace("{title}", esc(name)),
            "css": _STARTER_CSS.replace("VW", scale).replace("MAX", largest),
            "fit": "page",
        }
    )


EXAMPLE: Final[dict[str, Any]] = {
    "fit": "canvas",
    "width": 1080,
    "height": 1350,
    "html": (
        '<section class="poster"><p>14 June, 7 pm</p><h1>Summer<br>Concert</h1>'
        '<svg viewBox="0 0 400 40"><path d="M0 20q25-36 50 0t50 0 50 0 50 0 50 0 50 0 50 0 '
        '50 0"/></svg><p>Town Hall. Free entry.</p></section>'
    ),
    "css": (
        ".poster{display:grid;grid-template-rows:auto 1fr auto auto;gap:48px;height:100%;"
        "padding:96px;font-size:40px;color:var(--ink-2)}"
        ".poster h1{align-self:end;font-size:210px;line-height:.9;letter-spacing:-.045em;"
        "color:var(--ink)}"
        ".poster path{fill:none;stroke:var(--accent);stroke-width:3}"
    ),
}

GUIDE: Final[str] = (
    "design: one freely designed visual (poster, invitation, one-pager, social card, "
    "landing-page mock-up). You write the markup and the styles.\n"
    'Spec: {"html": body markup, "css": styles, "fit": "page" | "canvas", "width": px, '
    '"height": px, "background": color}\n'
    '- "page" (default): a scrolling page as wide as the window, for one-pagers and '
    "landing pages. Make it fluid (grid, %, clamp()).\n"
    '- "canvas": a fixed artboard scaled to fit the window, for posters and cards. Give '
    "width and height (default 1080 x 1350; 1080 x 1080 square, 1920 x 1080 wide) and lay "
    "out in px for exactly that size.\n"
    "- background: a hex or a token color name; default the page ground.\n"
    "The theme is already on the page. Color tokens, which switch between the light and "
    "the dark theme: --bg, --bg-2, --bg-3 (grounds), --ink, --ink-2, --ink-3 (text), "
    "--line, --line-2 (hairlines), --accent, --accent-soft, --good, --warn, --bad (each "
    "with -soft), --s1 to --s6 (series). Also --font, --mono, --radius. Build on them and "
    "on color-mix() of them so the design reads in both themes; set a fixed hex only "
    "together with its own ground. Kit classes: .card, .chip, .btn, .table, .metrics, "
    ".callout, .steps, .bars, .muted, .num.\n"
    "Not allowed, and removed: scripts, iframes, forms, event handlers, web fonts, "
    "external images, url(http...), @import. Type through var(--font). Graphics as inline "
    "<svg> colored through CSS (stroke 1.5 to 1.75 for icons), pictures as data:image "
    "URIs, links as https:// or #id.\n"
    "Art direction: one idea and one focal point. A clear grid with generous margins. "
    "Strong hierarchy: one large headline (tight tracking, line-height near 1), one "
    "supporting line, small quiet details. Restrained color: ink on the ground plus one "
    "accent. Hairlines, not shadows; no gradients, no emoji, no decorative chips, no "
    "filler copy. Use the real names, dates and numbers.\n"
    'Revise with {"op":"replace","path":"/css" or "/html","find":passage,"value":text}.\n'
    "Example:\n" + json.dumps(EXAMPLE, ensure_ascii=False, separators=(",", ":"))
)

__all__ = [
    "EXAMPLE",
    "FITS",
    "GUIDE",
    "clean_html",
    "normalize",
    "preview",
    "render",
    "starter",
]
