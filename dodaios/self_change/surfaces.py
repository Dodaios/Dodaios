"""What the agent may change about itself, and which of it is never its call alone.

Every self-change touches one *surface* of the assistant's behaviour. Most
surfaces are ordinary: the change is checked and goes live on trial. Some are
*core*: they define who the assistant is, what it may do, how it is judged or
how its history is kept. A core change is only ever applied after the owner
approved it; no gate result and no agent can stand in for that.
"""

from __future__ import annotations

import fnmatch
import re
from enum import StrEnum
from typing import Final


class Surface(StrEnum):
    SKILL = "skill"
    PROMPT = "prompt"  # the persona / system prompt override
    INSTRUCTIONS = "instructions"  # the owner's standing-instructions file
    TOOL = "tool"  # tool descriptions, plugin and tool installs
    CODE = "code"  # self-build code changes
    CONFIG = "config"  # a setting of the assistant itself
    ROUTINE = "routine"
    AGENT = "agent"


class State(StrEnum):
    PROPOSED = "proposed"  # written down, not applied (waits for the owner, or for a gate)
    TRIAL = "trial"  # applied, passed the gate, on probation
    LIVE = "live"  # applied and confirmed
    REVERTED = "reverted"  # rolled back to the previous version
    BLOCKED = "blocked"  # the gate failed or the owner refused: never applied


#: States in which the change is in effect.
ACTIVE_STATES: Final[frozenset[State]] = frozenset({State.TRIAL, State.LIVE})

#: Files and folders only the owner may change. Anything matching is core, so a
#: self-change that edits the evaluation, the audit, the registry itself, the
#: trust rules, the persona, the provider lock or the judges waits for approval.
CORE_PATHS: Final[tuple[str, ...]] = (
    "dodaios/self_change/*",
    "dodaios/trust/*",
    "dodaios/safety/*",
    "dodaios/evals/*",
    "dodaios/core/self_mod/*",  # the provider lock and the settings allowlist
    "dodaios/self_build/judge.py",
    "dodaios/self_build/policy.py",
    "dodaios/self_build/sandbox.py",
    "dodaios/brain/persona_loader.py",
    "dodaios/brain/DODAIOS_PERSONA.md",
    "dodaios/brain/agent_instructions.py",
    "tests/eval/*",
    "tests/fixtures/lead_routing/*",
    "scripts/lead_routing_eval.py",
    "scripts/agent_done_gate*.py",
    "AGENTS.md",
    "CLAUDE.md",
)

#: Settings that decide who is in charge or how the assistant is judged.
CORE_CONFIG_PREFIXES: Final[tuple[str, ...]] = (
    "security.",
    "trust.",
    "brain.",
    "self_build.",
    "self_change.",
    "audit.",
    "persona.",
    "mcp_server.",
    "harness.",
)

#: Wording that tries to move the objective or the safeguards. A skill or an
#: instruction containing it is treated as a core change whatever its surface.
_OBJECTIVE = re.compile(
    r"(ignore|forget|override|disregard)\s+(all\s+|any\s+|the\s+|your\s+)?"
    r"(previous|prior|above|earlier|safety|system|these)?\s*(instructions|rules|prompt|guidelines|limits)"
    r"|without\s+(asking|approval|confirmation|permission)"
    r"|(never|stop|don'?t)\s+(ask|asking|confirm|confirming)"
    r"|(disable|turn off|bypass|skip)\s+(the\s+)?(approval|approvals|confirmation|safety|audit"
    r"|trust|judge|regression|evaluation)"
    r"|your\s+(main\s+|only\s+|real\s+|new\s+)?(goal|objective|purpose|mission)\s+(is|are)"
    r"|(provider\s+lock|brain\s+provider)",
    re.IGNORECASE,
)


def touches_objective(text: str) -> bool:
    """True when ``text`` tries to rewrite the goal, the limits or the approvals."""
    return bool(_OBJECTIVE.search(text or ""))


def is_core_path(path: str) -> bool:
    norm = path.replace("\\", "/").lstrip("./")
    return any(fnmatch.fnmatch(norm, pattern) for pattern in CORE_PATHS)


def core_reasons(
    surface: Surface, target: str, after: str | None, paths: tuple[str, ...] = ()
) -> list[str]:
    """Why this change needs the owner. An empty list means it is an ordinary change."""
    reasons: list[str] = []
    if surface is Surface.PROMPT:
        reasons.append("it rewrites the persona")
    if surface is Surface.CONFIG and target.startswith(CORE_CONFIG_PREFIXES):
        reasons.append(f"the setting {target!r} is a safety or provider setting")
    protected = [p for p in (target, *paths) if is_core_path(p)]
    if protected:
        reasons.append(f"it edits protected code ({protected[0]})")
    if touches_objective(after or ""):
        reasons.append("its text changes the goal, the limits or the approvals")
    return reasons
