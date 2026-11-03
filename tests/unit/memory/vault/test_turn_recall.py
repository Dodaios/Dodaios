"""Per-message recall from the memory vault (ADR-0044)."""

from __future__ import annotations

import pytest

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault


@pytest.fixture
def vault(tmp_path):
    v = MemoryVault(tmp_path / "vault.db")
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


def test_recall_brings_matching_memories_that_are_not_always_in_mind(vault):
    vault.remember("I live in Berlin.", "profile")
    vault.remember("We hiked the Zugspitze with Lea last summer.", "episode", entities=["Lea"])
    vault.remember(
        "Lea's birthday is on 14 March.", "reference", entities=["Lea"], sensitivity="sensitive"
    )
    block = vault_runtime.turn_block("When is Lea's birthday?")
    assert block.startswith("## Possibly relevant memories")
    assert "Lea's birthday is on 14 March." in block
    # Already in the always-on block: not repeated.
    assert "I live in Berlin." not in vault_runtime.turn_block("Where do I live, Berlin?")
    used = {m.text: m.use_count for m in vault.list()}
    assert used["Lea's birthday is on 14 March."] == 1


def test_recall_stays_quiet_on_small_talk_and_without_a_vault(vault):
    vault.remember("We hiked the Zugspitze last summer.", "episode")
    assert vault_runtime.turn_block("can you tell me what you know?") == ""
    assert vault_runtime.turn_block("   ") == ""
    vault_runtime.set_active(None)
    assert vault_runtime.turn_block("Zugspitze") == ""


def test_recall_drops_weak_hits_and_respects_the_budget(vault):
    for i in range(20):
        vault.remember(f"Concert number {i} with the jazz band was great.", "episode")
    block = vault_runtime.turn_block("jazz concert")
    lines = [line for line in block.splitlines() if line.startswith("- ")]
    assert 0 < len(lines) <= vault_runtime.TURN_LIMIT
    assert len(block) <= vault_runtime.TURN_MAX_CHARS + 200


@pytest.mark.asyncio
async def test_manager_recall_helper_is_bounded(vault, monkeypatch):
    from dodaios.brain.manager import BrainManager

    vault.remember("We hiked the Zugspitze last summer.", "episode")
    assert "Zugspitze" in await BrainManager._vault_recall("Zugspitze hike")

    def slow(_text: str) -> str:
        import time

        time.sleep(0.5)
        return "late"

    monkeypatch.setattr(vault_runtime, "turn_block", slow)
    assert await BrainManager._vault_recall("anything") == ""
