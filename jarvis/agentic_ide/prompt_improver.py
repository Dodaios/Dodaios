"""Improve a typed prompt before it goes to a coding agent.

The side panel's Prompt tab: the user types a rough prompt, picks the model
that rewrites it, reads the result and sends it to the pane they choose.

Deliberately not the prompt composer. The composer briefs an agent from a
SPOKEN instruction on the voice turn's clock: a fixed skeleton, a 1.2 s
budget, a deterministic fallback, always English. Here the user typed the
prompt themselves, waits for it on purpose and reads the answer before
anything is sent, so the instruction is one short paragraph they can replace,
the answer keeps their language, and a failure is reported instead of being
papered over with a template.

Two things are fixed whatever the user's instruction says: the prompt states
the goal and leaves the route to the agent (the composer's own rule, imported
so the two cannot drift), and the writer sees the repository the receiving
pane works in.

The model is the user's pick. The caller hands the picked model in as a brain
(the web route builds it from the seat an agent chat on that provider uses), so
this package stays free of the chat and agent packages; with no brain given it
is whoever writes the IDE's task briefs (``writer.resolve_writer``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

from .folders import ProjectProfile, probe_project
from .prompt_blueprint import GOAL_NOT_IMPLEMENTATION_RULE
from .session import MAX_PROMPT_CHARS

#: What the writer is asked to do when the user gave no instruction of their own.
DEFAULT_INSTRUCTION = (
    "Improve this prompt for the coding agent that will receive it: clear, "
    "complete and easy to act on."
)

#: Longest instruction of the user's own that is passed on.
MAX_INSTRUCTION_CHARS = 1000

#: The whole wait. A subscription CLI pays a cold process start before it
#: thinks at all, and the user is watching a spinner they started themselves.
IMPROVE_TIMEOUT_S = 90.0

#: Room for the file map in the writer's context.
_MAP_CHARS = 2400

#: The usage ledger's name for this work.
USAGE_CALLER = "prompt_improver"

_FIXED_RULES = f"""\
{GOAL_NOT_IMPLEMENTATION_RULE}

Keep everything the prompt asks for - every requirement, file, name and \
boundary. Add nothing it does not ask for: no invented requirement, constraint, \
step list or success criterion, and no general advice (follow the conventions, \
read the instructions, run the tests) - the agent does all of that on its own. \
The repository notes are there so you name things the way this codebase does; \
mention a file only when the notes show it is the place, never as a guess.

Keep it as short as the task allows: plain sentences, and a heading or list \
only when the prompt has several separate parts.

Write in the language the prompt is written in. Answer with the improved \
prompt only: no preamble, no quotes, no code fence."""


class EmptyPrompt(ValueError):
    """There is nothing to improve."""


class ImproverUnavailable(RuntimeError):
    """No model can take the job as asked. The message is app-authored."""


class ImproverFailed(RuntimeError):
    """The chosen model accepted the job and did not deliver.

    Carries the exception type, never its text: a provider's error body must
    not reach a log line or the UI (AP-34).
    """


@dataclass(frozen=True, slots=True)
class ImprovedPrompt:
    """The rewritten prompt and who wrote it."""

    text: str
    #: Where the writer came from: ``provider:<id>`` for the user's pick, else
    #: the brief writer's own source (``tool_model:…``, ``api``, ``subscription:…``).
    source: str
    #: The writing brain's name, for the "written by" line.
    writer: str


def system_prompt(instruction: str = "") -> str:
    """The writer's instruction: the user's sentence, then the two fixed rules."""
    asked = " ".join((instruction or "").split())[:MAX_INSTRUCTION_CHARS]
    return f"{asked or DEFAULT_INSTRUCTION}\n\n{_FIXED_RULES}"


def repo_context(folder: str, prompt: str, profile: ProjectProfile | None = None) -> str:
    """What the writer is told about the repository. Blocking; run in a thread.

    The profile (branch, stack, top-level folders, the skills and subagents the
    repo defines) plus a map of the folders that fit the prompt, taken from the
    workspace's file index when it is already built. Never waits for a walk.
    """
    if not folder:
        return ""
    from .file_index import cached_index

    profile = profile or probe_project(folder)
    lines = profile.summary_lines()
    index = cached_index(folder)
    tree = index.render_map(prompt, max_chars=_MAP_CHARS) if index is not None else ""
    if tree:
        lines += ["", "Files that fit the prompt:", tree]
    return "\n".join(lines)


def user_block(prompt: str, context: str) -> str:
    """The writer's user turn: the repository, then the prompt to improve."""
    parts = []
    if context:
        parts.append(f"REPOSITORY\n{context}")
    parts.append(f"PROMPT TO IMPROVE\n{prompt}")
    return "\n\n".join(parts)


