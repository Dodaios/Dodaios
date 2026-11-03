"""Test doubles for the verse host: a fake backend port, bus and in-memory socket."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from dodaios.verse_host.bridge import TransportClosed
from dodaios.verse_host.ports import NotFound, UnknownWorldAction

FIXTURES = Path(__file__).parent / "fixtures" / "bridge"
TOKEN = "t" * 43


def golden(type_: str) -> list[dict]:
    return json.loads((FIXTURES / "messages" / f"{type_}.json").read_text(encoding="utf-8"))


def golden_replies(command: str) -> list[dict]:
    return json.loads((FIXTURES / "replies" / f"{command}.json").read_text(encoding="utf-8"))


def schema():
    from scripts.unreal import bridge_schema

    return bridge_schema.load()


class FakeBus:
    def __init__(self) -> None:
        self.handlers: dict[type, list[Any]] = defaultdict(list)
        self.published: list[Any] = []

    def subscribe(self, event_type: type, handler: Any) -> None:
        self.handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Any) -> None:
        if handler in self.handlers[event_type]:
            self.handlers[event_type].remove(handler)

    async def publish(self, event: Any) -> None:
        self.published.append(event)
        for handler in list(self.handlers[type(event)]):
            await handler(event)


class FakeDuelService:
    def __init__(self) -> None:
        self.results: dict[str, dict] = {}

    def duel_stats(self) -> dict[str, Any]:
        wins = sum(1 for r in self.results.values() if r["outcome"] == "won")
        return {"matches": len(self.results), "wins": wins}

    def record_duel(self, result: dict[str, Any]) -> dict[str, Any]:
        first = result["match_id"] not in self.results
        self.results.setdefault(result["match_id"], result)
        awards = (
            [{"xp_source": "duel_won", "xp": 60}] if first and result["outcome"] == "won" else []
        )
        return {"recorded": True, "awards": awards, "duel_stats": self.duel_stats()}


class FakeBackend:
    """Every read the relays make, from plain lists the test edits."""

    def __init__(self) -> None:
        self.bus = FakeBus()
        self.agents: list[dict[str, Any]] = [
            {
                "agent_id": "ag_7f1",
                "name": "Mara",
                "title": "Research scout",
                "tier": "specialist",
                "state": "active",
                "run_state": "waiting",
                "waiting_reason": "question",
                "avatar": {"look": "look_02", "archetype": "engineer", "palette": "graphite"},
                "session_id": "society:ag_7f1",
                "api_key": "sk-ant-secret-should-never-cross",
                "description": "standing instructions stay in the app",
            }
        ]
        self.panes: list[dict[str, Any]] = [
            {
                "workspace_id": "ws_91",
                "key": "T1",
                "name": "T1",
                "history_id": "h_55",
                "display_name": "Claude Code",
                "agent": "claude",
                "title": "Fix the login retry",
                "status": "live",
                "activity": "working",
                "activity_since": 1793612301.0,
                "worked": True,
                "cols": 132,
                "rows": 40,
                "prompt": "secret prompt text",
            }
        ]
        self.subjects = [
            {
                "subject_id": "person",
                "kind": "person",
                "level": 14,
                "xp": 5230,
                "xp_into_level": 130,
                "xp_for_next": 600,
                "title": "Lieutenant",
            },
            {
                "subject_id": "agent:ag_7f1",
                "kind": "agent",
                "level": 6,
                "xp": 400,
                "xp_into_level": 10,
                "xp_for_next": 90,
                "title": "Ensign",
            },
        ]
        self.groups = [
            {"group_id": "grp_a", "name": "Release crew", "members": ["ag_7f1", "ag_02c"]}
        ]
        self.meetings: dict[str, dict] = {"grp_a": {"messages": [], "running": False, "room": None}}
        self.chats: dict[str, list[dict]] = {
            "society:ag_7f1": [
                {"seq": 1, "kind": "user_message", "payload": {"text": "Check the retry window."}},
                {"seq": 2, "kind": "tool_call", "payload": {"name": "mcp__x__read_file"}},
            ]
        }
        self.actions: list[tuple[str, str]] = []
        self.created: list[dict] = []
        self.opened: list[tuple[str | None, str]] = []
        self.prompts: list[tuple[str, str, str]] = []
        self.duel: FakeDuelService | None = None
        self.confirm = True
        self.screens: dict[str, dict] = {}
        self.attached: dict[str, Any] = {}
        self.attach_fails: set[str] = set()
        self.launch_gate: asyncio.Event | None = None
        self.pet = {"pet_id": "drone", "look": "drone", "style": "default"}

    async def list_agents(self) -> list[dict[str, Any]]:
        return [dict(a) for a in self.agents]

    async def list_panes(self) -> list[dict[str, Any]]:
        return [dict(p) for p in self.panes]

    async def progression(self) -> dict[str, Any]:
        return {
            "subjects": [dict(s) for s in self.subjects],
            "pet_id": "drone",
            "latest_seq": 902,
            "ranks": [{"id": "recruit", "level": 1, "tier": "deck"}],
            "rewards": [],
            "looks": [],
            "titles": {"person": [{"level": 1, "title": "Cadet"}]},
        }

    async def report_action(self, action: str, ref: str) -> dict[str, Any] | None:
        if action == "bogus":
            raise UnknownWorldAction(action)
        self.actions.append((action, ref))
        return None

    def duel_service(self) -> Any:
        return self.duel

    async def chat_tail(self, session_id: str, tail: int) -> list[dict[str, Any]] | None:
        events = self.chats.get(session_id)
        return None if events is None else events[-tail:]

    async def chat_groups(self) -> list[dict[str, Any]]:
        return [dict(g) for g in self.groups]

    async def group_meeting(self, group_id: str) -> dict[str, Any] | None:
        return self.meetings.get(group_id)

    async def meeting_start(self, group_id: str, text: str) -> dict[str, Any]:
        if group_id not in self.meetings:
            raise NotFound(group_id)
        self.meetings[group_id] = {
            "running": True,
            "messages": [{"id": "r1", "speaker": "user", "text": text}],
            "room": {
                "room_id": "room_44",
                "phase": "open",
                "topic": text,
                "rounds": 0,
                "max_rounds": 4,
            },
        }
        return self.meetings[group_id]

    async def meeting_stop(self, group_id: str) -> dict[str, Any]:
        if group_id not in self.meetings:
            raise NotFound(group_id)
        self.meetings[group_id]["running"] = False
        return self.meetings[group_id]

    async def confirm_dangerous(self, action: str, detail: str) -> bool:
        return self.confirm

    async def create_agent(self, fields: dict[str, Any]) -> str:
        self.created.append(fields)
        return f"ag_new{len(self.created)}"

    async def ide_state(self) -> dict[str, Any]:
        return {"active_id": "ws_91", "workspaces": [{"id": "ws_91", "name": "dodaios"}]}

    async def ide_agents(self) -> list[dict[str, Any]]:
        return [
            {"name": "claude", "display_name": "Claude Code", "installed": True},
            {"name": "shell", "kind": "shell", "installed": True},
        ]

    async def open_terminal(self, workspace_id: str | None, agent: str) -> tuple[str, str]:
        if self.launch_gate is not None:
            await self.launch_gate.wait()
        ws = workspace_id or "ws_91"
        name = f"T{len(self.panes) + 1}"
        self.opened.append((ws, name))
        self.panes.append(
            {
                "workspace_id": ws,
                "key": name,
                "name": name,
                "status": "live",
                "activity": "starting",
                "agent": agent,
            }
        )
        return ws, name

    async def start_terminal(self, name: str, workspace_id: str) -> None:
        return None

    async def prompt_terminal(self, name: str, text: str, workspace_id: str) -> bool | None:
        self.prompts.append((workspace_id, name, text))
        return True

    async def active_pet(self) -> dict[str, Any]:
        return dict(self.pet)

    async def attach_screen(self, pane_id: str, on_output: Any, on_exit: Any) -> tuple[int, int]:
        if pane_id in self.attach_fails or not any(
            f"{p['workspace_id']}:{p['key']}" == pane_id for p in self.panes
        ):
            raise NotFound(pane_id)
        self.attached[pane_id] = (on_output, on_exit)
        return (80, 24)

    def detach_screen(self, pane_id: str, on_output: Any) -> None:
        self.attached.pop(pane_id, None)

    def plain_screen(self, pane_id: str) -> dict[str, Any] | None:
        return self.screens.get(pane_id)


class MemoryTransport:
    """One side of an in-memory WebSocket: the test plays Verse."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[str | bytes | None] = asyncio.Queue()
        self.sent: list[str | bytes] = []
        self.closed_with: tuple[int, str] | None = None
        self._new = asyncio.Event()

    # --- server side (Transport protocol)
    async def receive(self) -> str | bytes:
        item = await self.inbox.get()
        if item is None:
            raise TransportClosed()
        return item

    async def send_text(self, text: str) -> None:
        if self.closed_with is not None:
            raise TransportClosed()
        self.sent.append(text)
        self._new.set()

    async def send_bytes(self, data: bytes) -> None:
        if self.closed_with is not None:
            raise TransportClosed()
        self.sent.append(data)
        self._new.set()

    async def close(self, code: int, reason: str = "") -> None:
        if self.closed_with is None:
            self.closed_with = (code, reason)
        await self.inbox.put(None)
        self._new.set()

    # --- Verse side
    def push(self, frame: dict | str | bytes) -> None:
        self.inbox.put_nowait(json.dumps(frame) if isinstance(frame, dict) else frame)

    def frames(self) -> list[dict]:
        return [json.loads(f) for f in self.sent if isinstance(f, str)]

    def binary(self) -> list[bytes]:
        return [f for f in self.sent if isinstance(f, bytes)]

    def of_type(self, type_: str) -> list[dict]:
        return [f for f in self.frames() if f["type"] == type_]

    async def wait_for(self, pred: Any, within: float = 3.0) -> Any:
        loop = asyncio.get_running_loop()
        end = loop.time() + within
        while True:
            for f in self.frames():
                if pred(f):
                    return f
            left = end - loop.time()
            if left <= 0:
                raise AssertionError(f"no matching frame; got {[f['type'] for f in self.frames()]}")
            self._new.clear()
            try:
                await asyncio.wait_for(self._new.wait(), left)
            except TimeoutError:
                pass

    async def reply_to(self, rid: str, within: float = 3.0) -> dict:
        return await self.wait_for(lambda f: f["type"] == "reply" and f.get("re") == rid, within)


