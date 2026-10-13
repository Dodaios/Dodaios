"""REST API for the Agentic IDE's prompt improver (the side panel's Prompt tab).

Endpoints (mounted by the WebServer in ``_build_app()``):

    GET  /api/agentic-ide/prompt-improver  → the default instruction and limits.
    POST /api/agentic-ide/prompt-improver  → {"improved": ...} for one prompt.

Improving never types into a pane. The tab shows the result and sends it
through ``POST /api/agentic-ide/terminals/{name}/prompt`` when the user says so.
"""
from __future__ import annotations

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
            folder = term.cwd(session.folder)
            return folder, session.profile if folder == session.folder else None
    session = registry.get(workspace or None)
    if session is None:
        return "", None
    return session.folder, session.profile


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
    try:
        result = await prompt_improver.improve(
            req.prompt,
            folder=folder,
            profile=profile,
            provider=req.provider.strip(),
            model=req.model.strip(),
            instruction=req.instruction,
        )
    except ValueError as exc:
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
