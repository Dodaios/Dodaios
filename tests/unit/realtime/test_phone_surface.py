"""The phone surface of the realtime session factory.

A phone line carries plain PCM. A provider that needs a browser's WebRTC offer
cannot hold a call, so the factory leaves it out for ``surface="phone"``; when
nothing else is left there is no session, and the call is refused upstream.
The call's brief reaches the session that is built.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.realtime import factory
from dodaios.realtime.protocol import PHONE_SURFACE, serves_phone


class _WebRtcProvider:
    name = "webrtc-only"
    requires_webrtc_offer = True
    continuous_conversation = True


class _PcmProvider:
    name = "pcm-native"
    native_tool_orchestration = True
    input_sample_rate = 16_000
    output_sample_rate = 24_000


def _cfg() -> Any:
    return SimpleNamespace(
        brain=SimpleNamespace(reply_language="auto", providers={}, realtime=None),
        voice=SimpleNamespace(realtime_tool_declaration_budget_tokens=0),
    )


def _build(**kwargs: Any) -> Any:
    async def _noop(*_args: Any) -> None:
        return None

    return factory.build_realtime_session(
        cfg=_cfg(), bus=None, session_id="s", send_binary=_noop, send_json=_noop, **kwargs
    )


def test_serves_phone_is_the_webrtc_capability():
    assert serves_phone(_PcmProvider()) is True
    assert serves_phone(_WebRtcProvider()) is False


def test_phone_surface_skips_a_provider_that_needs_a_browser(monkeypatch):
    monkeypatch.setattr(
        factory, "_provider_candidates", lambda *_a, **_k: [_WebRtcProvider(), _PcmProvider()]
    )
    session = _build(surface=PHONE_SURFACE, call_brief="PHONE CALL. brief")
    assert type(session).__name__ == "NativeLiveVoiceSession"
    assert session.active_provider == "pcm-native"
    assert session.surface == PHONE_SURFACE
    assert session._call_brief == "PHONE CALL. brief"
    assert factory.realtime_phone_ready(_cfg()) is True


def test_no_phone_capable_provider_means_no_session(monkeypatch):
    monkeypatch.setattr(factory, "_provider_candidates", lambda *_a, **_k: [_WebRtcProvider()])
    assert _build(surface=PHONE_SURFACE) is None
    assert factory.realtime_phone_ready(_cfg()) is False


def test_the_browser_surface_keeps_the_webrtc_provider(monkeypatch):
    monkeypatch.setattr(factory, "_provider_candidates", lambda *_a, **_k: [_WebRtcProvider()])
    session = _build(surface="browser")
    assert session is not None
    assert type(session).__name__ == "LiveVoiceSession"


@pytest.mark.parametrize("failure", [RuntimeError("registry broke")])
def test_a_failed_readiness_probe_reads_as_not_ready(monkeypatch, failure):
    def boom(*_a: Any, **_k: Any) -> list[Any]:
        raise failure

    monkeypatch.setattr(factory, "_provider_candidates", boom)
    assert factory.realtime_phone_ready(_cfg()) is False
