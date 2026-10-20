"""The one model call before a coding run: a short plan and a size estimate.

It runs only when a build was admitted to building (or accepted), never for a
proposal, and only on a connected subscription
(``brain.resolver.resolve_subscription_brain``). Without one there is no call
at all: the coding agent plans for itself and the estimate stays unknown.
Every call runs inside :func:`dodaios.self_build.cost.attributed`, so the
ledger shows what it cost.

An estimate of ``large`` stops the build before any coding: large work is not
something to hand an unattended agent.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from loguru import logger

from ..cost import attributed
from .github import Issue

SIZES: Final[tuple[str, ...]] = ("small", "medium", "large")
_MAX_TOKENS: Final[int] = 900
_SYSTEM: Final[str] = (
    "You plan a change for an unattended coding agent. Read the issue and the project "
    "brief. Answer in exactly this form and nothing else:\n"
    "SIZE: small | medium | large\n"
    "PLAN:\n- step\n- step\n"
    "small = one file or a few lines; medium = a few files with tests; large = design "
    "work, many files, or anything unclear. Say large when unsure."
)


@dataclass(frozen=True, slots=True)
class Plan:
    text: str = ""
    #: ``small`` | ``medium`` | ``large`` | ``""`` (no estimate).
    size: str = ""
    writer: str = ""


def parse(answer: str) -> Plan:
    size = ""
    match = re.search(r"(?im)^\s*SIZE\s*:\s*(small|medium|large)\b", answer)
    if match:
        size = match.group(1).lower()
    plan = answer.split("PLAN:", 1)[1] if "PLAN:" in answer else ""
    return Plan(text=plan.strip()[:2_000], size=size)


def _subscription_brain() -> Any | None:
    from dodaios.brain.resolver import resolve_subscription_brain
    from dodaios.core.config import load_config

    return resolve_subscription_brain(load_config())


async def plan(
    build_id: str,
    issue: Issue,
    brief_text: str,
    *,
    brain: Callable[[], Any | None] = _subscription_brain,
) -> Plan:
    """At most one call; an empty :class:`Plan` when no subscription can answer."""
    from dodaios.core.protocols import BrainMessage, BrainRequest

    try:
        model = await asyncio.to_thread(brain)
    except Exception:  # noqa: BLE001 - no brain is an answer: the agent plans itself
        logger.opt(exception=True).info("self-build code: no subscription brain for the plan")
        model = None
    if model is None:
        return Plan()
    prompt = (
        f"Issue #{issue.number}: {issue.title}\n\n{issue.body[:4_000]}\n\n"
        f"Project brief:\n{brief_text[:5_000]}"
    )
    request = BrainRequest(
        messages=(BrainMessage(role="user", content=prompt),),
        system=_SYSTEM,
        temperature=0.1,
        max_tokens=_MAX_TOKENS,
        stream=True,
        reasoning_effort="low",
    )
    chunks: list[str] = []
    try:
        with attributed(build_id):
            async for delta in model.complete(request):
                if delta.content:
                    chunks.append(delta.content)
    except Exception:  # noqa: BLE001 - a failed plan call leaves planning to the agent
        logger.opt(exception=True).info("self-build code: plan call failed")
        return Plan()
    result = parse("".join(chunks))
    writer = str(getattr(model, "model", "") or getattr(model, "name", "") or "")
    return Plan(text=result.text, size=result.size, writer=writer)
