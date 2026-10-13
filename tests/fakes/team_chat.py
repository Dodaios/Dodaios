"""Deterministic chat turns for team-lead tests; no provider calls.

Every ``send`` starts a turn as its own task, like the real service: the
session is busy until the turn ends, subscribers receive its events, and
``wait_turn`` joins it. ``scripts[session_id]`` decides what a turn does (a
lead's script calls the engine's tools); a session without one answers with
``replies[session_id]``. ``gates[session_id]`` holds a turn open until set.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.agent_chat.events import make_event
from jarvis.agent_chat.service import SessionBusy
from jarvis.agent_chat.store import AgentChatStore

Script = Callable[[str, dict[str, Any]], Awaitable[str]]


class TeamChatFake:
    supports_turn_completion = True

    def __init__(self, store: AgentChatStore) -> None:
        self.store = store
        self.sent: list[tuple[str, str, dict[str, Any], str]] = []
        self.scripts: dict[str, Script] = {}
        self.replies: dict[str, str] = {}
        self.gates: dict[str, asyncio.Event] = {}
        self.failing: set[str] = set()
        self.cancelled: list[tuple[str, str | None]] = []
        self.busy: set[str] = set()
        self._turns: dict[str, asyncio.Task[None]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    # ------------------------------------------------------------- reads

    def is_running(self, session_id: str) -> bool:
        return session_id in self.busy

    def running_session_ids(self) -> list[str]:
        return list(self.busy)

    def prompts(self, session_id: str) -> list[str]:
        return [text for sid, text, _, _ in self.sent if sid == session_id]

    def idle(self) -> bool:
        return not self.busy

    # --------------------------------------------------------- subscribe

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.get(session_id, set()).discard(queue)

    def _emit(self, session_id: str, kind: str, payload: dict[str, Any]) -> None:
        event = self.store.append_event(session_id, make_event(kind, payload))
        for queue in list(self._subscribers.get(session_id, ())):
            queue.put_nowait(event)

    # -------------------------------------------------------------- turns

    async def send(self, session_id: str, text: str, **kwargs: Any) -> str:
        if session_id in self.busy:
            raise SessionBusy(session_id)
        turn_id = f"turn-{len(self.sent)}"
        self.sent.append((session_id, text, kwargs, turn_id))
        self.busy.add(session_id)
        # As the real service does: the prompt of a turn is part of the chat.
        self._emit(session_id, "user_message", {"text": text})
        self._turns[session_id] = asyncio.create_task(
            self._run(session_id, turn_id, text, kwargs)
        )
        return turn_id

    async def _run(self, session_id: str, turn_id: str, text: str, kwargs: dict[str, Any]) -> None:
        status, reply, error = "done", "", ""
        try:
            gate = self.gates.get(session_id)
            if gate is not None:
                await gate.wait()
            if session_id in self.failing:
                raise RuntimeError("provider unavailable")
            script = self.scripts.get(session_id)
            if script is not None:
                reply = await script(text, kwargs)
            else:
                reply = self.replies.get(session_id, f"Done by {session_id}")
        except asyncio.CancelledError:
            status = "cancelled"
        except Exception as exc:  # noqa: BLE001 — a failing turn ends as an error event
            status, error = "error", str(exc)
        if reply:
            self._emit(session_id, "assistant_text", {"turn_id": turn_id, "text": reply})
        payload = {"turn_id": turn_id, "status": status}
        if error:
            payload["error"] = error
        # Free the session before the terminal is seen, as the service does.
        self.busy.discard(session_id)
        self._emit(session_id, "turn_finished", payload)

    async def wait_turn(self, session_id: str) -> None:
        task = self._turns.get(session_id)
        if task is not None:
            await asyncio.shield(task)

    async def cancel(self, session_id: str, *, expected_turn_id: str | None = None) -> bool:
        self.cancelled.append((session_id, expected_turn_id))
        task = self._turns.get(session_id)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.wait({task})
        return True

    async def post_notice(self, session_id: str, payload: dict[str, Any]) -> None:
        self._emit(session_id, "notice", payload)

    async def close(self) -> None:
        for task in self._turns.values():
            task.cancel()
        if self._turns:
            await asyncio.wait(set(self._turns.values()))


class FakeTasks:
    """The slice of the task store and scheduler a routine needs."""

    def __init__(self) -> None:
        self.specs: dict[str, Any] = {}
        self.cancelled: list[str] = []

    async def schedule(self, spec: Any, **_: Any) -> str:
        self.specs[str(spec.id)] = spec
        return str(spec.id)

    async def cancel_task(self, task_id: str) -> None:
        self.cancelled.append(task_id)

    async def delete(self, task_id: str) -> None:
        self.specs.pop(task_id, None)

    async def list(self, limit: int = 1000) -> list[dict[str, Any]]:
        return [
            {"id": task_id, "title": spec.title, "state": "scheduled",
             "spec_json": spec.model_dump_json()}
            for task_id, spec in self.specs.items()
        ]
