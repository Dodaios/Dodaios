"""The design node type: the cleaned markup, its page and its library card."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from typing import Any

import pytest

from dodaios.nodes.kinds import design
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError

PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8AAAAMB"
    "AQDJ/pLvAAAAAElFTkSuQmCC"
)


def _node(spec: dict[str, Any], *, title: str = "Poster") -> Node:
    return Node(
        id="0123456789ab",
        type="design",
        title=title,
        spec=spec,
        slug="s",
        page_path="p.html",
        created_at=1_700_000_000,
        updated_at=1_700_000_500,
    )


def _clean(markup: str) -> str:
    return design.normalize({"html": markup})["html"]


def _css(css: str) -> str:
    return design.normalize({"html": "<p>x</p>", "css": css})["css"]


class _Tags(HTMLParser):
    """Collects every start tag with its attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def _tags(page: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = _Tags()
    parser.feed(page)
    parser.close()
    return parser.tags


# ---------------------------------------------------------------- normalize


def test_normalize_fills_the_defaults_and_is_idempotent() -> None:
    spec = design.normalize({"html": " <h1>Hello</h1> ", "junk": 1})

    assert spec == {"html": "<h1>Hello</h1>", "css": "", "fit": "page", "background": ""}
    assert design.normalize(spec) == spec
    assert design.normalize("<h1>Hello</h1>") == spec


def test_a_canvas_has_a_bounded_artboard() -> None:
    default = design.normalize({"html": "<p>x</p>", "fit": "canvas"})
    sized = design.normalize({"html": "<p>x</p>", "width": "1920", "height": 1080.4})
    huge = design.normalize({"html": "<p>x</p>", "fit": "canvas", "width": 9e9, "height": 1})

    assert (default["width"], default["height"]) == (1080, 1350)
    # A size without a fit can only mean an artboard.
    assert (sized["fit"], sized["width"], sized["height"]) == ("canvas", 1920, 1080)
    assert (huge["width"], huge["height"]) == (4000, 320)
    assert isinstance(sized["width"], int) and isinstance(sized["height"], int)
    assert design.normalize(sized) == sized
    assert "width" not in design.normalize({"html": "<p>x</p>", "fit": "page", "width": 900})


def test_background_is_a_color_or_nothing() -> None:
    def ground(value: Any) -> str:
        return design.normalize({"html": "<p>x</p>", "background": value})["background"]

    assert ground("Blue") == "blue"
    assert ground("#0B1F3A") == "#0B1F3A"
    assert ground("rgb(10, 20, 30)") == "rgb(10, 20, 30)"
    assert ground("red;} body{display:none") == ""
    assert ground("url(https://example.org/x.png)") == ""
    assert ground("#12345") == ""


@pytest.mark.parametrize(
    ("spec", "needle"),
    [
        (None, "'html'"),
        (["<p>x</p>"], "'html'"),
        ({}, "'html'"),
        ({"html": "   "}, "'html'"),
        ({"html": 42}, "'html'"),
        ({"html": "<script>alert(1)</script><iframe src='x'></iframe>"}, "left after cleaning"),
        ({"html": "<p>" + "x" * design.MAX_HTML_CHARS + "</p>"}, "too long"),
    ],
)
def test_an_unusable_spec_is_refused_with_one_sentence(spec: Any, needle: str) -> None:
    with pytest.raises(NodeError) as raised:
        design.normalize(spec)

    message = str(raised.value)
    assert needle in message
    assert message.endswith(".") and "\n" not in message


def test_css_is_clipped_to_its_limit() -> None:
    css = _css(".a{color:red}" * 20_000)

    assert len(css) <= design.MAX_CSS_CHARS
    assert _css(css) == css


# ------------------------------------------------------------- the cleaner


def test_scripts_frames_and_embeds_are_removed_with_their_content() -> None:
    html = _clean(
        "<h1>Kept</h1>"
        "<script>alert(1)</script>"
        "<SCRIPT src='https://evil.example/x.js'></SCRIPT>"
        "<iframe src='https://evil.example'><p>inside</p></iframe>"
        "<object data='x.swf'><p>fallback</p></object>"
        "<embed src='x.swf'>"
        "<noscript><p>hidden</p></noscript>"
        "<template><p>template</p></template>"
        "<p>After</p>"
    )

    assert html == "<h1>Kept</h1><p>After</p>"


def test_head_furniture_is_removed_and_a_whole_document_is_unwrapped() -> None:
    html = _clean(
        "<!DOCTYPE html><html><head><title>Tab title</title>"
        '<meta http-equiv="refresh" content="0;url=https://evil.example">'
        '<link rel="stylesheet" href="https://evil.example/x.css">'
        '<base href="https://evil.example/"></head>'
        "<body onload='alert(1)'><!-- a comment --><p>Body</p></body></html>"
    )

    assert html == "<p>Body</p>"


def test_a_form_is_unwrapped_and_its_controls_are_inert() -> None:
    html = _clean(
        '<form action="https://evil.example" method="post">'
        '<input type="email" name="mail" placeholder="you@example.org" formaction="x">'
        '<input type="file"><input type="hidden" value="t">'
        '<button type="submit" formaction="https://evil.example">Join</button></form>'
    )

    assert "<form" not in html and "evil.example" not in html and "action" not in html
    assert '<input type="email" placeholder="you@example.org">' in html
    assert '<input><input value="t">' in html
    assert '<button type="button">Join</button>' in html


def test_event_handlers_and_srcdoc_are_removed_from_every_element() -> None:
    html = _clean(
        '<div onclick="alert(1)" ONMOUSEOVER="alert(2)" class="box" srcdoc="<p>x</p>">'
        '<svg onload="alert(3)" viewBox="0 0 1 1"><circle r="1" onfocus="alert(4)"/></svg>'
        '<a href="#top" onpointerdown="alert(5)">Top</a></div>'
    )

    assert "alert" not in html and "srcdoc" not in html
    assert not any(name.startswith("on") for _, attrs in _tags(html) for name in attrs)
    assert html.startswith('<div class="box"><svg viewBox="0 0 1 1"><circle r="1"></circle>')


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        " JaVaScRiPt:alert(1)",
        "java\tscript:alert(1)",
        "&#106;avascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "//evil.example/x",
    ],
)
def test_a_link_that_is_not_a_web_or_page_address_loses_its_target(href: str) -> None:
    assert _clean(f'<a href="{href}" target="_blank">Go</a>') == "<a>Go</a>"


