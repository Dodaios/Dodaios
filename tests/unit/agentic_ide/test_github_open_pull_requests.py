"""The person's open pull requests on GitHub as one read: their own and those waiting for them."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agentic_ide import github_link
from dodaios.ui.web.agentic_ide_git_routes import router

URL = "/api/agentic-ide/git/github/pull-requests"


def _node(number: int, **changes: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "number": number,
        "title": f"Change {number}",
        "url": f"https://github.com/acme/notes/pull/{number}",
        "isDraft": False,
        "updatedAt": "2026-03-02T08:00:00Z",
        "reviewDecision": None,
        "mergeable": "MERGEABLE",
        "repository": {"nameWithOwner": "acme/notes"},
        "author": {"login": "octo"},
        "mergeQueueEntry": None,
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "SUCCESS"}}}]},
    }
    node.update(changes)
    return node


def _answer(mine: list[Any], review: list[Any]) -> dict[str, Any]:
    return {
        "data": {
            "viewer": {"login": "octo"},
            "mine": {"nodes": mine},
            "review": {"nodes": review},
        }
    }


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch):
    """A connected GitHub whose one GraphQL answer the test sets."""
    calls: list[dict[str, Any]] = []
    state: dict[str, Any] = {"answer": _answer([], []), "error": None}

    def fake_graphql(token: str, query: str, variables: dict[str, Any] | None = None) -> Any:
        calls.append({"token": token, "query": query, "variables": variables or {}})
        if state["error"] is not None:
            raise state["error"]
        return state["answer"]

    monkeypatch.setattr(github_link, "credential", lambda: github_link.Credential("t", "app"))
    monkeypatch.setattr(github_link, "graphql", fake_graphql)
    state["calls"] = calls
    return state


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_own_pull_requests_and_those_waiting_for_review_come_in_two_groups(github) -> None:
    github["answer"] = _answer(
        [
            _node(7),
            _node(
                8, isDraft=True, reviewDecision="CHANGES_REQUESTED", mergeable="CONFLICTING",
                commits={"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE"}}}]},
            ),
            _node(
                9, reviewDecision="APPROVED", mergeQueueEntry={"position": 2},
                commits={"nodes": [{"commit": {"statusCheckRollup": {"state": "PENDING"}}}]},
            ),
        ],
        [_node(21, author={"login": "someone"}, reviewDecision="REVIEW_REQUIRED",
               commits={"nodes": [{"commit": {"statusCheckRollup": None}}]})],
    )
    cred = github_link.Credential("t", "app")
    login, mine, review = github_link.open_pull_requests(cred)

    assert login == "octo"
    assert [(row.number, row.checks, row.review) for row in mine] == [
        (7, "passing", ""), (8, "failing", "changes_requested"), (9, "running", "approved"),
    ]
    assert (mine[1].draft, mine[1].conflicts, mine[1].queued) == (True, True, False)
    assert (mine[2].conflicts, mine[2].queued) == (False, True)
    (waiting,) = review
    assert (waiting.repo, waiting.author, waiting.review) == ("acme/notes", "someone", (
        "review_required"
    ))
    # A head without checks says nothing about them.
    assert waiting.checks == ""

    (call,) = github["calls"]
    assert call["token"] == cred.token
    assert "author:@me" in call["variables"]["mine"] and "is:open" in call["variables"]["mine"]
    assert "review-requested:@me" in call["variables"]["review"]
    assert call["variables"]["first"] == github_link.MAX_PULL_REQUESTS


def test_the_number_asked_for_stays_inside_the_bounds(github) -> None:
    cred = github_link.Credential("t", "app")
    github_link.open_pull_requests(cred, limit=5)
    github_link.open_pull_requests(cred, limit=500)
    github_link.open_pull_requests(cred, limit=0)
    assert [call["variables"]["first"] for call in github["calls"]] == [5, 30, 1]


def test_rows_that_are_not_pull_requests_are_left_out(github) -> None:
    # A search can answer with an empty object (an issue the fragment does not cover).
    github["answer"] = _answer([{}, None, _node(3), {"number": 4, "title": "no repository"}], [])
    _, mine, review = github_link.open_pull_requests(github_link.Credential("t", "app"))
    assert [row.number for row in mine] == [3] and review == []


def test_the_route_lists_both_groups(github) -> None:
    github["answer"] = _answer([_node(7)], [_node(21, author={"login": "someone"})])
    with _client() as client:
        body = client.get(URL, params={"limit": 10}).json()
    assert body["connected"] is True and body["login"] == "octo" and body["reason"] == ""
    assert body["source"] == "app"
    assert body["mine"] == [
        {
            "repo": "acme/notes", "number": 7, "title": "Change 7",
            "url": "https://github.com/acme/notes/pull/7", "author": "octo", "draft": False,
            "updated_at": "2026-03-02T08:00:00Z", "checks": "passing", "review": "",
            "conflicts": False, "queued": False,
        }
    ]
    assert [row["number"] for row in body["review_requested"]] == [21]
    assert github["calls"][0]["variables"]["first"] == 10


def test_without_a_github_connection_the_route_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github_link, "credential", lambda: None)
    with _client() as client:
        body = client.get(URL).json()
    assert body == {
        "connected": False, "source": "", "login": "", "mine": [], "review_requested": [],
        "reason": "",
    }


def test_githubs_own_reason_is_passed_on(github) -> None:
    github["error"] = github_link.GitHubError(
        "GitHub's rate limit is reached; it resets within the hour.", code="rate_limited"
    )
    with _client() as client:
        limited = client.get(URL).json()
        github["error"] = github_link.GitHubError(
            "The GitHub connection has expired. Connect GitHub again.", code="not_connected"
        )
        expired = client.get(URL).json()
        too_many = client.get(URL, params={"limit": 31})
    assert limited["connected"] is True and "rate limit" in limited["reason"]
    assert limited["mine"] == [] and limited["review_requested"] == []
    assert expired["connected"] is False and "expired" in expired["reason"]
    assert too_many.status_code == 422


def test_the_reason_is_a_fixed_sentence_never_the_errors_own_text(github) -> None:
    """Whatever an error carries inside stays in the app; its kind picks the sentence."""
    github["error"] = github_link.GitHubError(
        "Traceback (most recent call last): secret-looking internals", code="unreachable"
    )
    with _client() as client:
        unreachable = client.get(URL).json()
        github["error"] = github_link.GitHubError("internals again", code="something-new")
        unknown = client.get(URL).json()
    assert unreachable["reason"] == "GitHub could not be reached."
    assert unknown["reason"] == "GitHub could not answer this request."
    assert unknown["connected"] is True


def test_the_assistant_may_read_it_without_asking() -> None:
    """A look that may only read gets the pull requests through this route, not a shell."""
    from dodaios.app_actions.catalog import build_catalog, default_tier

    app = FastAPI()
    app.include_router(router)
    entry = next(
        entry for entry in build_catalog(app.openapi()).values()
        if entry.path == URL and entry.method == "GET"
    )
    assert default_tier(entry) == "safe"
    assert "pull requests" in entry.title.lower()
