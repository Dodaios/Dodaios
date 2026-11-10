"""Compacted parts of the lead conversation become episode memories (ADR-0044)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from dodaios.memory.vault import episodes
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault


@pytest.fixture
def vault(tmp_path: Path):
    v = MemoryVault(tmp_path / "vault.db", clock=lambda: "2026-11-09T09:00:00+00:00")
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


class Scripted:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[dict[str, Any]] = []

    async def __call__(self, prompt: str) -> Any:
        self.prompts.append(json.loads(prompt))
        return self.replies.pop(0) if self.replies else []


def test_checkpoint_is_queued_once_and_distilled_into_episodes(vault):
    assert vault_runtime.record_checkpoint("lead:main", 120, "We planned the launch and fixed CI.")
    assert not vault_runtime.record_checkpoint("lead:main", 120, "same checkpoint again")
    reviewer = Scripted(
        [
            {
                "text": "2026-11-09: Planned the product launch for 2026-11-20.",
                "entities": ["Launch"],
            },
            {"text": "x" * 400},
            {"text": ""},
        ]
    )
    assert asyncio.run(episodes.process(vault, reviewer)) == 1
    assert reviewer.prompts == [
        {"day": "2026-11-09", "summary": "We planned the launch and fixed CI."}
    ]
    memory = vault.list(kind="episode")[0]
    assert memory.text.startswith("2026-11-09: Planned the product launch")
    assert memory.source["via"] == "conversation-checkpoint"
    assert "Planned the product launch" not in vault.profile_block()
    assert asyncio.run(episodes.process(vault, Scripted())) == 0


def test_a_failing_reviewer_keeps_the_item_and_a_pause_blocks_queueing(vault):
    vault_runtime.record_checkpoint("lead:main", 10, "Talked about the trip.")

    class Failing:
        async def __call__(self, prompt: str) -> Any:
            return None

    assert asyncio.run(episodes.process(vault, Failing())) == 0
    assert len(episodes._queue(vault)) == 1
    vault.pause_learning("forever")
    assert not vault_runtime.record_checkpoint("lead:main", 20, "Another part.")


def test_lead_compaction_hands_its_checkpoint_to_the_vault(vault, monkeypatch):
    """prepare_history queues the lead's checkpoints, never an agent's."""
    from dodaios.society import conversation

    calls: list[tuple[str, int, str]] = []
    monkeypatch.setattr(
        vault_runtime, "record_checkpoint", lambda s, t, summary: calls.append((s, t, summary))
    )
    source = Path(conversation.__file__).read_text(encoding="utf-8")
    assert 'getattr(session, "surface", "") == "jarvis"' in source
    assert "record_checkpoint(sid, through, summary)" in source
