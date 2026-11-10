"""The store shows a package the moment it is published, then hands over to
the live feed; a refusal from the registry checks is read back into the app."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from dodaios.marketplace import own_submissions


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(own_submissions, "_path", lambda: tmp_path / "own.json")


def _skill(name: str = "ste-80", version: str = "1.0.0") -> dict[str, Any]:
    return {
        "kind": "skill",
        "name": name,
        "version": version,
        "title": "STE-80 Humanizer",
        "description": "Rewrite text plainly.",
        "categories": ["writing"],
    }


def _index(*entries: tuple[str, str]) -> Any:
    items = [SimpleNamespace(name=n, version=v) for n, v in entries]
    return SimpleNamespace(plugins=[], skills=items, agents=[])


def test_a_new_submission_is_pending_until_the_feed_lists_it() -> None:
    own_submissions.record(_skill(), {"issue_number": 4, "issue_url": "u"}, "me")
    pending = own_submissions.pending(_index(("other", "1.0.0")))
    assert [p["name"] for p in pending] == ["ste-80"]
    assert pending[0]["state"] == "checking" and pending[0]["publisher"] == "me"

    assert own_submissions.pending(_index(("ste-80", "1.0.0"))) == []
    # Dropped for good, not only hidden.
    assert own_submissions.pending(None) == []


def test_an_older_version_in_the_feed_does_not_hide_the_new_one() -> None:
    own_submissions.record(_skill(version="1.1.0"), {"issue_number": 5}, "me")
    assert len(own_submissions.pending(_index(("ste-80", "1.0.0")))) == 1


def test_a_second_try_replaces_the_first() -> None:
    own_submissions.record(_skill(), {"issue_number": 4}, "me")
    own_submissions.record(_skill(), {"issue_number": 6}, "me")
    pending = own_submissions.pending(None)
    assert [p["issue_number"] for p in pending] == [6]


def test_problems_are_read_without_the_runner_path() -> None:
    body = (
        "The automated checks found problems:\n\n```\nFAIL — 1 problem(s):\n"
        "  - /home/runner/work/marketplace/marketplace/submissions/kjm.json: "
        "skill_md: frontmatter name must equal 'kjm'\n```"
    )
    assert own_submissions._problems_from_comment(body) == [
        "skill_md: frontmatter name must equal 'kjm'"
    ]


@pytest.mark.asyncio
async def test_a_refusal_on_the_issue_marks_the_record_failed() -> None:
    own_submissions.record(_skill(), {"issue_number": 13}, "me")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[{"body": "  - x/submissions/ste-80.json: bad thing"}])
        return httpx.Response(200, json={"labels": [{"name": "needs-changes"}]})

    item = await own_submissions.refresh_from_issue(
        "ste-80", "1.0.0", "Dodaios/marketplace", "tok", transport=httpx.MockTransport(handler)
    )
    assert item is not None
    assert item["state"] == "failed" and item["problems"] == ["bad thing"]
    assert own_submissions.previous_failed_issue("skill", "ste-80") == 13
