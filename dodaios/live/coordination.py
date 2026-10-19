"""How a live call decides between talking, a quick look and handing work over.

One wording for every live engine. A session whose speaking model delegates to
a separate reasoning backend and a session whose model calls its tools itself
follow the same rules; only the name of what carries out the work differs.
"""

from __future__ import annotations

from typing import Final

#: For the model that executes tools: progress, sync and branch questions.
WORK_STATUS_RULE: Final[str] = (
    "Progress questions: task_status once; one workspace: workspace-orchestrate with action "
    "status. To report when an agent the user started is done, call workspace-orchestrate "
    "with action watch now. Repository: workspace-git, with op state for branch and changes. "
    "Correct a running mission with mission-amend; never restart it. "
)


#: For the model that executes tools: what goes on screen instead of into speech.
ON_SCREEN_RULE: Final[str] = (
    "Tables, code, diffs or links go to show_on_screen; say the takeaway. navigate opens a "
    "section, chat or workspace. "
)


#: For the model that executes tools: talking with one of the user's agents.
TEAM_TALK_RULE: Final[str] = (
    "To talk with a named agent use ask_agent and relay its words until the user turns back "
    "to you. "
)


#: Every tool the rules above call by name. A model that is told to use a tool it
#: was not given says the tool does not exist, so these are always declared
#: directly, also under a small model's declaration budget.
NAMED_TOOLS: Final[tuple[str, ...]] = (
    "task_status",
    "workspace-orchestrate",
    "workspace-git",
    "show_on_screen",
    "navigate",
    "ask_agent",
    "mission-amend",
)


def conversation_rules(executor: str) -> str:
    """The speaking model's rules; ``executor`` is what carries out work for it."""
    return (
        "Talk it through: ideas, plans and decisions stay in the conversation; while the "
        "user plans, start no implementation until they approve. A clear request to do "
        "something now is not planning. Take a quick look: one short check is one request "
        f"to {executor}. Hand it over: slow or multi-step work goes to {executor} while you "
        "keep talking. Treat update and style wishes as preferences for the whole task. Pass "
        f"corrections of running work to {executor} at once; never say it cannot be changed. "
        "Say the takeaway. Never read out tables, lists, diffs, code or logs. "
    )


__all__ = [
    "NAMED_TOOLS",
    "ON_SCREEN_RULE",
    "TEAM_TALK_RULE",
    "WORK_STATUS_RULE",
    "conversation_rules",
]