def hello(token: str = TOKEN, **extra: Any) -> dict:
    data = {
        "token": token,
        "protocols": ["verse.bridge/1"],
        "build": {
            "version": "0.1.0",
            "changelist": "a1b2c3d",
            "config": "Shipping",
            "platform": "Win64",
        },
        "pid": 23144,
        "last_seq": 0,
        "encodings": {"screens": ["cells.bin/1", "cells.json/1"]},
        "capabilities": {"panel_stream": True, "duel": True},
    }
    data.update(extra)
    return {"type": "hello", "ts": 1.0, "data": data}


def make_host(tmp_path: Path, backend: FakeBackend | None = None, **kwargs: Any):
    from dodaios.verse_host.host import VerseHost
    from dodaios.verse_host.settings_store import SettingsStore

    class _App:
        class state:  # noqa: N801
            config = None

    backend = backend or FakeBackend()
    host = VerseHost(
        _App(),
        backend=backend,
        store=SettingsStore(tmp_path / "settings.json"),
        data_dir=tmp_path,
        app_version="4.1.1",
        **kwargs,
    )
    host.tokens.set("launch", TOKEN)
    return host, backend


async def connect(host: Any, *, peer: str = "127.0.0.1", **hello_extra: Any):
    """Start a session; returns ``(transport, serve_task)`` after ``welcome``."""
    t = MemoryTransport()
    t.push(hello(**hello_extra))
    task = asyncio.ensure_future(host.hub.serve(t, peer))
    await t.wait_for(lambda f: f["type"] == "welcome")
    return t, task


async def close(t: MemoryTransport, task: asyncio.Task) -> None:
    t.inbox.put_nowait(None)
    await asyncio.wait_for(task, 5)
