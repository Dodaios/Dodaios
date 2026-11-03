"""scripts/unreal/fake_bridge.py serves every scenario over a real WebSocket (G0.11).

A small scripted Verse client connects, says hello, subscribes and watches
what the scenario asks for, answers lifecycle and panel events the way the
Unreal side must, and checks every frame it receives against the schema.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from scripts.unreal import bridge_cells, bridge_schema, fake_bridge

TOKEN = secrets.token_urlsafe(32)
SCHEMA = bridge_schema.load()
SCENARIOS = fake_bridge.scenario_names()


def _hello(token: str = TOKEN, encodings=("cells.bin/1", "cells.json/1"), protocols=None) -> str:
    return json.dumps(
        {
            "type": "hello",
            "ts": time.time(),
            "data": {
                "token": token,
                "protocols": protocols or [bridge_schema.PROTOCOL],
                "build": {"version": "0.1.0", "changelist": "test", "config": "Development"},
                "pid": 4242,
                "last_seq": 0,
                "encodings": {"screens": list(encodings)},
            },
        }
    )


@contextlib.asynccontextmanager
async def running(name: str, **kw) -> AsyncIterator[fake_bridge.FakeBridge]:
    kw.setdefault("speed", 0.0)
    kw.setdefault("hold_s", 5.0)
    bridge = fake_bridge.FakeBridge(TOKEN, fake_bridge.load_scenario(name), **kw)
    await bridge.start()
    try:
        yield bridge
    finally:
        await bridge.stop()


class Verse:
    """The Unreal side, reduced to what the scenarios exercise."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.json: list[dict] = []
        self.binary: list[dict] = []
        self.replies: dict[str, dict] = {}
        self.next_id = 0
        self.started_meeting = False

    async def command(self, type_: str, data: dict) -> str:
        self.next_id += 1
        rid = f"c-{self.next_id}"
        await self.ws.send(json.dumps({"type": type_, "id": rid, "ts": time.time(), "data": data}))
        return rid

    async def notice(self, type_: str, data: dict) -> None:
        await self.ws.send(json.dumps({"type": type_, "ts": time.time(), "data": data}))

    async def react(self, frame: dict) -> None:
        type_, data = frame["type"], frame["data"]
        if type_ == "reply":
            assert frame["re"] not in self.replies, "two replies to one command"
            self.replies[frame["re"]] = frame
        elif type_ == "lifecycle.show":
            await self.notice("lifecycle.state", {"state": "visible", "vram_mb": 3000, "fps": 60})
        elif type_ in {"lifecycle.hide", "focus.app_took"}:
            await self.notice("lifecycle.state", {"state": "dormant", "vram_mb": 1500, "fps": 2})
        elif type_ == "lifecycle.quit":
            await self.notice("lifecycle.bye", {"saved": True})
        elif type_ == "panel.visibility":
            state = "streaming" if data["visible"] else "stopped"
            await self.notice("panel.stream_state", {"state": state})
        elif type_ == "progression.awarded" and data["level"] > data["previous_level"]:
            if data["subject_kind"] == "person":
                await self.command("progression.told", {"seq": data["seq"]})
        elif type_ == "meetings.update" and data["running"] and not self.started_meeting:
            self.started_meeting = True
            await self.command("meeting.start", {"group_id": data["group_id"], "text": "Ship it?"})

    async def pump(self) -> None:
        with contextlib.suppress(ConnectionClosed):
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    self.binary.append(bridge_cells.decode(raw))
                    continue
                frame = json.loads(raw)
                self.json.append(frame)
                await self.react(frame)


async def play(bridge: fake_bridge.FakeBridge, encodings=("cells.bin/1", "cells.json/1")) -> Verse:
    scenario = bridge.scenario
    async with connect(bridge.url) as ws:
        await ws.send(_hello(encodings=encodings))
        verse = Verse(ws)
        pump = asyncio.create_task(verse.pump())
        if scenario["topics"]:
            await verse.command("subscribe", {"topics": scenario["topics"]})
        if scenario["watch_screens"]:
            panes = [{"pane_id": p, "hz": 10} for p in scenario["watch_screens"]]
            await verse.command("screens.watch", {"panes": panes})
        if scenario["watch_chat_tails"]:
            await verse.command("chat_tails.watch", {"agents": scenario["watch_chat_tails"]})
        await asyncio.wait_for(bridge.finished.wait(), 20)
        await verse.notice("ping", {})
        for _ in range(200):
            if any(f["type"] == "pong" for f in verse.json) and len(verse.replies) == verse.next_id:
                break
            await asyncio.sleep(0.01)
        await ws.close()
        await pump
    return verse


