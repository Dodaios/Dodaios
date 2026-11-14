"""An aborted ElevenLabs stream must not leak tasks or keep paying for audio.

The SDK producer used to schedule one unawaited ``queue.put`` per chunk. Once
playback was cancelled the full queue left the rest pending forever, and they
surfaced as ~100 "Task was destroyed but it is pending!" per cancelled turn.
"""
from __future__ import annotations

import asyncio
import gc
import sys
import threading
import time
import types
from typing import Any

import pytest

from dodaios.plugins.tts.elevenlabs_tts import ElevenLabsTTS

_CHUNKS = 400


class _Stream:
    """Iterator standing in for the SDK's HTTP stream."""

    def __init__(self) -> None:
        self.pulled = 0
        self.closed = threading.Event()

    def __iter__(self) -> _Stream:
        return self

    def __next__(self) -> bytes:
        if self.pulled >= _CHUNKS:
            raise StopIteration
        self.pulled += 1
        return b"\x00\x00" * 32

    def close(self) -> None:
        self.closed.set()


@pytest.fixture
def stream(monkeypatch: pytest.MonkeyPatch) -> _Stream:
    fake_sdk = types.ModuleType("elevenlabs")
    fake_sdk.VoiceSettings = lambda **_kw: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "elevenlabs", fake_sdk)
    return _Stream()


def _provider(stream: _Stream) -> ElevenLabsTTS:
    tts = ElevenLabsTTS.__new__(ElevenLabsTTS)
    tts._client = types.SimpleNamespace(
        text_to_speech=types.SimpleNamespace(stream=lambda **_kw: stream)
    )
    tts._model = "eleven_flash_v2_5"
    tts._language_code = "en-US"
    for name, value in (
        ("_stability", 0.5), ("_similarity_boost", 0.75), ("_style", 0.0), ("_speed", 1.0),
    ):
        setattr(tts, name, value)
    return tts


async def _wait_until(predicate: Any, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert predicate()


@pytest.mark.asyncio
async def test_abandoned_stream_stops_the_producer_without_leaking(stream: _Stream) -> None:
    errors: list[dict] = []
    asyncio.get_running_loop().set_exception_handler(lambda _l, ctx: errors.append(ctx))
    baseline = asyncio.all_tasks()

    gen = _provider(stream)._stream_pcm("voice", "hello", None)
    assert await gen.__anext__()
    await gen.aclose()

    await _wait_until(stream.closed.is_set)
    await _wait_until(lambda: not (asyncio.all_tasks() - baseline))
    assert stream.pulled < _CHUNKS, "the producer must stop reading the HTTP stream"
    gc.collect()
    await asyncio.sleep(0)
    assert errors == []


@pytest.mark.asyncio
async def test_full_stream_is_delivered_in_order(stream: _Stream) -> None:
    received = [c async for c in _provider(stream)._stream_pcm("voice", "hello", None)]
    assert len(received) == _CHUNKS


@pytest.mark.asyncio
async def test_sdk_error_reaches_the_consumer(stream: _Stream) -> None:
    def _fail(**_kw: Any) -> Any:
        raise RuntimeError("boom")

    tts = _provider(stream)
    tts._client.text_to_speech.stream = _fail
    with pytest.raises(RuntimeError, match="boom"):
        async for _chunk in tts._stream_pcm("voice", "hello", None):
            pass
