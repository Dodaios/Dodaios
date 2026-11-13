"""Safe text and the document around a node page (``dodaios/nodes/shell.py``)."""

from __future__ import annotations

import math

import pytest

from dodaios.artifacts.design_guide import PAGE_JS
from dodaios.nodes import shell
from dodaios.nodes.bridge import BRIDGE_CSS, BRIDGE_JS
from dodaios.nodes.model import Node


def _node(**changes: object) -> Node:
    fields: dict[str, object] = {
        "id": "0123456789ab",
        "type": "docs",
        "title": "Quarter plan",
        "spec": {},
        "slug": "20260101T000000__node__0123456789ab",
        "page_path": "tasks/node/artifacts/files/quarter-plan.html",
        "created_at": 1_700_000_000.0,
        "updated_at": 1_700_000_600.0,
    }
    fields.update(changes)
    return Node(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- inline


def test_inline_escapes_markup_from_a_spec() -> None:
    assert shell.inline('<script>alert("x")</script> & more') == (
        '&lt;script&gt;alert("x")&lt;/script&gt; &amp; more'
    )
    assert shell.inline(None) == ""
    assert shell.inline(42) == "42"


def test_inline_reads_bold_italic_and_code() -> None:
    assert shell.inline("**bold** and *italic* and `code`") == (
        "<strong>bold</strong> and <em>italic</em> and <code>code</code>"
    )
    # A mark inside code stays as written, and code is escaped like all text.
    assert shell.inline("`*not* <b>`") == "<code>*not* &lt;b&gt;</code>"
    # A lone star is a star: a product, a footnote mark.
    assert shell.inline("2 * 3 * 4") == "2 * 3 * 4"
    assert shell.inline("a*b*c") == "a*b*c"


def test_inline_collapses_whitespace_and_clips() -> None:
    assert shell.inline("  one\n two\t\tthree ") == "one two three"
    assert shell.inline("abcdefgh", limit=3) == "abc"


def test_inline_keeps_only_web_and_mail_links() -> None:
    assert shell.inline("[site](https://example.com/a?b=1&c=2)") == (
        '<a href="https://example.com/a?b=1&amp;c=2" rel="noopener noreferrer">site</a>'
    )
    assert shell.inline("[mail](mailto:someone@example.com)") == (
        '<a href="mailto:someone@example.com" rel="noopener noreferrer">mail</a>'
    )
    # Any other scheme is dropped to its text.
    assert shell.inline("[run](javascript:alert)") == "run"
    assert shell.inline("[file](file:///etc/hosts)") == "file"
    assert shell.inline("[**bold** link](https://example.com)") == (
        '<a href="https://example.com" rel="noopener noreferrer"><strong>bold</strong> link</a>'
    )


def test_inline_link_cannot_break_out_of_its_attribute() -> None:
    html = shell.inline('[x](https://example.com/"onmouseover="alert(1))')
    assert '"onmouseover' not in html
    assert html.count('"') == 4  # href="…" and rel="…", nothing else


def test_inline_leaves_a_link_address_as_written() -> None:
    assert shell.inline("[doc](https://example.com/*draft*/page)") == (
        '<a href="https://example.com/*draft*/page" rel="noopener noreferrer">doc</a>'
    )


def test_inline_text_cannot_forge_a_held_code_span() -> None:
    # Code spans are parked behind a NUL-digits-NUL mark while the other marks
    # are read; text from a spec that holds that pattern must stay text.
    assert shell.inline("a\x000\x00b") == "a0b"
    assert shell.inline("`code` and \x000\x00") == "<code>code</code> and 0"


# ----------------------------------------------------------------------- lines


def test_lines_keeps_line_breaks_and_inline_marks() -> None:
    assert shell.lines("first\r\n**second**\n\n<third>") == (
        "first<br><strong>second</strong><br><br>&lt;third&gt;"
    )
    assert shell.lines("  padded  \n") == "padded"
    assert shell.lines(None) == ""
    assert shell.lines("abcdef", limit=4) == "abcd"


# ----------------------------------------------------------------------- color


def test_color_maps_names_to_theme_tokens() -> None:
    assert shell.color("blue") == "var(--s1)"
    assert shell.color(" Purple ") == "var(--s5)"
    assert shell.color("accent") == "var(--accent)"
    assert set(shell.NAMED_COLORS.values()) <= {
        shell.color(name) for name in shell.NAMED_COLORS
    }


def test_color_accepts_hex_rgb_and_hsl() -> None:
    assert shell.color("#fff") == "#fff"
    assert shell.color("#1A2b3C") == "#1A2b3C"
    assert shell.color("rgb(10, 20, 30)") == "rgb(10, 20, 30)"
    assert shell.color("rgba(10,20,30,0.5)") == "rgba(10,20,30,0.5)"
    assert shell.color("hsl(210 50% 40% / 0.8)") == "hsl(210 50% 40% / 0.8)"


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        "red",  # a CSS keyword outside the named tokens does not hold in both themes
        "#ggg",
        "#fff;background:url(https://example.com)",
        "rgb(0,0,0);position:fixed",
        "url(https://example.com/x.png)",
        "var(--ink)",
        "expression(alert(1))",
        'rgb(1,2,3)"><script>',
    ],
)
def test_color_refuses_everything_else(value: object) -> None:
    assert shell.color(value) == ""
    assert shell.color(value, "var(--ink)") == "var(--ink)"


