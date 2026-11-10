"""Warming the next call when the person reaches for the button (issue #154)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from dodaios.speech import call_warmup


class _Tts:
    def __init__(self) -> None:
        self.warmed = 0

    def _ensure_client(self) -> None:
        self.warmed += 1


class _Stt:
    def __init__(self) -> None:
        self.warmed = 0

    def warm_up(self) -> None:
        self.warmed += 1


def test_warm_runs_every_step_alone_and_reports(monkeypatch) -> None:
    monkeypatch.setattr(call_warmup, "_warm_imports", lambda: None)
    def broken() -> None:
        raise RuntimeError("no onnx")

    monkeypatch.setattr(call_warmup, "_warm_barge_detector", broken)

    async def no_transport(cfg):
        return None

    monkeypatch.setattr(
        "dodaios.realtime.factory.realtime_warm_selected_transports", no_transport, raising=False
    )
    pipeline = SimpleNamespace(_tts=_Tts(), _utterance_stt=_Stt())
    done = asyncio.run(call_warmup.CallWarmer().warm(pipeline, SimpleNamespace()))
    assert done["imports"] is True
    assert done["barge_detector"] is False  # failed alone, nothing else stopped
    assert done["tts"] is True and pipeline._tts.warmed == 1
    assert done["stt"] is True and pipeline._utterance_stt.warmed == 1
    assert done["transports"] is True


def test_without_a_pipeline_only_the_shared_parts_warm(monkeypatch) -> None:
    monkeypatch.setattr(call_warmup, "_warm_imports", lambda: None)
    monkeypatch.setattr(call_warmup, "_warm_barge_detector", lambda: None)
    done = asyncio.run(call_warmup.CallWarmer().warm(None, None))
    assert "tts" not in done and "stt" not in done
    assert done["transports"] is False


def test_kick_is_debounced_and_runs_in_the_background(monkeypatch) -> None:
    runs: list[int] = []

    async def fake_warm(self, pipeline, config):
        runs.append(1)
        return {}

    monkeypatch.setattr(call_warmup.CallWarmer, "warm", fake_warm)
    now = [100.0]
    warmer = call_warmup.CallWarmer(min_interval_s=30.0, clock=lambda: now[0])

    async def scenario() -> list[bool]:
        first = await warmer.kick(None, None)
        second = await warmer.kick(None, None)  # same moment: one warm
        await asyncio.sleep(0)
        now[0] += 10.0
        third = await warmer.kick(None, None)  # inside the window: still one
        now[0] += 31.0
        fourth = await warmer.kick(None, None)  # window passed: a new warm
        await asyncio.sleep(0)
        return [first, second, third, fourth]

    assert asyncio.run(scenario()) == [True, False, False, True]
    assert len(runs) == 2


def test_process_wide_warmer_can_be_replaced_for_tests() -> None:
    marker = call_warmup.CallWarmer()
    call_warmup.set_call_warmer(marker)
    try:
        assert call_warmup.call_warmer() is marker
    finally:
        call_warmup.set_call_warmer(None)
    assert call_warmup.call_warmer() is not marker
