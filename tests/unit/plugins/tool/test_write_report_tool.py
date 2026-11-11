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
    assert 'class="standfirst">Two bills need you.' in page
    assert '<html lang="de">' in page
    assert '<table class="table">' in page and 'class="table-wrap"' in page
    assert "<h2>Money</h2>" in page
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
