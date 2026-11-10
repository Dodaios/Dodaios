#!/usr/bin/env python3
"""A scripted stand-in for the backend side of ``verse.bridge/1`` (G0.11).

Unreal packages that read bridge feeds test against this, never against a
live app (``docs/verse/unreal/work-packages.md`` 0.3). It speaks the frozen
transport of ``contracts/bridge-protocol.md``: one WebSocket at
``/api/verse/bridge`` on loopback, ``hello`` first, the close codes, ping and
pong, per-connection ``seq``, ``base`` on deltas, one reply per command, and
terminal cells as ``cells.bin/1`` binary frames or ``cells.json/1``. Every
frame it serves comes from the golden fixtures in
``unreal/Verse/Tests/Data/bridge/`` and is checked against the schema first.

    python scripts/unreal/fake_bridge.py --token <random>           # idle scenario
    python scripts/unreal/fake_bridge.py --scenario busy_panes --once --report out.json
    python scripts/unreal/fake_bridge.py --list
    python scripts/unreal/fake_bridge.py --check                    # validate every scenario

The token also comes from ``DODAIOS_VERSE_TOKEN``. ``--discovery FILE``
writes the dev discovery file ``{url, token, pid}`` (contract section 1).

Scenario run: after ``welcome`` the steps play in order at ``at_ms`` (times
``--speed``; 0 plays them back to back). A feed step waits until its topic is
subscribed (``roster``, ``groups``, ``meetings``, ``progression``,
``companion``) or its pane or agent is watched (``screens``, ``chat_tails``);
lifecycle and panel events go out at once. An ``expect`` step waits up to
``timeout_ms`` for a Verse frame of that type whose ``data`` holds the given
fields. Commands are answered from the scenario's ``replies`` queue, then
from the golden replies; ``subscribe``, ``screens.watch``,
``chat_tails.watch``, ``resync``, ``progression.told``, ``settings.set``,
``duel.result`` and ``qa.exec`` behave as the contract says. Roster and
groups deltas are applied to the fake's own state, so a ``resync`` sends the
current snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import hmac
import ipaddress
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: How many data objects of each received frame type the report keeps.
RECEIVED_DATA_CAP = 50

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from websockets.asyncio.server import ServerConnection, serve  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from scripts.unreal import bridge_cells, bridge_schema  # noqa: E402

PATH = "/api/verse/bridge"
SNAPSHOT_OF = {
    "roster": "roster.snapshot",
    "groups": "groups.snapshot",
    "progression": "progression.snapshot",
    "companion": "companion.snapshot",
}
#: Collections a delta's upsert/remove lists touch, with the id field of each row.
DELTA_KEYS = {
    "roster": {"agents": "agent_id", "panes": "pane_id"},
    "groups": {"groups": "group_id"},
}
MAX_SCREENS = 8
MAX_CHAT_AGENTS = 6
CLOSE_BAD_HELLO, CLOSE_TOKEN, CLOSE_PEER, CLOSE_REPLACED, CLOSE_PROTOCOL = (
    4400,
    4401,
    4403,
    4409,
    4426,
)


def scenario_names(data_dir: Path = bridge_schema.DATA_DIR) -> list[str]:
    return sorted(p.stem for p in (data_dir / "scenarios").glob("*.json"))


def load_scenario(name_or_path: str, data_dir: Path = bridge_schema.DATA_DIR) -> dict:
    path = Path(name_or_path)
    if not path.suffix:
        path = data_dir / "scenarios" / f"{name_or_path}.json"
    return bridge_schema.read_json(path)


def golden(type_: str, data_dir: Path = bridge_schema.DATA_DIR) -> list[dict]:
    return bridge_schema.read_json(data_dir / "messages" / f"{type_}.json")


def golden_reply(command: str, data_dir: Path = bridge_schema.DATA_DIR) -> dict:
    """The data of the first successful golden reply to ``command``."""
    for pair in bridge_schema.read_json(data_dir / "replies" / f"{command}.json"):
        if pair["reply"]["data"].get("ok") is True:
            return copy.deepcopy(pair["reply"]["data"])
    raise KeyError(command)


def apply_delta(state: dict, topic: str, data: dict) -> None:
    """Apply a roster or groups delta to a snapshot's data in place."""
    for key, id_field in DELTA_KEYS[topic].items():
        rows = state.setdefault(key, [])
        index = {row[id_field]: row for row in rows}
        for patch in data.get("upsert", {}).get(key, []):
            if patch[id_field] in index:
                index[patch[id_field]].update(copy.deepcopy(patch))
            else:
                rows.append(copy.deepcopy(patch))
                index[patch[id_field]] = rows[-1]
        gone = set(data.get("remove", {}).get(key, []))
        rows[:] = [row for row in rows if row[id_field] not in gone]
    if topic == "roster" and data.get("commander") is not None:
        state["commander"] = copy.deepcopy(data["commander"])


