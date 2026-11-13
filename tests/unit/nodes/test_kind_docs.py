"""The ``docs`` node type: its spec, its page and its card."""

from __future__ import annotations

import json
from typing import Any

import pytest

from dodaios.nodes.kinds import docs, kind_of
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError

SCRIPT = "<script>alert(1)</script>"
BREAKOUT = '"><img src=x onerror=alert(1)>'

FULL = """## Result

Alpha costs **19 €** per seat, 8 € less than [Beta](https://beta.example/plans).

```metrics
19 € | Alpha | per seat and month
27 € | Beta | per seat and month
```

```chart
{"type": "line", "title": "Price per seat", "x": ["Q1", "Q2", "Q3"],
 "series": [{"name": "Alpha", "data": [17, 19, 19]}, {"name": "Beta", "data": [21, 25, 27]}]}
```

> [!WARNING]
> **Renewal** The contract renews on 1 December.

## Plans

| Plan | Price |
| --- | --: |
| Alpha | 19 € |
| Beta | 27 € |

## How to switch

1. **Export** Run the full export.
2. **Import** Read it into a trial.

## Sources

- [Alpha pricing](https://alpha.example/pricing)
- [Beta pricing](https://beta.example/pricing)
"""


def _node(spec: dict[str, Any], title: str = "Hosting plans", **more: Any) -> Node:
    return Node(
        id="0123456789ab",
        type="docs",
        title=title,
        spec=spec,
        slug="s",
        page_path="p.html",
        created_at=1_700_000_000,
        updated_at=1_700_000_600,
        **more,
    )


def _page(markdown: str, **more: Any) -> str:
    return docs.render(_node(docs.normalize({"markdown": markdown}), **more))


def _body(html: str) -> str:
    """The page without its head, so the kit's own styles and scripts are not searched."""
    return html[html.index("<main") : html.index("</main>")]


# ------------------------------------------------------------------ normalize


def test_normalize_keeps_summary_and_markdown_and_drops_the_rest() -> None:
    spec = docs.normalize(
        {"summary": "  Two\n lines.  ", "markdown": "\r\nHello\r\nworld\n\n", "theme": "x", "n": 1}
    )
    assert spec == {"summary": "Two lines.", "markdown": "Hello\nworld"}


def test_normalize_is_idempotent_and_bounded() -> None:
    long = docs.normalize(
        {
            "summary": "word " * 400,
            "markdown": ("line of text \n" * 20_000) + "\x00\x02tail",
        }
    )
    assert len(long["summary"]) <= docs.MAX_SUMMARY_CHARS
    assert len(long["markdown"]) <= docs.MAX_BODY_CHARS
    assert "\x00" not in long["markdown"] and "\x02" not in long["markdown"]
    assert docs.normalize(long) == long
    full = docs.normalize({"summary": "S", "markdown": FULL})
    assert docs.normalize(full) == full


@pytest.mark.parametrize(
    "spec",
    [None, "just text", ["markdown"], {}, {"markdown": ""}, {"markdown": "  \n "}, {"markdown": 3}],
)
def test_an_unusable_spec_is_refused_with_what_to_send(spec: Any) -> None:
    with pytest.raises(NodeError) as raised:
        docs.normalize(spec)
    message = str(raised.value)
    assert "'markdown'" in message and "Markdown" in message
    assert message.count(".") == 1 and message.endswith(".")


def test_starter_and_example_are_valid_specs() -> None:
    starter = docs.starter("My notes", "en")
    assert docs.normalize(starter) == starter
    assert docs.preview(starter)["heading"]
    example = docs.normalize(docs.EXAMPLE)
    assert docs.normalize(example) == example
    assert 'class="card chart"' in docs.render(_node(example))


def test_guide_is_compact_and_carries_the_example() -> None:
    assert len(docs.GUIDE) <= 2_500
    assert json.dumps(docs.EXAMPLE, ensure_ascii=False) in docs.GUIDE
    assert kind_of("docs").guide == docs.GUIDE
    assert kind_of("document").render is docs.render


