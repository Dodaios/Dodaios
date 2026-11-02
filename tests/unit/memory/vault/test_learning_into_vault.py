"""The learning loop writes into the memory vault (ADR-0044, chunk 2).

A scripted reviewer stands in for the model; the vault is a real file.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.memory.learning import notebook as notebook_module
from dodaios.memory.learning.loop import JarvisLearningLoop
from dodaios.memory.learning.notebook import JarvisNotebook, memory_block, snapshot_block
from dodaios.memory.learning.review import Turn
from dodaios.memory.learning.signals import has_signal
from dodaios.memory.vault import reconcile
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.plugins.tool.memory_vault import MemoryForgetTool, MemorySearchTool
from dodaios.plugins.tool.remember import RememberTool


class ScriptedReviewer:
    def __init__(self, *replies: list[dict[str, Any]] | None) -> None:
        self._replies = list(replies)
        self.prompts: list[dict[str, Any]] = []

    async def __call__(self, prompt: str) -> list[dict[str, Any]] | None:
        self.prompts.append(json.loads(prompt))
        return self._replies.pop(0) if self._replies else []


@pytest.fixture
def vault(tmp_path: Path):
    v = MemoryVault(tmp_path / "vault.db")
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


@pytest.fixture(autouse=True)
def _no_active_notebook():
    notebook_module.set_active(None)
    yield
    notebook_module.set_active(None)


def _loop(tmp_path: Path, reviewer: ScriptedReviewer) -> JarvisLearningLoop:
    book = JarvisNotebook(tmp_path / "society", budgets={"user": 600, "memory": 600})
    notebook_reviewer = ScriptedReviewer()
    loop = JarvisLearningLoop(book, notebook_reviewer, vault_reviewer=reviewer)
    loop.notebook_reviewer = notebook_reviewer  # type: ignore[attr-defined]
    return loop


SAID_HOME = "By the way, I live in Hamburg with my wife Lea."
SAID_MOVE = "We just moved, I live in Berlin now."


@pytest.mark.asyncio
async def test_add_then_update_keeps_history(tmp_path, vault):
    assert has_signal(SAID_HOME) and has_signal(SAID_MOVE)
    reviewer = ScriptedReviewer(
        [
            {
                "op": "add",
                "kind": "profile",
                "text": "The user lives in Hamburg.",
                "entities": ["Hamburg"],
                "evidence": "I live in Hamburg",
            }
        ],
    )
    loop = _loop(tmp_path, reviewer)
    loop.record("chat:a", Turn(user=SAID_HOME, channel="chat"))
    assert await loop.review("chat:a") == 1
    first = vault.list()[0]

    reviewer._replies.append(
        [
            {
                "op": "update",
                "id": first.id,
                "text": "The user lives in Berlin.",
                "entities": ["Berlin"],
                "evidence": "I live in Berlin now",
            }
        ]
    )
    loop.record("chat:a", Turn(user=SAID_MOVE, channel="chat"))
    assert await loop.review("chat:a") == 1

    # The second review was shown the stored memory it updated.
    assert [m["id"] for m in reviewer.prompts[1]["memories"]] == [first.id]
    assert [m.text for m in vault.list()] == ["The user lives in Berlin."]
    assert [m.text for m in vault.about("Hamburg")] == ["The user lives in Hamburg."]
    assert loop.notebook_reviewer.prompts == []  # type: ignore[attr-defined]
    assert "The user lives in Berlin." in snapshot_block()


def test_validate_rejects_ungrounded_and_unknown_ids(vault):
    shown = [vault.remember("The user lives in Hamburg.", "profile").memory]
    ops, rejected = reconcile.validate(
        [
            {"op": "add", "kind": "profile", "text": "x", "evidence": "never said this"},
            {"op": "update", "id": "mem_other", "text": "y", "evidence": SAID_HOME},
            {"op": "add", "kind": "diary", "text": "z", "evidence": SAID_HOME},
            {"op": "ephemeral", "text": "z", "evidence": SAID_HOME},
            {"op": "noop"},
            {
                "op": "add",
                "kind": "ephemeral",
                "text": "Dentist tomorrow.",
                "evidence": SAID_HOME,
                "valid_to": "2026-12-01",
            },
            {"op": "invalidate", "id": shown[0].id, "evidence": SAID_HOME},
        ],
        user_texts=[SAID_HOME],
        shown=shown,
    )
    assert [o.op for o in ops] == ["add", "invalidate"]
    assert ops[0].valid_to == "2026-12-01T23:59:59+00:00"
    assert len(rejected) == 4


def test_parse_handles_fences_and_garbage():
    assert reconcile.parse('```json\n{"ops": [{"op": "noop"}]}\n```') == [{"op": "noop"}]
    with pytest.raises(ValueError):
        reconcile.parse("no json here")


@pytest.mark.asyncio
async def test_explicit_request_and_remember_tool_write_to_vault(tmp_path, vault):
    loop = _loop(tmp_path, ScriptedReviewer())
    assert loop._keep_request("remember that I drink my coffee black", "I prefer black coffee.")
    tool = RememberTool()
    ctx = SimpleNamespace(user_utterance="note that my sister is called Mia")
    result = await tool.execute({"fact": "The user's sister is called Mia."}, ctx)
    assert result.success and "Saved to memory" in result.output
    again = await tool.execute({"fact": "The user's sister is called Mia."}, ctx)
    assert "Already in memory" in again.output
    kinds = {m.text: m.kind for m in vault.list()}
    assert kinds == {
        "I prefer black coffee.": "preference",
        "The user's sister is called Mia.": "relationship",
    }
    assert all(m.origin == "user" for m in vault.list())
    assert memory_block().count("I prefer black coffee.") == 1


@pytest.mark.asyncio
async def test_search_and_forget_tools(vault):
    vault.remember("The user's ex is called Sam.", "relationship", entities=["Sam"])
    vault.remember("The user likes jazz.", "preference")
    ctx = SimpleNamespace()
    found = await MemorySearchTool().execute({"query": "Sam"}, ctx)
    assert found.output["memories"][0]["text"] == "The user's ex is called Sam."

    forgot = await MemoryForgetTool().execute({"about": "ex Sam"}, ctx)
    assert forgot.success and "Forgot" in forgot.output
    assert vault.search("Sam") == []
    assert "Sam" not in snapshot_block()
    nothing = await MemorySearchTool().execute({"query": "Sam"}, ctx)
    assert "Nothing in memory" in nothing.output


@pytest.mark.asyncio
async def test_tools_without_a_vault_report_it():
    vault_runtime.set_active(None)
    result = await MemorySearchTool().execute({"query": "x"}, SimpleNamespace())
    assert not result.success


def test_open_from_config_respects_switch_and_path(tmp_path):
    cfg = SimpleNamespace(
        memory=SimpleNamespace(
            data_dir="./data",
            vault=SimpleNamespace(
                enabled=False, path=str(tmp_path / "v.db"), profile_max_chars=800
            ),
        )
    )
    assert vault_runtime.open_from_config(cfg) is None
    cfg.memory.vault.enabled = True
    opened = vault_runtime.open_from_config(cfg)
    try:
        assert opened is not None and opened.path == tmp_path / "v.db"
    finally:
        vault_runtime.set_active(None)
