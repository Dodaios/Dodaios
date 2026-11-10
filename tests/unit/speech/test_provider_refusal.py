"""A realtime provider that said no: classified, remembered, worded, announced."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from dodaios.brain import provider_health_ledger as ledger
from dodaios.brain import provider_test as pt
from dodaios.core.protocols import VoiceStartError
from dodaios.speech import provider_refusal as pr


@pytest.fixture
def fresh_ledger():
    store = ledger.ProviderHealthLedger(None)
    ledger.set_ledger(store)
    yield store
    ledger.set_ledger(None)


@pytest.mark.parametrize(
    ("code", "kind", "status"),
    [
        ("model_unavailable", pr.KIND_PLAN, pt.MODEL_UNAVAILABLE),
        ("access_denied", pr.KIND_PLAN, pt.MODEL_UNAVAILABLE),
        ("voice_not_offered", pr.KIND_PLAN, pt.MODEL_UNAVAILABLE),
        ("bad_key", pr.KIND_KEY, pt.BAD_KEY),
        ("no_credits", pr.KIND_CREDIT, pt.NO_CREDITS),
        ("rate_limited", pr.KIND_BUSY, pt.RATE_LIMITED),
        ("invalid_configuration", pr.KIND_REJECTED, ""),
    ],
)
def test_authored_code_wins(code: str, kind: str, status: str) -> None:
    error = VoiceStartError(
        "Live session creation failed (HTTP 404, error).", user_message="x", code=code
    )
    refusal = pr.describe(error)
    assert refusal is not None
    assert (refusal.kind, refusal.status) == (kind, status)


def test_code_is_found_through_the_exception_chain() -> None:
    inner = VoiceStartError("refused", user_message="x", code="no_credits")
    try:
        raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert pr.describe(outer) == pr.refusal_of_kind(pr.KIND_CREDIT)


def test_http_404_on_the_route_is_a_plan_refusal_even_without_a_model_word() -> None:
    # The live incident (2026-11-10): the body never said "model", the ledger's
    # strict classifier answered a bare error and nothing was remembered.
    refusal = pr.describe(RuntimeError("Live session creation failed (HTTP 404, error)."))
    assert refusal is not None
    assert refusal.kind == pr.KIND_PLAN
    assert not refusal.waiting_helps


def test_http_401_and_422_text() -> None:
    assert pr.describe("HTTP 401 unauthorized").kind == pr.KIND_KEY
    assert pr.describe("HTTP 422 bad voice").kind == pr.KIND_REJECTED


def test_ordinary_failures_are_not_refusals() -> None:
    assert pr.describe(RuntimeError("stream ended")) is None
    assert pr.describe(None) is None
    assert pr.describe("") is None


def test_only_a_definitive_usage_billed_refusal_overrides_the_fallback_block() -> None:
    from dodaios.plugins.realtime.openai_subscription_live import SubscriptionLiveError

    assert pr.refusal_of_kind(pr.KIND_PLAN).overrides_fallback_block
    assert pr.refusal_of_kind(pr.KIND_KEY).overrides_fallback_block
    assert not pr.refusal_of_kind(pr.KIND_BUSY).overrides_fallback_block
    assert not pr.refusal_of_kind(pr.KIND_UNREACHABLE).overrides_fallback_block
    # A subscription that refused keeps the rule it was pinned for (#828).
    refusal = pr.describe(SubscriptionLiveError("voice_not_offered", plan="free"))
    assert refusal is not None and refusal.kind == pr.KIND_PLAN
    assert refusal.subscription and not refusal.overrides_fallback_block
    try:
        raise RuntimeError("wrapper") from SubscriptionLiveError("quota_exhausted")
    except RuntimeError as wrapped:
        assert pr.describe(wrapped).subscription


def test_transient_kinds_say_waiting_helps() -> None:
    assert pr.refusal_of_kind(pr.KIND_BUSY).waiting_helps
    assert pr.refusal_of_kind(pr.KIND_UNREACHABLE).waiting_helps
    assert not pr.refusal_of_kind(pr.KIND_KEY).waiting_helps


def test_a_plan_refusal_keeps_the_provider_out_until_its_window_passes(fresh_ledger) -> None:
    pr.remember("dead-voice", pr.refusal_of_kind(pr.KIND_PLAN))
    assert pr.fresh_refusal("dead-voice").kind == pr.KIND_PLAN
    # Waiting cannot fix a plan: the next call does not spend 12 s on it again.
    assert pr.order_by_health(["dead-voice", "other-voice"]) == ["other-voice"]
    assert pr.order_by_health(["dead-voice"]) == []
    # Two hours later the plan may have changed: the provider is tried again.
    at = fresh_ledger.get("dead-voice", ledger.MODALITY_REALTIME).at
    later = at + pr.SKIP_FOR_S[pr.KIND_PLAN] + 1
    assert pr.fresh_refusal("dead-voice", now=later) is None


def test_a_busy_provider_is_only_demoted(fresh_ledger) -> None:
    pr.remember("slow-voice", pr.refusal_of_kind(pr.KIND_BUSY))
    assert pr.order_by_health(["slow-voice", "other-voice"]) == ["other-voice", "slow-voice"]
    assert pr.order_by_health(["slow-voice"]) == ["slow-voice"]


def test_a_rejected_settings_refusal_leaves_no_ledger_entry(fresh_ledger) -> None:
    pr.remember("picky", pr.refusal_of_kind(pr.KIND_REJECTED))
    assert fresh_ledger.get("picky", ledger.MODALITY_REALTIME) is None
    assert pr.fresh_refusal("picky") is None


def test_nothing_remembered_keeps_the_order(fresh_ledger) -> None:
    assert pr.order_by_health(["a", "b"]) == ["a", "b"]
    assert pr.fresh_refusal("") is None


def test_sentences_name_the_provider_and_what_happens_next() -> None:
    plan = pr.refusal_of_kind(pr.KIND_PLAN)
    en = pr.sentence(
        plan, provider="openai-live", language="en", continued_on=pr.CONTINUED_PIPELINE
    )
    assert "openai live" in en
    assert "plan" in en
    assert "classic voice path" in en
    de = pr.sentence(plan, provider="openai-live", language="de")
    assert "Tarif" in de
    assert "kann gerade nicht weitergehen" in de  # i18n-allow: the German catalog line
    es = pr.sentence(pr.refusal_of_kind(pr.KIND_CREDIT), provider="x", language="es",
                     continued_on=pr.CONTINUED_REALTIME)
    assert "crédito" in es and "otra conexión" in es
    pt_text = pr.sentence(pr.refusal_of_kind(pr.KIND_KEY), provider="x", language="pt")
    assert "chave" in pt_text


def test_unknown_kind_falls_back_to_rejected_wording() -> None:
    text = pr.sentence(pr.Refusal(kind="weird"), provider="p", language="en")
    assert "rejected the voice settings" in text


class _Bus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


class _Svc:
    def __init__(self) -> None:
        self.notices: list[tuple[str, dict]] = []

    async def post_notice(self, session_id: str, payload: dict) -> None:
        self.notices.append((session_id, payload))


def test_announce_publishes_the_event_and_posts_a_lead_notice(monkeypatch) -> None:
    svc = _Svc()

    class _Runtime:
        def chat_service(self):
            return svc

    class _Session:
        session_id = "lead-1"

    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: _Runtime())
    monkeypatch.setattr(
        "dodaios.agent_chat.lead.lead_session", lambda _svc, create=True: _Session()
    )
    bus = _Bus()
    text = asyncio.run(
        pr.announce(
            bus,
            session_id="call-9",
            provider="openai-live",
            refusal=pr.refusal_of_kind(pr.KIND_PLAN),
            language="en",
            continued_on=pr.CONTINUED_PIPELINE,
        )
    )
    from dodaios.core.events import VoiceProviderRefused

    (event,) = bus.events
    assert isinstance(event, VoiceProviderRefused)
    assert event.session_id == "call-9"
    assert event.provider == "openai-live"
    assert event.kind == pr.KIND_PLAN
    assert event.continued_on == "pipeline"
    assert event.message == text
    ((session_id, payload),) = svc.notices
    assert session_id == "lead-1"
    assert payload["kind"] == "voice_provider_refused"
    assert payload["text"] == text
    assert payload["continued_on"] == "pipeline"


def test_announce_never_raises_without_a_society_or_bus(monkeypatch) -> None:
    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: None)
    text = asyncio.run(
        pr.announce(None, session_id="s", provider="p", refusal=pr.refusal_of_kind(pr.KIND_BUSY),
                    language="de")
    )
    assert "ausgelastet" in text
