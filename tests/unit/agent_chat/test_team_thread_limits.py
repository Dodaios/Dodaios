"""A member out of credit stays in the team, and a member that left can come back (#1881).

The report: whenever a member's seat ran into a spending limit or needed API
credit, it was asked again at once, then dropped from the team for good, and
it could not be brought back after the top-up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.agent_chat.team import SeatPick, TeamError, TeamThreads, TeamThreadStore
from dodaios.agent_chat.team.engine import BACK_REASON, LIMIT_REASON, hit_a_limit
from dodaios.agent_chat.team.port import TurnResult
from dodaios.agent_chat.turn_errors import provider_down_reason
from tests.fakes.fake_team_turns import FakeTurns, FakeWorkspace

SEATS = [
    SeatPick("claude", name="Claude", family="claude"),
    SeatPick("gpt", name="GPT", family="openai"),
    SeatPick("gemini", name="Gemini", family="gemini"),
]

#: What the Anthropic API answers a key whose credit is spent.
NO_CREDIT = (
    "Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits."
)


def _engine(turns: FakeTurns, store: TeamThreadStore | None = None) -> TeamThreads:
    return TeamThreads(store or TeamThreadStore(":memory:"), turns, workspace=FakeWorkspace())


async def _run(engine: TeamThreads, tmp_path: Path, seats=SEATS) -> dict:
    snap = await engine.start(task="Add a retry to the uploader", cwd=str(tmp_path), seats=seats)
    await engine.settled(snap["team_id"])
    return engine.snapshot(snap["team_id"])


def _member(snap: dict, member_id: str) -> dict:
    return next(m for m in snap["members"] if m["member_id"] == member_id)


def _codes(snap: dict) -> list[str]:
    return [e["payload"]["code"] for e in snap["entries"] if e["kind"] == "notice"]


@pytest.mark.parametrize(
    ("error", "limited"),
    [
        (NO_CREDIT, True),
        ("Credit balance is too low", True),
        (
            'API Error: 400 {"type":"error","error":{"type":"invalid_request_error",'
            '"message":"Your credit balance is too low to access the Anthropic API."}}',
            True,
        ),
        ("You have reached your specified API usage limits.", True),
        ("Monthly spending limit reached for this workspace", True),
        ("Error code: 402 - Payment Required", True),
        ("insufficient_quota", True),
        (provider_down_reason("account_blocked"), True),
        ("overloaded", False),
        ("connection reset", False),
        ("not signed in", False),
        ("The model is not supported with this account.", False),
        ("", False),
    ],
)
def test_what_counts_as_a_spent_credit_or_limit(error: str, limited: bool) -> None:
    assert hit_a_limit(error) is limited


async def test_a_member_out_of_credit_stays_and_the_team_waits_for_the_top_up(
    tmp_path: Path,
) -> None:
    topped_up = False

    def script(provider: str, step: str, nth: int):
        if provider == "gemini" and step == "draft" and not topped_up:
            return TurnResult("failed", error=NO_CREDIT)
        return None

    turns = FakeTurns(script)
    engine = _engine(turns)
    snap = await _run(engine, tmp_path)

    assert (snap["state"], snap["reason"]) == ("needs_input", LIMIT_REASON)
    assert snap["note"] == f"Gemini: {NO_CREDIT}"
    # Still in the team, with its own thread.
    gemini = _member(snap, "m3")
    assert (gemini["state"], gemini["left_reason"]) == ("active", "")
    assert "member_left" not in _codes(snap)
    assert LIMIT_REASON in _codes(snap)
    # Asked once: an at-once second try only repeats the refusal.
    assert len(turns.prompts("gemini", "draft")) == 1

    topped_up = True
    await engine.resume(snap["team_id"])
    await engine.settled(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["state"] == "done"
    # The same member, in the same thread, goes on; the others' plans were kept.
    assert len(turns.prompts("gemini", "draft")) == 2
    assert len(turns.prompts("claude", "draft")) == 1
    assert len(turns.prompts("gpt", "draft")) == 1
    assert {a.provider for a in turns.asked if a.step == "critique"} == {"claude", "gpt", "gemini"}
    assert list(turns.sessions.values()) == ["claude", "gpt", "gemini"]  # no new member thread


async def test_saying_it_is_topped_up_continues_the_team(tmp_path: Path) -> None:
    topped_up = False

    def script(provider: str, step: str, nth: int):
        if provider == "claude" and step == "critique" and not topped_up:
            return TurnResult("failed", error="Monthly spending limit reached")
        return None

    turns = FakeTurns(script)
    engine = _engine(turns)
    snap = await _run(engine, tmp_path)
    assert snap["reason"] == LIMIT_REASON

    topped_up = True
    await engine.message(snap["team_id"], "Topped up, go on.")
    await engine.settled(snap["team_id"])
    assert engine.snapshot(snap["team_id"])["state"] == "done"


async def test_a_reviewer_out_of_credit_keeps_its_seat_in_the_review(tmp_path: Path) -> None:
    topped_up = False

    def script(provider: str, step: str, nth: int):
        if provider == "gemini" and step == "review" and not topped_up:
            return TurnResult("failed", error="Error code: 402 - Payment Required")
        return None

    turns = FakeTurns(script)
    engine = _engine(turns)
    snap = await _run(engine, tmp_path)
    assert (snap["state"], snap["reason"]) == ("needs_input", LIMIT_REASON)

    topped_up = True
    await engine.resume(snap["team_id"])
    await engine.settled(snap["team_id"])
    done = engine.snapshot(snap["team_id"])
    assert done["state"] == "done"
    assert {e["author"] for e in done["entries"] if e["kind"] == "review"} == {"m2", "m3"}


async def test_a_member_that_left_comes_back_and_takes_part_again(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        if provider == "gemini" and step == "draft":
            return TurnResult("failed", error="not signed in")
        return None

    turns = FakeTurns(script, hold={"critique"})
    engine = _engine(turns)
    snap = await engine.start(task="Add a retry", cwd=str(tmp_path), seats=SEATS)
    await turns.reached("critique", 2)
    team_id = snap["team_id"]
    assert _member(engine.snapshot(team_id), "m3")["state"] == "left"

    back = await engine.rejoin(team_id, "m3")
    assert _member(back, "m3")["state"] == "active"
    assert _member(back, "m3")["left_reason"] == ""
    assert "member_rejoined" in _codes(back)

    turns.script = None
    turns.hold.clear()
    turns.release.set()
    await engine.settled(team_id)
    done = engine.snapshot(team_id)
    assert done["state"] == "done"
    # Back in the steps that came after: it reviews with the other reviewer.
    assert "m3" in {e["author"] for e in done["entries"] if e["kind"] == "review"}


async def test_a_team_that_ended_short_of_members_waits_again_once_one_is_back(
    tmp_path: Path,
) -> None:
    store = TeamThreadStore(":memory:")
    turns = FakeTurns(hold={"draft"})
    engine = _engine(turns, store)
    snap = await engine.start(task="Add a retry", cwd=str(tmp_path), seats=SEATS[:2])
    team_id = snap["team_id"]
    await turns.reached("draft", 2)
    await engine.pause(team_id)
    # How a team ends when its builder is gone and one member is left.
    store.member_left(team_id, "m2", "not signed in")
    store.update(team_id, state="failed", reason="not_enough_members", note="")
    with pytest.raises(TeamError):
        await engine.resume(team_id)

    back = await engine.rejoin(team_id, "m2")
    assert (back["state"], back["reason"], back["note"]) == ("needs_input", BACK_REASON, "GPT")

    turns.hold.clear()
    turns.release.set()
    await engine.resume(team_id)
    await engine.settled(team_id)
    assert engine.snapshot(team_id)["state"] == "done"


async def test_what_cannot_be_brought_back(tmp_path: Path) -> None:
    engine = _engine(FakeTurns())
    snap = await _run(engine, tmp_path)
    assert snap["state"] == "done"
    with pytest.raises(KeyError):
        await engine.rejoin(snap["team_id"], "m9")
    with pytest.raises(TeamError, match="still in the team"):
        await engine.rejoin(snap["team_id"], "m1")
    engine._store.member_left(snap["team_id"], "m3", "not signed in")
    with pytest.raises(TeamError, match="over"):
        await engine.rejoin(snap["team_id"], "m3")