def test_web_mail_and_fragment_links_stay() -> None:
    html = _clean(
        '<a href="https://example.org/a?b=1&amp;c=2">Web</a>'
        '<a href="mailto:hello@example.org">Mail</a><a href="#plans">Plans</a>'
    )

    assert '<a href="https://example.org/a?b=1&amp;c=2">Web</a>' in html
    assert '<a href="mailto:hello@example.org">Mail</a>' in html
    assert '<a href="#plans">Plans</a>' in html


def test_only_embedded_raster_pictures_stay() -> None:
    html = _clean(
        f'<img src="{PNG}" alt="Kept" width="40" onerror="alert(1)">'
        '<img src="https://example.org/track.png" alt="External">'
        '<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=" alt="Vector">'
        '<img src="x" onerror="alert(1)">'
        '<img srcset="https://example.org/a.png 2x">'
        '<picture><source srcset="https://example.org/a.webp"></picture>'
        '<video src="https://example.org/a.mp4"></video><audio src="x"></audio>'
    )

    assert html == f'<img src="{PNG}" alt="Kept" width="40">'


def test_external_urls_and_imports_are_removed_from_css() -> None:
    css = _css(
        '@import url("https://evil.example/a.css");\n'
        "@IMPORT 'b.css' screen;\n"
        ".a{background:url(https://evil.example/a.png) no-repeat;color:red}\n"
        ".b{background:URL( 'http://evil.example/b.png' )}\n"
        ".c{background:url(//evil.example/c.png)}\n"
        ".d{background:image-set('https://evil.example/d.png' 1x)}\n"
        ".e{width:expression(alert(1));background:url(javascript:alert(1))}\n"
        "@font-face{font-family:X;src:url(https://fonts.example/x.woff2)}\n"
        ".f{cursor:url(relative/cursor.cur),auto}"
    )

    for needle in ("evil.example", "fonts.example", "@import", "@IMPORT", "url(", "URL("):
        assert needle not in css
    assert "expression" not in css and "javascript:" not in css and "image-set" not in css
    assert ".d{background:none}" in css
    assert ".a{background:none no-repeat;color:red}" in css
    assert ".f{cursor:none,auto}" in css


