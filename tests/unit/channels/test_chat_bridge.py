from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from dodaios.channels.base import ChannelMessage, ChannelSession
from dodaios.channels.chat_bridge import ChannelChatBridge
from dodaios.core.bus import EventBus
from dodaios.core.events import Event, MessageSent


class _QueueChannel:
    name = "telegram"

    def __init__(self) -> None:
        self.queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_message(self, msg: ChannelMessage) -> None: ...
    async def broadcast_event(self, event: Event) -> None: ...

    async def messages(self) -> AsyncIterator[ChannelMessage]:
        while True:
            yield await self.queue.get()

    async def sessions(self) -> list[ChannelSession]:
        return []


class _Manager:
    def __init__(self, channel: _QueueChannel) -> None:
        self.channel = channel

    def started(self) -> list[str]:
        return ["telegram"]

    def get(self, name: str) -> _QueueChannel:
        assert name == "telegram"
        return self.channel


@pytest.mark.asyncio
async def test_bridge_publishes_channel_text_as_user_message() -> None:
    bus = EventBus()
    channel = _QueueChannel()
    bridge = ChannelChatBridge(bus=bus, manager=_Manager(channel))  # type: ignore[arg-type]
    seen: list[MessageSent] = []
    ready = asyncio.Event()

    async def _capture(event: MessageSent) -> None:
        seen.append(event)
        ready.set()

    bus.subscribe(MessageSent, _capture)
    bridge.start()
    trace_id = uuid4()
    await channel.queue.put(
        ChannelMessage(
            session_id=uuid4(),
            kind="text",
            content="Hello",
            trace_id=trace_id,
            metadata={"telegram_chat_id": 12345},
        )
    )

    await asyncio.wait_for(ready.wait(), timeout=1.0)
    await bridge.stop()

    assert len(seen) == 1
    assert seen[0].trace_id == trace_id
    assert seen[0].thread_id == "telegram:12345"
    assert seen[0].role == "user"
    assert seen[0].text == "Hello"
    assert seen[0].source_layer == "channel.telegram"


class _SwapManager:
    def __init__(self, channel: _QueueChannel) -> None:
        self._channel = channel

    def started(self) -> list[str]:
        return ["telegram"]

    def get(self, name: str) -> _QueueChannel:
        assert name == "telegram"
        return self._channel

    def set_channel(self, channel: _QueueChannel) -> None:
        self._channel = channel


@pytest.mark.asyncio
async def test_refresh_rebinds_consumer_to_new_instance() -> None:
    bus = EventBus()
    old = _QueueChannel()
    mgr = _SwapManager(old)
    bridge = ChannelChatBridge(bus=bus, manager=mgr)  # type: ignore[arg-type]
    seen: list[MessageSent] = []
    ready = asyncio.Event()

    async def _capture(event: MessageSent) -> None:
        seen.append(event)
        ready.set()

    bus.subscribe(MessageSent, _capture)
    bridge.start()

    # Live reload swapped the channel instance — rebind the consumer.
    new = _QueueChannel()
    mgr.set_channel(new)
    await bridge.refresh("telegram")

    # A message on the OLD (now-detached) instance must NOT be consumed.
    await old.queue.put(
        ChannelMessage(
            session_id=uuid4(),
            kind="text",
            content="from-old",
            metadata={"telegram_chat_id": 1},
        )
    )
    # A message on the NEW instance must reach the bus.
    await new.queue.put(
        ChannelMessage(
            session_id=uuid4(),
            kind="text",
            content="from-new",
            metadata={"telegram_chat_id": 2},
        )
    )

    await asyncio.wait_for(ready.wait(), timeout=1.0)
    await asyncio.sleep(0.05)
    await bridge.stop()

    texts = [e.text for e in seen]
    assert "from-new" in texts
    assert "from-old" not in texts


@pytest.mark.asyncio
async def test_bridge_ignores_empty_and_system_messages() -> None:
    bus = EventBus()
    channel = _QueueChannel()
    bridge = ChannelChatBridge(bus=bus, manager=_Manager(channel))  # type: ignore[arg-type]
    seen: list[MessageSent] = []

    async def _capture(event: MessageSent) -> None:
        seen.append(event)

    bus.subscribe(MessageSent, _capture)
    bridge.start()
    await channel.queue.put(ChannelMessage(session_id=uuid4(), kind="system", content="hidden"))
    await channel.queue.put(ChannelMessage(session_id=uuid4(), kind="text", content="   "))
    await asyncio.sleep(0.05)
    await bridge.stop()

    assert seen == []