def _matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and _matches(v, actual[k]) for k, v in expected.items()
        )
    return expected == actual


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return host == "localhost"


@dataclass
class Report:
    scenario: str
    sent: dict[str, int] = field(default_factory=dict)
    received: dict[str, int] = field(default_factory=dict)
    #: The first RECEIVED_DATA_CAP data objects of each received type, in arrival order.
    received_data: dict[str, list] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    expectations: list[dict] = field(default_factory=list)
    invalid_from_verse: list[str] = field(default_factory=list)
    hung: bool = False
    done: bool = False

    @property
    def passed(self) -> bool:
        required_ok = all(e["ok"] or e["optional"] for e in self.expectations)
        return self.done and required_ok and not self.skipped and not self.invalid_from_verse

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "passed": self.passed,
            "done": self.done,
            "sent": dict(sorted(self.sent.items())),
            "received": dict(sorted(self.received.items())),
            "received_data": dict(sorted(self.received_data.items())),
            "skipped": self.skipped,
            "expectations": self.expectations,
            "invalid_from_verse": self.invalid_from_verse,
            "hung": self.hung,
        }


class Session:
    """One authenticated Verse connection."""

    def __init__(self, bridge: FakeBridge, ws: ServerConnection, hello: dict) -> None:
        self.bridge = bridge
        self.ws = ws
        self.hello = hello
        offered = hello["data"].get("encodings", {}).get("screens", [])
        self.encoding = "cells.bin/1" if "cells.bin/1" in offered else "cells.json/1"
        self.seq = 0
        self.last_seq: dict[str, int] = {}
        self.subscribed: set[str] = set()
        self.refs: dict[str, int] = {}
        self.next_ref = 1
        self.chat_agents: set[str] = set()
        self.screen_snapshots: dict[str, dict] = {}
        self.received: list[dict] = []
        self.changed = asyncio.Condition()
        self.last_frame = time.monotonic()
        self.duels: dict[str, dict] = {}

    # -------------------------------------------------------------- sending

    async def send(
        self, type_: str, data: Any, *, re: str | None = None, key: str | None = None
    ) -> int:
        self.seq += 1
        frame: dict[str, Any] = {"type": type_, "seq": self.seq, "ts": round(time.time(), 3)}
        if re is not None:
            frame["re"] = re
        if self.bridge.schema.is_delta(type_, data):
            frame["base"] = self.last_seq.get(key or type_, 1)
        frame["data"] = data
        if type_ != "reply" and key:
            self.last_seq[key] = self.seq
        await self.ws.send(json.dumps(frame, ensure_ascii=False))
        self.bridge.report.sent[type_] = self.bridge.report.sent.get(type_, 0) + 1
        return self.seq

    async def reply(self, request_id: str | None, data: dict) -> None:
        if request_id is not None:
            await self.send("reply", data, re=request_id)

    async def send_screen(self, type_: str, data: dict) -> None:
        pane_id = data["pane_id"]
        key = f"screens:{pane_id}"
        if type_ == "screens.gone":
            self.refs.pop(pane_id, None)
            self.screen_snapshots.pop(pane_id, None)
            await self.send(type_, data, key=key)
            return
        data = copy.deepcopy(data)
        ref = self.refs[pane_id]
        if data["kind"] == "snapshot":
            data["ref"] = ref
            self.screen_snapshots[pane_id] = data
        if self.encoding == "cells.json/1":
            await self.send("screens.frame", data, key=key)
            return
        if data["kind"] == "snapshot":
            meta = {k: data[k] for k in ("pane_id", "ref", "cols", "rows", "style", "cut", "at")}
            await self.send("screens.meta", meta)
        self.seq += 1
        base = self.last_seq.get(key, 1) if data["kind"] == "delta" else None
        blob = bridge_cells.encode(data, ref=ref, seq=self.seq, base=base)
        self.last_seq[key] = self.seq
        await self.ws.send(blob)
        self.bridge.report.sent["cells.bin/1"] = self.bridge.report.sent.get("cells.bin/1", 0) + 1

    async def send_snapshot(self, topic: str) -> None:
        type_ = SNAPSHOT_OF[topic]
        await self.send(type_, copy.deepcopy(self.bridge.state[type_]), key=topic)

    # -------------------------------------------------------------- receiving

    async def serve(self) -> None:
        async for raw in self.ws:
            self.last_frame = time.monotonic()
            if isinstance(raw, bytes):
                self.bridge.report.invalid_from_verse.append("binary frame from Verse")
                continue
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                self.bridge.report.invalid_from_verse.append("frame is not JSON")
                continue
            type_ = frame.get("type") if isinstance(frame, dict) else None
            counts = self.bridge.report.received
            counts[str(type_)] = counts.get(str(type_), 0) + 1
            kept = self.bridge.report.received_data.setdefault(str(type_), [])
            if len(kept) < RECEIVED_DATA_CAP and isinstance(frame, dict):
                kept.append(frame.get("data"))
            errors = self.bridge.schema.validate_frame(frame)
            entry = self.bridge.schema.entry(type_) if isinstance(type_, str) else None
            if errors:
                self.bridge.report.invalid_from_verse.extend(errors)
                if entry and entry["kind"] == "command" and isinstance(frame.get("id"), str):
                    await self.reply(frame["id"], _error("bad_request", errors[0]))
                continue
            async with self.changed:
                self.received.append(frame)
                self.changed.notify_all()
            if type_ == "ping":
                await self.send("pong", {})
            elif entry and entry["kind"] == "command":
                await self.command(frame)

    async def command(self, frame: dict) -> None:
        type_, rid, data = frame["type"], frame["id"], frame["data"]
        bridge = self.bridge
        features = set(bridge.welcome["features"])
        if type_ == "subscribe":
            wanted = data["topics"]
            served = [t for t in wanted if t in features]
            if not served:
                await self.reply(rid, _error("unavailable", "No requested topic is served."))
                return
            unavailable = [t for t in wanted if t not in features]
            await self.reply(rid, _ok({"subscribed": served, "unavailable": unavailable}))
            for topic in served:
                if topic in SNAPSHOT_OF and topic not in self.subscribed:
                    await self.send_snapshot(topic)
            await self._mark(lambda: self.subscribed.update(served))
        elif type_ == "unsubscribe":
            gone = [t for t in data["topics"] if t in self.subscribed]
            self.subscribed.difference_update(gone)
            await self.reply(rid, _ok({"unsubscribed": gone}))
        elif type_ == "resync":
            await self.resync(rid, data)
        elif type_ == "screens.watch":
            await self.watch_screens(rid, data["panes"])
        elif type_ == "chat_tails.watch":
            agents = data["agents"]
            watching, dropped = agents[:MAX_CHAT_AGENTS], agents[MAX_CHAT_AGENTS:]
            await self.reply(rid, _ok({"watching": watching, "dropped": dropped}))
            await self._mark(lambda: (self.chat_agents.clear(), self.chat_agents.update(watching)))
        elif type_ == "progression.told":
            snapshot = bridge.state["progression.snapshot"]
            snapshot["told_seq"] = max(snapshot.get("told_seq", 0), data["seq"])
            await self.reply(rid, _ok({"told_seq": snapshot["told_seq"]}))
        elif type_ == "settings.set":
            bridge.settings = _merge(bridge.settings, data)
            await self.reply(rid, _ok({"settings": copy.deepcopy(bridge.settings)}))
            await self.send("settings.changed", copy.deepcopy(data))
        elif type_ == "duel.result":
            if data["match_id"] not in self.duels:
                self.duels[data["match_id"]] = bridge.next_reply(type_)
            await self.reply(rid, copy.deepcopy(self.duels[data["match_id"]]))
        elif type_ == "qa.exec" and not bridge.qa:
            await self.reply(rid, _error("unavailable", "QA commands need DODAIOS_VERSE_QA=1."))
        elif type_ == "qa.exec":
            await self.reply(
                rid, _ok({"result": {"command": data["command"], "args": data.get("args", [])}})
            )
        else:
            await self.reply(rid, bridge.next_reply(type_))

    async def resync(self, rid: str, data: dict) -> None:
        topic = data["topic"]
        if topic == "screens":
            pane_id = data.get("pane_id")
            snapshot = self.screen_snapshots.get(pane_id)
            if pane_id not in self.refs or snapshot is None:
                await self.reply(rid, _error("not_found", "Pane is not watched."))
                return
            await self.reply(rid, _ok({}))
            await self.send_screen("screens.frame", snapshot)
        elif topic in SNAPSHOT_OF and topic in self.subscribed:
            await self.reply(rid, _ok({}))
            await self.send_snapshot(topic)
        else:
            await self.reply(rid, _error("not_found", f"Topic {topic} is not subscribed."))

    async def watch_screens(self, rid: str, panes: list[dict]) -> None:
        known = self.bridge.known_panes()
        bound, dropped, missing = [], [], []
        refs: dict[str, int] = {}
        for item in panes:
            pane_id = item["pane_id"]
            if pane_id not in known:
                missing.append(pane_id)
            elif len(refs) >= MAX_SCREENS:
                dropped.append(pane_id)
            else:
                refs[pane_id] = self.next_ref
                self.next_ref += 1
                bound.append({"pane_id": pane_id, "ref": refs[pane_id]})
        await self.reply(rid, _ok({"bound": bound, "dropped": dropped, "missing": missing}))
        await self._mark(lambda: (self.refs.clear(), self.refs.update(refs)))
        for pane_id in refs:
            if pane_id in self.screen_snapshots:
                await self.send_screen("screens.frame", self.screen_snapshots[pane_id])

    async def _mark(self, change) -> None:
        async with self.changed:
            change()
            self.changed.notify_all()

    # -------------------------------------------------------------- scenario

    def ready_for(self, frame: dict) -> bool:
        type_, data = frame["type"], frame["data"]
        topic = self.bridge.schema.topic_of(type_)
        if topic == "screens":
            return data["pane_id"] in self.refs
        if topic == "chat_tails":
            return data["agent_id"] in self.chat_agents
        if topic in SNAPSHOT_OF or topic == "meetings":
            return topic in self.subscribed
        return True

    async def run_scenario(self) -> None:
        bridge = self.bridge
        start = time.monotonic()
        for i, step in enumerate(bridge.scenario["steps"]):
            due = start + step["at_ms"] / 1000 * bridge.speed
            await asyncio.sleep(max(0.0, due - time.monotonic()))
            if "frame" in step:
                frame = step["frame"]
                try:
                    async with self.changed:
                        await asyncio.wait_for(
                            self.changed.wait_for(lambda f=frame: self.ready_for(f)), bridge.hold_s
                        )
                except TimeoutError:
                    bridge.report.skipped.append(
                        f"steps[{i}] {frame['type']}: topic never subscribed or watched"
                    )
                    continue
                await self.play(frame)
            else:
                await self.expect(step, start)
        bridge.report.done = True
        bridge.finished.set()

    async def play(self, frame: dict) -> None:
        type_, data = frame["type"], copy.deepcopy(frame["data"])
        topic = self.bridge.schema.topic_of(type_)
        if topic == "screens":
            await self.send_screen(type_, data)
            return
        if topic in DELTA_KEYS and type_.endswith(".delta"):
            apply_delta(self.bridge.state[SNAPSHOT_OF[topic]], topic, data)
        elif type_ in self.bridge.state:
            self.bridge.state[type_] = copy.deepcopy(data)
        key = topic if topic in SNAPSHOT_OF else None
        await self.send(type_, data, key=key)

    async def expect(self, step: dict, start: float) -> None:
        want = step["expect"]

        def found() -> bool:
            return any(
                f["type"] == want["type"] and _matches(want.get("data", {}), f["data"])
                for f in self.received
            )

        ok = True
        waited_from = time.monotonic()
        try:
            async with self.changed:
                await asyncio.wait_for(self.changed.wait_for(found), step["timeout_ms"] / 1000)
        except TimeoutError:
            ok = False
        waited_ms = round((time.monotonic() - waited_from) * 1000)
        if ok:
            # Consume the first match so a later expect waits for a fresh frame.
            for n, f in enumerate(self.received):
                if f["type"] == want["type"] and _matches(want.get("data", {}), f["data"]):
                    del self.received[n]
                    break
        self.bridge.report.expectations.append(
            {
                "type": want["type"],
                "data": want.get("data", {}),
                "ok": ok,
                "waited_ms": waited_ms,
                "optional": bool(step.get("optional")),
            }
        )

    async def watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            if time.monotonic() - self.last_frame > 5.0 and not self.bridge.report.hung:
                self.bridge.report.hung = True
                print(
                    "fake bridge: no frame from Verse for 5 s (hung)", file=sys.stderr, flush=True
                )