def test_embedded_pictures_and_fragment_references_stay_in_css() -> None:
    kept = (
        f'.a{{background:url("{PNG}")}}'
        ".b{fill:url(#grad);clip-path:url('#clip')}"
        ".c{background:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E\")}"
        '.d::before{content:"\\2713";color:var(--accent)}'
    )

    assert _css(kept) == kept


@pytest.mark.parametrize(
    "css",
    [
        "@im/**/port url(https://evil.example/a.css);",
        "@\\69mport 'https://evil.example/a.css';",
        ".a{background:u\\72l(https://evil.example/a.png)}",
        ".a{background:ur/* */l(https://evil.example/a.png)}",
        ".a{background:url(https://evil.example/a.png",
        "@im@import x;port url(https://evil.example/a.css);",
        ".a{background:uurl(rl(https://evil.example/a.png)}",
        ".a{background:url('ht\\74ps://evil.example/a.png')}",
        '.a{background:url("data:text/html,<script>alert(1)</script>")}',
        "/* unterminated @import url(https://evil.example/a.css);",
    ],
)
def test_obfuscated_css_does_not_get_a_request_through(css: str) -> None:
    cleaned = _css(css + "\n.keep{color:red}") if not css.startswith("/*") else _css(css)

    assert "url(" not in cleaned.lower()
    assert "@import" not in cleaned.lower()
    assert _css(cleaned) == cleaned


def test_css_cannot_leave_its_style_element() -> None:
    spec = design.normalize(
        {
            "html": "<p>x</p><style>.a{color:red}</style ><script>alert(1)</script>"
            "<style>p{color:blue}</style><style>@import 'x.css';</style>",
            "css": ".a{color:red}</style><script>alert(1)</script><style>",
        }
    )
    page = design.render(_node(spec))

    assert "<" not in spec["css"]
    assert spec["html"] == "<p>x</p><style>.a{color:red}</style><style>p{color:blue}</style>"
    assert "<script>alert" not in page
    # The theme stamp, the comment bridge and the kit's page script, nothing from the spec.
    assert [tag for tag, _ in _tags(page)].count("script") == 3


def test_inline_styles_are_cleaned_like_a_stylesheet() -> None:
    html = _clean(
        '<div style="background:url(https://evil.example/a.png);color:red">a</div>'
        f"<div style=\"background:url('{PNG}')\">b</div>"
        '<div style="@import url(x.css)">c</div>'
        '<p style="width:expression(alert(1))">d</p>'
    )

    assert '<div style="background:none;color:red">a</div>' in html
    assert f'<div style="background:url(&#x27;{PNG}&#x27;)">b</div>' in html
    assert "<div>c</div>" in html and "expression" not in html


def test_ordinary_markup_stays_as_it_was_written() -> None:
    markup = (
        '<section class="hero" id="top" data-tip="A hint" aria-label="Hero" lang="en">'
        '<h1>Title <em>with</em> <strong>weight</strong></h1><p class="lead">Text &amp; more<br>'
        "second line</p><ul><li>One</li><li>Two</li></ul>"
        '<table class="table"><thead><tr><th scope="col" colspan="2">Head</th></tr></thead>'
        "<tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
        '<details open=""><summary>More</summary><p>Hidden</p></details>'
        '<figure><figcaption>Caption</figcaption></figure><hr><time datetime="2026-06-14">14 June'
        "</time></section>"
    )

    assert _clean(markup) == markup


def test_inline_svg_keeps_its_shapes_gradients_and_spelling() -> None:
    markup = (
        '<svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" role="img" '
        'aria-label="Mark"><defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="0" '
        'x2="100"><stop offset="0" stop-color="#2A6FD0"></stop><stop offset="1" '
        'stop-color="var(--accent)"></stop></linearGradient><clipPath id="c" '
        'clipPathUnits="userSpaceOnUse"><rect width="50" height="50"></rect></clipPath>'
        '<symbol id="dot"><circle r="4"></circle></symbol></defs>'
        '<rect width="100" height="100" fill="url(#g)" clip-path="url(#c)" rx="8"></rect>'
        '<path d="M10 10L90 90" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
        'fill="none"></path><use href="#dot" x="20" y="20"></use>'
        '<text x="50" y="50" text-anchor="middle" font-size="12">Label <tspan dy="4">sub</tspan>'
        '</text><g transform="rotate(45 50 50)"><ellipse cx="50" cy="50" rx="10" ry="5"></ellipse>'
        '<polygon points="0,0 10,0 5,8"></polygon><polyline points="0,0 5,5"></polyline>'
        '<line x1="0" y1="0" x2="5" y2="5"></line></g></svg>'
    )

    assert _clean(markup) == markup
    # Written by a model in lower case or self-closed, it comes out the same.
    assert _clean(markup.replace("></rect>", "/>").replace("viewBox", "VIEWBOX")) == markup


