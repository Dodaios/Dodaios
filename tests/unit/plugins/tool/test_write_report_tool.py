"""The ``write_report`` tool and the report page it writes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dodaios.artifacts import report as report_mod
from dodaios.artifacts.report import (
    MARKER_KIND,
    ReportError,
    count_sections,
    markdown_to_html,
    write_report,
)
from dodaios.plugins.tool import write_report as tool_mod
from dodaios.plugins.tool.write_report import WriteReportTool, report_card

BODY = (
    "## Money\n\n"
    "- **Google One:** payment failed, 32.98 EUR, update by 13 Nov\n"
    "- **Jira:** plan ends today\n\n"
    "## Security\n\n"
    "| When | What |\n|---|---|\n| Mon | New device |\n"
)


def _ctx(session: str = "lead-1") -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(),
        user_utterance="",
        config={"approval_ref": f"agent-chat:{session}", "output_language": "de"},
        memory_read=None,
    )


def test_a_report_is_one_page_in_the_archive_with_its_markdown(tmp_path: Path) -> None:
    report = write_report(
        title="Mails, 6-11 Nov", summary="Two bills need you.", markdown=BODY,
        language="de", root=tmp_path,
    )
    run_dir = tmp_path / report.slug
    assert report.slug.endswith(f"__report__{report.id}")
    assert report.visual_id == f"{report.slug}::{report.page_path}"
    assert report.sections == 2
    page = (run_dir / report.page_path).read_text(encoding="utf-8")
    assert "<h1>Mails, 6-11 Nov</h1>" in page
    assert 'class="summary">Two bills need you.' in page
    assert '<html lang="de">' in page
    assert '<table class="table" data-sort>' in page and 'class="table-wrap"' in page
    assert '<h2 id="money">Money</h2>' in page
    md = (run_dir / report.page_path).with_suffix(".md").read_text(encoding="utf-8")
    assert md.startswith("# Mails, 6-11 Nov\n\nTwo bills need you.")
    marker = (run_dir / ".standalone-run.json").read_text(encoding="utf-8")
    assert MARKER_KIND in marker


def test_raw_html_in_the_markdown_is_shown_never_run() -> None:
    html = markdown_to_html("Quoted mail: <script>alert(1)</script>\n\n<img src=x onerror=y>")
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html


def test_a_title_repeated_as_the_first_heading_is_dropped(tmp_path: Path) -> None:
    report = write_report(title="Weekly", markdown="# Weekly\n\nAll quiet.", root=tmp_path)
    page = (tmp_path / report.slug / report.page_path).read_text(encoding="utf-8")
    assert page.count("Weekly</h1>") == 1


def test_title_and_body_are_required(tmp_path: Path) -> None:
    with pytest.raises(ReportError):
        write_report(title="", markdown="x", root=tmp_path)
    with pytest.raises(ReportError):
        write_report(title="T", markdown="  ", root=tmp_path)


def test_sections_count_level_two_headings_only() -> None:
    assert count_sections("# a\n## b\n### c\n## d") == 2


async def test_the_tool_writes_the_page_and_posts_a_report_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted: list[tuple[str, dict]] = []

    async def fake_post(session_id: str, payload: dict) -> bool:
        posted.append((session_id, payload))
        return True

    monkeypatch.setattr(tool_mod, "post_card", fake_post)
    monkeypatch.setattr(report_mod, "outputs_root", lambda: tmp_path)
    result = await WriteReportTool().execute(
        {"title": "Mails", "summary": "Two bills.", "markdown": BODY}, _ctx()
    )
    assert result.success, result.error
    assert "two or three" in str(result.output)
    [(session, card)] = posted
    # The assistant is handed the link that names the page in its reply.
    assert f"[Mails](artifact:{card['artifact']})" in str(result.output)
    assert session == "lead-1"
    assert card["kind"] == "report"
    assert card["text"] == "Mails"
    assert card["summary"] == "Two bills."
    assert card["sections"] == 2
    slug, _, path = card["artifact"].partition("::")
    page = (tmp_path / slug / path).read_text(encoding="utf-8")
    assert 'lang="de"' in page  # the turn's stamped language wins


async def test_the_tool_says_what_is_missing() -> None:
    result = await WriteReportTool().execute({"title": "Mails"}, _ctx())
    assert not result.success
    assert "markdown" in result.error


def test_report_card_shape() -> None:
    card = report_card(
        SimpleNamespace(title="T", summary="S", visual_id="a::b", sections=3)
    )
    assert card == {"kind": "report", "text": "T", "summary": "S", "artifact": "a::b",
                    "sections": 3}


def test_write_report_is_a_router_tool() -> None:
    from dodaios.brain.factory import ROUTER_TOOLS

    assert "write-report" in ROUTER_TOOLS


def _dated_page(title: str, summary: str, body_html: str) -> str:
    """A report page as it was written before the plain look."""
    return (
        '<!doctype html>\n<html lang="de"><head><meta charset="utf-8">'
        f"<title>{title}</title><style>.wrap{{}}</style></head><body>"
        '<main class="wrap"><header class="masthead">'
        '<p class="eyebrow"><time>2026-11-12 20:53</time></p>'
        f'<h1>{title}</h1><p class="standfirst">{summary}</p></header>'
        f'<article class="report">{body_html}</article>'
        '<footer class="colophon"><span class="brand">Dodaios</span></footer>'
        "</main></body></html>\n"
    )


def test_a_report_from_before_the_plain_look_is_laid_out_again_from_its_markdown(
    tmp_path: Path,
) -> None:
    import os

    from dodaios.artifacts.report import restyle_if_dated

    page = tmp_path / "mails.html"
    page.write_text(
        _dated_page("Mails &amp; more", "Two bills need you.", "<h2>Money</h2>"), encoding="utf-8"
    )
    page.with_suffix(".md").write_text(
        "# Mails & more\n\nTwo bills need you.\n\n" + BODY + "\n", encoding="utf-8"
    )
    os.utime(page, (1_700_000_000, 1_700_000_000))

    assert restyle_if_dated(page) is True
    html = page.read_text(encoding="utf-8")
    assert '<main class="page"><h1>Mails &amp; more</h1>' in html
    assert '<p class="summary">Two bills need you.</p>' in html
    assert "<time>2026-11-12 20:53</time>" in html and '<html lang="de">' in html
    # The body comes from the Markdown, and the head is not repeated in it.
    assert '<h2 id="money">Money</h2>' in html and '<table class="table" data-sort>' in html
    assert html.count("Two bills need you.") == 1 and html.count("Mails &amp; more</h1>") == 1
    for gone in ("masthead", "eyebrow", "standfirst", "colophon"):
        assert gone not in html
    # Its place in the Artifacts section does not move.
    assert page.stat().st_mtime == 1_700_000_000
    # A current page is left alone, and so is an old one without its Markdown.
    assert restyle_if_dated(page) is False
    lone = tmp_path / "lone.html"
    lone.write_text(_dated_page("Lone", "S", "<p>x</p>"), encoding="utf-8")
    before = lone.read_text(encoding="utf-8")
    assert restyle_if_dated(lone) is False and lone.read_text(encoding="utf-8") == before
    assert restyle_if_dated(tmp_path / "missing.html") is False
