"""The team-thread coordinator: order of work, agreement, bounds and stepping in."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.agent_chat.team import SeatPick, TeamError, TeamThreads, TeamThreadStore
from jarvis.agent_chat.team.port import TurnResult
from jarvis.agent_chat.team.signals import parse_review, parse_vote
from jarvis.agent_chat.team.workspace import GitWorkspace
from tests.fakes.fake_team_turns import (
    AGREE,
    APPROVE,
    FakeTurns,
    FakeWorkspace,
    changes,
    object_to,
)

SEATS = [
    SeatPick("claude", name="Claude", family="claude"),
    SeatPick("gpt", name="GPT", family="openai"),
    SeatPick("gemini", name="Gemini", family="gemini"),
]


def _engine(
    turns: FakeTurns,
    *,
    store: TeamThreadStore | None = None,
    workspace: FakeWorkspace | None = None,
) -> TeamThreads:
    return TeamThreads(
        store or TeamThreadStore(":memory:"), turns, workspace=workspace or FakeWorkspace()
    )


async def _run(engine: TeamThreads, tmp_path: Path, **kwargs) -> dict:
    kwargs.setdefault("seats", SEATS)
    snap = await engine.start(task="Add a retry to the uploader", cwd=str(tmp_path), **kwargs)
    await engine.settled(snap["team_id"])
    return engine.snapshot(snap["team_id"])


def _kinds(snap: dict) -> list[str]:
    return [e["kind"] for e in snap["entries"] if e["kind"] != "notice"]


def _codes(snap: dict) -> list[str]:
    return [e["payload"]["code"] for e in snap["entries"] if e["kind"] == "notice"]


async def test_a_team_carries_one_task_from_plan_to_reviewed_result(tmp_path: Path) -> None:
    turns = FakeTurns()
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    assert snap["phase"] == "done"
    kinds = _kinds(snap)
    assert kinds.count("draft") == 3
    assert kinds.count("critique") == 3
    assert kinds.count("plan") == 1
    assert kinds.count("vote") == 2
    assert kinds.count("build") == 1
    assert kinds.count("review") == 2
    assert kinds[-1] == "summary"
    assert snap["entries"][-1]["payload"]["outcome"] == "done"
    assert "plan_agreed" in _codes(snap)
    # The author of the agreed plan builds; the two others review.
    assert snap["builder"] == "m1"
    assert {e["author"] for e in snap["entries"] if e["kind"] == "review"} == {"m2", "m3"}
    assert snap["usage"]["turns"] == 3 + 3 + 1 + 2 + 1 + 2


async def test_first_plans_are_written_blind(tmp_path: Path) -> None:
    turns = FakeTurns()
    await _run(_engine(turns), tmp_path)

    for provider in ("claude", "gpt", "gemini"):
        (prompt,) = turns.prompts(provider, "draft")
        assert "Add a retry to the uploader" in prompt
        assert "draft by" not in prompt
    # The challenge shows the other two plans and never the reader's own.
    (challenge,) = turns.prompts("gpt", "critique")
    assert "draft by claude" in challenge
    assert "draft by gemini" in challenge
    assert "draft by gpt" not in challenge


async def test_an_objection_leads_to_a_new_plan_by_another_member(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "vote" and provider == "gpt" and nth == 0:
            return object_to("The plan never says how the retry is tested.")
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    plans = [e for e in snap["entries"] if e["kind"] == "plan"]
    assert [p["author"] for p in plans] == ["m1", "m2"]
    assert [p["round"] for p in plans] == [1, 2]
    (second,) = turns.prompts("gpt", "plan")
    assert "The plan never says how the retry is tested." in second
    assert "plan by claude" in second  # the last master plan, quoted
    assert snap["builder"] == "m2"
    (issue,) = snap["issues"]
    assert issue["stage"] == "plan"
    assert issue["by"] == "m2"
    assert issue["resolved"] is True


async def test_a_review_finding_goes_back_to_the_builder_until_it_is_approved(
    tmp_path: Path,
) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "review" and provider == "gemini" and nth == 0:
            return changes("The retry loops forever on a 404.")
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    kinds = _kinds(snap)
    assert kinds.count("fix") == 1
    assert kinds.count("review") == 4  # two reviewers, two rounds
    (fix,) = turns.prompts("claude", "fix")
    assert "The retry loops forever on a 404." in fix
    assert "findings by Gemini" in fix
    again = turns.prompts("gemini", "review")[1]
    assert "review again" in again
    assert "The retry loops forever on a 404." in again
    (issue,) = snap["issues"]
    assert issue["stage"] == "review"
    assert issue["severity"] == "blocking"
    assert issue["resolved"] is True
    summary = snap["entries"][-1]["payload"]
    assert summary["findings"] == 1
    assert summary["blocking"] == 1


async def test_a_plan_nobody_agrees_on_stops_with_the_open_points(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "vote" and provider in ("gpt", "claude"):
            return object_to(f"{provider} wants a different queue.")
        return None

    turns = FakeTurns(script)
    engine = _engine(turns)
    snap = await _run(engine, tmp_path, limits={"plan_rounds": 2})

    assert snap["state"] == "needs_input"
    assert snap["reason"] == "plan_disagreement"
    summary = snap["entries"][-1]
    assert summary["kind"] == "summary"
    assert summary["payload"]["rounds"] == 2
    assert [point["items"] for point in summary["payload"]["open"]] == [
        ["claude wants a different queue."]
    ]
    assert "build" not in _kinds(snap)

    # The person decides: every member reads it, and one more round runs.
    turns.script = None
    await engine.message(snap["team_id"], "Use the existing queue.")
    await engine.settled(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["state"] == "done"
    third = turns.prompts("gemini", "plan")[-1]
    assert "Use the existing queue." in third
    assert done["limits"]["plan_rounds"] == 3


async def test_the_person_can_take_the_plan_as_it_is(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "vote" and provider == "gpt":
            return object_to("Too risky.")
        return None

    engine = _engine(FakeTurns(script))
    snap = await _run(engine, tmp_path, limits={"plan_rounds": 1})
    assert snap["reason"] == "plan_disagreement"

    await engine.accept(snap["team_id"])
    await engine.settled(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["state"] == "done"
    assert "plan_accepted_by_user" in _codes(done)
    # The person overruled the objection; it was not resolved by the team.
    assert [issue["resolved"] for issue in done["issues"]] == [False]


async def test_a_review_nobody_approves_stops_and_can_be_accepted_open(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "review" and provider == "gpt":
            return changes("Still broken.")
        return None

    engine = _engine(FakeTurns(script))
    snap = await _run(engine, tmp_path, limits={"review_rounds": 2})

    assert snap["state"] == "needs_input"
    assert snap["reason"] == "review_disagreement"
    assert snap["entries"][-1]["payload"]["open"][0]["items"] == ["app.py:3: Still broken."]
    assert _kinds(snap).count("fix") == 1  # one answer between the two rounds

    await engine.accept(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["state"] == "done"
    assert done["entries"][-1]["payload"]["outcome"] == "accepted_by_user"
    assert all(not issue["resolved"] for issue in done["issues"])


async def test_a_reply_without_a_verdict_is_never_agreement(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "vote" and provider == "gpt" and nth == 0:
            return "Looks good to me."
        if step == "review" and provider == "gemini" and nth == 0:
            return "Looks good to me."
        return None

    snap = await _run(_engine(FakeTurns(script)), tmp_path)

    assert snap["state"] == "done"
    assert _kinds(snap).count("plan") == 2
    assert _kinds(snap).count("fix") == 1
    assert parse_vote("fine").positive is False
    assert parse_review("fine").positive is False
    assert parse_vote(AGREE).positive is True
    assert parse_review(APPROVE).positive is True
    # "Approve" together with a blocking finding is not an approval.
    mixed = (
        '```team-verdict\n{"verdict": "approve", "findings": '
        '[{"severity": "blocking", "issue": "crash"}]}\n```'
    )
    assert parse_review(mixed).positive is False
    minor = (
        '```team-verdict\n{"verdict": "approve", "findings": '
        '[{"severity": "minor", "issue": "typo"}]}\n```'
    )
    assert parse_review(minor).positive is True


async def test_a_member_that_fails_leaves_and_the_others_go_on(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if provider == "gemini":
            return TurnResult("failed", error="not signed in")
        return None

    snap = await _run(_engine(FakeTurns(script)), tmp_path)

    assert snap["state"] == "done"
    gemini = next(m for m in snap["members"] if m["member_id"] == "m3")
    assert gemini["state"] == "left"
    assert gemini["left_reason"] == "not signed in"
    assert "member_left" in _codes(snap)
    assert {e["author"] for e in snap["entries"] if e["kind"] == "review"} == {"m2"}


async def test_a_team_of_one_cannot_go_on(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if provider == "gpt":
            return TurnResult("failed", error="quota")
        return None

    snap = await _run(_engine(FakeTurns(script)), tmp_path, seats=SEATS[:2])

    assert snap["state"] == "failed"
    assert snap["reason"] == "not_enough_members"


async def test_a_new_builder_takes_over_when_the_builder_leaves(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if provider == "claude" and step == "build":
            return TurnResult("failed", error="crashed")
        return None

    snap = await _run(_engine(FakeTurns(script)), tmp_path)

    assert snap["state"] == "done"
    assert snap["builder"] == "m2"
    assert "builder_changed" in _codes(snap)


async def test_pause_stops_the_turns_and_resume_continues_where_it_was(tmp_path: Path) -> None:
    turns = FakeTurns(hold={"critique"})
    engine = _engine(turns)
    snap = await engine.start(task="Add a retry", cwd=str(tmp_path), seats=SEATS)
    team_id = snap["team_id"]
    await turns.reached("critique", 3)
    working = engine.snapshot(team_id)
    assert [m["working"] for m in working["members"]] == [True, True, True]

    paused = await engine.pause(team_id)
    assert paused["state"] == "paused"
    assert sorted(turns.cancelled) == ["s1", "s2", "s3"]
    assert not any(m["working"] for m in paused["members"])

    turns.hold.clear()
    await engine.resume(team_id)
    await engine.settled(team_id)
    done = engine.snapshot(team_id)
    assert done["state"] == "done"
    # The plans written before the pause were not asked for again.
    assert len(turns.prompts("claude", "draft")) == 1
    assert len(turns.prompts("claude", "critique")) == 2


async def test_stop_ends_the_thread_for_good(tmp_path: Path) -> None:
    turns = FakeTurns(hold={"draft"})
    engine = _engine(turns)
    snap = await engine.start(task="Add a retry", cwd=str(tmp_path), seats=SEATS)
    await turns.reached("draft", 3)

    stopped = await engine.stop(snap["team_id"])

    assert stopped["state"] == "stopped"
    with pytest.raises(TeamError):
        await engine.resume(snap["team_id"])
    with pytest.raises(TeamError):
        await engine.message(snap["team_id"], "one more thing")


async def test_what_the_person_says_reaches_every_member_once(tmp_path: Path) -> None:
    turns = FakeTurns(hold={"critique"})
    engine = _engine(turns)
    snap = await engine.start(task="Add a retry", cwd=str(tmp_path), seats=SEATS)
    await turns.reached("critique", 3)

    await engine.message(snap["team_id"], "Keep the public API unchanged.")
    turns.hold.clear()
    turns.release.set()
    await engine.settled(snap["team_id"])

    assert engine.snapshot(snap["team_id"])["state"] == "done"
    for provider in ("claude", "gpt", "gemini"):
        told = [a.step for a in turns.asked
                if a.provider == provider and "Keep the public API unchanged." in a.prompt]
        assert len(told) == 1, (provider, told)


async def test_the_turn_bound_stops_the_thread_and_resume_raises_it(tmp_path: Path) -> None:
    engine = _engine(FakeTurns())
    snap = await _run(engine, tmp_path, limits={"max_turns": 7})

    assert snap["state"] == "needs_input"
    assert snap["reason"] == "limit_turns"
    assert snap["usage"]["turns"] <= 7

    await engine.resume(snap["team_id"])
    await engine.settled(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["limits"]["max_turns"] == 17
    assert done["state"] == "done"


async def test_a_turn_over_its_time_is_reported_as_stalled(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if provider == "gpt" and step == "critique" and nth == 0:
            return TurnResult("timeout", error="too slow")
        return None

    engine = _engine(FakeTurns(script))
    snap = await _run(engine, tmp_path)

    assert snap["state"] == "needs_input"
    assert snap["reason"] == "stalled"
    assert snap["note"] == "GPT"
    # Nobody left the team: the slow member is asked again on Resume.
    assert all(m["state"] == "active" for m in snap["members"])
    await engine.resume(snap["team_id"])
    await engine.settled(snap["team_id"])
    assert engine.snapshot(snap["team_id"])["state"] == "done"


async def test_cost_is_counted_where_the_seat_reports_it(tmp_path: Path) -> None:
    priced = await _run(_engine(FakeTurns(cost_usd=0.25)), tmp_path, limits={"max_cost_usd": 1})
    assert priced["state"] == "needs_input"
    assert priced["reason"] == "limit_cost"
    assert priced["usage"]["cost_partial"] is False

    unpriced = await _run(_engine(FakeTurns()), tmp_path)
    assert unpriced["usage"]["cost_usd"] == 0
    assert unpriced["usage"]["cost_partial"] is True


async def test_a_thread_left_running_comes_back_paused(tmp_path: Path) -> None:
    store = TeamThreadStore(":memory:")
    turns = FakeTurns(hold={"draft"})
    first = _engine(turns, store=store)
    snap = await first.start(task="Add a retry", cwd=str(tmp_path), seats=SEATS)
    await turns.reached("draft", 3)
    await first.close()  # the app goes down mid-turn

    second = _engine(FakeTurns(sessions=dict(turns.sessions)), store=store)
    back = second.snapshot(snap["team_id"])
    assert back["state"] == "paused"
    assert back["reason"] == "interrupted"

    await second.resume(snap["team_id"])
    await second.settled(snap["team_id"])
    assert second.snapshot(snap["team_id"])["state"] == "done"


async def test_files_changed_in_a_reading_step_are_called_out(tmp_path: Path) -> None:
    workspace = FakeWorkspace()

    def script(provider: str, step: str, nth: int):
        if provider == "gpt" and step == "draft":
            workspace.touch()
        return None

    snap = await _run(_engine(FakeTurns(script), workspace=workspace), tmp_path)

    changed = [e["payload"] for e in snap["entries"]
               if e["kind"] == "notice" and e["payload"]["code"] == "files_changed"]
    assert changed == [{"code": "files_changed", "step": "draft"}]


async def test_the_reviewers_read_the_change_since_the_build_started(tmp_path: Path) -> None:
    workspace = FakeWorkspace()

    def script(provider: str, step: str, nth: int):
        if step == "build":
            workspace.touch()
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns, workspace=workspace), tmp_path)

    build = next(e for e in snap["entries"] if e["kind"] == "build")
    assert build["payload"]["files"] == ["app.py"]
    (review,) = turns.prompts("gpt", "review")
    assert "+new line" in review
    assert "files_changed" not in _codes(snap)


async def test_a_folder_without_git_says_so_and_still_works(tmp_path: Path) -> None:
    turns = FakeTurns()
    snap = await _run(_engine(turns, workspace=FakeWorkspace(tree=None)), tmp_path)

    assert snap["state"] == "done"
    assert "no_git" in _codes(snap)
    assert "not a git repository" in turns.prompts("gpt", "review")[0]


async def test_a_one_family_team_is_told_what_it_cannot_give(tmp_path: Path) -> None:
    seats = [SeatPick("claude", model="opus", family="claude"),
             SeatPick("claude", model="opus", family="claude")]
    snap = await _run(_engine(FakeTurns()), tmp_path, seats=seats)

    assert snap["state"] == "done"
    assert _codes(snap)[0] == "same_family"
    assert [m["name"] for m in snap["members"]] == ["opus 1", "opus 2"]


async def test_start_refuses_what_cannot_be_a_team(tmp_path: Path) -> None:
    turns = FakeTurns(refuse={"gemini"})
    engine = _engine(turns)
    with pytest.raises(TeamError):
        await engine.start(task="x", cwd=str(tmp_path), seats=SEATS[:1])
    with pytest.raises(TeamError):
        await engine.start(task="  ", cwd=str(tmp_path), seats=SEATS)
    with pytest.raises(TeamError):
        await engine.start(task="x", cwd=str(tmp_path / "missing"), seats=SEATS)
    with pytest.raises(TeamError):
        await engine.start(task="x", cwd=str(tmp_path), seats=SEATS)
    # The two seats opened before the refused one were taken back.
    assert turns.discarded == ["s1", "s2"]
    assert engine.threads() == []


async def test_deleting_a_thread_removes_its_member_sessions(tmp_path: Path) -> None:
    turns = FakeTurns()
    engine = _engine(turns)
    snap = await _run(engine, tmp_path)
    assert engine.session_teams() == {sid: snap["team_id"] for sid in ("s1", "s2", "s3")}

    await engine.delete(snap["team_id"])

    assert turns.discarded == ["s1", "s2", "s3"]
    assert engine.threads() == []
    assert engine.session_teams() == {}


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_snapshot_sees_new_files_and_leaves_the_index_alone(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(tmp_path), *args],  # noqa: S607
            capture_output=True, encoding="utf-8", check=True,
        ).stdout

    git("init", "-q")
    git("config", "user.email", "team@example.invalid")
    git("config", "user.name", "Team")
    (tmp_path / "app.py").write_text("one\n", encoding="utf-8")
    git("add", "app.py")
    git("commit", "-q", "-m", "first")
    workspace = GitWorkspace()

    before = workspace.snapshot(str(tmp_path))
    (tmp_path / "app.py").write_text("one\ntwo\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("fresh\n", encoding="utf-8")
    after = workspace.snapshot(str(tmp_path))

    assert before and after and before != after
    change = workspace.change(str(tmp_path), before, after)
    assert sorted(change.files) == ["app.py", "new.py"]
    assert "+two" in change.patch
    assert "+fresh" in change.patch
    # Nothing was staged and the new file is still untracked.
    assert git("diff", "--cached", "--name-only").strip() == ""
    assert "?? new.py" in git("status", "--porcelain")