def test_svg_cannot_carry_code_or_outside_references() -> None:
    html = _clean(
        '<svg viewBox="0 0 10 10">'
        "<foreignObject><div>html inside</div><script>alert(1)</script></foreignObject>"
        "<script>alert(2)</script>"
        '<use href="https://evil.example/sprite.svg#a"></use>'
        '<use xlink:href="other.svg#b"></use>'
        '<image href="https://evil.example/a.png"></image>'
        '<a href="javascript:alert(3)"><circle r="1"></circle></a>'
        '<animate attributeName="href" to="javascript:alert(4)"></animate>'
        '<set attributeName="onload" to="alert(5)"></set>'
        '<rect fill="url(https://evil.example/paint.svg#p)" filter="url(//evil.example/f)"></rect>'
        "<style><script>alert(6)</script>circle{fill:red}</style>"
        "</svg>"
    )

    assert "alert" not in html.replace("alert(6)", "") and "evil.example" not in html
    assert "<script" not in html and "foreignObject" not in html and "html inside" not in html
    assert "<use></use><use></use>" in html
    assert '<a><circle r="1"></circle></a>' in html
    assert '<rect fill="none" filter="none"></rect>' in html
    # A style element inside SVG is markup to a browser: no "<" may be left in it.
    style = html[html.index("<style>") + 7 : html.index("</style>")]
    assert "<" not in style and "circle{fill:red}" in style


def test_text_stays_text() -> None:
    html = _clean("<p>&lt;script&gt;alert(1)&lt;/script&gt; 1 < 2 &amp; 3 > 2</p>")

    assert html == "<p>&lt;script&gt;alert(1)&lt;/script&gt; 1 &lt; 2 &amp; 3 &gt; 2</p>"
    assert _clean('<p title="&quot;&gt;&lt;img src=x onerror=alert(1)&gt;">x</p>') == (
        '<p title="&quot;&gt;&lt;img src=x onerror=alert(1)&gt;">x</p>'
    )


def test_unbalanced_markup_is_closed_and_unknown_elements_are_unwrapped() -> None:
    assert _clean("<div><span>a</div>b</span></p>") == "<div><span>a</span></div>b"
    assert _clean("<my-widget><p>kept <blink>text</blink></p></my-widget>") == "<p>kept text</p>"
    assert _clean('<p class="a" class="b" CLASS="c">x') == '<p class="a">x</p>'


NASTY = [
    "<p <b>x",
    '<a href="x" <script>alert(1)</script>',
    "<![foo bar]>x<![CDATA[y]]><?php z ?>",
    "<svg><style><script>alert(1)</script></style></svg>",
    "<textarea><script>alert(1)</script></textarea><title>t</title><p>y",
    "&#12;a&#0;b&lt;script&gt;&ampfoo &#x26;lt;",
    "<style>a{b:c}</style><style></style ><p>x</p><style>@import 'x'",
    "<div style=\"background:ur\\6c(x);co/**/lor:red;x:'\\''\">a\r\nb\rc\x00\x0b</div>",
    "<script/>alert(1)</script><p/>x<br/><img/><svg><path/><circle></svg>",
    "<table><p>foster</p><tr><td>cell</table><select><option>a<p>b</select>",
    "<iframe><p>a</iframe><p>b</p><object><embed><object></object>c</object>d",
    '<p style="a:url(&quot;data:image/svg+xml,<svg></svg>&quot;)">x</p>',
    "<math><mi>x</mi></math><plaintext>rest <b>of</b> page",
]


@pytest.mark.parametrize("markup", NASTY)
def test_cleaning_twice_changes_nothing(markup: str) -> None:
    once = design.clean_html(markup)

    assert design.clean_html(once) == once
    assert "<script" not in once
    if once:
        spec = design.normalize({"html": markup, "css": markup})
        assert spec["html"] == once
        assert design.normalize(spec) == spec


# ------------------------------------------------------------------- render


