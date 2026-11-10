"""A Live start the provider refused is classified, remembered and kept on the session."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from dodaios.brain import provider_health_ledger as ledger
from dodaios.brain import provider_test as pt
from dodaios.core.protocols import VoiceStartError
from dodaios.live.session import LiveVoiceSession
from dodaios.speech import provider_refusal as pr


@pytest.fixture
def fresh_ledger():
    store = ledger.ProviderHealthLedger(None)
    ledger.set_ledger(store)
    yield store
    ledger.set_ledger(None)


def _session(sent: list[dict]) -> LiveVoiceSession:
    session = LiveVoiceSession.__new__(LiveVoiceSession)
    session._provider = SimpleNamespace(name="openai-live")
    session._language = "en"

    async def send_json(message: dict) -> None:
        sent.append(message)

    session._send_json = send_json
    return session


def test_a_404_on_the_realtime_route_is_a_remembered_plan_refusal(fresh_ledger) -> None:
    sent: list[dict] = []
    session = _session(sent)
    error = VoiceStartError(
        "OpenAI Live session creation failed (HTTP 404, error).",
        user_message="Your plan does not offer it.",
        code="model_unavailable",
    )
    asyncio.run(session._announce_start_failure(error))
    assert session.start_refusal == pr.refusal_of_kind(pr.KIND_PLAN)
    outcome = fresh_ledger.get("openai-live", ledger.MODALITY_REALTIME)
    assert outcome is not None and outcome.status == pt.MODEL_UNAVAILABLE
    assert pr.fresh_refusal("openai-live") is not None
    # The spoken line says the account, not the weather, is the problem.
    (spoken,) = sent
    assert spoken["type"] == "error_spoken"
    assert "account" in spoken["text"]


def test_an_unclassified_failure_keeps_the_old_path(fresh_ledger) -> None:
    sent: list[dict] = []
    session = _session(sent)
    asyncio.run(session._announce_start_failure(RuntimeError("stream ended")))
    assert session.start_refusal is None
    assert fresh_ledger.get("openai-live", ledger.MODALITY_REALTIME) is None
    assert sent and sent[0]["type"] == "error_spoken"
