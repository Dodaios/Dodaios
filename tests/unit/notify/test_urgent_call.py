"""Call me for urgent decisions: opt-in, narrow, and silent otherwise."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from dodaios.notify import urgent_call as uc
from dodaios.notify.settings import NotifySettings, UrgentCallSettings
from dodaios.notify.urgent_call import CallLedger, UrgentCaller, UrgentEvent
from dodaios.telephony import decision_calls
from tests.fakes.fake_telephony_stack import FakeBrain, FakeSTT, FakeTTS

NOON = datetime(2026, 11, 11, 12, 0)
NOW_MS = int(NOON.timestamp() * 1000)
PCM = b"\x00\x00" * 160


def _settings(**urgent) -> NotifySettings:
    base = {"enabled": True, "escalate_after_min": 0, "route": "desktop"}
    base.update(urgent)
    return NotifySettings.from_dict({"urgent_call": base})


class Rig:
    """A caller whose two rings and its card state are fakes."""

    def __init__(self, settings: NotifySettings, *, open_: bool = True, allowed: bool = True):
        self.settings = settings
        self.open = open_
        self.allowed = allowed
        self.rings: list[tuple[str, str, str]] = []
        self.slept: list[float] = []
        self.clock = NOON

        async def desktop(event, target):
            self.rings.append(("desktop", event.ref_id, target))
            return True

        async def phone(event, target):
            self.rings.append(("phone", event.ref_id, target))
            return True

        async def sleep(seconds):
            self.slept.append(seconds)

        self.caller = UrgentCaller(
            ring_desktop=desktop,
            ring_phone=phone,
            is_open=lambda _e: self.open,
            phone_allowed=lambda: self.allowed,
            settings=lambda: self.settings,
            clock=lambda: self.clock,
            sleep=sleep,
        )


def _approval(ref="a1", **kw) -> UrgentEvent:
    return UrgentEvent(kind="approval", ref_id=ref, session_id="s1", summary="send the mail", **kw)


@pytest.fixture(autouse=True)
def _clean_registry():
    decision_calls.clear()
    yield
    decision_calls.clear()


async def test_default_settings_are_off_and_nothing_rings():
    assert NotifySettings().urgent_call.enabled is False
    rig = Rig(NotifySettings())
    for event in (
        _approval(urgent=True),
        UrgentEvent(kind="question", ref_id="q", urgent=True, recommended="yes"),
        UrgentEvent(kind="watchdog", ref_id="w", severity="critical"),
    ):
        assert await rig.caller.handle(event) == uc.OFF
    assert rig.rings == []


async def test_listener_with_setting_off_schedules_nothing():
    rig = Rig(NotifySettings())
    rig.caller.on_chat_event(
        "s1", {"kind": "approval_required", "payload": {"approval_id": "a1", "urgent": True}}
    )
    await asyncio.sleep(0)
    assert rig.rings == [] and rig.caller._tasks == {}


async def test_non_qualifying_events_never_ring():
    rig = Rig(_settings(keywords=["wire transfer"], deadline_min=10))
    far_deadline = _approval("a2", deadline_ms=NOW_MS + 3_600_000)
    expired = _approval("a3", deadline_ms=NOW_MS - 1000)
    watch_minor = UrgentEvent(kind="watchdog", ref_id="w", severity="warning")
    for event in (_approval(), far_deadline, expired, watch_minor):
        assert await rig.caller.handle(event) == uc.NOT_URGENT
    assert rig.rings == []


async def test_each_qualifying_rule_rings():
    rig = Rig(_settings(keywords=["wire transfer"], deadline_min=10, max_per_day=10))
    assert await rig.caller.handle(_approval("a1", urgent=True)) == uc.RANG
    keyword = UrgentEvent(kind="approval", ref_id="a2", summary="Approve WIRE TRANSFER of 5k")
    assert await rig.caller.handle(keyword) == uc.RANG
    soon = _approval("a3", deadline_ms=NOW_MS + 5 * 60_000)
    assert await rig.caller.handle(soon) == uc.RANG
    critical = UrgentEvent(kind="watchdog", ref_id="w", severity="critical")
    assert await rig.caller.handle(critical) == uc.RANG
    assert [r[1] for r in rig.rings] == ["a1", "a2", "a3", "w"]


async def test_event_kind_switches_are_respected():
    rig = Rig(_settings(events={"approval": False, "question": True, "watchdog": False}))
    assert await rig.caller.handle(_approval(urgent=True)) == uc.NOT_URGENT
    q = UrgentEvent(kind="question", ref_id="q", urgent=True, recommended="x")
    assert await rig.caller.handle(q) == uc.RANG
    w = UrgentEvent(kind="watchdog", ref_id="w", severity="critical")
    assert await rig.caller.handle(w) == uc.NOT_URGENT


async def test_quiet_hours_hold_the_call():
    settings = NotifySettings.from_dict(
        {
            "quiet_hours": {"enabled": True, "start": "11:00", "end": "13:00"},
            "urgent_call": {"enabled": True, "escalate_after_min": 0},
        }
    )
    rig = Rig(settings)
    assert await rig.caller.handle(_approval(urgent=True)) == uc.QUIET
    assert rig.rings == []


async def test_daily_cap_holds_the_call():
    rig = Rig(_settings(max_per_day=2))
    outcomes = [await rig.caller.handle(_approval(f"a{i}", urgent=True)) for i in range(3)]
    assert outcomes == [uc.RANG, uc.RANG, uc.CAPPED]
    rig.clock = datetime(2026, 11, 12, 9, 0)  # the next day starts fresh
    assert await rig.caller.handle(_approval("a9", urgent=True)) == uc.RANG


def test_ledger_survives_a_restart(tmp_path):
    ledger = CallLedger(tmp_path / "n" / "calls.json")
    ledger.add("2026-11-11")
    assert CallLedger(tmp_path / "n" / "calls.json").count("2026-11-11") == 1


async def test_text_goes_first_and_an_answered_decision_never_rings():
    rig = Rig(_settings(escalate_after_min=5))
    rig.open = False  # the owner answered by text during the grace
    assert await rig.caller.handle(_approval(urgent=True)) == uc.RESOLVED
    assert rig.slept == [300.0]
    assert rig.rings == []


async def test_still_open_after_the_grace_rings_once():
    rig = Rig(_settings(escalate_after_min=5))
    event = _approval(urgent=True)
    assert await rig.caller.handle(event) == uc.RANG
    assert await rig.caller.handle(event) == uc.DUPLICATE
    assert len(rig.rings) == 1


async def test_switching_off_during_the_grace_cancels_the_call():
    rig = Rig(_settings(escalate_after_min=5))

    async def switch_off(seconds):
        rig.settings = NotifySettings()

    rig.caller._sleep = switch_off
    assert await rig.caller.handle(_approval(urgent=True)) == uc.OFF
    assert rig.rings == []


async def test_resolved_event_cancels_the_waiting_call():
    rig = Rig(_settings(escalate_after_min=5))
    gate = asyncio.Event()

    async def slow(seconds):
        await gate.wait()

    rig.caller._sleep = slow
    rig.caller.on_chat_event(
        "s1", {"kind": "approval_required", "payload": {"approval_id": "a1", "urgent": True}}
    )
    await asyncio.sleep(0)
    assert "a1" in rig.caller._tasks
    rig.caller.on_chat_event("s1", {"kind": "approval_resolved", "payload": {"approval_id": "a1"}})
    await asyncio.sleep(0)
    assert rig.rings == [] and rig.caller._tasks == {}


async def test_phone_route_needs_number_and_policy():
    rig = Rig(_settings(route="phone"))
    assert await rig.caller.handle(_approval("a1", urgent=True)) == uc.NO_NUMBER
    rig.settings = _settings(route="phone", phone_number="+4915112345678")
    rig.allowed = False  # a key-billed voice seat while a subscription is connected
    assert await rig.caller.handle(_approval("a2", urgent=True)) == uc.TEXT_ONLY
    assert rig.rings == []
    rig.allowed = True
    assert await rig.caller.handle(_approval("a3", urgent=True)) == uc.RANG
    assert rig.rings == [("phone", "a3", "+4915112345678")]


def test_settings_validate_and_clamp():
    s = UrgentCallSettings.from_dict(
        {
            "enabled": "yes",
            "route": "carrier-pigeon",
            "phone_number": "0151",
            "max_per_day": 999,
            "deadline_min": -4,
            "keywords": ["  Wire  Transfer ", "wire transfer", ""],
        }
    )
    assert s.enabled is False  # only a real true switches it on
    assert (s.route, s.phone_number, s.max_per_day, s.deadline_min) == ("desktop", "", 20, 0)
    assert s.keywords == ("wire transfer",)


def test_patch_merges_nested_events():
    s = NotifySettings().patched({"urgent_call": {"enabled": True, "events": {"watchdog": False}}})
    assert s.urgent_call.enabled is True
    assert s.urgent_call.events == {"approval": True, "question": True, "watchdog": False}
    assert NotifySettings.from_dict(s.to_dict()) == s


def test_event_from_chat_reads_the_preview_and_the_card():
    event = uc.event_from_chat(
        "s1",
        {
            "kind": "approval_required",
            "payload": {
                "approval_id": "a1",
                "name": "send_mail",
                "summary": "long",
                "preview": {"compact": "Mail to Ann: invoice"},
                "urgent": True,
            },
        },
    )
    assert event is not None and event.summary == "Mail to Ann: invoice" and event.urgent
    question = uc.event_from_chat(
        "s1",
        {
            "kind": "question_required",
            "payload": {
                "question_id": "q1",
                "questions": [{"question": "Ship it?", "options": [{"label": "Ship"}]}],
            },
        },
    )
    assert question is not None and question.recommended == "Ship" and question.accepts_yes
    assert uc.event_from_chat("s1", {"kind": "turn_started", "payload": {}}) is None


def test_opening_says_the_exact_action_and_how_to_answer():
    text = uc.opening_for(_approval(), "Atlas")
    assert "Atlas" in text and "send the mail" in text and "yes" in text and "later" in text


# ------------------------------------------------- the call itself (phone)


class FakeService:
    def __init__(self):
        self.approvals: list[tuple] = []
        self.questions: list[tuple] = []

    def resolve_approval(self, session_id, approval_id, decision):
        self.approvals.append((session_id, approval_id, decision))
        return True

    def resolve_question(self, session_id, question_id, *, index=0, option_index=None, **_):
        self.questions.append((session_id, question_id, option_index))
        return True


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("yes please", "yes"),
        ("Ja, mach das", "yes"),  # i18n-allow: spoken German answer
        ("no", "no"),
        ("Nein danke", "no"),  # i18n-allow: spoken German answer
        ("später", "later"),  # i18n-allow: spoken German answer
        ("not now", "later"),
        ("no, do it tomorrow", "no"),
        ("hmm what", None),
        ("", None),
    ],
)
def test_classify_answer(said, expected):
    assert decision_calls.classify_answer(said) == expected


def _session(stt_lines, call):
    from dodaios.telephony.session import TelephonyCallSession

    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    session = TelephonyCallSession(
        call_sid="CAdecision",
        stream_sid="MZ",
        send=send,
        stt=FakeSTT(stt_lines),
        brain=FakeBrain("the brain must not answer"),
        tts=FakeTTS(ms_per_char=1),
        language_code="en-US",
    )
    decision_calls.register("CAdecision", call)
    return session


@pytest.mark.parametrize(("answer", "decision"), [("Yes, go ahead", "allow"), ("No", "deny")])
async def test_spoken_answer_settles_the_approval_card_and_ends_the_call(answer, decision):
    from dodaios.notify.urgent_ring import decision_for

    service = FakeService()
    session = _session([answer], decision_for(service, _approval("a1")))
    await session._run_turn(PCM)
    assert service.approvals == [("s1", "a1", decision)]
    assert session.ended and session.end_reason.startswith("decision_")
    assert decision_calls.get("CAdecision") is None


async def test_later_and_unclear_answers_leave_the_card_open():
    from dodaios.notify.urgent_ring import decision_for

    service = FakeService()
    session = _session(["later"], decision_for(service, _approval("a1")))
    await session._run_turn(PCM)
    assert service.approvals == [] and session.ended

    decision_calls.clear()
    session = _session(["blorp", "blorp"], decision_for(service, _approval("a2")))
    await session._run_turn(PCM)
    assert not session.ended  # asked once more
    await session._run_turn(PCM)
    assert service.approvals == [] and session.ended


async def test_yes_to_a_question_needs_a_recommended_answer():
    from dodaios.notify.urgent_ring import decision_for

    service = FakeService()
    asked = UrgentEvent(
        kind="question", ref_id="q1", session_id="s1", summary="Ship?", recommended="Ship"
    )
    session = _session(["yes"], decision_for(service, asked))
    await session._run_turn(PCM)
    assert service.questions == [("s1", "q1", 0)]

    decision_calls.clear()
    open_ended = UrgentEvent(kind="question", ref_id="q2", session_id="s1", summary="Which name?")
    session = _session(["yes"], decision_for(service, open_ended))
    await session._run_turn(PCM)
    assert service.questions == [("s1", "q1", 0)]  # nothing guessed


async def test_phone_ringer_places_the_call_with_the_opening_and_registers_it(monkeypatch):
    from dodaios.notify import urgent_ring

    placed: dict = {}

    def fake_place_call(**kw):
        placed.update(kw)
        return "CAplaced"

    monkeypatch.setattr(
        "dodaios.plugins.tool.call_contact._default_call_config",
        lambda: {
            "account_sid": "AC1",
            "auth_token": "t",
            "from_number": "+4930111",
            "public_base_url": "https://x.example",
        },
    )
    monkeypatch.setattr("dodaios.telephony.outbound.place_call", fake_place_call)
    ring = urgent_ring.phone_ringer(FakeService())
    assert await ring(_approval("a1"), "+4915112345678") is True
    assert placed["to"] == "+4915112345678" and "send the mail" in placed["opening"]
    assert decision_calls.get("CAplaced") is not None


async def test_phone_ringer_without_telephony_does_not_call(monkeypatch):
    from dodaios.notify import urgent_ring

    monkeypatch.setattr("dodaios.plugins.tool.call_contact._default_call_config", lambda: None)
    assert await urgent_ring.phone_ringer(FakeService())(_approval(), "+4915112345678") is False
