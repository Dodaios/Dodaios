"""REST API for the Agentic IDE's prompt improver (the side panel's Prompt tab).

Endpoints (mounted by the WebServer in ``_build_app()``):

    GET  /api/agentic-ide/prompt-improver  → the default instruction and limits.
    POST /api/agentic-ide/prompt-improver  → {"improved": ...} for one prompt.

Improving never types into a pane. The tab shows the result and sends it
through ``POST /api/agentic-ide/terminals/{name}/prompt`` when the user says so.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from jarvis.agentic_ide import prompt_improver
from jarvis.agentic_ide.session import MAX_PROMPT_CHARS, get_registry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agentic-ide/prompt-improver", tags=["prompt-improver"])


class ImproveRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    #: A provider id from the agent catalog; empty = the IDE's brief writer.
    provider: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=200)
    #: The user's own instruction; empty = the default one.
    instruction: str = Field(default="", max_length=prompt_improver.MAX_INSTRUCTION_CHARS)
    #: The pane the prompt is meant for: its repository is the writer's context.
    workspace: str | None = Field(default=None, max_length=200)
    pane: str | None = Field(default=None, max_length=200)


def _target(workspace: str | None, pane: str | None) -> tuple[str, Any]:
    """``(folder, profile)`` of the pane's repository, or ``("", None)``.

    A worktree pane works in its own folder, which the workspace's cached
    profile does not describe, so the profile is handed on only when the two
    are the same folder.
    """
    registry = get_registry()
    if pane:
        found = registry.find_terminal(pane, workspace or None)
        if found is not None:
            session, term = found
            if term.computer_id:
                # The agent works on another machine; this folder is not its repository.
                return "", None
            folder = term.cwd(session.folder)
            return folder, session.profile if folder == session.folder else None
    session = registry.get(workspace or None)
    if session is None:
        return "", None
    return session.folder, session.profile


def _seat_for(provider: str, model: str) -> tuple[Any, Any]:
    """``(config, seat)`` for the picked provider. Blocking: a CLI probe, a config load."""
    from jarvis.agent_chat.catalog import offers
    from jarvis.agent_chat.service import resolve_runner
    from jarvis.core.config import load_config
    from jarvis.society.seat_brain import Seat

    if not offers("agent", provider):
        raise prompt_improver.ImproverUnavailable(
            f"'{provider}' is not a model provider this app offers."
        )
    runner = resolve_runner(provider, surface="agent")
    if runner == "unknown":
        raise prompt_improver.ImproverUnavailable(
            f"'{provider}' cannot write prompts on this machine."
        )
    return load_config(), Seat(provider, model, runner)


async def _picked_brain(provider: str, model: str) -> Any:
    """The user's pick as a brain, on the seat an agent chat on that provider uses.

    The rewrite then runs on the credential the picker showed and on nothing
    else. Raises ``ImproverUnavailable`` with an app-authored message; a
    failure of any other kind is reported by its type, because its text may
    quote the configuration.
    """
    from jarvis.society import seat_brain

    try:
        config, seat = await asyncio.to_thread(_seat_for, provider, model)
        return await seat_brain.seat_brain(config, seat, caller=prompt_improver.USAGE_CALLER)
    except prompt_improver.ImproverUnavailable:
        raise
    except seat_brain.SeatUnavailable as exc:
        raise prompt_improver.ImproverUnavailable(str(exc)) from None
    except Exception as exc:  # noqa: BLE001 - reported by type, see the docstring
        log.info(
            "Prompt improver: the %s seat could not be prepared (%s).",
            provider,
            type(exc).__name__,
        )
        raise prompt_improver.ImproverUnavailable(
            f"'{provider}' could not be prepared ({type(exc).__name__})."
        ) from None


@router.get(
    "",
    summary="Show the prompt improver's defaults",
    openapi_extra={"x-jarvis-readonly": True},
)
def prompt_improver_defaults() -> dict[str, Any]:
    """The instruction used when the user gives none, and the size limits."""
    return {
        "default_instruction": prompt_improver.DEFAULT_INSTRUCTION,
        "max_prompt_chars": MAX_PROMPT_CHARS,
        "max_instruction_chars": prompt_improver.MAX_INSTRUCTION_CHARS,
    }


@router.post("", summary="Improve a prompt for a coding agent")
async def improve_prompt(req: ImproveRequest) -> dict[str, Any]:
    """Rewrite ``prompt`` as a goal-only prompt, with the target pane's repo as context.

    ``provider``/``model`` name the writing model; without them the IDE's
    configured brief writer answers. Nothing is sent to a pane.
    """
    folder, profile = _target(req.workspace, req.pane)
    provider = req.provider.strip().lower()
    try:
        brain = await _picked_brain(provider, req.model.strip()) if provider else None
        result = await prompt_improver.improve(
            req.prompt,
            folder=folder,
            profile=profile,
            instruction=req.instruction,
            brain=brain,
            source=f"provider:{provider}" if provider else "",
        )
    except prompt_improver.EmptyPrompt as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except prompt_improver.ImproverUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except prompt_improver.ImproverFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    log.info(
        "Prompt improver: %d -> %d chars via %s.", len(req.prompt), len(result.text), result.source
    )
    return {
        "improved": result.text,
        "source": result.source,
        "writer": result.writer,
        "folder": folder,
    }
