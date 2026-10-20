"""Session badges must describe the exact GitHub branch and pushed commit."""

import time
from types import SimpleNamespace

import pytest

from jarvis.agentic_ide import github_link
from jarvis.agentic_ide import github_status as status

HEAD = "a" * 40
OTHER = "b" * 40
TARGET = status.Checkout("owner/repo", "feature/test", HEAD)


def rollup(conclusion="SUCCESS", state="SUCCESS", phase="COMPLETED"):
    return {
        "state": state,
        "contexts": {
            "totalCount": 1,
            "nodes": [
                {
                    "__typename": "CheckRun",
                    "name": "tests",
                    "status": phase,
                    "conclusion": conclusion,
                    "detailsUrl": "https://github.com/owner/repo/actions/runs/1",
                }
            ],
        },
    }


def pr(number=1, state="OPEN", head=HEAD, **extra):
    return {
        "number": number,
        "url": f"https://github.com/owner/repo/pull/{number}",
        "state": state,
        "headRefName": TARGET.branch,
        "headRefOid": head,
        "headRepository": {"nameWithOwner": TARGET.repo},
        "commits": {"nodes": [{"commit": {"oid": head, "statusCheckRollup": rollup()}}]},
        **extra,
    }


def payload(*prs, head=HEAD, checks=None):
    return {
        "data": {
            "repository": {
                "ref": {"target": {"oid": head, "statusCheckRollup": checks}} if head else None,
                "pullRequests": {"nodes": list(prs)},
            }
        }
    }


@pytest.mark.parametrize(
    "remote, expected",
    [
        ("git@github.com:owner/repo.git", "owner/repo"),
        ("ssh://git@github.com/owner/repo.git", "owner/repo"),
        ("https://github.com/owner/repo.git", "owner/repo"),
        ("https://notgithub.com/owner/repo.git", ""),
        ("https://github.com.evil.invalid/owner/repo", ""),
        ("https://gitlab.com/owner/repo", ""),
    ],
)
def test_remote_host_is_exact(remote, expected):
    assert status._repository(remote) == expected


@pytest.mark.parametrize(
    "state, extra, expected",
    [
        ("OPEN", {}, "open"),
        ("OPEN", {"isDraft": True}, "draft"),
        ("OPEN", {"isInMergeQueue": True}, "queued"),
        ("MERGED", {}, "merged"),
        ("CLOSED", {}, "closed"),
    ],
)
def test_pr_states_survive_branch_deletion(state, extra, expected):
    value = status.parse_status(TARGET, payload(pr(state=state, **extra), head=""), 123)
    assert value.published and value.state == expected
    assert value.ci.state == "success"


def test_local_only_is_unpublished_and_green_checks_do_not_mean_merged():
    assert not status.parse_status(TARGET, payload(head=""), 1).published
    value = status.parse_status(TARGET, payload(checks=rollup()), 1)
    assert value.published and value.state == "branch"
    assert value.ci.state == "success"


def test_reused_branch_does_not_inherit_an_old_merge():
    value = status.parse_status(TARGET, payload(pr(state="MERGED", head=OTHER)), 1)
    assert value.state == "branch" and value.number is None
    # Remote moved too, while the local checkout still has the merged commit.
    value = status.parse_status(TARGET, payload(pr(state="MERGED"), head=OTHER), 1)
    assert value.state == "branch"


def test_other_forks_same_branch_name_are_not_this_session():
    value = status.parse_status(
        TARGET, payload(pr(headRepository={"nameWithOwner": "other/repo"}), head=""), 1
    )
    assert not value.published


def test_fork_pr_in_upstream_is_supported():
    data = payload()
    data["data"]["repository"]["ref"]["associatedPullRequests"] = {
        "nodes": [pr(url="https://github.com/upstream/repo/pull/1")]
    }
    assert status.parse_status(TARGET, data, 1).url == "https://github.com/upstream/repo/pull/1"


def test_new_pushed_tip_wins_over_old_pr_ci():
    value = status.parse_status(
        TARGET, payload(pr(head=OTHER), checks=rollup("FAILURE", "FAILURE")), 1
    )
    assert value.ci.state == "failure" and value.ci.commit == HEAD[:12]


