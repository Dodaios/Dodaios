"""The one model call before a coding run: a short plan and a size estimate.

It runs only when a build was admitted to building (or accepted), never for a
proposal, and only through the loop's shared seat list
(:func:`dodaios.self_build.brain.ask`: signed-in subscriptions, then keyless
local models, never a per-token key). Without a seat there is no call at all:
the coding agent plans for itself and the estimate stays unknown.
Every call runs inside :func:`dodaios.self_build.cost.attributed`, so the
ledger shows what it cost.

An estimate of ``large`` stops the build before any coding: large work is not
something to hand an unattended agent.
"""

from __future__ import annotations

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


def _config() -> Any:
    from dodaios.core.config import load_config

    return load_config()


async def plan(
    build_id: str,
    issue: Issue,
    brief_text: str,
    *,
    config: Callable[[], Any] = _config,
) -> Plan:
    """At most one call; an empty :class:`Plan` when no seat can answer."""
    from dodaios.brain.background_policy import BackgroundDeferred

    from .. import brain

    prompt = (
        f"Issue #{issue.number}: {issue.title}\n\n{issue.body[:4_000]}\n\n"
        f"Project brief:\n{brief_text[:5_000]}"
    )
    try:
        with attributed(build_id):
            answer = await brain.ask(config(), _SYSTEM, prompt, max_tokens=_MAX_TOKENS)
    except BackgroundDeferred:  # no subscription or local seat: the agent plans itself
        logger.info("self-build code: no seat for the plan; the coding agent plans")
        return Plan()
    except Exception:  # noqa: BLE001 - a failed plan call leaves planning to the agent
        logger.opt(exception=True).info("self-build code: plan call failed")
        return Plan()
    return parse(answer)
