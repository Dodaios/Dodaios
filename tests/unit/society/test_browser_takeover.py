"""Watch-and-take-over: hand-back note, request tool, privacy of what the owner types."""

import asyncio
import logging
from types import SimpleNamespace

from dodaios.society.browser.live import LiveSessions, LiveUpdates
from dodaios.society.browser.takeover import TakeoverState, handback_note, safe_url
from dodaios.society.browser.takeover_tool import RequestBrowserTakeoverTool
from tests.fakes.fake_browser_profiles import LoginControlSession


def test_safe_url_keeps_host_and_path_only():
    assert (
        safe_url("https://user:pw@Example.com:8443/login/2fa?token=abc#code=9")
        == "https://example.com/login/2fa"
    )
    assert safe_url("javascript:alert(1)") == ""
    assert safe_url("") == ""


def test_note_counts_inputs_but_never_keeps_what_was_typed():
    state = TakeoverState()
    state.begin("https://shop.test/cart?id=5")
    for op in ("click", "text", "key", "scroll", "move"):
        state.record(op)
    note = state.end("https://shop.test/paid?session=secret")
    assert note["inputs"] == 4  # "move" is hover only and not an input
    assert note["typed"] is True
    assert note["url"] == "https://shop.test/paid"
    assert note["url_changed"] is True
    assert "secret" not in str(note)
    assert "not recorded" in note["text"]


def test_a_look_without_input_says_so():
    note = handback_note("https://a.test/x", "https://a.test/x", 0, 0)
    assert note["inputs"] == 0 and note["typed"] is False and note["url_changed"] is False
    assert "without doing anything" in note["text"]


def test_input_before_takeover_is_not_counted():
    state = TakeoverState()
    state.record("click")
    assert state.actions == 0


async def test_request_is_one_request_and_end_wakes_the_waiter():
    state = TakeoverState()
    first, is_new = state.request_takeover("  solve   the CAPTCHA ")
    again, repeated = state.request_takeover("something else")
    assert is_new and not repeated and again is first
    assert first["reason"] == "solve the CAPTCHA"
    waiter = asyncio.create_task(state.wait_handback(5))
    await asyncio.sleep(0)
    state.begin("https://a.test/")
    state.end("https://a.test/done")
    note = await waiter
    assert note is not None and note["request_id"] == first["id"]
    assert state.request is None


async def test_wait_times_out_without_a_handback():
    assert await TakeoverState().wait_handback(0.01) is None


class _Live(LiveSessions):
    def __init__(self, session, tmp_path):
        super().__init__(tmp_path)
        self.sessions[session.agent_id] = session


def _session():
    session = LoginControlSession("lead", capable=False)
    session.state["url"] = "https://bank.test/login"
    return session


async def test_takeover_and_handback_publish_note_without_typed_content(tmp_path):
    session = _session()
    live = _Live(session, tmp_path)
    session.takeover.request_takeover("enter the code")

    await live.control(session, "owner", "takeover", {"enabled": True})
    assert session.takeover.active
    await live.control(session, "owner", "text", {"text": "hunter2"})
    session.state["url"] = "https://bank.test/home?s=1"
    await live.control(session, "owner", "takeover", {"enabled": False})

    assert not session.takeover.active and session.takeover.request is None
    note = session.takeover.last_note
    assert note["inputs"] == 1 and note["typed"] is True
    assert note["url"] == "https://bank.test/home"
    assert "hunter2" not in str(note)
    published = [e for kind, e in session.commands if kind == "event"]
    kinds = [e["kind"] for e in published][-3:]
    assert kinds == ["takeover_request_cleared", "handback", "control"]
    assert "hunter2" not in str(published)


async def test_owner_input_is_never_logged(tmp_path, caplog):
    session = _session()
    live = _Live(session, tmp_path)
    caplog.set_level(logging.DEBUG)
    await live.control(session, "owner", "takeover", {"enabled": True})
    await live.control(session, "owner", "text", {"text": "correct-horse-battery"})
    await live.control(session, "owner", "takeover", {"enabled": False})
    assert "correct-horse-battery" not in caplog.text