def test_a_page_design_sits_in_the_themed_page_with_the_kit_script() -> None:
    spec = design.normalize(
        {
            "html": '<h1 class="big">Open house</h1><a href="https://example.org">More</a>',
            "css": ".big{font-size:96px;color:var(--ink)}",
            "background": "#0B1F3A",
        }
    )
    page = design.render(_node(spec, title="Open <house>"))

    assert "<title>Open &lt;house&gt;</title>" in page
    assert '<main class="design"><h1 class="big">Open house</h1>' in page
    assert "<body>" in page
    # The theme first, the spec's styles after it, so the design can build on the tokens.
    assert page.index("--accent:#2A6FD0") < page.index(".big{font-size:96px")
    assert ":root{--design-bg:#0B1F3A}" in page
    assert "dodaios-open-link" in page
    assert page == design.render(_node(json.loads(json.dumps(spec)), title="Open <house>"))


def test_a_canvas_design_is_an_artboard_scaled_to_the_window() -> None:
    spec = design.normalize({"html": "<h1>Poster</h1>", "width": 1200, "height": 1600})
    page = design.render(_node(spec))

    assert '<body class="fill">' in page
    assert '<div class="design-fit" data-w="1200" data-h="1600"' in page
    assert '<main class="design design-art" style="width:1200px;height:1600px">' in page
    assert "@page{size:1200px 1600px;margin:0}" in page
    assert 'addEventListener("resize",size)' in page
    assert "--design-bg" in page and ":root{--design-bg:" not in page
    # Print shows the artboard at its natural size.
    assert ".design-art{position:relative;transform:none!important}" in page
    assert page == design.render(_node(spec))


def test_render_cleans_a_spec_that_was_stored_unclean() -> None:
    page = design.render(_node({"html": "<p onclick='alert(1)'>x</p><script>alert(2)</script>"}))

    assert "alert" not in page.replace("dodaios", "")
    assert '<main class="design"><p>x</p></main>' in page


# ------------------------------------------------- preview, starter, guide


def test_preview_has_exactly_the_cards_values() -> None:
    page = design.preview(design.normalize({"html": "<p>x</p>", "background": "blue"}))
    canvas = design.preview(design.normalize({"html": "<p>x</p>", "width": 1080, "height": 1080}))

    assert page == {"background": "var(--s1)", "fit": "page", "width": 1280, "height": 800}
    assert canvas == {"background": "", "fit": "canvas", "width": 1080, "height": 1080}
    assert design.preview({"html": "<p>x</p>", "background": "#0B1F3A"})["background"] == "#0B1F3A"
    assert all(isinstance(canvas[key], int) for key in ("width", "height"))


def test_starter_is_a_one_screen_page_that_shows_the_title() -> None:
    spec = design.starter("Autumn <b>open</b> house", "en")

    assert spec["fit"] == "page" and design.normalize(spec) == spec
    assert "<h1>Autumn &lt;b&gt;open&lt;/b&gt; house</h1>" in spec["html"]
    assert "<svg" in spec["html"] and "var(--accent)" in spec["css"]
    assert "clamp(40px,6.4vw,96px)" in spec["css"]
    assert "clamp(40px,8.6vw,128px)" in design.starter("Short", "en")["css"]
    assert "<h1>Untitled</h1>" in design.starter("", "en")["html"]


def test_guide_is_compact_names_the_tokens_and_its_example_is_a_valid_spec() -> None:
    spec = design.normalize(design.EXAMPLE)

    assert design.normalize(spec) == spec
    assert (spec["fit"], spec["width"], spec["height"]) == ("canvas", 1080, 1350)
    assert spec["css"] == design.EXAMPLE["css"]
    assert json.dumps(design.EXAMPLE, ensure_ascii=False, separators=(",", ":")) in design.GUIDE
    assert len(design.GUIDE) <= 2_500
    for needle in ("--bg", "--ink", "--line", "--accent", "--s1", "var(--font)", "canvas", "svg"):
        assert needle in design.GUIDE


def test_declarations_are_taken_out_before_the_parser_sees_them() -> None:
    # Python 3.11's parser raises on an unknown marked section and 3.12 skips
    # it; neither may decide what a design keeps.
    markup = "<!DOCTYPE html><![foo bar]><p>a</p><![CDATA[b]]><?php c ?><p>d</p>"

    assert design.clean_html(markup) == "<p>a</p><p>d</p>"
