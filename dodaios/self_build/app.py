"""Wire the loop for memories, skills, routines and agents into the running app.

One call at boot, right after the ledger is opened (``server.py``)::

    install_in_app(self_build_service, app.state, bus)

It registers a builder and an undoer for each of the four kinds and
subscribes the loop to the events it observes. Everything it reaches later
(the notebook, the skill registry, the scheduler, the society) is looked up
lazily, so the boot path pays only for two small SQLite files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .builders import Env
from .loop import SelfBuildLoop, current, install

log = logging.getLogger(__name__)


def _society_accessor(app_state: Any) -> Any:
    async def society() -> Any | None:
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime() or getattr(app_state, "society", None)
        if runtime is None:
            factory = getattr(app_state, "society_factory", None)
            if factory is None:
                return None
            runtime = factory()
            app_state.society = runtime
        await runtime.ensure_started()
        return runtime

    return society


def _notebook() -> Any | None:
    from dodaios.memory.learning.notebook import active

    return active()


def _agent_skills(agent_id: str) -> list[Any]:
    """An agent's private skills (active and draft); ``[]`` without a society. Blocking."""
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    if runtime is None:
        return []
    skills = runtime.skills_for(agent_id)
    return [*skills.list_active(), *skills.registry.list_drafts()]


def _pane_history() -> Path:
    from dodaios.agentic_ide.prompt_history import store_dir

    return store_dir()


def install_in_app(service: Any, app_state: Any, bus: Any) -> SelfBuildLoop:
    """Register the four builders and start observing (idempotent)."""
    existing = current()
    if existing is not None:
        return existing
    env = Env(
        config=service.config,
        data_dir=Path(service.ledger.path).parent,
        bus=bus,
        notebook=_notebook,
        skill_registry=lambda: getattr(app_state, "skill_registry", None),
        task_store=lambda: getattr(app_state, "task_store", None),
        scheduler=lambda: getattr(app_state, "task_scheduler", None),
        society=_society_accessor(app_state),
        agent_skills=_agent_skills,
        pane_history=_pane_history,
    )
    return install(service, env=env, bus=bus)


def pane_prompt_recorded(history_id: str) -> None:
    """The IDE's hook after a prompt the person typed reached a pane; a no-op when off.

    Never raises into the IDE: a failure here only costs one observation.
    """
    loop = current()
    if loop is None:
        return
    try:
        loop.pane_prompt_recorded(history_id)
    except Exception:  # noqa: BLE001 - observation must never break a prompt
        log.warning("self_build: pane prompt not observed", exc_info=True)


async def chat_turn_completed(session: Any, completion: Any, *, surface: str) -> None:
    """The chat surfaces' hook (``agent_chat/surface_kits.py``); a no-op when off.

    Never raises into the chat: a failure here only costs one observation.
    """
    loop = current()
    if loop is None:
        return
    try:
        await loop.chat_turn_completed(session, completion, surface=surface)
    except Exception:  # noqa: BLE001 - observation must never break a chat turn
        log.warning("self_build: chat turn not observed", exc_info=True)
