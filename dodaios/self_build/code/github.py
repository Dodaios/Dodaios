"""The GitHub calls the code builder makes, with the person's existing connection.

Reads: who the person is and which organisations they administer, a
repository's open issues and pull requests, one pull request's state and CI.
Writes, only in the person's own repositories: open a pull request, close it
(undo), merge it (only where the person opted in per repository). Nothing
else: no issue comments, no labels, no reviews.

The credential is the one the IDE's Git tab uses (``github_link.credential``):
the app's GitHub connection, else ``gh auth token``. There is no public webhook
URL on a desktop, so the loop polls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from loguru import logger

from dodaios.agentic_ide import github_link
from dodaios.agentic_ide.github_link import GitHubError

#: Owner permissions that may receive a loop pull request.
OWN_PERMISSIONS = frozenset({"ADMIN", "MAINTAIN"})


@dataclass(frozen=True, slots=True)
class Viewer:
    login: str
    #: Organisations the person administers (lower case).
    admin_orgs: frozenset[str] = frozenset()

    def owns(self, repo: str) -> bool:
        owner = repo.partition("/")[0].strip().lower()
        return bool(owner) and (owner == self.login.lower() or owner in self.admin_orgs)


@dataclass(frozen=True, slots=True)
class Issue:
    number: int
    title: str
    body: str = ""
    url: str = ""
    author: str = ""
    labels: tuple[str, ...] = ()
    assignees: int = 0
    comments: int = 0
    state: str = "OPEN"
    updated_at: str = ""
    #: Logins of the assignees, where the query read them (:meth:`GitHubApi.issue`).
    assigned_to: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "author": self.author,
            "labels": list(self.labels),
            "assignees": self.assignees,
            "comments": self.comments,
            "state": self.state,
            "updated_at": self.updated_at,
            "assigned_to": list(self.assigned_to),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Issue:
        return cls(
            number=int(data.get("number") or 0),
            title=str(data.get("title") or ""),
            body=str(data.get("body") or ""),
            url=str(data.get("url") or ""),
            author=str(data.get("author") or ""),
            labels=tuple(str(x) for x in data.get("labels") or ()),
            assignees=int(data.get("assignees") or 0),
            comments=int(data.get("comments") or 0),
            state=str(data.get("state") or "OPEN"),
            updated_at=str(data.get("updated_at") or ""),
            assigned_to=tuple(str(x) for x in data.get("assigned_to") or ()),
        )


@dataclass(frozen=True, slots=True)
class PullRef:
    number: int
    title: str
    head: str = ""
    body: str = ""


@dataclass(frozen=True, slots=True)
class Snapshot:
    repo: str
    permission: str = ""
    archived: bool = False
    fork: bool = False
    default_branch: str = ""
    issues: tuple[Issue, ...] = ()
    pulls: tuple[PullRef, ...] = ()


@dataclass(frozen=True, slots=True)
class PullState:
    id: str
    number: int
    url: str
    #: ``OPEN`` | ``CLOSED`` | ``MERGED``.
    state: str
    draft: bool = False
    head_oid: str = ""
    #: The CI rollup of the head commit: ``SUCCESS`` | ``FAILURE`` | ``ERROR`` |
    #: ``PENDING`` | ``EXPECTED`` | ``""`` (no checks at all).
    checks: str = ""
    commits: int = 0
    failing: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CreatedPull:
    id: str
    number: int
    url: str


class GitHub(Protocol):
    """What the loop needs from GitHub; tests pass a fake."""

    def viewer(self) -> Viewer: ...
    def snapshot(self, repo: str) -> Snapshot: ...
    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> CreatedPull: ...
    def pull(self, repo: str, number: int) -> PullState: ...
    def issue(self, repo: str, number: int) -> Issue | None: ...
    def close_pull(self, pull_id: str) -> None: ...
    def merge_pull(self, pull_id: str, *, head_oid: str) -> None: ...


_VIEWER = """
query { viewer { login } }
"""
#: Asked apart from the login: it needs the ``read:org`` scope, which a token
#: from the in-app GitHub connection may not carry.
_VIEWER_ORGS = """
query {
  viewer { organizations(first: 100) { nodes { login viewerCanAdminister } } }
}
"""

_SNAPSHOT = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner isArchived isFork viewerPermission
    defaultBranchRef { name }
    issues(states: OPEN, first: 30, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number title body url updatedAt state
        author { login }
        assignees(first: 1) { totalCount }
        labels(first: 20) { nodes { name } }
        comments { totalCount }
      }
    }
    pullRequests(states: OPEN, first: 30, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title headRefName body }
    }
  }
}
"""

