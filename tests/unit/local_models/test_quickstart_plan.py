"""The plan behind "Use a free local model" (dodaios/brain/ollama_quickstart.py).

Pins: an installed model that fits wins over a download, a machine without
Ollama still gets a pick from the shortlist, the hardware is named in one
sentence, and the route answers the same plan on pull-capable cards only.
"""

from __future__ import annotations

from typing import Any

import pytest

from dodaios.brain import ollama_pull, ollama_quickstart, ollama_roles, ollama_runtime

ROWS: list[dict[str, Any]] = [
    {
        "id": "qwen3.5",
        "label": "Qwen 3.5 9B",
        "size_gb": 6.6,
        "role": "chat",
        "installed": False,
        "fit": "comfortable",
        "fit_note": "Fits in the 16 GB of graphics memory.",
        "recommended": True,
        "recommended_for": ["chat", "vision"],
    },
    {
        "id": "granite4.1:3b",
        "label": "Granite 4.1 3B",
        "size_gb": 2.1,
        "role": "chat",
        "installed": False,
        "fit": "comfortable",
        "fit_note": "",
        "recommended": False,
        "recommended_for": [],
    },
]


def _runtime(installed: bool, running: bool) -> dict[str, Any]:
    return {
        "installed": installed,
        "running": running,
        "starting": False,
        "host_kind": "local",
        "detail": "Ollama is not installed on this machine." if not installed else "ok",
    }


class _Spec:
    def __init__(self, role_id: str) -> None:
        self.id = role_id


class _State:
    def __init__(self, role_id: str, recommended: str, reason: str) -> None:
        self.spec = _Spec(role_id)
        self.recommended = recommended
        self.recommended_reason = reason


@pytest.fixture
def machine(monkeypatch: pytest.MonkeyPatch):
    def setup(
        *,
        installed: list[str],
        runtime: dict[str, Any],
        chat_pick: str = "",
        roles_fail: bool = False,
    ) -> None:
        async def _recommendations() -> dict[str, Any]:
            return {
                "models": [dict(r) for r in ROWS],
                "installed": installed,
                "memory_gb": 32.0,
                "accelerator_gb": 16.0,
                "accelerator_source": "nvidia",
                "server_reachable": runtime["running"],
            }

        async def _list_roles(root: str, cfg: Any, **_kw: Any):
            if roles_fail:
                raise RuntimeError("boom")
            return [_State("chat", chat_pick, "Largest installed model that fits.")], None

        monkeypatch.setattr(ollama_pull, "recommendations", _recommendations)
        monkeypatch.setattr(ollama_runtime, "runtime_status", lambda: runtime)
        monkeypatch.setattr(ollama_roles, "list_roles", _list_roles)
        monkeypatch.setattr(ollama_pull, "server_root", lambda: "http://localhost:11434")

    return setup


async def test_fresh_machine_gets_the_shortlist_pick(machine) -> None:
    machine(installed=[], runtime=_runtime(False, False), roles_fail=True)
    plan = await ollama_quickstart.quickstart_plan(object())
    assert plan["model"] == "qwen3.5"
    assert plan["label"] == "Qwen 3.5 9B"
    assert plan["installed"] is False
    assert plan["size_gb"] == 6.6
    assert plan["runtime"] == {
        "installed": False,
        "running": False,
        "starting": False,
        "host_kind": "local",
        "detail": "Ollama is not installed on this machine.",
    }
    assert plan["hardware"]["summary"] == "This computer: 16 GB graphics memory, 32 GB RAM."


async def test_an_installed_model_wins_over_a_download(machine) -> None:
    machine(
        installed=["qwen3:8b"],
        runtime=_runtime(True, True),
        chat_pick="qwen3:8b",
    )
    plan = await ollama_quickstart.quickstart_plan(object())
    assert plan["model"] == "qwen3:8b"
    assert plan["installed"] is True
    # Not on the shortlist: the name stands in for the label, nothing invented.
    assert plan["label"] == "qwen3:8b"
    assert plan["size_gb"] is None
    assert plan["reason"] == "Largest installed model that fits."


async def test_latest_tag_counts_as_installed(machine) -> None:
    machine(installed=["qwen3.5:latest"], runtime=_runtime(True, True), chat_pick="qwen3.5")
    plan = await ollama_quickstart.quickstart_plan(object())
    assert plan["installed"] is True


def test_hardware_sentence_without_readings() -> None:
    assert ollama_quickstart.hardware_sentence(None, 0.0) == (
        "This computer's memory could not be read."
    )
    assert ollama_quickstart.hardware_sentence(8.0, 0.0) == "This computer: 8 GB RAM."


def test_route_answers_the_plan_on_pull_capable_cards_only(machine, monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from dodaios.core.bus import EventBus
    from dodaios.core.config import JarvisConfig
    from dodaios.ui.web.server import WebServer

    machine(installed=[], runtime=_runtime(False, False), roles_fail=True)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    cfg = JarvisConfig()
    cfg.ui.dev_mode = True
    srv = WebServer(cfg, bus=EventBus())
    srv.app.state.config = cfg
    with TestClient(srv.app) as client:
        ok = client.get("/api/providers/ollama/local-models/quickstart")
        refused = client.get("/api/providers/openai/local-models/quickstart")
    assert ok.status_code == 200, ok.text
    assert ok.json()["model"] == "qwen3.5"
    assert refused.status_code == 400
