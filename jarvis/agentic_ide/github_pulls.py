"""Open a pull request with the person's existing GitHub connection.

The Git tab opens a pull request for a pushed branch without the GitHub CLI:
the same credential that reads pull requests and CI
(:mod:`jarvis.agentic_ide.github_link`) creates one through GitHub's GraphQL
API. Failures come back as one sentence — GitHub's own where it has one
("A pull request already exists for …").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.agentic_ide import github_link
from jarvis.agentic_ide.github_link import GitHubError

_REPOSITORY_ID = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { id }
}
"""

_CREATE = """
mutation($input: CreatePullRequestInput!) {
  createPullRequest(input: $input) { pullRequest { number url } }
}
"""


@dataclass(slots=True)
class CreatedPullRequest:
    number: int
    url: str


def _first_error(payload: dict[str, Any]) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list):
        for error in errors:
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
    return ""


def create(
    repo: str, token: str, *, head: str, base: str, title: str, draft: bool = False
) -> CreatedPullRequest:
    """Open a pull request from ``head`` into ``base`` of ``repo`` (``owner/name``)."""
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise GitHubError("Pick this folder's GitHub repository first.", code="needs_repo")
    found = github_link.graphql(token, _REPOSITORY_ID, {"owner": owner, "name": name})
    repository = ((found.get("data") or {}).get("repository") or {}).get("id")
    if not repository:
        raise GitHubError(
            "GitHub does not know this repository, or this account cannot see it.",
            code="repo_missing",
        )
    payload = github_link.graphql(
        token,
        _CREATE,
        {
            "input": {
                "repositoryId": repository,
                "baseRefName": base,
                "headRefName": head,
                "title": title,
                "draft": draft,
            }
        },
    )
    created = ((payload.get("data") or {}).get("createPullRequest") or {}).get("pullRequest")
    if not isinstance(created, dict) or not created.get("url"):
        raise GitHubError(
            _first_error(payload) or "GitHub could not open the pull request.", code="refused"
        )
    return CreatedPullRequest(number=int(created.get("number") or 0), url=str(created["url"]))