def _check_stream(verse: Verse, scenario: dict) -> None:
    frames = verse.json
    assert frames[0]["type"] == "welcome" and frames[0]["seq"] == 1
    lenient_steps = sum(1 for s in scenario["steps"] if s.get("lenient"))
    strict_failures = 0
    for frame in frames:
        assert SCHEMA.validate_frame(frame, lenient=True) == [], frame["type"]
        if SCHEMA.validate_frame(frame):
            strict_failures += 1
    assert strict_failures == lenient_steps
    # One seq counter across JSON and binary frames, strictly increasing.
    seqs = sorted([f["seq"] for f in frames] + [b["seq"] for b in verse.binary])
    assert len(set(seqs)) == len(seqs)
    seen = set(seqs)
    for frame in frames + verse.binary:
        if frame.get("base") is not None:
            assert frame["base"] in seen and frame["base"] < frame["seq"]
    assert sorted(verse.replies) == sorted(f"c-{i}" for i in range(1, verse.next_id + 1))


@pytest.mark.parametrize("name", SCENARIOS)
async def test_fake_bridge_serves_every_scenario(name: str) -> None:
    async with running(name) as bridge:
        verse = await play(bridge)
    report = bridge.report.as_dict()
    assert report["passed"], report
    scenario = bridge.scenario
    _check_stream(verse, scenario)
    feed_steps = [s["frame"] for s in scenario["steps"] if "frame" in s]
    received = [f for f in verse.json if f["type"] not in {"welcome", "reply", "pong"}]
    json_steps = [f for f in feed_steps if f["type"] != "screens.frame"]
    snapshots = [t for t in scenario["topics"] if t in fake_bridge.SNAPSHOT_OF]
    metas = sum(
        1 for f in feed_steps if f["type"] == "screens.frame" and f["data"]["kind"] == "snapshot"
    )
    extra = [f for f in received if f["type"] == "screens.meta"]
    assert len(received) == len(json_steps) + len(snapshots) + len(extra)
    assert metas == sum(1 for f in received if f["type"] == "screens.meta")
    screen_steps = [f["data"] for f in feed_steps if f["type"] == "screens.frame"]
    assert [b["rows_changed"] for b in verse.binary] == [
        bridge_cells.normalise_runs(d["rows_changed"]) for d in screen_steps
    ]


async def test_busy_panes_in_json_encoding_and_refs_from_the_watch_reply() -> None:
    async with running("busy_panes") as bridge:
        verse = await play(bridge, encodings=("cells.json/1",))
    assert bridge.report.passed
    assert verse.json[0]["data"]["encoding"] == {"screens": "cells.json/1"}
    assert not verse.binary
    watch = verse.replies["c-2"]["data"]["result"]
    refs = {b["pane_id"]: b["ref"] for b in watch["bound"]}
    assert len(refs) == 8 and watch["dropped"] == [] and watch["missing"] == []
    frames = [f for f in verse.json if f["type"] == "screens.frame"]
    steps = [
        s["frame"]["data"]
        for s in bridge.scenario["steps"]
        if s.get("frame", {}).get("type") == "screens.frame"
    ]
    assert len(frames) == len(steps)
    for frame in frames:
        if frame["data"]["kind"] == "snapshot":
            assert frame["data"]["ref"] == refs[frame["data"]["pane_id"]]
        else:
            assert "base" in frame
    _check_stream(verse, bridge.scenario)