def test_unpushed_local_commits_are_explicit():
    value = status.parse_status(TARGET, payload(pr(head=OTHER), head=OTHER), 1)
    assert value.ci_stale and value.ci.commit == OTHER[:12]


def test_remote_merge_remains_true_when_local_work_has_advanced():
    value = status.parse_status(TARGET, payload(pr(state="MERGED", head=OTHER), head=OTHER), 1)
    assert value.state == "merged" and value.ci.commit == OTHER[:12]


def test_historical_pr_before_this_session_created_the_branch_is_ignored():
    target = status.Checkout(TARGET.repo, TARGET.branch, HEAD, created_at=1_800_000_000)
    value = status.parse_status(
        target, payload(pr(state="MERGED", createdAt="2020-01-01T00:00:00Z")), 1
    )
    assert value.state == "branch" and value.number is None


def test_deleted_fork_branch_uses_its_remembered_pull_request():
    data = payload(head="")
    data["data"]["nodes"] = [pr(state="MERGED", url="https://github.com/upstream/repo/pull/1")]
    value = status.parse_status(TARGET, data, 1)
    assert value.published and value.state == "merged"


def test_folder_only_requests_are_not_evidence_of_session_ownership():
    assert status.statuses({"t1": "workspace-on-main"}) == {"t1": None}


@pytest.mark.parametrize(
    "conclusion, phase, rollup_state, expected",
    [
        ("SUCCESS", "COMPLETED", "SUCCESS", "success"),
        ("FAILURE", "COMPLETED", "FAILURE", "failure"),
        ("TIMED_OUT", "COMPLETED", "FAILURE", "timed_out"),
        ("CANCELLED", "COMPLETED", "FAILURE", "cancelled"),
        ("SKIPPED", "COMPLETED", "SUCCESS", "skipped"),
        ("NEUTRAL", "COMPLETED", "SUCCESS", "neutral"),
        (None, "IN_PROGRESS", "PENDING", "running"),
        (None, "QUEUED", "PENDING", "pending"),
    ],
)
def test_ci_states(conclusion, phase, rollup_state, expected):
    value = status.parse_status(TARGET, payload(checks=rollup(conclusion, rollup_state, phase)), 1)
    assert value.ci.state == expected


def test_incomplete_check_page_uses_github_aggregate():
    checks = rollup("SUCCESS", "FAILURE")
    checks["contexts"]["totalCount"] = 120
    assert status.parse_status(TARGET, payload(checks=checks), 1).ci.state == "failure"


def test_checkout_reads_worktree_head_and_custom_upstream(monkeypatch, tmp_path):
    def git(folder, *args):
        assert folder == tmp_path
        if args[0] == "symbolic-ref":
            return "local-name"
        if args[0] == "for-each-ref":
            return f"{HEAD}\tcompany\trefs/heads/feature/test\trefs/heads/local-name"
        if args[0] == "remote":
            assert args[-1] == "company"
            return "git@github.com:owner/repo.git"
        return ""

    monkeypatch.setattr(status, "_git", git)
    monkeypatch.setattr(status, "_setting", git)
    assert status.checkout(tmp_path, "local-name") == TARGET


def test_detached_head_never_gets_branch_status(monkeypatch, tmp_path):
    monkeypatch.setattr(status, "_git", lambda *_: "")
    assert status.checkout(tmp_path) is None


def test_remote_settings_are_asked_of_git_once_a_minute(monkeypatch, tmp_path):
    status._settings.clear()
    asked = []

    def run(args, cwd):
        asked.append(args)
        # `git config --get` answers an unset option with exit code 1.
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(status.git_overview, "_run", run)
    assert status._setting(tmp_path, "config", "--get", "remote.pushDefault") == ""
    assert status._setting(tmp_path, "config", "--get", "remote.pushDefault") == ""
    assert len(asked) == 1