# --------------------------------------------------------------------- render


def test_a_small_document_renders_a_complete_page() -> None:
    html = _page("Just one paragraph.")
    assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
    assert "<title>Hosting plans</title>" in html
    body = _body(html)
    assert "<h1>Hosting plans</h1>" in body
    assert "<p>Just one paragraph.</p>" in body
    assert 'class="lead"' not in body and 'class="toc"' not in body
    assert '<p class="node-meta">' not in body
    assert html == _page("Just one paragraph.")


def test_a_full_document_has_summary_contents_and_kit_blocks() -> None:
    node = _node(docs.normalize({"summary": "Alpha wins on price.", "markdown": FULL}))
    html = docs.render(node)
    assert html == docs.render(node)
    body = _body(html)
    assert '<p class="lead">Alpha wins on price.</p>' in body
    assert 'class="page doc has-toc"' in body
    for anchor in ("result", "plans", "how-to-switch", "sources"):
        assert f'<a href="#{anchor}">' in body and f'id="{anchor}"' in body
    assert '<div class="metrics">' in body
    assert '<figure class="card chart">' in body and '<div class="plot"><svg ' in body
    assert '<div class="callout warn">' in body
    assert '<table class="table" data-sort>' in body
    assert '<ol class="steps">' in body and '<ol class="links">' in body
    assert body.count("<h1") == 1


def test_three_sections_get_no_contents_box() -> None:
    body = _body(_page("## One\n\na\n\n## Two\n\nb\n\n## Three\n\nc"))
    assert 'class="toc"' not in body and "has-toc" not in body


def test_the_title_is_not_repeated_and_other_top_headings_become_sections() -> None:
    body = _body(_page("# Hosting plans\n\nIntro.\n\n# A\n\n1\n\n# B\n\n2\n\n# C\n\n3\n\n# D\n\n4"))
    assert body.count("Hosting plans") == 1
    assert body.count("<h1") == 1 and body.count("</h1>") == 1
    assert '<h2 id="a">A</h2>' in body
    assert body.count('<a href="#') == 4


def test_a_kept_current_document_shows_the_upkeep_line() -> None:
    html = _page("Text.", track="The weekly numbers from the shop.", note="Shop was offline.")
    assert '<p class="node-meta">' in html and 'data-updated="1700000600"' in html
    assert "Intl.RelativeTimeFormat" in html
    assert '<p class="node-note">Shop was offline.</p>' in html


def test_the_page_follows_the_theme_and_carries_no_network_or_storage() -> None:
    html = docs.render(_node(docs.normalize({"summary": "S", "markdown": FULL}), language="de"))
    assert '<html lang="de">' in html
    assert 'data-theme' in html and "--bg:" in html
    for forbidden in ("<link", "@import", "url(", 'src="http', "fetch(", "XMLHttpRequest"):
        assert forbidden not in html
    assert "localStorage" not in html and "sessionStorage" not in html
    assert "prefers-reduced-motion" in html and "@media print" in html


# ------------------------------------------------------------------- escaping


@pytest.mark.parametrize("payload", [SCRIPT, BREAKOUT])
def test_no_text_field_reaches_the_page_unescaped(payload: str) -> None:
    chart = json.dumps(
        {
            "type": "line",
            "title": payload,
            "note": payload,
            "unit": payload,
            "x": [payload, "b"],
            "series": [{"name": payload, "data": [1, 2]}, {"name": "B", "data": [2, 1]}],
        }
    )
    markdown = "\n\n".join(
        [
            f"# {payload}",
            f"## {payload}",
            f"Text {payload} and **{payload}** and [{payload}](https://a.example/{payload})",
            f"- {payload}\n- second",
            f"1. **{payload}** {payload}\n2. **B** more",
            f"> [!NOTE]\n> **{payload}** {payload}",
            f"| {payload} | B |\n| --- | --- |\n| {payload} | 1 |",
            f"```metrics\n{payload} | {payload} | {payload}\n```",
            f"```chart\n{chart}\n```",
            f"```\n{payload}\n```",
            f"![{payload}](https://img.example/{payload})",
        ]
    )
    node = _node(
        docs.normalize({"summary": payload, "markdown": markdown}),
        title=payload,
        track="x",
        note=payload,
        language=payload,
    )
    html = docs.render(node)
    assert payload not in html
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "onerror=alert(1)>" not in html


