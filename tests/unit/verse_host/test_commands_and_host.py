"""17.5, 17.7-17.10, A17.6 (host half), A17.8, A17.9: relays, commands and the host."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from dodaios.core.events import (
    PetChanged,
    ProgressionAwarded,
    ShowWindowRequested,
    SocietyResultPosted,
    VerseOpenRequested,
    VerseSettingsChanged,
)
from dodaios.verse_host import probe
from tests.unit.verse_host._support import (
    FakeDuelService,
    close,
    connect,
    make_host,
    schema,
)

PROOF = Path(__file__).resolve().parents[3] / "unreal" / "Verse" / "Saved" / "Harness" / "proof"


def _cmd(t, type_: str, rid: str, data: dict) -> None:
    t.push({"type": type_, "id": rid, "ts": 1.0, "data": data})


async def test_launcher_single_flight_busy_and_cancel(tmp_path: Path) -> None:
    host, backend = make_host(tmp_path)
    backend.launch_gate = asyncio.Event()
    t, task = await connect(host)
    _cmd(t, "launcher.start", "c-1", {"agents": [{"agent": "claude", "count": 3}], "brief": "Go."})
    await asyncio.sleep(0.05)
    for _ in range(20):
        if host.launcher.busy:
            break
        await asyncio.sleep(0.01)
    _cmd(t, "launcher.start", "c-2", {"agents": [{"agent": "claude", "count": 1}], "brief": "x"})
    busy = await t.reply_to("c-2")
    assert busy["data"]["error"]["code"] == "busy"
    _cmd(t, "launcher.cancel", "c-3", {})
    cancel = await t.reply_to("c-3")
    assert cancel["data"]["result"]["stopped"] == 3
    backend.launch_gate.set()
    done = await t.reply_to("c-1")
    assert done["data"]["ok"] is True
    assert len(done["data"]["result"]["panes"]) == 1  # cancelled after the first open
    await close(t, task)


async def test_launcher_briefs_each_pane(tmp_path: Path) -> None:
    host, backend = make_host(tmp_path)
    t, task = await connect(host)
    _cmd(
        t,
        "launcher.start",
        "c-1",
        {
            "workspace_id": "ws_91",
            "agents": [{"agent": "claude", "count": 2}],
            "brief": "Write the tests.",
        },
    )
    reply = await t.reply_to("c-1")
    panes = reply["data"]["result"]["panes"]
    assert [p["submitted"] for p in panes] == [True, True]
    assert [p[2] for p in backend.prompts] == ["Write the tests.", "Write the tests."]
    _cmd(t, "launcher.start", "c-2", {"agents": [{"agent": "claude", "count": 1}], "brief": ""})
    limited = await t.reply_to("c-2")
    assert limited["data"]["error"]["code"] == "rate_limited"
    await close(t, task)


async def test_qa_exec_gate(tmp_path: Path, monkeypatch) -> None:
    host, _ = make_host(tmp_path)
    monkeypatch.delenv("DODAIOS_VERSE_QA", raising=False)
    t, task = await connect(host)
    _cmd(t, "qa.exec", "c-1", {"command": "Verse.QA.SetDuty", "args": ["ag_7f1", "error"]})
    assert (await t.reply_to("c-1"))["data"]["error"]["code"] == "unavailable"
    monkeypatch.setenv("DODAIOS_VERSE_QA", "1")
    _cmd(t, "subscribe", "c-2", {"topics": ["roster"]})
    await t.wait_for(lambda f: f["type"] == "roster.snapshot")
    _cmd(t, "qa.exec", "c-3", {"command": "Verse.QA.SetDuty", "args": ["ag_7f1", "error"]})
    ok = await t.reply_to("c-3")
    assert ok["data"]["result"] == {"result": {"agent_id": "ag_7f1", "duty": "error"}}
    delta = await t.wait_for(lambda f: f["type"] == "roster.delta")
    assert delta["data"]["upsert"]["agents"][0]["duty"] == "error"
    await close(t, task)


async def test_open_commands_publish_and_raise(tmp_path: Path) -> None:
    host, backend = make_host(tmp_path)
    t, task = await connect(host)
    _cmd(t, "pane.open", "c-1", {"pane_id": "ws_91:T1", "open": "changes"})
    _cmd(t, "ide.focus_terminal", "c-2", {"pane_id": "ws_91:T1"})
    _cmd(t, "group.open", "c-3", {"group_id": "gone"})
    _cmd(t, "pane.open", "c-4", {"pane_id": "ws_91:T9"})
    for rid in ("c-1", "c-2", "c-3", "c-4"):
        await t.reply_to(rid)
    await close(t, task)
    opens = [e for e in backend.bus.published if isinstance(e, VerseOpenRequested)]
    assert [(e.target, e.workspace_id, e.name, e.open, e.focus) for e in opens] == [
        ("pane", "ws_91", "T1", "changes", False),
        ("pane", "ws_91", "T1", "", True),
    ]
    assert sum(isinstance(e, ShowWindowRequested) for e in backend.bus.published) == 2
    codes = {f["re"]: f["data"].get("error", {}).get("code") for f in t.of_type("reply")}
    assert codes["c-3"] == "not_found" and codes["c-4"] == "not_found"


async def test_settings_set_and_import_once(tmp_path: Path) -> None:
    host, backend = make_host(tmp_path)
    t, task = await connect(host)
    welcome = t.of_type("welcome")[0]["data"]
    assert welcome["settings"]["return_key"] == "F10"
    assert welcome["locale"]["strings"].get("verse.ranks.duty.working")
    _cmd(t, "settings.set", "c-1", {"gore": "reduced", "view": {"fov_first": 90}})
    reply = await t.reply_to("c-1")
    assert reply["data"]["result"]["settings"]["gore"] == "reduced"
    assert reply["data"]["result"]["settings"]["view"]["fov_first"] == 90
    changed = await t.wait_for(lambda f: f["type"] == "settings.changed")
    assert changed["data"] == {
        "gore": "reduced",
        "view": reply["data"]["result"]["settings"]["view"],
    }
    _cmd(t, "settings.set", "c-2", {"colour": "cyan"})
    assert (await t.reply_to("c-2"))["data"]["error"]["code"] == "bad_request"
    await close(t, task)
    assert any(isinstance(e, VerseSettingsChanged) for e in backend.bus.published)
    values = {
        "dodaios.verse.view.v1": json.dumps({"fov_first": 70, "sensitivity": 1.5, "bogus": 1}),
        "dodaios.verse.uniform.v1": "dress",
        "jarvis.verse.level.sound.v1": "false",
        "jarvis.verse.levels.seen.v1": "880",
        "jarvis.office.arcade.asteroids.best": "4200",
    }
    first = host.import_browser_settings(values)
    assert set(first) == set(values)
    settings = host.store.settings()
    assert settings["view"]["fov_first"] == 90  # already set by Verse: kept
    assert settings["view"]["sensitivity"] == 1.5
    assert settings["uniform"] == "dress" and settings["level_sound"] is False
    assert host.store.told_seq() == 880
    assert host.import_browser_settings(values) == []


async def test_progression_relay_snapshot_awards_and_duel(tmp_path: Path) -> None:
    host, backend = make_host(tmp_path)
    t, task = await connect(host)
    _cmd(t, "subscribe", "c-1", {"topics": ["progression"]})
    snap = await t.wait_for(lambda f: f["type"] == "progression.snapshot")
    assert snap["data"]["told_seq"] == 0 and snap["data"]["latest_seq"] == 902
    await backend.bus.publish(
        ProgressionAwarded(
            seq=903,
            subject_id="person",
            subject_kind="person",
            xp_source="daily_visit",
            xp=25,
            total_xp=5255,
            level=14,
            previous_level=14,
            title="Lieutenant",
        )
    )
    award = await t.wait_for(lambda f: f["type"] == "progression.awarded")
    assert award["data"]["seq"] == 903 and award["data"]["xp_source"] == "daily_visit"
    _cmd(t, "progression.told", "c-2", {"seq": 903})
    assert (await t.reply_to("c-2"))["data"]["result"] == {"told_seq": 903}
    _cmd(t, "progression.action", "c-3", {"action": "duel_won", "ref": ""})
    assert (await t.reply_to("c-3"))["data"]["error"]["code"] == "bad_request"
    _cmd(t, "progression.action", "c-4", {"action": "inspection", "ref": "hangar"})
    assert (await t.reply_to("c-4"))["data"]["result"] == {"awarded": None}
    assert backend.actions == [("inspection", "hangar")]
    _cmd(t, "duel.result", "c-5", {"match_id": "m1", "outcome": "won"})
    assert (await t.reply_to("c-5"))["data"]["error"]["code"] == "unavailable"
    backend.duel = FakeDuelService()
    _cmd(t, "duel.result", "c-6", {"match_id": "m1", "outcome": "won"})
    _cmd(t, "duel.result", "c-7", {"match_id": "m1", "outcome": "won"})
    first, again = await t.reply_to("c-6"), await t.reply_to("c-7")
    assert first["data"]["result"]["awards"] == [{"xp_source": "duel_won", "xp": 60}]
    assert again["data"]["result"]["awards"] == [] and again["data"]["result"]["recorded"]
    await close(t, task)


async def test_roster_error_signal_and_companion_update(tmp_path: Path) -> None:
    host, backend = make_host(tmp_path)
    backend.agents[0]["run_state"] = "idle"
    backend.agents[0]["waiting_reason"] = None
    t, task = await connect(host)
    _cmd(t, "subscribe", "c-1", {"topics": ["roster", "companion"]})
    snap = await t.wait_for(lambda f: f["type"] == "roster.snapshot")
    agent = snap["data"]["agents"][0]
    assert agent["duty"] == "idle" and agent["rank"] == "technician" and agent["level"] == 6
    assert snap["data"]["commander"]["rank"] == "lieutenant"
    assert snap["data"]["panes"][0]["pane_id"] == "ws_91:T1"
    assert "api_key" not in json.dumps(snap) and "secret prompt" not in json.dumps(snap)
    await backend.bus.publish(SocietyResultPosted(agent_id="ag_7f1", status="blocked"))
    delta = await t.wait_for(lambda f: f["type"] == "roster.delta")
    assert delta["data"]["upsert"]["agents"] == [{"agent_id": "ag_7f1", "duty": "error"}]
    await t.wait_for(lambda f: f["type"] == "companion.snapshot")
    started = time.perf_counter()
    backend.pet = {"pet_id": "owl", "look": "owl", "style": "default"}
    await backend.bus.publish(PetChanged(pet_id="owl"))
    update = await t.wait_for(lambda f: f["type"] == "companion.update")
    assert update["data"]["pet_id"] == "owl" and time.perf_counter() - started < 2.0
    await close(t, task)


async def test_lifecycle_messages_and_timings(tmp_path: Path) -> None:
    host, backend = make_host(tmp_path)
    # A cached "ok" verdict: check() and acheck() then never start the real GPU probe.
    host.capability = probe.Capability("ok", "Verse.exe", probe.GpuReport(True), time.time())
    host.supervisor.state.status = "running"
    host.supervisor.process = type("P", (), {"alive": lambda self: True, "pid": 1})()
    t, task = await connect(host)
    t.push({"type": "lifecycle.ready", "ts": 1.0, "data": {"first_frame_ms": 4100}})
    t.push(
        {
            "type": "lifecycle.state",
            "ts": 1.0,
            "data": {"state": "visible", "vram_mb": 4300, "fps": 120},
        }
    )
    t.push({"type": "focus.return_to_app", "ts": 1.0, "data": {"reason": "return_key"}})
    t.push(
        {
            "type": "lifecycle.state",
            "ts": 1.0,
            "data": {"state": "dormant", "vram_mb": 1800, "fps": 2},
        }
    )
    await asyncio.sleep(0.1)
    assert host.state == "dormant" and host.visibility == "hidden"
    assert any(isinstance(e, ShowWindowRequested) for e in backend.bus.published)
    await host.show("station")
    show = await t.wait_for(lambda f: f["type"] == "lifecycle.show")
    assert show["data"]["reason"] == "station"
    t.push({"type": "lifecycle.state", "ts": 1.0, "data": {"state": "visible"}})
    await asyncio.sleep(0.05)
    assert "dormant_to_visible_ms" in host.timings
    await host.hide("user")
    await host.gpu_pressure(True, "local_model")
    await host.panel_visibility(True, 480, 320, 1.5)
    await t.wait_for(lambda f: f["type"] == "panel.visibility")
    await host.settings_changed({"lang": "de", "gore": "full"})
    await t.wait_for(lambda f: f["type"] == "settings.changed")
    host.supervisor.process = None
    await close(t, task)
    sch = schema()
    for frame in t.frames():
        assert sch.validate_frame(frame) == [], frame
    assert [
        f["type"] for f in t.frames() if f["type"].startswith(("lifecycle.", "gpu.", "panel."))
    ] == ["lifecycle.show", "lifecycle.hide", "gpu.yield", "panel.visibility"]
    out = PROOF / "WP17" / "17.12"
    out.mkdir(parents=True, exist_ok=True)
    (out / "host_lifecycle_timing.json").write_text(
        json.dumps({"source": "backend host (simulated Verse frames)", **host.timings}, indent=2)
    )


SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|sk-ant-|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|xox[bp]-|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY|api[_-]?key|password|secret|bearer\s)",
    re.IGNORECASE,
)


async def test_no_secrets_cross_the_bridge(tmp_path: Path) -> None:
    """A17.8: a long busy session's every frame is scanned for key or credential patterns."""
    host, backend = make_host(tmp_path)
    backend.agents[0]["provider_key"] = "sk-proj-ABCDEFGHIJKLMNOP"
    backend.agents[0]["account_id"] = "ghp_ABCDEFGHIJKLMNOPQRSTUV"
    t, task = await connect(host)
    _cmd(
        t,
        "subscribe",
        "c-1",
        {"topics": ["roster", "progression", "groups", "meetings", "companion"]},
    )
    _cmd(t, "chat_tails.watch", "c-2", {"agents": ["ag_7f1"]})
    _cmd(t, "screens.watch", "c-3", {"panes": [{"pane_id": "ws_91:T1", "hz": 10}]})
    await t.reply_to("c-3")
    from dodaios.core.events import SocietyMessageSent

    for i in range(200):
        backend.agents[0]["run_state"] = "working" if i % 2 else "idle"
        await backend.bus.publish(SocietyMessageSent())
        await backend.attached["ws_91:T1"][0](f"\x1b[{i % 20 + 1};1Hbuild step {i} ok")
        await asyncio.sleep(0.005)
    await asyncio.sleep(0.3)
    await close(t, task)
    hits = []
    for raw in t.sent:
        text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
        if text.startswith('{"type":"welcome"'):
            # Locale strings are UI copy (they may say "password" as a word).
            text = text.split('"locale"')[0]
        hits += SECRET.findall(text)
    assert hits == [], hits
    assert len(t.sent) > 20


async def test_qa_exec_server_to_verse(tmp_path: Path, monkeypatch) -> None:
    """qa.exec S->V: the backend forwards a Verse.QA.* command and returns Verse's reply."""
    import pytest

    from dodaios.verse_host import protocol as P

    host, _ = make_host(tmp_path)
    monkeypatch.delenv("DODAIOS_VERSE_QA", raising=False)
    with pytest.raises(P.BridgeError):
        await host.qa_exec("Verse.QA.Stats", [])
    monkeypatch.setenv("DODAIOS_VERSE_QA", "1")
    t, task = await connect(host)
    pending = asyncio.ensure_future(host.qa_exec("Verse.QA.Stats", []))
    sent = await t.wait_for(lambda f: f["type"] == "qa.exec")
    assert sent["id"].startswith("s-") and sent["data"] == {"command": "Verse.QA.Stats", "args": []}
    t.push(
        {
            "type": "reply",
            "re": sent["id"],
            "ts": 1.0,
            "data": {"ok": True, "result": {"result": {"fps": 120}}},
        }
    )
    answer = await asyncio.wait_for(pending, 3)
    assert answer["result"]["result"] == {"fps": 120}
    await close(t, task)
