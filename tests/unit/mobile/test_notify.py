"""Needs-you cards and lead reminders reach every subscribed phone, once each."""

from __future__ import annotations

import asyncio

import pytest

from dodaios.agent_chat.attention import AgentAttentionChanged
from dodaios.mobile.devices import MobileDevices, PushSubscription
from dodaios.mobile.notify import MobilePushNotifier


class _Sender:
    def __init__(self, result: str = "sent") -> None:
        self.result = result
        self.sent: list[tuple[str, dict]] = []

    async def send(self, subscription, payload, *, ttl_s=0, urgency="normal"):
        self.sent.append((subscription.endpoint, {**payload, "urgency": urgency}))
        return self.result


def _subscription(endpoint: str) -> PushSubscription:
    return PushSubscription(endpoint=endpoint, p256dh="k" * 32, auth="a" * 16)


@pytest.fixture
def paired(tmp_path):
    store = MobileDevices(tmp_path / "devices.json")
    one, _ = store.redeem(store.issue_code()["code"], "One")
    two, _ = store.redeem(store.issue_code()["code"], "Two")
    store.set_push(one.id, _subscription("https://push.test/one"))
    store.set_push(two.id, _subscription("https://push.test/two"))
    return store


@pytest.mark.asyncio
async def test_needs_input_is_pushed_to_every_phone_once(paired: MobileDevices) -> None:
    sender = _Sender()
    notifier = MobilePushNotifier(devices=paired, sender=sender, assistant_name=lambda: "Nova")
    event = AgentAttentionChanged(
        count=1, transition="needs_input", agent_name="Scout", kind="approval",
        ref_id="ap1", summary="Run the deploy script",
    )
    await notifier.on_attention(event)
    assert sorted(e for e, _ in sender.sent) == ["https://push.test/one", "https://push.test/two"]
    note = sender.sent[0][1]
    assert note["title"] == "Scout needs you" and note["body"] == "Run the deploy script"
    assert note["tag"] == "needs-ap1" and note["urgency"] == "high" and note["url"] == "/m/"
    # The same card again within the window is not pushed twice.
    await notifier.on_attention(event)
    assert len(sender.sent) == 2
    # A plain refresh (no transition) is not news.
    await notifier.on_attention(AgentAttentionChanged(count=1))
    assert len(sender.sent) == 2


@pytest.mark.asyncio
async def test_kind_fallback_body_and_assistant_name(paired: MobileDevices) -> None:
    sender = _Sender()
    notifier = MobilePushNotifier(devices=paired, sender=sender, assistant_name=lambda: "Nova")
    await notifier.on_attention(
        AgentAttentionChanged(count=1, transition="needs_input", kind="credential", ref_id="c1")
    )
    assert sender.sent[0][1]["title"] == "Nova needs you"
    assert sender.sent[0][1]["body"] == "A login is needed to continue."


@pytest.mark.asyncio
async def test_gone_subscriptions_are_dropped(paired: MobileDevices) -> None:
    sender = _Sender(result="gone")
    notifier = MobilePushNotifier(devices=paired, sender=sender)
    sent = await notifier.push(tag="x", title="t", body="b")
    assert sent == 0
    assert paired.push_targets() == []


@pytest.mark.asyncio
async def test_lead_notices_push_only_reminder_kinds(paired: MobileDevices) -> None:
    sender = _Sender()
    notifier = MobilePushNotifier(
        devices=paired,
        sender=sender,
        lead_session_id=lambda: "lead-1",
        assistant_name=lambda: "Nova",
    )

    class _Service:
        def __init__(self) -> None:
            self.listeners = []

        def add_event_listener(self, fn) -> None:
            self.listeners.append(fn)

    svc = _Service()
    notifier.attach_service(svc)
    notifier.attach_service(svc)
    assert len(svc.listeners) == 1
    listener = svc.listeners[0]
    listener("lead-1", {"seq": 1, "kind": "notice", "payload": {"kind": "chat_control"}})
    listener("lead-1", {"seq": 2, "kind": "assistant_text", "payload": {"text": "hi"}})
    listener("other", {"seq": 3, "kind": "notice", "payload": {"kind": "reminder", "text": "x"}})
    listener("lead-1", {"seq": 4, "kind": "notice",
                        "payload": {"kind": "society_result", "text": "The brief is ready."}})
    listener("lead-1", {"seq": 5, "kind": "notice",
                        "payload": {"kind": "custom", "push": True, "text": "Water the plants"}})
    await asyncio.sleep(0.05)
    bodies = sorted(p["body"] for _, p in sender.sent if p["tag"] == "notice-4")
    assert bodies == ["The brief is ready.", "The brief is ready."]
    custom = [p for _, p in sender.sent if p["tag"] == "notice-5"]
    assert custom and custom[0]["body"] == "Water the plants" and custom[0]["title"] == "Nova"
    assert not [p for _, p in sender.sent if p["tag"] == "notice-3"]


@pytest.mark.asyncio
async def test_no_phones_means_nothing_is_sent(tmp_path) -> None:
    sender = _Sender()
    notifier = MobilePushNotifier(devices=MobileDevices(tmp_path / "d.json"), sender=sender)
    assert await notifier.push(tag="a", title="t", body="b") == 0
    assert sender.sent == []
