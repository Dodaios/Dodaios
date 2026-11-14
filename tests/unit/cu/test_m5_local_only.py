"""M5 local-only hard-block regressions (offline, no GUI, no billable calls).

Proves that an explicit local-only Computer-Use mission:

* never attempts a nonlocal provider (Codex/ChatGPT, OpenAI, Gemini, ...)
  — not even once, not even through the CU-provider hoist or last resort;
* still serves through local brains (UI-Mate :8000, Ollama/Qwen);
* fails closed with an actionable error when no local brain is reachable;
* leaves normal (non-local-only) missions byte-for-byte on the prior chain.

Fakes only: no real BrainManager, no network.
"""

from __future__ import annotations

from typing import Any

import pytest

from dodaios.core.protocols import ImageBlock
from dodaios.cu.brain_call import (
    CUNoVisionProviderError,
    call_vision_brain,
)
from dodaios.harness.computer_use_planner import ComputerUsePlannerSelector


class _FakeBrain:
    supports_tools = False

    def __init__(self, *, text: str = '{"action": "wait", "ms": 1}', supports_vision: bool = True) -> None:
        self.text = text
        self.supports_vision = supports_vision
        self.calls = 0

    async def complete(self, req: Any):  # type: ignore[no-untyped-def]
        from dodaios.core.protocols import BrainDelta

        self.calls += 1
        if self.text:
            yield BrainDelta(content=self.text)
        yield BrainDelta(finish_reason="stop")

    def estimate_cost(self, req: Any) -> float:
        return 0.0


class _FakeManager:
    active_provider = "codex"

    def __init__(self, brains: dict[str, _FakeBrain], cu_provider: str = "") -> None:
        self.brains = brains
        self._cu_provider_value = cu_provider
        self.requested: list[tuple[str, str | None]] = []

    def _build_fallback_chain(self, level: str) -> list[tuple[str, str | None]]:
        assert level == "fast"
        return [("codex", None), ("openai", None), ("ui-mate", None), ("ollama", None)]

    def _get_brain(self, name: str, model: str | None = None) -> _FakeBrain:
        self.requested.append((name, model))
        return self.brains[name]

    def _cu_model(self, name: str) -> str | None:
        return None

    def _cu_provider(self) -> str:
        return self._cu_provider_value

    def _fast_model(self, provider: str) -> str | None:
        return None


def _prompt(provider: str, brain: Any) -> tuple[str, str]:
    return "system", "user"


def _image() -> list[ImageBlock]:
    return [ImageBlock(mime="image/jpeg", data_b64="QQ==", source_hash="x")]


async def test_local_only_never_attempts_codex_and_serves_local() -> None:
    # ``ollama`` is the portable local representative: it is local on every
    # checkout (spec-derived ``auth_mode == "none"``), while ``ui-mate`` is
    # local only where its provider card is registered.
    manager = _FakeManager(
        {
            "codex": _FakeBrain(),
            "openai": _FakeBrain(),
            "ollama": _FakeBrain(text='{"action": "done"}'),
            "local-openai": _FakeBrain(),
        }
    )
    reply = await call_vision_brain(
        manager, build_prompt=_prompt, images=_image(), local_only=True,
    )
    assert reply.provider == "ollama"
    assert ("codex", None) not in manager.requested
    assert ("openai", None) not in manager.requested
    assert manager.brains["codex"].calls == 0
    assert manager.brains["openai"].calls == 0
    assert manager.brains["ollama"].calls == 1


async def test_local_only_blocks_nonlocal_cu_provider_hoist() -> None:
    # Even when the global CU provider pin points at a nonlocal brain, a
    # local-only mission must not hoist or call it.
    manager = _FakeManager(
        {
            "codex": _FakeBrain(),
            "openai": _FakeBrain(),
            "ollama": _FakeBrain(text='{"action": "done"}'),
            "local-openai": _FakeBrain(),
        },
        cu_provider="codex",
    )
    reply = await call_vision_brain(
        manager, build_prompt=_prompt, images=_image(), local_only=True,
    )
    assert reply.provider == "ollama"
    assert ("codex", None) not in manager.requested


async def test_local_only_fails_closed_without_local_brain() -> None:
    manager = _FakeManager(
        {
            "codex": _FakeBrain(),
            "openai": _FakeBrain(),
        }
    )

    async def _chain_unused() -> None:
        return None

    def _sync_chain(level: str) -> list[tuple[str, str | None]]:
        return [("codex", None), ("openai", None)]

    manager._build_fallback_chain = _sync_chain  # type: ignore[method-assign]
    with pytest.raises(CUNoVisionProviderError, match="local-only"):
        await call_vision_brain(
            manager, build_prompt=_prompt, images=_image(), local_only=True,
        )
    assert manager.requested == []


async def test_normal_mission_chain_unchanged() -> None:
    # Default (local_only=False) keeps the prior behavior: the chain head
    # (codex here) is attempted first.
    manager = _FakeManager(
        {
            "codex": _FakeBrain(text='{"action": "done"}'),
            "openai": _FakeBrain(),
            "ui-mate": _FakeBrain(),
            "ollama": _FakeBrain(),
        }
    )
    reply = await call_vision_brain(
        manager, build_prompt=_prompt, images=_image(), local_only=False,
    )
    assert reply.provider == "codex"
    assert manager.requested[0] == ("codex", None)


async def test_selector_local_only_skips_nonlocal_before_get_brain() -> None:
    manager = _FakeManager(
        {
            "codex": _FakeBrain(),
            "ollama": _FakeBrain(),
        }
    )
    selector = ComputerUsePlannerSelector(
        manager=manager,
        chain=[("codex", None), ("ollama", None)],
        local_only=True,
    )
    yielded = list(selector.iter_candidates(images_attached=True))
    assert [p for _, p, _, _ in yielded] == ["ollama"]
    assert manager.requested == [("ollama", None)]
    assert selector.nonlocal_blocked == 1
    assert any(e.kind == "nonlocal_blocked" for e in selector.errors)


async def test_selector_default_still_yields_nonlocal() -> None:
    manager = _FakeManager(
        {
            "codex": _FakeBrain(),
            "ui-mate": _FakeBrain(),
        }
    )
    selector = ComputerUsePlannerSelector(
        manager=manager, chain=[("codex", None), ("ui-mate", None)],
    )
    yielded = list(selector.iter_candidates(images_attached=True))
    assert [p for _, p, _, _ in yielded] == ["codex", "ui-mate"]


async def test_is_local_only_mission_flag_matrix() -> None:
    from types import SimpleNamespace

    from dodaios.cu.engine import _is_local_only_mission

    assert _is_local_only_mission(SimpleNamespace(env={"JARVIS_CU_LOCAL_ONLY": "1"}), SimpleNamespace()) is True
    assert _is_local_only_mission(SimpleNamespace(env={"JARVIS_CU_LOCAL_ONLY": "true"}), SimpleNamespace()) is True
    assert _is_local_only_mission(SimpleNamespace(env={}), SimpleNamespace(local_only=True)) is True
    assert _is_local_only_mission(SimpleNamespace(env={}), SimpleNamespace()) is False
    assert _is_local_only_mission(SimpleNamespace(env={"JARVIS_CU_LOCAL_ONLY": "0"}), SimpleNamespace()) is False