def test_a_setting_git_gave_no_answer_for_is_asked_again(monkeypatch, tmp_path):
    status._settings.clear()
    answers = [
        None,
        SimpleNamespace(returncode=128, stdout=""),
        SimpleNamespace(returncode=0, stdout="url\n"),
    ]
    monkeypatch.setattr(status.git_overview, "_run", lambda args, cwd: answers.pop(0))
    assert status._setting(tmp_path, "remote", "get-url", "origin") == ""
    assert status._setting(tmp_path, "remote", "get-url", "origin") == ""
    assert status._setting(tmp_path, "remote", "get-url", "origin") == "url"
    assert status._setting(tmp_path, "remote", "get-url", "origin") == "url"
    assert not answers


def test_multiple_panes_share_requests_and_errors_are_unknown(monkeypatch):
    status._slot.cache_clear()
    reads, requests = [], []

    def local(folder, branch, created_at):
        reads.append(folder)
        return TARGET

    def graphql(*args):
        requests.append(args)
        if len(requests) > 1:
            raise github_link.GitHubError("GitHub could not be reached.")
        return payload(pr(state="MERGED"))

    monkeypatch.setattr(status, "checkout", local)
    monkeypatch.setattr(
        status,
        "pane_branches",
        lambda record: [
            SimpleNamespace(folder="worktree", branch=TARGET.branch, created_at=0, unproven=False)
        ],
    )
    monkeypatch.setattr(
        github_link, "credential", lambda: github_link.Credential("test-token", "gh")
    )
    monkeypatch.setattr(github_link, "graphql", graphql)
    records = [status.PaneBranchRecord(pane, pane, "worktree") for pane in ("t1", "t2")]
    panes = status.statuses(records)
    assert len(reads) == len(requests) == 1
    assert panes["t1"] == panes["t2"]
    cached = status._snapshot(TARGET, "test-token")
    cached.fetched_at = 0
    failed = status.statuses(records[:1])["t1"]
    assert failed["published"] and not failed["available"]


def _session(monkeypatch, branches, answers, unproven=()):
    """One pane whose session worked on ``branches``; GitHub answers per branch."""
    status._slot.cache_clear()
    requests: list[str] = []

    def graphql(_token, _query, variables):
        requests.append(variables["branch"])
        return answers[variables["branch"]]

    monkeypatch.setattr(
        status,
        "checkout",
        lambda folder, branch, created_at: status.Checkout(TARGET.repo, branch, HEAD),
    )
    monkeypatch.setattr(
        status,
        "pane_branches",
        lambda record: [
            SimpleNamespace(
                folder="worktree", branch=branch, created_at=0, unproven=branch in unproven
            )
            for branch in branches
        ],
    )
    monkeypatch.setattr(
        github_link, "credential", lambda: github_link.Credential("test-token", "gh")
    )
    monkeypatch.setattr(github_link, "graphql", graphql)
    return requests


def _answer(branch, number, state):
    return payload(pr(number, state, headRefName=branch))


def test_open_work_is_shown_before_a_finished_branch_and_the_rest_is_listed(monkeypatch):
    answers = {
        "claude/merged-last": _answer("claude/merged-last", 3, "MERGED"),
        "claude/still-open": _answer("claude/still-open", 2, "OPEN"),
        "claude/closed-first": _answer("claude/closed-first", 1, "CLOSED"),
    }
    _session(monkeypatch, list(answers), answers)

    pane = status.statuses([status.PaneBranchRecord("t1", "t1", "worktree")])["t1"]

    assert (pane["branch"], pane["state"], pane["number"]) == ("claude/still-open", "open", 2)
    assert [(other["branch"], other["state"]) for other in pane["others"]] == [
        ("claude/merged-last", "merged"),
        ("claude/closed-first", "closed"),
    ]


def test_current_branch_stays_in_front_when_nothing_is_open(monkeypatch):
    answers = {
        "claude/merged-last": _answer("claude/merged-last", 3, "MERGED"),
        "claude/closed-first": _answer("claude/closed-first", 1, "CLOSED"),
    }
    _session(monkeypatch, list(answers), answers)

    pane = status.statuses([status.PaneBranchRecord("t1", "t1", "worktree")])["t1"]

    assert pane["branch"] == "claude/merged-last"
    assert [other["branch"] for other in pane["others"]] == ["claude/closed-first"]


