"""A person's review of a plan reaches the agent (dodaios/agent_chat/plan_review.py).

The plan card opens a review window where the person edits the plan and
comments on passages. These tests pin what the agent then reads: the edited
plan as the approved tool input (Claude Code), the comments as the reason of a
declined plan, and both as the next message for every other coding CLI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import plan_review, turn_prompts
from dodaios.agent_chat.approval_preview import EditRejected, apply_edits, editable_keys
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.plan_review import PlanComment, PlanReview, review_from
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import router as chat_router
from tests.unit.agent_chat.test_turn_prompts import _can_use, _claude_turn

PLAN = "# Plan\n\n1. Add the table\n2. Wire the route"
EDITED = "# Plan\n\n1. Add the table\n2. Wire the route\n3. Write the test"

# ------------------------------------------------------------------ the texts


def test_a_review_that_says_nothing_changes_nothing() -> None:
    assert plan_review.is_empty(PLAN, None)
    assert plan_review.is_empty(PLAN, PlanReview())
    # The same text with other line ends is no edit.
    same = PlanReview(plan=PLAN.replace("\n", "\r\n") + "\n\n")
    assert plan_review.is_empty(PLAN, same)
    assert plan_review.approved_plan(PLAN, same) is PLAN
    assert plan_review.changes_wanted(PLAN, same) == ""
    assert plan_review.go_ahead(PLAN, same, "Go.") == "Go."
    assert plan_review.shown(PLAN, same, "Go.") == "Go."


def test_an_approved_plan_is_the_person_s_version_with_their_notes() -> None:
    review = PlanReview(
        plan=EDITED,
        comments=(PlanComment("Wire the route", "Use the existing router.\nNo new file."),),
        note="Keep it small.",
    )
    approved = plan_review.approved_plan(PLAN, review)
    assert approved.startswith(EDITED)
    assert plan_review.NOTES_HEADING in approved
    assert '1. On "Wire the route": Use the existing router.\n   No new file.' in approved
    assert "2. On the whole plan: Keep it small." in approved
    # Edited only: the person's text and nothing else.
    assert plan_review.approved_plan(PLAN, PlanReview(plan=EDITED)) == EDITED
    # Comments only: the agent's own plan, with the notes after it.
    noted = plan_review.approved_plan(PLAN, PlanReview(note="Keep it small."))
    assert noted.startswith(PLAN) and noted.endswith("1. On the whole plan: Keep it small.")


def test_a_plan_sent_back_tells_the_agent_what_to_change() -> None:
    review = PlanReview(comments=(PlanComment("Add the table", "Which table?"),))
    told = plan_review.changes_wanted(PLAN, review)
    assert "did not approve it yet" in told and "Do not build anything" in told
    assert '1. On "Add the table": Which table?' in told
    assert "<plan>" not in told
    assert told.endswith("then present it again.")
    edited = plan_review.changes_wanted(PLAN, PlanReview(plan=EDITED))
    assert f"<plan>\n{EDITED}\n</plan>" in edited
    assert "Go on planning from their version" in edited


def test_a_review_from_a_request_is_cleaned_and_bounded() -> None:
    review = review_from(
        plan=None,
        comments=[
            {"quote": "  a\n  long   passage ", "text": "  fix this  "},
            {"quote": "dropped", "text": "   "},
            PlanComment("x" * 1000, "too long a quote"),
        ],
        note="  whole  ",
    )
    assert review.comments[0] == PlanComment("a long passage", "fix this")
    assert len(review.comments) == 2
    assert len(review.comments[1].quote) == plan_review.QUOTE_CHARS
    assert review.comments[1].quote.endswith("…")
    assert review.note == "whole"
    with pytest.raises(ValueError):
        review_from(plan="x" * (plan_review.PLAN_CHARS + 1))
    with pytest.raises(ValueError):
        review_from(plan="   ")
    with pytest.raises(ValueError):
        review_from(plan=7)
    with pytest.raises(ValueError):
        review_from(comments=[{"text": "c"}] * (plan_review.MAX_COMMENTS + 1))


def test_only_a_plan_s_text_can_be_edited_on_its_card() -> None:
    assert editable_keys("ExitPlanMode", {"plan": PLAN}) == {"plan": "plan"}
    # A CLI that keeps the plan in its own file hands no text to edit.
    assert editable_keys("ExitPlanMode", {}) == {}
    new_args, changed = apply_edits("ExitPlanMode", {"plan": PLAN}, {"plan": EDITED})
    assert new_args == {"plan": EDITED}
    assert changed["plan"]["after"] == EDITED
    with pytest.raises(EditRejected):
        apply_edits("ExitPlanMode", {"plan": PLAN}, {"allowedPrompts": "x"})


# ------------------------------------------------------------------ Claude Code's own card


def _events(svc: AgentChatService, sid: str, kind: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in svc.store.list_events(sid) if e["kind"] == kind]


async def _open_plan_card(
    tmp_path: Path, name: str = "ExitPlanMode", args: dict[str, Any] | None = None
) -> tuple[AgentChatService, str, dict[str, Any], asyncio.Task[str], str]:
    svc = AgentChatService(AgentChatStore(":memory:"))
    sid = svc.create_session(
        provider="claude-api", cwd=str(tmp_path), permission_mode="plan", surface="agent"
    ).session_id
    call = {"plan": PLAN} if args is None else args
    await svc._emit(sid, make_event("turn_started", {"turn_id": "t1"}))
    asking = asyncio.create_task(svc._ask(sid, "t1", "c1", name, call, "Plan ready"))
    for _ in range(200):
        cards = _events(svc, sid, "approval_required")
        if cards:
            return svc, sid, call, asking, cards[0]["approval_id"]
        await asyncio.sleep(0.01)
    raise AssertionError("the approval card never opened")


def test_build_hands_claude_the_plan_the_person_left(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, call, asking, approval_id = await _open_plan_card(tmp_path)
        review = PlanReview(plan=EDITED, comments=(PlanComment("the table", "users only"),))
        assert svc.resolve_approval(sid, approval_id, "allow", review=review)
        assert await asking == "allow"
        # The very dict the runner sends back as ``updatedInput`` carries it.
        assert call["plan"].startswith(EDITED)
        assert '1. On "the table": users only' in call["plan"]
        (resolved,) = _events(svc, sid, "approval_resolved")
        assert resolved["decision"] == "allow"
        assert resolved["plan"] == call["plan"]
        assert "plan" in resolved["edited"]

    asyncio.run(scenario())


def test_build_without_a_change_sends_the_plan_as_written(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, call, asking, approval_id = await _open_plan_card(tmp_path)
        assert svc.resolve_approval(sid, approval_id, "allow", review=PlanReview(plan=PLAN))
        assert await asking == "allow"
        assert call == {"plan": PLAN}
        (resolved,) = _events(svc, sid, "approval_resolved")
        assert "plan" not in resolved and "edited" not in resolved

    asyncio.run(scenario())


def test_keep_planning_tells_claude_the_comments(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, call, asking, approval_id = await _open_plan_card(tmp_path)
        review = PlanReview(plan=EDITED, comments=(PlanComment("Wire the route", "which one?"),))
        assert svc.resolve_approval(
            sid, approval_id, "deny", feedback="Smaller steps.", review=review
        )
        assert await asking == "deny"
        assert call == {"plan": PLAN}
        told = svc.take_deny_feedback(sid, "c1")
        assert '1. On "Wire the route": which one?' in told
        # What was typed in the card's own field is the note on the whole plan.
        assert "2. On the whole plan: Smaller steps." in told
        assert f"<plan>\n{EDITED}\n</plan>" in told

    asyncio.run(scenario())


def test_a_long_review_is_not_cut_at_the_short_reason_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, _, asking, approval_id = await _open_plan_card(tmp_path)
        long_plan = "# Plan\n\n" + "\n".join(f"{n}. Step {n} of the work" for n in range(400))
        assert len(long_plan) > 2000
        assert svc.resolve_approval(sid, approval_id, "deny", review=PlanReview(plan=long_plan))
        assert await asking == "deny"
        assert svc.take_deny_feedback(sid, "c1").count("of the work") == 400

    asyncio.run(scenario())


def test_a_review_on_anything_but_a_plan_is_refused(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, _, asking, approval_id = await _open_plan_card(
            tmp_path, "Bash", {"command": "ls"}
        )
        with pytest.raises(ValueError):
            svc.resolve_approval(sid, approval_id, "allow", review=PlanReview(note="x"))
        # The card is still open and takes a plain answer.
        assert svc.resolve_approval(sid, approval_id, "deny")
        assert await asking == "deny"

    asyncio.run(scenario())


def test_the_cli_is_answered_with_the_edited_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The runner answers with the arguments as the card left them."""
    from dodaios.agent_chat.runner_api import TurnHandle

    real = TurnHandle

    def edited_handle(**kwargs: Any) -> TurnHandle:
        async def ask(call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
            args["plan"] = EDITED
            return "allow"

        return real(**{**kwargs, "request_approval": ask})

    monkeypatch.setattr("tests.unit.agent_chat.test_turn_prompts.TurnHandle", edited_handle)
    answers, _, _ = _claude_turn(
        monkeypatch, tmp_path, [_can_use("ExitPlanMode", {"plan": PLAN})], mode="plan"
    )
    (body,) = answers
    assert body["behavior"] == "allow"
    assert body["updatedInput"] == {"plan": EDITED}


# ------------------------------------------------------------------ every other CLI's card


async def _plan_card(tmp_path: Path) -> tuple[AgentChatService, str, list[tuple[str, Any]]]:
    svc = AgentChatService(AgentChatStore(":memory:"))
    sid = svc.create_session(
        provider="openai-codex", cwd=str(tmp_path), permission_mode="plan", surface="agent"
    ).session_id
    sent: list[tuple[str, Any]] = []

    async def send(session_id: str, text: str, *_: Any, **kwargs: Any) -> str:
        sent.append((text, kwargs.get("display_text")))
        return "next-turn"

    svc.send = send  # type: ignore[method-assign]
    await svc._emit(sid, make_event("turn_started", {"turn_id": "t1"}))
    await svc._emit(sid, make_event("assistant_text", {"turn_id": "t1", "text": PLAN}))
    await svc._emit(sid, make_event("turn_finished", {"turn_id": "t1", "status": "done"}))
    await svc._open_turn_prompts(sid, "t1", "codex-cli")
    assert _events(svc, sid, "plan_ready")
    return svc, sid, sent


def test_build_sends_the_edited_plan_with_the_go_ahead(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, sent = await _plan_card(tmp_path)
        review = PlanReview(plan=EDITED, comments=(PlanComment("the table", "users only"),))
        assert await svc.resolve_turn_plan(sid, "t1", "build", review=review)
        ((text, display),) = sent
        assert text.startswith(turn_prompts.PLAN_GO_AHEAD)
        assert f"<plan>\n{EDITED}\n</plan>" in text
        assert '1. On "the table": users only' in text
        # The person's bubble shows their own words, not the whole plan again.
        assert display.startswith(turn_prompts.PLAN_GO_AHEAD)
        assert "users only" in display and EDITED not in display
        assert svc.store.get_session(sid).permission_mode != "plan"

    asyncio.run(scenario())


def test_keep_planning_with_comments_sends_them_and_stays_in_plan(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, sent = await _plan_card(tmp_path)
        review = PlanReview(comments=(PlanComment("Add the table", "Which table?"),))
        assert await svc.resolve_turn_plan(sid, "t1", "keep", review=review)
        ((text, display),) = sent
        assert '1. On "Add the table": Which table?' in text
        assert display.startswith(turn_prompts.PLAN_KEEP_SHOWN)
        assert svc.store.get_session(sid).permission_mode == "plan"
        assert _events(svc, sid, "plan_resolved") == [{"turn_id": "t1", "decision": "keep"}]
        assert _events(svc, sid, "session_updated") == []

    asyncio.run(scenario())


def test_keep_planning_with_an_empty_review_only_closes_the_card(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, sent = await _plan_card(tmp_path)
        assert await svc.resolve_turn_plan(sid, "t1", "keep", review=PlanReview(plan=PLAN))
        assert sent == []

    asyncio.run(scenario())


# ------------------------------------------------------------------ the routes


def test_the_plan_route_takes_a_review(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(chat_router)

    async def prepared() -> tuple[AgentChatService, str, list[tuple[str, Any]]]:
        return await _plan_card(tmp_path)

    svc, sid, sent = asyncio.run(prepared())
    app.state.agent_chat = svc
    with TestClient(app) as client:
        bad = client.post(
            f"/api/agent-chat/sessions/{sid}/plan",
            json={"turn_id": "t1", "decision": "keep", "review": {"plan": "  "}},
        )
        assert bad.status_code == 400, bad.text
        answered = client.post(
            f"/api/agent-chat/sessions/{sid}/plan",
            json={
                "turn_id": "t1",
                "decision": "keep",
                "review": {
                    "comments": [{"quote": "Add the table", "text": "Which table?"}],
                    "note": "Smaller.",
                },
            },
        )
        assert answered.status_code == 200, answered.text
    ((text, _),) = sent
    assert '1. On "Add the table": Which table?' in text
    assert "2. On the whole plan: Smaller." in text