# ---------------------------------------------------------- links and pictures


def test_safe_link_allows_web_and_mail_addresses_only() -> None:
    assert shell.safe_link("https://example.com/a b") == "https://example.com/a b"
    assert shell.safe_link("  HTTP://EXAMPLE.COM ") == "HTTP://EXAMPLE.COM"
    assert shell.safe_link("mailto:someone@example.com") == "mailto:someone@example.com"
    for refused in (
        "",
        None,
        "javascript:alert(1)",
        " JavaScript:alert(1)",
        "data:text/html,<script>",
        "file:///etc/hosts",
        "//example.com",
        "example.com",
        "/relative",
        "https://example.com/" + "a" * 2_000,
    ):
        assert shell.safe_link(refused) == ""


def test_safe_image_allows_embedded_raster_pictures_only() -> None:
    png = "data:image/png;base64,iVBORw0KGgo="
    assert shell.safe_image(png) == png
    assert shell.safe_image(f"  {png}\n") == png
    for kind in ("jpeg", "jpg", "gif", "webp", "avif"):
        assert shell.safe_image(f"data:image/{kind};base64,AAAA")
    for refused in (
        "",
        None,
        "https://example.com/a.png",
        "data:image/svg+xml;base64,PHN2Zz4=",  # an SVG can carry script
        "data:text/html;base64,AAAA",
        "data:image/png,AAAA",
        'data:image/png;base64,AAAA" onerror="x',
        "data:image/png;base64," + "A" * shell.MAX_IMAGE_CHARS,
    ):
        assert shell.safe_image(refused) == ""


# --------------------------------------------------------------------- numbers


def test_number_reads_json_numbers_and_numeric_text() -> None:
    assert shell.number(3) == 3.0
    assert shell.number(-2.5) == -2.5
    assert shell.number("12.5") == 12.5
    assert shell.number(" 1 000 ") == 1000.0
    assert shell.number("1e3") == 1000.0
    assert isinstance(shell.number(3), float)


@pytest.mark.parametrize(
    "value",
    [None, True, False, "", "abc", "12 apples", "1,5", [1], {"n": 1}, math.inf, math.nan, "inf"],
)
def test_number_is_none_for_everything_else(value: object) -> None:
    assert shell.number(value) is None


def test_bounded_clamps_and_falls_back() -> None:
    assert shell.bounded(5, 0, 10, 1) == 5.0
    assert shell.bounded(-3, 0, 10, 1) == 0.0
    assert shell.bounded("99", 0, 10, 1) == 10.0
    assert shell.bounded(None, 0, 10, 1) == 1
    assert shell.bounded("wide", 0, 10, 7) == 7
    assert shell.bounded(True, 0, 10, 4) == 4


# ------------------------------------------------------------- small text tools


