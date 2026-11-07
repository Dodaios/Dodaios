"""The OpenCode mission worker: routing, and one ACP turn against a scripted agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.missions import init as missions_init
from dodaios.missions.workers import opencode_worker as ow
from dodaios.missions.workers.stream_consumer import ClaudeResult, ClaudeSystemInit

_AGENT = Path(__file__).resolve().parents[2] / "fakes" / "fake_acp_agent.py"


def test_selecting_opencode_routes_the_heavy_task_to_its_own_worker() -> None:
    kind = missions_init._select_subagent_worker_kind("opencode", "")
    assert kind == "opencode"
    # A per-step model cannot divert it to another provider's worker.
    assert missions_init._select_subagent_worker_kind("opencode", "sonnet") == "opencode"


def test_only_a_provider_slug_is_sent_as_the_opencode_model() -> None:
    assert ow._opencode_model("opencode/beam-free") == "opencode/beam-free"
    # Claude aliases the decomposer writes are not OpenCode ids.
    assert ow._opencode_model("sonnet") == ""
    assert ow._opencode_model("") == ""


async def test_one_step_runs_over_acp_and_reports_the_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ow, "_build_opencode_cmd", lambda: [sys.executable, str(_AGENT)])
    worker = ow.OpenCodeWorker()
    events: list[Any] = []
    log_dir = tmp_path / "logs"

    async for event in worker.spawn(
        "hello there",
        worktree=tmp_path,
        env=dict(os.environ),
        job=SimpleNamespace(assign=lambda _pid: None),
        worker_id="m1::0",
        log_dir=log_dir,
        model="opencode/beam-free",
        timeout_s=60.0,
    ):
        events.append(event)

    assert isinstance(events[0], ClaudeSystemInit)
    assert events[0].model == "opencode/opencode/beam-free"
    assert isinstance(events[-1], ClaudeResult)
    assert events[-1].is_error is False
    assert "echo: hello there" in events[-1].result
    # The raw ACP frames are kept as the mission's evidence.
    stream = (log_dir / "stream.jsonl").read_text(encoding="utf-8")
    assert "agent_message_chunk" in stream
    assert "end_turn" in stream
