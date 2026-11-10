"""From the attention list to the desktop (dodaios/notify/attention_bridge.py)."""

from __future__ import annotations

from typing import Any

from dodaios.agent_chat.attention import AgentAttentionChanged
from dodaios.notify import attention_bridge
from dodaios.notify.notifier import Verdict


class _Notifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def notify(self, kind: str, title: str, body: str, **kw: Any) -> Verdict:
        self.calls.append({"kind": kind, "title": title, "body": body, **kw})
        return Verdict(True, how="shown")


class _Bus:
    def __init__(self) -> None:
        self.handlers: dict[type, Any] = {}

    def subscribe(self, event_type: type, handler: Any) -> None:
        self.handlers[event_type] = handler

    async def publish(self, event: Any) -> None:
        await self.handlers[type(event)](event)


def test_kind_of_maps_transitions() -> None:
    assert attention_bridge.kind_of(AgentAttentionChanged(transition="done")) == "finished"
    assert (
        attention_bridge.kind_of(AgentAttentionChanged(transition="needs_input", kind="approval"))
        == "approval"
    )
    assert (
        attention_bridge.kind_of(AgentAttentionChanged(transition="needs_input", kind="question"))
        == "needs_you"
    )
    # A bare count refresh is no news.
    assert attention_bridge.kind_of(AgentAttentionChanged(count=3)) is None


async def test_changes_become_notifications_with_the_agent_named() -> None:
    bus, notifier = _Bus(), _Notifier()
    attention_bridge.install(bus, notifier)  # type: ignore[arg-type]
    await bus.publish(
        AgentAttentionChanged(
            count=1,
            transition="needs_input",
            agent_id="scout",
            agent_name="Scout",
            session_id="society:scout",
            kind="approval",
            ref_id="a1",
            summary="rm -rf build",
        )
    )
    await bus.publish(AgentAttentionChanged(count=0, transition="done", agent_name="Scout"))
    await bus.publish(AgentAttentionChanged(count=0))
    assert [c["kind"] for c in notifier.calls] == ["approval", "finished"]
    approval = notifier.calls[0]
    assert "Scout" in approval["title"] and approval["body"] == "rm -rf build"
    assert approval["session_id"] == "society:scout"
    finished = notifier.calls[1]
    assert "Scout" in finished["title"] and finished["body"]


async def test_a_nameless_agent_still_reads_well() -> None:
    bus, notifier = _Bus(), _Notifier()
    attention_bridge.install(bus, notifier)  # type: ignore[arg-type]
    await bus.publish(AgentAttentionChanged(transition="needs_input", kind="question"))
    assert notifier.calls[0]["title"] == "An agent needs you"
    assert notifier.calls[0]["body"] == "Open the conversation to answer."
