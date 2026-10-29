"""A recall store left open must not keep Jarvis from exiting.

BC-250 2026-10-29: after a browser voice session, `systemctl stop` ended in
SIGKILL after 60 s, every time. Stacks captured during the hang showed the main
thread in threading._shutdown() waiting for two non-daemon aiosqlite worker
threads, owned by RecallStore instances that a MessageRecorder had opened on
the first ResponseGenerated and nobody closed: the per-session brain's and the
app brain's.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dodaios.brain.manager import BrainManager
from dodaios.core.bus import EventBus
from dodaios.core.events import ResponseGenerated
from dodaios.memory.message_recorder import MessageRecorder
from dodaios.memory.recall import RecallStore, close_open_recall_stores

REPO = Path(__file__).resolve().parents[3]

# The shape of the live defect: a recorder on the app's long-lived bus opens its
# store on a response, then the event loop ends. CLOSE decides whether the
# shutdown closes leftover stores.
_SCRIPT = textwrap.dedent(
    """
    import asyncio, sys
    sys.path.insert(0, {repo!r})
    from dodaios.core.bus import EventBus
    from dodaios.core.events import ResponseGenerated
    from dodaios.memory.message_recorder import MessageRecorder
    from dodaios.memory.recall import RecallStore, close_open_recall_stores

    APP = []  # the app keeps its bus, so the recorder and its store stay alive

    async def main():
        bus = EventBus()
        APP.append(bus)
        MessageRecorder(RecallStore({db!r})).attach(bus)
        await bus.publish(ResponseGenerated(text="Il est midi."))
        await asyncio.sleep(0.2)
        if {close}:
            await close_open_recall_stores()

    asyncio.run(main())
    print("MAIN RETURNED", flush=True)
    """
)


def _run(tmp_path: Path, *, close: bool) -> subprocess.CompletedProcess[str] | None:
    script = _SCRIPT.format(repo=str(REPO), db=str(tmp_path / "jarvis.db"), close=close)
    try:
        return subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
        )
    except subprocess.TimeoutExpired:
        return None


def test_a_store_left_open_keeps_the_process_alive(tmp_path: Path) -> None:
    """The mechanism itself: main() returns, the interpreter never exits."""
    assert _run(tmp_path, close=False) is None, "an open aiosqlite thread blocks exit"


def test_closing_leftover_stores_lets_the_process_exit(tmp_path: Path) -> None:
    done = _run(tmp_path, close=True)
    assert done is not None, "the process must exit once leftover stores are closed"
    assert done.returncode == 0
    assert "MAIN RETURNED" in done.stdout


@pytest.mark.asyncio
async def test_close_open_recall_stores_closes_each_open_store_once(tmp_path: Path) -> None:
    first = RecallStore(tmp_path / "a.db")
    second = RecallStore(tmp_path / "b.db")
    await first.open()
    await second.open()
    assert await close_open_recall_stores() == 2
    assert first._conn is None and second._conn is None
    assert await close_open_recall_stores() == 0


@pytest.mark.asyncio
async def test_brain_aclose_detaches_its_recorder_and_closes_its_store(tmp_path: Path) -> None:
    bus = EventBus()
    recall = RecallStore(tmp_path / "jarvis.db")
    recorder = MessageRecorder(recall)
    recorder.attach(bus)
    brain = BrainManager.__new__(BrainManager)
    brain._recall = recall
    brain.own_message_recorder(recorder, bus)

    await bus.publish(ResponseGenerated(text="première réponse"))  # i18n-allow: French fixture
    assert recall._conn is not None

    await brain.aclose()
    assert recall._conn is None
    await bus.publish(ResponseGenerated(text="après la fin"))  # i18n-allow: French fixture
    assert recall._conn is None, "a detached recorder must not reopen the store"
    await brain.aclose()  # idempotent