class FakeBridge:
    def __init__(
        self,
        token: str,
        scenario: dict,
        *,
        speed: float = 1.0,
        qa: bool = False,
        hello_timeout: float = 5.0,
        hold_s: float = 30.0,
        data_dir: Path = bridge_schema.DATA_DIR,
    ) -> None:
        self.token = token
        self.scenario = scenario
        self.speed = speed
        self.qa = qa
        self.hello_timeout = hello_timeout
        self.hold_s = hold_s
        self.data_dir = data_dir
        self.schema = bridge_schema.Schema(
            bridge_schema.read_json(data_dir / bridge_schema.SCHEMA_FILE)
        )
        problems = self.schema.validate_scenario(scenario)
        if problems:
            raise ValueError("invalid scenario: " + "; ".join(problems[:5]))
        self.welcome = copy.deepcopy(golden("welcome", data_dir)[0]["data"])
        self.settings = copy.deepcopy(self.welcome["settings"])
        self.state = {
            t: copy.deepcopy(golden(t, data_dir)[0]["data"]) for t in SNAPSHOT_OF.values()
        }
        self.state.update(copy.deepcopy(scenario["state"]))
        self.replies = {k: copy.deepcopy(v) for k, v in scenario["replies"].items()}
        self.report = Report(scenario["name"])
        self.finished = asyncio.Event()
        self.closed = asyncio.Event()
        self.session: Session | None = None
        self.url = ""
        self._server = None

    def known_panes(self) -> set[str]:
        panes = {p["pane_id"] for p in self.state["roster.snapshot"]["panes"]}
        for step in self.scenario["steps"]:
            frame = step.get("frame")
            if frame and frame["type"].startswith("screens."):
                panes.add(frame["data"]["pane_id"])
        return panes

    def next_reply(self, command: str) -> dict:
        queue = self.replies.get(command)
        if queue:
            return queue.pop(0)
        return golden_reply(command, self.data_dir)

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        def process_request(connection, request):
            if request.path.split("?")[0] != PATH:
                return connection.respond(404, "Not a verse.bridge endpoint.\n")
            return None

        self._server = await serve(
            self._handle,
            host,
            port,
            process_request=process_request,
            max_size=1 << 20,
            ping_interval=None,
        )
        bound = self._server.sockets[0].getsockname()
        shown = f"[{bound[0]}]" if ":" in bound[0] else bound[0]
        self.url = f"ws://{shown}:{bound[1]}{PATH}"
        return self.url

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, ws: ServerConnection) -> None:
        if not _is_loopback(str(ws.remote_address[0])):
            await ws.close(CLOSE_PEER, "Loopback peers only.")
            return
        try:
            raw = await asyncio.wait_for(ws.recv(), self.hello_timeout)
            hello = json.loads(raw)
        except (TimeoutError, json.JSONDecodeError, TypeError, ConnectionClosed):
            await ws.close(CLOSE_BAD_HELLO, "Expected hello.")
            return
        if (
            not isinstance(hello, dict)
            or hello.get("type") != "hello"
            or self.schema.validate_frame(hello)
        ):
            await ws.close(CLOSE_BAD_HELLO, "Malformed hello.")
            return
        if not hmac.compare_digest(str(hello["data"]["token"]).encode(), self.token.encode()):
            await ws.close(CLOSE_TOKEN, "Wrong token.")
            return
        if bridge_schema.PROTOCOL not in hello["data"]["protocols"]:
            await ws.close(CLOSE_PROTOCOL, json.dumps({"supported": [bridge_schema.PROTOCOL]}))
            return
        previous = self.session
        if previous is not None:
            await previous.ws.close(CLOSE_REPLACED, "replaced")
        session = self.session = Session(self, ws, hello)
        welcome = copy.deepcopy(self.welcome)
        welcome["encoding"] = {"screens": session.encoding}
        welcome["settings"] = copy.deepcopy(self.settings)
        welcome["app_pid"] = os.getpid()
        await session.send("welcome", welcome)
        tasks = [
            asyncio.create_task(session.run_scenario()),
            asyncio.create_task(session.watchdog()),
        ]
        try:
            await session.serve()
        except ConnectionClosed:
            pass
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if self.session is session:
                self.session = None
                self.closed.set()


