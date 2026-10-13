"""The Prompt tab's route: improve a prompt, with the target pane's repo as context.

Pinned here: the writer is told about the folder of the pane the prompt is
meant for, the user's pick and instruction reach it unchanged, nothing is
typed into a pane, and each failure keeps its own status.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jarvis.agentic_ide import prompt_improver
from jarvis.agentic_ide import session as session_mod
from jarvis.agentic_ide.prompt_improver import ImprovedPrompt, ImproverFailed, ImproverUnavailable
from jarvis.agentic_ide.session import Registry
from jarvis.ui.web import prompt_improver_routes
from tests.fakes.fake_pty_manager import FakePtyManager

URL = "/api/agentic-ide/prompt-improver"


@pytest.fixture(autouse=True)
def _isolated_recents(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.agentic_ide import recents

    store = tmp_path_factory.mktemp("recents") / "recents.json"
    monkeypatch.setattr(recents, "_store_path", lambda: store)


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Registry:
    monkeypatch.setattr(session_mod, "agent_argv", lambda name: (f"/usr/bin/{name}",))
    reg = Registry(pty_manager=FakePtyManager())
    monkeypatch.setattr(prompt_improver_routes, "get_registry", lambda: reg)
    return reg


@pytest.fixture
def client(registry: Registry) -> TestClient:
    app = FastAPI()
    app.include_router(prompt_improver_routes.router)
    return TestClient(app)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Stands in for the writer and keeps what the route asked of it."""
    seen: list[dict] = []

    async def _improve(prompt: str, **kwargs: object) -> ImprovedPrompt:
        seen.append({"prompt": prompt, **kwargs})
        return ImprovedPrompt(text="Improved.", source="provider:picked", writer="fake-writer")

    monkeypatch.setattr(prompt_improver, "improve", _improve)
    return seen


def test_the_defaults_name_the_instruction_and_the_limits(client: TestClient) -> None:
    body = client.get(URL).json()
    assert body["default_instruction"] == prompt_improver.DEFAULT_INSTRUCTION
    assert body["max_prompt_chars"] == session_mod.MAX_PROMPT_CHARS


async def test_the_writer_is_told_about_the_target_panes_repository(
    client: TestClient, registry: Registry, calls: list[dict], tmp_path: Path
) -> None:
    await registry.start(str(tmp_path), [{"agent": "claude"}])
    assert registry.session is not None
    pane = registry.session.terminals[0]

    response = client.post(
        URL,
        json={
            "prompt": "make it faster",
            "provider": "picked",
            "model": "model-x",
            "instruction": "Tighten it.",
            "workspace": registry.session.id,
            "pane": pane.key,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "improved": "Improved.",
        "source": "provider:picked",
        "writer": "fake-writer",
        "folder": registry.session.folder,
    }
    call = calls[0]
    assert call["prompt"] == "make it faster"
    assert call["folder"] == registry.session.folder
    assert call["profile"] is registry.session.profile
    assert (call["provider"], call["model"], call["instruction"]) == (
        "picked",
        "model-x",
        "Tighten it.",
    )
    # Improving is a preview: the pane was never typed into.
    assert pane.prompts_sent == 0


def test_without_a_workspace_the_prompt_is_still_improved(
    client: TestClient, calls: list[dict]
) -> None:
    response = client.post(URL, json={"prompt": "make it faster"})
    assert response.status_code == 200
    assert calls[0]["folder"] == ""
    assert response.json()["folder"] == ""


def test_an_empty_prompt_is_rejected(client: TestClient, calls: list[dict]) -> None:
    assert client.post(URL, json={"prompt": ""}).status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    ("error", "status"),
    [(ImproverUnavailable("no model"), 409), (ImproverFailed("it died"), 502)],
)
def test_each_failure_keeps_its_own_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, error: Exception, status: int
) -> None:
    async def _improve(_prompt: str, **_kwargs: object) -> ImprovedPrompt:
        raise error

    monkeypatch.setattr(prompt_improver, "improve", _improve)

    response = client.post(URL, json={"prompt": "make it faster"})

    assert response.status_code == status
    assert response.json()["detail"] == str(error)
