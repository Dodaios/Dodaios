"""17.1 / A17.1: the backend codec passes every G0.11 golden fixture and scenario.

* every golden message frame parses and re-encodes identically;
* every ``cells.bin/1`` vector encodes to the exact bytes and decodes back,
  and every malformed vector is rejected;
* every golden command request, driven through a live :class:`BridgeHub`
  session, gets exactly one reply that validates against the schema, with the
  golden reply's ``ok`` and error code;
* every frame the backend sends in those sessions validates as golden data;
* every ``fake_bridge.py`` scenario frame parses with the backend codec.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dodaios.verse_host import cells_codec, protocol
from tests.unit.verse_host._support import (
    FIXTURES,
    FakeBackend,
    FakeDuelService,
    close,
    connect,
    make_host,
    schema,
)

MESSAGES = sorted((FIXTURES / "messages").glob("*.json"))
REPLIES = sorted((FIXTURES / "replies").glob("*.json"))
SCENARIOS = sorted((FIXTURES / "scenarios").glob("*.json"))
VECTORS = json.loads((FIXTURES / "cells" / "vectors.json").read_text(encoding="utf-8"))


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", MESSAGES, ids=lambda p: p.stem)
def test_golden_message_round_trip(path: Path) -> None:
    for frame in _load(path):
        text = protocol.encode(frame)
        parsed = protocol.parse(text)
        assert parsed.type == frame["type"]
        assert parsed.data == frame["data"]
        assert json.loads(protocol.encode(parsed.raw)) == frame


@pytest.mark.parametrize("vector", VECTORS["valid"], ids=lambda v: v["name"])
def test_cells_vector_encodes_exactly(vector: dict) -> None:
    frame = vector["frame"]
    data = frame["data"]
    blob = cells_codec.encode(data, ref=vector["ref"], seq=frame["seq"], base=frame.get("base"))
    assert blob.hex() == vector["bin_hex"]
    decoded = cells_codec.decode(bytes.fromhex(vector["bin_hex"]))
    assert decoded["kind"] == data["kind"]
    assert decoded["cols"] == data["cols"] and decoded["rows"] == data["rows"]
    assert decoded["cursor"] == data["cursor"]
    assert decoded["seq"] == frame["seq"]
    expected = [
        {
            "row": r["row"],
            "runs": [
                {
                    "col": u["col"],
                    "text": u["text"],
                    "fg": u.get("fg"),
                    "bg": u.get("bg"),
                    "attrs": list(u.get("attrs", [])),
                }
                for u in r["runs"]
            ],
        }
        for r in data["rows_changed"]
    ]
    assert decoded["rows_changed"] == expected


@pytest.mark.parametrize("vector", VECTORS["invalid"], ids=lambda v: v["name"])
def test_cells_vector_rejected(vector: dict) -> None:
    with pytest.raises(cells_codec.CellsError):
        cells_codec.decode(bytes.fromhex(vector["bin_hex"]))


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenario_frames_parse(path: Path) -> None:
    scenario = _load(path)
    for step in scenario["steps"]:
        if "frame" in step:
            frame = dict(step["frame"], seq=2, ts=0.0)
            parsed = protocol.parse(protocol.encode(frame))
            assert parsed.type == step["frame"]["type"]
            if parsed.type == "screens.frame":
                data = parsed.data
                blob = cells_codec.encode(
                    data, ref=1, seq=5, base=4 if data["kind"] == "delta" else None
                )
                assert cells_codec.decode(blob)["rows_changed"] is not None


def _requests() -> list[tuple[str, dict, dict]]:
    out = []
    for path in REPLIES:
        for pair in _load(path):
            out.append((path.stem, pair["request"], pair["reply"]))
    return out


@pytest.mark.parametrize(
    "command,request_frame,golden_reply",
    _requests(),
    ids=[f"{c}-{r['id']}" for c, r, _ in _requests()],
)
async def test_golden_command_gets_one_valid_reply(
    command: str, request_frame: dict, golden_reply: dict, tmp_path: Path, monkeypatch
) -> None:
    backend = FakeBackend()
    backend.duel = FakeDuelService()
    backend.panes.append(dict(backend.panes[0], key="T2", name="T2"))
    backend.agents.append(
        {"agent_id": "ag_02c", "name": "Ode", "state": "active", "run_state": "idle"}
    )
    golden_ok = golden_reply["data"]["ok"]
    golden_code = None if golden_ok else golden_reply["data"]["error"]["code"]
    if command == "qa.exec" and golden_ok:
        monkeypatch.setenv("DODAIOS_VERSE_QA", "1")
    else:
        monkeypatch.delenv("DODAIOS_VERSE_QA", raising=False)
    if command in ("meeting.start", "meeting.stop") and golden_code == "conflict":
        backend.confirm = False
    if command == "subscribe" and request_frame["data"].get("topics") == ["panel"]:
        # The golden reply is the host without Pixel Streaming signalling.
        monkeypatch.setattr("dodaios.verse_host.host.panel_available", lambda: False)
    host, _ = make_host(tmp_path, backend)
    t, task = await connect(host)
    if golden_code == "busy":
        backend.launch_gate = asyncio.Event()
        host.launcher.running = object()  # type: ignore[assignment]
    if golden_code == "rate_limited":
        limit = t  # noqa: F841
        for i in range(8):
            t.push(dict(request_frame, id=f"warm-{i}"))
        await asyncio.sleep(0.05)
    t.push(request_frame)
    reply = await t.reply_to(request_frame["id"])
    if golden_code == "busy":
        host.launcher.running = None
    await close(t, task)
    sch = schema()
    assert sch.validate_reply(reply, command) == [], reply
    replies = [f for f in t.frames() if f["type"] == "reply" and f.get("re") == request_frame["id"]]
    assert len(replies) == 1
    if golden_code in (
        "not_found",
        "bad_request",
        "unavailable",
        "busy",
        "conflict",
        "rate_limited",
    ):
        if command not in ("progression.action",) or golden_code != "not_found":
            assert reply["data"]["ok"] is False, reply
            assert reply["data"]["error"]["code"] == golden_code, reply
    elif golden_ok:
        assert reply["data"]["ok"] is True, reply


async def test_every_sent_frame_is_golden_valid(tmp_path: Path) -> None:
    backend = FakeBackend()
    host, _ = make_host(tmp_path, backend)
    t, task = await connect(host)
    t.push(
        {
            "type": "subscribe",
            "id": "c-1",
            "ts": 1.0,
            "data": {
                "topics": [
                    "roster",
                    "panes",
                    "progression",
                    "meetings",
                    "groups",
                    "companion",
                    "lifecycle",
                    "panel",
                ]
            },
        }
    )
    t.push({"type": "chat_tails.watch", "id": "c-2", "ts": 1.0, "data": {"agents": ["ag_7f1"]}})
    t.push({"type": "ping", "ts": 1.0, "data": {}})
    await t.wait_for(lambda f: f["type"] == "roster.snapshot")
    await t.wait_for(lambda f: f["type"] == "progression.snapshot")
    await t.wait_for(lambda f: f["type"] == "groups.snapshot")
    await t.wait_for(lambda f: f["type"] == "companion.snapshot")
    await t.wait_for(lambda f: f["type"] == "chat_tails.update")
    await t.wait_for(lambda f: f["type"] == "pong")
    backend.agents[0]["run_state"] = "working"
    backend.agents[0]["waiting_reason"] = None
    from dodaios.core.events import SocietyMessageSent

    await backend.bus.publish(SocietyMessageSent())
    await t.wait_for(lambda f: f["type"] == "roster.delta", 3.0)
    await close(t, task)
    sch = schema()
    seqs = []
    for frame in t.frames():
        errors = sch.validate_frame(frame)
        assert errors == [], (frame["type"], errors)
        seqs.append(frame["seq"])
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    welcome = t.frames()[0]
    assert welcome["type"] == "welcome" and welcome["seq"] == 1
    delta = t.of_type("roster.delta")[0]
    snap = t.of_type("roster.snapshot")[0]
    assert delta["base"] == snap["seq"]
    assert delta["data"]["upsert"]["agents"] == [
        {"agent_id": "ag_7f1", "run_state": "working", "waiting_reason": None, "duty": "working"}
    ]