async def test_roster_deltas_reach_the_fake_state_and_resync_sends_it() -> None:
    async with running("roster_churn") as bridge, connect(bridge.url) as ws:
        await ws.send(_hello())
        verse = Verse(ws)
        pump = asyncio.create_task(verse.pump())
        await verse.command("subscribe", {"topics": ["roster"]})
        await asyncio.wait_for(bridge.finished.wait(), 10)
        await verse.command("resync", {"topic": "roster"})
        for _ in range(200):
            if len(verse.replies) == 2:
                break
            await asyncio.sleep(0.01)
        await ws.close()
        await pump
    snapshot = [f for f in verse.json if f["type"] == "roster.snapshot"][-1]["data"]
    agents = {a["agent_id"]: a for a in snapshot["agents"]}
    assert "ag_004" not in agents and "ag_006" in agents
    assert all(a["duty"] == "working" for a in agents.values() if a["agent_id"] != "ag_005")
    assert snapshot["commander"]["level"] == 15
    assert {p["pane_id"] for p in snapshot["panes"]} == {
        "ws_91:T1",
        "ws_91:T3",
        "ws_91:T4",
        "ws_91:T5",
    }


async def _close_code(bridge, first: str | None) -> int:
    async with connect(bridge.url) as ws:
        if first is not None:
            await ws.send(first)
        with contextlib.suppress(ConnectionClosed):
            while True:
                await asyncio.wait_for(ws.recv(), 5)
        return ws.close_code


async def test_wrong_token_closes_4401() -> None:
    async with running("idle") as bridge:
        assert await _close_code(bridge, _hello(token=secrets.token_urlsafe(32))) == 4401


async def test_missing_or_malformed_hello_closes_4400() -> None:
    async with running("idle", hello_timeout=0.2) as bridge:
        assert await _close_code(bridge, None) == 4400
        ping = json.dumps({"type": "ping", "ts": 1.0, "data": {}})
        assert await _close_code(bridge, ping) == 4400
        assert await _close_code(bridge, "{not json") == 4400


async def test_unsupported_protocol_closes_4426_naming_the_supported_ones() -> None:
    async with running("idle") as bridge, connect(bridge.url) as ws:
        await ws.send(_hello(protocols=["verse.bridge/2"]))
        with contextlib.suppress(ConnectionClosed):
            await asyncio.wait_for(ws.recv(), 5)
        assert ws.close_code == 4426
        assert json.loads(ws.close_reason) == {"supported": ["verse.bridge/1"]}


async def test_second_client_replaces_the_first_with_4409() -> None:
    async with running("idle") as bridge:
        async with connect(bridge.url) as first:
            await first.send(_hello())
            assert json.loads(await first.recv())["type"] == "welcome"
            async with connect(bridge.url) as second:
                await second.send(_hello())
                assert json.loads(await second.recv())["type"] == "welcome"
                with contextlib.suppress(ConnectionClosed):
                    await asyncio.wait_for(first.recv(), 5)
                assert first.close_code == 4409


async def test_other_paths_are_refused() -> None:
    async with running("idle") as bridge:
        with pytest.raises(InvalidStatus):
            async with connect(bridge.url.replace("/api/verse/bridge", "/api/other")):
                pass


async def test_commands_follow_the_contract_rules() -> None:
    async with running("idle") as bridge, connect(bridge.url) as ws:
        await ws.send(_hello())
        verse = Verse(ws)
        pump = asyncio.create_task(verse.pump())
        duel = bridge_schema.read_json(bridge_schema.DATA_DIR / "messages" / "duel.result.json")[0]
        ids = {
            "duel1": await verse.command("duel.result", duel["data"]),
            "duel2": await verse.command("duel.result", duel["data"]),
            "set": await verse.command("settings.set", {"gore": "reduced"}),
            "qa": await verse.command("qa.exec", {"command": "Verse.QA.Stats", "args": []}),
            "sub": await verse.command("subscribe", {"topics": ["panel"]}),
            "watch": await verse.command(
                "screens.watch",
                {"panes": [{"pane_id": "ws_91:T1", "hz": 10}, {"pane_id": "ws_9:X", "hz": 2}]},
            ),
            "bad": await verse.command("pane.open", {"pane_id": "no-colon"}),
            "told": await verse.command("progression.told", {"seq": 950}),
        }
        for _ in range(300):
            if len(verse.replies) == len(ids):
                break
            await asyncio.sleep(0.01)
        await ws.close()
        await pump

    def data(key: str) -> dict:
        return verse.replies[ids[key]]["data"]

    assert data("duel1") == data("duel2") and data("duel1")["result"]["recorded"] is True
    assert data("set")["result"]["settings"]["gore"] == "reduced"
    changed = [f for f in verse.json if f["type"] == "settings.changed"]
    assert changed and changed[0]["data"] == {"gore": "reduced"}
    assert data("qa")["error"]["code"] == "unavailable"
    assert data("sub")["result"] == {"subscribed": ["panel"], "unavailable": []}
    assert data("watch")["result"] == {
        "bound": [{"pane_id": "ws_91:T1", "ref": 1}],
        "dropped": [],
        "missing": ["ws_9:X"],
    }
    assert data("bad")["error"]["code"] == "bad_request"
    assert data("told")["result"] == {"told_seq": 950}
    assert bridge.report.invalid_from_verse  # the malformed pane.open is recorded
    for reply in verse.replies.values():
        assert SCHEMA.validate_frame(reply) == []


