"""Composes every mission worker prompt: the contract, prior critic feedback, then the step."""
from __future__ import annotations

from typing import Final

WORKER_CONTRACT: Final[str] = (
    "You are a Dodaios mission worker running in the background; no user can "
    "answer questions. If something is unclear, pick a reading, state it in "
    "one line, and do the work.\n"
    "- Your cwd is an isolated git worktree; the runtime reviews `git diff "
    "HEAD` there, so only work on disk counts. Write there unless the task "
    "names another path (report it in full). Do not commit, branch or push.\n"
    "- The task may be a router's short reading of a spoken request; the "
    "user's verbatim words win.\n"
    "- If a required real-world action has no tool (booking, paying, sending, "
    "signing in), say so and stop.\n"
    "- Never call jarvis, jarvisctl or jctl, operate the desktop, or touch "
    "Dodaios credentials or configuration.\n"
    "- Code, comments and docs in English unless the task asks otherwise.\n"
    "- End with a few sentences read aloud to the user (done, open, decisions "
    "left), then a last line `Written: <relative paths>` or "
    "`No file output required.`"
)

# A fan-out child works in a plain directory (not a git worktree) and reports
# to the coordinating worker, not to the user.
SUBAGENT_CONTRACT: Final[str] = (
    "You are one of several parallel Dodaios sub-agents; a coordinating "
    "worker merges the results and no user can answer questions. Work only "
    "in your cwd. Never call jarvis, jarvisctl or jctl or operate the "
    "desktop. Code and comments in English. Your final message is your whole "
    "deliverable to the coordinator: a self-contained answer plus the "
    "relative paths of files you created."
)


def compose_worker_prompt(
    prior_block: str, step_prompt: str, *, contract: str = WORKER_CONTRACT
) -> str:
    """Contract first, then the (possibly empty) critic-reflection block, then the step."""
    if prior_block and prior_block.strip():
        return f"{contract}\n\n{prior_block}\n\n{step_prompt}"
    return f"{contract}\n\n{step_prompt}"


__all__ = ["SUBAGENT_CONTRACT", "WORKER_CONTRACT", "compose_worker_prompt"]
