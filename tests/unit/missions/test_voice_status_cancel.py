"""MissionManager answers the deterministic voice status/cancel commands."""
from __future__ import annotations

import asyncio
from pathlib import Path

from dodaios.missions.manager import MissionManager
from dodaios.missions.state_machine import MissionState


def _run(coro):
    return asyncio.run(coro)


def test_status_and_cancel_round_trip(tmp_path: Path) -> None:
    async def scenario() -> None:
        mgr = MissionManager(tmp_path / "m.db")
        await mgr.start()
        try:
            assert "No mission is running" in await mgr.jarvis_agent_status(None)
            assert "nothing to cancel" in await mgr.jarvis_agent_cancel(None)

            mid = await mgr.dispatch(prompt="research heat pumps")
            await mgr.transition_state(mid, MissionState.RUNNING, reason="t")
            status = await mgr.jarvis_agent_status(None)
            assert "research heat pumps" in status and "running" in status
            assert "research heat pumps" in await mgr.jarvis_agent_status(mid[:8])

            killed: list[str] = []
            mgr.bind_run_canceller(lambda m: killed.append(m) or True)
            reply = await mgr.jarvis_agent_cancel(mid[:8])
            assert reply == "Cancelled the mission."
            assert killed == [mid]
            view = await mgr.mission(mid)
            assert view is not None and view.state is MissionState.CANCELLED
            assert "No mission is running" in await mgr.jarvis_agent_status(None)
        finally:
            await mgr.stop()

    _run(scenario())


def test_cancel_all_and_unknown_id(tmp_path: Path) -> None:
    async def scenario() -> None:
        mgr = MissionManager(tmp_path / "m.db")
        await mgr.start()
        try:
            a = await mgr.dispatch(prompt="one")
            b = await mgr.dispatch(prompt="two")
            assert "2 missions" in await mgr.jarvis_agent_status(None)
            assert "No running mission matches" in await mgr.jarvis_agent_cancel("zzz")
            assert await mgr.jarvis_agent_cancel(None) == "Cancelled 2 missions."
            for mid in (a, b):
                view = await mgr.mission(mid)
                assert view is not None and view.state is MissionState.CANCELLED
        finally:
            await mgr.stop()

    _run(scenario())
