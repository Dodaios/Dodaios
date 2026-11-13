"""A browser step must not be lost to a consent wall, a hung action or a prose reply.

No real browser here; the consent tests in ``tests/contract/test_browser_live.py`` run
the same paths in Chromium.
"""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from dodaios.society.browser.consent_walls import dismiss_consent
from dodaios.society.browser.live import LiveSession
from dodaios.society.browser.model_reply import json_candidates, parse_reply


def _runner():
    previous = sys.stdout
    try:
        from dodaios.society.browser import live_runner
    finally:
        sys.stdout = previous  # The worker module points stdout at stderr.
    return live_runner


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory: str
    action: list[dict]


BODY = {"memory": "on the page", "action": [{"click": {"index": 3}}]}


# ------------------------------------------------------------- model replies


@pytest.mark.parametrize(
    "reply",
    [
        json.dumps(BODY),
        "```json\n" + json.dumps(BODY) + "\n```",
        "Here is my next step:\n```json\n" + json.dumps(BODY) + "\n```\nDone.",
        "I will click the button. " + json.dumps(BODY),
        "```\n" + json.dumps(BODY, indent=2) + "\n```",
    ],
)
def test_the_json_object_is_found_inside_fences_and_prose(reply):
    assert parse_reply(reply, Output) == Output(**BODY)


def test_an_object_that_does_not_fit_the_schema_is_skipped():
    reply = 'Note {"hint": 1} then ' + json.dumps(BODY)
    assert parse_reply(reply, Output).memory == "on the page"


def test_prose_only_raises_the_schema_error_browser_use_reports():
    with pytest.raises(ValidationError, match="json_invalid"):
        parse_reply('Both attempts to click "Alle ablehnen" timed out.', Output)


def test_an_empty_reply_is_an_error():
    with pytest.raises(ValueError, match="empty"):
        parse_reply("   ", Output)


def test_candidates_are_tried_once_each():
    reply = json.dumps(BODY)
    assert list(json_candidates(reply)) == [reply]


# ----------------------------------------------------------- action timeouts


def test_page_actions_fail_fast_and_model_actions_keep_the_library_limit():
    runner = _runner()
    assert runner.action_timeout_s({"click": {"index": 4}}) == runner.CLICK_TIMEOUT_S
    assert runner.action_timeout_s({"navigate": {"url": "https://a.test"}}) == (
        runner.NAVIGATION_TIMEOUT_S
    )
    assert runner.action_timeout_s({"scroll": {"down": True}}) == runner.INTERACTION_TIMEOUT_S
    assert runner.action_timeout_s({"input": {"index": 2, "text": "x"}}) == (
        runner.INTERACTION_TIMEOUT_S
    )
    assert runner.action_timeout_s({"extract": {"query": "prices"}}) is None
    assert runner.action_timeout_s({"done": {"text": "ok"}}) is None
    assert runner.CLICK_TIMEOUT_S < 60  # Browser-Use's own cap was 180 s.


def test_a_step_outlasts_an_approval_wait():
    runner = _runner()
    # A click waits up to 600 s for the person's approval (bridge.py); the old
    # 180 s step limit cut that wait off and sent a second approval card.
    assert runner.STEP_TIMEOUT_S > 600


async def test_an_abandoned_worker_request_tells_the_parent(monkeypatch):
    runner = _runner()
    sent = []
    monkeypatch.setattr(runner, "emit", lambda kind, **data: sent.append((kind, data)))
    worker = runner.Worker()
    request = asyncio.create_task(worker.rpc("action", {"action": {"click": {"index": 1}}}))
    for _ in range(50):
        if sent:
            break
        await asyncio.sleep(0.01)
    key = sent[0][1]["id"]
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert sent[-1] == ("rpc_cancel", {"id": key})
    assert worker.pending == {}


async def test_an_answered_worker_request_sends_no_cancel(monkeypatch):
    runner = _runner()
    sent = []
    monkeypatch.setattr(runner, "emit", lambda kind, **data: sent.append((kind, data)))
    worker = runner.Worker()
    request = asyncio.create_task(worker.rpc("llm", {}))
    for _ in range(50):
        if worker.pending:
            break
        await asyncio.sleep(0.01)
    next(iter(worker.pending.values())).set_result({"ok": True})
    assert await request == {"ok": True}
    assert [kind for kind, _ in sent] == ["llm"]


async def test_the_parent_stops_answering_a_request_the_worker_gave_up():
    reader = asyncio.StreamReader()
    session = LiveSession(
        "lead",
        SimpleNamespace(stdout=reader, stdin=None),
        SimpleNamespace(close=lambda: None),
    )
    waiting = asyncio.Event()
    withdrawn = asyncio.Event()

    async def action(payload):
        waiting.set()
        try:
            await asyncio.sleep(3600)  # An approval card nobody answers.
        except asyncio.CancelledError:
            withdrawn.set()
            raise

    session.rpc = {"action": action}
    reading = asyncio.create_task(session.read())
    reader.feed_data(json.dumps({"kind": "action", "id": "r1", "payload": {}}).encode() + b"\n")
    await asyncio.wait_for(waiting.wait(), 5)
    assert "r1" in session.rpc_tasks
    reader.feed_data(json.dumps({"kind": "rpc_cancel", "id": "r1"}).encode() + b"\n")
    await asyncio.wait_for(withdrawn.wait(), 5)
    reader.feed_eof()
    await reading
    assert session.rpc_tasks == {}


# ------------------------------------------------------------- consent walls


class Frame:
    def __init__(self, url, answers):
        self.url = url
        self.answers = list(answers)

    def is_detached(self):
        return False

    async def evaluate(self, script, words):
        assert "(words) =>" in script
        assert {"alle ablehnen", "reject all"} <= set(words["strong"])
        answer = self.answers.pop(0) if self.answers else None
        if answer == "hang":
            await asyncio.sleep(3600)
        return answer


class Page:
    def __init__(self, *frames):
        self.main_frame = frames[0]
        self.frames = list(frames)
        self.settled = 0

    def is_closed(self):
        return False

    async def wait_for_load_state(self, state, **options):
        self.settled += 1


async def test_a_refusal_in_an_iframe_is_clicked_and_reported():
    banner = {"text": "reject all", "rank": -1, "how": "button.sp_choice_type_13", "host": "cmp"}
    page = Page(Frame("https://shop.test/", []), Frame("https://cmp.test/", [banner]))
    hits = await dismiss_consent(page)
    assert hits == [{**banner, "url": "https://cmp.test/"}]
    assert page.settled == 1


async def test_a_hanging_frame_cannot_hold_the_step(monkeypatch):
    monkeypatch.setattr("dodaios.society.browser.consent_walls._FRAME_TIMEOUT_S", 0.05)
    page = Page(Frame("https://slow.test/", ["hang"]))
    async with asyncio.timeout(2):
        assert await dismiss_consent(page) == []


async def test_the_consent_check_never_raises():
    class Broken(Page):
        @property
        def frames(self):
            raise RuntimeError("target closed")

        @frames.setter
        def frames(self, value):
            pass

    assert await dismiss_consent(Broken(Frame("https://x.test/", []))) == []
    assert await dismiss_consent(None) == []


async def test_a_wall_is_answered_in_a_bounded_number_of_clicks():
    hit = {"text": "alle ablehnen", "rank": 0, "how": "text", "host": "consent.google.com"}
    page = Page(Frame("https://consent.google.com/m", [hit] * 10))
    assert len(await dismiss_consent(page)) == 3