class _ReplyChannel(_QueueChannel):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[ChannelMessage] = []
        self.got = asyncio.Event()

    async def send_message(self, msg: ChannelMessage) -> None:
        self.sent.append(msg)
        self.got.set()


@pytest.mark.asyncio
async def test_owner_private_chat_continues_the_lead_conversation(monkeypatch) -> None:
    from dodaios.agent_chat import lead

    asked: list[str] = []

    async def fake_answer(svc, text, *, source, timeout_s=900.0, **_kw):
        asked.append(text)
        return "Lisbon, in June."

    monkeypatch.setattr(lead, "answer_in_lead", fake_answer)
    bus = EventBus()
    channel = _ReplyChannel()
    bridge = ChannelChatBridge(
        bus=bus,
        manager=_Manager(channel),
        get_chat_service=lambda: object(),  # type: ignore[arg-type]
    )
    published: list[MessageSent] = []

    async def _capture(event: MessageSent) -> None:
        published.append(event)

    bus.subscribe(MessageSent, _capture)
    bridge.start()
    owner = {"telegram_chat_id": 12345, "friend_id": None}
    await channel.queue.put(
        ChannelMessage(
            session_id=uuid4(), kind="text", content="Where is the wedding?", metadata=owner
        )
    )
    await asyncio.wait_for(channel.got.wait(), timeout=2.0)
    assert asked == ["Where is the wedding?"]
    assert channel.sent[0].content == "Lisbon, in June."
    assert channel.sent[0].metadata["telegram_chat_id"] == 12345
    assert published == []

    # A friend never reaches the owner's conversation.
    friend = {"telegram_chat_id": 777, "friend_id": "f-1"}
    await channel.queue.put(
        ChannelMessage(session_id=uuid4(), kind="text", content="hi from a friend", metadata=friend)
    )
    # A group chat neither.
    group = {"telegram_chat_id": -100, "friend_id": None}
    await channel.queue.put(
        ChannelMessage(session_id=uuid4(), kind="text", content="group hello", metadata=group)
    )
    for _ in range(50):
        if len(published) == 2:
            break
        await asyncio.sleep(0.02)
    await bridge.stop()
    assert [e.text for e in published] == ["hi from a friend", "group hello"]
    assert asked == ["Where is the wedding?"]


def test_only_discord_direct_messages_of_the_owner_reach_the_lead() -> None:
    bridge = ChannelChatBridge(
        bus=EventBus(),
        manager=_Manager(_QueueChannel()),
        get_chat_service=lambda: "svc",  # type: ignore[arg-type]
    )

    def msg(meta: dict) -> ChannelMessage:
        return ChannelMessage(session_id=uuid4(), kind="text", content="x", metadata=meta)

    assert bridge._lead_service("discord", msg({"discord_dm": True, "friend_id": None})) == "svc"  # noqa: SLF001
    assert bridge._lead_service("discord", msg({"discord_dm": False})) is None  # noqa: SLF001
    assert bridge._lead_service("discord", msg({"discord_dm": True, "friend_id": "f"})) is None  # noqa: SLF001
    assert bridge._lead_service("discord", msg({})) is None  # noqa: SLF001


class _CardSvc:
    """A chat service with one open approval and one open question."""

    def __init__(self, *, approvals: list[str], questions: list[str]) -> None:
        self.approvals = approvals
        self.questions = questions
        self.resolved: list[tuple[str, str]] = []
        self.answered: list[str] = []

    def lead_session(self, *_a, **_k):
        from types import SimpleNamespace

        return SimpleNamespace(session_id="lead-1")

    def pending_approvals(self, session_id: str) -> list[str]:
        return list(self.approvals)

    def pending_questions(self, session_id: str) -> list[str]:
        return list(self.questions)

    def resolve_approval(self, session_id: str, approval_id: str, decision: str) -> bool:
        self.resolved.append((approval_id, decision))
        return True

    async def answer_by_message(self, session_id: str, text: str) -> dict:
        self.answered.append(text)
        return {"consumed": True, "question_id": "q1"}