def test_single_branch_has_no_others(monkeypatch):
    answers = {"claude/only": _answer("claude/only", 4, "OPEN")}
    _session(monkeypatch, list(answers), answers)

    pane = status.statuses([status.PaneBranchRecord("t1", "t1", "worktree")])["t1"]

    assert pane["branch"] == "claude/only" and pane["others"] == []


def test_finished_branch_is_read_rarely_and_never_looks_stale(monkeypatch):
    answers = {
        "claude/open": _answer("claude/open", 2, "OPEN"),
        "claude/merged": _answer("claude/merged", 3, "MERGED"),
    }
    requests = _session(monkeypatch, list(answers), answers)
    records = [status.PaneBranchRecord("t1", "t1", "worktree")]
    status.statuses(records)
    for branch in answers:
        status._snapshot(status.Checkout(TARGET.repo, branch, HEAD), "test-token").fetched_at -= 60

    pane = status.statuses(records)["t1"]

    # Both read at first (side by side, in any order); then only the open one.
    assert sorted(requests[:2]) == ["claude/merged", "claude/open"]
    assert requests[2:] == ["claude/open"]
    (merged,) = pane["others"]
    assert merged["state"] == "merged" and merged["available"]
    assert time.time() - merged["fetched_at"] < 5


def test_deleted_branch_needs_its_pull_request_to_count(monkeypatch):
    answers = {
        "claude/current": _answer("claude/current", 5, "OPEN"),
        "claude/deleted-merged": _answer("claude/deleted-merged", 4, "MERGED"),
        "claude/deleted-never-pushed": payload(head=""),
    }
    _session(
        monkeypatch,
        list(answers),
        answers,
        unproven={"claude/deleted-merged", "claude/deleted-never-pushed"},
    )

    pane = status.statuses([status.PaneBranchRecord("t1", "t1", "worktree")])["t1"]

    assert pane["branch"] == "claude/current"
    assert [other["branch"] for other in pane["others"]] == ["claude/deleted-merged"]


def test_pane_whose_only_branch_is_unconfirmed_shows_nothing(monkeypatch):
    answers = {"claude/deleted-never-pushed": payload(head="")}
    _session(monkeypatch, list(answers), answers, unproven=set(answers))

    assert status.statuses([status.PaneBranchRecord("t1", "t1", "worktree")]) == {"t1": None}


def test_route_uses_pane_cwd_and_excludes_remote_computers(monkeypatch):
    from fastapi import HTTPException

    from jarvis.ui.web import agentic_ide_git_routes as routes

    calls = []
    pane = SimpleNamespace(
        name="t1",
        computer_id="",
        cwd=lambda _: "fork-folder",
        history_id="history",
        agent="codex",
        account="",
        resume=None,
        branch="owned",
    )
    remote = SimpleNamespace(name="t2", computer_id="server")
    session = SimpleNamespace(id="w", folder="workspace", terminals=[pane, remote])
    other = SimpleNamespace(id="behind", folder="other", terminals=[])
    monkeypatch.setattr(
        routes,
        "get_registry",
        lambda: SimpleNamespace(
            get=lambda key: session if key == "w" else None, sessions=[session, other]
        ),
    )
    ahead = []
    monkeypatch.setattr(
        status,
        "board",
        lambda key, records, wait: calls.append((records, wait)) or {"panes": {}},
    )
    monkeypatch.setattr(status, "due", lambda key: True)
    monkeypatch.setattr(status, "read_ahead", lambda key, records: ahead.append(key))
    assert routes.session_github_status("w", wait=2, instant=True) == {"panes": {}}
    assert calls[0][1] == 2
    # A caller that does not know `instant` gets the answer once the read lands.
    routes.session_github_status("w", wait=0, instant=False)
    assert calls[1][1] == routes._LEGACY_WAIT_S
    calls[:] = [records for records, _ in calls]
    assert [record.pane for record in calls[0]] == ["t1"]
    assert calls[0][0].folder == "fork-folder"
    assert calls[0][0].created_branch == "owned"
    # The tab behind is read ahead of its first visit; the one in front is not.
    assert set(ahead) == {"behind"}
    with pytest.raises(HTTPException) as error:
        routes.session_github_status("missing")
    assert error.value.status_code == 404


# ------------------------------------------------------------------- board


