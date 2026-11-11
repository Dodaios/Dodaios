"""The exact action on an approval card: preview, inline edits, set-aside cards.

Real bus, executor, workflow, bridge and chat service; no mocks of the code
under test (D8).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat.approval_bridge import ChatApprovalBridge, ChatGrant, approval_ref
from dodaios.agent_chat.approval_card import describe_call
from dodaios.agent_chat.approval_preview import (
    EditRejected,
    apply_edits,
    build_preview,
    compact_line,
    editable_keys,
)
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.tool_executor import ToolExecutor
from dodaios.trust.recipients import known_recipients

MAIL = {
    "action": "send_message",
    "to": "ada@known.example, new@stranger.example",
    "cc": "boss@known.example",
    "subject": "Quarterly numbers",
    "body": "Hi Ada,\nthe numbers are attached.",
    "attachments": ["C:/reports/q3.xlsx"],
}


def _known(value: str) -> bool:
    return value.endswith("@known.example")


def _fields(preview: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["key"]: f for f in preview["fields"]}


# ------------------------------------------------------------------ preview


def test_a_mail_shows_every_field_and_flags_only_the_new_recipient() -> None:
    preview = build_preview("mcp__dodaios__gmail", MAIL, recipients_known=_known)
    assert preview is not None and preview["class"] == "mail"
    fields = _fields(preview)
    assert [(i["text"], i["new"]) for i in fields["to"]["items"]] == [
        ("ada@known.example", False),
        ("new@stranger.example", True),
    ]
    assert fields["cc"]["items"][0]["new"] is False
    assert fields["subject"]["value"] == "Quarterly numbers"
    assert fields["body"]["value"].startswith("Hi Ada")
    assert [i["text"] for i in fields["attachments"]["items"]] == ["q3.xlsx"]
    assert preview["irreversible"] is True
    assert {k for k, f in fields.items() if f["editable"]} == {"subject", "body"}


def test_a_calendar_invite_shows_attendees_and_time() -> None:
    args = {
        "action": "create_event",
        "summary": "Planning",
        "start": "2026-11-12T10:00:00+01:00",
        "end": "2026-11-12T11:00:00+01:00",
        "attendees": ["a@known.example", "x@stranger.example"],
    }
    preview = build_preview("google_calendar", args, recipients_known=_known)
    assert preview is not None and preview["class"] == "calendar"
    fields = _fields(preview)
    assert fields["title"]["arg"] == "summary"
    assert [i["new"] for i in fields["attendees"]["items"]] == [False, True]
    assert {k for k, f in fields.items() if f["editable"]} == {"title", "start", "end"}
    assert "Planning" in preview["compact"]
    assert "x@stranger.example (new)" in preview["compact"]


def test_an_overwrite_shows_a_diff_and_a_new_file_is_a_create(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    over = build_preview(
        "Write", {"file_path": "notes.txt", "content": "one\n2\nthree\n"}, str(tmp_path)
    )
    assert over is not None and over["class"] == "file_write"
    diff = over["diff"]
    assert (diff["added"], diff["removed"], diff["creates"]) == (1, 1, False)
    assert {"op": "-", "text": "two"} in diff["lines"]
    assert {"op": "+", "text": "2"} in diff["lines"]
    assert over["irreversible"] is True

    fresh = build_preview("Write", {"file_path": "new.txt", "content": "x\n"}, str(tmp_path))
    assert fresh is not None and fresh["diff"]["creates"] is True
    assert fresh["irreversible"] is False


def test_a_delete_and_a_shell_command_are_marked_and_show_where(tmp_path: Path) -> None:
    (tmp_path / "gone.txt").write_text("abc", encoding="utf-8")
    deleted = build_preview("delete_file", {"path": "gone.txt"}, str(tmp_path))
    assert deleted is not None and deleted["class"] == "file_delete" and deleted["irreversible"]
    assert _fields(deleted)["path"]["value"] == "gone.txt"

    shell = build_preview(
        "Bash", {"command": "rm -rf build", "cwd": str(tmp_path / "app")}, str(tmp_path)
    )
    assert shell is not None and shell["class"] == "shell" and shell["irreversible"]
    assert _fields(shell)["command"]["value"] == "rm -rf build"
    assert "folder" in _fields(shell)
    safe = build_preview("Bash", {"command": "echo hi"}, str(tmp_path))
    assert safe is not None and safe["irreversible"] is False


def test_a_payment_lists_amount_and_payee_and_never_a_secret() -> None:
    preview = build_preview(
        "stripe",
        {
            "action": "charge",
            "amount": "49.00",
            "currency": "EUR",
            "payee": "Acme",
            "api_key": "not-shown",
        },
    )
    assert preview is not None and preview["class"] == "payment" and preview["irreversible"]
    assert "api_key" not in _fields(preview)
    assert "49.00" in preview["compact"] and "Acme" in preview["compact"]


def test_the_card_payload_carries_the_preview() -> None:
    fields = describe_call("gmail", dict(MAIL), "mail")
    assert fields["preview"]["class"] == "mail"
    assert describe_call("Read", {"file_path": "a.txt"}, "a.txt").get("preview") is None


def test_the_phone_line_is_compact_and_localised() -> None:
    preview = build_preview("gmail", MAIL, recipients_known=_known)
    assert preview is not None
    en, de = compact_line(preview, "en"), compact_line(preview, "de")
    assert en.startswith("To: ada@known.example, new@stranger.example (new)")
    assert "Subject: Quarterly numbers" in en and "1 attachments" in en
    assert de.startswith("An: ") and "Betreff: " in de and "nicht rückgängig" in de  # i18n-allow
    assert len(en) < 400


# ------------------------------------------------------------------- edits


def test_only_text_fields_can_be_edited_and_recipients_never() -> None:
    assert editable_keys("gmail", MAIL) == {"subject": "subject", "body": "body"}
    new, changed = apply_edits("gmail", MAIL, {"subject": "Q3 numbers"})
    assert new["subject"] == "Q3 numbers" and new["to"] == MAIL["to"]
    assert changed == {"subject": {"before": "Quarterly numbers", "after": "Q3 numbers"}}
    with pytest.raises(EditRejected):
        apply_edits("gmail", MAIL, {"to": "evil@stranger.example"})
    with pytest.raises(EditRejected):
        apply_edits("Bash", {"command": "ls"}, {"command": "rm -rf /"})
    # An unchanged edit is not a change.
    assert apply_edits("gmail", MAIL, {"subject": MAIL["subject"]})[1] == {}


def test_an_event_time_edit_must_be_a_real_time() -> None:
    args = {
        "action": "update_event",
        "summary": "x",
        "start": "2026-11-12T10:00:00Z",
        "end": "2026-11-12T11:00:00Z",
    }
    new, _ = apply_edits("google_calendar", args, {"start": "2026-11-12T09:30:00Z"})
    assert new["start"] == "2026-11-12T09:30:00Z"
    with pytest.raises(EditRejected):
        apply_edits("google_calendar", args, {"start": "tomorrow-ish"})


class _Mail:
    name = "gmail"
    risk_tier = "ask"
    description = "mail"
    schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        self.calls.append(dict(args))
        return ToolResult(success=True, output={"sent": True})


def _stack(ask: Any) -> ToolExecutor:
    bus = EventBus()
    executor = ToolExecutor(
        bus,
        RiskTierEvaluator(SafetyConfig()),
        ApprovalWorkflow(bus, timeout_s=5.0),
        default_timeout_s=5.0,
    )
    bridge = ChatApprovalBridge(bus)
    bridge.arm(
        approval_ref("s1"),
        ChatGrant(session_id="s1", turn_id="t1", stance="ask", always_allowed=set(), ask=ask),
    )
    executor._test_bridge = bridge  # noqa: SLF001 - keeps the subscriber alive
    return executor


_SNAPSHOT = {
    "approval_surface": "interactive",
    "approval_ref": approval_ref("s1"),
    "approval_timeout_s": 5.0,
}
_SEND = {"action": "send_message", "to": "ada@known.example", "subject": "Q3", "body": "old"}


async def test_the_edited_version_is_what_executes_and_the_turn_is_told() -> None:
    async def ask(call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        args["body"] = "Hi Ada, the corrected numbers."  # the service amends in place
        return "allow"

    executor = _stack(ask)
    tool = _Mail()
    known_recipients().remember(["ada@known.example"])
    result = await executor.execute(tool, dict(_SEND), config_snapshot=_SNAPSHOT)
    assert result.success, result.error
    assert tool.calls[0]["body"] == "Hi Ada, the corrected numbers."
    assert "edited this action" in result.output["approval_edits"]
    assert "old" in result.output["approval_edits"]


async def test_an_edit_that_trips_the_outbound_check_never_runs() -> None:
    async def ask(call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        args["body"] = "the key is sk-" + "a1" * 20
        return "allow"

    executor = _stack(ask)
    tool = _Mail()
    known_recipients().remember(["ada@known.example"])
    result = await executor.execute(tool, dict(_SEND), config_snapshot=_SNAPSHOT)
    assert result.success is False and tool.calls == []


# ---------------------------------------------------------------- the service


async def _next(q: asyncio.Queue, kind: str) -> dict[str, Any]:
    while True:
        ev = await asyncio.wait_for(q.get(), timeout=5)
        if ev["kind"] == kind:
            return ev


def _service(tmp_path: Path) -> tuple[AgentChatService, Any]:
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


async def test_the_service_applies_an_inline_edit_and_reports_it(tmp_path: Path) -> None:
    svc, session = _service(tmp_path)
    q = svc.subscribe(session.session_id)
    args = dict(MAIL)
    asking = asyncio.create_task(
        svc._ask(session.session_id, "t1", "c1", "gmail", args, "mail")  # noqa: SLF001
    )
    card = (await _next(q, "approval_required"))["payload"]
    assert card["preview"]["class"] == "mail"
    with pytest.raises(ValueError):
        svc.resolve_approval(
            session.session_id, card["approval_id"], "allow", edits={"to": "x@y.z"}
        )
    assert svc.resolve_approval(
        session.session_id, card["approval_id"], "allow", edits={"subject": "Edited"}
    )
    assert await asyncio.wait_for(asking, 2) == "allow"
    assert args["subject"] == "Edited"
    resolved = (await _next(q, "approval_resolved"))["payload"]
    assert resolved["edited"]["subject"]["after"] == "Edited"


async def test_a_new_message_sets_the_card_aside_and_a_later_allow_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, session = _service(tmp_path)
    sid = session.session_id
    sent: list[dict[str, Any]] = []

    async def fake_send(session_id: str, text: str, *a: Any, **kw: Any) -> str:
        sent.append({"text": text, **kw})
        return "turn"

    monkeypatch.setattr(svc, "send", fake_send)
    q = svc.subscribe(sid)
    args = {"action": "send_message", "to": "ada@known.example", "subject": "S", "body": "B"}
    asking = asyncio.create_task(svc._ask(sid, "t1", "c1", "gmail", dict(args), "mail"))  # noqa: SLF001
    card = (await _next(q, "approval_required"))["payload"]

    assert svc.defer_open_approvals(sid) == 1
    assert await asyncio.wait_for(asking, 2) == "deny"
    assert "did NOT run" in svc.take_deny_feedback(sid, "c1")
    assert (await _next(q, "approval_deferred"))["payload"]["approval_id"] == card["approval_id"]
    assert svc.pending_approvals(sid) == [card["approval_id"]]

    assert svc.resolve_approval(sid, card["approval_id"], "allow", edits={"body": "B2"})
    resolved = (await _next(q, "approval_resolved"))["payload"]
    assert resolved["decision"] == "allow" and resolved["deferred"] is True
    for _ in range(50):
        if sent:
            break
        await asyncio.sleep(0.05)
    assert sent and '"body": "B2"' in sent[0]["text"] and sent[0]["background_result"] is True

    # The lead's call with exactly those arguments meets the answer already given.
    same = {**args, "body": "B2"}
    assert await svc._ask(sid, "t2", "c2", "gmail", dict(same), "mail") == "allow"  # noqa: SLF001
    # ... once only: the next identical call asks again.
    again = asyncio.create_task(svc._ask(sid, "t3", "c3", "gmail", dict(same), "mail"))  # noqa: SLF001
    await _next(q, "approval_required")
    again.cancel()


async def test_nothing_is_set_aside_when_no_card_waits(tmp_path: Path) -> None:
    svc, session = _service(tmp_path)
    assert svc.defer_open_approvals(session.session_id) == 0
    assert await svc.release_waiting_turn(session.session_id) is False


async def test_a_new_message_frees_a_lead_turn_that_waits_on_a_card(tmp_path: Path) -> None:
    from types import SimpleNamespace

    svc, session = _service(tmp_path)
    sid = session.session_id
    q = svc.subscribe(sid)
    args = {"action": "send_message", "to": "ada@known.example", "subject": "S", "body": "B"}
    turn = asyncio.create_task(svc._ask(sid, "t1", "c1", "gmail", args, "mail"))  # noqa: SLF001
    await _next(q, "approval_required")
    svc._running[sid] = SimpleNamespace(task=turn)  # noqa: SLF001
    svc.is_running = lambda session_id: session_id == sid and not turn.done()  # type: ignore[method-assign]

    assert await svc.release_waiting_turn(sid) is True
    assert turn.result() == "deny"
    assert svc.pending_approvals(sid) != []  # the card is still open for a later answer


def test_the_phone_channel_carries_the_same_essentials() -> None:
    from dodaios.agent_chat.lead import _card_of
    from dodaios.channels.chat_bridge import _card_line

    preview = build_preview("gmail", MAIL, recipients_known=_known)
    card = _card_of("approval_required", {"summary": "mail", "preview": preview})
    assert card is not None and "new@stranger.example (new)" in card.summary
    assert "Betreff: Quarterly numbers" in _card_line(card, "de")  # i18n-allow
    plain = _card_of("approval_required", {"summary": "Run it", "name": "Bash"})
    assert plain is not None and plain.summary == "Run it"
