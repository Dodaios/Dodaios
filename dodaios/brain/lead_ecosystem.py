"""The lead's ecosystem map: what exists in the app and how the lead reads it.

The lead cannot propose or reach what it does not know exists. Its self-description
used to be hand-written and stale. This module renders one block for the lead's
system prompt from code: the sidebar section ids (``navigate``'s ``KNOWN``), the
Command Registry's sections, the coding agents the app can run, and a table that
says, for every sidebar section, which lead tool or app action reads it.

The block is byte-stable: it depends on nothing but the code (no roster, no
installed tools, no clock), so it stays inside the cached prompt prefix. The
parity tests (``tests/unit/brain/test_lead_ecosystem.py``) fail when a sidebar
section is added without a lead read path, or a named tool or route disappears.

A read path is either a lead tool name or ``GET /api/...``, an app action the
lead runs with ``run-app-action``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Final

#: Every sidebar section id -> the lead's read paths for it (tool names, or
#: ``GET <path>`` app actions). A section id missing here fails the parity test.
SECTION_READS: Final[dict[str, tuple[str, ...]]] = {
    "agents": ("society_status",),
    "agentic-ide": ("work_board", "agentic-ide-status"),
    "agentic-ide-classic": ("agentic-ide-status",),
    "chat-workspace": ("agentic-ide-status",),
    "chats": ("GET /api/chats",),
    "sessions": ("session-latest-turn", "GET /api/sessions"),
    "board": ("GET /api/board/personal/summary",),
    "costs": ("costs_summary",),
    "computers": ("GET /api/computers",),
    "memory": ("memory-search",),
    "profile": ("GET /api/profile",),
    "settings": ("describe-app-settings",),
    "languages": ("GET /api/settings/ui-language",),
    "apikeys": ("providers-list",),
    "voice-api-keys": ("providers-list",),
    "agent-instructions": ("GET /api/settings/agent-instructions",),
    "trust": ("GET /api/trust/rules",),
    "notifications": ("GET /api/notify/settings",),
    "shortcuts": ("GET /api/settings/keybinds",),
    "voice-shortcuts": ("GET /api/settings/keybinds",),
    "taskbar": ("GET /api/settings/bar-size",),
    "visualization": ("GET /api/settings/appearance",),
    "appshots": ("GET /api/appshot/settings",),
    "pets": ("GET /api/pets",),
    "feedback": ("GET /api/feedback/board",),
    "voice-language": ("GET /api/settings/stt-language",),
    "dictation": ("GET /api/dictation/settings",),
    "dictionary": ("GET /api/dictionary",),
    "telephony": ("GET /api/telephony/status",),
    "telephony-setup": ("GET /api/telephony/config",),
    "phone": ("GET /api/mobile/status",),
    "socials": ("GET /api/socials",),
    "skills": ("skills-list",),
    "plugins": ("GET /api/plugins",),
    "mcps": ("GET /api/mcps",),
    "marketplace": ("marketplace-browse",),
    "docs": ("GET /api/docs",),
    "clis": ("GET /api/clis",),
    "cli-test-hub": ("GET /api/clis",),
    "self-build": ("GET /api/self-build",),
}


@dataclass(frozen=True, slots=True)
class Area:
    """One part of the ecosystem as the lead sees it."""

    name: str
    what: str
    #: Sidebar section ids of this area (``navigate`` opens them).
    sections: tuple[str, ...] = ()
    #: Read paths beyond the sections' own (tools or ``GET`` app actions).
    reads: tuple[str, ...] = ()
    #: The lead tools that change things here.
    acts: tuple[str, ...] = ()


AREAS: Final[tuple[Area, ...]] = (
    Area(
        "Agents",
        "the agent society: roster, island, routines, approvals; each agent has its own hands",
        sections=("agents",),
        reads=("society-list-routines",),
        acts=("delegate", "ask_agent", "society-create-agent", "society-create-routine"),
    ),
    Area(
        "Coding panes",
        "Agentic IDE workspaces with terminals that run coding agents, addressed by stable id",
        sections=("agentic-ide", "agentic-ide-classic", "chat-workspace"),
        acts=("delegate", "workspace-orchestrate", "workspace-git"),
    ),
    Area(
        "Team threads",
        "several coding agents on different models plan, build and review one task together",
        reads=("team_thread",),
        acts=("delegate", "team_thread"),
    ),
    Area(
        "Jobs",
        "everything you start gets a job id; read what became of it; multi-day work is a project",
        reads=("work_board", "job_status", "await_jobs", "project"),
        acts=("delegate", "verify_delegate", "job_stop", "project"),
    ),
    Area(
        "Artifacts",
        "what the agents made: mission outputs, files and living pages",
        reads=("artifacts", "missions-list"),
        acts=("living_page", "create_artifact"),
    ),
    Area(
        "Automations",
        "routines, reminders, when-then event triggers and workflows",
        reads=("society-list-routines", "reminders", "GET /api/tasks/triggers/catalog",
               "GET /api/workflows"),
        acts=("society-create-routine", "reminders"),
    ),
    Area(
        "Conversations",
        "chats, the saved conversation archive, the person's activity board",
        sections=("chats", "sessions", "board"),
    ),
    Area(
        "Computers",
        "the person's servers and local VMs, reached over SSH",
        sections=("computers",),
    ),
    Area("Spend", "cost and tokens per agent, seat and model", sections=("costs",),
         acts=("costs_summary",)),
    Area(
        "Memory and profile",
        "the personal memory vault, the profile, standing instructions, trust rules",
        sections=("memory", "profile", "agent-instructions", "trust", "feedback"),
        acts=("memory-forget",),
    ),
    Area(
        "Extensions",
        "skills, plugins, MCP servers, the marketplace, docs, coding-CLI inventory, self-build",
        sections=("skills", "plugins", "mcps", "marketplace", "docs", "clis", "cli-test-hub",
                  "self-build"),
        acts=("create-skill", "run-skill", "manage-mcp-server", "marketplace-install"),
    ),
    Area(
        "Voice, phone and channels",
        "dictation, wake word and voice shortcuts, telephony, the paired phone, socials",
        sections=("voice-language", "voice-shortcuts", "dictation", "dictionary", "telephony",
                  "telephony-setup", "phone", "socials", "voice-api-keys"),
    ),
    Area(
        "Look and settings",
        "providers and keys, language, notifications, shortcuts, taskbar, pets, appshots",
        sections=("settings", "apikeys", "languages", "notifications", "shortcuts", "taskbar",
                  "visualization", "appshots", "pets"),
        acts=("brain-switch", "set_config_value"),
    ),
)

_PREAMBLE: Final[str] = (
    "ECOSYSTEM MAP (generated from the app; section ids open with navigate)\n"
    "A read path is a tool name, or `GET /api/...` which you run with run-app-action. "
    "Anything not listed: find-app-action searches every other action of the app."
)


def _reads_of(area: Area) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for section in area.sections:
        for path in SECTION_READS.get(section, ()):
            seen.setdefault(path)
    for path in area.reads:
        seen.setdefault(path)
    return tuple(seen)


def _coding_agents() -> str:
    from dodaios.workspace.agents import builtin_names, get_agent

    names = []
    for key in builtin_names():
        agent = get_agent(key)
        if agent is not None and key != "shell":
            names.append(agent.display_name)
    return ", ".join(names)


def _registry_sections() -> str:
    from collections import Counter

    from dodaios.commands.registry import get_registry

    counts = Counter(command.ui_section for command in get_registry())
    return ", ".join(f"{section} {n}" for section, n in sorted(counts.items()))


@lru_cache(maxsize=1)
def render_ecosystem_map() -> str:
    """The block. Same bytes on every call of one build of the app."""
    lines = [_PREAMBLE]
    for area in AREAS:
        parts = [f"- {area.name}: {area.what}."]
        if area.sections:
            parts.append(f"Sections: {', '.join(area.sections)}.")
        reads = _reads_of(area)
        if reads:
            parts.append(f"Read: {', '.join(reads)}.")
        acts = tuple(tool for tool in area.acts if tool not in reads)
        if acts:
            parts.append(f"Act: {', '.join(acts)}.")
        lines.append(" ".join(parts))
    lines.append(f"Coding agents the app can run: {_coding_agents()}.")
    lines.append(f"app-command registry, commands per section: {_registry_sections()}.")
    return "\n".join(lines)


def section_read_paths() -> dict[str, tuple[str, ...]]:
    """Every sidebar section -> its lead read paths, for the parity test and docs."""
    return dict(SECTION_READS)


__all__ = ["AREAS", "SECTION_READS", "Area", "render_ecosystem_map", "section_read_paths"]
