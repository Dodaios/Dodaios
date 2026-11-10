"""The chat and the trust layer: standing rules outlive the chat, hard limits
keep asking, and a reversible action posts an undo notice."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.trust.rules import trust_rules
from dodaios.trust.undo import undo_ledger


async def _next(q: asyncio.Queue, kind: str, budget_s: float = 5.0) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while True:
        ev = await asyncio.wait_for(q.get(), timeout=max(0.01, deadline - loop.time()))
        if ev["kind"] == kind:
            return ev


def _service(tmp_path: Path):
    svc = AgentChatService(AgentChatStore(":memory:"))
    session = svc.store.create_session(
        provider="claude-api",
        model="m",
        effort="medium",
        cwd=str(tmp_path),
        permission_mode="ask",
        surface="jarvis",
    )
    return svc, session


def test_a_chat_always_becomes_a_standing_rule_the_next_chat_honours(tmp_path: Path):
    async def scenario() -> None:
        svc, session = _service(tmp_path)
        q = svc.subscribe(session.session_id)
        asking = asyncio.create_task(
            svc._ask(session.session_id, "t1", "c1", "Bash", {"command": "npm test"}, "npm test")  # noqa: SLF001
        )
        card = (await _next(q, "approval_required"))["payload"]
        assert "hard_limit" not in card
        svc.resolve_approval(
            session.session_id, card["approval_id"], "allow_always", scope="chat", narrow="command"
        )
        assert await asking == "allow"
        notice = (await _next(q, "notice"))["payload"]
        assert notice["kind"] == "approval_rule" and notice["narrow"] == "command"
        rules = trust_rules().items()
        assert [(r["tool"], r["kind"], r["target"]) for r in rules] == [
            ("Bash", "command", "npm test")
        ]
        assert notice["rule_id"] == rules[0]["id"]

        # Another chat (a restart, say) runs the same command without a card…
        other, fresh = _service(tmp_path)
        assert (
            await other._ask(fresh.session_id, "t1", "c1", "Bash", {"command": "npm  test"}, "")  # noqa: SLF001
            == "allow"
        )
        # …until the rule is revoked on the Trust page.
        trust_rules().revoke(rules[0]["id"])
        svc.forget_standing_rule(rules[0])
        pending = asyncio.create_task(
            other._ask(fresh.session_id, "t1", "c2", "Bash", {"command": "npm test"}, "")  # noqa: SLF001
        )
        q2 = other.subscribe(fresh.session_id)
        await asyncio.sleep(0.05)
        assert other.pending_approvals(fresh.session_id), "the card is back"
        pending.cancel()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        q2.put_nowait({"kind": "done"})

    asyncio.run(scenario())


def test_a_hard_limit_keeps_asking_and_saves_no_rule(tmp_path: Path):
    async def scenario() -> None:
        svc, session = _service(tmp_path)
        q = svc.subscribe(session.session_id)
        trust_rules().add(tool="Bash", kind="tool", label="Bash")
        asking = asyncio.create_task(
            svc._ask(
                session.session_id, "t1", "c1", "Bash", {"command": "rm -rf dist"}, "rm -rf dist"
            )  # noqa: SLF001
        )
        card = (await _next(q, "approval_required"))["payload"]
        assert card["hard_limit"] == "permanent_delete", (
            "the tool rule does not cover deleting for good"
        )
        svc.resolve_approval(session.session_id, card["approval_id"], "allow_always", scope="chat")
        # An "always" for a hard limit runs this once and remembers nothing.
        assert await asking == "allow"
        await asyncio.sleep(0.05)
        assert [r["kind"] for r in trust_rules().items()] == ["tool"], "no second rule was saved"
        assert "Bash" not in svc.always_allowed(session.session_id)

    asyncio.run(scenario())


def test_the_card_names_an_outbound_finding(tmp_path: Path):
    async def scenario() -> None:
        svc, session = _service(tmp_path)
        q = svc.subscribe(session.session_id)
        args = {"action": "send_message", "to": "bob@gmial.com", "body": "hi"}
        asking = asyncio.create_task(
            svc._ask(session.session_id, "t1", "c1", "gmail", args, "Send")  # noqa: SLF001
        )
        card = (await _next(q, "approval_required"))["payload"]
        assert card["hard_limit"] == "new_recipient"
        assert {c["code"] for c in card["checks"]} == {"unknown_recipient", "mistyped_domain"}
        svc.resolve_approval(session.session_id, card["approval_id"], "deny")
        assert await asking == "deny"

    asyncio.run(scenario())


def test_a_recorded_undo_reaches_the_chat_as_a_notice(tmp_path: Path):
    async def scenario() -> None:
        svc, session = _service(tmp_path)
        q = svc.subscribe(session.session_id)
        entry = undo_ledger().record(
            "gmail",
            {"action": "modify_message", "message_id": "m1", "remove_labels": ["INBOX"]},
            {"id": "m1"},
            {"approval_ref": f"agent-chat:{session.session_id}"},
        )
        notice = (await _next(q, "notice"))["payload"]
        assert notice["kind"] == "undo_available"
        assert notice["undo_id"] == entry["id"] and notice["text"] == "Archived a mail"
        # Another session's action is not this chat's business.
        undo_ledger().record(
            "gmail",
            {"action": "modify_message", "message_id": "m2", "remove_labels": ["INBOX"]},
            {"id": "m2"},
            {"approval_ref": "agent-chat:somebody-else"},
        )
        await asyncio.sleep(0.05)
        assert q.empty()

    asyncio.run(scenario())