def _resolve_default() -> tuple[Any, str]:
    """Whoever writes the IDE's task briefs. Blocking."""
    from .writer import resolve_writer

    brain, source = resolve_writer(cli_timeout_s=IMPROVE_TIMEOUT_S)
    if brain is None:
        raise ImproverUnavailable(
            "No model can write prompts right now. Connect a provider under API "
            "Keys, or pick a model here."
        )
    return brain, source


def _strip_wrapping(text: str) -> str:
    """Drop a code fence a model put around the whole answer."""
    out = text.strip()
    if out.startswith("```") and out.endswith("```") and out.count("```") == 2:
        out = out[3:-3]
        # ``` may carry a language tag on its own line.
        head, _, rest = out.partition("\n")
        out = rest if rest and " " not in head.strip() else out
    return out.strip()


async def _write(brain: Any, system: str, block: str) -> str:
    from jarvis.core.protocols import BrainMessage, BrainRequest

    request = BrainRequest(
        messages=(BrainMessage(role="user", content=block),),
        system=system,
        # A rewrite that must carry the user's intent, not a creative draft.
        temperature=0.2,
        # A goal-only prompt is far shorter; the room is for a model that
        # spends part of its budget reasoning before it answers.
        max_tokens=4096,
        stream=True,
    )
    from jarvis.costs.ledger import usage_context

    chunks: list[str] = []
    # One coroutine consumes the whole stream, so the tag is set and reset here.
    with usage_context(USAGE_CALLER):
        async for delta in brain.complete(request):
            if delta.content:
                chunks.append(delta.content)
    return "".join(chunks)


async def improve(
    prompt: str,
    *,
    folder: str = "",
    profile: ProjectProfile | None = None,
    instruction: str = "",
    brain: Any = None,
    source: str = "",
) -> ImprovedPrompt:
    """Rewrite ``prompt``, knowing the repository in ``folder``.

    ``brain`` is the model the user picked, with ``source`` saying where it
    came from; without one the IDE's configured brief writer answers.

    Raises ``EmptyPrompt`` for an empty prompt, ``ImproverUnavailable`` when no
    model can take the job and ``ImproverFailed`` when the model did not
    deliver. There is no fallback text: the user's own prompt is still in
    front of them, and a template presented as "improved" would be a lie.
    """
    text = (prompt or "").strip()
    if not text:
        raise EmptyPrompt("The prompt is empty.")
    text = text[:MAX_PROMPT_CHARS]

    try:
        context = await asyncio.to_thread(repo_context, folder, text, profile)
    except Exception as exc:  # noqa: BLE001 - the notes are a help, never a requirement
        logger.info("Prompt improver: no repository notes ({})", type(exc).__name__)
        context = ""
    if brain is None:
        try:
            brain, source = await asyncio.to_thread(_resolve_default)
        except ImproverUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - by type; the text may quote the config
            logger.info("Prompt improver: no brief writer ({})", type(exc).__name__)
            raise ImproverUnavailable(
                f"The model that writes prompts could not be prepared ({type(exc).__name__})."
            ) from None

    try:
        raw = await asyncio.wait_for(
            _write(brain, system_prompt(instruction), user_block(text, context)),
            timeout=IMPROVE_TIMEOUT_S,
        )
    except TimeoutError:
        raise ImproverFailed(
            f"The model did not answer within {int(IMPROVE_TIMEOUT_S)} seconds."
        ) from None
    except Exception as exc:  # noqa: BLE001 - reported by type; the text may be a provider's
        logger.info("Prompt improver: {} failed ({})", source, type(exc).__name__)
        raise ImproverFailed(f"The model call failed ({type(exc).__name__}).") from None

    improved = _strip_wrapping(raw)
    if not improved:
        raise ImproverFailed("The model returned an empty answer.")
    return ImprovedPrompt(
        text=improved, source=source or "pinned", writer=str(getattr(brain, "name", "") or "")
    )


__all__ = [
    "DEFAULT_INSTRUCTION",
    "EmptyPrompt",
    "IMPROVE_TIMEOUT_S",
    "MAX_INSTRUCTION_CHARS",
    "USAGE_CALLER",
    "ImprovedPrompt",
    "ImproverFailed",
    "ImproverUnavailable",
    "improve",
    "repo_context",
    "system_prompt",
    "user_block",
]