async def test_qa_exec_runs_when_qa_is_enabled() -> None:
    async with running("idle", qa=True) as bridge, connect(bridge.url) as ws:
        await ws.send(_hello())
        verse = Verse(ws)
        pump = asyncio.create_task(verse.pump())
        rid = await verse.command("qa.exec", {"command": "Verse.QA.Stats", "args": ["fps"]})
        for _ in range(200):
            if rid in verse.replies:
                break
            await asyncio.sleep(0.01)
        await ws.close()
        await pump
    result = {"result": {"command": "Verse.QA.Stats", "args": ["fps"]}}
    assert verse.replies[rid]["data"] == {"ok": True, "result": result}


async def test_missing_expectation_fails_the_report() -> None:
    async with running("panel") as bridge, connect(bridge.url) as ws:
        # A Verse that never answers panel events.
        for step in bridge.scenario["steps"]:
            step["timeout_ms"] = min(step.get("timeout_ms", 0), 100) or step.get("timeout_ms")
        await ws.send(_hello())
        await asyncio.wait_for(bridge.finished.wait(), 10)
    report = bridge.report.as_dict()
    assert not report["passed"]
    assert [e["ok"] for e in report["expectations"]] == [False, False]


def test_invalid_scenario_is_refused() -> None:
    scenario = fake_bridge.load_scenario("panel")
    scenario["steps"][0]["frame"]["data"]["visible"] = "yes"
    with pytest.raises(ValueError, match="invalid scenario"):
        fake_bridge.FakeBridge(TOKEN, scenario)


def test_cli_lists_and_checks_scenarios(capsys) -> None:
    assert fake_bridge.main(["--list"]) == 0
    listed = capsys.readouterr().out
    for name in ("roster_churn", "busy_panes", "meetings", "awards", "lifecycle", "panel"):
        assert f"{name}:" in listed
    assert fake_bridge.main(["--check"]) == 0


def test_cli_serves_a_scenario_once_and_writes_the_report(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    discovery = tmp_path / "verse" / "bridge.json"
    script = Path(fake_bridge.__file__)
    args = [
        sys.executable,
        str(script),
        "--token",
        TOKEN,
        "--scenario",
        "lifecycle",
        "--speed",
        "0",
    ]
    args += ["--once", "--report", str(report_path), "--discovery", str(discovery)]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, text=True, encoding="utf-8")  # noqa: S603
    try:
        line = proc.stdout.readline()
        url = line.split(" on ", 1)[1].split(" ", 1)[0]
        assert json.loads(discovery.read_text(encoding="utf-8"))["url"] == url

        async def client() -> None:
            async with connect(url) as ws:
                await ws.send(_hello())
                verse = Verse(ws)
                pump = asyncio.create_task(verse.pump())
                for _ in range(500):
                    if any(f["type"] == "lifecycle.quit" for f in verse.json):
                        break
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.2)
                await ws.close()
                await pump

        asyncio.run(client())
        assert proc.wait(timeout=20) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        proc.stdout.close()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] and report["sent"]["lifecycle.quit"] == 1
    assert not discovery.exists()
