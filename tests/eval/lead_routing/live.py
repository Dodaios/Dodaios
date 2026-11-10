"""Opt-in live run: the golden set against one real seat, through the real tool catalog.

A live run bills whatever seat is chosen and is never part of CI. Nothing here
runs unless the owner invokes ``scripts/lead_routing_eval.py --live``. No tool
is ever executed: the first tool call a seat makes is recorded and the stream
is closed.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from .cases import Case
from .catalog import LeadCatalog
from .scoring import Recording

LIVE_ENV_FLAG = "DODAIOS_LEAD_ROUTING_LIVE"
PER_CASE_TIMEOUT_S = 90.0

#: A compact stand-in for the lead's briefing. The live app builds a much longer
#: prompt per turn (persona, team card, ecosystem notes); this one keeps the run
#: reproducible and cheap to read. Compare seats with each other, not with the app.
LEAD_SYSTEM = (
    "You are the lead of a personal super-agent: the one assistant the person talks to. "
    "You answer knowledge questions, chat and writing requests directly in text, with no tool. "
    "For everything that needs the person's apps, agents, coding panes, memory, settings or the "
    "outside world, you call exactly the one tool that fits first. Named society agents get work "
    "through delegate_to_agent and questions through message_agent. Coding panes (T1, T2, ...) "
    "are addressed by their id. Never start background work for a plain question."
)


@dataclass(frozen=True, slots=True)
class LiveGate:
    """Whether a live run may start, and what the owner must be told first."""

    allowed: bool
    billing: str  # "api" | "subscription" | "local"
    reasons: tuple[str, ...]
    notice: str


def billing_of(seat: str) -> str:
    from dodaios.brain import background_policy as policy

    if policy.keyless_local(seat):
        return "local"
    if policy.subscription_capable(seat):
        return "subscription"
    return "api"


def live_gate(
    seat: str,
    *,
    env: dict[str, str] | None = None,
    allow_api_key: bool = False,
    case_count: int = 0,
    tokens_per_call: int = 0,
) -> LiveGate:
    """Decide whether a live run on *seat* may start.

    It never starts without the explicit env flag, never in CI, and never on a
    per-token API key while a subscription is connected (the background policy's
    rule) unless the owner says ``--allow-api-key`` in the same command.
    """
    from dodaios.brain import background_policy as policy

    env = dict(os.environ) if env is None else env
    billing = billing_of(seat)
    reasons: list[str] = []
    if env.get("CI") or env.get("GITHUB_ACTIONS"):
        reasons.append("live routing evals never run in CI")
    if env.get(LIVE_ENV_FLAG) != "1":
        reasons.append(f"set {LIVE_ENV_FLAG}=1 to confirm you want a billed run")
    if billing == "api" and not policy.background_providers([seat]).permits(seat):
        if not allow_api_key:
            reasons.append(
                f"a subscription is connected and {seat!r} is a per-token API key; "
                "pass --allow-api-key to bill that key on purpose"
            )
    cost = {
        "api": "BILLS the per-token API key of this seat",
        "subscription": "spends this seat's subscription allowance",
        "local": "runs on the local model (free, but uses the GPU)",
    }[billing]
    notice = (
        f"LIVE routing eval on seat {seat!r}: {case_count} model calls, about "
        f"{tokens_per_call:,} input tokens each (the full lead tool catalog). This {cost}."
    )
    return LiveGate(not reasons, billing, tuple(reasons), notice)


def estimate_tokens_per_call(catalog: LeadCatalog) -> int:
    return len(json.dumps(catalog.offered(), default=str)) // 4 + len(LEAD_SYSTEM) // 4 + 40


def offerable(case: Case, catalog: LeadCatalog) -> bool:
    """A live run can offer only tools with a schema (session tools are name-only)."""
    if not case.expect.expects_tool:
        return True
    return any(name in catalog.tools for name in (*case.expect.tools, *case.expect.also_accept))


def build_brain(seat: str, model: str | None) -> Any:
    from dodaios.brain.resolver import _get_registry

    return _get_registry().instantiate(seat, **({"model": model} if model else {}))


async def first_move(brain: Any, utterance: str, tools: tuple[dict[str, Any], ...]) -> Recording:
    """Ask *brain* once; return its first tool call, or its text when it calls none."""
    from dodaios.core.protocols import BrainMessage, BrainRequest

    request = BrainRequest(
        messages=(BrainMessage(role="user", content=utterance),),
        tools=tools,
        system=LEAD_SYSTEM,
        temperature=0.0,
        max_tokens=1024,
        stream=True,
    )
    text: list[str] = []
    stream = brain.complete(request)
    try:
        async for delta in stream:
            call = getattr(delta, "tool_call", None)
            if call:
                args = call.get("input", call.get("arguments", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                return Recording(tool=str(call.get("name") or ""), input=dict(args or {}))
            if getattr(delta, "content", None):
                text.append(str(delta.content))
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
    return Recording(tool=None, text="".join(text)[:400])


async def run_live(
    cases: list[Case],
    catalog: LeadCatalog,
    brain: Any,
    *,
    concurrency: int = 4,
    progress: Any = None,
) -> dict[str, Recording]:
    """Record the first move of *brain* for every case. Errors become a recorded text."""
    tools = tuple(catalog.offered())
    gate = asyncio.Semaphore(max(1, concurrency))
    out: dict[str, Recording] = {}

    async def one(case: Case) -> None:
        async with gate:
            try:
                out[case.id] = await asyncio.wait_for(
                    first_move(brain, case.utterance, tools), PER_CASE_TIMEOUT_S
                )
            except Exception as exc:  # noqa: BLE001 - a failed call is a recorded miss
                out[case.id] = Recording(error=f"{type(exc).__name__}: {exc}"[:400])
            if progress is not None:
                progress(case, out[case.id])

    await asyncio.gather(*(one(case) for case in cases))
    return out
