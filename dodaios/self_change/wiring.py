"""Boot wiring: open the registry, give each surface its handler, mirror the self-build ledger."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import set_current
from .registry import MIRROR_PREFIX, FileHandler, SelfChangeRegistry
from .store import Change
from .surfaces import State, Surface

log = logging.getLogger(__name__)

#: Self-build kinds that are behaviour surfaces; memory entries are not.
_KIND_SURFACE = {"routine": Surface.ROUTINE, "agent": Surface.AGENT, "code": Surface.CODE}
_STATE = {
    "trial": State.TRIAL,
    "kept": State.LIVE,
    "archived": State.REVERTED,
    "undone": State.REVERTED,
}


def _persona_path(_target: str) -> Path:
    from dodaios.brain import persona_loader

    return persona_loader.custom_prompt_path()


def _skill_path(target: str) -> Path:
    from dodaios.core.paths import user_skills_dir

    return user_skills_dir() / target / "SKILL.md"


def instructions_handler(config: Any) -> FileHandler:
    from dodaios.brain import agent_instructions

    return FileHandler(lambda _target: agent_instructions.instructions_path(config))


def make_notifier(get_loop: Any) -> Any:
    """Post a notice into the lead conversation (quietly does nothing without a society)."""

    def notify(payload: dict[str, Any]) -> None:
        import asyncio

        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        loop = get_loop()
        if runtime is None or loop is None or loop.is_closed():
            return
        lead = next((a for a in runtime.roster.snapshot() if a.agent_id == runtime.lead_id), None)
        if lead is None:
            return
        asyncio.run_coroutine_threadsafe(runtime.post_chat_notice(lead, payload), loop)

    return notify


def install(data_dir: Path, config: Any, loop_of: Any = lambda: None) -> SelfChangeRegistry:
    registry = SelfChangeRegistry(data_dir, notify=make_notifier(loop_of))
    registry.register_handler(Surface.PROMPT, FileHandler(_persona_path))
    registry.register_handler(Surface.INSTRUCTIONS, instructions_handler(config))
    registry.register_handler(Surface.SKILL, FileHandler(_skill_path))
    set_current(registry)
    return registry


def mirror_build(registry: SelfChangeRegistry, record: Any) -> None:
    """Keep the registry in step with one self-build record (called on every ledger change)."""
    kind, state = str(record.kind.value), str(record.state.value)
    new_state = _STATE.get(state)
    if new_state is None:
        return
    if kind == "skill":
        # Skills are recorded by the authoring path itself; here only the end of their life.
        name = str((record.artefact or {}).get("name") or "")
        from dodaios.skills.authoring.service import slugify

        existing = registry.store.by_ref(f"skill:{slugify(name)}") if name else None
        if (
            existing is not None
            and new_state is State.REVERTED
            and existing.state
            in (
                State.TRIAL,
                State.LIVE,
            )
        ):
            registry.store.move(existing.id, State.REVERTED, actor="self-build", note="undone")
        return
    surface = _KIND_SURFACE.get(kind)
    if surface is None:
        return
    proof = record.proof if isinstance(getattr(record, "proof", None), dict) else {}
    registry.note_external(
        surface=surface,
        ref=f"{MIRROR_PREFIX}{record.id}",
        title=str(record.title),
        state=new_state,
        author="self-build",
        gate=proof or None,
    )


def revert_build(service: Any, change: Change) -> None:
    """Revert a mirrored change through the self-build ledger's own undo."""
    import asyncio

    build_id = change.ref[len(MIRROR_PREFIX) :]
    loop = getattr(service, "_loop", None)
    if loop is None or loop.is_closed():
        raise RuntimeError("the self-build loop is not running")
    asyncio.run_coroutine_threadsafe(
        service.undo.undo(service.ledger, build_id, "rolled back from the self-change list"), loop
    ).result(timeout=60)