def test_markdown_cannot_set_handlers_styles_or_script_links() -> None:
    body = _body(
        _page(
            '## Heading {: onclick="alert(1)" #own }\n\n'
            "A [link](javascript:alert(1)) and `code`{: onmouseover=\"a()\" .x }.\n"
            '{: style="background:url(https://evil.example/x)" }\n\n'
            "[fine](https://ok.example/a?b=1&c=2) and [here](#own)\n"
        )
    )
    assert "onclick" not in body and "onmouseover" not in body
    assert "javascript:" not in body
    assert "evil.example" not in body and "style=" not in body
    assert '<h2 id="own">Heading</h2>' in body
    assert '<a href="https://ok.example/a?b=1&amp;c=2">fine</a>' in body
    assert '<a href="#own">here</a>' in body
    assert "<a>link</a>" in body


def test_a_picture_from_an_address_is_its_description() -> None:
    pixel = "data:image/png;base64,iVBORw0KGgo="
    body = _body(_page(f"![A chart of prices](https://img.example/a.png)\n\n![Inline]({pixel})"))
    assert "img.example" not in body
    assert "A chart of prices" in body
    assert f'src="{pixel}"' in body and body.count("<img") == 1


def test_right_aligned_table_columns_keep_their_alignment() -> None:
    body = _body(_page("| A | B |\n| --- | --: |\n| x | 1 |"))
    assert '<td style="text-align: right;">1</td>' in body


# -------------------------------------------------------------------- preview


def test_preview_takes_the_first_heading_and_the_text_under_it() -> None:
    card = docs.preview(docs.normalize({"markdown": FULL}))
    assert set(card) == {"heading", "lines", "bullets"}
    assert card["heading"] == "Result"
    assert card["bullets"] is False
    assert card["lines"][0].startswith("Alpha costs 19 € per seat, 8 € less than Beta")
    assert 1 <= len(card["lines"]) <= 5
    assert all(isinstance(line, str) and 0 < len(line) <= 64 for line in card["lines"])


def test_preview_reads_a_list_as_bullets() -> None:
    markdown = "## Shopping\n\n" + "\n".join(
        f"- **Item {index}** with `code` and a [link](https://a.example) " + "x" * 80
        for index in range(1, 9)
    )
    card = docs.preview({"markdown": markdown})
    assert card["heading"] == "Shopping" and card["bullets"] is True
    assert len(card["lines"]) == 5
    assert card["lines"][0].startswith("Item 1 with code and a link")
    assert all(len(line) <= 64 for line in card["lines"])


def test_preview_bounds_and_empty_cases() -> None:
    long = docs.preview({"markdown": "# " + "Heading " * 30 + "\n\n" + "word " * 400})
    assert len(long["heading"]) <= 60 and long["heading"].endswith("…")
    assert len(long["lines"]) == 5 and all(len(line) <= 64 for line in long["lines"])
    assert docs.preview({"markdown": "Only text, no heading."}) == {
        "heading": "",
        "lines": ["Only text, no heading."],
        "bullets": False,
    }
    assert docs.preview({}) == {"heading": "", "lines": [], "bullets": False}
    other_blocks = "## T\n\n```chart\n{}\n```\n\n| a | b |\n\n> quote\n\nText."
    skipped = docs.preview({"markdown": other_blocks})
    assert skipped == {"heading": "T", "lines": ["Text."], "bullets": False}