def test_escaping_and_cleaning_helpers() -> None:
    assert shell.esc('<a href="x">&</a>') == '&lt;a href="x"&gt;&amp;&lt;/a&gt;'
    assert shell.esc(None) == ""
    assert shell.esc(0) == "0"
    assert shell.attr('say "hi" & <go>') == "say &quot;hi&quot; &amp; &lt;go&gt;"
    assert shell.attr("it's") == "it&#x27;s"
    assert shell.clean("  a \n b  ", 10) == "a b"
    assert shell.clean("abcdef", 3) == "abc"
    assert shell.clean_block(" a\r\nb\rc ", 10) == "a\nb\nc"
    assert shell.as_list(None, 3) == []
    assert shell.as_list("one", 3) == ["one"]
    assert shell.as_list([1, 2, 3, 4], 3) == [1, 2, 3]
    assert shell.as_list((1, 2), 3) == [1, 2]
    assert shell.pick(" Wide ", ("wide", "tall"), "square") == "wide"
    assert shell.pick("round", ("wide", "tall"), "square") == "square"
    assert shell.pick(None, ("wide", "tall"), "square") == "square"


# -------------------------------------------------------------------- document


def test_document_is_one_page_with_the_theme_and_the_kit() -> None:
    page = shell.document(_node(language="de"), body="<main>content</main>")
    assert page.startswith('<!doctype html>\n<html lang="de"><head>')
    assert page.endswith("</body></html>\n")
    assert "<title>Quarter plan</title>" in page
    assert '<meta name="dodaios-node" content="0123456789ab">' in page
    assert '<meta name="dodaios-node-type" content="docs">' in page
    assert "<body><main>content</main>" in page
    assert shell.NODE_CSS in page
    assert f"<script>{PAGE_JS}</script>" in page
    # No address a page could load from: it runs without network.
    assert 'src="http' not in page and "@import" not in page


def test_document_without_track_carries_no_refresh_clock() -> None:
    page = shell.document(_node(), body="<main>x</main>")
    assert shell.RELATIVE_TIME_JS not in page
    assert shell.upkeep_meta(_node()) == ""


def test_document_with_track_keeps_the_refresh_time_current() -> None:
    node = _node(track="open orders in the shop", refreshing=True, note="Shop <offline>")
    page = shell.document(node, body=f"<main>{shell.upkeep_meta(node)}</main>")
    assert f"<script>{shell.RELATIVE_TIME_JS}</script>" in page
    assert '<time data-updated="1700000600"></time>' in page
    assert '<span class="live on">' in page
    assert '<p class="node-note">Shop &lt;offline&gt;</p>' in page

    stopped = shell.upkeep_meta(_node(track="open orders", refreshing=False))
    assert '<span class="live">' in stopped and "node-note" not in stopped


def test_document_escapes_what_comes_from_the_node() -> None:
    node = _node(
        id='a"><script>1</script>',
        type='docs"><i>',
        title="</title><script>alert(1)</script>",
        language='en"><script>',
    )
    page = shell.document(node, body="<main>x</main>")
    assert "<title>&lt;/title&gt;&lt;script&gt;alert(1)&lt;/script&gt;</title>" in page
    assert "<script>alert(1)</script>" not in page
    assert "<script>1</script>" not in page
    assert '<html lang="en&quot;&gt;&lt;script&gt;">' in page
    assert 'content="docs&quot;&gt;&lt;i&gt;"' in page


def test_document_options_add_the_types_own_parts() -> None:
    page = shell.document(
        _node(),
        body="<main>x</main>",
        css=".deck{color:red}",
        js="window.deck=1;",
        body_class="fill",
        kit_js=False,
    )
    assert '<body class="fill"><main>x</main>' in page
    assert f"{shell.NODE_CSS}{BRIDGE_CSS}.deck{{color:red}}</style>" in page
    assert PAGE_JS not in page
    assert page.endswith("<script>window.deck=1;</script></body></html>\n")


def test_document_falls_back_to_english() -> None:
    assert '<html lang="en">' in shell.document(_node(language=""), body="")


def test_every_page_carries_the_comment_bridge_before_its_own_scripts() -> None:
    page = shell.document(_node(), body="<main>x</main>", js="window.own=1;")

    assert f"<script>{BRIDGE_JS}</script>" in page
    # First among the page's scripts: in comment mode it takes a click before
    # any control of the page does.
    assert page.index(BRIDGE_JS) < page.index(PAGE_JS) < page.index("window.own=1;")
    assert BRIDGE_CSS in page


def test_the_bridge_reaches_nothing_but_its_parent() -> None:
    # No network, no storage, and no markup built from a message.
    for word in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "http://", "https://"):
        assert word not in BRIDGE_JS
    assert BRIDGE_JS.count("innerHTML") == 1  # the two constant icons (tick, cross)
    assert "e.source!==up" in BRIDGE_JS
    assert "</script" not in BRIDGE_JS.lower()