async def test_viewer_loss_hands_back_and_wakes_the_agent(tmp_path):
    session = LoginControlSession("lead", capable=True)
    live = _Live(session, tmp_path)
    request, _ = session.takeover.request_takeover("sign in")
    waiter = asyncio.create_task(session.takeover.wait_handback(5, request["id"]))
    await live.control(session, "owner", "takeover", {"enabled": True})
    queue = LiveUpdates()
    session.subscribers.add(queue)
    await live.unsubscribe(session, queue, "owner")
    assert (await waiter) is not None


class _Roster:
    async def get(self, agent_id):
        return SimpleNamespace(agent_id=agent_id)


def _tool(session, tmp_path, wait_s=5.0):
    live = _Live(session, tmp_path)
    runtime = SimpleNamespace(roster=_Roster(), browser=SimpleNamespace(live=live))
    return RequestBrowserTakeoverTool(runtime, "lead", wait_s=wait_s), live


def _capture_notices(monkeypatch):
    posted = []

    async def fake_post(svc, session_id, payload):
        posted.append(payload)
        return ""

    monkeypatch.setattr("dodaios.notify.reminders.post_notice", fake_post)
    monkeypatch.setattr(
        "dodaios.notify.reminders.lead_target", lambda: (SimpleNamespace(), "lead-chat")
    )
    return posted


async def test_tool_posts_one_card_waits_and_returns_the_note(tmp_path, monkeypatch):
    posted = _capture_notices(monkeypatch)
    session = _session()
    tool, live = _tool(session, tmp_path)
    run = asyncio.create_task(tool.execute({"reason": "CAPTCHA on the login"}, None))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if session.takeover.request is not None and posted:
            break
    assert session.takeover.request["reason"] == "CAPTCHA on the login"
    assert [p["kind"] for p in posted] == ["browser_takeover"]

    await live.control(session, "owner", "takeover", {"enabled": True})
    await live.control(session, "owner", "text", {"text": "secret-code"})
    await live.control(session, "owner", "takeover", {"enabled": False})
    result = await asyncio.wait_for(run, 10)

    assert result.success and result.output["status"] == "handed_back"
    assert result.output["typed"] is True and "secret-code" not in str(result.output)
    assert [p["kind"] for p in posted] == ["browser_takeover", "browser_takeover_done"]
    assert posted[-1]["status"] == "handed_back"


async def test_tool_gives_up_cleanly_when_nobody_takes_over(tmp_path, monkeypatch):
    posted = _capture_notices(monkeypatch)
    session = _session()
    tool, _ = _tool(session, tmp_path, wait_s=0.05)
    result = await tool.execute({"reason": "2FA"}, None)
    assert not result.success
    assert session.takeover.request is None
    assert posted[-1]["status"] == "expired"


async def test_tool_requires_a_reason(tmp_path):
    tool, _ = _tool(_session(), tmp_path)
    assert not (await tool.execute({"reason": "  "}, None)).success


async def test_a_closed_browser_ends_the_wait(tmp_path, monkeypatch):
    monkeypatch.setattr("dodaios.notify.reminders.lead_target", lambda: None)
    session = _session()
    tool, _ = _tool(session, tmp_path)
    run = asyncio.create_task(tool.execute({"reason": "sign in"}, None))
    await asyncio.sleep(0.05)
    session.closed = True
    result = await asyncio.wait_for(run, 15)
    assert not result.success


def test_status_light_lists_a_running_browser_and_an_open_request():
    from dodaios.core.status_light import build_status_light

    light = build_status_light(
        browsers=[
            {"agent_id": "lead", "running": True, "request_id": "", "title": "Dodaios"},
            {"agent_id": "scout", "running": True, "request_id": "r1", "reason": "enter the code"},
        ]
    )
    assert [r["kind"] for r in light["running"]] == ["browser"]
    need = light["needs_you"][0]
    assert need["kind"] == "browser_takeover" and need["title"] == "enter the code"
    assert need["link"] == {"agent_id": "scout"}
    assert light["counts"] == {"running": 1, "needs_you": 1}


def test_phone_line_for_a_takeover_card_is_short_and_localized():
    from dodaios.agent_chat.lead import LeadCard
    from dodaios.channels.chat_bridge import _card_line

    card = LeadCard("takeover", "solve the CAPTCHA", [])
    assert "solve the CAPTCHA" in _card_line(card, "en")
    assert "übernimm" in _card_line(card, "de")  # i18n-allow