def _ok(result: dict) -> dict:
    return {"ok": True, "result": result}


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def write_discovery(path: Path, url: str, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"url": url, "token": token, "pid": os.getpid()}), encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


async def _run(args: argparse.Namespace, token: str) -> int:
    bridge = FakeBridge(token, load_scenario(args.scenario), speed=args.speed, qa=args.qa)
    url = await bridge.start(args.host, args.port)
    if args.discovery:
        write_discovery(Path(args.discovery), url, token)
    print(f"fake bridge listening on {url} (scenario {bridge.scenario['name']})", flush=True)
    try:
        if args.once:
            await bridge.finished.wait()
            await bridge.closed.wait()
        else:
            await asyncio.Event().wait()
    finally:
        await bridge.stop()
        _finish(args, bridge.report.as_dict())
    return 0 if bridge.report.passed else 1


def _finish(args: argparse.Namespace, report: dict) -> None:
    if args.discovery:
        with contextlib.suppress(OSError):
            Path(args.discovery).unlink()
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--token", default=os.environ.get("DODAIOS_VERSE_TOKEN"), help="launch token"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--scenario", default="idle", help="scenario name or JSON path")
    parser.add_argument(
        "--speed", type=float, default=1.0, help="time scale of at_ms; 0 plays at once"
    )
    parser.add_argument(
        "--once", action="store_true", help="exit when the scenario ends and Verse disconnects"
    )
    parser.add_argument("--report", help="write the run report JSON here")
    parser.add_argument("--discovery", help="write the dev discovery file {url, token, pid} here")
    parser.add_argument(
        "--qa", action="store_true", help="answer qa.exec as DODAIOS_VERSE_QA=1 would"
    )
    parser.add_argument("--list", action="store_true", help="list the scenarios")
    parser.add_argument("--check", action="store_true", help="validate every scenario and exit")
    args = parser.parse_args(argv)
    if args.list:
        for name in scenario_names():
            print(f"{name}: {load_scenario(name)['description']}")
        return 0
    if args.check:
        schema = bridge_schema.load()
        errors = [
            e for name in scenario_names() for e in schema.validate_scenario(load_scenario(name))
        ]
        print("\n".join(errors) or f"{len(scenario_names())} scenarios: OK")
        return 1 if errors else 0
    token = args.token
    if not token:
        token = secrets.token_urlsafe(32)
        print(f"token: {token}", flush=True)
    try:
        return asyncio.run(_run(args, token))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