_PULL = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      id number url state isDraft headRefOid
      commits(last: 1) {
        totalCount
        nodes { commit { statusCheckRollup {
          state
          contexts(first: 30) { nodes {
            ... on CheckRun { name conclusion }
            ... on StatusContext { context state }
          } }
        } } }
      }
    }
  }
}
"""

_ISSUE = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number title body url updatedAt state
      author { login }
      assignees(first: 10) { totalCount nodes { login } }
      labels(first: 20) { nodes { name } }
      comments { totalCount }
    }
  }
}
"""

_REPOSITORY_ID = """
query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { id } }
"""

_CREATE = """
mutation($input: CreatePullRequestInput!) {
  createPullRequest(input: $input) { pullRequest { id number url } }
}
"""

_CLOSE = """
mutation($id: ID!) { closePullRequest(input: {pullRequestId: $id}) { pullRequest { state } } }
"""

_MERGE = """
mutation($id: ID!, $oid: GitObjectID) {
  mergePullRequest(input: {pullRequestId: $id, mergeMethod: SQUASH, expectedHeadOid: $oid}) {
    pullRequest { state }
  }
}
"""

_BAD = frozenset(
    {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
)


def _split(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise GitHubError("A repository is written as owner/name.", code="needs_repo")
    return owner, name


def _issue_from(node: dict[str, Any]) -> Issue:
    assignees = node.get("assignees") or {}
    return Issue(
        number=int(node.get("number") or 0),
        title=str(node.get("title") or ""),
        body=str(node.get("body") or "")[:8_000],
        url=str(node.get("url") or ""),
        author=str((node.get("author") or {}).get("login") or ""),
        labels=tuple(
            str(label.get("name") or "")
            for label in (node.get("labels") or {}).get("nodes") or []
            if isinstance(label, dict)
        ),
        assignees=int(assignees.get("totalCount") or 0),
        comments=int((node.get("comments") or {}).get("totalCount") or 0),
        state=str(node.get("state") or "OPEN"),
        updated_at=str(node.get("updatedAt") or ""),
        assigned_to=tuple(
            str(person.get("login") or "")
            for person in assignees.get("nodes") or []
            if isinstance(person, dict) and person.get("login")
        ),
    )


def _first_error(payload: dict[str, Any]) -> str:
    for error in payload.get("errors") or []:
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:300]
    return ""


class _Secret:
    """Holds the token so a logged traceback or ``repr`` never shows it."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "<token redacted>"

    __str__ = __repr__


class GitHubApi:
    """:class:`GitHub` over GraphQL with the person's token."""

    def __init__(self, token: str) -> None:
        self._token = _Secret(token)

    def __repr__(self) -> str:
        return "GitHubApi(<token redacted>)"

    @classmethod
    def connect(cls) -> GitHubApi | None:
        cred = github_link.credential()
        return cls(cred.token) if cred is not None else None

    def _q(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        return github_link.graphql(self._token.reveal(), query, variables or {})

    def viewer(self) -> Viewer:
        data = (self._q(_VIEWER).get("data") or {}).get("viewer") or {}
        return Viewer(login=str(data.get("login") or ""), admin_orgs=self._admin_orgs())

    def _admin_orgs(self) -> frozenset[str]:
        """Organisations the person administers; none when the token may not read them.

        Without ``read:org`` GitHub refuses the whole query. The person's own
        repositories are still theirs; only organisation repositories are left
        out until the connection can read organisations.
        """
        try:
            payload = self._q(_VIEWER_ORGS)
        except GitHubError as exc:
            logger.info("self-build code: organisations unreadable ({}); own repos only", exc)
            return frozenset()
        data = (payload.get("data") or {}).get("viewer") or {}
        orgs = frozenset(
            str(node.get("login") or "").lower()
            for node in (data.get("organizations") or {}).get("nodes") or []
            if isinstance(node, dict) and node.get("viewerCanAdminister")
        )
        return orgs - {""}

    def snapshot(self, repo: str) -> Snapshot:
        owner, name = _split(repo)
        data = (self._q(_SNAPSHOT, {"owner": owner, "name": name}).get("data") or {}).get(
            "repository"
        ) or {}
        issues = [
            _issue_from(node)
            for node in (data.get("issues") or {}).get("nodes") or []
            if isinstance(node, dict)
        ]
        pulls = [
            PullRef(
                number=int(node.get("number") or 0),
                title=str(node.get("title") or ""),
                head=str(node.get("headRefName") or ""),
                body=str(node.get("body") or "")[:4_000],
            )
            for node in (data.get("pullRequests") or {}).get("nodes") or []
            if isinstance(node, dict)
        ]
        return Snapshot(
            repo=str(data.get("nameWithOwner") or repo),
            permission=str(data.get("viewerPermission") or ""),
            archived=bool(data.get("isArchived")),
            fork=bool(data.get("isFork")),
            default_branch=str((data.get("defaultBranchRef") or {}).get("name") or ""),
            issues=tuple(issues),
            pulls=tuple(pulls),
        )

    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> CreatedPull:
        owner, name = _split(repo)
        found = self._q(_REPOSITORY_ID, {"owner": owner, "name": name})
        repo_id = ((found.get("data") or {}).get("repository") or {}).get("id")
        if not repo_id:
            raise GitHubError("GitHub does not know this repository.", code="repo_missing")
        payload = self._q(
            _CREATE,
            {
                "input": {
                    "repositoryId": repo_id,
                    "baseRefName": base,
                    "headRefName": head,
                    "title": title,
                    "body": body,
                    "draft": draft,
                }
            },
        )
        created = ((payload.get("data") or {}).get("createPullRequest") or {}).get("pullRequest")
        if not isinstance(created, dict) or not created.get("url"):
            raise GitHubError(
                _first_error(payload) or "GitHub could not open the pull request.",
                code="refused",
            )
        return CreatedPull(
            id=str(created.get("id") or ""),
            number=int(created.get("number") or 0),
            url=str(created["url"]),
        )

    def pull(self, repo: str, number: int) -> PullState:
        owner, name = _split(repo)
        variables = {"owner": owner, "name": name, "number": int(number)}
        repository = (self._q(_PULL, variables).get("data") or {}).get("repository") or {}
        data = repository.get("pullRequest") or {}
        if not data:
            raise GitHubError("GitHub does not know this pull request.", code="not_found")
        commits = data.get("commits") or {}
        nodes = commits.get("nodes") or []
        rollup = ((nodes[-1] or {}).get("commit") or {}).get("statusCheckRollup") if nodes else None
        failing: list[str] = []
        for ctx in ((rollup or {}).get("contexts") or {}).get("nodes") or []:
            if not isinstance(ctx, dict):
                continue
            verdict = str(ctx.get("conclusion") or ctx.get("state") or "").upper()
            if verdict in _BAD:
                failing.append(str(ctx.get("name") or ctx.get("context") or "check"))
        return PullState(
            id=str(data.get("id") or ""),
            number=int(data.get("number") or number),
            url=str(data.get("url") or ""),
            state=str(data.get("state") or ""),
            draft=bool(data.get("isDraft")),
            head_oid=str(data.get("headRefOid") or ""),
            checks=str((rollup or {}).get("state") or ""),
            commits=int(commits.get("totalCount") or 0),
            failing=tuple(failing[:10]),
        )

    def issue(self, repo: str, number: int) -> Issue | None:
        """One issue as it stands now; None when GitHub does not know it."""
        owner, name = _split(repo)
        variables = {"owner": owner, "name": name, "number": int(number)}
        repository = (self._q(_ISSUE, variables).get("data") or {}).get("repository") or {}
        node = repository.get("issue")
        return _issue_from(node) if isinstance(node, dict) else None

    def close_pull(self, pull_id: str) -> None:
        payload = self._q(_CLOSE, {"id": pull_id})
        if not ((payload.get("data") or {}).get("closePullRequest")):
            raise GitHubError(_first_error(payload) or "GitHub could not close the pull request.")

    def merge_pull(self, pull_id: str, *, head_oid: str) -> None:
        payload = self._q(_MERGE, {"id": pull_id, "oid": head_oid or None})
        if not ((payload.get("data") or {}).get("mergePullRequest")):
            raise GitHubError(_first_error(payload) or "GitHub could not merge the pull request.")
