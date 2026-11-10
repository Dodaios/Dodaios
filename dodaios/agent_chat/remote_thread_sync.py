"""A thread's folder on another computer, turn by turn.

A thread placed on another computer runs every turn's CLI there, in a copy of
the thread's folder. The copy is sent before a turn and the work comes back
after it, so the folder on this computer is where a thread's work ends up, as
it does for a thread that runs here. Without the way back, the next turn's
copy replaced whatever the previous turn had written.

Both steps tell the reader in the thread what happened to the work, and
neither fails a turn: work that cannot come back stays on the other computer
and the line says so.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from dodaios.agent_chat.events import make_event

log = logging.getLogger(__name__)

#: ``notice.kind`` of the line that says where a remote turn's work went.
NOTICE_KIND = "remote_work"

#: One exchange at a time per computer and folder: the copy on the other
#: computer is one git checkout, and two git commands in it collide.
_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def _lock(computer_id: str, folder: Path) -> asyncio.Lock:
    return _LOCKS.setdefault((computer_id, str(folder)), asyncio.Lock())


def _computer_name(computer_id: str) -> str:
    from dodaios.computers.service import get_service

    try:
        return str(get_service().get(computer_id).name)
    except Exception as exc:  # noqa: BLE001 - a removed or unreadable record still needs a word
        log.info("agent chat: no name for computer %s (%s); using a general word", computer_id, exc)
        return "the other computer"


async def _emit_notice(handle: Any, text: str) -> None:
    await handle.emit(
        make_event("notice", {"kind": NOTICE_KIND, "turn_id": handle.turn_id, "text": text})
    )


async def send_folder(handle: Any, computer_id: str, folder: Path) -> Any:
    """Copy the thread's folder to the computer for the turn about to start.

    Work an interrupted turn left there comes back first, because the copy
    resets that computer's folder to this one. Returns the placement
    (``agentic_ide.remote.Placement``); raises its ``MoveError`` when the
    folder cannot be set up there.
    """
    from dodaios.agentic_ide import remote
    from dodaios.computers.remote_terminal import pool_for

    pool = pool_for(computer_id)
    name = _computer_name(computer_id)
    async with _lock(computer_id, folder):
        try:
            left = await remote.pull_unreturned(pool, folder, name)
        except remote.MoveError as exc:
            left = None
            # The copy below sets such work aside on that computer before it
            # resets the folder (``refs/jarvis/backup``), so it is not gone.
            await _emit_notice(handle, f"{exc} That computer keeps it as a backup in its copy.")
        except Exception as exc:  # noqa: BLE001 - the copy below reports a dead connection
            left = None
            log.warning(
                "agent chat %s: reading %s for unreturned work failed: %s",
                handle.turn_id,
                name,
                exc,
            )
        if left is not None and left.message:
            await _emit_notice(handle, left.message)
        return await remote.push_code(pool, folder)


async def return_work(handle: Any, computer_id: str, folder: Path, placement: Any) -> None:
    """Bring the finished turn's work from the computer into the folder."""
    from dodaios.agentic_ide import remote
    from dodaios.computers.remote_terminal import pool_for

    name = _computer_name(computer_id)
    if placement.offload_snapshot is None:
        # A folder without git history goes over as an archive: it has no way
        # back, and the next turn's archive lands on top of the work.
        await _emit_notice(
            handle,
            f"This folder has no git history, so work done on {name} does not come back, "
            "and the next turn copies this computer's files over it. In a git folder "
            "the work comes back after every turn.",
        )
        return
    try:
        async with _lock(computer_id, folder):
            outcome = await remote.pull_code(
                pool_for(computer_id),
                folder,
                placement.remote_folder,
                placement.offload_snapshot,
                name,
                per_turn=True,
            )
    except Exception as exc:  # noqa: BLE001 - SSH, SFTP and git failures become one line
        log.warning(
            "agent chat %s: bringing work back from %s failed: %s", handle.turn_id, name, exc
        )
        await _emit_notice(
            handle,
            f"This turn's work could not be brought back from {name} ({exc}). "
            "It is still there and comes back before the next turn.",
        )
        return
    if outcome.message:
        await _emit_notice(handle, outcome.message)
