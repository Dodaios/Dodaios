#!/usr/bin/env python
"""Dictation replay benchmark: end of speech -> text delivered, through the real Take.

What it measures
----------------
Synthetic recordings (three short machine-voice clips in ``scripts/bench/data``,
joined with silences into cases of 1 to 22 seconds) are fed block by block into
the real :class:`dodaios.dictation.take.Take`, at microphone pace, exactly as
the dictation path does. ``Take.finish()`` reports ``wait_after_stop_ms``: the
time between the stop and the finished text. That is the number the person
feels as "dictation lag", and it is what a refactor of the take, the speech map
or the read-ahead must not make worse.

Two engines:

* ``--engine sim`` (default, headless, no model): the recognizer is a stand-in
  whose decode time follows a fixed latency model (decode seconds as a function
  of clip length, measured once on the reference machine). Time is a virtual
  clock, so the result depends on the take's own scheduling only and is
  repeatable. This is the regression guard.
* ``--engine real``: the on-device recognizer (``LocalFinalSTT``) in real time.
  Needs the local Whisper model files and a few CPU cores; numbers move with
  machine load, so compare only runs on the same quiet machine.

Usage:
    python scripts/bench/dictation_replay.py [--engine sim|real] [--json out.json]
        [--budget-ms N]    # sim only: exit 1 when the worst case exceeds N

Exit codes: 0 ok, 1 budget exceeded or a case produced no text, 78 skipped
(real engine unavailable).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DATA = Path(__file__).resolve().parent / "data"
SAMPLE_RATE = 16_000
BLOCK = 3200  # 100 ms: the microphone block size of the dictation path
#: Decode seconds as a function of clip seconds (on-device model, language
#: pinned, reference machine). Linear interpolation between the points.
LATENCY_MODEL = ((1.25, 0.162), (4, 0.196), (10, 0.318), (20, 0.462), (30, 0.837))
DEFAULT_BUDGET_MS = 1500


def _clip(index: int) -> bytes:
    with wave.open(str(DATA / f"dictation_synthetic_{index}.wav")) as wav:
        return wav.readframes(wav.getnframes())


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


def cases() -> list[tuple[str, bytes]]:
    c1, c2, c3 = _clip(1), _clip(2), _clip(3)
    pause = _silence(0.8)
    tail = _silence(0.1)  # released right after the last sound
    medium = pause.join([c1, c2, c3])
    long_ = pause.join([c1, c2, c3] * 5)
    # Released 0.5 s into the words that follow a pause: the moment a reading
    # started at that pause is most likely still running.
    mid_word = c1 + pause + c2[: int(SAMPLE_RATE * 0.5) * 2]
    return [
        ("short_1s", c1 + tail),
        ("medium_5s", medium + tail),
        ("long_31s", long_ + tail),
        ("mid_word_3s", mid_word),
    ]


def model_latency(clip_s: float) -> float:
    pts = LATENCY_MODEL
    if clip_s <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if clip_s <= x1:
            return y0 + (clip_s - x0) * (y1 - y0) / (x1 - x0)
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    return y1 + (clip_s - x1) * (y1 - y0) / (x1 - x0)


class _VirtualLoop(asyncio.SelectorEventLoop):
    """An event loop whose clock jumps to the next timer instead of waiting."""

    def __init__(self) -> None:
        super().__init__()
        self._vt = 0.0

    def time(self) -> float:
        return self._vt

    def _run_once(self) -> None:
        if not self._ready and self._scheduled:
            self._vt = max(self._vt, self._scheduled[0]._when)
        super()._run_once()


class _SimSTT:
    """Stand-in recognizer: filler words per clip, after the modelled decode time."""

    takes_context = True

    def __init__(self) -> None:
        self.calls = 0

    async def transcribe_pcm(self, pcm: bytes, language: str | None = None, context: str = ""):
        self.calls += 1
        clip_s = len(pcm) / (SAMPLE_RATE * 2)
        await asyncio.sleep(model_latency(clip_s))
        words = max(2, int(clip_s / 0.45))
        text = " ".join(["word"] * (words - 1) + ["end."])
        return SimpleNamespace(
            text=text,
            raw_text=text,
            language=language if language and language != "auto" else "en",
            confidence=1.0,
            segments=({"start": 0.0, "end": clip_s, "text": text},),
        )


def _row(name: str, result) -> dict:
    return {
        "name": name,
        "duration_s": round(result.duration_s, 1),
        "speech_s": round(result.speech_s, 1),
        "wait_ms": result.wait_after_stop_ms,
        "calls": result.calls,
        "pieces": result.pieces,
        "reads_ahead": getattr(result, "reads_ahead", 0),
        "reads_ahead_kept": getattr(result, "reads_ahead_kept", 0),
        "chars": len(result.text),
        "error": result.error,
    }


def run_sim() -> list[dict]:
    from dodaios.dictation import take as take_mod

    rows = []
    real_time = take_mod.time
    try:
        for name, pcm in cases():
            loop = _VirtualLoop()
            asyncio.set_event_loop(loop)
            take_mod.time = SimpleNamespace(
                perf_counter=loop.time, monotonic=loop.time, time=time.time
            )

            async def one(pcm: bytes = pcm):
                stt = _SimSTT()
                rec = [take_mod.Recognizer(id="sim", provider=stt, model="sim", on_device=True)]
                take = take_mod.Take(rec, language="auto", language_hint="en")
                for off in range(0, len(pcm), BLOCK):
                    take.feed(pcm[off : off + BLOCK])
                    await asyncio.sleep(BLOCK / (SAMPLE_RATE * 2))
                return await take.finish()

            try:
                rows.append(_row(name, loop.run_until_complete(one())))
            finally:
                loop.close()
    finally:
        take_mod.time = real_time
        asyncio.set_event_loop(None)
    return rows


async def _run_real() -> list[dict]:
    from dodaios.dictation.local_final import LocalFinalSTT
    from dodaios.dictation.take import Recognizer, Take

    provider = LocalFinalSTT("large-v3-turbo")
    await asyncio.to_thread(provider.warm_up)
    await provider.transcribe_pcm(b"\x00\x00" * SAMPLE_RATE, language="en")
    recognizers = [
        Recognizer(id="faster-whisper", provider=provider, model="large-v3-turbo", on_device=True)
    ]
    rows = []
    try:
        for name, pcm in cases():
            take = Take(recognizers, language="auto", language_hint="en")
            take.warm()
            start = time.perf_counter()
            for n, off in enumerate(range(0, len(pcm), BLOCK)):
                take.feed(pcm[off : off + BLOCK])
                due = start + (n + 1) * BLOCK / (SAMPLE_RATE * 2)
                await asyncio.sleep(max(0.0, due - time.perf_counter()))
            rows.append(_row(name, await take.finish()))
            await asyncio.sleep(0.3)
    finally:
        provider.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--engine", choices=("sim", "real"), default="sim")
    ap.add_argument("--json", help="write the rows to this file")
    ap.add_argument("--budget-ms", type=int, default=DEFAULT_BUDGET_MS)
    args = ap.parse_args()

    started = time.perf_counter()
    if args.engine == "sim":
        rows = run_sim()
    else:
        try:
            rows = asyncio.run(_run_real())
        except Exception as exc:  # model files or runtime missing
            print(f"SKIP real engine unavailable: {type(exc).__name__}: {exc}")
            return 78
    for r in rows:
        print(
            f"{r['name']:12s} audio {r['duration_s']:5.1f}s  "
            f"wait after stop {r['wait_ms']:5d} ms  "
            f"calls {r['calls']}  pieces {r['pieces']}  "
            f"ahead kept {r['reads_ahead_kept']}/{r['reads_ahead']}  chars {r['chars']}"
        )
    worst = max(r["wait_ms"] for r in rows)
    real_s = time.perf_counter() - started
    print(f"engine={args.engine} worst wait {worst} ms  ({real_s:.1f}s real)")
    if args.json:
        Path(args.json).write_text(
            json.dumps({"engine": args.engine, "rows": rows, "worst_wait_ms": worst}, indent=1),
            encoding="utf-8",
        )
    bad = [r["name"] for r in rows if r["chars"] == 0 or r["error"]]
    if bad:
        print(f"FAIL no text / error in: {', '.join(bad)}")
        return 1
    if args.engine == "sim" and worst > args.budget_ms:
        print(f"FAIL worst wait {worst} ms exceeds budget {args.budget_ms} ms")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
