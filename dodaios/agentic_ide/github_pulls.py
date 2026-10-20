"""Open a pull request with the person's existing GitHub connection.

The Git tab opens a pull request for a pushed branch without the GitHub CLI:
the same credential that reads pull requests and CI
(:mod:`dodaios.agentic_ide.github_link`) creates one through GitHub's GraphQL
API. Failures come back as one sentence — GitHub's own where it has one
("A pull request already exists for …").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dodaios.agentic_ide import git_ops, github_link
from dodaios.agentic_ide.git_ops import GitError
from dodaios.agentic_ide.github_link import GitHubError

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


def open_for_branch(
    folder: str | Path, *, branch: str = "", title: str = "", draft: bool = False
) -> str:
    """Push ``branch`` (default: the checked-out one) if needed and open its pull request.

    Uses the GitHub connection the Git tab already reads with; without one (or
    before a repository was picked for the folder) the GitHub CLI opens it.
    Returns the pull request's URL.
    """
    path = Path(folder)
    cred = github_link.credential()
    repo = github_link.bound_repository(path)
    wanted = git_ops.normalize_branch(branch)
    info = git_ops.inspect(path)
    if cred is None or not repo:
        if wanted and wanted != info.branch:
            raise GitError("Connect GitHub to open this pull request.", code="not_connected")
        return git_ops.create_pull_request(path, title=title, draft=draft)
    head_branch = wanted or info.branch
    if not info.is_repo or not head_branch:
        raise GitError("Check out a branch before opening a pull request.", code="detached")
    if head_branch == info.default_branch:
        raise GitError(
            f"{head_branch} is the default branch — open the pull request from a feature branch.",
            code="invalid",
        )
    upstream = git_ops.push(path, head_branch)
    head = upstream.partition("/")[2] or head_branch
    base_ref = f"origin/{info.default_branch}"
    if base_ref not in info.remote_branches:
        base_ref = info.default_branch
    subject = title.strip() or git_ops.first_subject(path, head_branch, base_ref)
    try:
        created = create(
            repo, cred.token, head=head, base=info.default_branch, title=subject, draft=draft
        )
    except GitHubError as exc:
        raise GitError(str(exc), code=exc.code) from exc
    return created.url
