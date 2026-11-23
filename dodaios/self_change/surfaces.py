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
    CODING_POLICY = "coding_policy"  # how the app steers coding runs (dodaios.rsi.policy)


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
    # What judges a coding run's output, and what that judge reads through.
    "dodaios/orchestrator/verification/*",
    "dodaios/rsi/*",
    "dodaios/self_build/code/judge.py",
    "dodaios/self_build/code/commands.py",
    "dodaios/missions/safety/path_guard.py",
    "dodaios/agent_chat/team/workspace.py",
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

#: What the kernel reads its evidence through: the record of what happened, the
#: judge from another model family, the skill replay, the seat that may be asked,
#: and the checks every pull request has to pass. A self-change that could edit
#: one of these could grade itself, so for the registry they are core as well.
#: (Kept apart from ``CORE_PATHS``: the output scan of ordinary coding runs reads
#: that list, and these files are everyday work for a coding agent the person sent.)
EVIDENCE_PATHS: Final[tuple[str, ...]] = (
    "dodaios/agent_chat/store.py",
    "dodaios/agent_chat/control_eval.py",
    "dodaios/skills/eval_harness.py",
    "dodaios/self_build/brain.py",
    ".github/workflows/*",
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


def is_kernel_path(path: str) -> bool:
    """True for code the assistant may never change about itself: core paths and its evidence."""
    norm = path.replace("\\", "/")
    while norm.startswith("./"):  # not ``lstrip``: ``.github`` keeps its dot
        norm = norm[2:]
    return is_core_path(norm) or any(fnmatch.fnmatch(norm, p) for p in EVIDENCE_PATHS)


def core_reasons(
    surface: Surface, target: str, after: str | None, paths: tuple[str, ...] = ()
) -> list[str]:
    """Why this change needs the owner. An empty list means it is an ordinary change."""
    reasons: list[str] = []
    if surface is Surface.PROMPT:
        reasons.append("it rewrites the persona")
    if surface is Surface.CONFIG and target.startswith(CORE_CONFIG_PREFIXES):
        reasons.append(f"the setting {target!r} is a safety or provider setting")
    protected = [p for p in (target, *paths) if is_kernel_path(p)]
    if protected:
        reasons.append(f"it edits protected code ({protected[0]})")
    if touches_objective(after or ""):
        reasons.append("its text changes the goal, the limits or the approvals")
    if surface is Surface.CODING_POLICY and _policy_text(after):
        reasons.append("it changes what coding agents are told")
    return reasons


def _policy_text(after: str | None) -> str:
    """The turn material a coding policy would add to briefs (decision 5.4: the owner's call)."""
    import json

    try:
        data = json.loads(after or "{}")
    except ValueError:  # not JSON: the gate's policy check blocks it anyway
        return ""
    return str(data.get("domain_block") or "") if isinstance(data, dict) else ""
