"""What GitHub says about the commit a run left behind: landing and checks."""

from __future__ import annotations

from typing import Any

import pytest

from dodaios.orchestrator.verification import evidence
from dodaios.orchestrator.verification.evidence import Evidence

SHA = "a" * 40
MERGE = "b" * 40
OTHER = "c" * 40


def _rollup(state: str, *contexts: tuple[str, str, str]) -> dict[str, Any]:
    nodes = [
        {"__typename": "CheckRun", "name": name, "conclusion": verdict}
        if kind == "check"
        else {"__typename": "StatusContext", "context": name, "state": verdict}
        for kind, name, verdict in contexts
    ]
    return {"state": state, "contexts": {"nodes": nodes}}


def _pull(number: int = 12, **fields: Any) -> dict[str, Any]:
    head = fields.pop("head", SHA)
    head_rollup = fields.pop("head_rollup", None)
    return {
        "number": number,
        "state": "OPEN",
        "isDraft": False,
        "merged": False,
        "headRefOid": head,
        "mergeCommit": None,
        "commits": {"nodes": [{"commit": {"oid": head, "statusCheckRollup": head_rollup}}]},
        **fields,
    }


def _answer(
    *pulls: dict[str, Any],
    rollup: dict[str, Any] | None = None,
    history: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """One answer of GitHub; ``history`` is the default branch, newest commit first."""
    commit = {
        "oid": SHA,
        "statusCheckRollup": rollup,
        "associatedPullRequests": {"nodes": list(pulls)},
    }
    nodes = [
        {"oid": oid, "statusCheckRollup": {"state": state} if state else None}
        for oid, state in history or []
    ]
    branch = {"target": {"history": {"nodes": nodes}}}
    return {"data": {"repository": {"object": commit, "defaultBranchRef": branch}}}


# ------------------------------------------------------------------ parsing


def test_a_commit_github_does_not_know_has_not_landed():
    found = evidence.from_payload({"data": {"repository": {"object": None}}}, SHA)
    assert (found.landing, found.checks) == ("none", "none")
    assert found.settled is True
    assert evidence.from_payload({}, SHA).landing == "none"
    assert evidence.from_payload({"data": {"repository": None}}, SHA).landing == "none"


def test_a_pushed_commit_without_a_pull_request_is_judged_by_its_own_checks():
    found = evidence.from_payload(_answer(rollup=_rollup("SUCCESS")), SHA)
    assert (found.landing, found.checks, found.pr) == ("pushed", "passing", 0)
    assert found.checked_sha == SHA
    assert found.settled is True


def test_an_open_pull_request_shows_the_checks_of_its_head():
    passing = evidence.from_payload(_answer(_pull(head_rollup=_rollup("SUCCESS"))), SHA)
    assert (passing.landing, passing.checks, passing.pr) == ("pr_open", "passing", 12)
    assert passing.draft is False
    # It may still merge: the record is read again.
    assert passing.settled is False

    running = evidence.from_payload(_answer(_pull(head_rollup=_rollup("PENDING"))), SHA)
    assert running.checks == "running"
    assert running.settled is False

    draft = evidence.from_payload(
        _answer(_pull(isDraft=True, head_rollup=_rollup("SUCCESS"))), SHA
    )
    assert (draft.draft, draft.settled) == (True, True)


def test_failing_checks_are_named():
    rollup = _rollup(
        "FAILURE",
        ("check", "lint", "SUCCESS"),
        ("check", "test (ubuntu)", "FAILURE"),
        ("check", "test (windows)", "TIMED_OUT"),
        ("status", "deploy/preview", "ERROR"),
        ("check", "test (ubuntu)", "FAILURE"),
        ("check", "docs", "NEUTRAL"),
    )
    found = evidence.from_payload(_answer(_pull(head_rollup=rollup)), SHA)
    assert found.checks == "failing"
    assert found.failing == ("test (ubuntu)", "test (windows)", "deploy/preview")


def test_a_pull_request_that_moved_on_leaves_the_run_its_own_commit():
    moved = _pull(head=OTHER, head_rollup=_rollup("FAILURE"))
    found = evidence.from_payload(_answer(moved, rollup=_rollup("SUCCESS")), SHA)
    assert (found.landing, found.checks, found.checked_sha) == ("pr_open", "passing", SHA)


def test_merged_work_is_judged_on_the_merge_commit():
    merged = _pull(
        state="MERGED", merged=True, head_rollup=_rollup("SUCCESS"),
        mergeCommit={"oid": MERGE, "statusCheckRollup": _rollup(
            "FAILURE", ("check", "main / test", "FAILURE")
        )},
    )
    found = evidence.from_payload(_answer(merged), SHA)
    assert (found.landing, found.checks, found.checked_sha) == ("merged", "failing", MERGE)
    assert found.failing == ("main / test",)
    assert "#12 is merged" in found.reason and "merge commit" in found.reason
    assert found.settled is True


def test_merged_work_without_checks_on_the_default_branch_keeps_its_own():
    merged = _pull(
        state="MERGED", merged=True, head_rollup=_rollup("SUCCESS"),
        mergeCommit={"oid": MERGE, "statusCheckRollup": None},
    )
    found = evidence.from_payload(_answer(merged), SHA)
    assert (found.landing, found.checks, found.checked_sha) == ("merged", "passing", SHA)
    assert "pull request's head" in found.reason


def _queued(history: list[tuple[str, str]], head_state: str = "SUCCESS") -> Evidence:
    """Merged through a merge queue that cancelled this commit's own run."""
    cancelled = _rollup(
        "FAILURE",
        ("check", "lint", "SUCCESS"),
        ("check", "e2e (windows)", "CANCELLED"),
        ("check", "CI gate", "CANCELLED"),
    )
    merged = _pull(
        state="MERGED", merged=True, head_rollup=_rollup(head_state),
        mergeCommit={"oid": MERGE, "statusCheckRollup": cancelled},
    )
    return evidence.from_payload(_answer(merged, history=history), SHA)


def test_a_cancelled_run_on_the_merge_commit_is_not_a_failure():
    """A merge queue tests several pull requests as one: the last commit carries the result."""
    newest, next_one, older = "d" * 40, "e" * 40, "f" * 40
    found = _queued([(newest, "FAILURE"), (next_one, "SUCCESS"), ("9" * 40, ""),
                     (MERGE, "FAILURE"), (older, "SUCCESS")])
    assert (found.landing, found.checks, found.checked_sha) == ("merged", "passing", next_one)
    assert found.failing == ()
    assert "next commit on the default branch" in found.reason
    assert found.settled is True


def test_a_red_commit_after_the_merge_is_never_skipped_for_a_later_green_one():
    """The red may be this work's doing: then only the pull request's own checks are known."""
    found = _queued([("d" * 40, "SUCCESS"), ("e" * 40, "FAILURE"), (MERGE, "FAILURE")])
    assert (found.checks, found.checked_sha) == ("passing", SHA)
    assert "pull request's head" in found.reason


def test_checks_still_running_on_the_next_commit_are_waited_for():
    found = _queued([("d" * 40, "PENDING"), (MERGE, "FAILURE"), ("f" * 40, "SUCCESS")])
    assert (found.landing, found.checks, found.settled) == ("merged", "running", False)
    assert "still run" in found.reason


def test_a_green_commit_before_the_merge_says_nothing_about_it():
    older = "f" * 40
    # No later commit yet: what ran on the pull request is what is known.
    found = _queued([(MERGE, "FAILURE"), (older, "SUCCESS")])
    assert (found.checks, found.checked_sha) == ("passing", SHA)
    assert "pull request's head" in found.reason
    # The merge commit is too far back to be found: the same.
    assert _queued([("d" * 40, "SUCCESS")]).checked_sha == SHA
    assert _queued([]).checked_sha == SHA
    # Nothing passed anywhere: no checks completed, and the record waits.
    nothing = _queued([(MERGE, "FAILURE")], head_state="PENDING")
    assert (nothing.checks, nothing.settled) == ("running", False)


def test_a_cancelled_run_beside_a_failed_one_is_still_a_failure():
    rollup = _rollup(
        "FAILURE", ("check", "unit", "FAILURE"), ("check", "e2e", "CANCELLED")
    )
    found = evidence.from_payload(_answer(_pull(head_rollup=rollup)), SHA)
    assert (found.checks, found.failing) == ("failing", ("unit",))
    # Red without a name in sight (more checks than one answer lists) stays red.
    unnamed = evidence.from_payload(_answer(_pull(head_rollup=_rollup("FAILURE"))), SHA)
    assert (unnamed.checks, unnamed.failing) == ("failing", ())
    # Only cancelled: nothing completed.
    only = _rollup("FAILURE", ("check", "unit", "CANCELLED"))
    assert evidence.from_payload(_answer(_pull(head_rollup=only)), SHA).checks == "none"


def test_merged_work_whose_checks_still_run_is_waited_for():
    merged = _pull(
        state="MERGED", merged=True, head_rollup=_rollup("SUCCESS"),
        mergeCommit={"oid": MERGE, "statusCheckRollup": _rollup("PENDING")},
    )
    found = evidence.from_payload(_answer(merged), SHA)
    assert (found.landing, found.checks, found.settled) == ("merged", "running", False)


def test_a_pull_request_closed_without_a_merge_is_not_landed():
    found = evidence.from_payload(
        _answer(_pull(state="CLOSED", head_rollup=_rollup("SUCCESS"))), SHA
    )
    assert found.landing == "pr_closed"
    assert found.settled is True
    assert "closed without a merge" in found.reason


def test_of_several_pull_requests_the_one_this_commit_heads_counts():
    other = _pull(7, head=OTHER, head_rollup=_rollup("FAILURE"))
    mine = _pull(8, head_rollup=_rollup("SUCCESS"))
    assert evidence.from_payload(_answer(other, mine), SHA).pr == 8
    # None headed by it: a merged one says more than an open one.
    merged = _pull(9, head=OTHER, state="MERGED", merged=True,
                   mergeCommit={"oid": MERGE, "statusCheckRollup": _rollup("SUCCESS")})
    found = evidence.from_payload(_answer(other, merged), SHA)
    assert (found.pr, found.landing, found.checks) == (9, "merged", "passing")


# ------------------------------------------------------------------ settled


@pytest.mark.parametrize(
    ("found", "settled"),
    [
        (Evidence("none", "none"), True),
        (Evidence("pr_closed", "failing"), True),
        (Evidence("pushed", "passing"), True),
        (Evidence("pushed", "running"), False),
        (Evidence("pushed", "none"), False),
        (Evidence("merged", "passing"), True),
        (Evidence("merged", "failing"), True),
        (Evidence("merged", "none"), False),
        (Evidence("pr_open", "failing"), False),
        (Evidence("pr_open", "failing", draft=True), True),
        (Evidence("unknown", "unknown"), True),
        (Evidence("unknown", "unknown", transient=True), False),
    ],
)
def test_what_is_worth_reading_again(found: Evidence, settled: bool):
    assert found.settled is settled


# ------------------------------------------------------------------- asking


def test_only_a_repository_on_github_is_asked_about():
    assert evidence.github_repo("github.com/acme/notes") == ("acme", "notes")
    assert evidence.github_repo("github.com/acme/notes.py") == ("acme", "notes.py")
    assert evidence.github_repo("gitlab.com/acme/notes") is None
    assert evidence.github_repo("path:abc123") is None
    assert evidence.github_repo("") is None

    asked: list[tuple[str, str, str]] = []

    def ask(owner: str, name: str, oid: str) -> dict[str, Any]:
        asked.append((owner, name, oid))
        return _answer(rollup=_rollup("SUCCESS"))

    elsewhere = evidence.read("gitlab.com/acme/notes", SHA, ask=ask)
    assert (elsewhere.landing, elsewhere.settled) == ("unknown", True)
    nothing = evidence.read("github.com/acme/notes", "", ask=ask)
    assert (nothing.landing, nothing.settled) == ("none", True)
    assert asked == []

    found = evidence.read("github.com/acme/notes", SHA, ask=ask)
    assert asked == [("acme", "notes", SHA)]
    assert (found.landing, found.checks) == ("pushed", "passing")


def test_github_out_of_reach_is_unknown_and_asked_again():
    from dodaios.agentic_ide.github_link import GitHubError

    def down(*_args: str) -> dict[str, Any]:
        raise GitHubError("GitHub could not be reached.", code="unreachable")

    def signed_out(*_args: str) -> dict[str, Any]:
        raise GitHubError("GitHub is not connected.", code="not_connected")

    def broken(*_args: str) -> dict[str, Any]:
        raise RuntimeError("boom")

    unreachable = evidence.read("github.com/acme/notes", SHA, ask=down)
    assert (unreachable.landing, unreachable.checks) == ("unknown", "unknown")
    assert unreachable.settled is False
    assert "could not be reached" in unreachable.reason
    # Without a connection asking again tells nothing new.
    assert evidence.read("github.com/acme/notes", SHA, ask=signed_out).settled is True
    assert evidence.read("github.com/acme/notes", SHA, ask=broken).settled is False
    garbage = evidence.read("github.com/acme/notes", SHA, ask=lambda *_a: "garbage")
    assert (garbage.landing, garbage.settled) == ("unknown", False)


def test_the_question_goes_out_with_the_persons_own_connection(monkeypatch):
    from dodaios.agentic_ide import github_link

    calls: list[tuple[str, dict[str, Any]]] = []
    credentials = [github_link.Credential("tok-1", "gh")]
    asked_for_token = []

    def credential() -> Any:
        asked_for_token.append(1)
        return credentials[0]

    def graphql(token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        calls.append((token, variables))
        assert "associatedPullRequests" in query
        return _answer(_pull(head_rollup=_rollup("SUCCESS")))

    monkeypatch.setattr(evidence, "_token", None)
    monkeypatch.setattr(github_link, "credential", credential)
    monkeypatch.setattr(github_link, "graphql", graphql)

    first = evidence.read("github.com/acme/notes", SHA)
    second = evidence.read("github.com/acme/notes", OTHER)

    assert (first.landing, first.pr) == ("pr_open", 12)
    assert second.head_sha == OTHER
    assert calls == [
        ("tok-1", {"owner": "acme", "name": "notes", "oid": SHA, "history": 50}),
        ("tok-1", {"owner": "acme", "name": "notes", "oid": OTHER, "history": 50}),
    ]
    # The token is looked up once for both.
    assert len(asked_for_token) == 1


def test_without_a_github_connection_nothing_is_asked(monkeypatch):
    from dodaios.agentic_ide import github_link

    def never(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("no call without a token")

    monkeypatch.setattr(evidence, "_token", None)
    monkeypatch.setattr(github_link, "credential", lambda: None)
    monkeypatch.setattr(github_link, "graphql", never)
    found = evidence.read("github.com/acme/notes", SHA)
    assert (found.landing, found.checks, found.settled) == ("unknown", "unknown", True)
    assert "not connected" in found.reason
