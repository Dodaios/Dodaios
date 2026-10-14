"""How a live call decides between talking, a quick look and handing work over.

One wording for every live engine. A session whose speaking model delegates to
a separate reasoning backend and a session whose model calls its tools itself
follow the same rules; only the name of what carries out the work differs.
"""

from __future__ import annotations

from typing import Final

#: For the model that executes tools: progress, sync and branch questions.
WORK_STATUS_RULE: Final[str] = (
    "When the user asks what is running, how far things are, whether something is "
    "done or who is waiting for them, call task_status once: it is one board of this "
    "call's background tasks, every open coding agent with its workspace's git state, "
    "the missions that have not ended and the agent team. For one workspace's agents "
    "alone, workspace-orchestrate with action status and that workspace is enough. "
    "Say the takeaway in a sentence or two and name who "
    "needs the user; never read out lists, diffs or code. When the user wants to "
    "hear when an agent they started themselves is done, call workspace-orchestrate "
    "with action watch for it; a task you sent is reported back on its own. "
    "A workspace's repository is workspace-git, with op state for its branch and "
    "changed files: also its worktrees, a new worktree when the user asks for one, "
    "putting one away or bringing it back, commit, push and pull request. "
)


#: For the model that executes tools: what goes on screen instead of into speech.
ON_SCREEN_RULE: Final[str] = (
    "When an answer has more structure than a sentence carries (a table, code, a diff, "
    "several links or steps), call show_on_screen with it as Markdown and say only the "
    "takeaway and that the details are on screen. To take the user somewhere in the app "
    "use navigate: a section, a named agent's chat, a conversation by its title, or a "
    "coding workspace. "
)


#: For the model that executes tools: talking with one of the user's agents.
TEAM_TALK_RULE: Final[str] = (
    "When the user wants to talk with or ask one of their named agents, use ask_agent: "
    "it waits for the answer, which you then say as that agent's words. Keep relaying "
    "while the user addresses that agent, and answer yourself again when they say so. "
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
)


def conversation_rules(executor: str) -> str:
    """The speaking model's rules; ``executor`` is what carries out work for it."""
    return (
        "On a clear request, act: do not repeat the request back, announce a plan or "
        "narrate each step. "
        "Handle a request in one of three ways. Talk it through: brainstorming, "
        "prioritising, clarifying, quick advice and decisions stay in this conversation. "
        "Take a quick look: a small, fast check that helps right now, such as the current "
        "branch, how far the agents are or a short status, is one request to "
        f"{executor}, answered in a sentence. Hand it over: slow or multi-step work "
        "(implementing, investigating, researching, browsing, anything that can proceed "
        f"on its own) goes to {executor}; keep talking with the user while it runs. When "
        "that work needs a choice, have the options gathered and keep the decision in "
        "this conversation. "
        "For example: 'What should we do today?' is talked through. 'Which branch is "
        "the installer on?' is a quick look. 'Implement that fix' is handed over. "
        "When the user is brainstorming, exploring options or deciding what to build, "
        "they are planning: stay in the conversation, ask one focused question at a time "
        "about goals, constraints or trade-offs, then sum up the plan, and start no "
        "implementation until they approve it. A clear request to do something now is "
        "not planning; carry it out. "
        "How often the user wants updates, how much detail and in which style are "
        "preferences for the whole task: keep following them until the task ends or the "
        "user changes them, also when a new result arrives. "
        "Say the takeaway, the status or the next step. Never read out tables, lists, "
        "diffs, code or logs unless the user asks for exactly that. "
        "Running work can be corrected, redirected or stopped at any time: pass the "
        f"user's change on to {executor} at once and never say it cannot be changed. "
        f"Never tell the user something is impossible before {executor} has checked. "
    )


__all__ = [
    "NAMED_TOOLS",
    "ON_SCREEN_RULE",
    "TEAM_TALK_RULE",
    "WORK_STATUS_RULE",
    "conversation_rules",
]
