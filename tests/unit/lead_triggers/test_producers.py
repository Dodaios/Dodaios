"""Pollers for the trigger intake: cursors, dedupe, backoff, pauses and the own-address route.

Every provider is a fake HTTP transport; no model and no key is ever involved.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from dodaios.lead_triggers import SourceRule, TriggerEvent, TriggerService, TriggerSettings
from dodaios.lead_triggers.event import AGENT_SCOPE_PREFIX
from dodaios.lead_triggers.producers import ProducerRunner, RateLimited
from dodaios.lead_triggers.producers.agentmail import AgentMailProducer
from dodaios.lead_triggers.producers.base import Api, AuthError, NotConnected
from dodaios.lead_triggers.producers.calendar import CalendarProducer
from dodaios.lead_triggers.producers.github import GithubProducer
from dodaios.lead_triggers.producers.gmail import GmailProducer
from dodaios.lead_triggers.service import AGENT_MAIL_POLICY_ID

NOW = 1_800_000_000.0


class Store:
    def __init__(self) -> None:
        self.meta: dict[str, str] = {}

    async def get_meta(self, key: str, default: str = "") -> str:
        return self.meta.get(key, default)

    async def set_meta(self, key: str, value: str) -> None:
        self.meta[key] = value


class Fake:
    """A scripted provider: ``routes`` maps a path to a response factory."""

    def __init__(self) -> None:
        self.routes: dict[str, Any] = {}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for path, answer in self.routes.items():
            if request.url.path.endswith(path):
                return answer(request) if callable(answer) else answer
        return httpx.Response(404, json={})

    def api(self, plugin: str, **kw: Any) -> Api:
        async def tokens() -> Any:
            return SimpleNamespace(access="tok", needs_reauth=False)

        return Api(plugin, transport=httpx.MockTransport(self.handler), tokens=tokens, **kw)


def ok(body: Any, **headers: str) -> httpx.Response:
    return httpx.Response(200, json=body, headers=headers)


def message(mid: str, *, frm: str = "Ann <ann@client.com>", labels: list[str] | None = None,
            to: str = "me@x.com", extra: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {"From": frm, "To": to, "Subject": f"Subject {mid}", **(extra or {})}
    return {"id": mid, "threadId": f"t{mid}", "snippet": "hello there",
            "labelIds": labels or ["INBOX", "UNREAD"],
            "payload": {"headers": [{"name": k, "value": v} for k, v in headers.items()]}}


# --------------------------------------------------------------------- api


async def test_a_401_refreshes_once_and_retries() -> None:
    fake, refreshed = Fake(), []
    answers = iter([httpx.Response(401), ok({"ok": True})])
    fake.routes["/x"] = lambda r: next(answers)

    async def refresh(observed: str | None) -> bool:
        refreshed.append(observed)
        return True

    response = await fake.api("p", refresh=refresh).get("https://h.example/x")
    assert response.status_code == 200 and refreshed == ["tok"]


async def test_a_refused_refresh_is_an_auth_error_and_a_429_a_rate_limit() -> None:
    fake = Fake()
    fake.routes["/x"] = httpx.Response(401)

    async def refuse(observed: str | None) -> bool:
        return False

    with pytest.raises(AuthError):
        await fake.api("p", refresh=refuse).get("https://h.example/x")
    fake.routes["/x"] = httpx.Response(429, headers={"Retry-After": "90"})
    with pytest.raises(RateLimited) as caught:
        await fake.api("p").get("https://h.example/x")
    assert caught.value.retry_after_s == 90


async def test_no_token_is_not_connected() -> None:
    async def none() -> Any:
        return None

    api = Api("p", tokens=none)
    assert await api.connected() is False
    with pytest.raises(NotConnected):
        await api.get("https://h.example/x")


# ------------------------------------------------------------------- gmail


async def test_gmail_marks_the_present_then_reads_only_new_inbox_mail() -> None:
    fake = Fake()
    fake.routes["/profile"] = ok({"historyId": "100"})
    producer = GmailProducer(fake.api("gmail"))
    first = await producer.poll({}, NOW)
    assert first.events == [] and first.cursor["history_id"] == "100"

    fake.routes["/history"] = ok({"historyId": "120", "history": [
        {"id": "110", "messagesAdded": [{"message": {"id": "m1"}}]},
        {"id": "115", "messagesAdded": [{"message": {"id": "m2"}}, {"message": {"id": "m1"}}]},
    ]})
    fake.routes["/messages/m1"] = ok(message("m1"))
    fake.routes["/messages/m2"] = ok(message("m2", labels=["SENT"]))
    second = await producer.poll(first.cursor, NOW)
    history_call = next(r for r in fake.requests if r.url.path.endswith("/history"))
    assert history_call.url.params["startHistoryId"] == "100"
    assert [e.ids[0] for e in second.events] == ["m1"]  # the sent copy is skipped
    event = second.events[0]
    assert (event.source, event.sender, event.thread_key) == ("mail", "ann@client.com", "tm1")
    assert "Subject m1" in event.summary and "hello there" in event.summary
    assert "INBOX" in event.labels and second.cursor["history_id"] == "120"


async def test_gmail_flags_machine_mail_and_recovers_from_an_expired_history_id() -> None:
    fake = Fake()
    fake.routes["/history"] = ok({"historyId": "9", "history": [
        {"id": "5", "messagesAdded": [{"message": {"id": "a"}}, {"message": {"id": "b"}}]}]})
    fake.routes["/messages/a"] = ok(message("a", frm="noreply@shop.com"))
    fake.routes["/messages/b"] = ok(message("b", extra={"Precedence": "bulk"}))
    producer = GmailProducer(fake.api("gmail"))
    poll = await producer.poll({"history_id": "1"}, NOW)
    assert [e.is_bot for e in poll.events] == [True, True]

    fake.routes["/history"] = httpx.Response(404)
    fake.routes["/profile"] = ok({"historyId": "777"})
    expired = await producer.poll({"history_id": "1"}, NOW)
    assert expired.events == [] and expired.cursor["history_id"] == "777"


async def test_gmail_backlog_survives_to_the_next_poll() -> None:
    fake = Fake()
    ids = [f"m{i}" for i in range(45)]
    fake.routes["/history"] = ok({"historyId": "9", "history": [
        {"id": "5", "messagesAdded": [{"message": {"id": i}} for i in ids]}]})
    for i in ids:
        fake.routes[f"/messages/{i}"] = ok(message(i))
    producer = GmailProducer(fake.api("gmail"))
    first = await producer.poll({"history_id": "1"}, NOW)
    assert len(first.events) == 40 and first.cursor["backlog"] == ids[40:]
    fake.routes["/history"] = ok({"historyId": "9", "history": []})
    second = await producer.poll(first.cursor, NOW)
    assert [e.ids[0] for e in second.events] == ids[40:]


async def test_gmail_mail_to_the_agent_address_carries_the_agent_scope() -> None:
    fake = Fake()
    fake.routes["/history"] = ok({"historyId": "9", "history": [
        {"id": "5", "messagesAdded": [{"message": {"id": "a"}}]}]})
    fake.routes["/messages/a"] = ok(message("a", to="Jarvis <agent@mail.example>"))
    producer = GmailProducer(fake.api("gmail"), lambda: "agent@mail.example")
    poll = await producer.poll({"history_id": "1"}, NOW)
    assert poll.events[0].scope == f"{AGENT_SCOPE_PREFIX}agent@mail.example"


# ---------------------------------------------------------------- calendar


async def test_calendar_reports_invites_changes_and_starts_soon_once() -> None:
    fake = Fake()
    primary = {"id": "primary", "summary": "Me", "primary": True}
    fake.routes["/calendarList"] = ok({"items": [primary]})

    def events(request: httpx.Request) -> httpx.Response:
        if "updatedMin" in request.url.params:
            return ok({"items": [
                {"id": "e1", "summary": "Kickoff", "status": "confirmed", "updated": "u1",
                 "created": "2999-01-01T00:00:00Z", "organizer": {"email": "Boss@x.com"},
                 "attendees": [{"self": True, "responseStatus": "needsAction"}],
                 "start": {"dateTime": "2999-01-02T10:00:00Z"}},
                {"id": "e2", "summary": "Mine", "organizer": {"self": True}, "updated": "u2"},
                {"id": "e3", "status": "cancelled", "summary": "Lunch", "updated": "u3",
                 "organizer": {"email": "c@x.com"}},
            ]})
        return ok({"items": [{"id": "e9", "summary": "Standup", "start": {"dateTime": "t9"}}]})

    fake.routes["/events"] = events
    producer = CalendarProducer(fake.api("google_calendar"))
    first = await producer.poll({}, NOW)
    assert first.events == []
    second = await producer.poll(first.cursor, NOW + 120)
    kinds = [e.summary.split(":")[0] for e in second.events]
    assert kinds == ["Invite", "Cancelled", "Starting soon"]
    assert second.events[0].sender == "boss@x.com"
    third = await producer.poll(second.cursor, NOW + 240)
    assert [e.summary.split(":")[0] for e in third.events] == ["Invite", "Cancelled"]
    assert not any(e.labels == ("starting_soon",) for e in third.events)  # remembered


# ------------------------------------------------------------------ github


async def test_github_is_conditional_and_dedupes_by_update_time() -> None:
    fake = Fake()
    item = {"id": "n1", "reason": "review_requested", "updated_at": "T1",
            "subject": {"title": "Fix it", "type": "PullRequest",
                        "url": "https://api.github.com/repos/o/r/pulls/7"},
            "repository": {"full_name": "o/r"}}
    ci = {"id": "n2", "reason": "ci_activity", "updated_at": "T2",
          "subject": {"title": "CI workflow run failed", "type": "CheckSuite", "url": ""},
          "repository": {"full_name": "o/r"}}
    fake.routes["/notifications"] = ok([item], etag='"e1"', **{"X-Poll-Interval": "60"})
    producer = GithubProducer(fake.api("github"))
    first = await producer.poll({}, NOW)
    assert first.events == [] and first.cursor["etag"] == '"e1"'

    fake.routes["/notifications"] = ok([item, ci], etag='"e2"')
    second = await producer.poll(first.cursor, NOW)
    assert [e.summary for e in second.events] == ["CI: CI workflow run failed"]
    assert fake.requests[-1].headers["If-None-Match"] == '"e1"'

    fake.routes["/notifications"] = httpx.Response(304, headers={"X-Poll-Interval": "120"})
    third = await producer.poll(second.cursor, NOW)
    assert third.events == [] and third.cursor == second.cursor and third.min_interval_s == 120

    item["updated_at"] = "T3"
    fake.routes["/notifications"] = ok([item], etag='"e3"')
    fourth = await producer.poll(second.cursor, NOW)
    assert fourth.events[0].raw_ref == "https://github.com/o/r/pull/7"
    assert fourth.events[0].scope == "o/r" and "review requested" in fourth.events[0].summary


# --------------------------------------------------------------- agentmail


async def test_agentmail_reads_new_received_mail_of_the_configured_inbox() -> None:
    fake = Fake()
    producer = AgentMailProducer(fake.api("agentmail"), lambda: "agent@mail.example")
    first = await producer.poll({}, NOW)
    assert first.events == []
    stamp = "2027-01-15T09:00:00Z"
    fake.routes["/messages"] = ok({"messages": [
        {"message_id": "x1", "thread_id": "th", "from": "Ben <ben@x.com>", "subject": "Do it",
         "preview": "please", "timestamp": stamp, "labels": ["received"]},
        {"message_id": "x2", "from": "agent@mail.example", "subject": "Out", "timestamp": stamp,
         "labels": ["sent"]},
    ]})
    second = await producer.poll(first.cursor, NOW)
    assert [(e.ids[0], e.sender, e.scope) for e in second.events] == [
        ("x1", "ben@x.com", "agent:agent@mail.example")]
    assert (await producer.poll(second.cursor, NOW)).events == []


async def test_agentmail_without_an_address_is_not_pollable() -> None:
    with pytest.raises(NotConnected):
        await AgentMailProducer(Fake().api("agentmail"), lambda: "").poll({}, NOW)


# ------------------------------------------------------------------ runner


class Rig:
    """The real intake in observe mode with a seat that must never be asked."""

    def __init__(self) -> None:
        self.store = Store()
        self.now = NOW
        self.held = False
        self.seat_calls = 0
        self.started: list[Any] = []
        self.service = TriggerService(
            self.store, seat=self._seat, starter=self._starter, notifier=self._notify,
            clock=lambda: self.now, batch_window_s=3600,
        )
        self.fake = Fake()
        self.fake.routes["/profile"] = ok({"historyId": "1"})
        self.fake.routes["/history"] = ok({"historyId": "2", "history": [
            {"id": "2", "messagesAdded": [{"message": {"id": "m1"}}]}]})
        self.fake.routes["/messages/m1"] = ok(message("m1"))
        self.runner = ProducerRunner(
            self.store, [GmailProducer(self.fake.api("gmail"))],
            settings=self.service.settings, submit=self._submit, paused=lambda: self.held,
            clock=lambda: self.now,
        )

    async def _seat(self, prompt: str) -> str | None:
        self.seat_calls += 1
        return None

    async def _starter(self, *args: Any) -> str:
        self.started.append(args)
        return "task"

    async def _notify(self, record: dict[str, Any]) -> None:
        pass

    async def _submit(self, event: TriggerEvent) -> str:
        if event.scope.startswith(AGENT_SCOPE_PREFIX):
            return await self.service.submit_agent_mail(event)
        return await self.service.submit(event)

    async def configure(self, **extra: Any) -> None:
        settings: dict[str, Any] = {
            "accept": "observe", "sources": {"mail": {"mode": "candidate"}}, **extra}
        await self.service.save_settings(TriggerSettings.from_dict(settings))

    def gmail_calls(self) -> int:
        return len(self.fake.requests)


async def test_events_reach_the_intake_in_observe_mode_without_a_model() -> None:
    rig = Rig()
    await rig.configure()
    await rig.runner.tick()  # baseline
    rig.now += 200
    await rig.runner.tick()
    view = await rig.service.view()
    assert view["counts"]["received"] == 1 and view["counts"]["candidates"] == 1
    assert rig.seat_calls == 0 and rig.started == []
    [state] = await rig.runner.view()
    assert (state["state"], state["events"]) == ("polling", 1)
    assert state["last_event_at"] == rig.now
    rig.now += 200  # nothing new: the same message is not delivered twice
    rig.fake.routes["/history"] = ok({"historyId": "3", "history": []})
    await rig.runner.tick()
    assert (await rig.service.view())["counts"]["received"] == 1


async def test_the_poll_interval_gates_requests() -> None:
    rig = Rig()
    await rig.configure(poll_interval_s=300)
    await rig.runner.tick()
    count = rig.gmail_calls()
    rig.now += 100
    await rig.runner.tick()
    assert rig.gmail_calls() == count
    rig.now += 250
    await rig.runner.tick()
    assert rig.gmail_calls() > count


@pytest.mark.parametrize(
    ("extra", "hold", "state"),
    [
        ({"producers": {"gmail": False}}, False, "off"),
        ({"accept": "off"}, False, "paused"),
        ({}, True, "held"),
        ({"sources": {"mail": {"mode": "explicit_only"}}}, False, "idle"),
    ],
)
async def test_a_paused_poller_asks_the_provider_nothing(
    extra: dict[str, Any], hold: bool, state: str
) -> None:
    rig = Rig()
    await rig.configure(**extra)
    rig.held = hold
    await rig.runner.tick()
    assert rig.gmail_calls() == 0
    assert (await rig.runner.view())[0]["state"] == state
    # lifting the pause resumes polling
    rig.held = False
    await rig.configure()
    await rig.runner.tick()
    assert rig.gmail_calls() > 0


async def test_errors_back_off_and_a_rate_limit_waits_what_the_provider_says() -> None:
    rig = Rig()
    await rig.configure(poll_interval_s=60)
    rig.fake.routes["/profile"] = httpx.Response(500)
    await rig.runner.tick()
    entry = json.loads(rig.store.meta["lead.triggers.producers"])["gmail"]
    assert entry["state"] == "backoff" and entry["next_at"] == NOW + 120
    rig.now = entry["next_at"]
    await rig.runner.tick()
    entry = json.loads(rig.store.meta["lead.triggers.producers"])["gmail"]
    assert entry["next_at"] == rig.now + 240
    rig.now = entry["next_at"]
    rig.fake.routes["/profile"] = httpx.Response(429, headers={"Retry-After": "900"})
    await rig.runner.tick()
    entry = json.loads(rig.store.meta["lead.triggers.producers"])["gmail"]
    assert entry["last_error"] == "rate_limited" and entry["next_at"] == rig.now + 900
    # a later success clears the error
    rig.now = entry["next_at"]
    rig.fake.routes["/profile"] = ok({"historyId": "1"})
    await rig.runner.tick()
    [state] = await rig.runner.view()
    assert state["state"] == "polling" and state["last_error"] == ""


async def test_a_dead_token_is_reported_and_retried_slowly() -> None:
    rig = Rig()
    await rig.configure()
    rig.fake.routes["/profile"] = httpx.Response(401)

    async def refuse(observed: str | None) -> bool:
        return False

    rig.runner = ProducerRunner(
        rig.store, [GmailProducer(rig.fake.api("gmail", refresh=refuse))],
        settings=rig.service.settings, submit=rig._submit, clock=lambda: rig.now,
    )
    await rig.runner.tick()
    [state] = await rig.runner.view()
    assert state["state"] == "error" and state["last_error"] == "reconnect"


async def test_a_failed_submit_keeps_the_cursor_so_nothing_is_lost() -> None:
    rig = Rig()
    await rig.configure()
    await rig.runner.tick()
    rig.now += 200
    boom = {"on": True}
    real = rig._submit

    async def flaky(event: TriggerEvent) -> str:
        if boom["on"]:
            raise RuntimeError("store busy")
        return await real(event)

    rig.runner._submit = flaky
    await rig.runner.tick()
    assert (await rig.runner.view())[0]["state"] == "backoff"
    boom["on"] = False
    rig.now += 400
    await rig.runner.tick()
    assert (await rig.service.view())["counts"]["received"] == 1


# --------------------------------------------------- the lead's own address


def agent_event(sender: str, mid: str = "a1") -> TriggerEvent:
    return TriggerEvent(
        source="mail", scope=f"{AGENT_SCOPE_PREFIX}agent@mail.example", sender=sender,
        thread_key="t", summary="Book the flight", ids=(mid,),
    )


async def configured_service(**extra: Any) -> tuple[Rig, TriggerService]:
    rig = Rig()
    await rig.configure(
        agent_address="Agent@Mail.Example", self_senders=["me@x.com"],
        sources={"mail": {"mode": "explicit_only"}}, **extra,
    )
    return rig, rig.service


async def test_settings_normalize_the_agent_address_and_producers() -> None:
    settings = TriggerSettings.from_dict({
        "agent_address": " Agent@Mail.Example ", "poll_interval_s": 5,
        "producers": {"github": False, "nope": False}, "agent_senders": ["Me@X.com"]})
    assert settings.agent_address == "agent@mail.example" and settings.poll_interval_s == 60
    assert settings.producer_enabled("github") is False and settings.producer_enabled("gmail")
    assert settings.to_dict()["agent_senders"] == ["me@x.com"]
    assert TriggerSettings.from_dict({"agent_address": "not an address"}).agent_address == ""
    assert TriggerSettings.from_dict(settings.to_dict()) == settings


async def test_an_allow_listed_request_is_only_recorded_while_observing() -> None:
    rig, service = await configured_service()
    assert await service.submit_agent_mail(agent_event("me@x.com")) == "request"
    assert await service.submit_agent_mail(agent_event("me@x.com")) == "duplicate"
    view = await service.view()
    [entry] = view["log"]
    assert entry["policy_id"] == AGENT_MAIL_POLICY_ID and entry["outcome"] == "would_have"
    assert rig.started == [] and rig.seat_calls == 0


async def test_an_allow_listed_request_starts_a_job_in_auto_mode() -> None:
    rig, service = await configured_service(accept="auto")
    await service.submit_agent_mail(agent_event("me@x.com"))
    [(event, policy, _)] = rig.started
    assert event.sender == "me@x.com" and policy.id == AGENT_MAIL_POLICY_ID
    from dodaios.lead_triggers.wiring import job_prompt

    order = job_prompt(event, policy, "")
    assert "allow-listed" in order and "own address" in order and "EVENT_DATA" in order


async def test_mail_from_others_becomes_a_candidate_even_when_mail_is_explicit_only() -> None:
    rig, service = await configured_service()
    assert await service.submit_agent_mail(agent_event("stranger@evil.com")) == "candidate"
    counts = (await service.view())["counts"]
    assert counts["candidates"] == 1 and rig.started == []
    await rig.configure(agent_address="agent@mail.example", sources={"mail": {"mode": "ignore"}})
    assert await service.submit_agent_mail(agent_event("x@y.com", "a2")) == "ignored_source"


async def test_agent_mail_of_another_address_or_with_triggers_off_is_not_admitted() -> None:
    rig, service = await configured_service()
    other = TriggerEvent(source="mail", scope="agent:else@x.com", sender="me@x.com", ids=("z",))
    assert await service.submit_agent_mail(other) == "not_agent_mail"
    await rig.configure(accept="off", agent_address="agent@mail.example")
    assert await service.submit_agent_mail(agent_event("me@x.com", "a9")) == "off"


def test_source_rule_import_is_still_public() -> None:
    assert SourceRule().mode == "explicit_only"


def test_address_check_is_linear_and_strict() -> None:
    ok_ = TriggerSettings.from_dict({"agent_address": "a.b@mail.example.com"})
    assert ok_.agent_address == "a.b@mail.example.com"
    for bad in ("a@b", "a@@b.c", "@b.c", "a@b..c", "a@b.c.", "a b@c.d", "x" * 300 + "@a.b"):
        assert TriggerSettings.from_dict({"agent_address": bad}).agent_address == ""
    evil = "!" * 50_000 + "@" + "!" * 50_000
    assert TriggerSettings.from_dict({"agent_address": evil}).agent_address == ""
