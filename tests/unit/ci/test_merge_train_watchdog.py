"""The merge train's watchdog: stuck pull requests, merge freezes, abandoned ones.

Small fakes stand in for ``gh``; nothing reaches GitHub.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from scripts.ci import agent_integrate, merge_freeze

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
REPO = "example/project"


def _iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat().replace("+00:00", "Z")


class _FakeGh:
    """Records gh calls instead of reaching GitHub."""

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> int:
        self.calls.append(args)
        return 0

    def named(self, *prefix: str) -> list[tuple[str, ...]]:
        return [c for c in self.calls if c[: len(prefix)] == prefix]


class _FakeGhJson:
    """Answers ``gh_json`` reads from a table keyed by the first matching
    argument fragment; records every question."""

    def __init__(self, answers: dict[str, object]):
        self.answers = answers
        self.asked: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> object:
        self.asked.append(args)
        joined = " ".join(args)
        for fragment, answer in self.answers.items():
            if fragment in joined:
                return answer
        return None


def _verdict(**overrides):
    base = {
        "number": 7,
        "action": "merge",
        "state": "success",
        "merge_state": "CLEAN",
        "labels": set(),
        "auto_merge": False,
        "idle_minutes": 31.0,
    }
    return agent_integrate.watch_verdict(**{**base, **overrides})


# ----- C2: stuck pull requests


def test_green_but_never_queued_for_half_an_hour_is_stuck():
    verdict = _verdict()
    assert verdict["reason"] == "green-idle" and verdict["comment"]
    assert verdict["step"] == "Request auto-merge: `gh pr merge 7 --auto --squash`."
    assert _verdict(idle_minutes=29.0) is None
    assert _verdict(idle_minutes=None) is None  # CI still running


def test_a_pull_request_github_lands_by_itself_is_never_stuck():
    assert _verdict(action="queued") is None
    assert _verdict(auto_merge=True) is None
    assert _verdict(auto_merge=True, state="failure", idle_minutes=500.0) is None


def test_a_merge_freeze_is_an_expected_wait_not_a_stuck_one():
    assert _verdict(frozen=True, idle_minutes=100.0) is None
    # A red one is still told: the freeze does not fix its CI.
    assert _verdict(frozen=True, state="failure", idle_minutes=100.0)["reason"] == "red-idle"


def test_a_head_the_queue_failed_asks_for_a_fix_not_for_auto_merge():
    verdict = _verdict(action="held")
    assert verdict["reason"] == "green-idle" and verdict["step"].startswith("Push a fix")


def test_red_without_a_new_commit_for_an_hour_names_the_failing_checks():
    verdict = _verdict(state="failure", idle_minutes=60.0, failing=["Lint", "Tests (ubuntu)"])
    assert verdict["reason"] == "red-idle"
    assert verdict["step"] == "Fix the failing checks: `Lint`, `Tests (ubuntu)`."
    assert _verdict(state="failure", idle_minutes=59.0) is None
    assert _verdict(state="failure", idle_minutes=90.0)["step"] == "Fix the failing checks."


def test_an_unresolved_conflict_is_stuck_without_a_second_comment():
    verdict = _verdict(merge_state="DIRTY", labels={"needs-rebase"}, idle_minutes=None)
    assert verdict["reason"] == "conflict" and verdict["comment"] is False
    # A conflict the train has not tried yet is its own job, not stuck.
    assert _verdict(merge_state="DIRTY", action="wait") is None


def test_run_finished_at_reads_the_newest_completed_pull_request_run():
    done = {"event": "pull_request", "status": "completed", "conclusion": "success"}
    runs = [
        {**done, "created_at": "2026-10-19T10:00:00Z", "updated_at": "2026-10-19T10:20:00Z"},
        {**done, "created_at": "2026-10-19T11:00:00Z", "updated_at": "2026-10-19T11:15:00Z"},
        {**done, "event": "workflow_dispatch", "created_at": "2026-10-19T11:30:00Z"},
    ]
    assert agent_integrate.run_finished_at(runs) == "2026-10-19T11:15:00Z"
    running = [*runs, {"event": "pull_request", "status": "in_progress", "created_at": "z"}]
    assert agent_integrate.run_finished_at(running) is None
    assert agent_integrate.run_finished_at([]) is None


def test_failing_jobs_leave_out_the_gate_that_only_repeats_them(monkeypatch):
    jobs = {
        "jobs": [
            {"name": "Lint", "conclusion": "failure"},
            {"name": "Tests", "conclusion": "success"},
            {"name": "Windows", "conclusion": "timed_out"},
            {"name": "CI gate", "conclusion": "failure"},
        ]
    }
    monkeypatch.setattr(agent_integrate, "gh_json", _FakeGhJson({"/jobs": jobs}))
    assert agent_integrate.failing_jobs(REPO, 12) == ["Lint", "Windows"]
    assert agent_integrate.failing_jobs(REPO, None) == []


def test_a_planned_entry_reads_its_failing_jobs_and_earlier_comment(monkeypatch):
    marker = agent_integrate.stuck_marker("a" * 40)
    fake = _FakeGhJson(
        {
            "/runs/12/jobs": {"jobs": [{"name": "Lint", "conclusion": "failure"}]},
            "pr view": {"comments": [{"body": marker}]},
        }
    )
    monkeypatch.setattr(agent_integrate, "gh_json", fake)
    entry = {
        **_entry(),
        "state": "failure",
        "run_id": 12,
        "merge_state": "CLEAN",
        "auto_merge": False,
        "idle_minutes": 75.0,
        "frozen_by": None,
    }
    verdict = agent_integrate.watch_entry(REPO, entry)
    assert verdict["step"] == "Fix the failing checks: `Lint`." and verdict["told"] is True
    asked = len(fake.asked)
    # A moving pull request costs no further question.
    assert agent_integrate.watch_entry(REPO, {**entry, "idle_minutes": 5.0}) is None
    assert len(fake.asked) == asked


def _plan(entries, **extra):
    return {"repo": REPO, "main": "m" * 40, "queue": True, "entries": entries, **extra}


def _entry(number=7, action="wait", labels=(), watch=None, head="a" * 40):
    return {
        "number": number,
        "branch": f"claude/{number}",
        "head": head,
        "id": f"PR_{number}",
        "action": action,
        "labels": list(labels),
        "watch": watch,
    }


def test_a_stuck_pull_request_is_labelled_and_told_its_next_step_once(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    verdict = {**_verdict(), "told": False}
    agent_integrate.apply(tmp_path, _plan([_entry(watch=verdict)]), False, True)
    assert len(fake.named("label", "create")) == len(agent_integrate.TRAIN_LABELS)
    assert ("pr", "edit", "7", "--repo", REPO, "--add-label", "stuck") in fake.calls
    (comment,) = fake.named("pr", "comment")
    body = comment[-1]
    assert "**Next step:** Request auto-merge: `gh pr merge 7 --auto --squash`." in body
    assert agent_integrate.stuck_marker("a" * 40) in body

    # The next tick: labelled, and the comment for this head is already there.
    quiet = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", quiet)
    told = _entry(labels=["stuck"], watch={**verdict, "told": True})
    agent_integrate.apply(tmp_path, _plan([told]), False, True)
    assert not quiet.calls


def test_a_new_head_gets_its_own_comment_even_while_still_labelled(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    verdict = {**_verdict(state="failure", idle_minutes=70.0), "told": False}
    agent_integrate.apply(
        tmp_path, _plan([_entry(labels=["stuck"], watch=verdict, head="b" * 40)]), False, True
    )
    assert not fake.named("pr", "edit")  # the label is already on
    (comment,) = fake.named("pr", "comment")
    assert agent_integrate.stuck_marker("b" * 40) in comment[-1]


def test_already_told_reads_the_marker_and_stays_quiet_when_it_cannot_read(monkeypatch):
    marker = agent_integrate.stuck_marker("a" * 40)
    comments = {"comments": [{"body": "hello"}, {"body": f"stuck\n\n{marker}"}]}
    monkeypatch.setattr(agent_integrate, "gh_json", _FakeGhJson({"pr view": comments}))
    assert agent_integrate.already_told(REPO, 7, marker)
    assert not agent_integrate.already_told(REPO, 7, agent_integrate.stuck_marker("c" * 40))
    monkeypatch.setattr(agent_integrate, "gh_json", _FakeGhJson({}))
    assert agent_integrate.already_told(REPO, 7, marker)


def test_the_stuck_label_goes_once_the_pull_request_moves(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    agent_integrate.apply(tmp_path, _plan([_entry(labels=["stuck"])]), False, True)
    assert fake.calls == [("pr", "edit", "7", "--repo", REPO, "--remove-label", "stuck")]


def test_enqueueing_a_green_pull_request_is_moving_it(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    verdict = {**_verdict(), "told": False}
    entry = _entry(action="merge", labels=["stuck"], watch=verdict)
    agent_integrate.apply(tmp_path, _plan([entry]), False, False)  # merge bot token
    assert len(fake.named("api", "graphql")) == 1
    assert ("pr", "edit", "7", "--repo", REPO, "--remove-label", "stuck") in fake.calls
    assert not fake.named("pr", "comment")


def test_github_token_cannot_enqueue_so_the_green_pull_request_is_labelled(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    verdict = {**_verdict(), "told": False}
    agent_integrate.apply(tmp_path, _plan([_entry(action="merge", watch=verdict)]), False, True)
    assert not fake.named("api", "graphql")
    assert fake.named("pr", "comment") and fake.named("pr", "edit")


def test_a_conflict_the_train_could_not_resolve_adds_stuck_to_needs_rebase(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    state = tmp_path / "state" / "pr-7.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"status": "conflict", "unresolved": ["a.py"]}), "utf-8")
    agent_integrate.apply(tmp_path, _plan([_entry(action="update")]), False, True)
    edits = fake.named("pr", "edit")
    assert ("pr", "edit", "7", "--repo", REPO, "--add-label", "needs-rebase") in edits
    assert ("pr", "edit", "7", "--repo", REPO, "--add-label", "stuck") in edits
    assert len(fake.named("pr", "comment")) == 1  # the needs-rebase report only


def test_a_dry_run_reports_the_watchdog_and_touches_nothing(tmp_path, monkeypatch, capsys):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    plan = _plan(
        [_entry(watch={**_verdict(), "told": False}), _entry(number=8, labels=["stuck"])],
        stale=[{"number": 9, "action": "close", "idle_days": 15.0}],
        expired_freezes=[{"number": 10, "marker": "<!-- m -->", "age_hours": 3.0}],
    )
    agent_integrate.apply(tmp_path, plan, True, True)
    assert not fake.calls
    out = capsys.readouterr().out
    assert "would label and comment" in out and "would lift" in out
    assert "#9: no commit for 15.0 days; would close" in out
    assert "#10: merge freeze expired; would comment" in out


# ----- C3: merge freeze


def _freeze_answers(labelled: dict[int, timedelta]) -> dict[str, object]:
    answers: dict[str, object] = {
        "--label merge-freeze": [{"number": n, "title": f"PR {n}"} for n in labelled]
    }
    for number, age in labelled.items():
        answers[f"issues/{number}/events"] = [
            {"event": "labeled", "label": {"name": "merge-freeze"}, "created_at": _iso(age)}
        ]
    return answers


def test_a_young_freeze_holds_every_other_pull_request(monkeypatch):
    fake = _FakeGhJson(_freeze_answers({50: timedelta(minutes=30)}))
    monkeypatch.setattr(agent_integrate, "gh_json", fake)
    held_by, expired = agent_integrate.freeze_lookup(REPO, NOW)
    assert held_by(7).number == 50
    assert held_by(50) is None  # the freeze holder itself may land
    assert expired == []
    listings = [a for a in fake.asked if "--label" in a]
    assert len(listings) == 1  # one listing per tick, however many ask


def test_an_expired_freeze_holds_nothing_and_is_listed_for_one_notice(monkeypatch):
    fake = _FakeGhJson(_freeze_answers({50: timedelta(hours=3)}))
    monkeypatch.setattr(agent_integrate, "gh_json", fake)
    held_by, expired = agent_integrate.freeze_lookup(REPO, NOW)
    assert held_by(7) is None
    assert [f.number for f in expired] == [50]
    marker = agent_integrate.freeze_marker(expired[0])
    assert expired[0].since.isoformat() in marker


def test_a_frozen_pull_request_is_neither_enqueued_nor_merged(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    entry = _entry(action="frozen")
    entry["note"] = "merge freeze held by PR #50 (move); it lapses in 60 min at the latest"
    agent_integrate.apply(tmp_path, _plan([entry]), False, False)
    agent_integrate.apply(tmp_path, {**_plan([entry]), "queue": False}, False, False)
    assert not fake.calls


def test_the_expired_freeze_notice_carries_its_marker(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    plan = _plan([], expired_freezes=[{"number": 50, "marker": "<!-- f -->", "age_hours": 3.1}])
    agent_integrate.apply(tmp_path, plan, False, True)
    ((*_, body),) = fake.named("pr", "comment")
    assert body.startswith(agent_integrate.FREEZE_EXPIRED) and body.endswith("<!-- f -->")
    assert "older than 2 h" in agent_integrate.FREEZE_EXPIRED
    assert merge_freeze.FREEZE_LABEL == "merge-freeze"


# ----- C4: abandoned pull requests


def _pr(number=7, branch="claude/x", labels=(), **extra):
    return {
        "number": number,
        "headRefName": branch,
        "baseRefName": "main",
        "isDraft": True,
        "isCrossRepository": False,
        "labels": [{"name": name} for name in labels],
        "author": {"login": "someone"},
        "createdAt": _iso(timedelta(days=30)),
        **extra,
    }


def test_drafts_count_but_dependabot_forks_and_other_branches_never_do():
    assert agent_integrate.stale_candidate(_pr())
    assert agent_integrate.stale_candidate(_pr(branch="feature/x", labels=["auto-merge"]))
    assert not agent_integrate.stale_candidate(_pr(branch="feature/x"))
    assert not agent_integrate.stale_candidate(_pr(author={"login": "app/dependabot"}))
    assert not agent_integrate.stale_candidate(
        _pr(branch="dependabot/pip/x", labels=["auto-merge"])
    )
    assert not agent_integrate.stale_candidate(_pr(isCrossRepository=True))
    assert not agent_integrate.stale_candidate(_pr(baseRefName="release"))


def test_stale_verdicts():
    verdict = agent_integrate.stale_verdict
    assert verdict(set(), 6.9, None) is None
    assert verdict(set(), 7.0, None) == "warn"
    assert verdict({"stale"}, 10.0, 3.0) is None  # warned, the week is not over
    assert verdict({"stale"}, 14.0, 7.0) == "close"
    # Warned only yesterday (the train is new, the pull request old): a full week first.
    assert verdict({"stale"}, 40.0, 1.0) is None
    assert verdict({"stale"}, 40.0, None) is None  # label age unknown: never closed
    assert verdict({"stale"}, 2.0, 8.0) == "unstale"  # a new commit
    for exempt in ("keep", "needs-human", "merge-freeze", "wip", "do-not-merge"):
        assert verdict({exempt}, 40.0, None) is None
        assert verdict({exempt, "stale"}, 40.0, 30.0) == "unstale"


def _activity(*prs: tuple[int, list[tuple[timedelta, str]]]) -> dict:
    nodes = [
        {
            "number": number,
            "commits": {
                "nodes": [
                    {"commit": {"committedDate": _iso(age), "author": {"name": who}}}
                    for age, who in commits
                ]
            },
        }
        for number, commits in prs
    ]
    return {"data": {"repository": {"pullRequests": {"nodes": nodes}}}}


def test_the_trains_own_merges_of_main_are_not_activity(monkeypatch):
    train = agent_integrate.TRAIN_AUTHOR
    answer = _activity(
        (1, [(timedelta(days=20), "agent"), (timedelta(days=1), train)]),
        (2, [(timedelta(days=9), train), (timedelta(days=2), train)]),
        (3, []),
    )
    monkeypatch.setattr(agent_integrate, "gh_json", _FakeGhJson({"graphql": answer}))
    found = agent_integrate.last_activity(REPO)
    assert found[1] == _iso(timedelta(days=20))
    # Only train commits in view: the oldest of them, never staler than the truth.
    assert found[2] == _iso(timedelta(days=9))
    assert 3 not in found


def test_stale_sweep_warns_closes_and_lifts(monkeypatch):
    week = timedelta(days=8)
    answers = {
        "graphql": _activity(
            (1, [(week, "agent")]),
            (2, [(timedelta(days=15), "agent")]),
            (3, [(timedelta(hours=3), "agent")]),
            (4, [(timedelta(days=30), "agent")]),
            (5, [(timedelta(days=30), "agent")]),
        ),
        "issues/2/events": [
            {"event": "labeled", "label": {"name": "stale"}, "created_at": _iso(week)}
        ],
    }
    fake = _FakeGhJson(answers)
    monkeypatch.setattr(agent_integrate, "gh_json", fake)
    prs = [
        _pr(1),
        _pr(2, labels=["stale"]),
        _pr(3, labels=["stale"]),
        _pr(4, labels=["keep"]),
        _pr(5, branch="dependabot/npm/x", author={"login": "app/dependabot"}),
        _pr(6),  # its activity could not be read
        # Opened today on a month-old commit.
        _pr(1, createdAt=_iso(timedelta(hours=1))),
    ]
    sweep = agent_integrate.stale_sweep(REPO, prs, NOW)
    assert [(item["number"], item["action"]) for item in sweep] == [
        (1, "warn"),
        (2, "close"),
        (3, "unstale"),
    ]


def test_the_sweep_acts_only_outside_a_dry_run(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    monkeypatch.setattr(agent_integrate, "already_told", lambda *_: False)
    stale = [
        {"number": 1, "action": "warn", "idle_days": 8.0},
        {"number": 2, "action": "close", "idle_days": 15.0},
        {"number": 3, "action": "unstale", "idle_days": 0.1},
    ]
    agent_integrate.apply(tmp_path, _plan([], stale=stale), True, True)
    assert not fake.calls
    agent_integrate.apply(tmp_path, _plan([], stale=stale), False, True)
    warning = f"{agent_integrate.STALE_WARNING}\n\n{agent_integrate.STALE_MARKER}"
    assert ("pr", "comment", "1", "--repo", REPO, "--body", warning) in fake.calls
    assert ("pr", "edit", "1", "--repo", REPO, "--add-label", "stale") in fake.calls
    close = ("pr", "close", "2", "--repo", REPO, "--comment", agent_integrate.STALE_CLOSING)
    assert close in fake.calls
    assert ("pr", "edit", "3", "--repo", REPO, "--remove-label", "stale") in fake.calls
    assert agent_integrate.STALE_WARNING == (
        "No activity for 7 days; this closes in 7 more days unless labelled `keep`."
    )


def test_the_train_creates_its_labels_idempotently_and_once_per_run(tmp_path, monkeypatch):
    fake = _FakeGh()
    monkeypatch.setattr(agent_integrate, "gh", fake)
    stale = [{"number": n, "action": "warn", "idle_days": 8.0} for n in (1, 2)]
    agent_integrate.apply(tmp_path, _plan([], stale=stale), False, True)
    created = fake.named("label", "create")
    assert {c[2] for c in created} == {"stuck", "stale", "keep", "merge-freeze"}
    assert all("--force" in c for c in created) and len(created) == 4