@pytest.fixture
def boards(monkeypatch):
    """Empty boards, and a `statuses` the test opens and closes by hand."""
    monkeypatch.setattr(status, "_boards", {})
    monkeypatch.setattr(status, "_ahead", {})
    monkeypatch.setattr(status, "_ahead_running", False)
    monkeypatch.setattr(status, "_front_reads", 0)
    status._front_idle.set()
    gate = SimpleNamespace(
        release=__import__("threading").Event(),
        reads=[],
        ttls=[],
        answer=lambda records: {record.pane: {"branch": record.history_id} for record in records},
    )

    def statuses(records, live_ttl=status._LIVE_TTL):
        gate.reads.append([record.pane for record in records])
        gate.ttls.append(live_ttl)
        assert gate.release.wait(5)
        return gate.answer(records)

    monkeypatch.setattr(status, "statuses", statuses)
    return gate


def _settle(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, "the background read did not finish"
        time.sleep(0.01)


def _records(*panes, history="h"):
    return [status.PaneBranchRecord(pane, f"{history}-{pane}", "folder") for pane in panes]


def test_board_answers_at_once_and_reads_in_the_background(boards):
    first = status.board("w", _records("t1"))
    # Nothing read yet: no answer, and the pane is named as waiting for one.
    assert first == {
        "panes": {},
        "refreshing": True,
        "age": None,
        "waiting": ["t1"],
        "failed": False,
    }
    boards.release.set()
    _settle(lambda: not status.board("w", _records("t1"))["refreshing"])
    answer = status.board("w", _records("t1"))
    assert answer["panes"] == {"t1": {"branch": "h-t1"}}
    assert answer["waiting"] == [] and answer["age"] < 5


def test_board_reads_once_while_a_read_runs_and_again_once_it_is_old(boards):
    status.board("w", _records("t1"))
    status.board("w", _records("t1"))
    assert len(boards.reads) == 1
    boards.release.set()
    _settle(lambda: not status._boards["w"].reading)
    status.board("w", _records("t1"))
    assert len(boards.reads) == 1  # Still fresh.
    boards.release.clear()
    status._boards["w"].tried_at -= status._BOARD_TTL
    status._boards["w"].read_at -= status._BOARD_TTL
    answer = status.board("w", _records("t1"))
    # The old answer is served while the newer one is read.
    assert answer["refreshing"] and answer["panes"] == {"t1": {"branch": "h-t1"}}
    assert answer["waiting"] == [] and answer["age"] >= status._BOARD_TTL
    boards.release.set()
    _settle(lambda: len(boards.reads) == 2 and not status._boards["w"].reading)


def test_board_never_shows_a_pane_its_predecessors_answer(boards):
    boards.release.set()
    status.board("w", _records("t1", "t2"))
    _settle(lambda: not status._boards["w"].reading)
    boards.release.clear()
    # T2 now runs another conversation: its old answer is withheld, T1's kept.
    records = _records("t1") + _records("t2", history="new")
    status._boards["w"].tried_at -= status._RETRY_S
    answer = status.board("w", records)
    assert answer["panes"] == {"t1": {"branch": "h-t1"}}
    assert answer["refreshing"] and answer["waiting"] == ["t2"]
    boards.release.set()
    _settle(lambda: not status._boards["w"].reading)
    assert status.board("w", records)["panes"]["t2"] == {"branch": "new-t2"}


def test_a_failed_read_keeps_the_last_answer_and_is_not_retried_at_once(boards):
    boards.release.set()
    status.board("w", _records("t1"))
    _settle(lambda: not status._boards["w"].reading)
    read_at = status._boards["w"].read_at

    def broken(records):
        raise RuntimeError("git vanished")

    boards.answer = broken
    status._boards["w"].tried_at -= status._BOARD_TTL
    status._boards["w"].read_at -= status._BOARD_TTL
    status.board("w", _records("t1"))
    _settle(lambda: not status._boards["w"].reading)
    answer = status.board("w", _records("t1"))
    assert answer["panes"] == {"t1": {"branch": "h-t1"}}
    # Nothing newer is coming: the answer says so instead of looking current.
    assert not answer["refreshing"] and answer["failed"]
    assert status._boards["w"].read_at == read_at - status._BOARD_TTL
    assert len(boards.reads) == 2


def test_a_read_that_cannot_start_leaves_nothing_waiting(boards, monkeypatch):
    def no_thread(*_, **__):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(status.threading, "Thread", no_thread)
    answer = status.board("w", _records("t1"))
    assert not answer["refreshing"] and answer["waiting"] == []
    assert status._front_reads == 0 and status._front_idle.is_set()


def test_tabs_behind_are_read_once_one_after_another_after_the_front(boards):
    status.board("front", _records("t1"))
    status.read_ahead("a", _records("t1"))
    status.read_ahead("b", _records("t1"))
    status.read_ahead("a", _records("t1"))
    assert not status.due("a") and not status.due("b")
    # The read for the tab in front runs alone; the reads ahead wait for it.
    time.sleep(0.05)
    assert len(boards.reads) == 1
    boards.release.set()
    _settle(lambda: len(boards.reads) == 3 and not status._ahead_running)
    assert status.board("a", _records("t1"))["panes"] == {"t1": {"branch": "h-t1"}}


def test_a_visit_takes_over_a_read_ahead_that_has_not_begun(boards):
    status.board("front", _records("t1"))
    status.read_ahead("behind", _records("t1"))
    # Someone switches to the tab behind before its turn came.
    answer = status.board("behind", _records("t1"))
    assert answer["refreshing"] and "behind" not in status._ahead
    boards.release.set()
    _settle(lambda: not status._ahead_running and not status._front_reads)
    assert len(boards.reads) == 2


def test_one_pane_that_cannot_be_read_does_not_cost_the_others_their_status(monkeypatch):
    answers = {"claude/fine": _answer("claude/fine", 6, "OPEN")}
    _session(monkeypatch, list(answers), answers)
    working = status.pane_branches

    def pane_branches(record):
        if record.pane == "broken":
            raise OSError("record vanished mid-read")
        return working(record)

    monkeypatch.setattr(status, "pane_branches", pane_branches)
    records = [
        status.PaneBranchRecord("broken", "broken", "worktree"),
        status.PaneBranchRecord("t1", "t1", "worktree"),
    ]
    panes = status.statuses(records)
    assert panes["broken"] is None
    assert panes["t1"]["number"] == 6


def test_a_tab_behind_is_kept_recent_with_a_slower_github_rhythm(boards):
    boards.release.set()
    status.read_ahead("behind", _records("t1"))
    _settle(lambda: not status._ahead_running)
    assert boards.ttls == [status._WARM_GITHUB_TTL]
    # Recent: not read again.
    assert not status.due("behind")
    status.read_ahead("behind", _records("t1"))
    assert len(boards.reads) == 1
    # Once older than the warm interval, it is read again ahead of a visit.
    status._boards["behind"].read_at -= status._WARM_S
    status._boards["behind"].tried_at -= status._WARM_S
    assert status.due("behind")
    status.read_ahead("behind", _records("t1"))
    _settle(lambda: len(boards.reads) == 2 and not status._ahead_running)
    # The tab in front still asks GitHub on its own, quicker rhythm.
    status.board("front", _records("t1"))
    _settle(lambda: len(boards.reads) == 3 and not status._front_reads)
    assert boards.ttls[-1] == status._LIVE_TTL


def test_a_request_that_waits_gets_the_read_the_moment_it_lands(boards):
    status.board("w", _records("t1"))
    threading = __import__("threading")
    threading.Timer(0.2, boards.release.set).start()
    started = time.monotonic()
    answer = status.board("w", _records("t1"), wait=3)
    assert time.monotonic() - started < 2
    assert not answer["refreshing"] and answer["panes"] == {"t1": {"branch": "h-t1"}}


def test_a_wait_is_bounded_when_the_read_is_slow(boards, monkeypatch):
    monkeypatch.setattr(status, "_MAX_WAIT_S", 0.2)
    status.board("w", _records("t1"))
    started = time.monotonic()
    answer = status.board("w", _records("t1"), wait=5)
    assert 0.15 < time.monotonic() - started < 2
    assert answer["refreshing"] and answer["waiting"] == ["t1"]
    boards.release.set()
    _settle(lambda: not status._front_reads)
