"""``SocietyRuntime.started``: true only between ensure_started() and close().

Readers that do not start the runtime themselves (the attention list) use it
to skip a runtime whose store is not open yet, instead of hitting
``SocietyStore: call open() before use``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.society.runtime import SocietyRuntime


async def test_started_follows_the_runtime_lifecycle(tmp_path: Path) -> None:
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False)
    assert runtime.started is False
    with pytest.raises(RuntimeError, match="call open"):
        await runtime.approvals.pending()

    await runtime.ensure_started()
    try:
        assert runtime.started is True
        assert await runtime.approvals.pending() == []
    finally:
        await runtime.close()

    assert runtime.started is False