async def _run_owner_message(monkeypatch, svc, text: str, answer_fn=None):
    from dodaios.agent_chat import lead

    monkeypatch.setattr(lead, "lead_session", lambda s, **_k: s.lead_session())
    if answer_fn is not None:
        monkeypatch.setattr(lead, "answer_in_lead", answer_fn)
    channel = _ReplyChannel()
    bridge = ChannelChatBridge(
        bus=EventBus(), manager=_Manager(channel), get_chat_service=lambda: svc
    )
    bridge.start()
    owner = {"telegram_chat_id": 12345, "friend_id": None}
    await channel.queue.put(
        ChannelMessage(session_id=uuid4(), kind="text", content=text, metadata=owner)
    )
    return bridge, channel


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "text", "needle"),
    [
        ("error", "Where is the wedding?", "error"),
        ("timeout", "Where is the wedding?", "too long"),
        ("empty", "Where is the wedding?", "without an answer"),
        ("error", "Ich brauche den Plan für morgen, bitte schnell", "Fehler"),  # i18n-allow
    ],
)
async def test_the_owner_always_gets_an_answer(monkeypatch, status, text, needle) -> None:
    async def fake_answer(svc, text, *, source, report=None, on_card=None, **_kw):
        report.status = status
        return ""

    bridge, channel = await _run_owner_message(
        monkeypatch, _CardSvc(approvals=[], questions=[]), text, fake_answer
    )
    await asyncio.wait_for(channel.got.wait(), timeout=2.0)
    await bridge.stop()
    line = channel.sent[0].content
    assert needle in line and "app" in line.lower()


@pytest.mark.asyncio
async def test_a_crashing_turn_still_answers(monkeypatch) -> None:
    async def boom(svc, text, **_kw):
        raise RuntimeError("provider said something private")

    bridge, channel = await _run_owner_message(
        monkeypatch, _CardSvc(approvals=[], questions=[]), "hello there", boom
    )
    await asyncio.wait_for(channel.got.wait(), timeout=2.0)
    await bridge.stop()
    assert "private" not in channel.sent[0].content
    assert "couldn't finish" in channel.sent[0].content


@pytest.mark.asyncio
async def test_an_open_card_is_sent_to_the_chat(monkeypatch) -> None:
    from dodaios.agent_chat.lead import LeadCard

    async def fake_answer(svc, text, *, source, report=None, on_card=None, **_kw):
        await on_card(LeadCard("approval", "Send the mail to Max", []))
        await on_card(LeadCard("question", "Which day?", ["Monday", "Friday"]))
        return "Done."

    svc = _CardSvc(approvals=[], questions=[])
    bridge, channel = await _run_owner_message(monkeypatch, svc, "mail Max", fake_answer)
    for _ in range(100):
        if len(channel.sent) == 3:
            break
        await asyncio.sleep(0.02)
    await bridge.stop()
    texts = [m.content for m in channel.sent]
    assert "Send the mail to Max" in texts[0] and "yes or no" in texts[0]
    assert "Which day?" in texts[1] and "Monday, Friday" in texts[1]
    assert texts[2] == "Done."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("word", "decision"), [("Yes", "allow"), ("nein", "deny"), ("OK!", "allow")]
)
async def test_yes_or_no_from_the_chat_settles_the_open_approval(
    monkeypatch, word, decision
) -> None:
    asked: list[str] = []

    async def fake_answer(svc, text, **_kw):
        asked.append(text)
        return "x"

    svc = _CardSvc(approvals=["ap-1", "ap-2"], questions=[])
    bridge, _channel = await _run_owner_message(monkeypatch, svc, word, fake_answer)
    await asyncio.sleep(0.1)
    await bridge.stop()
    assert svc.resolved == [("ap-1", decision)]
    assert asked == []  # consumed: it did not start a new turn


@pytest.mark.asyncio
async def test_a_message_answers_the_open_question(monkeypatch) -> None:
    asked: list[str] = []

    async def fake_answer(svc, text, **_kw):
        asked.append(text)
        return "x"

    svc = _CardSvc(approvals=[], questions=["qid"])
    bridge, _channel = await _run_owner_message(monkeypatch, svc, "On Friday", fake_answer)
    await asyncio.sleep(0.1)
    await bridge.stop()
    assert svc.answered == ["On Friday"] and asked == []


@pytest.mark.asyncio
async def test_without_an_open_card_yes_is_an_ordinary_message(monkeypatch) -> None:
    asked: list[str] = []

    async def fake_answer(svc, text, **_kw):
        asked.append(text)
        return "ok then"

    svc = _CardSvc(approvals=[], questions=[])
    bridge, channel = await _run_owner_message(monkeypatch, svc, "yes", fake_answer)
    await asyncio.wait_for(channel.got.wait(), timeout=2.0)
    await bridge.stop()
    assert asked == ["yes"] and svc.resolved == []
