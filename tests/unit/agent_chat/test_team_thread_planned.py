"""The planner-and-builder mode: a living plan, built and reviewed one step at a time."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dodaios.agent_chat.team import SeatPick, TeamError, TeamThreads, TeamThreadStore
from dodaios.agent_chat.team.port import TurnResult
from dodaios.agent_chat.team.signals import parse_plan, parse_step
from tests.fakes.fake_team_turns import (
    FakeTurns,
    FakeWorkspace,
    changes,
    object_to,
    plan,
    step_report,
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
    kwargs.setdefault("mode", "planner_builder")
    snap = await engine.start(task="Add a retry to the uploader", cwd=str(tmp_path), **kwargs)
    await engine.settled(snap["team_id"])
    return engine.snapshot(snap["team_id"])


def _steps(snap: dict) -> list[tuple[str, str, int]]:
    """``(kind, author, round)`` of every contribution, in order."""
    return [
        (e["kind"], e["author"], e["round"])
        for e in snap["entries"]
        if e["kind"] not in ("notice", "user", "summary")
    ]


def _codes(snap: dict) -> list[str]:
    return [e["payload"]["code"] for e in snap["entries"] if e["kind"] == "notice"]


async def test_a_plan_is_built_step_by_step_and_reviewed(tmp_path: Path) -> None:
    turns = FakeTurns()
    snap = await _run(_engine(turns), tmp_path)

    assert (snap["state"], snap["mode"]) == ("done", "planner_builder")
    assert [m["role"] for m in snap["members"]] == ["planner", "builder", "reviewer"]
    assert _steps(snap) == [
        ("plan_version", "m1", 1),
        ("plan_review", "m3", 1),
        ("step_build", "m2", 1),
        ("step_review", "m3", 1),
        ("step_build", "m2", 1),
        ("step_review", "m3", 1),
        # The whole change: the reviewer, and the planner signs off.
        ("review", "m1", 1),
        ("review", "m3", 1),
    ]
    assert [s["status"] for s in snap["plan"]["steps"]] == ["accepted", "accepted"]
    assert snap["plan"]["version"] == 1
    assert snap["plan"]["agreed"] is True
    summary = snap["entries"][-1]["payload"]
    assert summary["outcome"] == "done"
    assert (summary["step_count"], summary["plan_versions"], summary["step_rounds"]) == (2, 1, 2)
    # The builder is given one step at a time, with the whole plan around it.
    first, second = turns.prompts("gpt", "step_build")
    assert "build step 1 of 2" in first
    assert "1. [open] Add the setting  <- this step" in first
    assert "2. [accepted] Use it in the uploader" not in second
    assert "1. [accepted] Add the setting" in second
    # The reviewer holds the step against its check.
    review = turns.prompts("gemini", "step_review")[0]
    assert "Done when: Add the setting works" in review
    assert "signs off" not in review
    assert "You wrote the plan" in turns.prompts("claude", "review")[0]


async def test_two_members_review_each_other(tmp_path: Path) -> None:
    turns = FakeTurns()
    snap = await _run(_engine(turns), tmp_path, seats=SEATS[:2])

    assert snap["state"] == "done"
    assert _steps(snap) == [
        ("plan_version", "m1", 1),
        ("plan_review", "m2", 1),  # the builder reads the plan it will build
        ("step_build", "m2", 1),
        ("step_review", "m1", 1),  # the planner checks each step
        ("step_build", "m2", 1),
        ("step_review", "m1", 1),
        ("review", "m1", 1),
    ]


async def test_the_person_picks_the_roles(tmp_path: Path) -> None:
    snap = await _run(_engine(FakeTurns()), tmp_path, roles=["reviewer", "planner", "builder"])

    assert [m["role"] for m in snap["members"]] == ["reviewer", "planner", "builder"]
    assert snap["builder"] == "m3"
    assert _steps(snap)[:3] == [
        ("plan_version", "m2", 1),
        ("plan_review", "m1", 1),
        ("step_build", "m3", 1),
    ]


async def test_roles_that_leave_work_unchecked_are_refused(tmp_path: Path) -> None:
    engine = _engine(FakeTurns())
    for roles in (
        ["planner", "planner", "builder"],
        ["planner", "reviewer", "reviewer"],
        ["planner", "builder"],
        ["planner", "builder", "boss"],
    ):
        with pytest.raises(TeamError):
            await engine.start(
                task="x", cwd=str(tmp_path), seats=SEATS, mode="planner_builder", roles=roles
            )
    with pytest.raises(TeamError):
        await engine.start(task="x", cwd=str(tmp_path), seats=SEATS, mode="solo")
    assert engine.threads() == []


async def test_objections_go_back_to_the_planner_until_the_plan_is_agreed(
    tmp_path: Path,
) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "plan_review" and nth == 0:
            return object_to("Step 2 has no check for the retry limit.")
        if step == "plan_version" and nth == 1:
            return plan("Add the setting", "Use it in the uploader", "Test the retry limit")
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    versions = [e for e in snap["entries"] if e["kind"] == "plan_version"]
    assert [(v["round"], v["payload"]["version"]) for v in versions] == [(1, 1), (2, 2)]
    second = turns.prompts("claude", "plan_version")[1]
    assert "Step 2 has no check for the retry limit." in second
    assert "your last proposal" in second
    assert len(snap["plan"]["steps"]) == 3
    (issue,) = snap["issues"]
    assert (issue["stage"], issue["resolved"]) == ("plan", True)


async def test_a_plan_nobody_agrees_on_waits_and_the_person_can_take_it(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "plan_review":
            return object_to("Too big.")
        return None

    turns = FakeTurns(script)
    engine = _engine(turns)
    snap = await _run(engine, tmp_path, limits={"plan_rounds": 2})

    assert (snap["state"], snap["reason"]) == ("needs_input", "plan_disagreement")
    assert snap["rounds"]["plan"] == 2
    assert snap["entries"][-1]["payload"]["open"][0]["items"] == ["Too big."]
    assert snap["plan"]["agreed"] is False

    turns.script = None
    await engine.accept(snap["team_id"])
    await engine.settled(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["state"] == "done"
    assert "plan_version_accepted_by_user" in _codes(done)
    assert all(not issue["resolved"] for issue in done["issues"])


async def test_a_plan_without_its_block_is_asked_for_once_more(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "plan_version" and nth == 0:
            return "1. Add the setting\n2. Use it"
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    retry = turns.prompts("claude", "plan_version")[1]
    assert "no plan the coordinator could read" in retry
    assert "no ```team-plan block" in retry
    unreadable, readable = [e for e in snap["entries"] if e["kind"] == "plan_version"]
    assert (unreadable["payload"]["valid"], readable["payload"]["valid"]) == (False, True)
    assert readable["payload"]["version"] == 1


async def test_a_planner_that_never_writes_a_readable_plan_stops_the_thread(
    tmp_path: Path,
) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "plan_version":
            return "I would do it like this."
        return None

    turns = FakeTurns(script)
    engine = _engine(turns)
    snap = await _run(engine, tmp_path)

    assert (snap["state"], snap["reason"]) == ("needs_input", "plan_unreadable")
    assert len(turns.prompts("claude", "plan_version")) == 2
    assert "plan_review" not in [kind for kind, _, _ in _steps(snap)]

    # Continue asks again, with two fresh tries.
    turns.script = None
    await engine.resume(snap["team_id"])
    await engine.settled(snap["team_id"])
    assert engine.snapshot(snap["team_id"])["state"] == "done"


async def test_changes_go_back_to_the_builder_on_the_same_step(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "step_review" and nth == 0:
            return changes("The setting is never read.", where="upload.py:12")
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    assert _steps(snap)[2:6] == [
        ("step_build", "m2", 1),
        ("step_review", "m3", 1),
        ("step_build", "m2", 2),
        ("step_review", "m3", 2),
    ]
    fix = turns.prompts("gpt", "step_build")[1]
    assert "build step 1 of 2" in fix
    assert "The setting is never read." in fix
    again = turns.prompts("gemini", "step_review")[1]
    assert "further round" in again
    assert snap["plan"]["steps"][0]["rounds"] == 2
    (issue,) = snap["issues"]
    assert (issue["stage"], issue["number"], issue["resolved"]) == ("step", 1, True)


async def test_a_step_the_reviewer_never_approves_waits_and_can_be_accepted(
    tmp_path: Path,
) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "step_review" and nth < 2:
            return changes("Still broken.")
        return None

    turns = FakeTurns(script)
    engine = _engine(turns)
    snap = await _run(engine, tmp_path, limits={"review_rounds": 2})

    assert (snap["state"], snap["reason"]) == ("needs_input", "step_disagreement")
    summary = snap["entries"][-1]["payload"]
    assert (summary["number"], summary["title"]) == (1, "Add the setting")
    assert snap["plan"]["steps"][0]["status"] == "in_review"

    await engine.accept(snap["team_id"])
    await engine.settled(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["state"] == "done"
    assert "step_accepted_by_user" in _codes(done)
    assert done["plan"]["steps"][0]["open_findings"] is True
    assert done["entries"][-1]["payload"]["open_steps"] == 1
    assert [i["resolved"] for i in done["issues"]] == [False, False]


async def test_an_answer_to_a_stuck_step_gives_it_one_more_round(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "step_review" and nth == 0:
            return changes("Use the existing config loader.")
        return None

    turns = FakeTurns(script)
    engine = _engine(turns)
    snap = await _run(engine, tmp_path, limits={"review_rounds": 1})
    assert snap["reason"] == "step_disagreement"

    await engine.message(snap["team_id"], "Keep the loader, add one key.")
    await engine.settled(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["state"] == "done"
    assert done["limits"]["review_rounds"] == 2
    assert "Keep the loader, add one key." in turns.prompts("gpt", "step_build")[1]


async def test_a_blocked_builder_gets_a_revised_plan_that_keeps_accepted_steps(
    tmp_path: Path,
) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "step_build" and nth == 1:
            return step_report(2, "blocked", note="The uploader has no retry hook.")
        if step == "plan_version" and nth == 1:
            return plan("Add the setting", "Add a retry hook", "Use it in the uploader")
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    assert "plan_revision" in _codes(snap)
    revise = turns.prompts("claude", "plan_version")[1]
    assert "revise the plan" in revise
    assert "The uploader has no retry hook." in revise
    assert "1. [accepted] Add the setting" in revise
    second = [e for e in snap["entries"] if e["kind"] == "plan_version"][1]
    assert (second["payload"]["version"], second["payload"]["carried"]) == (2, [1])
    # The revision is reviewed like any plan, and the accepted step is not built again.
    assert "This is a revision" in turns.prompts("gemini", "plan_review")[1]
    builds = [e["payload"] for e in snap["entries"] if e["kind"] == "step_build"]
    assert [(b["version"], b["number"]) for b in builds] == [(1, 1), (1, 2), (2, 2), (2, 3)]
    assert [s["status"] for s in snap["plan"]["steps"]] == ["accepted"] * 3
    assert snap["plan"]["version"] == 2


async def test_a_plan_change_after_a_done_step_comes_after_its_review(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "step_build" and nth == 0:
            return step_report(1, plan_change="Step 2 should also cover downloads.")
        if step == "plan_version" and nth == 1:
            return plan("Add the setting", "Use it in the uploader and the downloader")
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    order = [k for k, _, _ in _steps(snap)]
    assert order[:6] == [
        "plan_version",
        "plan_review",
        "step_build",
        "step_review",
        "plan_version",
        "plan_review",
    ]
    assert "Step 2 should also cover downloads." in turns.prompts("claude", "plan_version")[1]
    assert snap["plan"]["steps"][1]["title"] == "Use it in the uploader and the downloader"


async def test_the_planner_can_reopen_an_accepted_step(tmp_path: Path) -> None:
    workspace = FakeWorkspace()

    def script(provider: str, step: str, nth: int):
        if step == "step_build":
            workspace.touch()
        if step == "step_build" and nth == 1:
            return step_report(2, "blocked", note="Step 1 used the wrong file.")
        if step == "plan_version" and nth == 1:
            return plan("Add the setting", "Use it in the uploader", reopen=(1,))
        return None

    turns = FakeTurns(script)
    engine = _engine(turns, workspace=workspace)
    snap = await _run(engine, tmp_path)

    assert snap["state"] == "done"
    second = [e for e in snap["entries"] if e["kind"] == "plan_version"][1]
    assert second["payload"]["carried"] == []
    builds = [e["payload"] for e in snap["entries"] if e["kind"] == "step_build"]
    assert [(b["version"], b["number"]) for b in builds] == [(1, 1), (1, 2), (2, 1), (2, 2)]
    # The reopened step is reviewed against the tree it restarted from, not its first one;
    # the blocked step keeps the tree of its first try.
    bases = engine._store.get(snap["team_id"])["work"]["step_base"]  # noqa: SLF001
    assert bases == {"add the setting": "tree-2", "use it in the uploader": "tree-1"}


async def test_findings_of_the_final_review_go_back_to_the_builder(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if step == "review" and provider == "gemini" and nth == 0:
            return changes("Step 2 broke the download path.", where="download.py:4")
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path)

    assert snap["state"] == "done"
    assert _steps(snap)[-5:] == [
        ("review", "m1", 1),
        ("review", "m3", 1),
        ("fix", "m2", 1),
        ("review", "m1", 2),
        ("review", "m3", 2),
    ]
    assert "Step 2 broke the download path." in turns.prompts("gpt", "fix")[0]


async def test_a_reviewer_takes_over_when_the_planner_leaves(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if provider == "claude":
            return TurnResult("failed", error="signed out")
        return None

    snap = await _run(_engine(FakeTurns(script)), tmp_path)

    assert snap["state"] == "done"
    assert [m["state"] for m in snap["members"]] == ["left", "active", "active"]
    assert [m["role"] for m in snap["members"]] == ["planner", "builder", "planner"]
    assert "role_changed" in _codes(snap)
    # The new planner writes the plan; the builder reviews it, with no reviewer left.
    assert _steps(snap)[:2] == [("plan_version", "m3", 1), ("plan_review", "m2", 1)]


async def test_pause_and_continue_go_on_with_the_same_step(tmp_path: Path) -> None:
    turns = FakeTurns(hold={"step_review"})
    engine = _engine(turns)
    snap = await engine.start(
        task="Add a retry", cwd=str(tmp_path), seats=SEATS, mode="planner_builder"
    )
    team_id = snap["team_id"]
    await turns.reached("step_review", 1)
    working = engine.snapshot(team_id)
    assert [s["status"] for s in working["plan"]["steps"]] == ["in_review", "open"]
    assert working["plan"]["steps"][0]["holders"] == ["m3"]

    await engine.pause(team_id)
    turns.hold.clear()
    await engine.resume(team_id)
    await engine.settled(team_id)

    done = engine.snapshot(team_id)
    assert done["state"] == "done"
    # The step was built once; only its interrupted review was asked again.
    assert len(turns.prompts("gpt", "step_build")) == 2
    assert len(turns.prompts("gemini", "step_review")) == 3


async def test_the_board_sees_which_step_is_being_built(tmp_path: Path) -> None:
    turns = FakeTurns(hold={"step_build"})
    engine = _engine(turns)
    snap = await engine.start(
        task="Add a retry", cwd=str(tmp_path), seats=SEATS[:2], mode="planner_builder"
    )
    await turns.reached("step_build", 1)

    plan_view = engine.snapshot(snap["team_id"])["plan"]
    assert [(s["status"], s["holders"]) for s in plan_view["steps"]] == [
        ("building", ["m2"]),
        ("open", []),
    ]
    await engine.stop(snap["team_id"])


async def test_each_step_is_reviewed_against_its_own_change(tmp_path: Path) -> None:
    workspace = FakeWorkspace()

    def script(provider: str, step: str, nth: int):
        if step == "step_build":
            workspace.touch()
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns, workspace=workspace), tmp_path)

    builds = [e["payload"] for e in snap["entries"] if e["kind"] == "step_build"]
    assert [b["files"] for b in builds] == [["app.py"], ["app.py"]]
    assert "+new line" in turns.prompts("gemini", "step_review")[0]
    assert "change since this step started" in turns.prompts("gemini", "step_review")[0]
    assert "change since the build started" in turns.prompts("gemini", "review")[0]
    assert snap["entries"][-1]["payload"]["files"] == ["app.py"]
    assert "files_changed" not in _codes(snap)


async def test_the_peers_mode_has_no_plan_and_no_roles(tmp_path: Path) -> None:
    snap = await _run(_engine(FakeTurns()), tmp_path, mode="peers")

    assert (snap["state"], snap["mode"], snap["plan"]) == ("done", "peers", None)
    assert {m["role"] for m in snap["members"]} == {""}


def test_a_database_from_before_the_modes_reads_as_peers(tmp_path: Path) -> None:
    path = tmp_path / "team_threads.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE team_threads (team_id TEXT PRIMARY KEY, title TEXT NOT NULL, "
        "task TEXT NOT NULL, cwd TEXT NOT NULL, state TEXT NOT NULL, phase TEXT NOT NULL, "
        "reason TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', "
        "lang TEXT NOT NULL DEFAULT '', limits_json TEXT NOT NULL DEFAULT '{}', "
        "work_json TEXT NOT NULL DEFAULT '{}', created_ms INTEGER NOT NULL, "
        "updated_ms INTEGER NOT NULL);"
        "INSERT INTO team_threads (team_id, title, task, cwd, state, phase, created_ms, "
        "updated_ms) VALUES ('old', 't', 'task', '.', 'done', 'done', 1, 1);"
    )
    conn.commit()
    conn.close()

    store = TeamThreadStore(path)
    assert store.get("old")["mode"] == "peers"  # type: ignore[index]
    store.close()


def test_a_plan_is_read_only_out_of_its_typed_block() -> None:
    good = parse_plan(plan("One", "Two") + "\n")
    assert good.valid
    assert [s.title for s in good.steps] == ["One", "Two"]
    assert good.steps[0].done_when == "One works"
    assert good.text == "Here is the plan."

    assert parse_plan("1. One\n2. Two").valid is False
    broken = parse_plan('```team-plan\n{"steps": [{"title": "One",}]}\n```')
    assert broken.valid is False
    assert broken.error.startswith("The team-plan block is not valid JSON")
    no_check = parse_plan('```team-plan\n{"steps": [{"title": "One", "goal": "x"}]}\n```')
    assert (no_check.valid, no_check.error) == (False, 'Step 1 has no "done_when".')
    assert parse_plan('```team-plan\n{"steps": []}\n```').valid is False
    bare = parse_plan('```team-plan\n[{"title": "One", "done_when": "it runs"}]\n```')
    assert bare.valid and bare.steps[0].goal == ""
    reopen = parse_plan(
        '```team-plan\n{"steps": [{"title": "A", "done_when": "b"}], "reopen": [2, "x", 2]}\n```'
    )
    assert reopen.reopen == (2,)


def test_a_step_report_is_conservative() -> None:
    assert parse_step(step_report(1)).status == "done"
    blocked = parse_step(step_report(2, "blocked", note="no hook", plan_change="add one"))
    assert (blocked.status, blocked.note, blocked.plan_change) == ("blocked", "no hook", "add one")
    # Without a block the step is still reviewed against its check.
    assert (parse_step("Done.").status, parse_step("Done.").stated) == ("done", False)
    # A broken block can still say "blocked".
    loose = parse_step('```team-step\n{"status": "blocked", }\n```')
    assert (loose.status, loose.stated) == ("blocked", False)
