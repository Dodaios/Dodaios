"""Scripted peers and a scripted folder for team-thread tests.

``FakeTurns`` implements the engine's ``TurnPort``: each member is a session
whose answers come from a script keyed by the step the coordinator asked for.
``FakeWorkspace`` stands in for the git snapshots.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from dodaios.agent_chat.team.port import TurnResult
from dodaios.agent_chat.team.workspace import Change

AGREE = '```team-verdict\n{"verdict": "agree", "objections": []}\n```'
APPROVE = '```team-verdict\n{"verdict": "approve", "findings": []}\n```'


def object_to(*reasons: str) -> str:
    items = ", ".join(f'"{reason}"' for reason in reasons)
    return f'I object.\n```team-verdict\n{{"verdict": "object", "objections": [{items}]}}\n```'


def changes(issue: str, *, severity: str = "blocking", where: str = "app.py:3") -> str:
    return (
        "Found a defect.\n```team-verdict\n"
        f'{{"verdict": "changes", "findings": [{{"severity": "{severity}", '
        f'"where": "{where}", "issue": "{issue}", "fix": "handle it"}}]}}\n```'
    )


def plan(*titles: str, reopen: tuple[int, ...] = ()) -> str:
    """A planner's reply: a few words and the plan's typed block."""
    steps = ", ".join(
        f'{{"title": "{title}", "goal": "Do {title}", "done_when": "{title} works"}}'
        for title in titles
    )
    extra = f', "reopen": [{", ".join(str(n) for n in reopen)}]' if reopen else ""
    return f'Here is the plan.\n```team-plan\n{{"steps": [{steps}]{extra}}}\n```'


def step_report(number: int, status: str = "done", *, note: str = "", plan_change: str = "") -> str:
    return (
        f"Built step {number}.\n```team-step\n"
        f'{{"step": {number}, "status": "{status}", "note": "{note}", '
        f'"plan_change": "{plan_change}"}}\n```'
    )


def step_of(prompt: str) -> str:
    """Which step a coordinator prompt asks for."""
    # The planner-and-builder mode names each step in one line of its own.
    if "Your step: write the plan" in prompt or "Your step: revise the plan" in prompt:
        return "plan_version"
    if "Your step: review the plan" in prompt:
        return "plan_review"
    if "Your step: build step" in prompt:
        return "step_build"
    if "Your step: review step" in prompt:
        return "step_review"
    if "Your step: final review" in prompt:
        return "review"
    if "Your step: answer the final review" in prompt:
        return "fix"
    if "Step 1 of 5" in prompt:
        return "draft"
    if "Step 2 of 5" in prompt:
        return "critique"
    if "Step 3 of 5: master plan" in prompt:
        return "plan"
    if "Step 3 of 5: agree or object" in prompt:
        return "vote"
    if "Step 4 of 5" in prompt:
        return "build"
    if "Step 5 of 5: answer the review" in prompt:
        return "fix"
    if "Step 5 of 5: review" in prompt:
        return "review"
    raise AssertionError(f"unknown step in prompt: {prompt[:120]}")


@dataclass
class Asked:
    provider: str
    step: str
    prompt: str


@dataclass
class FakeTurns:
    #: ``(provider, step, nth time this provider was asked this step) -> reply``.
    #: A string is the final message; a ``TurnResult`` is returned as it is.
    script: Callable[[str, str, int], str | TurnResult] | None = None
    asked: list[Asked] = field(default_factory=list)
    sessions: dict[str, str] = field(default_factory=dict)
    discarded: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    remodelled: list[tuple[str, str]] = field(default_factory=list)
    #: Sessions whose stopped turn has fully unwound, and the slow ones.
    stopped: list[str] = field(default_factory=list)
    slow_to_stop: set[str] = field(default_factory=set)
    #: Steps that wait for ``release`` before they answer.
    hold: set[str] = field(default_factory=set)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    refuse: set[str] = field(default_factory=set)
    cost_usd: float | None = None
    _arrived: asyncio.Event = field(default_factory=asyncio.Event)

    async def reached(self, step: str, count: int) -> None:
        """Return once ``count`` turns of ``step`` have been asked for."""
        while sum(1 for a in self.asked if a.step == step) < count:
            self._arrived.clear()
            await self._arrived.wait()

    def open(self, *, provider: str, model: str, effort: str, cwd: str, title: str) -> str:
        if provider in self.refuse:
            raise ValueError(f"Unknown agent-chat provider: {provider!r}")
        session_id = f"s{len(self.sessions) + 1}"
        self.sessions[session_id] = provider
        return session_id

    async def ask(
        self, session_id: str, prompt: str, *, display: str, language: str, timeout_s: float
    ) -> TurnResult:
        provider = self.sessions[session_id]
        step = step_of(prompt)
        nth = sum(1 for a in self.asked if a.provider == provider and a.step == step)
        self.asked.append(Asked(provider, step, prompt))
        self._arrived.set()
        if step in self.hold:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.append(session_id)
                if provider in self.slow_to_stop:
                    # A CLI that takes a moment to die after it was told to stop.
                    await asyncio.sleep(0.05)
                self.stopped.append(session_id)
                raise
        await asyncio.sleep(0)
        reply: Any = self.script(provider, step, nth) if self.script else None
        if reply is None:
            reply = default_reply(provider, step)
        if isinstance(reply, TurnResult):
            return reply
        return TurnResult("ok", text=reply, cost_usd=self.cost_usd, duration_ms=5)

    def remodel(self, session_id: str, model: str) -> None:
        self.remodelled.append((session_id, model))

    def waiting(self, session_id: str) -> bool:
        return False

    def discard(self, session_id: str) -> None:
        self.discarded.append(session_id)

    def prompts(self, provider: str, step: str) -> list[str]:
        return [a.prompt for a in self.asked if a.provider == provider and a.step == step]


def default_reply(provider: str, step: str) -> str:
    """A team where everybody agrees at once."""
    if step in ("vote", "plan_review"):
        return f"Fine by {provider}.\n{AGREE}"
    if step in ("review", "step_review"):
        return f"{provider} read the change.\n{APPROVE}"
    if step == "plan_version":
        return plan("Add the setting", "Use it in the uploader")
    if step == "step_build":
        return step_report(1)
    return f"{step} by {provider}"


@dataclass
class FakeWorkspace:
    """Snapshots that change only when a test says the folder changed."""

    tree: str | None = "tree-0"
    files: tuple[str, ...] = ("app.py",)

    def touch(self) -> None:
        number = int((self.tree or "tree-0").rsplit("-", 1)[1]) + 1
        self.tree = f"tree-{number}"

    def snapshot(self, cwd: str) -> str | None:
        return self.tree

    def change(self, cwd: str, base: str, head: str, *, limit: int = 40_000) -> Change:
        if base == head:
            return Change((), "", "", False)
        return Change(self.files, f"{len(self.files)} file changed", "+new line", False)
