"""Task classes of the lead's real usage, and the deterministic rules that assign them.

A turn is classified from the tools it used first (a table, no model) and, when
no tool decides it, from a few keyword rules over the owner's message. The class
names are the stable vocabulary of the score; the importance table is the
owner's to edit (see :mod:`dodaios.evals.agent_score.config`).
"""

from __future__ import annotations

import re
from typing import Final

#: Class id -> default importance in [0, 1]. Owner-editable in the score config.
DEFAULT_IMPORTANCE: Final[dict[str, float]] = {
    "coding_delegation": 1.0,
    "mail": 0.8,
    "computer_use": 0.8,
    "calendar": 0.7,
    "memory": 0.7,
    "research_web": 0.6,
    "messaging": 0.6,
    "artifacts": 0.5,
    "status_orchestration": 0.5,
    "settings": 0.4,
    "chit_chat": 0.3,
    "other": 0.3,
}

#: Tie-break order when a turn used tools of several classes.
PRIORITY: Final[tuple[str, ...]] = tuple(DEFAULT_IMPORTANCE)

#: Bare tool name -> class.
TOOL_CLASS: Final[dict[str, str]] = {
    "gmail": "mail",
    "google_calendar": "calendar",
    "reminders": "calendar",
    "delegate_to_agent": "coding_delegation",
    "message_agent": "coding_delegation",
    "spawn_worker": "coding_delegation",
    "workspace": "coding_delegation",
    "mission": "coding_delegation",
    "missions": "coding_delegation",
    "run": "coding_delegation",
    "search_web": "research_web",
    "navigate": "research_web",
    "society_browser": "research_web",
    "memory": "memory",
    "update_profile": "memory",
    "contact": "memory",
    "set_config_value": "settings",
    "get_config_value": "settings",
    "list_mutable_settings": "settings",
    "providers": "settings",
    "wake": "settings",
    "tts": "settings",
    "skills": "settings",
    "skill": "settings",
    "marketplace": "settings",
    "computer_use": "computer_use",
    "screenshot": "computer_use",
    "app": "computer_use",
    "society_status": "status_orchestration",
    "society": "status_orchestration",
    "job_status": "status_orchestration",
    "await_jobs": "status_orchestration",
    "work_board": "status_orchestration",
    "tasks": "status_orchestration",
    "create_artifact": "artifacts",
    "living_page": "artifacts",
    "slack": "messaging",
    "reply": "messaging",
    "home_assistant": "other",
    "google_drive": "other",
}

#: Light keyword rules for turns whose tools do not decide (no tool, or unknown ones).
#: ``(class, English words, German words)``; both are regex alternations.
_KEYWORD_TABLE: Final[tuple[tuple[str, str, str], ...]] = (
    ("mail", r"e-?mails?|inbox|gmail|mails?", r"posteingang"),  # i18n-allow: DE matcher
    (
        "calendar",
        r"calendar|meeting|appointment|remind\w*",
        r"kalender|termin\w*|erinner\w*",  # i18n-allow: DE matcher
    ),
    (
        "coding_delegation",
        r"bug|pull request|pr|repo\w*|refactor\w*|implement\w*|unit tests?|code|fix",
        r"programmier\w*",  # i18n-allow: DE matcher
    ),
    (
        "research_web",
        r"search|google|look up|research|website|web ?search",
        r"recherch\w*|suche\w*",  # i18n-allow: DE matcher
    ),
    (
        "memory",
        r"remember|memory|forget",
        r"merk dir|erinnerst|vergiss",  # i18n-allow: DE matcher
    ),
    (
        "settings",
        r"settings?|config\w*|enable|disable",
        r"einstellung\w*|aktivier\w*",  # i18n-allow: DE matcher
    ),
    (
        "computer_use",
        r"click|screenshot|my screen|open the app",
        r"klick\w*|bildschirm",  # i18n-allow: DE matcher
    ),
    (
        "status_orchestration",
        r"status|progress|what is .* doing|how is .* going",
        r"fortschritt",  # i18n-allow: DE matcher
    ),
)
_KEYWORDS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (cls, re.compile(r"\b(" + en + "|" + de + r")\b", re.I)) for cls, en, de in _KEYWORD_TABLE
)


def bare_tool(name: str) -> str:
    """``mcp__x__gmail`` / ``plugin.gmail`` -> ``gmail``."""
    text = str(name or "").strip()
    for sep in ("__", ".", ":", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text.lower()


def classify_turn(tools: list[str], text: str = "") -> str:
    """The class of one turn: tool table first, keywords second, chit-chat last."""
    votes: dict[str, int] = {}
    for tool in tools:
        cls = TOOL_CLASS.get(bare_tool(tool))
        if cls and cls != "other":
            votes[cls] = votes.get(cls, 0) + 1
    if votes:
        best = max(votes.values())
        return next(c for c in PRIORITY if votes.get(c) == best)
    for cls, pattern in _KEYWORDS:
        if pattern.search(text or ""):
            # A keyword only decides a turn that did no tool work of a known class.
            return cls
    return "other" if tools else "chit_chat"
