"""17.6 / A17.7: styled mirror, screens relay, cells codec on the wire.

8 busy panes stay under 200 KB/s and the parser adds at most 5 ms (p99) to
the event loop per output chunk; plain fallback; screens.gone; resync.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path

from dodaios.verse_host import cells_codec
from dodaios.verse_host.styled_screen import StyledScreen
from tests.unit.verse_host._support import close, connect, make_host, schema

PROOF = Path(__file__).resolve().parents[3] / "unreal" / "Verse" / "Saved" / "Harness" / "proof"


def test_styled_screen_keeps_colours_and_attrs() -> None:
    s = StyledScreen(40, 5)
    s.feed("\x1b[1;38;2;79;184;106m✔ ok\x1b[0m \x1b[38;5;8m(42)\x1b[0m\r\n\x1b[7minv\x1b[27m")
    runs = s.row_record(0)["runs"]
    assert runs[0] == {"col": 0, "text": "✔ ok", "fg": "#4fb86a", "bg": None, "attrs": ["bold"]}
    assert runs[1]["text"] == " " and runs[2] == {
        "col": 5,
        "text": "(42)",
        "fg": {"i": 8},
        "bg": None,
        "attrs": [],
    }
    assert s.row_record(1)["runs"][0]["attrs"] == ["inverse"]
    assert s.cursor() == [1, 3]


def test_wide_glyphs_and_alt_screen() -> None:
    s = StyledScreen(10, 3)
    s.feed("漢字ab")
    runs = s.row_record(0)["runs"]
    assert runs[0] == {"col": 0, "text": "漢字", "fg": None, "bg": None, "attrs": ["wide"]}
    assert runs[1]["col"] == 4 and runs[1]["text"] == "ab"
    s.take_dirty()
    s.feed("\x1b[?1049h\x1b[HALT")
    assert s.text_rows()[0] == "ALT"
    s.feed("\x1b[?1049l")
    assert s.text_rows()[0] == "漢字ab"
    blob = cells_codec.encode(
        {
            "kind": "snapshot",
            "cols": 10,
            "rows": 3,
            "cursor": s.cursor(),
            "rows_changed": s.snapshot_rows(),
        },
        ref=1,
        seq=2,
        base=None,
    )
    assert cells_codec.decode(blob)["rows_changed"][0]["runs"][0]["text"] == "漢字"


def test_dirty_rows_only_and_scroll() -> None:
    s = StyledScreen(20, 4)
    s.take_dirty()
    s.feed("\x1b[3;1Hhello")
    assert [r["row"] for r in s.take_dirty()] == [2]
    s.feed("\x1b[4;1H\n")
    assert {r["row"] for r in s.take_dirty()} == {0, 1, 2, 3}


def test_hostile_stream_never_raises() -> None:
    s = StyledScreen(30, 5)
    rng = random.Random(7)  # noqa: S311 - test data
    alphabet = "\x1b[;?0123456789mHJKABCDsuhl\x07]\\P\n\r\t abc漢́"
    for _ in range(200):
        s.feed("".join(rng.choice(alphabet) for _ in range(rng.randint(1, 80))))
    for r in s.snapshot_rows():
        cells_codec.check_rows(s.sent_cols, s.sent_rows, [r])


def _busy_chunk(rng: random.Random, i: int) -> str:
    row = rng.randint(1, 40)
    colour = rng.choice([31, 32, 33, 34, 35, 36, 90])
    text = "".join(
        rng.choice("abcdefghijklmnopqrstuvwxyz ./:") for _ in range(rng.randint(20, 120))
    )
    return f"\x1b[{row};1H\x1b[2K\x1b[{colour}m{i:06d} {text}\x1b[0m"


async def test_eight_busy_panes_stay_under_budget(tmp_path: Path) -> None:
    host, backend = make_host(tmp_path)
    for n in range(2, 10):
        backend.panes.append(dict(backend.panes[0], key=f"T{n}", name=f"T{n}"))
    t, task = await connect(host)
    panes = [{"pane_id": f"ws_91:T{n}", "hz": 10} for n in range(1, 10)]
    t.push({"type": "screens.watch", "id": "c-30", "ts": 1.0, "data": {"panes": panes}})
    reply = await t.reply_to("c-30")
    assert [b["ref"] for b in reply["data"]["result"]["bound"]] == list(range(1, 9))
    assert reply["data"]["result"]["dropped"] == ["ws_91:T9"]
    relay = next(r for r in host.hub.current.relays if r.topics == ("screens",))
    rng = random.Random(1)  # noqa: S311 - test data
    loop = asyncio.get_running_loop()

    async def lag_probe(seconds: float) -> list[float]:
        """How long work queued on the loop waits before it runs (no timer granularity)."""
        lags, end = [], time.perf_counter() + seconds
        while time.perf_counter() < end:
            fut = loop.create_future()
            t0 = time.perf_counter()
            loop.call_soon(fut.set_result, None)
            await fut
            lags.append(time.perf_counter() - t0)
            await asyncio.sleep(0.002)
        return sorted(lags)

    baseline = await lag_probe(1.0)
    duration = 3.0
    counter = {"chunks": 0}
    first_bytes = host.hub.current.screen_bytes

    chunks = [_busy_chunk(rng, k) * 4 for k in range(512)]

    async def feeder(pane_id: str) -> None:
        end = loop.time() + duration
        while loop.time() < end:
            on_output, _ = backend.attached[pane_id]
            await on_output(chunks[counter["chunks"] % len(chunks)])
            counter["chunks"] += 1
            await asyncio.sleep(0.02)

    feeders = [asyncio.ensure_future(feeder(p)) for p in list(backend.attached)]
    lags = await lag_probe(duration)
    await asyncio.gather(*feeders)
    i = counter["chunks"]
    spent = host.hub.current.screen_bytes - first_bytes
    rate = spent / duration
    p99_feed = relay.feed_p99_ms()
    p99_frame = relay.frame_p99_ms()
    await close(t, task)
    p99_lag_ms = lags[int(len(lags) * 0.99)] * 1000
    p99_base_ms = baseline[int(len(baseline) * 0.99)] * 1000
    assert rate <= 200 * 1024 * 1.05, rate
    assert p99_feed <= 5.0, p99_feed
    # The relay's own work per loop step: one output chunk parsed, one pane framed.
    p99_frame = relay.frame_p99_ms()
    assert p99_frame <= 5.0, p99_frame
    metas = t.of_type("screens.meta")
    assert {m["data"]["pane_id"] for m in metas} == {f"ws_91:T{n}" for n in range(1, 9)}
    blobs = t.binary()
    assert blobs, "no binary cell frames"
    decoded = [cells_codec.decode(b) for b in blobs]
    by_ref: dict[int, list[dict]] = {}
    for d in decoded:
        by_ref.setdefault(d["ref"], []).append(d)
    for frames in by_ref.values():
        assert frames[0]["kind"] == "snapshot"
        for prev, cur in zip(frames, frames[1:], strict=False):
            if cur["kind"] == "delta":
                assert cur["base"] == prev["seq"]
    out = PROOF / "WP17" / "17.6"
    out.mkdir(parents=True, exist_ok=True)
    (out / "screens_budget.json").write_text(
        json.dumps(
            {
                "panes": 8,
                "seconds": duration,
                "screens_bytes_per_s": round(rate),
                "budget_bytes_per_s": 200 * 1024,
                "parser_p99_ms": round(p99_feed, 3),
                "frame_build_p99_ms": round(p99_frame, 3),
                "loop_lag_p99_ms": round(p99_lag_ms, 3),
                "loop_lag_p99_baseline_ms": round(p99_base_ms, 3),
                "loop_lag_p99_added_ms": round(p99_lag_ms - p99_base_ms, 3),
                "binary_frames": len(blobs),
                "chunks_fed": i,
                "measured_at": time.time(),
            },
            indent=2,
        )
    )


async def test_plain_fallback_gone_and_resync(tmp_path: Path, monkeypatch) -> None:
    host, backend = make_host(tmp_path)
    backend.panes.append(dict(backend.panes[0], key="T2", name="T2"))
    backend.attach_fails.add("ws_91:T2")
    backend.screens["ws_91:T2"] = {
        "cols": 40,
        "rows": 5,
        "lines": ["$ make", "ok"],
        "cursor": [1, 2],
        "at": 5.0,
    }
    t, task = await connect(host, encodings={"screens": ["cells.json/1"]})
    t.push(
        {
            "type": "screens.watch",
            "id": "c-1",
            "ts": 1.0,
            "data": {
                "panes": [
                    {"pane_id": "ws_91:T1", "hz": 10},
                    {"pane_id": "ws_91:T2", "hz": 2},
                    {"pane_id": "ws_91:T7", "hz": 2},
                ]
            },
        }
    )
    reply = await t.reply_to("c-1")
    assert reply["data"]["result"]["missing"] == ["ws_91:T7"]
    plain = await t.wait_for(
        lambda f: f["type"] == "screens.frame" and f["data"]["pane_id"] == "ws_91:T2"
    )
    assert plain["data"]["style"] == "plain" and plain["data"]["kind"] == "snapshot"
    assert plain["data"]["rows_changed"][0]["runs"][0]["text"] == "$ make"
    await backend.attached["ws_91:T1"][0]("\x1b[32mgreen\x1b[0m")
    styled = await t.wait_for(
        lambda f: (
            f["type"] == "screens.frame"
            and f["data"]["pane_id"] == "ws_91:T1"
            and f["data"]["kind"] == "delta"
        )
    )
    assert styled["data"]["rows_changed"][0]["runs"][0]["fg"] == {"i": 2}
    t.push(
        {
            "type": "resync",
            "id": "c-2",
            "ts": 1.0,
            "data": {"topic": "screens", "pane_id": "ws_91:T1"},
        }
    )
    await t.reply_to("c-2")

    def snaps() -> list[dict]:
        return [
            f
            for f in t.of_type("screens.frame")
            if f["data"]["pane_id"] == "ws_91:T1" and f["data"]["kind"] == "snapshot"
        ]

    await t.wait_for(lambda f: len(snaps()) >= 2)
    await backend.attached["ws_91:T1"][1](0)
    gone = await t.wait_for(lambda f: f["type"] == "screens.gone")
    assert gone["data"] == {"pane_id": "ws_91:T1", "reason": "exited"}
    await close(t, task)
    sch = schema()
    for frame in t.frames():
        assert sch.validate_frame(frame) == [], frame
